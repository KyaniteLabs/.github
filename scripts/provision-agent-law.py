#!/usr/bin/env python3
"""Provision Empower Orchestrator / Agent Law across an owner namespace.

This script is intentionally self-contained so the `.github` hub repository can
repair new or drifting repositories without depending on a package install.

Default behavior is audit-only. Pass `--apply` to create/update rulesets and
open repair PRs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

START = "<!-- EMPOWER_ORCHESTRATOR:START -->"
END = "<!-- EMPOWER_ORCHESTRATOR:END -->"
BRANCH_DEFAULT = "codex/provision-agent-law"
RULESET_NAME = "Agent Law"


@dataclass(frozen=True)
class Repo:
    name_with_owner: str
    default_branch: str
    is_archived: bool
    is_fork: bool
    url: str

    @property
    def name(self) -> str:
        return self.name_with_owner.split("/", 1)[1]


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and cp.returncode != 0:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{cp.stdout}")
    return cp


def gh_api(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [
        "gh",
        "api",
        "-X",
        method,
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2022-11-28",
        path,
    ]
    tmp: Path | None = None
    try:
        if payload is not None:
            fd, name = tempfile.mkstemp(prefix="agent-law-payload-", suffix=".json")
            os.close(fd)
            tmp = Path(name)
            tmp.write_text(json.dumps(payload, indent=2))
            cmd += ["--input", str(tmp)]
        return run(cmd, check=check)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def is_org(owner: str) -> bool:
    return gh_api(f"/orgs/{owner}", check=False).returncode == 0


def list_repos(owner: str) -> list[Repo]:
    cp = run([
        "gh",
        "repo",
        "list",
        owner,
        "--limit",
        "1000",
        "--json",
        "nameWithOwner,isArchived,isFork,defaultBranchRef,url",
    ])
    repos = []
    for item in json.loads(cp.stdout):
        ref = item.get("defaultBranchRef") or {}
        repos.append(
            Repo(
                name_with_owner=item["nameWithOwner"],
                default_branch=ref.get("name") or "main",
                is_archived=bool(item.get("isArchived")),
                is_fork=bool(item.get("isFork")),
                url=item["url"],
            )
        )
    return [repo for repo in repos if not repo.is_archived and not repo.is_fork]


def repo_ruleset_payload() -> dict[str, Any]:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": base_rules(),
    }


def org_ruleset_payload() -> dict[str, Any]:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "repository_name": {"include": ["~ALL"], "exclude": [], "protected": False},
            "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        },
        "rules": base_rules(),
    }


def base_rules() -> list[dict[str, Any]]:
    return [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 0,
                "dismiss_stale_reviews_on_push": False,
                "require_code_owner_review": False,
                "require_last_push_approval": False,
                "required_review_thread_resolution": False,
                "required_reviewers": [],
                "allowed_merge_methods": ["merge", "squash", "rebase"],
            },
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": True,
                "required_status_checks": [{"context": "agent-law"}],
            },
        },
    ]


def ensure_org_ruleset(owner: str, *, apply: bool) -> str:
    if not is_org(owner):
        return "skipped:not-org"
    listed = gh_api(f"/orgs/{owner}/rulesets", check=False)
    if listed.returncode != 0:
        if not apply:
            return "skipped:admin-org-scope-required"
        return "blocked:admin-org-scope-required"
    for item in json.loads(listed.stdout or "[]"):
        if item.get("name") == RULESET_NAME:
            return f"exists:{item.get('id')}"
    if not apply:
        return "missing:dry-run"
    created = gh_api(f"/orgs/{owner}/rulesets", method="POST", payload=org_ruleset_payload())
    return f"created:{json.loads(created.stdout).get('id')}"


def ensure_repo_ruleset(repo: Repo, *, apply: bool) -> str:
    listed = gh_api(f"/repos/{repo.name_with_owner}/rulesets", check=False)
    if listed.returncode != 0:
        if not apply:
            return "skipped:repo-admin-required"
        return "blocked:repo-admin-required"
    for item in json.loads(listed.stdout or "[]"):
        if item.get("name") == RULESET_NAME:
            return f"exists:{item.get('id')}"
    if not apply:
        return "missing:dry-run"
    created = gh_api(f"/repos/{repo.name_with_owner}/rulesets", method="POST", payload=repo_ruleset_payload())
    return f"created:{json.loads(created.stdout).get('id')}"


def hub_recipe() -> str:
    path = Path("docs/agent-law/empower-orchestrator.md")
    if path.exists():
        return path.read_text()
    return """# Empower Orchestrator Agent Law\n\nEvery top-level/orchestrator session is an audition to improve the system, not only finish the task. Before automation, state the four-question blast-radius check: scale, severity, reversibility, predictability.\n"""


def law_block(recipe_path: str = "docs/agent-law/empower-orchestrator.md") -> str:
    return f"""{START}
## Empower the Orchestrator

This repository is governed by the Empower Orchestrator law. Every top-level/orchestrator agent session is an audition to improve the system, not only finish the current task.

When you notice a repeatable task done 3+ times or a recurring agent failure mode, consider shipping the smallest durable artifact that prevents the repetition: a tool, skill, slash command, hook, guardrail, memory entry, test, verifier, or doctrine doc.

This applies to top-level/orchestrator sessions. Background workers execute their assigned slice and do not independently widen scope.

Before dispatching automation or creating a durable system change, state the four-question blast-radius check in chat:

1. Scale: one file/workspace/all sessions?
2. Severity: minor friction/broken workflow/data loss or leaked content?
3. Reversibility: single revert/manual cleanup/surgery?
4. Predictability: bounded failure mode/guessing/unknown?

All green permits auto mode. Any yellow requires inline human approval. Any red means do not dispatch; do the work inline or escalate.

Worker discipline: isolated worktree/sandbox, one artifact equals one commit/change unit, verify before commit, register through the target tool's native discovery surface, and never write outside the assigned scope.

Success line: “I noticed X, found a better way. The system just got an upgrade.”

Full recipe: `{recipe_path}`.
{END}"""


def pr_template_block() -> str:
    return f"""{START}
## Empower Orchestrator checklist

- [ ] I checked whether this PR reveals a repeatable task or recurring agent failure.
- [ ] If it does, I either shipped the smallest durable improvement or documented why not.
- [ ] Any automation or durable system change included the scale/severity/reversibility/predictability blast-radius check.
- [ ] Workers/subagents stayed inside their assigned scope and verification evidence is included before completion claims.
{END}"""


def contributing_block() -> str:
    return f"""{START}
## Agent-law contribution rule

This repository follows the Empower Orchestrator law in `docs/agent-law/empower-orchestrator.md`.

If a change exposes a repeated task or repeated agent failure, contributors and agents should either ship the smallest durable prevention artifact or explain why this PR is intentionally one-off.

Automation and durable system changes require the scale/severity/reversibility/predictability blast-radius check before dispatch.
{END}"""


def workflow_text() -> str:
    return """name: Agent Law

on:
  pull_request:
  merge_group:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  agent-law:
    name: agent-law
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Verify Empower Orchestrator law
        shell: bash
        run: |
          set -euo pipefail
          fail=0

          require_file() {
            local path="$1"
            if [[ ! -f "$path" ]]; then
              echo "::error file=$path::Required agent-law file is missing"
              fail=1
            fi
          }

          require_marker() {
            local path="$1"
            if [[ ! -f "$path" ]]; then
              echo "::error file=$path::Required file is missing"
              fail=1
              return
            fi
            if ! grep -q 'EMPOWER_ORCHESTRATOR:START' "$path"; then
              echo "::error file=$path::Missing EMPOWER_ORCHESTRATOR marker"
              fail=1
            fi
          }

          recipe="docs/agent-law/empower-orchestrator.md"
          if [[ ! -f "$recipe" && -f "Docs/agent-law/empower-orchestrator.md" ]]; then
            recipe="Docs/agent-law/empower-orchestrator.md"
          fi

          require_file "$recipe"
          require_marker "AGENTS.md"
          require_marker "CLAUDE.md"

          if [[ ! -f ".github/pull_request_template.md" && ! -f ".github/PULL_REQUEST_TEMPLATE.md" && ! -f "pull_request_template.md" && ! -f "PULL_REQUEST_TEMPLATE.md" && ! -f "docs/pull_request_template.md" && ! -f "docs/PULL_REQUEST_TEMPLATE.md" ]]; then
            echo "::error::.github/pull_request_template.md or equivalent PR template is required"
            fail=1
          elif ! grep -R -q 'EMPOWER_ORCHESTRATOR:START' .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE.md pull_request_template.md PULL_REQUEST_TEMPLATE.md docs/pull_request_template.md docs/PULL_REQUEST_TEMPLATE.md 2>/dev/null; then
            echo "::error::PR template exists but lacks EMPOWER_ORCHESTRATOR marker"
            fail=1
          fi

          if ! grep -q 'four-question blast-radius check' "$recipe"; then
            echo "::error file=$recipe::Recipe must name the four-question blast-radius check"
            fail=1
          fi

          if [[ "$fail" != 0 ]]; then
            exit 1
          fi

          echo "Empower Orchestrator agent law is present."
"""


def upsert_marker_file(path: Path, block: str, header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else header.rstrip() + "\n"
    if START in text and END in text:
        before, rest = text.split(START, 1)
        _old, after = rest.split(END, 1)
        text = before.rstrip() + "\n\n" + block + after
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text)


def choose_recipe_path(repo_dir: Path) -> Path:
    # Respect repos that already use a capitalized Docs tree on case-insensitive machines.
    if (repo_dir / "Docs").exists() and not (repo_dir / "docs").exists():
        return repo_dir / "Docs" / "agent-law" / "empower-orchestrator.md"
    return repo_dir / "docs" / "agent-law" / "empower-orchestrator.md"


def choose_pr_template(repo_dir: Path) -> Path:
    candidates = [
        repo_dir / ".github" / "pull_request_template.md",
        repo_dir / ".github" / "PULL_REQUEST_TEMPLATE.md",
        repo_dir / "pull_request_template.md",
        repo_dir / "PULL_REQUEST_TEMPLATE.md",
        repo_dir / "docs" / "pull_request_template.md",
        repo_dir / "docs" / "PULL_REQUEST_TEMPLATE.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return repo_dir / ".github" / "pull_request_template.md"


def apply_payload(repo_dir: Path) -> None:
    recipe_path = choose_recipe_path(repo_dir)
    recipe_rel = str(recipe_path.relative_to(repo_dir))
    upsert_marker_file(repo_dir / "AGENTS.md", law_block(recipe_rel), "# AGENTS.md instructions")
    upsert_marker_file(repo_dir / "CLAUDE.md", law_block(recipe_rel), "# CLAUDE.md instructions")
    upsert_marker_file(repo_dir / "CONTRIBUTING.md", contributing_block(), "# Contributing")
    upsert_marker_file(choose_pr_template(repo_dir), pr_template_block(), "# Pull Request")
    recipe_path.parent.mkdir(parents=True, exist_ok=True)
    recipe_path.write_text(hub_recipe())
    workflow = repo_dir / ".github" / "workflows" / "agent-law.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(workflow_text())


def repo_is_compliant(repo_dir: Path) -> bool:
    required = ["AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".github/workflows/agent-law.yml"]
    if not all((repo_dir / path).exists() for path in required):
        return False
    if not all(START in (repo_dir / path).read_text(errors="ignore") for path in ["AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md"]):
        return False
    recipes = [repo_dir / "docs" / "agent-law" / "empower-orchestrator.md", repo_dir / "Docs" / "agent-law" / "empower-orchestrator.md"]
    if not any(path.exists() for path in recipes):
        return False
    templates = [
        repo_dir / ".github" / "pull_request_template.md",
        repo_dir / ".github" / "PULL_REQUEST_TEMPLATE.md",
        repo_dir / "pull_request_template.md",
        repo_dir / "PULL_REQUEST_TEMPLATE.md",
        repo_dir / "docs" / "pull_request_template.md",
        repo_dir / "docs" / "PULL_REQUEST_TEMPLATE.md",
    ]
    return any(path.exists() and START in path.read_text(errors="ignore") for path in templates)


def remote_branch_exists(repo: Repo, branch: str) -> bool:
    cp = run(["git", "ls-remote", "--heads", repo.url, branch], check=False)
    return bool(cp.stdout.strip())


def repair_files(repo: Repo, *, apply: bool, branch: str, workdir: Path) -> str:
    repo_dir = workdir / repo.name_with_owner.replace("/", "__")
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    cp = run(["gh", "repo", "clone", repo.name_with_owner, str(repo_dir), "--", "--depth", "1", "--branch", repo.default_branch], check=False)
    if cp.returncode != 0:
        return "blocked:clone-failed"
    if repo_is_compliant(repo_dir):
        return "compliant"
    if not apply:
        return "missing:dry-run"

    run(["git", "config", "user.name", "agent-law-provisioner"], cwd=repo_dir)
    run(["git", "config", "user.email", "agent-law-provisioner@users.noreply.github.com"], cwd=repo_dir)
    if remote_branch_exists(repo, branch):
        run(["git", "fetch", "origin", branch], cwd=repo_dir)
        run(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=repo_dir)
    else:
        run(["git", "checkout", "-B", branch], cwd=repo_dir)
    apply_payload(repo_dir)
    if repo_is_compliant(repo_dir) is False:
        return "blocked:payload-verification-failed"
    if not run(["git", "status", "--short"], cwd=repo_dir).stdout.strip():
        return "compliant-after-checkout"
    run(["git", "add", "-f", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".github/workflows/agent-law.yml"], cwd=repo_dir)
    for candidate in [
        "docs/agent-law/empower-orchestrator.md",
        "Docs/agent-law/empower-orchestrator.md",
        ".github/pull_request_template.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "pull_request_template.md",
        "PULL_REQUEST_TEMPLATE.md",
        "docs/pull_request_template.md",
        "docs/PULL_REQUEST_TEMPLATE.md",
    ]:
        if (repo_dir / candidate).exists():
            run(["git", "add", "-f", candidate], cwd=repo_dir)
    run([
        "git",
        "commit",
        "-m",
        "Make Empower Orchestrator law repo-local\n\nConstraint: Provisioned by the Agent Law hub to repair a missing or drifting repo.\nRejected: Leaving new repos to inherit only global defaults | Agents and reviewers need repo-local law.\nConfidence: high\nScope-risk: moderate\nDirective: Keep EMPOWER_ORCHESTRATOR markers and agent-law workflow in sync.\nTested: Provisioner verified required files and marker presence before commit.\nNot-tested: Repository-specific application build/test suites.",
    ], cwd=repo_dir)
    run(["git", "push", "-u", "origin", branch], cwd=repo_dir)
    existing = run(["gh", "pr", "list", "--repo", repo.name_with_owner, "--head", branch, "--json", "url", "--jq", ".[0].url // empty"], check=False).stdout.strip()
    if existing:
        return f"pr:{existing}"
    body = f"""## Summary

The Agent Law provisioner found `{repo.name_with_owner}` missing or drifting from the Empower Orchestrator law and repaired it with repo-local doctrine plus the `agent-law` workflow.

## Verification

- Provisioner verified required files and `EMPOWER_ORCHESTRATOR` marker presence before commit.
"""
    body_path = repo_dir / ".agent-law-pr-body.md"
    body_path.write_text(body)
    created = run([
        "gh",
        "pr",
        "create",
        "--repo",
        repo.name_with_owner,
        "--base",
        repo.default_branch,
        "--head",
        branch,
        "--title",
        "Make Empower Orchestrator law repo-local",
        "--body-file",
        str(body_path),
    ], cwd=repo_dir)
    return f"pr:{created.stdout.strip().splitlines()[-1]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, help="GitHub org or user to provision")
    parser.add_argument("--apply", action="store_true", help="Create/update rulesets and repair PRs. Omit for audit-only.")
    parser.add_argument("--ensure-org-ruleset", action="store_true", help="Create an owner-level ruleset when owner is an org and token has admin:org.")
    parser.add_argument("--ensure-repo-rulesets", action="store_true", help="Create per-repo Agent Law rulesets.")
    parser.add_argument("--repair-files", action="store_true", help="Open repair PRs for repos missing Agent Law files.")
    parser.add_argument("--branch", default=BRANCH_DEFAULT)
    args = parser.parse_args()

    if not shutil.which("gh"):
        raise SystemExit("gh CLI is required")
    if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
        print("::warning::GH_TOKEN/GITHUB_TOKEN is not set; gh auth must already be configured", file=sys.stderr)

    rows: list[dict[str, str]] = []
    if args.ensure_org_ruleset:
        status = ensure_org_ruleset(args.owner, apply=args.apply)
        rows.append({"scope": args.owner, "kind": "org-ruleset", "status": status})
        print(f"{args.owner}\torg-ruleset\t{status}")

    repos = list_repos(args.owner)
    with tempfile.TemporaryDirectory(prefix="agent-law-provision-") as tmp:
        workdir = Path(tmp)
        for repo in repos:
            if args.ensure_repo_rulesets:
                status = ensure_repo_ruleset(repo, apply=args.apply)
                rows.append({"scope": repo.name_with_owner, "kind": "repo-ruleset", "status": status})
                print(f"{repo.name_with_owner}\trepo-ruleset\t{status}")
            if args.repair_files:
                status = repair_files(repo, apply=args.apply, branch=args.branch, workdir=workdir)
                rows.append({"scope": repo.name_with_owner, "kind": "files", "status": status})
                print(f"{repo.name_with_owner}\tfiles\t{status}")

    Path("agent-law-provisioner-results.json").write_text(json.dumps(rows, indent=2) + "\n")
    blocked = [row for row in rows if row["status"].startswith("blocked")]
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
