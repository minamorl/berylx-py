"""Compare Python observations with outputs of the separately executed pinned TS runtime."""

import json
from pathlib import Path

from berylx import Catch, EffectTree, Merge, Task
from berylx import darkcore as d


def test_pinned_ts_observations():
    def put(k, v):
        return Task(k, lambda f: f.at(k).set(v))

    def envelope(r):
        out = {"ok": r.is_ok(), "state": r.focus.to_object()}
        if r.is_err():
            out["error"] = r.error.to_object()
        return out

    fail = Task("fail", lambda f: f.reject("declined", "no"))
    observations = {}
    observations["partial"] = envelope(
        put("charged", True).then(fail).then(put("skipped", True)).call({})
    )
    observations["caught"] = envelope(
        put("charged", True)
        .then(fail)
        .then(Catch("heal", block=lambda e, f: f.put("healed", e.code)))
        .call({})
    )
    par = put("a", 1).par(put("b", 2))
    observations["strict"] = envelope(par.call({"a": 0, "b": 0}))
    observations["deep"] = envelope(par.reduce(Merge.deep()).call({"a": 0, "b": 0}))
    observations["conflict"] = envelope(put("a", 1).par(put("a", 2)).call({"a": 0}))
    observations["accumulate"] = envelope(
        fail.par(Task("other", lambda f: f.reject("other"))).accumulate().call({})
    )
    trace = []
    effects = EffectTree.around(
        {"lookup": lambda x: x * 10}, lambda tag, p, inner: trace.append(tag) or inner(p)
    )
    observations["handlers"] = envelope(
        EffectTree.run(
            Task("lookup", lambda f, p: f.put("v", p.perform("lookup", 2))).par(
                fail.rescue_with(put("healed", True))
            ),
            {},
            effects,
        )
    )
    observations["trace"] = trace
    observations["state"] = list(
        d.State.get()
        .bind(lambda n: d.State.put(n + 1).seq(d.State.get()))
        .fmap(lambda n: n * 2)
        .run(10)
    )
    observations["monads"] = {
        "maybe": d.Just(3).bind(lambda x: d.Just(x + 1)).value,
        "result": d.Err("bad").bind(d.Ok).error,
        "validation": list(d.Failure(["a"]).ap(d.Failure(["b"])).errors),
    }
    assert observations == json.loads(
        (Path(__file__).parent / "fixtures/ts-observations.json").read_text()
    )
