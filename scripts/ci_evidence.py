"""Layer 3 before/after evidence: summarize a CI run, and compare a PR against main.

`collect ROOT` reads what the CI profile already leaves in ROOT/.ci-results/
and writes ROOT/.ci-results/evidence.json:

  * status and per-phase seconds from the profile receipt (ci-profile.json);
  * test totals from the profile's JUnit reports;
  * line coverage, when a coverage summary exists (Istanbul
    coverage/coverage-summary.json or Cobertura coverage.xml);
  * byte sizes of built artifacts (.ci-results/dist/* and top-level
    .ci-results/*.tar, *.tgz, *.whl, *.zip), keyed with versions stripped so
    a version bump compares like with like;
  * Layer 6 structure signals from structure_signals.py (duplication, large
    files, complex Python functions).

`compare BASE HEAD` prints one `evidence delta:` line per measure and an
`evidence regression:` line for each advisory regression (fewer tests, a
missing test report, line coverage down more than 0.1 points, an artifact
more than 5% larger, duplication up more than 0.5 points, more large files
or complex functions). Comparison is advisory: it exits 0 even with
regressions, and only says so when no baseline exists yet.
Main-branch runs publish their evidence to the `ci-evidence` branch; PR runs
compare against it.
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SIZE_GROWTH_LIMIT = 0.05
# Coverage moves by a few hundredths between identical runs; flag real drops only.
COVERAGE_TOLERANCE_PTS = 0.1
DUPLICATION_TOLERANCE_PTS = 0.5
VERSION = re.compile(r"[-_]?v?\d+\.\d+\.\d+(?:-(?:alpha|beta|rc|dev|pre)\.?\d*)?(?=[-_.]|$)")


def junit_totals(root: Path, patterns: list[str]) -> dict[str, int] | None:
    total = failed = skipped = 0
    found = False
    for pattern in patterns:
        for path in glob.glob(str(root / pattern), recursive=True):
            found = True
            for case in ET.parse(path).getroot().iter("testcase"):
                total += 1
                if case.find("failure") is not None or case.find("error") is not None:
                    failed += 1
                elif case.find("skipped") is not None:
                    skipped += 1
    return {"total": total, "failed": failed, "skipped": skipped} if found else None


def coverage_pct(root: Path) -> float | None:
    summary = root / "coverage/coverage-summary.json"
    if summary.is_file():
        pct = json.loads(summary.read_text()).get("total", {}).get("lines", {}).get("pct")
        return round(float(pct), 2) if isinstance(pct, (int, float)) else None
    for name in ("coverage.xml", ".ci-results/coverage.xml"):
        path = root / name
        if path.is_file():
            rate = ET.parse(path).getroot().get("line-rate")
            return round(float(rate) * 100, 2) if rate is not None else None
    return None


def artifact_key(name: str) -> str:
    return VERSION.sub("", name)


def artifact_sizes(results: Path) -> dict[str, int]:
    paths = list((results / "dist").glob("*")) if (results / "dist").is_dir() else []
    for suffix in ("*.tar", "*.tgz", "*.whl", "*.zip"):
        paths += results.glob(suffix)
    sizes = {}
    for path in sorted(paths):
        if path.is_file() and path.name != "SHA256SUMS":
            sizes[artifact_key(path.name)] = path.stat().st_size
    return sizes


def structure(root: Path) -> dict | None:
    spec = importlib.util.spec_from_file_location("structure_signals", Path(__file__).with_name("structure_signals.py"))
    if spec is None or not Path(spec.origin).is_file():
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.measure(root)
    except (OSError, ValueError, RecursionError) as exc:
        print(f"evidence: structure signals skipped ({exc.__class__.__name__}: {exc})", file=sys.stderr)
        return None


def collect(root: Path, profile_name: str) -> dict:
    results = root / ".ci-results"
    receipt_path = results / "ci-profile.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
    profile_path = root / profile_name
    profile = json.loads(profile_path.read_text()) if profile_path.is_file() else {}
    phases: dict[str, float] = {}
    for step in receipt.get("steps", []):
        phase = step.get("phase") or "other"
        phases[phase] = round(phases.get(phase, 0.0) + float(step.get("elapsed_seconds", 0)), 3)
    evidence = {
        "version": 1,
        "source_sha": receipt.get("source_sha"),
        "status": receipt.get("status", "unknown"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "phases": phases,
        "tests": junit_totals(root, profile.get("junit_reports", [])),
        "coverage_lines_pct": coverage_pct(root),
        "artifacts": artifact_sizes(results),
        "structure": structure(root),
    }
    results.mkdir(parents=True, exist_ok=True)
    (results / "evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def human_bytes(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return str(value)


def compare(base: dict, head: dict) -> list[str]:
    lines, regressions = [], []
    bt, ht = base.get("tests") or {}, head.get("tests") or {}
    if ht:
        delta = ht.get("total", 0) - bt.get("total", 0)
        lines.append(f"tests {bt.get('total', '-')} -> {ht['total']} ({delta:+d})" if bt else f"tests - -> {ht['total']} (no base)")
        if bt and delta < 0:
            regressions.append(f"test count fell by {-delta}")
    elif bt:
        lines.append(f"tests {bt.get('total', '-')} -> - (no test report)")
        regressions.append("test report missing; main had one")
    bc, hc = base.get("coverage_lines_pct"), head.get("coverage_lines_pct")
    if hc is not None:
        if bc is None:
            lines.append(f"line coverage - -> {hc}% (no base)")
        else:
            lines.append(f"line coverage {bc}% -> {hc}% ({hc - bc:+.2f} pts)")
            if bc - hc > COVERAGE_TOLERANCE_PTS:
                regressions.append(f"line coverage fell {bc}% -> {hc}%")
    for phase, seconds in sorted((head.get("phases") or {}).items()):
        before = (base.get("phases") or {}).get(phase)
        lines.append(f"phase {phase} {before if before is not None else '-'}s -> {seconds}s")
    for key, size in sorted((head.get("artifacts") or {}).items()):
        before = (base.get("artifacts") or {}).get(key)
        if before is None:
            lines.append(f"artifact {key} - -> {human_bytes(size)} (new)")
            continue
        growth = (size - before) / before if before else 0.0
        lines.append(f"artifact {key} {human_bytes(before)} -> {human_bytes(size)} ({growth:+.1%})")
        if growth > SIZE_GROWTH_LIMIT:
            regressions.append(f"artifact {key} grew {growth:.1%} (limit {SIZE_GROWTH_LIMIT:.0%})")
    for key in sorted(set(base.get("artifacts") or {}) - set(head.get("artifacts") or {})):
        lines.append(f"artifact {key} {human_bytes(base['artifacts'][key])} -> - (gone)")
    bs, hs = base.get("structure") or {}, head.get("structure") or {}
    if hs:
        bd, hd = bs.get("duplicated_lines_pct"), hs.get("duplicated_lines_pct")
        if bd is None:
            lines.append(f"duplicated lines - -> {hd}% (no base)")
        else:
            lines.append(f"duplicated lines {bd}% -> {hd}% ({hd - bd:+.2f} pts)")
            if hd - bd > DUPLICATION_TOLERANCE_PTS:
                regressions.append(f"duplicated lines rose {bd}% -> {hd}%")
        for key, label in (("large_files", "large files"), ("python_complex_functions", "complex Python functions")):
            before, after = bs.get(key), hs.get(key)
            if after is None:
                continue
            lines.append(f"{label} {before if before is not None else '-'} -> {after}")
            if before is not None and after > before:
                regressions.append(f"{label} rose {before} -> {after}")
    return [f"evidence delta: {line}" for line in lines] + [f"evidence regression: {line}" for line in regressions]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="write .ci-results/evidence.json")
    c.add_argument("root", nargs="?", default=".")
    c.add_argument("--profile", default=".ci/profile.json")
    d = sub.add_parser("compare", help="print advisory deltas from BASE to HEAD")
    d.add_argument("base")
    d.add_argument("head")
    args = parser.parse_args(argv)
    if args.command == "collect":
        try:
            evidence = collect(Path(args.root).resolve(), args.profile)
        except (OSError, ValueError, ET.ParseError) as exc:
            print(f"evidence: collection failed ({exc.__class__.__name__}: {exc})", file=sys.stderr)
            return 1
        tests = evidence["tests"] or {}
        print(f"evidence: collected (status {evidence['status']}, tests {tests.get('total', '-')}, "
              f"coverage {evidence['coverage_lines_pct'] if evidence['coverage_lines_pct'] is not None else '-'}, "
              f"{len(evidence['artifacts'])} artifact(s), "
              f"duplication {(evidence['structure'] or {}).get('duplicated_lines_pct', '-')}%)")
        return 0
    try:
        head = json.loads(Path(args.head).read_text())
    except (OSError, ValueError) as exc:
        print(f"evidence: head evidence unreadable ({exc.__class__.__name__})", file=sys.stderr)
        return 1
    try:
        base = json.loads(Path(args.base).read_text())
    except (OSError, ValueError):
        print("evidence: no main baseline yet (it is published by the first main-branch run)")
        return 0
    lines = compare(base, head)
    print(f"evidence: comparing against main {str(base.get('source_sha') or '?')[:12]}")
    for line in lines:
        print(line)
    flagged = sum(line.startswith("evidence regression:") for line in lines)
    print(f"evidence: {flagged} advisory regression(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
