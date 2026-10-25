"""Layer 5 self-description check: a repository must describe itself consistently.

Offline and stdlib-only, so it runs inside any CI job. The package manifest
(package.json, pyproject.toml or setup.py) is the source of truth for the
name and version. Every other self-description the repository ships must
agree with it:

  * the newest released CHANGELOG entry, and at most one "Unreleased" section;
  * MCP server.json (version and each package version);
  * MCPB / plugin / extension manifests that declare a version;
  * README pins written as <name>@<x.y.z>;
  * README install commands, which must not name a near-miss of the package
    (running a declared bin, as in `npx <bin>` after install, is allowed).

Exit 0 when consistent, 1 on any mismatch, 2 when no version source exists.
Evidence lines name every source compared, so a pass is visible in CI logs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"
VERSIONED_MANIFESTS = (
    "mcpb/manifest.json",
    "manifest.json",
    "gemini-extension.json",
    ".claude-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
)


def package_bins(root: Path) -> set[str]:
    """Executable names the package declares; `npx <bin>` after install is valid."""
    pkg = root / "package.json"
    if not pkg.is_file():
        return set()
    bins = json.loads(pkg.read_text(encoding="utf-8")).get("bin") or {}
    return set(bins) if isinstance(bins, dict) else set()


def package_source(root: Path) -> tuple[str, str | None, str] | None:
    """Return (name, version, source) from the first manifest that declares them."""
    pkg = root / "package.json"
    if pkg.is_file():
        data = json.loads(pkg.read_text(encoding="utf-8"))
        if data.get("version"):
            return data.get("name") or "", data["version"], "package.json"
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        if project.get("version"):
            return project.get("name") or "", project["version"], "pyproject.toml"
    setup = root / "setup.py"
    if setup.is_file():
        text = setup.read_text(encoding="utf-8")
        version = re.search(r"""version\s*=\s*["']([^"']+)["']""", text)
        name = re.search(r"""name\s*=\s*["']([^"']+)["']""", text)
        if version:
            return (name.group(1) if name else ""), version.group(1), "setup.py"
    return None


def changelog_findings(root: Path, version: str) -> tuple[list[str], list[str]]:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return [], ["CHANGELOG.md: absent (skipped)"]
    headings = re.findall(r"^##\s+(.*)$", path.read_text(encoding="utf-8"), re.M)
    unreleased = [h for h in headings if re.match(r"\[?unreleased\]?", h, re.I)]
    released = [m.group(1) for h in headings if (m := re.match(rf"\[?v?({SEMVER})\]?", h))]
    errors = []
    if len(unreleased) > 1:
        errors.append(f"CHANGELOG.md: {len(unreleased)} 'Unreleased' sections; keep exactly one at the top")
    if not released:
        errors.append("CHANGELOG.md: no released version heading")
    elif released[0] != version:
        errors.append(f"CHANGELOG.md: newest released entry is {released[0]}, package is {version}")
    return errors, [f"CHANGELOG.md: newest released entry {released[0] if released else '-'}"]


def manifest_findings(root: Path, version: str) -> tuple[list[str], list[str]]:
    errors, evidence = [], []
    server = root / "server.json"
    if server.is_file():
        data = json.loads(server.read_text(encoding="utf-8"))
        found = [("server.json version", data.get("version"))]
        found += [(f"server.json packages[{i}].version", p.get("version")) for i, p in enumerate(data.get("packages", []))]
        for label, value in found:
            evidence.append(f"{label}: {value}")
            if value != version:
                errors.append(f"{label} is {value}, package is {version}")
    for rel in VERSIONED_MANIFESTS:
        path = root / rel
        if not path.is_file():
            continue
        value = json.loads(path.read_text(encoding="utf-8")).get("version")
        if value is None:
            continue
        evidence.append(f"{rel} version: {value}")
        if value != version:
            errors.append(f"{rel} version is {value}, package is {version}")
    return errors, evidence


def readme_findings(root: Path, name: str, version: str) -> tuple[list[str], list[str]]:
    path = root / "README.md"
    if not path.is_file() or not name:
        return [], ["README.md: skipped (absent or unnamed package)"]
    text = path.read_text(encoding="utf-8")
    errors = []
    pins = set(re.findall(rf"{re.escape(name)}@({SEMVER})", text))
    for pin in sorted(pins - {version}):
        errors.append(f"README.md pins {name}@{pin}, package is {version}")
    base = name.rsplit("/", 1)[-1].lower()
    bins = package_bins(root)
    commands = re.findall(
        r"(npm\s+(?:i|install)(?:\s+-g)?|pnpm\s+add|pip\s+install|npx(?:\s+-y)?|uvx)\s+(@?[\w./-]+)", text
    )
    installs = {target for _, target in commands}
    for command, target in sorted(set(commands)):
        bare = re.sub(rf"@{SEMVER}$", "", target)
        runs_bin = command.startswith(("npx", "uvx")) and bare in bins
        if bare != name and not runs_bin and bare.rsplit("/", 1)[-1].lower() == base:
            errors.append(f"README.md installs '{bare}', package is '{name}'")
    return errors, [f"README.md: {len(pins)} version pin(s), {len(set(installs))} install command(s)"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=".", help="repository root (default: .)")
    root = Path(parser.parse_args(argv).root)
    source = package_source(root)
    if source is None:
        print("self-description: no version source (package.json, pyproject.toml, setup.py)", file=sys.stderr)
        return 2
    name, version, origin = source
    errors, evidence = [], [f"source of truth: {origin} -> {name or '(unnamed)'} {version}"]
    for check in (
        lambda: changelog_findings(root, version),
        lambda: manifest_findings(root, version),
        lambda: readme_findings(root, name, version),
    ):
        found_errors, found_evidence = check()
        errors += found_errors
        evidence += found_evidence
    for line in evidence:
        print(f"gate evidence: {line}")
    for line in errors:
        print(f"self-description mismatch: {line}", file=sys.stderr)
    print(f"self-description: {'FAIL' if errors else 'OK'} ({len(errors)} mismatch(es))")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
