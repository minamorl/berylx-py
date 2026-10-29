"""Frozen expectations derived before implementation from TS 24aabcd tests/source."""

import asyncio

import pytest

from berylx import (
    AsyncTask,
    Catch,
    ControlSignal,
    EffectTree,
    Else,
    Err,
    Flow,
    Focus,
    Merge,
    Ok,
    ResultOps,
    Root,
    State,
    Task,
    When,
    Workflow,
)


def obj(result):
    return result.focus.to_object()


def put(key, value):
    return Task(key, lambda f: f.at(key).set(value))


def test_snapshot_and_partial_failure_are_immutable():
    source = {"items": [1], "n": 0}
    f = Focus.of(source)
    source["items"].append(2)
    assert list(f.at("items").get()) == [1]
    with pytest.raises(TypeError):
        f.to_object()["n"] = 4
    failed = f.at("n").set(1).reject("bad")
    assert obj(failed)["n"] == 1
    assert f.at("n").get() == 0


def test_focus_path_helpers_and_root_updates():
    f = Focus.of({"a": {"b": 1}})
    assert f.at("a").at("b").update(lambda n: n + 1).path == ()
    assert f.at("missing").maybe() is None
    assert f.at("missing").fetch(False) is False
    assert not f.at("missing").present()
    assert isinstance(f.at("missing").required(), Err)
    with pytest.raises(KeyError):
        f.at("missing").get()
    assert f.at("new").at("deep").set(2).at("new").get() == {"deep": 2}


def test_sequence_failure_preserves_partial_and_skips():
    calls = []
    fail = Task("fail", lambda f: f.reject("declined", "no"))
    result = put("charged", True).then(fail).then(Task("skip", lambda f: calls.append(1))).call({})
    assert isinstance(result, Err)
    assert obj(result) == {"charged": True}
    assert (result.code, result.message, result.failed_node, result.trace) == (
        "declined",
        "no",
        "fail",
        ("fail",),
    )
    assert calls == []


def test_exception_cause_and_control_signal():
    cause = ValueError("bad")

    def explode(f):
        raise cause

    result = Task("explode", explode).call({"x": 1})
    assert result.cause is cause
    with pytest.raises(ValueError, match="bad"):
        result.unwrap()
    signal = ControlSignal("stop")

    def stop(f):
        raise signal

    with pytest.raises(ControlSignal) as caught:
        Task("stop", stop).call({})
    assert caught.value is signal


@pytest.mark.parametrize("limit,expected", [(None, [1, 2, 3]), (0, []), (2, [2, 3])])
def test_root_history_commit_and_subscribe(limit, expected):
    root = Root.of({"n": 0}, history_limit=limit)
    history = root.history
    events = []
    unsubscribe = root.subscribe(events.append)
    for n in range(1, 4):
        root.pipe(put("n", n))
    root.pipe(Task("fail", lambda f: f.at("n").set(9).reject("bad")))
    assert root.state() == {"n": 3}
    assert root.history is history
    assert [e["value"]["n"] for e in history] == expected
    assert [e["type"] for e in events] == ["snapshot", "commit", "commit", "commit"]
    unsubscribe()
    root.commit({"n": 4})
    assert len(events) == 4


@pytest.mark.parametrize("limit", [-1, 1.5, float("inf"), True])
def test_invalid_history(limit):
    with pytest.raises(ValueError):
        Root({}, history_limit=limit)


def test_raw_commit_deep_merges_focus_replaces():
    root = Root({"user": {"name": "a", "id": 1}})
    root.commit({"user": {"name": "b"}})
    assert root.state() == {"user": {"name": "b", "id": 1}}
    root.commit(Focus.of({"fresh": True}))
    assert root.state() == {"fresh": True}


def test_merge_existing_keys_and_identity():
    base = {"a": 0, "b": 0}
    noop = Task("noop", lambda f: f)
    assert obj(put("a", 1).par(put("b", 2)).call(base)) == {"a": 1, "b": 2}
    assert obj(put("a", 1).par(noop).call(base)) == {"a": 1, "b": 0}
    assert obj(noop.par(put("a", 1)).call(base)) == {"a": 1, "b": 0}
    assert obj(put("a", 1).par(put("b", 2)).reduce(Merge.deep()).call(base)) == {"a": 0, "b": 2}


def test_merge_conflict_and_equal_edits():
    failed = put("a", 1).par(put("a", 2)).call({"a": 0})
    assert (failed.code, failed.failed_node, obj(failed)) == (
        "merge_conflict",
        "parallel",
        {"a": 0},
    )
    assert failed.error.metadata["path"] == ["a"]
    assert obj(put("a", 1).par(put("a", 1)).call({"a": 0})) == {"a": 1}


def test_parallel_runs_all_and_orders_errors():
    calls = []

    def bad(name):
        def body(f):
            calls.append(name)
            return f.put(name, True).reject(name)

        return Task(name, body)

    node = bad("a").par(bad("b"))
    first = node.call({})
    assert calls == ["a", "b"]
    assert first.code == "a"
    combined = node.accumulate().call({})
    assert combined.code == "parallel_failed"
    assert [e.code for e in combined.parallel_errors] == ["a", "b"]
    assert obj(combined) == {"a": True}


def test_branch_predicate_exception_escapes_and_first_match():
    node = When.of("yes", lambda f: True).then(put("a", 1)).or_else(Else.then(put("a", 2)))
    assert obj(node.call({})) == {"a": 1}
    assert When.of("no", lambda f: False).then(put("a", 1)).call({}).code == "no_branch_matched"

    def bad(f):
        raise ValueError("predicate")

    with pytest.raises(ValueError):
        When.of("bad", bad).then(put("a", 1)).call({})


@pytest.mark.parametrize("fatal,catches", [(False, False), (True, False), (True, True)])
def test_catch_fatal_and_resume(fatal, catches):
    fail = Task("fail", lambda f: ResultOps.err(f.put("partial", 1), "stop", fatal=fatal))
    boundary = Catch("recover", block=lambda e, f: f.put("recovered", e.code), fatal=catches)
    result = fail.then(boundary).then(put("done", True)).call({})
    assert isinstance(result, Ok) == (not fatal or catches)
    if isinstance(result, Ok):
        assert obj(result) == {"partial": 1, "recovered": "stop", "done": True}


def test_failed_recovery_preserves_original_error():
    result = (
        Task("first", lambda f: f.reject("original"))
        .rescue_with(Task("second", lambda f: f.reject("recovery")))
        .call({})
    )
    assert result.code == "recovery"
    assert result.error.metadata["rescuedError"]["code"] == "original"


def test_state_flow_workflow_and_result_bind():
    node = put("x", 1).then(put("y", 2))
    assert obj(State.of({}).and_then(node).call()) == {"x": 1, "y": 2}
    assert obj(Flow.of({}).call(node)) == {"x": 1, "y": 2}
    assert obj(Workflow.of("w", lambda: node).call({})) == {"x": 1, "y": 2}
    assert ResultOps.map(ResultOps.ok(10), lambda f: f.get() + 1).focus.get() == 11


def test_tagged_tree_lazy_handlers_and_decoder():
    calls = []
    node = Task("a", lambda f: calls.append("a") or f)
    tree = EffectTree.build(node.then(put("b", 2)), {})
    assert calls == []
    assert tree.tag == EffectTree.TASK
    assert tree.payload[0] is node
    handlers = EffectTree.real_handlers()
    handlers[EffectTree.TASK] = lambda p: "bad"
    with pytest.raises(TypeError, match="Ok or Err"):
        EffectTree.run(node, {}, handlers)
    for tag in (
        EffectTree.TASK,
        EffectTree.PARALLEL,
        EffectTree.BRANCH,
        EffectTree.RESCUE,
        EffectTree.RECOVER,
    ):
        with pytest.raises(TypeError):
            EffectTree.real_handlers()[tag](None)


def test_nested_effect_handler_propagation_and_dry_run():
    node = Task("read", lambda f, p: f.put("x", p.perform("answer", None)))
    wrapped = []
    handlers = EffectTree.around(
        {"answer": lambda p: 42}, lambda tag, payload, inner: wrapped.append(tag) or inner(payload)
    )
    result = EffectTree.run(node.par(put("y", 1)), {}, handlers)
    assert obj(result) == {"x": 42, "y": 1}
    assert "answer" in wrapped
    assert wrapped.count(EffectTree.TASK) == 2
    dry = EffectTree.dry_run(node.then(put("y", 1)), {})
    assert dry.steps == ["read", "y"]
    assert obj(dry.result) == {}
    with pytest.raises(ValueError):
        EffectTree.real_handlers({EffectTree.TASK: lambda p: p})


def test_async_mixed_concurrent_and_ordered_settlement():
    async def scenario():
        started = []
        ready = asyncio.Event()

        async def a(f):
            started.append("a")
            await ready.wait()
            return f.put("a", 1)

        async def b(f):
            started.append("b")
            ready.set()
            return f.put("b", 2)

        node = AsyncTask("a", a).par(AsyncTask("b", b)).then(put("c", 3))
        result = await EffectTree.run_async(node, {"a": 0, "b": 0})
        assert obj(result) == {"a": 1, "b": 2, "c": 3}
        assert started == ["a", "b"]

    asyncio.run(scenario())
    with pytest.raises(RuntimeError, match="asynchronous"):
        AsyncTask("a", lambda f: f).call({})
