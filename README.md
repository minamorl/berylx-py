# berylx-py

Immutable state workflows interpreted through a tagged Freer effect monad. Python
port of [minamorl/berylx-ts](https://github.com/minamorl/berylx-ts), frozen at
[`24aabcd6059547f15b5b2817592e3d0dd4f258bb`](https://github.com/minamorl/berylx-ts/tree/24aabcd6059547f15b5b2817592e3d0dd4f258bb)
(TS 0.4.0). The frozen revision equals upstream HEAD observed on 2026-10-29.

## Install

Python 3.11 or newer. From this source directory:

```bash
python -m pip install .
```

The public repository is https://github.com/minamorl/berylx-py .
Install directly from GitHub:

```bash
python -m pip install 'git+https://github.com/minamorl/berylx-py.git'
```

No PyPI release is implied. For development from this source directory:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

## Workflows

```python
from berylx import Root, Task, Ok

root = Root.of({'user': {'name': '  mina  '}, 'total': 0})
trim = Task.of('trim', lambda f: f.at('user').at('name').update(str.strip))
charge = Task.of('charge', lambda f: f.at('total').set(100))
result = root.call(trim.then(charge))
assert isinstance(result, Ok)
assert root.at('user').at('name').get() == 'mina'
assert root.state()['total'] == 100
```

`Focus`/`Lay` is a snapshot; `at` navigates, `set`/`put`/`update` return a new root
focus. Dicts and lists are defensively copied into read-only views. `Root` commits
only successful results automatically. An `Err` carries its partial focus, structured
error, cause and trace; `unwrap()` explicitly raises. `Catch` recovers at a sequence
boundary; `rescue_with` wraps a whole workflow.

`a.par(b)` starts each branch from the same snapshot. Default strict three-way merge
preserves independent changes to existing keys and reports `merge_conflict` for
incompatible same-path changes. `.reduce(Merge.deep())` explicitly selects
right-biased two-way merging. `.accumulate()` collects failures. The default
`short_circuit` selects the first failure **after every branch settles**; it does
not cancel work. `AsyncTask` runs with `await EffectTree.run_async(...)`.

## Monads and effect interpretation

```python
from berylx import darkcore as d

program = d.op('lookup', {'id': 7}, int).bind(lambda n: d.pure(n + 1))
assert d.run(program, {'lookup': lambda payload: 41}) == 42
assert d.run(program, {'lookup': lambda payload: 9}) == 10

stateful = d.State.get().bind(
    lambda n: d.State.put(n + 1).seq(d.State.get())
)
assert stateful.run(10) == (11, 11)
assert d.Err('failed').bind(lambda x: d.Ok(x + 1)) == d.Err('failed')
```

Darkcore supplies `Just/Nothing`, `Right/Left`, `Ok/Err`, `Success/Failure`, `State`
and `Effect`. These value result classes are distinct from workflow `Ok/Err`.
`Validation.bind` short-circuits; `Validation.ap` accumulates errors and intentionally
differs from the application operation induced by its bind.

Tasks compile into inspectable tagged payloads `(node, focus)` over the same Effect
substrate. Handler maps interpret the tree; `EffectTree.around`/`around_async` wrap
nested tasks, effects and recovery. Callbacks declaring a required second positional
parameter receive `Perform`; recovery callbacks receive it as their third.

```python
from berylx import Task, EffectTree

fetch = Task('fetch', lambda f, p: f.put('answer', p.perform('lookup', 7)))
handlers = EffectTree.real_handlers({'lookup': lambda key: 42})
assert EffectTree.run(fetch, {}, handlers).focus.get()['answer'] == 42
assert EffectTree.dry_run(fetch, {}).steps == ['fetch']
```

Dry-run skips task bodies but still evaluates predicates. It is a planning
interpreter, not proof of behavioral equivalence. Real and virtual IO handlers
interpret the same `darkcore.IOEffects` programs.

## Equivalence and differences

The supported runtime contract includes monad values/state/effects, immutable
focus, structured failures, sequence/parallel/branch/recovery, async interpretation,
Root history/subscriptions, scoped factories, graph output and Cray adapters.
Timeline scheduling and Root integration are exposed in `berylx.timeline` and
`berylx.timeline_berylx` (clock injection, human waits, recurring origins and
concurrent commit merge). See [the frozen contract](docs/equivalence.md) and
[API mapping](docs/api.md) for exact boundaries.

Python names are snake_case; `or_else`/`and_then` avoid keywords. Python exceptions,
truthiness and numbers follow Python rules. `None` combines JavaScript null and
undefined. Python generics do not reproduce TS compile-time path-key inference.
Browser/npm exports are not applicable. The port does not claim unrestricted
cross-language equivalence for arbitrary objects, numeric edge cases or deletions
through parallel's strict reducer. Timeline uses a separate deletion-aware merge.

## Validation

Regression/unit tests and independently captured TypeScript observations were
written and run RED before implementation. After all regression/unit gates pass,
Hypothesis checks generated monad/composition/state/failure/merge properties.

```bash
python -m pytest -q tests/test_regression.py tests/test_darkcore.py tests/test_oracle.py tests/test_boundaries.py tests/test_timeline.py
python -m pytest -q tests/test_properties.py
python -m pytest -q
ruff check src tests
ruff format --check src tests
mypy src/berylx
python -m build
```

The type gate checks implementation bodies; it does not prove TS-style path types.
[Recorded evidence](evidence/) includes phase gates. To regenerate the independent
oracle, build a separate TS checkout at the frozen revision, then run:

```bash
node scripts/ts_oracle.mjs /absolute/path/to/berylx-ts/dist/index.js
```

Its output must match `tests/fixtures/ts-observations.json`. Python compares state,
error envelopes, handler order, State and value-monad observations against that
fixture, without importing or executing the TS implementation.

MIT licensed; original TypeScript implementation copyright 2026 minamorl is
retained in [LICENSE](LICENSE).
