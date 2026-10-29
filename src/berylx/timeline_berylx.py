"""Timeline integration through the existing async EffectTree interpreter."""

from __future__ import annotations

import inspect
import math
from collections.abc import Mapping, Sequence

from .core import BerylxError, Err, Focus, Ok
from .effect_tree import EffectTree
from .timeline import Timeline, TimelineError, _IdentityRegistry

BERYLX_HUMAN_LOGIN = "berylx_timeline_human_login"


async def wait_for_human_login(performer, task):
    result = performer.perform(BERYLX_HUMAN_LOGIN, task)
    if inspect.isawaitable(result):
        await result


class BerylxTimeline:
    _roots = _IdentityRegistry()

    def __init__(self, root, timeline):
        self.root, self.timeline, self._active_plan = root, timeline, None

    @classmethod
    def for_root(cls, root, clock):
        timeline = Timeline.for_execution(root, clock)
        existing = cls._roots.get(root)
        if existing is not None:
            return existing
        connection = cls(root, timeline)
        cls._roots.put(root, connection)
        return connection

    def human_login(self, label):
        return self.timeline.human_login(label, lambda observation: False)

    def workflow(self, label, node, when=None):
        async def execute(observation):
            if self._active_plan is None:
                raise TimelineError(
                    "PLAN_NOT_ISSUED", "Issue the Berylx Timeline before starting it"
                )
            await self._active_plan.run_workflow(task, node)

        task = self.timeline.ai(label, execute, when)
        return task

    def issue(self):
        plan = BerylxTimelinePlan(self.root, self.timeline.issue())
        self._active_plan = plan
        return plan


class BerylxTimelinePlan:
    def __init__(self, root, executable):
        self.root, self.executable, self._results = root, executable, {}

    @property
    def observation(self):
        return self.executable.observation

    def result(self, task):
        return self._results.get(task)

    async def start(self):
        await self.executable.start()

    async def advance(self):
        await self.executable.advance()

    async def emit(self, event=None, **kwargs):
        await self.executable.emit(event, **kwargs)

    async def run_workflow(self, task, node):
        base = self.root.to_lay()

        def login(payload):
            if getattr(payload, "kind", None) != "human-login" or not isinstance(
                getattr(payload, "label", None), str
            ):
                raise TimelineError(
                    "INVALID_LOGIN_WAIT",
                    "Human login effect requires a predeclared human-login task",
                )
            return self.executable.wait_for_human_login(payload)

        async def around(tag, payload, inner):
            if tag != EffectTree.TASK:
                output = inner(payload)
                return await output if inspect.isawaitable(output) else output
            if (
                not isinstance(payload, Sequence)
                or not payload
                or not isinstance(getattr(payload[0], "name", None), str)
            ):
                raise TypeError("berylx task observation requires a named task payload")
            name = payload[0].name
            await self.emit(
                {"type": "berylx-task-started", "task": task, "details": {"node": name}}
            )
            try:
                output = inner(payload)
                result = await output if inspect.isawaitable(output) else output
                await self.emit(
                    {
                        "type": "berylx-task-failed"
                        if isinstance(result, Err)
                        else "berylx-task-completed",
                        "task": task,
                        "details": {"node": name},
                    }
                )
                return result
            except Exception:
                await self.emit(
                    {"type": "berylx-task-failed", "task": task, "details": {"node": name}}
                )
                raise

        handlers = EffectTree.around_async({BERYLX_HUMAN_LOGIN: login}, around)
        result = await EffectTree.run_async(node, self.root.to_lay(), handlers)
        if isinstance(result, Err):
            self._results[task] = result
            raise _WorkflowFailure(result)
        try:
            self.executable.assert_commit_allowed()
            merged = _merge_concurrent(self.root.to_lay(), result.focus, base)
            self.root.commit(merged)
            self._results[task] = Ok(merged)
        except Exception as error:
            failed = Err(
                result.focus,
                BerylxError.from_exception(error, failed_node=task.label, trace=[task.label]),
            )
            self._results[task] = failed
            raise _WorkflowFailure(failed) from error


class _WorkflowFailure(Exception):
    def __init__(self, result):
        super().__init__(result.message)
        self.result = result


_MISSING = object()


def _sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _equal(left, right, seen=None):
    if left is right:
        return True
    if left is _MISSING or right is _MISSING:
        return False
    seen = set() if seen is None else seen
    pair = (id(left), id(right))
    if pair in seen:
        return True
    seen.add(pair)
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        return (
            isinstance(left, Mapping)
            and isinstance(right, Mapping)
            and len(left) == len(right)
            and all(key in right and _equal(value, right[key], seen) for key, value in left.items())
        )
    if _sequence(left) or _sequence(right):
        return (
            _sequence(left)
            and _sequence(right)
            and len(left) == len(right)
            and all(_equal(a, b, seen) for a, b in zip(left, right))
        )
    if type(left) in (int, float) and type(right) in (int, float):
        # Match Object.is: NaN equals NaN, but +0 and -0 differ.
        if isinstance(left, float) and math.isnan(left):
            return isinstance(right, float) and math.isnan(right)
        if left == 0 and right == 0:
            return math.copysign(1, left) == math.copysign(1, right)
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, (str, bool, type(None))):
        return left == right
    # Nonplain objects are compared by identity upstream (handled first).
    return False


def _show(value):
    return {"missing": True} if value is _MISSING else value


def _merge_value(current, completed, base, path):
    current_changed = not _equal(current, base)
    completed_changed = not _equal(completed, base)
    if not completed_changed:
        return current
    if not current_changed:
        return completed
    if _equal(current, completed):
        return current
    if (
        isinstance(current, Mapping)
        and isinstance(completed, Mapping)
        and (base is _MISSING or isinstance(base, Mapping))
    ):
        return _merge_records(current, completed, {} if base is _MISSING else base, path)
    raise BerylxError.create(
        "merge_conflict",
        "merge conflict at " + ".".join(map(str, path)),
        metadata={
            "path": path,
            "current": _show(current),
            "completed": _show(completed),
            "base": _show(base),
        },
    )


def _merge_records(current, completed, base, path=()):
    keys = dict.fromkeys([*base, *current, *completed])
    merged = {}
    for key in keys:
        value = _merge_value(
            current.get(key, _MISSING),
            completed.get(key, _MISSING),
            base.get(key, _MISSING),
            [*path, key],
        )
        if value is not _MISSING:
            merged[key] = value
    return merged


def _merge_concurrent(current, completed, base):
    a, b, original = current.to_object(), completed.to_object(), base.to_object()
    if all(isinstance(value, Mapping) for value in (a, b, original)):
        return Focus.of(_merge_records(a, b, original))
    if _equal(a, original):
        return completed
    if _equal(b, original) or _equal(a, b):
        return current
    raise BerylxError.create(
        "merge_conflict",
        "concurrent non-object state conflict",
        metadata={"current": a, "completed": b, "base": original},
    )
