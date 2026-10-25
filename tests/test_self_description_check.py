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


@pytest.mark.parametrize(
    "setup_py",
    [
        'black_config(target_version="py39")\nsetup(name="pkg", version="1.0.0")\n',
        'meta = dict(name="Someone")\nsetup(name="pkg", version="1.0.0")\n',
        'import setuptools\nsetuptools.setup(version="1.0.0", name="pkg")\n',
    ],
)
def test_setup_py_reads_only_the_setup_call(tmp_path, setup_py):
    write(tmp_path, "setup.py", setup_py)
    assert sdc.package_source(tmp_path) == ("pkg", "1.0.0", "setup.py")


def test_readme_pin_needs_a_left_boundary(repo):
    write(repo, "README.md", "npm i other-tool@9.9.9\nnpm i @org/tool-extra@9.9.9\n")
    assert sdc.main([str(repo)]) == 0


@pytest.mark.parametrize(
    "rel, content",
    [
        ("server.json", "{not json"),
        ("server.json", "[]"),
        ("package.json", "{not json"),
    ],
)
def test_unparseable_files_are_mismatches_not_tracebacks(repo, capsys, rel, content):
    write(repo, rel, content)
    assert sdc.main([str(repo)]) == 1
    err = capsys.readouterr().err
    assert "unparseable" in err or "expected a JSON object" in err


def test_server_packages_without_version_are_skipped(repo):
    write(repo, "server.json", {"version": "1.2.3", "packages": [{"registryType": "oci", "identifier": "x"}]})
    assert sdc.main([str(repo)]) == 0


def test_root_manifest_only_checked_when_mcpb(repo, capsys):
    write(repo, "manifest.json", {"manifest_version": 3, "version": "0.0.1", "name": "browser ext"})
    assert sdc.main([str(repo)]) == 0
    write(repo, "manifest.json", {"dxt_version": "0.1", "version": "0.0.1"})
    assert sdc.main([str(repo)]) == 1
    assert "manifest.json version is 0.0.1" in capsys.readouterr().err


@pytest.mark.parametrize(
    "heading",
    ["### [1.2.3](https://example.test) (2026-10-25)", "## Version 1.2.3", "## @org/tool@1.2.3", "## v1.2.3"],
)
def test_changelog_heading_styles(repo, heading):
    write(repo, "CHANGELOG.md", f"# Changelog\n\n## Unreleased\n\n{heading}\n")
    assert sdc.main([str(repo)]) == 0


def test_changelog_ignores_fenced_headings_and_flags_misplaced_unreleased(repo, capsys):
    write(repo, "CHANGELOG.md", "## [1.2.3]\n\n```\n## Unreleased\n```\n")
    assert sdc.main([str(repo)]) == 0
    write(repo, "CHANGELOG.md", "## [1.2.3]\n\n## Unreleased\n")
    assert sdc.main([str(repo)]) == 1
    assert "sits below a release" in capsys.readouterr().err


def test_build_metadata_version_matches_its_heading(tmp_path):
    write(tmp_path, "package.json", {"name": "tool", "version": "1.2.3+abc"})
    write(tmp_path, "CHANGELOG.md", "## [1.2.3+abc]\n")
    assert sdc.main([str(tmp_path)]) == 0


def test_bin_exemption_is_npx_only_and_string_bins_count(tmp_path, capsys):
    write(tmp_path, "package.json", {"name": "@org/tool", "version": "1.0.0", "bin": "cli.js"})
    write(tmp_path, "README.md", "npx tool --help\n")
    assert sdc.main([str(tmp_path)]) == 0
    write(tmp_path, "README.md", "npm install tool\n")
    assert sdc.main([str(tmp_path)]) == 1
    assert "README.md installs 'tool'" in capsys.readouterr().err


def test_install_forms_and_name_normalization(tmp_path, capsys):
    write(tmp_path, "pyproject.toml", '[project]\nname = "my_tool"\nversion = "1.0.0"\n')
    write(tmp_path, "README.md", "pip install My-Tool\nuv tool install my.tool\n")
    assert sdc.main([str(tmp_path)]) == 0
    write(tmp_path, "README.md", "pipx install other/my-tool\n")
    assert sdc.main([str(tmp_path)]) == 1


def test_duplicate_mismatches_are_reported_once(tmp_path, capsys):
    write(tmp_path, "package.json", {"name": "@org/tool", "version": "1.0.0"})
    write(tmp_path, "README.md", "npm install tool\nnpm install tool\n")
    assert sdc.main([str(tmp_path)]) == 1
    assert capsys.readouterr().err.count("README.md installs 'tool'") == 1
