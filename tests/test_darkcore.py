import asyncio

import pytest

from berylx import darkcore as d


@pytest.mark.parametrize(
    "success,failure",
    [
        (d.Just, d.Nothing()),
        (d.Right, d.Left("e")),
        (d.Ok, d.Err("e")),
        (d.Success, d.Failure(["e"])),
    ],
)
def test_value_monad_units(success, failure):
    assert success(2).bind(lambda x: success(x + 1)) == success(3)
    assert success(lambda x: x * 2).ap(success(3)) == success(6)
    assert success(2).fmap(lambda x: x * 3) == success(6)
    assert failure.bind(lambda x: pytest.fail("evaluated failure")) is failure
    assert failure.fmap(lambda x: pytest.fail("evaluated failure")) is failure
    assert failure.seq(success(1)) is failure


def test_validation_accumulates_only_ap():
    assert d.Failure(["a"]).ap(d.Failure(["b"])).errors == ("a", "b")
    assert d.Validation.failure(["a", "b"], "c").errors == ("a", "b", "c")
    assert d.Failure(["a"]).bind(lambda x: d.Failure(["b"])).errors == ("a",)


def test_maybe_null_and_result_try():
    assert isinstance(d.Maybe.from_nil(None), d.Nothing)
    assert d.Maybe.from_nil(0) == d.Just(0)

    def bad():
        raise ValueError("bang")

    assert d.Result.try_(bad) == d.Err("bang")


def test_state_threads_value_and_state():
    program = (
        d.State.get().bind(lambda n: d.State.put(n + 1).seq(d.State.get())).fmap(lambda n: n * 2)
    )
    assert program.run(10) == (22, 11)
    assert d.State.modify(lambda n: n + 2).run(1) == (None, 3)


def test_effect_handler_boundary_and_substitution():
    calls = []

    def decode(x):
        if not isinstance(x, int):
            raise TypeError("number required")
        return x

    program = d.op("lookup", 7, decode).bind(lambda n: d.pure(n + 1))
    assert calls == []
    assert d.run(program, {"lookup": lambda p: calls.append(p) or 41}) == 42
    assert calls == [7]
    assert d.run(program, {"lookup": lambda p: 1}) == 2
    with pytest.raises(TypeError):
        d.run(program, {"lookup": lambda p: "41"})
    with pytest.raises(ValueError):
        d.op("pure", None, lambda x: x)
    with pytest.raises(KeyError):
        d.run(program, {})
    assert d.fold(d.pure(2), lambda x: str(x), {}) == "2"


def test_async_effect_fold():
    async def handler(p):
        return p + 1

    assert asyncio.run(d.run_async(d.op("inc", 2, int), {"inc": handler})) == 3


def test_io_real_virtual_substitution(tmp_path):
    path = str(tmp_path / "note")
    program = (
        d.IOEffects.write(path, "hello")
        .seq(d.IOEffects.append(path, " world"))
        .seq(d.IOEffects.read(path))
    )
    world = d.VirtualWorld()
    assert d.run(program, world.handlers()) == d.run(program, d.real_handlers()) == "hello world"
    assert [x[0] for x in world.log] == ["write", "append", "read"]
    with pytest.raises(TypeError):
        d.run(d.IOEffects.exists(path), {"exists": lambda p: "yes"})
