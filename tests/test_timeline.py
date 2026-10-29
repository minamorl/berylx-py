"""Pinned 24aabcd Timeline observations, specified before implementation (P2)."""

import asyncio
import re
from datetime import datetime, timedelta, timezone

import pytest

from berylx.core import Err, Ok, Root
from berylx.nodes import AsyncTask, Task
from berylx.timeline import KeyframeTrack, Timeline, TimelineError, predicates
from berylx.timeline_berylx import BerylxTimeline, wait_for_human_login


class Clock:
    def __init__(self):
        self.current = datetime(2026, 9, 26, tzinfo=timezone.utc)

    def now(self):
        return self.current


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 2))


async def eventually(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    assert predicate()


def test_issue_is_lazy_singleton_and_locked():
    async def scenario():
        clock, token, seen = Clock(), Root.of({}), []
        timeline = Timeline.for_execution(token, clock)
        assert Timeline.for_execution(token, clock) is timeline
        with pytest.raises(TimelineError) as error:
            Timeline.for_execution(token, Clock())
        assert error.value.code == "CLOCK_CONFLICT"
        task = timeline.ai("one", lambda obs: seen.append("one"))
        plan = timeline.issue()
        assert seen == []
        assert plan.observation.state(task) == "pending"
        with pytest.raises(TimelineError):
            timeline.user("too late")
        await plan.start()
        assert seen == ["one"]
        assert plan.observation.state(task) == "completed"
        with pytest.raises(TimelineError):
            await plan.start()

    run(scenario())


def test_human_completion_and_predicates():
    async def scenario():
        timeline = Timeline.for_execution(Root.of({}), Clock())
        human = timeline.user("review")
        seen = []
        task = timeline.ai(
            "next",
            lambda obs: seen.append("next"),
            predicates.all(predicates.completed(human), predicates.event("human-completed")),
        )
        plan = timeline.issue()
        await plan.start()
        assert plan.observation.state(human) == "waiting"
        assert plan.observation.state(task) == "pending"
        await plan.emit({"type": "human-completed", "task": human})
        assert seen == ["next"]
        with pytest.raises(TimelineError) as error:
            await plan.emit({"type": "human-completed", "task": human})
        envelope = error.value.to_json()
        assert list(envelope) == ["code", "message", "details", "trace_id"]
        assert envelope["code"] == "INVALID_COMPLETION"
        assert re.fullmatch("[0-9A-HJKMNP-TV-Z]{26}", envelope["trace_id"])

    run(scenario())


def test_runner_can_await_emit_without_deadlock():
    async def scenario():
        timeline = Timeline.for_execution(Root.of({}), Clock())
        human = timeline.user("approve")
        seen = []
        timeline.ai("dependent", lambda obs: seen.append("dependent"), predicates.completed(human))

        async def publish(obs):
            await plan.emit({"type": "human-completed", "task": human})
            seen.append("published")

        timeline.ai("publisher", publish)
        plan = timeline.issue()
        await plan.start()
        assert sorted(seen) == ["dependent", "published"]

    run(scenario())


def test_external_event_releases_work_while_other_runner_waits():
    async def scenario():
        timeline = Timeline.for_execution(Root.of({}), Clock())
        gate = asyncio.Event()
        seen = []

        async def slow(obs):
            await gate.wait()

        slow_ref = timeline.ai("slow", slow)
        next_ref = timeline.ai("next", lambda obs: seen.append(1), predicates.event("go"))
        plan = timeline.issue()
        starting = asyncio.create_task(plan.start())
        await eventually(lambda: plan.observation.state(slow_ref) == "running")
        await plan.emit({"type": "go"})
        await eventually(lambda: plan.observation.state(next_ref) == "completed")
        assert not starting.done()
        gate.set()
        await starting
        assert seen == [1]

    run(scenario())


def test_beat_cron_recurring_once_and_advance_during_active_work():
    async def scenario():
        clock = Clock()
        timeline = Timeline.for_execution(Root.of({}), clock)
        timeline.beat(
            {"type": "pulse", "beat": 0.25, "every": 0.25, "bpm": 120, "from": clock.now()}
        )
        timeline.calendar(
            {
                "type": "cron",
                "at": clock.now(),
                "cron": {"minute": [1, 3], "hour": 0, "dayOfMonth": 26, "month": 9, "dayOfWeek": 6},
            }
        )
        pulses, minutes = [], []
        timeline.recurring("pulse", "pulse", lambda obs, event: pulses.append(event.origin["beat"]))
        timeline.recurring("cron", "cron", lambda obs, event: minutes.append(event.at.minute))
        plan = timeline.issue()
        await plan.start()
        clock.current += timedelta(milliseconds=375)
        await plan.advance()
        assert pulses == [0.25, 0.5, 0.75]
        await plan.advance()
        assert pulses == [0.25, 0.5, 0.75]
        clock.current = datetime(2026, 9, 26, 0, 3, tzinfo=timezone.utc)
        await plan.advance()
        assert minutes == [1, 3]

    run(scenario())


def test_keyframe_linear_clamp_replace_and_validation():
    clock = Clock()
    track = KeyframeTrack().place(clock.now(), 0).place(clock.now() + timedelta(seconds=10), 20)
    assert track.sample(clock.now() + timedelta(seconds=2.5)) == 5
    assert track.generate(
        [clock.now() - timedelta(seconds=1), clock.now() + timedelta(seconds=11)]
    ) == [0, 20]
    track.place(clock.now(), 4)
    assert track.sample(clock.now()) == 4
    with pytest.raises(TimelineError):
        KeyframeTrack().sample(clock.now())
    with pytest.raises(TimelineError):
        track.place(clock.now(), float("nan"))


def test_bridge_success_failure_and_observed_leaf_events():
    async def scenario():
        root = Root.of({"count": 0})
        connection = BerylxTimeline.for_root(root, Clock())
        node = Task.of("inc", lambda focus: focus.at("count").set(1))
        ref = connection.workflow("workflow", node)
        plan = connection.issue()
        assert root.state() == {"count": 0}
        await plan.start()
        assert isinstance(plan.result(ref), Ok)
        assert root.state() == {"count": 1}
        assert [(event.type, event.details["node"]) for event in plan.observation.events] == [
            ("berylx-task-started", "inc"),
            ("berylx-task-completed", "inc"),
        ]
        root2 = Root.of({"stable": True})
        connection2 = BerylxTimeline.for_root(root2, Clock())
        ref2 = connection2.workflow(
            "bad", Task.of("reject", lambda focus: focus.put("partial", True).reject("bad"))
        )
        plan2 = connection2.issue()
        with pytest.raises(TimelineError) as error:
            await plan2.start()
        assert error.value.code == "TASK_FAILED"
        assert isinstance(plan2.result(ref2), Err)
        assert plan2.result(ref2).focus.to_object() == {"stable": True, "partial": True}
        assert root2.state() == {"stable": True}

    run(scenario())


@pytest.mark.parametrize(
    "initial,replacement", [(0, 1), ([1], [1, 2]), ({"a": 1}, {"b": 2}), ({"a": 1}, 7)]
)
def test_bridge_replaces_unchanged_roots(initial, replacement):
    async def scenario():
        root = Root.of(initial)
        connection = BerylxTimeline.for_root(root, Clock())
        connection.workflow("replace", Task.of("replace", lambda focus: replacement))
        await connection.issue().start()
        assert root.state() == replacement

    run(scenario())


@pytest.mark.parametrize(
    "base,paused,immediate,expected,conflict",
    [
        (
            {"a": 1, "stable": True},
            {"stable": True},
            {"a": 1, "stable": True, "b": 2},
            {"stable": True, "b": 2},
            False,
        ),
        ({"a": 1}, {}, {"a": 2}, {"a": 2}, True),
        (0, 1, 2, 2, True),
        ({"a": 1}, {"a": 2}, {"a": 2}, {"a": 2}, False),
    ],
)
def test_login_wait_concurrent_commit_and_deletion(base, paused, immediate, expected, conflict):
    async def scenario():
        root = Root.of(base)
        connection = BerylxTimeline.for_root(root, Clock())
        login = connection.human_login("login")

        async def delayed(focus, performer):
            await wait_for_human_login(performer, login)
            return paused

        delayed_ref = connection.workflow("delayed", AsyncTask.of("delayed", delayed))
        immediate_ref = connection.workflow(
            "immediate", Task.of("immediate", lambda focus: immediate)
        )
        plan = connection.issue()
        starting = asyncio.create_task(plan.start())
        await eventually(lambda: plan.observation.state(immediate_ref) == "completed")
        assert plan.observation.state(login) == "waiting"
        await plan.emit({"type": "human-completed", "task": login})
        if conflict:
            with pytest.raises(TimelineError):
                await starting
            assert plan.result(delayed_ref).code == "merge_conflict"
        else:
            await starting
            assert isinstance(plan.result(delayed_ref), Ok)
        assert root.state() == expected

    run(scenario())


def test_fatal_failure_rejects_login_and_prevents_late_commits():
    async def scenario():
        root = Root.of({"stable": True})
        connection = BerylxTimeline.for_root(root, Clock())
        login = connection.human_login("never")
        gate = asyncio.Event()

        async def waiting(focus, performer):
            await wait_for_human_login(performer, login)
            return focus.put("authenticated", True)

        async def slow(focus):
            await gate.wait()
            return focus.put("late", True)

        connection.workflow("waiting", AsyncTask.of("waiting", waiting))
        connection.workflow("slow", AsyncTask.of("slow", slow))

        def fail(obs):
            raise ValueError("failure")

        connection.timeline.ai("fatal", fail)
        plan = connection.issue()
        with pytest.raises(TimelineError):
            await plan.start()
        assert root.state() == {"stable": True}
        gate.set()
        for _ in range(30):
            await asyncio.sleep(0)
        assert root.state() == {"stable": True}
        with pytest.raises(TimelineError):
            await plan.emit({"type": "human-completed", "task": login})

    run(scenario())


def test_advance_flushes_new_time_work_without_waiting_for_old_login():
    async def scenario():
        clock = Clock()
        root = Root.of({"done": False})
        connection = BerylxTimeline.for_root(root, clock)
        login = connection.human_login("login")

        async def delayed(focus, performer):
            await wait_for_human_login(performer, login)
            return focus.put("done", True)

        connection.workflow("delayed", AsyncTask.of("delayed", delayed))
        connection.timeline.beat({"type": "pulse", "beat": 1, "bpm": 1, "from": clock.now()})
        seen = []
        connection.timeline.recurring("pulse", "pulse", lambda obs, event: seen.append("pulse"))
        plan = connection.issue()
        starting = asyncio.create_task(plan.start())
        await eventually(lambda: plan.observation.state(login) == "waiting")
        clock.current += timedelta(minutes=1)
        await asyncio.wait_for(plan.advance(), 0.5)
        assert seen == ["pulse"]
        assert not starting.done()
        await plan.emit({"type": "human-completed", "task": login})
        await starting
        assert root.state() == {"done": True}

    run(scenario())


def test_invalid_origins_and_plan_lifecycle_are_explicit():
    async def scenario():
        clock = Clock()
        timeline = Timeline.for_execution(object(), clock)
        for origin in [
            {"type": "bad", "beat": -1, "bpm": 120, "from": clock.now()},
            {"type": "bad", "beat": 1, "bpm": 0, "from": clock.now()},
            {"type": "bad", "beat": 1, "bpm": 120, "every": 0, "from": clock.now()},
        ]:
            with pytest.raises(TimelineError) as error:
                timeline.beat(origin)
            assert error.value.code == "INVALID_BEAT"
        with pytest.raises(TimelineError):
            timeline.calendar({"type": "bad", "at": clock.now(), "cron": {"minute": 60}})
        with pytest.raises(TimelineError):
            timeline.calendar({"type": "bad", "at": clock.now(), "cron": {}, "every": "minute"})
        plan = timeline.issue()
        for operation in [plan.advance(), plan.emit({"type": "event"})]:
            with pytest.raises(TimelineError) as error:
                await operation
            assert error.value.code == "NOT_STARTED"
        other = Timeline.for_execution(object(), clock).user("foreign")
        with pytest.raises(TimelineError) as error:
            plan.observation.state(other)
        assert error.value.code == "UNKNOWN_TASK"

    run(scenario())


def test_bridge_nested_nodes_observed_and_login_reused():
    async def scenario():
        root = Root.of({"ready": True})
        clock = Clock()
        connection = BerylxTimeline.for_root(root, clock)
        assert BerylxTimeline.for_root(root, clock) is connection
        login = connection.human_login("authentication")

        async def authenticate(focus, performer):
            await wait_for_human_login(performer, login)
            return focus.put("authenticated", True)

        first = connection.workflow("first", AsyncTask.of("authenticate", authenticate))

        async def reuse(focus, performer):
            await wait_for_human_login(performer, login)
            return focus.put("reused", True)

        second = connection.workflow(
            "second", AsyncTask.of("reuse", reuse), predicates.completed(first)
        )
        nested = Task.of("left", lambda f: f.put("left", 1)).par(
            Task.of("right", lambda f: f.put("right", 2))
        )
        nested = nested.then(
            Task.of("bad", lambda f: f.reject("expected")).rescue_with(
                Task.of("heal", lambda f: f.put("healed", True))
            )
        )
        connection.workflow("nested", nested)
        plan = connection.issue()
        starting = asyncio.create_task(plan.start())
        await eventually(lambda: plan.observation.state(login) == "waiting")
        await plan.emit({"type": "human-completed", "task": login})
        await starting
        assert plan.observation.state(second) == "completed"
        assert root.state() == {
            "ready": True,
            "authenticated": True,
            "reused": True,
            "left": 1,
            "right": 2,
            "healed": True,
        }
        events = [
            (event.type, event.details["node"])
            for event in plan.observation.events
            if event.type.startswith("berylx-task-")
        ]
        assert ("berylx-task-failed", "bad") in events
        assert ("berylx-task-completed", "heal") in events

    run(scenario())


def test_ready_sync_runners_observe_first_still_running():
    async def scenario():
        timeline = Timeline.for_execution(object(), Clock())
        seen = []
        first = timeline.ai("first", lambda obs: None)
        timeline.ai("second", lambda obs: seen.append(obs.state(first)))
        await timeline.issue().start()
        assert seen == ["running"]

    run(scenario())


def test_unhashable_forged_task_completion_is_structured_error():
    async def scenario():
        timeline = Timeline.for_execution(object(), Clock())
        timeline.user("real")
        plan = timeline.issue()
        await plan.start()
        with pytest.raises(TimelineError) as error:
            await plan.emit({"type": "human-completed", "task": {"kind": "user", "label": "fake"}})
        assert error.value.code == "INVALID_COMPLETION"

    run(scenario())


def test_bridge_identity_cache_does_not_retain_discarded_roots():
    import gc
    import weakref

    root = Root.of({})
    connection = BerylxTimeline.for_root(root, Clock())
    connection.workflow("retained closure", Task.of("noop", lambda focus: focus))
    root_ref, connection_ref = weakref.ref(root), weakref.ref(connection)
    del root, connection
    gc.collect()
    assert root_ref() is None
    assert connection_ref() is None


def test_timeline_merge_distinguishes_signed_zero_and_equates_nan():
    from berylx.core import BerylxError, Focus
    from berylx.timeline_berylx import _merge_concurrent

    with pytest.raises(BerylxError) as error:
        _merge_concurrent(Focus.of(2), Focus.of(-0.0), Focus.of(0.0))
    assert error.value.code == "merge_conflict"
    current = Focus.of(float("nan"))
    assert _merge_concurrent(current, Focus.of(float("nan")), Focus.of(0)) is current
