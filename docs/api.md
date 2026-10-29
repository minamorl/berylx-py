# API correspondence and deliberate boundaries

| TypeScript surface                                      | Python surface                           | Contract                                                 |
| ------------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------- |
| Focus / Lay                                             | Focus / Lay                              | immutable snapshot and lazy path operations              |
| toObject / toLay / toState                              | to_object / to_lay / to_state            | same state boundaries                                    |
| Root / RootOptions.historyLimit                         | Root(..., history_limit=N)               | success-only commit, bounded history                     |
| Flow / State.and                                        | Flow / State.and_then                    | immediate execution / pending composition                |
| Task / AsyncTask                                        | Task / AsyncTask                         | sync / async callback boundaries                         |
| then / par / rescueWith                                 | then / par / rescue_with                 | sequence / shared-base parallel / recovery               |
| When / Else / Branch.or                                 | When / Else / Branch.or_else             | ordered predicates and fallback                          |
| Catch / Rescue / RescueBlock                            | same names                               | partial-state recovery                                   |
| ResultOps                                               | ResultOps                                | normalization and failure-preserving bind/map            |
| BerylxError.failedNode/parallelErrors/withContext       | failed_node/parallel_errors/with_context | structured error properties                              |
| error.toObject                                          | error.to_object                          | serialized keys retain TS camelCase for interoperability |
| Merge.keepLeft/keepRight/deep/strict                    | keep_left/keep_right/deep/strict         | same reducer policies                                    |
| EffectTree build/run/runAsync                           | build/run/run_async                      | same tagged Freer representation                         |
| realHandlers/asyncRealHandlers/around/aroundAsync       | snake_case counterparts                  | propagating handler maps                                 |
| runSubtree/runSubtreeAsync/branchMatches                | snake_case counterparts                  | interpreter utilities                                    |
| EffectTree dryRun                                       | dry_run                                  | task names + Ok unchanged focus                          |
| Perform                                                 | Perform                                  | custom effect dispatch                                   |
| ControlSignal                                           | ControlSignal                            | ordinary Exception marker escaping task conversion       |
| Darkcore Maybe/Either/Result/Validation/State/Effect    | berylx.darkcore (also Darkcore)          | distinct value monads, state and Freer effects           |
| Darkcore fold/foldAsync/run/runAsync                    | fold/fold_async/run/run_async            | synchronous/asynchronous handlers                        |
| IOEffects / VirtualWorld / realHandlers                 | IOEffects / VirtualWorld / real_handlers | explicit real/virtual IO                                 |
| Workflow / Graph                                        | Workflow / Graph                         | workflow wrapper, structural DOT/Mermaid                 |
| berylx<S>()                                             | berylx()                                 | scoped constructors; no recursive static path inference  |
| attachRoot                                              | attach_root                              | projection, snapshot/commit callbacks, unsubscribe       |
| Cray/fromCrayResult/toCrayResult                        | Cray/from_cray_result/to_cray_result     | structural result adapter, Python method spellings       |
| Timeline / ExecutablePlan / KeyframeTrack               | berylx.timeline equivalents              | clock-driven scheduler                                   |
| BerylxTimeline / BerylxTimelinePlan / waitForHumanLogin | berylx.timeline_berylx snake_case        | async effect integration, concurrent commit              |

## Explicit exclusions and adaptations

- EffectTree's low-level public TS helpers `recover`, `runParallel`, `runBranch`,
  `runRescue`, `realRecover` and their async variants are not exported as public
  Python helpers. Equivalent execution is available through `run`/`run_async` and
  handler maps. In particular, the TS legacy `recover(RescueBlock, Err)` inconsistency
  is not reproduced as an extra path.
- TS `deriveFmap`/`deriveAp` helper exports are not public here; each monad implements
  their derivations. Python Effect additionally provides fmap/map/ap.
- The JSON-shaped equivalence domain is string-keyed mappings, finite numbers,
  booleans, strings, lists and None; no symbols, prototype traversal, sparse array
  holes or JavaScript bigint/undefined identity is claimed. List growth uses None.
  Nonplain objects retain identity; updates use Python `with_patch` instead of JS
  `with`. Dict/list cycles are preserved; repeated mutable children are cloned
  independently. Tuples are treated as application values and are not deeply frozen.
- to_object/get expose read-only mapping/list views. Use `berylx.core.plain` to make
  ordinary containers for JSON serialization. Cyclic values are not JSON encodable.
  Merge's structural equality/recursion is intended for acyclic values, as upstream.
- Python truthiness (empty containers false), arbitrary-precision ints, numeric
  conversion, exception names/messages, and object equality follow Python. Custom
  object comparison is not promised equivalent to JS identity. Inputs for matching
  numeric observations should use finite safe JS integers and explicit predicates.
- `history_limit=True` is rejected (Python bool is an int subtype; JS boolean also
  fails Number.isInteger). Pure callback arity counts required positional parameters
  before the first default, analogous to Function.length. Zero-argument callbacks
  receive no arguments because Python cannot ignore surplus positional arguments.
- Python cancellation/KeyboardInterrupt/SystemExit are BaseException control paths,
  not ordinary Err. Cancellation semantics are native asyncio, not JS Promise.
  Recovery blocks are synchronous; use AsyncTask recovery for awaited operations.
- The fold loop executes long right-associated programs iteratively; arbitrary deeply
  left-associated bind closures are not guaranteed stack-safe, matching TS's limitation.
- Parallel strict follows upstream missing-key behavior, not deletion semantics:
  one missing side adopts the present side, and a key missing from both sides can
  expose an internal missing sentinel. Properties exclude deletions and incompatible
  container shape changes. Timeline's separate commit join handles deletions.
- Graph node/edge structure is preserved, with JSON-safe DOT quoting (upstream raw
  quotes can produce invalid DOT). Rendering is not claimed byte-identical for
  escaped names. Cray duck typing recognizes Python is_success/is_failure methods,
  plus success/ok/tag fields; JS camelCase-only foreign methods need an adapter.
- IO is UTF-8 text. Real now returns timezone-aware datetime; ask returns an empty
  string at EOF, virtual exhausted input/env return None. Virtual random equivalence
  is limited to nonempty sequences of nonnegative integers and positive n; negative
  modulo, empty sequences and zero divisors use Python behavior. OS error types,
  console rendering and shell behavior are platform-specific. No external IO occurs
  merely by constructing an IOEffects tree.
- Python package version starts at 0.1.0 independently of TS 0.4.0. No PyPI artifact,
  browser bundle, Node module shim, or TypeScript compile-time fixture parity claimed.
