# Measured CI profiles

CI must produce useful failures, exercise the built product, and make its cost
visible. The shared `actions/ci-profile` action runs a project-owned
`.ci/profile.json`. Consumers pin the shared action to a reviewed commit. A shared
change does not silently alter every project's checks.

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

## Rollout and rollback

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
