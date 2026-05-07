# Agent Law Provisioner

The Agent Law provisioner is the durable repair loop for the Empower Orchestrator law.

It exists because default community files and local dotfiles are not enough: each repository needs repo-local doctrine, a PR checklist, an `agent-law` workflow, and branch rules requiring that workflow.

## What it provisions

For every active, non-archived, non-fork repo under the selected owner it can:

1. Ensure an `Agent Law` repository ruleset exists.
2. Attempt an owner-level organization ruleset when the owner is an organization and the token has `admin:org`.
3. Open a repair PR if repo-local Agent Law files are missing or drifted.

## Required secret

Configure `AGENT_LAW_ADMIN_TOKEN` in this hub repository.

For `KyaniteLabs/.github`, use a token or GitHub App installation that can:

- list all org repositories, including private repos
- administer repository rulesets
- create branches and PRs
- write workflow files
- create organization rulesets if you want the single org-level ruleset

A classic PAT needs at least `repo`, `workflow`, and `admin:org` for the KyaniteLabs org-level ruleset path. Fine-grained tokens/apps are better if scoped to the org with repository administration and contents/pull-request/workflow write permissions.

For `simongonzalezdc/.github`, personal repositories do not have an organization-level ruleset surface; the provisioner uses per-repo rulesets plus repair PRs.

## Operating modes

- Scheduled runs automatically apply only when `AGENT_LAW_ADMIN_TOKEN` exists.
- Without that secret, the workflow falls back to audit-only and emits a warning.
- Manual dispatch can set `apply=false` for dry runs.

## Local smoke

```bash
python3 -m py_compile scripts/provision-agent-law.py
python3 scripts/provision-agent-law.py --owner KyaniteLabs --ensure-org-ruleset --ensure-repo-rulesets --repair-files
```

Omit `--apply` for audit-only. Add `--apply` only when the token has the necessary write/admin permissions.
