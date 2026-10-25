"""Layer 5 self-description check: a repository must describe itself consistently.

Offline and stdlib-only, so it runs inside any CI job. The package manifest
(package.json, pyproject.toml [project], or the setup() call in setup.py) is
the source of truth for the name and version. Everything else the repository
ships about itself must agree with it:

  * CHANGELOG.md: the newest released entry equals the package version, and
    at most one "Unreleased" section exists, above every release;
  * MCP server.json (version and each package version);
  * MCPB, plugin and extension manifests that declare a version;
  * README pins written as <name>@<version>;
  * README install commands, which must not name a near-miss of the package
    (running a declared bin, as in `npx <bin>` after install, is allowed).

Exit codes: 0 consistent, 1 mismatch (including unparseable files), 2 not
applicable (no supported version source; do not adopt the check until the
repository has one). Evidence lines name every source compared, so a pass is
visible in CI logs.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?(?![\w.])"
# Manifests whose top-level "version" describes this package. A root
# manifest.json is checked only when it is an MCPB/DXT manifest; browser
# extensions and web app manifests version themselves independently.
VERSIONED_MANIFESTS = (
    "mcpb/manifest.json",
    "gemini-extension.json",
    ".claude-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
)
INSTALL = re.compile(
    r"(npm\s+(?:i|install|add)|pnpm\s+(?:add|install|i)|yarn\s+add|bun\s+add|pip3?\s+install|pipx\s+install|"
    r"uv\s+(?:tool\s+install|add|pip\s+install)|npx|uvx)"
    r"((?:[ \t]+-{1,2}[\w-]+)*)[ \t]+(@?[\w./-]+)"
)


# "[Unreleased]" with anything after it, or a bare "Unreleased" alone or before a dash;
# "Unreleased fixes" is an ordinary subsection title.
UNRELEASED = re.compile(r"\[unreleased\]|unreleased\s*(?:$|[—–-])", re.I)


class Unparseable(Exception):
    """A file exists but cannot be read as the expected structure."""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Unparseable(f"{path.name}: unreadable ({exc.__class__.__name__})") from None


def load_json(path: Path) -> dict:
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise Unparseable(f"{path.name}: unparseable ({exc.__class__.__name__})") from None
    if not isinstance(data, dict):
        raise Unparseable(f"{path.name}: expected a JSON object, got {type(data).__name__}")
    return data


def setup_call_keywords(text: str) -> dict[str, str]:
    """String keywords of the setup(...) call, ignoring every other call."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise Unparseable("setup.py: unparseable (SyntaxError)") from None
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            is_setup = func.id == "setup"
        else:
            is_setup = isinstance(func, ast.Attribute) and func.attr == "setup" and ast.unparse(func.value) in {
                "setuptools",
                "distutils.core",
            }
        keywords = {
            kw.arg: kw.value.value
            for kw in node.keywords
            if kw.arg and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)
        }
        if is_setup and "version" in keywords:
            found = keywords
    return found


def package_source(root: Path) -> tuple[str, str, str] | None:
    """Return (name, version, source) from the first manifest that declares a version."""
    pkg = root / "package.json"
    if pkg.is_file():
        data = load_json(pkg)
        if isinstance(data.get("version"), str):
            return str(data.get("name") or ""), data["version"], "package.json"
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        import tomllib  # Python 3.11+; imported here so npm-only repos run on older Pythons.

        try:
            project = tomllib.loads(read_text(pyproject)).get("project", {})
        except tomllib.TOMLDecodeError:
            raise Unparseable("pyproject.toml: unparseable (TOMLDecodeError)") from None
        if not isinstance(project, dict):
            raise Unparseable("pyproject.toml: [project] is not a table")
        if isinstance(project.get("version"), str):
            return str(project.get("name") or ""), project["version"], "pyproject.toml"
    setup = root / "setup.py"
    if setup.is_file():
        keywords = setup_call_keywords(read_text(setup))
        if "version" in keywords:
            return keywords.get("name", ""), keywords["version"], "setup.py"
    return None


def package_bins(root: Path, name: str) -> set[str]:
    """Executable names the package declares; `npx <bin>` after install is valid."""
    pkg = root / "package.json"
    if not pkg.is_file():
        return set()
    bins = load_json(pkg).get("bin")
    if isinstance(bins, dict):
        return set(bins)
    if isinstance(bins, str):
        return {name.rsplit("/", 1)[-1]}
    return set()


def strip_fences(text: str) -> str:
    """Drop fenced blocks; a fence closes only on the same character, at least as long."""
    kept, fence = [], None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence is None and marker:
            fence = marker.group(1)
        elif fence is not None and marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
            fence = None
        elif fence is None:
            kept.append(line)
    return "\n".join(kept)


def changelog_findings(root: Path, name: str, version: str) -> tuple[list[str], list[str]]:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return [], ["CHANGELOG.md: absent (skipped)"]
    headings = re.findall(r"^(#{2,3})\s+(.*)$", strip_fences(read_text(path)), re.M)
    prefix = rf"(?:version\s+|{re.escape(name)}@)?" if name else r"(?:version\s+)?"
    releases = [(len(h), m.group(1)) for h, text in headings if (m := re.match(rf"\[?{prefix}v?({SEMVER})\]?", text, re.I))]
    level = releases[0][0] if releases else 2
    entries = []
    for hashes, heading in headings:
        if len(hashes) == level and UNRELEASED.match(heading):
            entries.append(("unreleased", None))
        elif len(hashes) == level and (match := re.match(rf"\[?{prefix}v?({SEMVER})\]?", heading, re.I)):
            entries.append(("release", match.group(1)))
    unreleased = [i for i, (kind, _) in enumerate(entries) if kind == "unreleased"]
    released = [v for kind, v in entries if kind == "release"]
    errors = []
    if len(unreleased) > 1:
        errors.append(f"CHANGELOG.md: {len(unreleased)} 'Unreleased' sections; keep exactly one, above every release")
    elif unreleased and unreleased[0] != 0:
        errors.append("CHANGELOG.md: the 'Unreleased' section sits below a release; move it to the top")
    if not released:
        errors.append("CHANGELOG.md: no released version heading")
    elif released[0] != version:
        errors.append(f"CHANGELOG.md: newest released entry is {released[0]}, package is {version}")
    return errors, [f"CHANGELOG.md: newest released entry {released[0] if released else '-'}"]


def manifest_findings(root: Path, version: str) -> tuple[list[str], list[str]]:
    errors, evidence = [], []
    server = root / "server.json"
    if server.is_file():
        data = load_json(server)
        found = [("server.json version", data.get("version"))]
        packages = data.get("packages") if isinstance(data.get("packages"), list) else []
        found += [
            (f"server.json packages[{i}].version", p["version"])
            for i, p in enumerate(packages)
            if isinstance(p, dict) and "version" in p
        ]
        for label, value in found:
            evidence.append(f"{label}: {value}")
            if value != version:
                errors.append(f"{label} is {value}, package is {version}")
    candidates = list(VERSIONED_MANIFESTS)
    root_manifest = root / "manifest.json"
    if root_manifest.is_file():
        data = load_json(root_manifest)
        if "dxt_version" in data or ("manifest_version" in data and "server" in data):
            candidates.append("manifest.json")
    for rel in candidates:
        path = root / rel
        if not path.is_file():
            continue
        value = load_json(path).get("version")
        if value is None:
            continue
        evidence.append(f"{rel} version: {value}")
        if value != version:
            errors.append(f"{rel} version is {value}, package is {version}")
    return errors, evidence


def normalized(name: str) -> str:
    """Compare names the way registries do (PEP 503 style; npm names are lowercase)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def readme_findings(root: Path, name: str, version: str) -> tuple[list[str], list[str]]:
    path = root / "README.md"
    if not path.is_file() or not name:
        return [], ["README.md: skipped (absent or unnamed package)"]
    text = read_text(path)
    errors = []
    pins = set(re.findall(rf"(?<![\w@/.-]){re.escape(name)}@({SEMVER})", text))
    for pin in sorted(pins - {version}):
        errors.append(f"README.md pins {name}@{pin}, package is {version}")
    base = normalized(name.rsplit("/", 1)[-1])
    bins = package_bins(root, name)
    commands = INSTALL.findall(text)
    for command, _flags, target in commands:
        bare = re.sub(rf"(?<=.)@{SEMVER}$", "", target)
        runs_bin = command.startswith(("npx", "uvx")) and bare in bins
        if normalized(bare) != normalized(name) and not runs_bin and normalized(bare.rsplit("/", 1)[-1]) == base:
            errors.append(f"README.md installs '{bare}', package is '{name}'")
    return errors, [f"README.md: {len(pins)} version pin(s), {len(commands)} install/run command(s)"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=".", help="repository root (default: .)")
    root = Path(parser.parse_args(argv).root)
    try:
        source = package_source(root)
    except Unparseable as exc:
        print(f"self-description mismatch: {exc}", file=sys.stderr)
        print("self-description: FAIL (1 mismatch(es))")
        return 1
    if source is None:
        print("self-description: not applicable (no version in package.json, pyproject.toml [project] or setup())")
        return 2
    name, version, origin = source
    errors, evidence = [], [f"source of truth: {origin} -> {name or '(unnamed)'} {version}"]
    checks = (
        lambda: changelog_findings(root, name, version),
        lambda: manifest_findings(root, version),
        lambda: readme_findings(root, name, version),
    )
    for check in checks:
        try:
            found_errors, found_evidence = check()
        except Unparseable as exc:
            found_errors, found_evidence = [str(exc)], []
        errors += found_errors
        evidence += found_evidence
    errors = list(dict.fromkeys(errors))
    for line in evidence:
        print(f"gate evidence: {line}")
    for line in errors:
        print(f"self-description mismatch: {line}", file=sys.stderr)
    print(f"self-description: {'FAIL' if errors else 'OK'} ({len(errors)} mismatch(es))")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
