# KyaniteLabs shared repository hub

This is the organization profile/defaults hub and an operator tool for repository-policy provisioning, not an end-user AI product. It belongs in the live-tool inventory because its provisioner can open cross-repository repair PRs and create branch rulesets.

## Existing experience and surfaces

- [profile/README.md](profile/README.md): public GitHub organization profile and product links. Product installation/features belong to the individual product repositories.
- Shared issue/PR/contribution/security/funding files, agent instructions and GitHub/Forgejo workflow templates.
- [scripts/provision-agent-law.py](scripts/provision-agent-law.py): discover active non-fork repositories under an owner, inspect named Agent Law rulesets, inspect local doctrine/checklist files, and optionally create missing rulesets/open repair PRs.
- [scripts/check-agent-parity.py](scripts/check-agent-parity.py): compare selected sections of CLAUDE.md/AGENTS.md and report supporting agent-file presence.
- Scheduled/manual provisioner workflow, marker-based `agent-law` checks and tests of repository defaults.

There is no user database or reference dataset. The maintained corpus is policy prose, templates, metadata and scripts; generated audit/provisioning reports describe inspected repositories, not product behavior.

## Limits and authority

The provisioner defaults to audit-only without `--apply`, but audit mode is not filesystem-read-only: file inspection clones repositories and uses temporary-workspace cleanup. With an admin secret the scheduled workflow is configured to apply; the absence of that secret forces audit-only. This repository does not prove what credentials or schedules are actually installed.

Ruleset existence is not ruleset-content reconciliation. Parity is a normalized/word-overlap heuristic, and marker checks do not prove compliance, reviewer approval or working products. Changing repository settings/access remains separately approval-gated; this documentation does not run provisioning, change policies/settings, or authorize cross-repo writes.
