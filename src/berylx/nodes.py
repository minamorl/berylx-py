"""Workflow descriptions; interpretation lives in effect_tree."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import Parameter, signature
from typing import Generic, TypeVar

from .core import ControlSignal, Err, ResultOps
from .darkcore import await_maybe
from .merge import Merge

S = TypeVar("S")


def arity(block):
    """JS Function.length adaptation: positional parameters before first default."""
    count = 0
    for parameter in signature(block).parameters.values():
        if parameter.kind not in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            break
        if parameter.default is not Parameter.empty:
            break
        count += 1
    return count


def invoke(block, *args):
    """Python zero-parameter callbacks cannot ignore surplus arguments like JS."""
    parameters = signature(block).parameters.values()
    if any(p.kind == Parameter.VAR_POSITIONAL for p in parameters):
        return block(*args)
    positional = sum(
        p.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD) for p in parameters
    )
    return block(*args[:positional])


class Node(Generic[S]):
    def call(self, focus):
        from .effect_tree import EffectTree

        return EffectTree.run(self, focus)

    def then(self, other):
        return Sequence([self, other])

    pipe = then
    __rshift__ = then

    def par(self, other):
        return Parallel([self, other])

    __and__ = par

    def rescue_with(self, handler=None, name="rescue", block=None):
        handler = RescueBlock(name or "rescue", block) if block else handler
        if handler is None:
            raise ValueError("rescue_with requires a task or block")
        return Rescue(self, handler)

    def compile(self):
        from .graph import Graph

        return Graph.from_node(self)

    def nodes(self):
        return [self]


class Task(Node[S]):
    def __init__(self, name, block):
        if not callable(block):
            raise TypeError("Task requires a block")
        self.name, self.block = str(name), block

    @classmethod
    def of(cls, name, block):
        return cls(name, block)

    def effectful(self):
        return arity(self.block) >= 2

    def _invoke(self, root, performer):
        if self.effectful():
            if performer is None:
                raise RuntimeError(f"task {self.name} performs effects; run through a handler map")
            return invoke(self.block, root, performer)
        return invoke(self.block, root)

    def _context(self, result):
        if isinstance(result, Err) and not result.failed_node:
            return Err(result.focus, result.error.prepend_trace(self.name))
        return result

    def call(self, focus, performer=None):
        root = ResultOps.coerce_focus(focus)
        try:
            return self._context(ResultOps.normalize(self._invoke(root, performer)))
        except ControlSignal:
            raise
        except Exception as e:
            return ResultOps.err(
                root, type(e).__name__, str(e), cause=e, failed_node=self.name, trace=[self.name]
            )


class AsyncTask(Task[S]):
    def call(self, focus, performer=None):
        raise RuntimeError(f'AsyncTask "{self.name}" is asynchronous: use run_async or call_async')

    async def call_async(self, focus, performer=None):
        root = ResultOps.coerce_focus(focus)
        try:
            return self._context(
                ResultOps.normalize(await await_maybe(self._invoke(root, performer)))
            )
        except ControlSignal:
            raise
        except Exception as e:
            return ResultOps.err(
                root, type(e).__name__, str(e), cause=e, failed_node=self.name, trace=[self.name]
            )


class Sequence(Node[S]):
    steps: tuple[Node, ...]

    def __init__(self, steps):
        self.steps = tuple(
            child
            for step in steps
            for child in (step.steps if isinstance(step, Sequence) else [step])
        )

    def nodes(self):
        return [leaf for step in self.steps for leaf in step.nodes()]


class Parallel(Node[S]):
    branches: tuple[Node, ...]

    def __init__(self, branches, reducer=None, on_err="short_circuit"):
        self.branches = tuple(
            child
            for branch in branches
            for child in (branch.branches if isinstance(branch, Parallel) else [branch])
        )
        self.reducer = reducer if reducer is not None else Merge.strict()
        self.on_err = on_err

    def par(self, other):
        return Parallel([*self.branches, other], self.reducer, self.on_err)

    def reduce(self, reducer):
        return Parallel(self.branches, reducer, self.on_err)

    def accumulate(self):
        return Parallel(self.branches, self.reducer, "accumulate")

    def short_circuit(self):
        return Parallel(self.branches, self.reducer, "short_circuit")

    def nodes(self):
        return [leaf for branch in self.branches for leaf in branch.nodes()]


@dataclass(frozen=True)
class Predicate:
    name: str
    block: object
    else_branch: bool = False


@dataclass(frozen=True)
class BranchArm:
    predicate: Predicate
    body: Node


class When:
    def __init__(self, name, block=None, else_branch=False):
        if not callable(block) and not else_branch:
            raise TypeError("When requires a predicate block")
        self.predicate = Predicate(str(name), block, else_branch)

    @classmethod
    def of(cls, name, block):
        return cls(name, block)

    def then(self, body):
        return Branch([BranchArm(self.predicate, body)])


Else = When("else", else_branch=True)


class Branch(Node[S]):
    def __init__(self, arms):
        self.arms = tuple(arms)

    def or_else(self, other):
        return Branch([*self.arms, *other.arms])

    def nodes(self):
        return [leaf for arm in self.arms for leaf in arm.body.nodes()]


class RescueBlock:
    def __init__(self, name, block):
        self.name, self.block = str(name), block

    def effectful(self):
        return arity(self.block) >= 3

    def call(self, focus, error_result, performer=None):
        try:
            error = error_result.cause if error_result.cause is not None else error_result.error
            args = (error, focus, performer) if self.effectful() else (error, focus)
            result = ResultOps.normalize(invoke(self.block, *args))
            return (
                Err(result.focus, result.error.prepend_trace(self.name))
                if isinstance(result, Err) and not result.failed_node
                else result
            )
        except ControlSignal:
            raise
        except Exception as e:
            return ResultOps.err(
                focus, type(e).__name__, str(e), cause=e, failed_node=self.name, trace=[self.name]
            )

    def nodes(self):
        return [self]


class Catch(Node[S]):
    def __init__(self, name="catch", handler=None, *, fatal=False, block=None):
        self.name = str(name)
        self.handler = RescueBlock(name, block) if block else handler
        self._fatal = fatal
        if self.handler is None:
            raise ValueError("Catch requires a task or block")

    @classmethod
    def of(cls, *args, **kwargs):
        return cls(*args, **kwargs)

    def catches(self, result):
        return not result.error.fatal() or self._fatal

    def nodes(self):
        return self.handler.nodes()


class Rescue(Node[S]):
    def __init__(self, body, handler):
        self.body, self.handler = body, handler

    def nodes(self):
        return [*self.body.nodes(), *self.handler.nodes()]


class Workflow(Node[S]):
    def __init__(self, name, body):
        self.name, self.body = str(name), body

    @classmethod
    def of(cls, name, build):
        return cls(name, build())

    def call(self, focus):
        from .core import Flow

        return Flow.of(focus).call(self.body)

    def then(self, other):
        return self.body.then(other)

    def par(self, other):
        return self.body.par(other)

    def rescue_with(self, *args, **kwargs):
        return self.body.rescue_with(*args, **kwargs)

    def compile(self):
        from .graph import Graph

        return Graph.from_node(self.body, self.name)

    def nodes(self):
        return self.body.nodes()
