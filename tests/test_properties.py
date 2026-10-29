"""P4: generated laws, enabled only after the 68-test regression/unit barrier.

Domains intentionally exclude JS/Python numeric differences, cyclic merge values,
and parallel strict deletion behavior (see docs/api.md). Every law family includes
observable values, failure alternatives, or state/effect logs as applicable.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from berylx import (
    AsyncTask,
    Catch,
    EffectTree,
    Err,
    Focus,
    Merge,
    Root,
    Sequence,
    Task,
)
from berylx import (
    darkcore as d,
)
from berylx.core import plain
from berylx.timeline import KeyframeTrack
from berylx.timeline_berylx import _merge_concurrent

settings.register_profile("ci", max_examples=100, deadline=None, derandomize=True)
settings.load_profile("ci")
number = st.integers(-1000, 1000)
small = st.integers(-10, 10)


def value_function(success, failure, offset, divisor):
    return lambda x: failure if x % divisor == 0 else success(x + offset)


@pytest.mark.parametrize(
    "success,failure",
    [
        (d.Just, d.Nothing()),
        (d.Right, d.Left("left")),
        (d.Ok, d.Err("error")),
        (d.Success, d.Failure(["invalid"])),
    ],
)
@given(a=number, offset=small, offset2=small, divisor=st.integers(2, 9), failed=st.booleans())
def test_value_monad_three_laws(success, failure, a, offset, offset2, divisor, failed):
    f = value_function(success, failure, offset, divisor)
    g = value_function(success, failure, offset2, divisor + 1)
    m = failure if failed else success(a)
    assert success(a).bind(f) == f(a)
    assert m.bind(success) == m
    assert m.bind(f).bind(g) == m.bind(lambda x: f(x).bind(g))
    assert m.fmap(lambda x: x + offset) == m.bind(lambda x: success(x + offset))


@given(
    left=st.lists(st.text(max_size=10), max_size=8),
    right=st.lists(st.text(max_size=10), max_size=8),
)
def test_validation_accumulating_ap_is_distinct_from_bind(left, right):
    a, b = d.Failure(left), d.Failure(right)
    assert a.ap(b).errors == tuple(left + right)
    assert a.bind(lambda _: b) is a


@given(a=number, initial=number, delta=small, delta2=small, failed=st.booleans())
def test_state_monad_laws_with_failure_values_and_mutating_state(a, initial, delta, delta2, failed):
    # State carries a Result value without silently introducing StateT short-circuiting.
    value = d.Err("bad") if failed else d.Ok(a)

    def f(x):
        return d.State(lambda state: (x.fmap(lambda n: n + delta), state + delta))

    def g(x):
        return d.State(lambda state: (x.fmap(lambda n: n * 2), state + delta2))

    m = d.State(lambda state: (value, state + 1))
    assert d.State.pure(value).bind(f).run(initial) == f(value).run(initial)
    assert m.bind(d.State.pure).run(initial) == m.run(initial)
    assert m.bind(f).bind(g).run(initial) == m.bind(lambda x: f(x).bind(g)).run(initial)
    assert m.bind(f).bind(g).run(initial)[1] == initial + 1 + delta + delta2


def effect_observation(program):
    log = []

    def handler(payload):
        log.append(payload)
        return payload

    value = d.run(program, {"record": handler})
    return value, log


@given(a=number, delta=small, delta2=small, failed=st.booleans())
def test_freer_monad_laws_observe_return_value_and_ordered_effect_log(a, delta, delta2, failed):
    value = d.Err("bad") if failed else d.Ok(a)

    def f(x):
        return d.op("record", ("f", delta), lambda response: response).seq(
            d.pure(x.fmap(lambda n: n + delta))
        )

    def g(x):
        return d.op("record", ("g", delta2), lambda response: response).seq(
            d.pure(x.fmap(lambda n: n * delta2))
        )

    m = d.op("record", ("seed", a), lambda response: response).seq(d.pure(value))
    assert effect_observation(d.pure(value).bind(f)) == effect_observation(f(value))
    assert effect_observation(m.bind(d.pure)) == effect_observation(m)
    assert effect_observation(m.bind(f).bind(g)) == effect_observation(
        m.bind(lambda x: f(x).bind(g))
    )
    assert effect_observation(m.bind(f).bind(g))[1] == [("seed", a), ("f", delta), ("g", delta2)]


def envelope(result):
    return (
        type(result).__name__,
        plain(result.focus.to_object()),
        result.error.to_object() if isinstance(result, Err) else None,
    )


@given(initial=number, a=small, b=small, fail_at=st.integers(0, 3), recover=st.booleans())
def test_sequence_associativity_preserves_partial_failure_and_catch(
    initial, a, b, fail_at, recover
):
    def step(name, delta, ordinal):
        def body(f):
            updated = f.at("n").update(lambda n: n + delta)
            return updated.reject("stop") if fail_at == ordinal else updated

        return Task(name, body)

    x, y, z = step("x", a, 1), step("y", b, 2), step("z", 1, 3)
    if recover:
        y = y.then(Catch("catch", block=lambda error, f: f.put("caught", error.code)))
    left, right = x.then(y).then(z), x.then(y.then(z))
    assert envelope(left.call({"n": initial})) == envelope(right.call({"n": initial}))
    assert envelope(Sequence([]).then(left).call({"n": initial})) == envelope(
        left.call({"n": initial})
    )
    assert envelope(left.then(Sequence([])).call({"n": initial})) == envelope(
        left.call({"n": initial})
    )


@given(initial=number, delta=small)
def test_root_failure_never_commits_even_when_partial_state_changes(initial, delta):
    root = Root({"n": initial})
    result = root.call(Task("fail", lambda f: f.at("n").set(initial + delta).reject("no")))
    assert isinstance(result, Err)
    assert result.focus.at("n").get() == initial + delta
    assert root.state() == {"n": initial}
    assert root.history == []


@given(a=number, b=number, x=number, y=number)
def test_strict_merge_base_identities_and_disjoint_existing_nested_updates(a, b, x, y):
    base = Focus({"nested": {"a": a, "b": b}})
    left = base.at("nested").at("a").set(x)
    right = base.at("nested").at("b").set(y)
    join = Merge.strict()
    assert join(base, left, base).to_object() == left.to_object()
    assert join(left, base, base).to_object() == left.to_object()
    assert join(left, left, base).to_object() == left.to_object()
    assert join(left, right, base).to_object() == {"nested": {"a": x, "b": y}}
    assert join(left, right, base).to_object() == join(right, left, base).to_object()


@given(base_value=number, delta=st.integers(1, 100), delta2=st.integers(101, 200))
def test_incompatible_edits_are_errors_not_silent_overwrites(base_value, delta, delta2):
    node = Task("a", lambda f: f.put("n", base_value + delta)).par(
        Task("b", lambda f: f.put("n", base_value + delta2))
    )
    result = node.call({"n": base_value})
    assert isinstance(result, Err)
    assert result.code == "merge_conflict"
    assert result.focus.to_object() == {"n": base_value}


@given(a=number, b=number, c=number, x=number, y=number, z=number)
def test_strict_compatible_join_associativity(a, b, c, x, y, z):
    base = Focus({"a": a, "b": b, "c": c})
    left, middle, right = base.put("a", x), base.put("b", y), base.put("c", z)
    join = Merge.strict()
    assert (
        join(join(left, middle, base), right, base).to_object()
        == join(left, join(middle, right, base), base).to_object()
    )


@given(initial=number, delta=small, fail=st.booleans(), accumulate=st.booleans())
def test_sync_async_workflow_observational_agreement(initial, delta, fail, accumulate):
    def left(f):
        value = f.at("n").update(lambda n: n + delta)
        return value.reject("left") if fail else value

    def right(f):
        return f.put("right", True)

    sync_node = Task("left", left).par(Task("right", right))

    async def async_left(f):
        await asyncio.sleep(0)
        return left(f)

    async def async_right(f):
        await asyncio.sleep(0)
        return right(f)

    async_node = AsyncTask("left", async_left).par(AsyncTask("right", async_right))
    if accumulate:
        sync_node, async_node = sync_node.accumulate(), async_node.accumulate()
    assert envelope(sync_node.call({"n": initial})) == envelope(
        asyncio.run(EffectTree.run_async(async_node, {"n": initial}))
    )


@given(base_value=number, other=number)
def test_timeline_deletion_aware_join_preserves_disjoint_updates(base_value, other):
    base = Focus({"deleted": base_value, "other": 0})
    current = base.put("other", other)
    completed = Focus({"other": 0})
    result = _merge_concurrent(current, completed, base)
    assert result.to_object() == {"other": other}


@given(start=number, finish=number, numerator=st.integers(0, 100))
def test_keyframe_linear_interpolation(start, finish, numerator):
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    track = KeyframeTrack().place(origin, start).place(origin + timedelta(seconds=100), finish)
    assert track.sample(origin + timedelta(seconds=numerator)) == pytest.approx(
        start + (finish - start) * numerator / 100
    )


@given(a=number, factor=small, delta=small, failed=st.booleans())
def test_freer_handler_responses_control_continuation_values_and_payloads(a, factor, delta, failed):
    def f(response):
        return d.op(
            "record", response + delta, lambda value: d.Err("failed") if failed else d.Ok(value)
        )

    def g(result):
        payload = -1 if isinstance(result, d.Err) else result.value
        return d.op("final", payload, int).fmap(lambda response: result.fmap(lambda _: response))

    program = d.op("lookup", a, int)

    def observe(effect):
        log = []

        def lookup(payload):
            log.append(("lookup", payload))
            return payload * factor

        def record(payload):
            log.append(("record", payload))
            return payload * 2

        def final(payload):
            log.append(("final", payload))
            return payload + 1

        return d.run(effect, {"lookup": lookup, "record": record, "final": final}), log

    left = observe(program.bind(f).bind(g))
    assert left == observe(program.bind(lambda response: f(response).bind(g)))
    response = (a * factor + delta) * 2
    assert left == (
        d.Err("failed") if failed else d.Ok(response + 1),
        [("lookup", a), ("record", a * factor + delta), ("final", -1 if failed else response)],
    )
