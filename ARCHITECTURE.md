# Shared hub architecture

## Parts and flow

```text
operator / scheduled workflow -> provision-agent-law.py -> gh discovery
 -> named org/repo ruleset lookup -> optional creation through GitHub API
 -> repository clone + structural checks -> optional doctrine/workflow patch
 -> commit/branch push/repair PR -> local JSON report -> workflow artifact
local repository files -> check-agent-parity.py -> heuristic report / CI exit
```

[scripts/provision-agent-law.py](scripts/provision-agent-law.py) is self-contained Python using subprocess Git/gh and temporary workspaces. Repository discovery filters archived repos/forks. Ruleset helpers return `exists` on name match rather than validating existing contents; missing rulesets are created only with `--apply`. File repair writes marker-delimited doctrine/checklist blocks, a recipe and an `agent-law` workflow, respecting certain existing docs/template path variants.

[.github/workflows/agent-law-provisioner.yml](.github/workflows/agent-law-provisioner.yml) configures scheduled/manual execution and uploads `agent-law-provisioner-results.json`. It uses the admin secret when present; otherwise applies repo-scoped credentials only in audit mode. The script itself can also rely on ambient gh authentication. [docs/agent-law/provisioning.md](docs/agent-law/provisioning.md) describes intended permissions; it is not evidence of current grants.

[scripts/check-agent-parity.py](scripts/check-agent-parity.py) strips comments/tags/frontmatter, extracts selected headings, and compares normalized content or word-set overlap. It reports pass/warn/fail thresholds and only returns a failing parity exit in `--ci` mode. The CLI skips dot-prefixed directory names, so running it from the `.github` directory can silently inspect nothing; direct `check_repo` inspection avoids that blind spot without changing source.

## Risky paths and failure signatures

- **Administrative blast radius:** `--apply` can create org/repo rulesets and push many repair branches. The code's ruleset payload requires PRs/status checks but sets approving-review count to zero; it is not a substitute for current review/merge policy. Do not execute it as a docs verification command.
- **Incomplete reconciliation:** an existing named ruleset or marker-compliant files may be stale or weaker than intended. A `compliant`/`exists` row is structural evidence only; no product tests or downstream settings readback follows.
- **Filesystem/destruction:** `repair_files` removes an existing clone directory; temporary-directory cleanup deletes clones even in audit mode. Respect no-deletion sessions and shared-resource claims. Neither mode is a safe arbitrary-path sandbox.
- **Workflow/branch drift:** generated workflows overwrite the target file; existing repair branches may diverge from the default branch; pushes/PR creation can fail after partial local/remote work. Inspect exact target branch/PR before claiming repair.
- **Auth/reporting:** missing scopes produce blocked/skipped statuses, command failures can raise before report creation, and exit zero may mean only missing/dry-run rows. Report status is not an authorized settings receipt.
- **Governance:** policy templates and marker checks cannot establish that an agent followed the law, received approval, or produced user-side proof. Policy changes need owner review independent of code execution.

## Verification and rollback

Use help/import/pure inspection checks without invoking discovery/repair/settings mutation when only documenting. No provisioner apply/audit job or repository setting is changed here. Docs-only rollback is reverting the commit. Reversing an actual ruleset/provisioning rollout is a separate authorized operation, not implied by that rollback.
