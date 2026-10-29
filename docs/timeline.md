# Timeline and Berylx integration

This module ports the scheduler and workflow bridge from berylx-ts revision
`24aabcd6059547f15b5b2817592e3d0dd4f258bb`. It executes real asynchronous
workflows through the same `EffectTree`; task graphs and dry runs alone are not
used as an execution substitute.

A clock exposes `now()` returning an aware `datetime`. `Timeline.for_execution`
shares a timeline by execution-token identity. Registration describes work;
`issue()` locks the draft and returns an inert plan. Only `await plan.start()`
starts work. A plan starts once. `advance()` reevaluates due times and predicates.
No timer thread or background polling is installed.

```python
from datetime import datetime, timezone
from berylx.timeline import Timeline, predicates

class Clock:
    def now(self):
        return datetime.now(timezone.utc)

token = object()
timeline = Timeline.for_execution(token, Clock())
review = timeline.user("review")
timeline.ai("publish", lambda observation: print("approved"),
            predicates.completed(review))
plan = timeline.issue()
# Inside an async function:
# await plan.start()
# await plan.emit({"type": "human-completed", "task": review})
```

AI runners receive an `Observation`; they may return normally or return an
awaitable. Recurring runners additionally receive their triggering
`TimelineEvent`. Tasks use identity-bearing `TaskRef` objects, not labels as IDs.
Events expose `type`, `at`, `task`, `details`, and `origin` attributes.
`Observation.events` snapshots the event sequence while `state(task)` and
`has_event(type)` read the current plan. State names are `pending`, `running`,
`waiting`, `completed`, and `failed`.

Ready AI runners execute concurrently. Human work waits for a `human-completed`
event. An AI runner may safely await `emit`: during an active scheduler pass it
records the event and queues another pass without waiting on itself. External
`advance()` during active work waits for the newly requested pass and new work,
without waiting on previously active login requests. A fatal runner failure
produces a structured `TimelineError`, rejects pending login waits, and prevents
late workflow commits. The scheduler does not forcibly cancel arbitrary runner
side effects.

`Timeline.beat` accepts a mapping with `type`, `beat`, `bpm`, `from` (or `from_`),
and optional repeating `every`. `Timeline.calendar` accepts `type`, aware `at`,
and either `every` (`minute`, `hour`, `day`) or a UTC `cron` selection. Cron
supports minute/hour/day/month/weekday integers or lists; both day selectors must
match when both are specified. Both `dayOfMonth`/`dayOfWeek` and Python
`day_of_month`/`day_of_week` keys work. Due occurrences are recorded in origin
registration order, with each origin's backlog in time order. `recurring` runs
once for each newly observed matching event, whereas ordinary `ai` is one-shot.

`KeyframeTrack.place(at, value)` inserts or replaces finite numeric frames;
`sample` linearly interpolates and clamps outside the endpoints. `generate`
samples a sequence of requested instants.

## Workflow bridge

`BerylxTimeline.for_root(root, clock)` uses the same Root as the timeline token.
`workflow(label, node, when=None)` registers a workflow. Its plan retains each
workflow's `Ok` or `Err` through `result(task)` and emits
`berylx-task-started`, `berylx-task-completed`, and `berylx-task-failed` events
for executed leaves, including nested recovery.

The bridge's `human_login(label)` predeclares a login task without starting it.
An `AsyncTask` callback receives Perform and calls
`await wait_for_human_login(performer, login_ref)`. Human completion resumes all
waiters; later workflows can reuse the completed login. No credentials are
accepted, stored, or inferred.

Only successful workflows commit. Concurrent commits compare current state,
completed state, and the original snapshot. Independent changes and deletions
merge; incompatible updates or deletion versus update yield `merge_conflict`.
Scalar and array replacements work when the other side has not changed. This
commit merge deliberately differs from `Merge.strict`'s upstream missing-key
policy. Failed results keep partial state without changing Root.

## Python adaptations and limits

- Method names are snake_case. Clock/time APIs use timezone-aware Python
  datetimes instead of JavaScript Date. Naive datetimes are rejected. Beat
  timestamps are truncated to millisecond offsets as in JavaScript Date; Python
  calendar/keyframe datetimes retain microseconds.
- Runners use Python's explicit callback arity: ordinary AI receives one
  observation, recurring AI receives observation and occurrence. Python does
  not silently ignore extra JavaScript arguments.
- Events are frozen dataclass records and the event sequence is a tuple.
  Details/origin mappings retain their data semantics. Task references compare
  by identity.
- For attribute-bearing weakrefable tokens (including Root), the token owns its
  cached Timeline/connection and the registry holds weak values. Dropping Root
  and connection references allows cyclic garbage collection, even after
  workflow registration. Non-weakrefable tokens are retained strongly; weakrefable
  tokens that cannot own attributes fall back to a weak key with a strong value.
  Such fallback tokens should be reused deliberately; Python has no direct
  equivalent of JavaScript WeakMap's ephemeron garbage collection.
- Timeline errors expose `to_json()` with code/message/details/trace_id. IDs use
  the ULID alphabet and timestamp prefix with a random suffix, not an ordered
  cross-process ID guarantee.
- Calendar calculations use Python's datetime year range. The cron search
  horizon is 40 times 366 days rather than JavaScript's calendar-year endpoint.
  Ordinary supported UTC schedules are equivalent; extreme year boundaries
  are not claimed equivalent. Unknown calendar intervals are rejected.
- Coroutine scheduling preserves event/state observations and concurrency
  barriers, not JavaScript microtask tick counts. External cancellation of a
  Python coroutine is not specified by the TypeScript API.

## Regression evidence and phase order

Before implementation, `tests/test_timeline.py` specified concrete state,
result, event, conflict, and concurrency observations. The P2 command was:

```sh
PYTHONPATH=src /tmp/berylx-timeline-venv/bin/python -m pytest -q tests/test_timeline.py
```

It exited **2**, with `ModuleNotFoundError: No module named 'berylx.timeline'`
(one collection error in 0.09s), confirming the missing implementation. Raw log:
`/tmp/berylx-timeline-p2-red.log`. The parent reviewed this and released P3.

After implementing the scheduler and bridge, the same command exited **0**:
`23 passed in 0.14s`. Raw log: `/tmp/berylx-timeline-p3.log`. This covered plan
identity/laziness, human predicates, reentrant emit, concurrent wakeups,
beat/cron recurrence, keyframes, nested task events, login reuse, partial-state
failure, object/scalar/list replacements, deletion conflicts, new timed work
while login waits, and prevention of late commits after failure. The first 17
cases were green before two additional source-derived regression cases were
added. These are regression/unit tests, not property tests; property execution
requires the subsequent phase barrier.

## Review corrections

Independent review supplied two concrete upstream observations. Before fixes, the
added tests produced exit 1: `2 failed, 19 passed in 0.24s`. The runtime now yields
a completion continuation after every successful AI runner, including synchronous
runners: the second ready runner observes the first as `running`, matching TS.
Forged unhashable task references now produce structured `INVALID_COMPLETION`
rather than leaking Python TypeError. Raw review RED is in
`/tmp/berylx-timeline-review-red.log`.

The following raw outputs preserve the original phase evidence in the repository.
The command above used Python 3.14 in an isolated virtual environment.

### P2 command exit 2

```text

==================================== ERRORS ====================================
___________________ ERROR collecting tests/test_timeline.py ____________________
ImportError while importing test module '/home/minamorl/repos/.worktrees/berylx-py-timeline/tests/test_timeline.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_timeline.py:8: in <module>
    from berylx.timeline import Timeline, TimelineError, KeyframeTrack, predicates
E   ModuleNotFoundError: No module named 'berylx.timeline'
=========================== short test summary info ============================
ERROR tests/test_timeline.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.09s

```

### P3 command exit 0 after review

```text
.....................                                                    [100%]
21 passed in 0.13s

```

Further review regressions reproduced two failures (exit 1, `2 failed, 21
passed in 0.18s`) before fixes: the cache retained discarded Root/connection
cycles, and numeric merge equality treated signed zero/NaN unlike Object.is.
Root-owned caches and weak registry values now pass explicit garbage collection
checks even with registered workflow closures. Merge comparison distinguishes
positive and negative zero and equates independently constructed NaNs. Raw RED:
`/tmp/berylx-timeline-review2-red.log`. Latest command exit **0**:

```text
.......................                                                  [100%]
23 passed in 0.14s

```
