"""Read CI adoption signals through the configured fj credential; never mutate."""

import argparse
import base64
import json
import re
import subprocess
from urllib.parse import quote

PHASES = {"install", "verify", "build", "test", "acceptance"}


class LookupFailed(Exception):
    """A lookup did not produce usable evidence; do not infer absence."""


def repository(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise argparse.ArgumentTypeError("expected owner/repository")
    if any(part in {".", ".."} for part in value.split("/")):
        raise argparse.ArgumentTypeError("invalid repository segment")
    return value


def fetch(path):
    result = subprocess.run(
        ["fj", "api", "GET", path], capture_output=True, text=True, timeout=45,
        check=False,
    )
    if result.returncode:
        raise LookupFailed(f"GET {path}: lookup unavailable")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LookupFailed(f"GET {path}: invalid JSON") from error


def contents(get, repo, path, ref):
    item = get(f"repos/{repo}/contents/{path}?ref={quote(ref, safe='')}")
    if item.get("encoding") != "base64":
        raise LookupFailed(f"unsupported content encoding: {path}")
    return base64.b64decode(item["content"]).decode("utf-8")


def profile_signals(text):
    profile = json.loads(text)
    if not isinstance(profile, dict) or not isinstance(profile.get("steps", []), list):
        raise TypeError("invalid profile shape")
    steps = profile.get("steps", [])
    if any(not isinstance(step, dict) for step in steps):
        raise TypeError("invalid step shape")
    return {
        "version": profile.get("version"),
        "missing_phases": sorted(PHASES - {step.get("phase") for step in steps}),
        "commands_declared": bool(steps) and all(
            isinstance(step.get("argv"), list) and bool(step["argv"])
            and all(isinstance(arg, str) and arg for arg in step["argv"])
            for step in steps
        ),
        "junit_pattern_count": len(profile.get("junit_reports", [])),
        "note": "Declarations do not prove execution or artifact acceptance.",
    }


def audit(repo, get=fetch, shared_repo="KyaniteLabs/.github", pull_request=None):
    repo, shared_repo = repository(repo), repository(shared_repo)
    report = {"repository": repo, "scope": "adoption-signals-only", "errors": []}
    metadata = get(f"repos/{repo}")
    branch = metadata["default_branch"]
    head = get(f"repos/{repo}/branches/{quote(branch, safe='')}")["commit"]["id"]
    report.update(default_branch=branch, source_sha=head)
    if pull_request is not None:
        head = get(f"repos/{repo}/pulls/{pull_request}")["head"]["sha"]
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (head, report["source_sha"])):
        raise LookupFailed("source identity unavailable")
    report["status_source"] = {"sha": head, "pull_request": pull_request}
    statuses = get(f"repos/{repo}/commits/{head}/status")
    items = statuses.get("statuses") or []
    observed = {item["context"] for item in items}
    report["observed_statuses"] = [
        {"context": item["context"], "state": item.get("status", item.get("state"))}
        for item in items
    ]
    rules = get(f"repos/{repo}/branch_protections") or []
    report["matching_protections"] = [
        {key: rule.get(key) for key in (
            "branch_name", "enable_status_check", "status_check_contexts",
            "apply_to_admins", "enable_push",
        )}
        for rule in rules if branch == rule.get("branch_name")
    ]
    report["pattern_rules_for_review"] = [
        rule.get("branch_name") for rule in rules
        if any(character in rule.get("branch_name", "") for character in "*?[")
    ]
    enabled = [rule for rule in report["matching_protections"] if rule["enable_status_check"]]
    report["status_checks_enabled"] = bool(enabled)
    report["admin_status_enforcement"] = any(rule["apply_to_admins"] for rule in enabled)
    if not report["matching_protections"] and report["pattern_rules_for_review"]:
        report["status_checks_enabled"] = None
        report["admin_status_enforcement"] = None
    required = sorted({context for rule in enabled for context in (rule["status_check_contexts"] or [])})
    report["required_contexts"] = required
    report["required_context_patterns_for_review"] = [
        context for context in required if any(character in context for character in "*?[]{}\\")
    ]
    report["required_contexts_absent_from_supplied_pr"] = (
        sorted(set(required) - observed)
        if pull_request is not None and required and not report["required_context_patterns_for_review"]
        else None
    )
    for path, kind in ((".ci/profile.json", "profile"), (".forgejo/workflows/ci.yml", "workflow")):
        try:
            text = contents(get, repo, path, report["source_sha"])
            if kind == "profile":
                report[kind] = profile_signals(text)
            else:
                pattern = re.escape(shared_repo) + r"/\.forgejo/workflows/ci-profile\.yml@([0-9a-f]{40})(?=\s|$)"
                report["shared_workflow_pins"] = sorted(set(re.findall(pattern, text)))
                report["failure_masking_review_lines"] = [
                    number for number, line in enumerate(text.splitlines(), 1)
                    if re.search(r"\|\|\s*(?:true|echo\b)", line)
                ]
        except (LookupFailed, ValueError, KeyError, TypeError, UnicodeError) as error:
            report["errors"].append(f"{path}: {type(error).__name__}")
    report["audit_status"] = "incomplete" if report["errors"] else "complete"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=repository)
    parser.add_argument("--shared-repo", default="KyaniteLabs/.github", type=repository)
    parser.add_argument("--pull-request", type=int, help="Compare required names to this PR's emitted statuses")
    args = parser.parse_args()
    if args.pull_request is not None and args.pull_request <= 0:
        parser.error("pull request number must be positive")
    try:
        result = audit(args.repo, shared_repo=args.shared_repo, pull_request=args.pull_request)
    except (LookupFailed, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {"repository": args.repo, "audit_status": "incomplete", "error": type(error).__name__}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["audit_status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
