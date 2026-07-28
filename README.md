# KyaniteLabs `.github`

Shared defaults for Kyanite Labs org repositories (GitHub + Forgejo).

## What’s in this repo

| Path | Job |
| --- | --- |
| [`profile/README.md`](profile/README.md) | Public GitHub org profile |
| `.gitea/workflows/` | Node / Python / Docker CI templates for Forgejo |
| `.github/workflows/` | Agent-law + org CI on GitHub |
| `workflow-templates/` | Reusable GitHub workflow templates |
| `docs/agent-law/` | Shared agent workflow rules |
| `scripts/provision-agent-law.py` | Copy agent-law into target repos |
| `.github/pull_request_template.md` | PR template |

Product install paths and feature docs live in each product repository—not here.

<!-- EMPOWER_ORCHESTRATOR:START -->
## Agent-law contribution rule

This repository follows the Empower Orchestrator law in `docs/agent-law/empower-orchestrator.md`.

If a change exposes a repeated task or repeated agent failure, contributors and agents should either ship the smallest durable prevention artifact or explain why this PR is intentionally one-off.

Automation and durable system changes require the scale/severity/reversibility/predictability blast-radius check before dispatch.
<!-- EMPOWER_ORCHESTRATOR:END -->
