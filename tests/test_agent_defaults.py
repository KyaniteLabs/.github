from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


parity = load_script("check_agent_parity", ROOT / "scripts" / "check-agent-parity.py")
provisioner = load_script("provision_agent_law", ROOT / "scripts" / "provision-agent-law.py")


class AgentParityTests(unittest.TestCase):
    def test_strip_agent_specific_removes_markers_and_normalizes(self) -> None:
        content = """---
title: hidden
---
# Rules
<!-- private -->
<agent>ignore</agent>


Keep this.
"""

        self.assertEqual(parity.strip_agent_specific(content), "# Rules\n\nignore\n\nKeep this.")

    def test_extract_sections_keeps_nested_section_names(self) -> None:
        sections = parity.extract_sections("# One\nAlpha\n\n## Two\nBeta")

        self.assertEqual(sections["One"], "Alpha")
        self.assertEqual(sections["Two"], "Beta")

    def test_check_repo_fails_when_agents_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "example"
            repo.mkdir()
            (repo / "CLAUDE.md").write_text("# Organization Principles\n\nUseful over flashy.\n")

            result = parity.check_repo(repo)

        self.assertEqual(result.status, "fail")
        self.assertIn("AGENTS.md file is missing", result.content_differences)


class ProvisionerTests(unittest.TestCase):
    def test_upsert_marker_file_replaces_existing_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AGENTS.md"
            path.write_text(f"# Rules\n\n{provisioner.START}\nold\n{provisioner.END}\n")

            provisioner.upsert_marker_file(path, f"{provisioner.START}\nnew\n{provisioner.END}", "# Rules")

            text = path.read_text()

        self.assertIn("new", text)
        self.assertNotIn("old", text)
        self.assertEqual(text.count(provisioner.START), 1)

    def test_choose_recipe_path_respects_capitalized_docs_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "Docs").mkdir()

            path = provisioner.choose_recipe_path(repo)

        self.assertEqual(path, Path(tmp) / "Docs" / "agent-law" / "empower-orchestrator.md")

    def test_generated_workflow_uses_pinned_checkout_without_credentials(self) -> None:
        text = provisioner.workflow_text()

        self.assertIn("actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5", text)
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("actions/checkout@v4", text)


if __name__ == "__main__":
    unittest.main()
