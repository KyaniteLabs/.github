# Contributing to Kyanite Labs Projects

We use **issue-driven development**. All contributions start as GitHub issues.

## Contribution terms

By submitting content to this project — in an issue, a pull request, or any other channel — you agree:

1. **Licence.** You grant Kyanite Labs and everyone who receives this software a perpetual, worldwide, royalty-free, irrevocable licence to use, reproduce, modify, adapt, publish, distribute, sublicense and otherwise deal in your content as part of the software and its documentation, under this repository's licence. This includes any patent rights you own or control that are necessarily infringed by your content as part of the software. You keep copyright in what you submit; no signature is required.
2. **Certification.** You certify that your submission complies with the Developer Certificate of Origin version 1.1 (https://developercertificate.org): you created it or have the right to submit it under this licence, and any third-party material in it is available under a compatible licence. A human must make this certification — do not add a `Signed-off-by` line on behalf of anyone else or of an AI tool. Where this repository runs a DCO check, each commit in a pull request carries a `Signed-off-by:` trailer (`git commit -s`).
3. **AI-assisted content.** Content produced with AI tools is welcome under the same terms. You are responsible for reviewing it, for ensuring the tool's terms of use do not conflict with this licence, and for the certification above.

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

### Direct Pull Requests

If you have a fix, opening an issue describing the problem and proposed solution is the fastest route; maintainers may ask you to submit a PR if appropriate. Unsolicited PRs may be closed unread or converted to issues at maintainer discretion; anything we accept is governed by the contribution terms above.

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
