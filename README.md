# KyaniteLabs Shared Config

Centralized workflow templates, org defaults, and agent governance configuration for the KyaniteLabs Forgejo instance. This repository serves as the single source of truth for CI/CD templates, AI agent policies, and organizational compliance tooling across all KyaniteLabs repositories.

## What is This?

KyaniteLabs Shared Config (`.github`) is the organizational meta-repository that powers CI/CD automation, dependency management, and AI agent governance for every project under the KyaniteLabs namespace. It contains Forgejo Actions workflow templates that can be instantiated in any org repository, Renovate and Dependabot configurations for automated dependency updates, agent policy documentation and enforcement scripts, and org-wide security and contribution guidelines.

## Features

- **Forgejo Actions Workflow Templates** — Ready-to-use CI templates for Go projects including `blacksmith-go-smoke` and `blacksmith-probe`, with associated metadata files for template discovery.
- **Automated Dependency Management** — Pre-configured `renovate.json` and `dependabot-template.yml` to keep dependencies up to date across all org repositories.
- **Agent Law Governance** — Documentation and provisioning scripts (`docs/agent-law/`, `scripts/provision-agent-law.py`) that define and enforce AI agent policies across repositories.
- **Agent Parity Checks** — `scripts/check-agent-parity.py` validates that agent configurations remain consistent across the organization.
- **Security Policy** — `SECURITY.md` defines responsible disclosure and vulnerability reporting procedures.
- **CODEOWNERS** — Automated review assignments for all changes.
- **Profile README** — A public-facing organization profile in `profile/README.md`.
- **CI Self-Tests** — `tests/test_agent_defaults.py` validates org default configurations stay green.

## Installation

This repository is not installed as a package. It is used by the Forgejo platform and other KyaniteLabs repositories directly.

**To use a workflow template in your repo:**

```bash
# Copy a workflow template into your repository
mkdir -p .forgejo/workflows
cp path/to/.github/workflow-templates/blacksmith-go-smoke.yml .forgejo/workflows/ci.yml
```

**To run the local scripts or tests, clone and install dependencies:**

```bash
git clone https://forgejo.kyanitelabs.com/KyaniteLabs/.github.git
cd .github

# Run agent parity checks
python scripts/check-agent-parity.py

# Run org default tests
python tests/test_agent_defaults.py
```

## Quick Start

1. **Enable CI for a new Go repo** — Copy `workflow-templates/blacksmith-go-smoke.yml` into `.forgejo/workflows/` in your repository. The workflow will run on push and pull request events.

2. **Provision agent-law policies** — Run the provisioning script to apply agent governance to a target repository:
   ```bash
   python scripts/provision-agent-law.py --target /path/to/repo
   ```

3. **Enable dependency updates** — Copy `renovate.json` or `dependabot-template.yml` into your repository root to activate automated dependency PRs.

## Usage

### Workflow Templates

| Template | Description | Metadata |
|----------|-------------|----------|
| `blacksmith-go-smoke.yml` | Go build and smoke test pipeline | `blacksmith-go-smoke.properties.json` |
| `blacksmith-probe.yml` | Lightweight probe/health-check workflow | `blacksmith-probe.properties.json` |

Each template has an accompanying `.properties.json` file that defines display name, description, and supported parameters for Forgejo's template picker UI.

### Scripts

```bash
# Check that agent configs are consistent across org repos
python scripts/check-agent-parity.py

# Apply agent-law provisions to a repository
python scripts/provision-agent-law.py --target <repo-path>
```

### Documentation

- **`docs/agent-law/`** — Agent governance policies, consent requirements, and operational constraints.
- **`docs/factory/`** — Factory-level configuration and architecture docs.
- **`AGENTS.md`** — Machine-readable agent behavior specifications.
- **`CLAUDE.md`** — Claude-specific agent configuration and constraints.

### Dependency Management

- **Renovate** — `renovate.json` configures update grouping, automerge rules, and schedule.
- **Dependabot** — `dependabot-template.yml` provides a starting point for Dependabot configuration in individual repos.

## FAQ

### How do I add a new workflow template?

Create the workflow YAML file and an accompanying `.properties.json` metadata file in `workflow-templates/`. The properties file must include `name`, `description`, and `fileRef` fields. See existing templates for reference.

### What is Agent Law?

Agent Law is KyaniteLabs' governance framework for AI agents operating on repositories. It defines what agents can and cannot do, consent requirements for automated changes, and audit trails. See `docs/agent-law/` for the full specification.

### How do I report a security vulnerability?

Please see [`SECURITY.md`](./SECURITY.md) for our responsible disclosure policy. Do **not** open a public issue for security vulnerabilities.

### Can I use these templates outside KyaniteLabs?

The templates are MIT-licensed and can be adapted for any Forgejo or Gitea instance. You may need to adjust runner labels, container images, and registry endpoints to match your environment.

### Why are there two dependency managers (Renovate and Dependabot)?

`renovate.json` is the primary configuration for this org. `dependabot-template.yml` is provided as a starter template for individual repos that prefer Dependabot or need it alongside Renovate for specific ecosystems.

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) for guidelines on branch naming, commit messages, and review expectations.

All changes are subject to review by the CODEOWNERS listed in [`CODEOWNERS`](./CODEOWNERS). CI must pass before merge.

```bash
# Clone and create a branch
git clone https://forgejo.kyanitelabs.com/KyaniteLabs/.github.git
cd .github
git checkout -b feature/my-change

# Make changes, commit, and push
git commit -m "feat: describe your change"
git push origin feature/my-change
```

## License

This project is licensed under the terms of the [MIT License](./LICENSE).