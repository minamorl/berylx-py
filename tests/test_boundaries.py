import asyncio
from dataclasses import FrozenInstanceError

import pytest

from berylx import (
    AsyncTask,
    Catch,
    ControlSignal,
    Cray,
    EffectTree,
    Else,
    Err,
    Focus,
    Ok,
    Parallel,
    Root,
    Task,
    When,
    attach_root,
    berylx,
    from_cray_result,
    to_cray_result,
)
from berylx import darkcore as d


def test_async_parallel_joins_and_rethrows_first_declared():
    async def scenario():
        events = []
        first, second = ControlSignal("first"), ControlSignal("second")
        gate = asyncio.Event()

        async def left(f):
            events.append("left:start")
            await gate.wait()
            events.append("left:end")
            raise first

        async def right(f):
            events.append("right")
            raise second

        async def final(f):
            events.append("final")
            gate.set()
            return f

        with pytest.raises(ControlSignal) as caught:
            await EffectTree.run_async(
                Parallel(
                    [AsyncTask("left", left), AsyncTask("right", right), AsyncTask("final", final)]
                ),
                {},
            )
        assert caught.value is first
        assert events == ["left:start", "right", "final", "left:end"]

    asyncio.run(scenario())


def test_sync_parallel_joins_predicate_errors_and_signals():
    events = []
    first = ValueError("predicate")

    def bad(f):
        events.append("bad")
        raise first

    def signal(f):
        events.append("signal")
        raise ControlSignal()

    branches = [
        When("bad", bad).then(Task("unreachable", lambda f: f)),
        Task("signal", signal),
        Task("last", lambda f: events.append("last") or f),
    ]
    with pytest.raises(ValueError) as caught:
        EffectTree.run(Parallel(branches), {})
    assert caught.value is first
    assert events == ["bad", "signal", "last"]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_recover_dispatch_overrides_propagate(asynchronous):
    async def scenario():
        seen = []
        fail = Task("fail", lambda f: f.reject("bad"))
        recover = Task("recover", lambda f: f.put("ok", True))
        handlers = EffectTree.async_real_handlers() if asynchronous else EffectTree.real_handlers()
        inner = handlers[EffectTree.RECOVER]

        def intercept(payload):
            seen.append(type(payload[0]).__name__)
            return inner(payload)

        handlers[EffectTree.RECOVER] = intercept
        for node in [fail.then(Catch("catch", recover)), fail.rescue_with(recover)]:
            result = (
                await EffectTree.run_async(node, {}, handlers)
                if asynchronous
                else EffectTree.run(node, {}, handlers)
            )
            assert result.focus.get() == {"ok": True}
        assert seen == ["Catch", "Rescue"]

    asyncio.run(scenario())


def test_effect_shallow_immutable_record_payload_mutable():
    payload = {"n": 1}
    effect = d.op("read", payload, lambda x: x)
    with pytest.raises(FrozenInstanceError):
        effect._step = None
    with pytest.raises(FrozenInstanceError):
        effect.step().tag = "other"
    payload["n"] = 2
    assert effect.payload is payload
    assert effect.payload["n"] == 2


def test_focus_cycles_shared_children_none_and_arrays():
    source = {"name": "a"}
    source["self"] = source
    f = Focus(source)
    assert f.value["self"] is f.value
    child = {"x": 1}
    values = Focus({"a": child, "b": child}).value
    assert values["a"] is not values["b"]
    f = Focus({"a": None, "items": [1, 2], "scalar": 1})
    assert f.at("a").present()
    assert not f.at("missing").present()
    assert f.at("items").at("1").get() == 2
    assert f.at("items").at(0).set(3).at("items").get() == [3, 2]
    with pytest.raises(KeyError):
        f.at("items").at(-1).get()
    with pytest.raises(TypeError):
        f.at("scalar").at("x").set(2)
    receipt = {"lines": ["charge"]}
    error = f.put("receipt", receipt).reject("bad")
    receipt["lines"].append("refund")
    assert error.focus.at("receipt").at("lines").get() == ["charge"]


def test_namespace_predicates_and_state_ap_order():
    assert d.Ok is not Ok and d.Err is not Err
    assert d.Nothing.pure(1).is_just()
    assert d.Left.pure(1).is_right()
    assert d.Err.pure(1).is_ok()
    assert d.Failure.pure(1).is_success()
    assert d.Just(lambda x: x).ap(d.Nothing()).is_nothing()
    assert d.Right(lambda x: x).ap(d.Left("e")).is_left()
    assert d.Ok(lambda x: x).ap(d.Err("e")).is_err()
    assert d.Success(lambda x: x).ap(d.Failure(["e"])).is_failure()
    function = d.State(lambda s: (lambda x: x * 2, s + ["function"]))
    argument = d.State(lambda s: (len(s), s + ["argument"]))
    assert function.ap(argument).run([]) == (2, ["function", "argument"])


def test_virtual_observers_payload_validation_and_random_cycle():
    world = d.VirtualWorld(files={"/a/b/c": "x"}, rand_seq=[7, 3])
    h = world.handlers()
    assert h["list_dir"]("/a") == ["b/c"]
    assert [h["rand"](5) for _ in range(3)] == [2, 3, 2]
    assert h["getenv"]("missing") is None
    assert h["exists"]("/missing") is False
    assert world.log == []
    assert h["ask"](None) is None
    assert h["shell"]("unknown") == ""
    for handlers in (h, d.real_handlers()):
        with pytest.raises(TypeError):
            handlers["write"](["path"])
    with pytest.raises(TypeError):
        d.run(d.IOEffects.say("x"), {"say": lambda _: "bad"})


def test_graph_scoped_adapters_are_real_and_lazy():
    b = berylx()
    node = b.task("a", lambda f: f.put("a", 1)).par(b.task("b", lambda f: f.put("b", 2)))
    node = node.then(
        When("yes", lambda f: True)
        .then(b.task("c", lambda f: f))
        .or_else(Else.then(b.task("other", lambda f: f)))
    )
    graph = node.compile()
    assert graph.nodes() == ["a", "b", "c", "other"]
    assert graph.parallel_nodes() == [["a", "b"]]
    assert '"split#0" -> "a#2";' in graph.to_dot()
    assert "|yes|" in graph.to_mermaid()
    root = Root({})
    seen = []
    unsubscribe = attach_root(root, seen.append)
    root.call(node)
    unsubscribe()
    root.commit({"after": True})
    assert seen == [{}, {"a": 1, "b": 2}]
    result = from_cray_result(Cray.success({"x": 1}))
    assert from_cray_result(to_cray_result(result)).focus.get() == {"x": 1}
    assert from_cray_result({"ok": False, "error": "bad"}).code == "bad"


def test_long_right_associated_effect_interpretation():
    def loop(n):
        return d.pure(n) if n == 2000 else d.op("tick", n, int).bind(lambda x: loop(x + 1))

    assert d.run(loop(0), {"tick": lambda x: x}) == 2000


def test_error_nullish_context_and_empty_messages():
    from berylx import BerylxError

    error = BerylxError("bad", failed_node="first", trace=["first"])
    assert error.with_context(failed_node=None).failed_node == "first"
    assert BerylxError("bad", failed_node="").prepend_trace("next").failed_node == ""
    assert Focus({}).at("missing").required("missing", "").message == ""


def test_external_mapping_proxy_is_not_assumed_deeply_frozen():
    from types import MappingProxyType

    original = {"items": [1]}
    original["self"] = original
    result = Focus.of(MappingProxyType(original))
    original["items"].append(2)
    assert result.at("items").get() == [1]
    with pytest.raises(TypeError):
        result.at("items").get()[0] = 3


def test_real_virtual_io_preserve_all_newline_sequences(tmp_path):
    path = str(tmp_path / "lines")
    text = "first\r\nsecond\rthird\n"
    program = (
        d.IOEffects.write(path, text)
        .seq(d.IOEffects.append(path, "\r\nlast"))
        .seq(d.IOEffects.read(path))
    )
    assert (
        d.run(program, d.real_handlers())
        == d.run(program, d.VirtualWorld().handlers())
        == text + "\r\nlast"
    )


def test_cray_missing_vs_explicit_none_fallbacks():
    assert from_cray_result(Cray.failure("bad"), None).focus.get() == {}
    assert from_cray_result({"success": True}).focus.get() == {}
    assert from_cray_result({"success": True}, None).focus.get() is None
    assert from_cray_result({"success": True, "value": None}).focus.get() is None
