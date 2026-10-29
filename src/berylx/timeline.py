"""Clock-driven execution plans; ported from berylx-ts 24aabcd.

An issued plan is inert until start. Ready AI work runs concurrently; human work
is completed by events. No wall-clock sleeps or credentials are required.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import secrets
import time
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


class TimelineError(Exception):
    def __init__(self, code: str, message: str, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, dict(details or {})
        alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
        milliseconds = int(time.time() * 1000)
        prefix = ""
        for _ in range(10):
            prefix = alphabet[milliseconds % 32] + prefix
            milliseconds //= 32
        self.trace_id = prefix + "".join(secrets.choice(alphabet) for _ in range(16))

    def to_json(self):
        return dict(
            code=self.code, message=self.message, details=self.details, trace_id=self.trace_id
        )


@dataclass(frozen=True, eq=False)
class TaskRef:
    kind: str
    label: str


@dataclass(frozen=True)
class TimelineEvent:
    type: str
    at: datetime
    task: TaskRef | None = None
    details: Any = None
    origin: Any = None


class Observation:
    def __init__(self, plan):
        self.events = tuple(plan._observed)
        self._plan = plan

    def state(self, task):
        try:
            return self._plan._states[task]
        except (KeyError, TypeError):
            raise TimelineError("UNKNOWN_TASK", "Task does not belong to this plan") from None

    def has_event(self, event_type):
        return any(event.type == event_type for event in self._plan._observed)


class _Predicates:
    @staticmethod
    def event(event_type):
        return lambda observation: observation.has_event(event_type)

    @staticmethod
    def completed(task):
        return lambda observation: observation.state(task) == "completed"

    @staticmethod
    def all(*parts):
        return lambda observation: all(part(observation) for part in parts)

    @staticmethod
    def any(*parts):
        return lambda observation: any(part(observation) for part in parts)


predicates = _Predicates()


@dataclass
class _TaskDefinition:
    ref: TaskRef
    when: Callable
    run: Callable | None = None
    recurring_event: str | None = None


@dataclass
class _Origin:
    type: str
    at: datetime
    origin: dict
    recurrence: Any = None


class _IdentityRegistry:
    """Weak identity keys when possible, strong keys for non-weakrefable tokens."""

    def __init__(self):
        self.entries = {}

    def get(self, token):
        entry = self.entries.get(id(token))
        if entry is None:
            return None
        key, weak, value, weak_value = entry
        if (key() if weak else key) is not token:
            return None
        return value() if weak_value else value

    def put(self, token, value):
        identity = id(token)
        try:
            key = weakref.ref(token, lambda ref: self.entries.pop(identity, None))
            weak = True
        except TypeError:
            key, weak = token, False
        weak_value = False
        if weak:
            # The token owns its cache: registry roots cannot retain a
            # connection -> Root cycle. GC collects the cycle with the token.
            try:
                setattr(token, f"_berylx_identity_cache_{id(self)}", value)
                value = weakref.ref(value)
                weak_value = True
            except (AttributeError, TypeError):
                pass
        self.entries[identity] = (key, weak, value, weak_value)


def _instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("an aware datetime is required")
    return value.astimezone(timezone.utc)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


_CRON = {
    "minute": (0, 59),
    "hour": (0, 23),
    "dayOfMonth": (1, 31),
    "month": (1, 12),
    "dayOfWeek": (0, 6),
}


def _normalize_cron(selection):
    normalized = {}
    for key, (minimum, maximum) in _CRON.items():
        alias = {"dayOfMonth": "day_of_month", "dayOfWeek": "day_of_week"}.get(key, key)
        value = selection.get(key, selection.get(alias))
        if value is None:
            continue
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        if not values or any(
            not isinstance(v, int) or isinstance(v, bool) or not minimum <= v <= maximum
            for v in values
        ):
            raise TimelineError("INVALID_CRON", f"Invalid UTC cron {key} selection")
        normalized[key] = tuple(sorted(set(values)))
    return normalized


def _next_cron(lower, selection):
    candidate = _instant(lower)
    if candidate.second or candidate.microsecond:
        candidate = candidate.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = candidate + timedelta(days=366 * 40)

    def includes(key, value):
        return key not in selection or value in selection[key]

    while candidate <= limit:
        if not (
            includes("month", candidate.month)
            and includes("dayOfMonth", candidate.day)
            and includes("dayOfWeek", (candidate.weekday() + 1) % 7)
        ):
            candidate = (candidate + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif not includes("hour", candidate.hour):
            candidate = (candidate + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        elif not includes("minute", candidate.minute):
            candidate += timedelta(minutes=1)
        else:
            return candidate
    raise TimelineError("INVALID_CRON", "UTC cron selection has no occurrence within 40 years")


class Timeline:
    _roots = _IdentityRegistry()

    def __init__(self, clock):
        self._clock, self._tasks, self._origins, self._issued = clock, [], [], False

    @classmethod
    def for_execution(cls, execution, clock):
        existing = cls._roots.get(execution)
        if existing is not None:
            if existing._clock is not clock:
                raise TimelineError(
                    "CLOCK_CONFLICT", "An execution already has a Timeline with another Clock"
                )
            return existing
        root = cls(clock)
        cls._roots.put(execution, root)
        return root

    def _ensure_draft(self):
        if self._issued:
            raise TimelineError("ALREADY_ISSUED", "Timeline has already issued its plan")

    def _add(self, kind, label, when, run=None, recurring_event=None):
        self._ensure_draft()
        ref = TaskRef(kind, label)
        self._tasks.append(
            _TaskDefinition(ref, when or (lambda observation: True), run, recurring_event)
        )
        return ref

    def ai(self, label, run, when=None):
        if not callable(run):
            raise TimelineError("INVALID_TASK", "AI task requires a runner")
        return self._add("ai", label, when, run)

    def recurring(self, label, event_type, run, when=None):
        if not event_type or not callable(run):
            raise TimelineError(
                "INVALID_TASK", "Recurring AI task requires an event type and runner"
            )
        return self._add("ai", label, when, run, event_type)

    def user(self, label, when=None):
        return self._add("user", label, when)

    def human_login(self, label, when=None):
        return self._add("human-login", label, when)

    def beat(self, origin):
        self._ensure_draft()
        beat, bpm, every = origin["beat"], origin["bpm"], origin.get("every")
        if (
            not _finite(bpm)
            or bpm <= 0
            or not _finite(beat)
            or beat < 0
            or (every is not None and (not _finite(every) or every <= 0))
        ):
            raise TimelineError("INVALID_BEAT", "Beat and BPM must be finite; BPM must be positive")
        try:
            start = _instant(origin.get("from", origin.get("from_")))
            at = start + timedelta(milliseconds=int(beat * 60_000 / bpm))
            if (
                every is not None
                and start + timedelta(milliseconds=int((beat + every) * 60_000 / bpm)) <= at
            ):
                raise ValueError("interval does not advance time")
        except (ValueError, OverflowError, TypeError):
            raise TimelineError(
                "INVALID_BEAT", "Beat origin and interval must advance finite time"
            ) from None
        recurrence = None if every is None else ("beat", every, bpm, start)
        self._origins.append(
            _Origin(origin["type"], at, {"kind": "beat", "beat": beat, "bpm": bpm}, recurrence)
        )
        return self

    def calendar(self, origin):
        self._ensure_draft()
        try:
            at = _instant(origin["at"])
        except (ValueError, TypeError):
            raise TimelineError("INVALID_CALENDAR", "Invalid calendar time") from None
        every, cron = origin.get("every"), origin.get("cron")
        if every and cron is not None:
            raise TimelineError("INVALID_CALENDAR", "Calendar origin cannot combine every and cron")
        if cron is not None:
            selection = _normalize_cron(cron)
            self._origins.append(
                _Origin(
                    origin["type"],
                    _next_cron(at, selection),
                    {"kind": "calendar", "cron": selection},
                    ("cron", selection),
                )
            )
        else:
            if every not in (None, "minute", "hour", "day"):
                raise TimelineError("INVALID_CALENDAR", "Unknown calendar interval")
            self._origins.append(
                _Origin(
                    origin["type"],
                    at,
                    {"kind": "calendar"},
                    None if every is None else ("calendar", every),
                )
            )
        return self

    def issue(self):
        self._ensure_draft()
        self._issued = True
        return ExecutablePlan(
            self._clock,
            list(self._tasks),
            [
                _Origin(origin.type, origin.at, dict(origin.origin), origin.recurrence)
                for origin in self._origins
            ],
        )


class ExecutablePlan:
    def __init__(self, clock, tasks, origins):
        self._clock, self._tasks, self._scheduled = clock, tasks, origins
        self._states = {task.ref: "pending" for task in tasks}
        self._observed = []
        self._started = False
        self._advancing = None
        self._fatal = None
        self._human_waiters = {}
        self._cursors = {task.ref: 0 for task in tasks if task.recurring_event}
        self._active = {}
        self._completed = []
        self._advance_waiters = []
        self._wake = asyncio.Event()

    @property
    def observation(self):
        return Observation(self)

    async def start(self):
        if self._started:
            raise TimelineError("ALREADY_STARTED", "Plan has already started")
        self._started = True
        await self.advance()

    async def advance(self):
        if not self._started:
            raise TimelineError("NOT_STARTED", "Start the plan before advancing it")
        if self._fatal:
            raise self._fatal
        if self._advancing is not None:
            future = asyncio.get_running_loop().create_future()
            self._advance_waiters.append([set(self._active), set(), False, future])
            self._wake.set()
            await future
            return
        self._advancing = asyncio.create_task(self._schedule())
        await self._advancing

    async def emit(self, event=None, **kwargs):
        event = dict(event or {}, **kwargs)
        if not self._started:
            raise TimelineError("NOT_STARTED", "Start the plan before emitting events")
        if self._fatal:
            raise self._fatal
        task = event.get("task")
        if event["type"] == "human-completed":
            if (
                not isinstance(task, TaskRef)
                or task not in self._states
                or task.kind == "ai"
                or self._states[task] != "waiting"
            ):
                raise TimelineError(
                    "INVALID_COMPLETION", "Human completion requires a waiting human task"
                )
            self._states[task] = "completed"
            for waiter in self._human_waiters.pop(task, []):
                if not waiter.done():
                    waiter.set_result(None)
        self._observed.append(
            TimelineEvent(event["type"], _instant(self._clock.now()), task, event.get("details"))
        )
        if self._advancing is not None:
            self._wake.set()
            return
        await self.advance()

    async def wait_for_human_login(self, task):
        if not self._started:
            raise TimelineError("NOT_STARTED", "Start the plan before waiting for human login")
        if self._fatal:
            raise self._fatal
        if not isinstance(task, TaskRef) or task not in self._states or task.kind != "human-login":
            raise TimelineError(
                "INVALID_LOGIN_WAIT", "Human login wait requires a predeclared human-login task"
            )
        state = self._states[task]
        if state == "completed":
            return
        if state == "failed":
            raise TimelineError("INVALID_LOGIN_WAIT", "Human login task is no longer waitable")
        if state == "pending":
            self._states[task] = "waiting"
        waiter = asyncio.get_running_loop().create_future()
        self._human_waiters.setdefault(task, []).append(waiter)
        await waiter

    def assert_commit_allowed(self):
        if self._fatal:
            raise self._fatal

    def _record_due(self):
        now = _instant(self._clock.now())
        for origin in list(self._scheduled):
            while origin.at <= now:
                self._observed.append(
                    TimelineEvent(origin.type, origin.at, origin=dict(origin.origin))
                )
                recurrence = origin.recurrence
                if recurrence is None:
                    self._scheduled.remove(origin)
                    break
                if recurrence[0] == "calendar":
                    origin.at += {
                        "minute": timedelta(minutes=1),
                        "hour": timedelta(hours=1),
                        "day": timedelta(days=1),
                    }[recurrence[1]]
                elif recurrence[0] == "cron":
                    origin.at = _next_cron(origin.at + timedelta(minutes=1), recurrence[1])
                else:
                    _, every, bpm, start = recurrence
                    beat = origin.origin["beat"] + every
                    next_at = start + timedelta(milliseconds=int(beat * 60_000 / bpm))
                    if next_at <= origin.at:
                        raise TimelineError(
                            "INVALID_BEAT", "Recurring beat interval must advance time"
                        )
                    origin.at = next_at
                    origin.origin = {"kind": "beat", "beat": beat, "bpm": bpm}

    def _occurrence(self, task):
        cursor = self._cursors[task.ref]
        while cursor < len(self._observed):
            event = self._observed[cursor]
            if event.type == task.recurring_event:
                self._cursors[task.ref] = cursor
                if not task.when(self.observation):
                    return None
                self._cursors[task.ref] = cursor + 1
                return event
            cursor += 1
        self._cursors[task.ref] = cursor
        return None

    async def _run_task(self, task, occurrence):
        try:
            output = (
                task.run(self.observation, occurrence)
                if task.recurring_event
                else task.run(self.observation)
            )
            if inspect.isawaitable(output):
                await output
            # JavaScript await yields even for an immediate non-Promise result.
            # Keep all ready runners running until their completion continuation.
            await asyncio.sleep(0)
            if self._fatal:
                self._states[task.ref] = "failed"
                return self._fatal
            self._states[task.ref] = "completed"
            return None
        except Exception:
            self._states[task.ref] = "failed"
            return self._fatal or TimelineError(
                "TASK_FAILED", "AI task failed", {"task": task.ref.label}
            )

    def _fail(self, error):
        if self._fatal:
            return
        self._fatal = error
        for ref, state in self._states.items():
            if state in ("running", "waiting"):
                self._states[ref] = "failed"
        for waiters in self._human_waiters.values():
            for future in waiters:
                if not future.done():
                    future.set_exception(error)
        self._human_waiters.clear()
        for _, _, _, future in self._advance_waiters:
            if not future.done():
                future.set_exception(error)
        self._advance_waiters.clear()
        self._wake.set()

    async def _schedule(self):
        try:
            while True:
                self._wake.clear()
                self._record_due()
                for waiter in self._advance_waiters:
                    waiter[2] = True
                for task in self._tasks:
                    if (
                        self._states[task.ref] == "pending"
                        and task.ref.kind != "ai"
                        and task.when(self.observation)
                    ):
                        self._states[task.ref] = "waiting"
                launched = False
                for task in self._tasks:
                    if (
                        task.ref.kind != "ai"
                        or self._states[task.ref] in ("running", "failed")
                        or task.ref in self._active
                    ):
                        continue
                    occurrence = self._occurrence(task) if task.recurring_event else None
                    ready = (
                        occurrence is not None
                        if task.recurring_event
                        else self._states[task.ref] == "pending" and task.when(self.observation)
                    )
                    if not ready:
                        continue
                    self._states[task.ref] = "running"
                    self._active[task.ref] = asyncio.create_task(self._run_task(task, occurrence))
                    self._active[task.ref].add_done_callback(
                        lambda execution, ref=task.ref: self._completed.append(ref)
                    )
                    for baseline, pending, _, _future in self._advance_waiters:
                        if task.ref not in baseline:
                            pending.add(task.ref)
                    launched = True
                if not launched:
                    for waiter in list(self._advance_waiters):
                        _, pending, seen, future = waiter
                        if seen and not pending:
                            self._advance_waiters.remove(waiter)
                            if not future.done():
                                future.set_result(None)
                if not self._active:
                    return
                wake_task = asyncio.create_task(self._wake.wait())
                try:
                    await asyncio.wait(
                        [*self._active.values(), wake_task], return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    wake_task.cancel()
                    await asyncio.gather(wake_task, return_exceptions=True)
                # Like Promise.race, observe one completion per evaluation pass.
                # Callback order preserves completion order, not declaration order.
                while self._completed:
                    ref = self._completed.pop(0)
                    execution = self._active.pop(ref, None)
                    if execution is None:
                        continue
                    for _, pending, _, _ in self._advance_waiters:
                        pending.discard(ref)
                    failure = execution.result()
                    if failure:
                        self._fail(failure)
                        raise failure
                    break
        finally:
            self._advancing = None


class KeyframeTrack:
    def __init__(self):
        self._frames = []

    def place(self, at, value):
        try:
            at = _instant(at)
            if not _finite(value):
                raise ValueError()
        except (ValueError, TypeError):
            raise TimelineError(
                "INVALID_KEYFRAME", "Keyframe time and value must be finite"
            ) from None
        self._frames = [(t, v) for t, v in self._frames if t != at]
        self._frames.append((at, value))
        self._frames.sort(key=lambda frame: frame[0])
        return self

    def sample(self, at):
        if not self._frames:
            raise TimelineError("EMPTY_TRACK", "Keyframe track is empty")
        try:
            at = _instant(at)
        except (ValueError, TypeError):
            raise TimelineError("INVALID_SAMPLE", "Invalid sample time") from None
        if at <= self._frames[0][0]:
            return self._frames[0][1]
        for index in range(1, len(self._frames)):
            right_at, right_value = self._frames[index]
            if at <= right_at:
                left_at, left_value = self._frames[index - 1]
                return left_value + (right_value - left_value) * (
                    (at - left_at) / (right_at - left_at)
                )
        return self._frames[-1][1]

    def generate(self, at):
        return [self.sample(instant) for instant in at]
