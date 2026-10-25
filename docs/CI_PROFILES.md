# Measured CI profiles

CI must produce useful failures, exercise the built product, and make its cost
visible. The shared `actions/ci-profile` action runs a project-owned
`.ci/profile.json`. Consumers pin the shared action to a reviewed commit. A shared
change does not silently alter every project's checks.

`.forgejo/workflows/ci-profile.yml` exposes the same action as a reusable workflow.
It accepts `profile`, `runner`, `image`, and `artifact_paths`; the defaults use an
existing Docker runner and a digest-pinned Node/Debian environment. Consumers own
their trigger and PR cancellation policy. Keep private hooks and credentials in
the project layer, and retain reports from workspace subdirectories explicitly.
The workflow checks out its pinned shared action with the ordinary short-lived
job token. This supports installations requiring authenticated public Git access
without a standing cross-project publisher credential.

## Version 1 contract

Profiles declare argument arrays, test-file globs, dependency files, and explicit
`install`, `verify`, `build`, `test`, and `acceptance` phases. Each command has a
bounded timeout (default 600 seconds, maximum 3600). Nonzero exits stop execution
and fail the job. Commands run without an implicit shell. When a project needs a
shell, it explicitly supplies `bash -euo pipefail -c` and reviews that script.
Project scripts still need review: a wrapper cannot make an intentionally
failure-masking command trustworthy.

The runner rejects an empty test inventory. Profiles can additionally require
JUnit reports; missing reports, zero executed tests, entirely skipped reports,
and reported failures reject the run. File inventory alone is not proof that a
test runner collected those files. Use structured reports where supported and
retain each framework's normal nonempty-suite check.

`.ci-results/ci-profile.json` records the checked-out source SHA, profile and
dependency-file hashes, phase durations, exits, and final result. It never dumps
environment variables. This is execution evidence, not a signed provenance
attestation or authority to release. Record runner image/toolchain identity with
the workflow and qualification evidence as well.

Consumers retain this directory with the Forgejo-compatible, SHA-pinned artifact
action. Artifact uploads must run after failure too. Required branch contexts
must match the statuses actually emitted by the installed Forgejo version;
configured names with enforcement disabled do not protect a branch. Save prior
protection settings before an authorized change, verify positive and negative
behavior, and retain a recovery path.

## Carry forward the Kinocut measurements

For a source-bound comparison of retained profile or workflow receipts, use
the [CI experiment command](CI_EXPERIMENTS.md). Its enforced regression fixtures
carry these lessons into future shared CI changes and include the retained
Kinocut control/candidate pair. Projects own their experiment policy and pins.

The initial scheduling comparison observed 29m37s versus 21m08s; test-runtime
variance means that difference cannot all be attributed to scheduling. A later
reusable-toolchain improvement reduced normal master CI from 20m34s to 15m55s
(4m39s, 22.6%), with matching per-shard pass/skip counts. Candidate full runs took
16m21s and 15m57s. Warm layers were available; cold-host image downloads were not
measured.

Across four fast shards and the slow job, time before pytest fell from about
894 seconds to 210 seconds. Remaining fast-shard pytest durations ranged from
4m46s to 9m54s. The local full precommit suite took 29m41s on that candidate.
Those observations identify the next experiments, not guaranteed future gains.

A subsequent local profiling sample passed 9,182 tests with 201 skipped in
30m57s. That sample reinforces the development-loop bottleneck; it does not
establish a speedup or attribute a regression. Keep local and CI measurements
separate, including contention from other work during either measurement.

The subsequent profiling change retained per-file JUnit timing reports and
printed slow call/setup phases without changing the test inventory. Full
control run 1230 passed in 16m04s on source
`71cd86a304c94977ed1dcc9ec99df18db181cd32`. Its four fast shards reported
9,219 cases across 517 files; the separate slow suite passed 159 tests with five
skipped, and each of the three FFmpeg versions passed 129 tests. The PR run had
skipped Slow under the existing scope policy, so a green PR alone would not
have qualified a scheduling change's full-workflow cost.

The observed dependency graph matters: the first fast shard's completion
releases a runner slot for Slow, while the fourth fast shard starts after
another shard finishes. A file's destination therefore changes both execution
time and downstream start times. Compare retained case identities and outcomes
across all shards after moving files; unchanged totals alone can conceal a
missing case and a duplicate case. Keep intentional duplicate compatibility
checks separate from the partitioned test inventory.
Refresh timing assumptions when the test inventory, toolchain or runner layout
changes. A historical file-to-shard assignment is not a permanent scheduling
rule for another project or environment.
Measure each trigger separately when PR and master/manual workflows run
different gates. A full-scope improvement does not establish a PR-turnaround
improvement, and a shorter PR run does not establish full validation cost.

The three-file scheduling experiment on
`5443f0908ee455b26deae7a73cbbc71500b02259`
passed [full run 1231](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/actions/runs/1231)
in 15m44s versus the control's 16m04s: 20 seconds, or 2.1%, in one comparison.
All 9,219 fast-case identities and pass/skip outcomes matched, Slow passed
159 tests with five skipped, and each FFmpeg version passed 129 tests.
The first shard released Slow about 45 seconds earlier, but Slow itself took
about 24 seconds longer. Aggregate logged job spans increased from 2,566.904s
to 2,657.427s, about 90.5 seconds or 3.5%. Those spans are elapsed job time,
not CPU utilization measurements.

The scheduling candidate was rejected and remains outside canonical master.
One small wall-time difference with higher aggregate job time does not qualify
an efficiency improvement or establish faster PR feedback. Retain the profiling
and the existing scheduling; target expensive media calls and the local full
validation loop next. This result narrows the return from this reshuffle, not
the potential of every future optimization.

A second full local sample passed the same 9,182 tests with 201 skipped in
32m55s. Detailed audio profiling put a dominant encode comparison at 14.52s
and repeated media setup at roughly 0.4s per case. These samples do not show a
local speedup, and a small fixture cleanup alone would not resolve the full
development-loop cost. Preserve mandatory full validation while qualifying
any faster local feedback path.

Apply these lessons to every applicable project profile:

1. Separate queue, checkout/setup, execution, and first useful failure. Measure
   end-to-end edit-to-confidence and delivery time, including local precommit.
2. Reuse pinned toolchains and cache downloads with lockfile/environment-aware
   keys. Create fresh environments; do not promote an arbitrary cached green
   result into validation. Keep untrusted PRs out of trusted write caches.
3. Profile individual tests and fixtures before changing shard allocation.
   Whole-workflow elapsed time and aggregate compute decide whether it helped.
   Equal shard lengths can delay a late-starting tail or increase contention.
4. Cancel superseded PR work safely. Preserve master/release gates. Do not raise
   runner concurrency or timeouts to conceal resource contention or lost jobs.
5. Preserve meaningful coverage and compare equivalent source, dependencies,
   workflow, and environment. Record cold/warm conditions and sample variation.
6. Add a quick development loop alongside required full validation. A faster
   local command does not waive a repository's precommit or release rules.

## Acceptance varies by project

Python packages: lint/type checks, real tests and JUnit, wheel build, clean wheel
install, canonical/compatibility imports, CLI or MCP contract smoke, and supported
Python versions. Docs/tooling profiles can compile and execute their shipped
commands without inventing a package build.

Node applications: the declared package manager and frozen lockfile, static and
generated checks, workspace build, real tests, built CLI/UI/API smoke, packaged
contents and clean install where distribution warrants it. Do not replace a
workspace's pnpm build/test with a generic npm command or an absent ESLint task.

Desktop/services: installed-app journeys, migrations, upgrade/rollback checks,
API compatibility and failure cases, and post-deployment smoke. Deployment and
publication remain separately authorized operations.

AI integrations: deterministic replay/evaluation regressions, tool permissions,
provider failures, and bounded live checks within resource/spend authority.
Docs/policy/skills: generated-source parity, command/link checks, and schema/API
alignment. Performance, size, security, dependency-drift, SBOM and provenance
checks belong in relevant profiles; one identical matrix does not fit all repos.

## Layer 1 rules learned in rollout (2026-10-25)

These come from the cohort rollouts across 25 repositories, with independent review of every PR. Each rule fixed a real failure.

- **Concurrency must never cancel or replace a default-branch run.** Key the group per pull request for PR events and per commit SHA otherwise:
  `${{ github.workflow }}-${{ github.event.pull_request.number && format('pr-{0}', github.event.pull_request.number) || github.sha }}`, and set `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`. A single group per ref lets a newer queued push replace a pending main run, so a merge commit can end with no result.
- **Declare `shell: bash`** (workflow `defaults` or per step) whenever steps use `pipefail`, `mapfile`, `[[` or process substitution. Several runners serve the `docker` label, and they differ: v1.0.8 runs container jobs under `sh -e`, where `pipefail` is illegal, while v12 runners use bash.
- **Silent validators must print evidence.** v12 runners log step output but no step headers. html-validate, `node --check` and similar tools print nothing on success, so a passing gate is indistinguishable from one that never ran. End each such step with an evidence line that names the tool, the version and the file count.
- **A tool with no rules passes everything.** For example, an html-validate config without `extends` enables zero rules. Pin versions (npx `pkg@x.y.z` or a lockfile) and extend a real preset.
- **Acceptance must be able to fail.** SPA preview servers return `index.html` (200) for every path, and static servers return directory listings. Check content type plus a body marker, and require a 404 for a missing path.
- **Test the runtime production uses** (Dockerfile base image or interpreter), digest-pin images and SHA-pin actions, and run as root-safe: CI containers run as root, so `chmod 000` does not block reads there.
- **Direct pushes to default branches are disabled** (`enable_push: false`, administrators included). The PR plus the repo's required CI check is the only path in. Context names are per repo and matched as exact strings — Forgejo appends the triggering event, e.g. `CI / ci/required (pull_request)`; some repositories require a differently named gate (for example `Forgejo CI / fast-gate (pull_request)`), and Epoch additionally requires `CI / node-22-floor (pull_request)`. Independent review before merge is by convention, recorded in the PR body, since approval counts (`required_approvals`) are 0.

## Layer 5: self-description consistency

`scripts/self_description_check.py` is offline and stdlib-only. It treats the package manifest (`package.json`, `pyproject.toml` or `setup.py`) as the source of truth for the package name and version, and fails when anything else the repository ships disagrees with it:
- the newest released `CHANGELOG.md` entry, and more than one `Unreleased` section;
- `server.json` (MCP registry) versions;
- MCPB, plugin and extension manifest versions;
- README `name@x.y.z` pins;
- README install commands that name a near-miss of the package. Running a declared bin with `npx <bin>` after install is allowed.

Each passing check prints `gate evidence:` lines. Exit codes: 0 consistent; 1 mismatch, including an unparseable or wrongly shaped file; 2 not applicable, because there is no version in `package.json`, `pyproject.toml` `[project]` or `setup()`. Poetry `[tool.poetry]` and dynamic versions are not read yet, so don't adopt the check until the repository has a supported version source. Runs automatically at the end of every `ci/required` via the shared `ci-profile` action (pinned `.ci-contract` checkout); manual invocation: `python3 <contract>/scripts/self_description_check.py`. Creating tags and releases remains a separately authorized publishing step; this check only proves that what the repository says about itself is consistent.

## Rollout and rollback

### Qualified adoption, 2026-10-24

The [shared contract](https://git.kyanitelabs.tech/KyaniteLabs/.github/pulls/5)
passed positive and deliberately failing phase, report, timeout and inventory
fixtures. The [reusable workflow](https://git.kyanitelabs.tech/KyaniteLabs/.github/pulls/6)
uses an ordinary short-lived job-token checkout for its pinned shared action.
The shared repository's postmerge run 23 passed on `25eeff8425dfc00574a3c572de84f98171839ae7`.

The [DialectOS pilot](https://git.kyanitelabs.tech/KyaniteLabs/DialectOS/pulls/38)
pins reusable workflow `0209ffe2feb69190760cc31491a097fea174550f` and passed
postmerge run 71 on `6aa60643578e768739f25c1df152b7c59006e7ab`. It executes
all seven workspace builds, generated/static checks, 1,393 passing package tests
with one skipped, and built CLI help, dialect-list and error-exit acceptance.
Separate negative fixtures demonstrated that both corrected build scripts now
propagate real TypeScript compiler failures. Clean installation of distributed
tarballs remains a separate acceptance gap. No speedup is claimed against its
previous workflow, which hid failures and skipped meaningful build validation.

Both pilot branches require the observed `CI / ci/required (pull_request)`
context with enforcement enabled for administrators too. These are qualified
consumers, not evidence that every repository has adopted the contract.
For each subsequent project, record its owner, immutable pin, exact successful
source/run, actual required context and remaining acceptance gaps here or in the
project's CI guide. Prioritize failure-masking workflows and missing enforcement
before adding more expensive gates. Preserve project-specific security, release
and compatibility checks when replacing a template.

### Expansion procedure

Run `python3 scripts/ci_adoption_audit.py --repo OWNER/REPO --pull-request NUMBER`
with the existing configured `fj` credential to repeat the read-only adoption
checks. It records the default source, immutable shared pin, declared profile
phases, enabled protection rules, administrator enforcement, and the supplied
PR's emitted status names. Failure-masking candidates are line-numbered for
review; optional fallback commands can be legitimate. Missing or unavailable
lookups remain unknown and make the audit incomplete. A complete audit means
the lookups completed, not that the project's CI or shipped product is accepted.
Without `--pull-request`, default-branch statuses are shown separately and no
comparison to PR-specific required names is inferred.
Pattern-based protection rules are listed for review rather than assuming the
installed server's glob semantics; unknown enforcement is represented as null.
Required-context glob patterns also remain separate from literal-name matching.
An empty required-context list is not a disabled status gate: the installed
[Forgejo 15 implementation](https://codeberg.org/forgejo/forgejo/src/tag/v15.0.10/services/pull/commit_status.go)
aggregates reported statuses in that case. Explicit names additionally guard
against an expected check disappearing. Preserve an existing aggregate policy
until a replacement's required names and behavior are qualified.

Keep private repository inventories and audit output private. This command does
not create credentials, change protections, execute project code, migrate a
consumer, or grant release authority. Use its evidence to prioritize cohorts,
then qualify each project's actual execution and artifact acceptance.

Qualify the shared runner against positive and intentionally failing isolated
fixtures before adoption. Pilot distinct active project types; require honest
pass/fail behavior and the actual branch gates before expanding. Compare repeated
queue/setup/test/first-failure and delivery measurements as samples accumulate.
Record ownership, acceptance coverage, known gaps, and the next cohort. Adoption
is proven by a consumer's pinned source, executed run, and enforced required
context—not by copying a template or opening a PR.

Roll back a workflow/action/image change to its prior pin through the project's
normal reviewed path. Restore a saved protection rule only under its authorized
recovery procedure. Keep failed evidence and meaningful existing gates.
