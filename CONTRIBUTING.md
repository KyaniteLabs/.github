# Contributing to Kyanite Labs Projects

We use **issue-driven development**. All contributions start as GitHub issues — no direct pull requests from external contributors.

## How to Contribute

### Report a Bug or Request a Feature

1. Check existing [issues](../../issues) to avoid duplicates
2. Open a new issue using a template:
   - **Bug report** — something broken or behaving incorrectly
   - **Feature request** — something new you'd like added
3. Fill out the template with as much detail as possible
4. Your issue will be labeled `needs-triage` automatically

### What Happens Next

1. Maintainers review your issue
2. If accepted, it gets the `approved` label
3. Our automated pipeline picks it up and creates a fix PR
4. You'll be notified when the fix is merged

### We Don't Accept Direct PRs

Pull requests from external contributors will not be reviewed. If you have a fix, open an issue describing the problem and proposed solution. Maintainers may ask you to submit a PR if appropriate.

## Issue Labels

| Label | Meaning |
|-------|---------|
| `needs-triage` | Awaiting maintainer review |
| `approved` | Accepted by maintainers, waiting for pipeline |
| `agent-ready` | Pipeline will create a fix |
| `bug` | Something is broken |
| `enhancement` | New feature or improvement |
| `good first issue` | Good entry point for new contributors |
| `priority: critical/high/medium/low` | Severity level |

## Reporting Security Issues

Do **not** open a public issue for security vulnerabilities. Use [GitHub Security Advisories](../../security/advisories/new) instead.

## Questions?

Open a [Discussion](../../discussions) or an issue with the `question` label.

<!-- EMPOWER_ORCHESTRATOR:START -->
## Agent-law contribution rule

This repository follows the Empower Orchestrator law in `docs/agent-law/empower-orchestrator.md`.

If a change exposes a repeated task or repeated agent failure, contributors and agents should either ship the smallest durable prevention artifact or explain why this PR is intentionally one-off.

Automation and durable system changes require the scale/severity/reversibility/predictability blast-radius check before dispatch.
<!-- EMPOWER_ORCHESTRATOR:END -->
