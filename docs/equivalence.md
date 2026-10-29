# Frozen behavior and task matrix

Source: minamorl/berylx-ts at `24aabcd6059547f15b5b2817592e3d0dd4f258bb` (version 0.4.0).
Python is an uncovered target: cc canonical spec-lane and spec-system's berylx.spec
were read; that pin targets the Ruby repository. This is declared code-first work,
with behavior lifted into this document and executable tests, not a Ruby spec edit.

| Phase                                                | Owner                    | Dependency            | Gate                                         |
| ---------------------------------------------------- | ------------------------ | --------------------- | -------------------------------------------- |
| P1 source implementation/tests + primary Python docs | port_owner, source_audit | none                  | source audit and frozen scope                |
| P2 regression and unit expectations                  | port_owner               | P1                    | tests exist before code; expected import RED |
| P3 monads, state, interpreter, composition, adapters | port_owner               | supervisor P2 release | regression/unit GREEN                        |
| P4 generated laws, packaging, documentation          | port_owner               | supervisor P3 release | property/build/lint/type GREEN               |
| P5 review and public GitHub delivery                 | root                     | all previous GREEN    | commit/push/public read                      |

## Observable contract

- Darkcore Maybe, Either, Result and Validation retain separate success/failure types;
  bind skips failures. Validation ap concatenates errors in left-to-right order while
  bind is short-circuiting (its accumulating ap is deliberately not monadic ap).
- Darkcore State threads `(value, state)` through bind; get/put/modify have no ambient state.
- Effect is a tagged Freer tree. op requires a response decoder; pure is reserved.
  bind joins continuations without executing handlers. fold/fold_async interpret tags.
  Workflow Task/Parallel/Branch/Rescue/Recover payloads contain actual node and Focus,
  not opaque thunks. Workflow and Darkcore Ok/Err remain distinct namespaces.
- Focus snapshots dict/list inputs; path navigation is lazy; missing get raises,
  fetch/maybe/present/required are explicit. set/update/put return a root focus.
  Err retains partial state; raised task exceptions retain input focus plus cause,
  failed_node and trace. ControlSignal escapes unchanged; Python BaseException does too.
- Sequence flattens and short-circuits until a matching Catch. Catch ignores success
  and excludes fatal errors unless opted in. Rescue recovers all Err; failed recovery
  retains original error in metadata.rescuedError. Predicate exceptions escape.
- Parallel flattens; all branches use one base. Sync runs every branch in declaration
  order, even with short_circuit. Async starts every branch and waits for settlement.
  First thrown rejection in declaration order escapes. short_circuit selects first Err
  after completion; accumulate preserves ordered child errors and first partial focus.
- Strict merge is a three-way recursive object join, preserves disjoint existing-key
  changes, accepts equal edits, and returns merge_conflict on incompatible edits.
  Explicit deep merge is two-way right-biased and can lose previous branch changes.
  Upstream strict merge treats a missing key as absence (not deletion); preserved.
- Root commits only Ok automatically. Explicit raw-dict commit deep-merges; Focus
  commit replaces. Subscription sends snapshot immediately then commit events.
  history_limit None/0/N retains all/none/latest N in the same list.
- Handler override maps propagate into every subtree and recovery; reserved tags cannot
  be supplied as ordinary custom effects. around wrappers observe nested dispatch.
  dry_run skips task bodies but evaluates predicates and uses the same Effect substrate.
- AsyncTask rejects synchronous execution; async interpretation accepts mixed tasks.
  IO programs can run with real handlers or deterministic VirtualWorld handlers.

## Python adaptations and limits

Python >=3.11. Public names use snake_case (`then`, `par` unchanged), `or_else` and
`and_then` avoid keywords. Python exceptions use native class names (ValueError etc.).
Python None combines JS null/undefined. Python mappings/lists need immutable views;
static TS recursive path-key inference cannot be reproduced by Python typing and is
not claimed. Dynamic path validation is retained. No npm/browser export parity or
Node-specific execution is claimed. Python IO handlers use pathlib/subprocess and
native datetime values. Further differences are recorded alongside final validation.

Primary references read: Python 3.11 official asyncio-task (gather with
return_exceptions for ordered settlement), types.MappingProxyType (read-only mapping),
and typing (Generic/TypeVar and runtime limits), all at docs.python.org/3.11/library/.

Host: vultr fallback, `/home/minamorl/repos/.worktrees/berylx-py-port`.
Parent verified MacBook Tailscale offline and SSH timeout; tau excluded.

## Phase execution record

Core P2: regression/unit/oracle tests were specified before implementation; captured
TS observations exit 0, Python collection RED exit 2 due to missing implementation.
Supervisor released core P3, then briefly paused it pending timeline P2 (two
Darkcore files already written under that release). Global P2 release followed;
no Property was written or run before global regression/unit acceptance.
Core P3: 45 regression/unit/oracle tests GREEN, including all-settled control
signals, custom RECOVER dispatch, deep snapshot cycles and independent TS fixtures.
Timeline is independently owned in its dedicated worktree and joins at global P3.

See [API mapping and limitations](api.md) for supported public surface and intentional
language differences. SAT evidence checks consistency of the lifted requested spec;
it is not a behavioral conformance proof.

Global P3 integrated gate: 68 regression/unit/oracle tests GREEN before any Property.
Supervisor then released P4. Hypothesis suite: 15 test instances, 100 deterministic
generated examples per instance, including four success/failure monad categories,
State effects, Freer ordered logs, sequence/Catch failure, root commit isolation,
strict merge laws, sync/async agreement, deletion-aware timeline join and keyframes.
Initial P4 run: 15 passed in 2.32s. Raw evidence is in evidence/p4-property.txt.

Independent final review found and reproduced RED on error nullish/empty-message
semantics, shallow external mapping proxies, IO newline translation, and Cray
null/missing fallback. Each was fixed with regression coverage. Dict/list and
external Mapping inputs are frozen into owned read-only views; real text IO uses
newline="" to preserve the same bytes as virtual IO for CR/LF sequences. Final
regression/unit count is 72, with 16 generated Property instances (88 total).
Python 3.11 open documentation and PyPA pyproject license guidance were read for
newline-preserving IO and SPDX packaging metadata.

A further response-driven Freer property uses transformed handler responses to
choose subsequent payloads and success/failure results; it compares full observed
value/logs and associativity, complementing tests of effect sequencing.

Development dependencies are pinned in requirements-dev.txt. The sdist includes
the oracle fixtures, tests, specifications and evidence; wheel contains runtime
modules and MIT license. A clean wheel environment executes the README examples
from /tmp (outside the source tree), avoiding source-path import leakage.

Local compatibility matrix used isolated CPython 3.11.18, 3.12.16, 3.13.18
and host 3.14.4. All passed the 72 regression/unit tests followed by 16 Property
test instances and mypy implementation checking. This is local execution evidence,
not a claim that hosted GitHub Actions has run.
