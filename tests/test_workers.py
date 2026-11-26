import asyncio

import pytest

from berylx import AsyncTask, EffectTree, Err, Parallel, Task, Workflow


@pytest.mark.parametrize("limit,peak", [(1, 1), (2, 2), (8, 4), (None, 4)])
def test_concurrency_and_ordered_merge(limit, peak):
    async def exercise():
        active = maximum = 0

        def branch(index):
            async def run(focus):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep((4 - index) * 0.01)
                active -= 1
                assert focus.to_object() == {"items": []}
                return focus.put("items", [index])

            return AsyncTask(str(index), run)

        node = Parallel([branch(i) for i in range(4)]).reduce(
            lambda acc, result: acc.put(
                "items", list(acc.to_object()["items"]) + list(result.to_object()["items"])
            )
        )
        if limit is not None:
            node = node.workers(limit)
        result = await EffectTree.run_async(node, {"items": []})
        assert result.focus.to_object() == {"items": [0, 1, 2, 3]}
        assert maximum == peak

    asyncio.run(exercise())


@pytest.mark.parametrize("accumulate", [False, True])
def test_failures_all_run_in_definition_order(accumulate):
    async def exercise():
        completed = []

        def branch(index):
            async def run(focus):
                await asyncio.sleep((3 - index) * 0.01)
                completed.append(index)
                return focus.reject(str(index))

            return AsyncTask(str(index), run)

        node = Parallel([branch(i) for i in range(3)], workers=2)
        result = await EffectTree.run_async(node.accumulate() if accumulate else node, {})
        assert isinstance(result, Err)
        assert sorted(completed) == [0, 1, 2]
        if accumulate:
            assert [error.code for error in result.parallel_errors] == ["0", "1", "2"]
        else:
            assert result.error.code == "0"

    asyncio.run(exercise())


def test_nested_limits_multiply_and_survive_composition():
    async def exercise():
        active = maximum = 0

        async def run(focus):
            nonlocal active, maximum
            active += 1
            maximum = max(active, maximum)
            await asyncio.sleep(0.02)
            active -= 1
            return focus

        groups = [Parallel([AsyncTask(str(i), run) for i in range(3)], workers=2) for _ in range(3)]
        node = Parallel(groups, workers=2)
        assert len(node.branches) == 3
        await EffectTree.run_async(node, {})
        assert maximum == 4
        assert len(groups[0].par(AsyncTask("extra", run)).branches) == 2
        assert groups[0].accumulate().short_circuit().reduce(lambda a, b: a)._workers == 2

    asyncio.run(exercise())


@pytest.mark.parametrize("invalid", [0, -1, 1.5, True, None, "2"])
def test_invalid_workers(invalid):
    a = Task("a", lambda f: f)
    with pytest.raises((TypeError, ValueError)):
        a.par(a, workers=invalid)
    with pytest.raises((TypeError, ValueError)):
        a.par(a).workers(invalid)


def test_sync_remains_sequential():
    order = []
    a = Task("a", lambda f: (order.append("a"), f)[1])
    b = Task("b", lambda f: (order.append("b"), f)[1])
    a.par(b, workers=2).call({})
    assert order == ["a", "b"]


def test_workflow_preserves_existing_par_override():
    class CustomTask(Task):
        def par(self, other):
            return super().par(other)

    a = CustomTask("a", lambda f: f.put("a", 1))
    b = Task("b", lambda f: f.put("b", 2))
    assert Workflow("workflow", a).par(b).call({}).focus.to_object() == {"a": 1, "b": 2}
    assert Workflow("workflow", a).par(b, workers=2).call({}).focus.to_object() == {
        "a": 1,
        "b": 2,
    }


def test_workflow_workers_limits_override_branches():
    async def exercise():
        active = maximum = 0

        async def run(focus):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return focus

        class CustomTask(AsyncTask):
            def par(self, other):
                return super().par(other).par(AsyncTask("third", run))

        node = Workflow("workflow", CustomTask("first", run)).par(
            AsyncTask("second", run), workers=1
        )
        await EffectTree.run_async(node, {})
        assert maximum == 1

    asyncio.run(exercise())
