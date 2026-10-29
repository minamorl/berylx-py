# User-request lift only. No target implementation, tests, traces, or supervisor artifacts were read.
@meta name: berylx-py
@meta version: 0.1
@meta target: repo=berylx-py
@meta request: "paseoでcodexを起動しberylx-pyを作り公開しろ。回帰とUnitから固めて等価なモナドをdarkcore相当で足場を固めそれからProperty通せ"
@meta provenance: "Confirmed constraints supplied with the user request; behavior details remain unpinned until separately established."
@meta route: "Uncovered Python target; declared code-first proceeds independently of this request lift."
import house_style@4.0

pin berylx_py.execution: require berylx_py.execution.agent = codex_via_paseo
pin berylx_py.language: require berylx_py.implementation.language = python
pin berylx_py.reference_repo: require berylx_py.reference.repository = https://github.com/minamorl/berylx-ts
pin berylx_py.reference_prefix: require berylx_py.reference.revision_prefix = 24aabcd
pin berylx_py.reference_resolution: require berylx_py.reference.revision_record = fixed_full_revision
pin berylx_py.reference_inspection: require berylx_py.reference.evidence = actual_implementation_and_tests
pin berylx_py.upstream_comparison: require berylx_py.reference.comparison = upstream
pin berylx_py.equivalence_scope: require berylx_py.equivalence.scope = explicitly_documented
pin berylx_py.host_preference: require berylx_py.workspace.preference = macbook_dedicated_worktree
pin berylx_py.host_fallback: require berylx_py.workspace.fallback = record_available_host_and_path
pin berylx_py.task_matrix: require berylx_py.workflow.task_matrix = maintained
pin berylx_py.phase_barriers: require berylx_py.workflow.phase_transition = preceding_phase_green
pin berylx_py.phase_order: require berylx_py.workflow.order = regression_unit_then_monad_substrate_then_property
pin berylx_py.regression_unit: require berylx_py.tests.regression_unit_basis = observed_reference_behavior
pin berylx_py.substrate: require berylx_py.monad.substrate = darkcore_equivalent
pin berylx_py.monad_equivalence: require berylx_py.monad.equivalence = within_documented_scope
pin berylx_py.property_monad: require berylx_py.tests.property.monad = checked
pin berylx_py.property_composition: require berylx_py.tests.property.composition = checked
pin berylx_py.property_state: require berylx_py.tests.property.state = checked
pin berylx_py.property_failure: require berylx_py.tests.property.failure = checked
pin berylx_py.investigate_type: require berylx_py.investigation.type = documented
pin berylx_py.investigate_state: require berylx_py.investigation.state = documented
pin berylx_py.investigate_error: require berylx_py.investigation.error = documented
pin berylx_py.investigate_composition: require berylx_py.investigation.composition = documented
pin berylx_py.investigate_interpretation: require berylx_py.investigation.interpretation = documented
pin berylx_py.investigate_merge: require berylx_py.investigation.merge = documented
pin berylx_py.differences: require berylx_py.compatibility.differences = documented
pin berylx_py.unsupported: require berylx_py.compatibility.unsupported = documented
pin berylx_py.python_sources: require berylx_py.python.research = official_primary_documentation
pin berylx_py.preserve_work: forbid berylx_py.workspace.existing_work = overwritten
pin berylx_py.publish_destination: require berylx_py.publication.destination = github_minamorl_berylx_py_public
pin berylx_py.publish_gate: require berylx_py.publication.prerequisite = green
pin berylx_py.publish_others: forbid berylx_py.publication.includes = others_changes
pin berylx_py.publish_secrets: forbid berylx_py.publication.includes = secrets
pin berylx_py.pypi: forbid berylx_py.publication.pypi = assumed
pin berylx_py.readme_install: require berylx_py.readme.install = documented
pin berylx_py.readme_use: require berylx_py.readme.use = documented
pin berylx_py.readme_equivalence: require berylx_py.readme.equivalence = documented
pin berylx_py.readme_differences: require berylx_py.readme.differences = documented
pin berylx_py.readme_tests: require berylx_py.readme.test_commands = documented
pin berylx_py.final_url: require berylx_py.final.repository_url = reported
pin berylx_py.final_commit: require berylx_py.final.commit = reported
pin berylx_py.final_ts_revision: require berylx_py.final.typescript_revision = reported
pin berylx_py.final_commands: require berylx_py.final.verification_commands = reported
pin berylx_py.final_exits: require berylx_py.final.verification_exit_codes = reported
pin berylx_py.final_outputs: require berylx_py.final.verification_outputs = reported
pin berylx_py.final_differences: require berylx_py.final.differences = reported
pin berylx_py.final_host: require berylx_py.final.host_and_path = reported

quarantine berylx_py.darkcore_equivalent_meaning: The request names darkcore-equivalent footing but does not itself define concrete operations or semantic equations; do not invent them from the name.
open_question berylx_py.reference_full_revision: Resolve the supplied 24aabcd prefix to the fixed full upstream revision and record it outside this spec-only converter context.
open_question berylx_py.concrete_equivalence_scope: Establish and document the concrete exported operations and observed behaviors covered by equivalence, including any differences and unsupported behavior.
open_question berylx_py.property_law_domains: Establish the concrete domains and observational equality for monad, composition, state, and failure laws from the confirmed equivalence scope; no specific generator or equation is asserted here.
free berylx_py.python_version: No Python support range was specified in the request.
free berylx_py.testing_tools: No Python test framework or property-testing tool was specified in the request.
free berylx_py.package_layout: No package layout or distribution backend was specified in the request.
