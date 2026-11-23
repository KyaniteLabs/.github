# Reproducible CI experiments

`python3 scripts/ci_experiment.py MANIFEST.json` compares retained measurements
against an explicit policy. It reads local evidence; it does not run project
commands, access a service, choose runners, merge, publish, or change policy.
Python 3.11 or later and the standard library are sufficient.

Consumers can check out this repository at a reviewed commit and run the command
against a project-owned manifest. Copying the tool is unnecessary. Keep the two
Python files together. Pin updates deliberately, as with the shared CI workflow.

## Run the retained pilot

From the shared checkout:

```sh
python3 scripts/ci_experiment.py examples/ci-experiment/kinocut/manifest.json
```

The expected exit is **1**, with decision `reject`: full runs 1230 and 1231 took
964 and 944 seconds, while aggregate logged job spans rose from 2,566.904 to
2,657.427 seconds. The 9,219 fast-test identities/outcomes match. Slow and the
three FFmpeg jobs are additionally checked through actual job status and
aggregate reported test counts; their individual case identities were not
retained. The manifest states this fingerprint scope explicitly.

The shipped fixture preserves the historical push and manual-dispatch triggers,
with an explicit justification for their equivalent eleven full-scope gates.
It excludes the narrower PR runs. Removing that equivalence declaration makes
the comparison `incomparable`. The policy in this reconstruction is
**retrospective**, not evidence of preregistered thresholds. Five percent and
zero extra aggregate job time are example budgets, not organization-wide rules.
The fixture contains source/run identities and measurements, without private
runner names, credentials, local paths or environment dumps.

## Manifest contract

Use the pilot manifest as the complete workflow example. Required top-level
fields are `version: 1`, a bounded `objective`, `design` (`prospective` or
`retrospective`), `policy`, and nonempty `baseline` and `candidate` sample lists.

Declare policy before collecting a prospective experiment:

- `min_elapsed_reduction_percent`: minimum observed median reduction.
- `max_aggregate_job_increase_percent`: allowed observed median resource proxy
  increase. Projects choose their own latency/resource trade-off.
- `minimum_samples`: at least two independent samples on each side for a
  positive policy result. This minimum does not establish statistical power.
- `allowed_input_changes`: explicitly allow changes to `workflow_sha256`,
  `images`, `dependencies`, or `cache_condition` when they are the experiment.
- Optional `equivalent_triggers` plus `trigger_equivalence_reason`: explicitly
  justify differing triggers. Matching actual gates, workload, execution context
  and fingerprint scope remain mandatory. Never infer this equivalence solely
  from a green aggregate status.

Every sample identifies:

- A distinct `run_id`, local `receipt` path and its `receipt_sha256`.
- Exact `source_sha` and `workflow_sha256`; `workload_sha256` identifies the
  unchanged application/test workload independently of the workflow change.
- `context`: `ci-job`, `ci-workflow`, or `local`; exact `trigger`; selected
  `gates`; `test_scope`; and explicit `cache_condition`.
- `images`: named toolchain identities, preferably image digests. A mutable tag
  records a limitation rather than becoming an immutable environment identity.
- `dependencies`: named SHA-256 inputs, matching the existing profile receipt
  when that receipt records dependency hashes.
- `tests`: either `junit` report objects containing `path` and `sha256`, or a
  retained `summary` path and `sha256`.

The comparator checks source/digest bindings and actual gate names. Workload,
workflow, toolchain, cache and trigger-equivalence declarations still require
review; it does not independently fetch or attest them. Compute hashes from the
retained exact inputs, never from a different checkout. Workload identity should
cover application code, tests and relevant configuration, with exclusions
declared in the experiment. The pilot hashes Git tree records except `.forgejo/`
and `docs/`, the only changed areas in that experiment.

All repeated samples within a side must share input conditions. Duplicate run
identities or identical receipt bytes cannot inflate the sample count. Evidence
paths, including symlinks, must resolve inside the manifest directory. Keep
private evidence in the project/operator's private artifact storage.

## Existing receipts and test evidence

`format: ci-profile-v1` reads the existing shared `.ci-results/ci-profile.json`:
source SHA, elapsed time, phase durations, dependencies and actual step exits.
It requires all five phases and known integer exits for a successful comparison.
Use it for CI-job or local measurements. Its single-job elapsed time cannot
stand in for whole-workflow time. Its aggregate job time equals that one job's
elapsed time.

`format: forgejo-logged-workflow-v1` reads the retained log adapter used in the
Kinocut pilot: `commit`, `elapsed_s`, `aggregate_logged_job_span_s`, and `jobs`
with distinct `job` names, `span_s` and successful Forgejo log `status: 1`.
Optional `passed`, `skipped`, `pytest_s` and `before_pytest_s` preserve test counts
and timing breakdowns. This is a local receipt format, not a general Forgejo REST
API contract. The comparator verifies the aggregate against individual spans.
It does not invent subprocess exit codes from status labels.

Both formats retain `queue_seconds` when actually measured; otherwise queue
latency stays null. Missing timing components stay unknown. Logged job spans
include execution overhead and are not CPU-seconds or hardware-utilization
measurements. Compare local measurements separately from CI.

JUnit evidence computes a multiset SHA-256 of sorted
`(file, classname, name, skipped)` rows using compact JSON. Reports must contain
executed tests; malformed, empty and skipped-only evidence is insufficient.
Failures remain failures. Required report hashes are checked before parsing.
The multiset preserves duplicate identities, rather than collapsing them.
It detects equal-count substitutions without equating test execution with line
coverage or installed-product acceptance.

Retained fingerprint summaries require `source_sha`, positive `case_count` and
`case_outcome_sha256`. They support historical evidence whose original report
artifacts may expire; they are operator-supplied evidence, not independently
verified reports. Preserve their raw report hashes and computation provenance.
The pilot includes those retained report hashes. Its fingerprint uses the same
compact sorted-row algorithm.

## Results and automation

Default stdout is a short decision, observed changes, sample counts and reasons.
`--json` emits the comparison with input metadata, ranges, medians, SHA-bound
references, timing breakdowns and limitations. `--output unused.json` retains
that JSON; it exclusively creates the file and refuses to overwrite any input
or existing result. No raw test output or command environments are embedded.

| Exit | Decision | Meaning |
| --- | --- | --- |
| 0 | `meets_policy` | Repeated equivalent observed samples meet the declared budget |
| 1 | `reject` | Observed execution failure or declared performance budget missed |
| 2 | `insufficient_evidence` | Missing/invalid evidence, unknown exit, or too few positive samples |
| 3 | `incomparable` | Trigger/gate/workload/test equivalence or declared-input constraints fail |

Rejection from an under-sampled pair is a decision against the observed budget,
not proof that the candidate is universally slower. All results expose sample
counts and uncertainty; none claims statistical significance, CPU utilization,
release authority or automatic org adoption. Review the receipt before retaining
or rejecting a change. Preserve the existing project gates and merge authority.

The shared CI profile lints this tool, runs positive and negative regression
fixtures, exercises the retained Kinocut pilot through its actual CLI, and checks
the shipped help entry point. A regression in these lessons fails the required
shared CI check. Other projects remain pinned until their own adoption is
qualified.
