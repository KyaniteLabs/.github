"""Evidence must reflect only what the run produced, and comparison stays advisory."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ci_evidence", Path(__file__).resolve().parents[1] / "scripts/ci_evidence.py",
)
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)

JUNIT = """<testsuites><testsuite>
<testcase name="a"/><testcase name="b"><failure/></testcase>
<testcase name="c"><skipped/></testcase><testcase name="d"/>
</testsuite></testsuites>"""


def checkout(**files):
    root = Path(tempfile.mkdtemp())
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content)
    return root


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = EVIDENCE.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CollectTests(unittest.TestCase):
    def full_checkout(self):
        receipt = {"status": "success", "source_sha": "a" * 40, "elapsed_seconds": 9.0, "steps": [
            {"phase": "install", "elapsed_seconds": 2.0},
            {"phase": "test", "elapsed_seconds": 3.0},
            {"phase": "test", "elapsed_seconds": 1.5},
        ]}
        return checkout(**{
            ".ci/profile.json": json.dumps({"junit_reports": [".ci-results/tests.xml"]}),
            ".ci-results/ci-profile.json": json.dumps(receipt),
            ".ci-results/tests.xml": JUNIT,
            ".ci-results/dist/pkg-1.2.3.tgz": b"x" * 100,
            ".ci-results/dist/SHA256SUMS": "sums",
            ".ci-results/site.tar": b"y" * 50,
            "coverage/coverage-summary.json": json.dumps({"total": {"lines": {"pct": 81.234}}}),
        })

    def test_collects_status_phases_tests_coverage_and_artifacts(self):
        root = self.full_checkout()
        code, out, _ = run("collect", str(root))
        self.assertEqual(code, 0)
        evidence = json.loads((root / ".ci-results/evidence.json").read_text())
        self.assertEqual(evidence["status"], "success")
        self.assertEqual(evidence["phases"], {"install": 2.0, "test": 4.5})
        self.assertEqual(evidence["tests"], {"total": 4, "failed": 1, "skipped": 1})
        self.assertEqual(evidence["coverage_lines_pct"], 81.23)
        self.assertEqual(evidence["artifacts"], {"pkg.tgz": 100, "site.tar": 50})
        self.assertIn("tests 4, coverage 81.23, 2 artifact(s)", out)

    def test_absent_sources_are_absent_not_zero(self):
        root = checkout()
        self.assertEqual(run("collect", str(root))[0], 0)
        evidence = json.loads((root / ".ci-results/evidence.json").read_text())
        self.assertIsNone(evidence["tests"])
        self.assertIsNone(evidence["coverage_lines_pct"])
        self.assertEqual((evidence["status"], evidence["artifacts"]), ("unknown", {}))

    def test_cobertura_coverage(self):
        root = checkout(**{"coverage.xml": '<coverage line-rate="0.756"/>'})
        self.assertEqual(EVIDENCE.coverage_pct(root), 75.6)

    def test_versions_are_stripped_from_artifact_keys(self):
        self.assertEqual(EVIDENCE.artifact_key("epoch-0.5.2.tgz"), "epoch.tgz")
        self.assertEqual(EVIDENCE.artifact_key("elixis-1.0.0-py3-none-any.whl"), "elixis-py3-none-any.whl")

    def test_broken_junit_fails_collection(self):
        root = checkout(**{".ci/profile.json": json.dumps({"junit_reports": ["t.xml"]}), "t.xml": "<not xml"})
        self.assertEqual(run("collect", str(root))[0], 1)


class CompareTests(unittest.TestCase):
    BASE = {"source_sha": "b" * 40, "tests": {"total": 10}, "coverage_lines_pct": 80.0,
            "phases": {"test": 30.0}, "artifacts": {"pkg.tgz": 1000, "old.tar": 10}}

    def test_deltas_and_regressions(self):
        head = {"tests": {"total": 9}, "coverage_lines_pct": 79.5, "phases": {"test": 31.0, "build": 5.0},
                "artifacts": {"pkg.tgz": 1100, "new.zip": 5}}
        lines = EVIDENCE.compare(self.BASE, head)
        self.assertIn("evidence delta: tests 10 -> 9 (-1)", lines)
        self.assertIn("evidence delta: line coverage 80.0% -> 79.5% (-0.50 pts)", lines)
        self.assertIn("evidence delta: phase build -s -> 5.0s", lines)
        self.assertIn("evidence delta: artifact pkg.tgz 1000 B -> 1.1 KB (+10.0%)", lines)
        self.assertIn("evidence delta: artifact new.zip - -> 5 B (new)", lines)
        self.assertIn("evidence delta: artifact old.tar 10 B -> - (gone)", lines)
        regressions = [line for line in lines if line.startswith("evidence regression:")]
        self.assertEqual(len(regressions), 3)

    def test_small_growth_and_more_tests_are_not_regressions(self):
        head = {"tests": {"total": 12}, "coverage_lines_pct": 80.0, "artifacts": {"pkg.tgz": 1040}}
        self.assertFalse([l for l in EVIDENCE.compare(self.BASE, head) if l.startswith("evidence regression:")])

    def test_compare_is_advisory_even_with_regressions(self):
        root = checkout(**{"base.json": json.dumps(self.BASE), "head.json": json.dumps({"tests": {"total": 1}})})
        code, out, _ = run("compare", str(root / "base.json"), str(root / "head.json"))
        self.assertEqual(code, 0)
        self.assertIn("evidence: comparing against main bbbbbbbbbbbb", out)
        self.assertIn("evidence: 1 advisory regression(s)", out)

    def test_missing_baseline_says_so(self):
        root = checkout(**{"head.json": "{}"})
        code, out, _ = run("compare", str(root / "absent.json"), str(root / "head.json"))
        self.assertEqual(code, 0)
        self.assertIn("no main baseline yet", out)

    def test_unreadable_head_fails(self):
        root = checkout(**{"base.json": "{}"})
        self.assertEqual(run("compare", str(root / "base.json"), str(root / "absent.json"))[0], 1)


if __name__ == "__main__":
    unittest.main()
