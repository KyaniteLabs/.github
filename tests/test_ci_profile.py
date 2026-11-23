import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "actions/ci-profile/run.py"
SPEC = importlib.util.spec_from_file_location("ci_profile", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ContractTests(unittest.TestCase):
    def fixture(self, root, failing_phase=None):
        subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=10)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=CI fixture", "-c",
                        "user.email=ci@example.invalid", "commit", "--allow-empty", "-qm", "fixture"],
                       check=True, timeout=10)
        (root / "test_example.py").write_text("def test_example(): assert True\n")
        profile = {"version": 1, "test_globs": ["test_*.py"], "steps": [
            {"name": phase, "phase": phase, "argv": [sys.executable, "-c",
             "raise SystemExit(7)" if phase == failing_phase else "pass"]}
            for phase in ["install", "verify", "build", "test", "acceptance"]
        ]}
        (root / "profile.json").write_text(json.dumps(profile))
        return profile

    def invoke(self, root):
        return subprocess.run([sys.executable, str(RUNNER), "profile.json"], cwd=root, check=False,
                              capture_output=True, text=True, timeout=15)

    def test_success_retains_source_and_phase_timings_without_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            result = self.invoke(root)
            receipt = json.loads((root / ".ci-results/ci-profile.json").read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(receipt["status"], "success")
        self.assertEqual(len(receipt["source_sha"]), 40)
        self.assertEqual(len(receipt["steps"]), 5)
        self.assertNotIn("environment", receipt)

    def test_every_required_phase_propagates_failure_and_stops(self):
        for phase in ["install", "verify", "build", "test", "acceptance"]:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                self.fixture(root, phase)
                result = self.invoke(root)
                receipt = json.loads((root / ".ci-results/ci-profile.json").read_text())
                self.assertEqual(result.returncode, 7)
                self.assertEqual(receipt["status"], "failure")
                self.assertEqual(receipt["steps"][-1]["phase"], phase)

    def test_missing_phase_and_empty_inventory_fail(self):
        for mutation in [lambda p: p["steps"].pop(), lambda p: p.update(test_globs=["missing/*.py"])]:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                profile = self.fixture(root)
                mutation(profile)
                (root / "profile.json").write_text(json.dumps(profile))
                self.assertNotEqual(self.invoke(root).returncode, 0)

    def test_reports_reject_missing_empty_skipped_failed_and_malformed(self):
        for xml in [None, "<testsuite/>", "<testsuite><testcase><skipped/></testcase></testsuite>",
                    "<testsuite><testcase><failure/></testcase></testsuite>", "broken"]:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                profile = self.fixture(root)
                profile["junit_reports"] = ["report.xml"]
                if xml is not None:
                    (root / "report.xml").write_text(xml)
                (root / "profile.json").write_text(json.dumps(profile))
                self.assertNotEqual(self.invoke(root).returncode, 0)

    def test_report_accepts_executed_test(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "report.xml").write_text("<testsuite><testcase time='1.5'/></testsuite>")
            MODULE.check_reports(root, ["report.xml"])

    def test_timeout_fails_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            profile = self.fixture(root)
            profile["steps"][0].update(argv=[sys.executable, "-c", "import time; time.sleep(5)"], timeout_seconds=1)
            (root / "profile.json").write_text(json.dumps(profile))
            self.assertEqual(self.invoke(root).returncode, 124)
            receipt = json.loads((root / ".ci-results/ci-profile.json").read_text())
            self.assertEqual(receipt["status"], "failure")

    def test_paths_cannot_escape_checkout(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            MODULE.checked_path(Path(temp).resolve(), "../outside.json")
