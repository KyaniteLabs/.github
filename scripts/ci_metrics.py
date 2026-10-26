"""Measure CI queue time, runtime and duplicate runs through the fj credential; never mutate.

Layer 4 baseline: before optimizing anything, measure p50/p95 queue time
(started - created) and runtime (stopped - started) per workflow and event,
and count duplicate runs (one commit built more than once by the same
workflow). Runs without both timestamps are counted but not measured, so a
missing number is visible instead of being folded into the percentiles.
"""

import argparse
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

PAGE = 50


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
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LookupFailed(f"GET {path}: invalid JSON") from error
    # fj wraps some responses as {"ok": ..., "data": ...}.
    if isinstance(data, dict) and "ok" in data and "data" in data:
        data = data["data"]
    return data


def timestamp(value):
    """Parse an API timestamp; zero or absent values mean the step never happened."""
    if not isinstance(value, str) or not value or value.startswith("0001-"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def runs(repo, get=fetch, limit=200, since=None):
    """Newest-first runs, stopping at `limit` or at the first run created before `since`."""
    repo = repository(repo)
    collected, page = [], 1
    while len(collected) < limit:
        body = get(f"repos/{repo}/actions/runs?limit={PAGE}&page={page}")
        batch = body.get("workflow_runs") if isinstance(body, dict) else None
        if not isinstance(batch, list):
            raise LookupFailed(f"{repo}: runs response has no workflow_runs list")
        for run in batch:
            created = timestamp(run.get("created"))
            if since and created and created < since:
                return collected
            collected.append(run)
            if len(collected) == limit:
                return collected
        if len(batch) < PAGE:
            return collected
        page += 1
    return collected


def percentile(values, fraction):
    """Nearest-rank percentile; None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def summarize(repo, items):
    groups = defaultdict(lambda: {"queue": [], "runtime": [], "runs": 0, "unmeasured": 0})
    outcomes = Counter()
    builds = defaultdict(list)
    for run in items:
        key = (run.get("workflow_id") or "?", run.get("trigger_event") or run.get("event") or "?")
        group = groups[key]
        group["runs"] += 1
        outcomes[run.get("status") or "unknown"] += 1
        created, started, stopped = (timestamp(run.get(k)) for k in ("created", "started", "stopped"))
        if created and started and stopped and created <= started <= stopped:
            group["queue"].append((started - created).total_seconds())
            group["runtime"].append((stopped - started).total_seconds())
        else:
            group["unmeasured"] += 1
        if run.get("commit_sha"):
            builds[(key[0], run["commit_sha"])].append(key[1])
    duplicated = {build: events for build, events in builds.items() if len(events) > 1}
    rows = []
    for (workflow, event), group in sorted(groups.items()):
        rows.append({
            "workflow": workflow,
            "event": event,
            "runs": group["runs"],
            "unmeasured": group["unmeasured"],
            "queue_p50": percentile(group["queue"], 0.5),
            "queue_p95": percentile(group["queue"], 0.95),
            "runtime_p50": percentile(group["runtime"], 0.5),
            "runtime_p95": percentile(group["runtime"], 0.95),
        })
    return {
        "repository": repo,
        "runs": len(items),
        "outcomes": dict(outcomes),
        "rows": rows,
        "duplicate_builds": len(duplicated),
        "extra_runs": sum(len(events) - 1 for events in duplicated.values()),
        "cross_event_duplicates": sum(1 for events in duplicated.values() if len(set(events)) > 1),
    }


def seconds(value):
    if value is None:
        return "-"
    value = round(value)
    return f"{value // 60}m{value % 60:02d}s" if value >= 60 else f"{value}s"


def markdown(reports, generated):
    lines = [f"# CI metrics baseline ({generated})", "",
             "Queue = started - created; runtime = stopped - started; nearest-rank percentiles.", "",
             "| Repository | Workflow | Event | Runs | Unmeasured | Queue p50 | Queue p95 | Runtime p50 | Runtime p95 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for report in reports:
        if "error" in report:
            lines.append(f"| {report['repository']} | - | - | - | - | unavailable: {report['error']} | | | |")
            continue
        for row in report["rows"]:
            lines.append(
                f"| {report['repository']} | {row['workflow']} | {row['event']} | {row['runs']} | {row['unmeasured']} "
                f"| {seconds(row['queue_p50'])} | {seconds(row['queue_p95'])} "
                f"| {seconds(row['runtime_p50'])} | {seconds(row['runtime_p95'])} |"
            )
    lines += ["", "## Duplicate runs (same workflow, same commit)", "",
              "| Repository | Runs | Duplicated commits | Extra runs | Across events | Outcomes |",
              "|---|---|---|---|---|---|"]
    for report in reports:
        if "error" in report:
            continue
        outcomes = ", ".join(f"{k} {v}" for k, v in sorted(report["outcomes"].items()))
        lines.append(
            f"| {report['repository']} | {report['runs']} | {report['duplicate_builds']} "
            f"| {report['extra_runs']} | {report['cross_event_duplicates']} | {outcomes} |"
        )
    return "\n".join(lines) + "\n"


def main(argv=None, get=fetch, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repositories", nargs="+", type=repository, help="owner/repository")
    parser.add_argument("--limit", type=int, default=200, help="newest runs per repository (default 200)")
    parser.add_argument("--days", type=int, default=30, help="ignore runs created earlier (default 30)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    args = parser.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)
    reports = []
    for repo in args.repositories:
        try:
            reports.append(summarize(repo, runs(repo, get, args.limit, since)))
        except LookupFailed as error:
            reports.append({"repository": repo, "error": str(error)})
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print(markdown(reports, now.strftime("%Y-%m-%d")), end="")
    return 1 if any("error" in report for report in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
