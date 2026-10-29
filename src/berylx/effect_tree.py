"""Compile workflow semantics into Darkcore Effect trees and substitute handlers."""

import asyncio
from dataclasses import dataclass
from typing import Any

from . import darkcore as d
from .core import BerylxError, ControlSignal, Err, Focus, Ok, ResultOps
from .nodes import (
    AsyncTask,
    Branch,
    Catch,
    Parallel,
    Rescue,
    RescueBlock,
    Sequence,
    Task,
    arity,
    invoke,
)

TASK = "berylx_task"
PARALLEL = "berylx_parallel"
BRANCH = "berylx_branch"
RESCUE = "berylx_rescue"
RECOVER = "berylx_recover"
RESERVED = (TASK, PARALLEL, BRANCH, RESCUE, RECOVER)


class Perform:
    def __init__(self, handlers):
        self.handlers = handlers

    def perform(self, tag, payload=None):
        if tag == d.PURE:
            raise ValueError("pure is reserved")
        if tag not in self.handlers:
            raise KeyError(f"no handler for effect: {tag}")
        return self.handlers[tag](payload)


def decode_result(value):
    if not isinstance(value, (Ok, Err)):
        raise TypeError("berylx effect handler must return Ok or Err")
    return value


def decode_payload(tag, payload):
    classes: dict[str, Any] = {
        TASK: Task,
        PARALLEL: Parallel,
        BRANCH: Branch,
        RESCUE: Rescue,
        RECOVER: (Rescue, Catch),
    }
    if (
        not isinstance(payload, (tuple, list))
        or len(payload) != 2
        or not isinstance(payload[0], classes[tag])
        or not isinstance(payload[1], Err if tag == RECOVER else Focus)
    ):
        raise TypeError(f"{tag} payload must be [node, Focus/Err]")
    return payload


def build(node, focus):
    focus = ResultOps.coerce_focus(focus)
    if isinstance(node, Sequence):
        effect = d.pure(Ok(focus))
        for step in node.steps:

            def continue_with(previous, current_step=step):
                return compile_step(current_step, previous)

            effect = effect.bind(continue_with)
        return effect
    if isinstance(node, Catch):
        return d.pure(Ok(focus))
    for cls, tag in ((Task, TASK), (Parallel, PARALLEL), (Branch, BRANCH), (Rescue, RESCUE)):
        if isinstance(node, cls):
            return d.op(tag, (node, focus), decode_result)
    raise TypeError(f"EffectTree does not support {type(node).__name__}")


def compile_step(step, previous):
    if isinstance(step, Catch):
        return (
            d.op(RECOVER, (step, previous), decode_result)
            if isinstance(previous, Err) and step.catches(previous)
            else d.pure(previous)
        )
    return d.pure(previous) if isinstance(previous, Err) else build(step, previous.focus)


def run(node, focus, handlers=None):
    return d.run(build(node, focus), real_handlers() if handlers is None else handlers)


async def run_async(node, focus, handlers=None):
    return await d.run_async(
        build(node, focus), async_real_handlers() if handlers is None else handlers
    )


def branch_matches(predicate, focus):
    return predicate.else_branch or bool(invoke(predicate.block, focus))


def parallel_result(node, focus, results):
    failures = [r for r in results if isinstance(r, Err)]
    if failures:
        first = failures[0]
        if node.on_err == "short_circuit":
            return first
        error = BerylxError(
            "parallel_failed",
            f"{len(failures)} parallel branch{'' if len(failures) == 1 else 'es'} failed",
            cause=first.cause,
            failed_node=first.failed_node,
            trace=first.trace,
            parallel_errors=[r.error for r in failures],
        )
        return Err(first.focus, error)
    try:
        acc = focus
        for result in results:
            args = (acc, result.focus, focus) if arity(node.reducer) == 3 else (acc, result.focus)
            acc = invoke(node.reducer, *args)
        return ResultOps.ok(acc)
    except ControlSignal:
        raise
    except Exception as e:
        return ResultOps.err(
            focus, BerylxError.from_exception(e, failed_node="parallel", trace=["parallel"])
        )


def rescue_failed(original, result):
    return (
        Err(
            result.focus,
            result.error.with_context(metadata={"rescuedError": original.error.to_object()}),
        )
        if isinstance(result, Err)
        else result
    )


def real_handlers(effects=None, subtree=None):
    effects = {} if effects is None else effects
    if set(effects).intersection(RESERVED):
        raise ValueError("effect tags collide with berylx tags")
    handlers: dict[str, Any] = {}

    def dispatch(tag, payload):
        node, value = decode_payload(tag, payload)
        current = handlers if subtree is None else subtree
        if tag == TASK:
            return node.call(value, Perform(current))
        if tag == PARALLEL:
            results, thrown = [], []
            for child in node.branches:
                try:
                    results.append(run(child, value, current))
                except Exception as e:
                    thrown.append(e)
            if thrown:
                raise thrown[0]
            return parallel_result(node, value, results)
        if tag == BRANCH:
            for arm in node.arms:
                if branch_matches(arm.predicate, value):
                    return run(arm.body, value, current)
            return ResultOps.err(value, "no_branch_matched")
        if tag == RESCUE:
            result = run(node.body, value, current)
            return (
                result
                if isinstance(result, Ok)
                else d.run(d.op(RECOVER, (node, result), decode_result), current)
            )
        recovery = node.handler
        result = (
            recovery.call(value.focus, value, Perform(current))
            if isinstance(recovery, RescueBlock)
            else run(recovery, value.focus, current)
        )
        return rescue_failed(value, result)

    for tag in RESERVED:
        handlers[tag] = lambda payload, tag=tag: dispatch(tag, payload)
    handlers.update(effects)
    return handlers


def async_real_handlers(effects=None, subtree=None):
    effects = {} if effects is None else effects
    if set(effects).intersection(RESERVED):
        raise ValueError("effect tags collide with berylx tags")
    handlers: dict[str, Any] = {}

    async def dispatch(tag, payload):
        node, value = decode_payload(tag, payload)
        current = handlers if subtree is None else subtree
        if tag == TASK:
            if isinstance(node, AsyncTask):
                return await node.call_async(value, Perform(current))
            return node.call(value, Perform(current))
        if tag == PARALLEL:
            results = await asyncio.gather(
                *(run_async(child, value, current) for child in node.branches),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            return parallel_result(node, value, results)
        if tag == BRANCH:
            for arm in node.arms:
                if branch_matches(arm.predicate, value):
                    return await run_async(arm.body, value, current)
            return ResultOps.err(value, "no_branch_matched")
        if tag == RESCUE:
            result = await run_async(node.body, value, current)
            return (
                result
                if isinstance(result, Ok)
                else await d.run_async(d.op(RECOVER, (node, result), decode_result), current)
            )
        recovery = node.handler
        result = (
            recovery.call(value.focus, value, Perform(current))
            if isinstance(recovery, RescueBlock)
            else await run_async(recovery, value.focus, current)
        )
        return rescue_failed(value, result)

    for tag in RESERVED:
        handlers[tag] = lambda payload, tag=tag: dispatch(tag, payload)
    handlers.update(effects)
    return handlers


def around(effects=None, wrapper=None):
    if wrapper is None:
        raise ValueError("around requires a wrapper")
    wrapped: dict[str, Any] = {}
    for tag, handler in real_handlers(effects, wrapped).items():
        wrapped[tag] = lambda payload, tag=tag, handler=handler: wrapper(tag, payload, handler)
    return wrapped


def around_async(effects=None, wrapper=None):
    if wrapper is None:
        raise ValueError("around_async requires a wrapper")
    wrapped: dict[str, Any] = {}
    for tag, handler in async_real_handlers(effects, wrapped).items():
        wrapped[tag] = lambda payload, tag=tag, handler=handler: wrapper(tag, payload, handler)
    return wrapped


@dataclass(frozen=True)
class DryRun:
    result: object
    steps: list[str]


def dry_run(node, focus):
    steps = []
    handlers: dict[str, Any] = {}

    def dispatch(tag, payload):
        node, focus = decode_payload(tag, payload)
        if tag == TASK:
            steps.append(node.name)
        elif tag == PARALLEL:
            for child in node.branches:
                run(child, focus, handlers)
        elif tag == BRANCH:
            for arm in node.arms:
                if branch_matches(arm.predicate, focus):
                    run(arm.body, focus, handlers)
                    break
        elif tag == RESCUE:
            run(node.body, focus, handlers)
        return Ok(focus)

    for tag in (TASK, PARALLEL, BRANCH, RESCUE):
        handlers[tag] = lambda payload, tag=tag: dispatch(tag, payload)
    return DryRun(run(node, focus, handlers), steps)


class EffectTree:
    TASK, PARALLEL, BRANCH, RESCUE, RECOVER = RESERVED
    build = staticmethod(build)
    run = staticmethod(run)
    run_subtree = staticmethod(run)
    run_async = staticmethod(run_async)
    run_subtree_async = staticmethod(run_async)
    real_handlers = staticmethod(real_handlers)
    async_real_handlers = staticmethod(async_real_handlers)
    around = staticmethod(around)
    around_async = staticmethod(around_async)
    dry_run = staticmethod(dry_run)
    branch_matches = staticmethod(branch_matches)
