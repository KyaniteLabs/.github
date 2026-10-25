import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("sdc", ROOT / "scripts/self_description_check.py")
sdc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdc)


def write(root: Path, rel: str, content) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content) if not isinstance(content, str) else content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    write(tmp_path, "package.json", {"name": "@org/tool", "version": "1.2.3", "bin": {"tool": "bin/tool.js"}})
    write(tmp_path, "CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-10-25\n\n## [1.2.2]\n")
    write(tmp_path, "README.md", "# Tool\n\n```\nnpm install @org/tool\nnpx tool --help\nnpx @org/tool@1.2.3 run\n```\n")
    write(tmp_path, "server.json", {"version": "1.2.3", "packages": [{"version": "1.2.3"}]})
    return tmp_path


def test_consistent_repository_passes(repo, capsys):
    assert sdc.main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "gate evidence: source of truth: package.json -> @org/tool 1.2.3" in out
    assert "self-description: OK" in out


@pytest.mark.parametrize(
    "rel, content, expected",
    [
        ("CHANGELOG.md", "## [Unreleased]\n## [1.2.2]\n", "newest released entry is 1.2.2"),
        ("CHANGELOG.md", "## [Unreleased]\n## Unreleased\n## [1.2.3]\n", "2 'Unreleased' sections"),
        ("CHANGELOG.md", "## Unreleased\n", "no released version heading"),
        ("server.json", {"version": "1.2.3", "packages": [{"version": "0.1.0"}]}, "server.json packages[0].version is 0.1.0"),
        ("mcpb/manifest.json", {"version": "1.0.0"}, "mcpb/manifest.json version is 1.0.0"),
        ("README.md", "npx @org/tool@1.1.0 run\n", "README.md pins @org/tool@1.1.0"),
        ("README.md", "npm install org-tool\nnpm install tool\n", "README.md installs 'tool'"),
    ],
)
def test_each_drift_fails(repo, capsys, rel, content, expected):
    write(repo, rel, content)
    assert sdc.main([str(repo)]) == 1
    assert expected in capsys.readouterr().err


def test_python_sources_are_supported(tmp_path, capsys):
    write(tmp_path, "pyproject.toml", '[project]\nname = "pkg"\nversion = "0.3.0"\n')
    write(tmp_path, "CHANGELOG.md", "## [0.3.1]\n")
    assert sdc.main([str(tmp_path)]) == 1
    assert "newest released entry is 0.3.1, package is 0.3.0" in capsys.readouterr().err
    (tmp_path / "pyproject.toml").unlink()
    write(tmp_path, "setup.py", 'setup(name="pkg", version="0.3.1")\n')
    assert sdc.main([str(tmp_path)]) == 0


def test_missing_version_source_is_distinct(tmp_path):
    assert sdc.main([str(tmp_path)]) == 2
