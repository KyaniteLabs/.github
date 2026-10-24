import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ci_experiment as experiment  # noqa: E402
from ci_experiment_evidence import EvidenceError  # noqa: E402


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {"version": 1, "design": "prospective", "objective": "reduce CI job latency",
                         "policy": {"minimum_samples": 2, "min_elapsed_reduction_percent": 5,
                                    "max_aggregate_job_increase_percent": 0,
                                    "allowed_input_changes": ["workflow_sha256"]},
                         "baseline": [], "candidate": []}
        for side, times in [("baseline", [100, 102]), ("candidate", [85, 86])]:
            for index, elapsed in enumerate(times):
                source = ("a" if side == "baseline" else "b") * 40
                prefix = f"{side}-{index}"
                data = {"version": 1, "source_sha": source, "status": "success",
                        "elapsed_seconds": elapsed, "dependency_sha256": {"lock": "d" * 64},
                        "steps": [{"phase": p, "exit_code": 0, "elapsed_seconds": elapsed / 5}
                                  for p in ["install", "verify", "build", "test", "acceptance"]]}
                sha = self.write(prefix + ".json", data)
                xml = '<testsuite><testcase file="test_a.py" classname="A" name="one"/></testsuite>'
                (self.root / (prefix + ".xml")).write_text(xml)
                self.manifest[side].append({
                    "run_id": prefix, "receipt": prefix + ".json", "receipt_sha256": sha,
                    "source_sha": source, "format": "ci-profile-v1", "context": "ci-job",
                    "trigger": "pull_request", "gates": [s["phase"] for s in data["steps"]],
                    "workflow_sha256": ("c" if side == "baseline" else "e") * 64,
                    "workload_sha256": "f" * 64, "test_scope": "all package tests",
                    "images": {"runtime": "python:fixture@sha256:" + "9" * 64},
                    "dependencies": {"lock": "d" * 64}, "cache_condition": "cold",
                    "tests": {"junit": [{"path": prefix + ".xml",
                                          "sha256": hashlib.sha256(xml.encode()).hexdigest()}]}})

    def write(self, name, value):
        raw = json.dumps(value, sort_keys=True).encode()
        (self.root / name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def mutate_receipt(self, spec, change):
        data = json.loads((self.root / spec["receipt"]).read_text())
        change(data)
        spec["receipt_sha256"] = self.write(spec["receipt"], data)

    def compare(self):
        return experiment.compare(self.root, self.manifest, "0" * 64)

    def invoke(self, *args):
        self.write("manifest.json", self.manifest)
        return subprocess.run([sys.executable, str(SCRIPTS / "ci_experiment.py"),
                               str(self.root / "manifest.json"), *args],
                              text=True, capture_output=True, timeout=10)

    def test_repeated_equivalent_samples_meet_policy_with_explicit_limits(self):
        result = self.compare()
        self.assertEqual(result["decision"], "meets_policy")
        self.assertEqual(result["baseline"]["samples"], 2)
        self.assertEqual(result["candidate"]["elapsed_seconds"]["median"], 85.5)
        self.assertEqual(result["tests"]["count"], 1)
        self.assertTrue(any("not measured CPU" in s for s in result["limitations"]))
        self.assertIsNone(result["evidence"]["baseline"][0]["timing_breakdown"]["queue_seconds"])

    def test_single_pair_cannot_qualify_a_positive_result(self):
        for side in ("baseline", "candidate"):
            self.manifest[side] = self.manifest[side][:1]
        result = self.compare()
        self.assertEqual(result["decision"], "insufficient_evidence")
        self.assertIn("more independent", result["reasons"][0])

    def test_trigger_workload_context_and_gate_scopes_are_not_interchangeable(self):
        for key, value in [("trigger", "push"), ("workload_sha256", "1" * 64),
                           ("context", "local"), ("test_scope", "only smoke")]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.manifest)
                changed["candidate"][0][key] = value
                result = experiment.compare(self.root, changed, "0" * 64)
                self.assertEqual(result["decision"], "incomparable")
        self.manifest["candidate"][0]["gates"].remove("test")
        with self.assertRaisesRegex(EvidenceError, "gates"):
            self.compare()

    def test_equal_counts_with_different_case_identity_or_outcome_are_incomparable(self):
        spec = self.manifest["candidate"][0]
        path = self.root / spec["tests"]["junit"][0]["path"]
        for xml in ['<testsuite><testcase file="test_a.py" name="other"/></testsuite>',
                    '<testsuite><testcase file="test_a.py" name="one"><failure/></testcase></testsuite>']:
            with self.subTest(xml=xml):
                path.write_text(xml)
                spec["tests"]["junit"][0]["sha256"] = hashlib.sha256(xml.encode()).hexdigest()
                self.assertEqual(self.compare()["decision"], "incomparable")

    def test_missing_exit_remains_unknown_despite_success_status(self):
        self.mutate_receipt(self.manifest["candidate"][0], lambda d: d["steps"][0].pop("exit_code"))
        result = self.compare()
        self.assertEqual(result["decision"], "insufficient_evidence")
        self.assertIn("outcome missing", result["reasons"][0])

    def test_execution_failure_rejects_even_with_green_test_report(self):
        self.mutate_receipt(self.manifest["candidate"][0], lambda d: d["steps"][0].update(exit_code=7))
        self.assertEqual(self.compare()["decision"], "reject")

    def test_declared_changes_and_cache_variation_are_visible(self):
        for key, value in [("images", {"runtime": "different"}), ("cache_condition", "warm")]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.manifest)
                changed["candidate"][0][key] = value
                self.assertEqual(experiment.compare(self.root, changed, "0" * 64)["decision"], "incomparable")

    def test_duplicates_tampering_and_source_drift_cannot_inflate_confidence(self):
        spec = self.manifest["candidate"][0]
        for key, value in [("receipt_sha256", "0" * 64), ("source_sha", "0" * 40),
                           ("dependencies", {"lock": "0" * 64}), ("run_id", "baseline-0")]:
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                changed = copy.deepcopy(self.manifest)
                changed["candidate"][0][key] = value
                experiment.compare(self.root, changed, "0" * 64)
        self.manifest["candidate"][1] = copy.deepcopy(spec)
        with self.assertRaisesRegex(EvidenceError, "duplicate"):
            self.compare()

    def test_missing_malformed_and_escaping_evidence_report_unknown_without_traceback(self):
        spec = self.manifest["candidate"][0]
        for value in ["absent.json", "../outside.json", "/outside.json"]:
            with self.subTest(value=value):
                spec["receipt"] = value
                result = self.invoke("--json")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)["decision"], "insufficient_evidence")
                self.assertNotIn("Traceback", result.stderr)

    def test_nonfinite_policy_and_corrupt_junit_are_not_accepted(self):
        self.manifest["policy"]["min_elapsed_reduction_percent"] = float("nan")
        self.assertEqual(self.invoke().returncode, 2)
        self.manifest["policy"]["min_elapsed_reduction_percent"] = 5
        spec = self.manifest["candidate"][0]
        for xml in ["broken", "<testsuite/>", '<!DOCTYPE x><testsuite/>',
                    '<testsuite><testcase name="one"><skipped/></testcase></testsuite>']:
            with self.subTest(xml=xml):
                (self.root / spec["tests"]["junit"][0]["path"]).write_text(xml)
                spec["tests"]["junit"][0]["sha256"] = hashlib.sha256(xml.encode()).hexdigest()
                self.assertEqual(self.invoke().returncode, 2)

    def test_cli_is_bounded_and_preserves_existing_output(self):
        result = self.invoke("--output", str(self.root / "comparison.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(len(result.stdout), 1500)
        self.assertNotIn(str(self.root), result.stdout)
        retained = (self.root / "comparison.json").read_bytes()
        self.assertEqual(self.invoke("--output", str(self.root / "comparison.json")).returncode, 2)
        self.assertEqual((self.root / "comparison.json").read_bytes(), retained)
        self.assertEqual(self.invoke("--output", str(self.root / "manifest.json")).returncode, 2)

    def test_retrospective_design_is_not_preregistered(self):
        self.manifest["design"] = "retrospective"
        self.assertTrue(any("not a preregistered" in s for s in self.compare()["limitations"]))

    def test_trigger_equivalence_requires_reason_and_matching_actual_gates(self):
        for sample in self.manifest["candidate"]:
            sample["trigger"] = "push"
        self.manifest["policy"]["equivalent_triggers"] = ["push", "pull_request"]
        with self.assertRaisesRegex(EvidenceError, "justification"):
            self.compare()
        self.manifest["policy"]["trigger_equivalence_reason"] = "Fixture executes identical gates and workload."
        self.assertEqual(self.compare()["decision"], "meets_policy")
        self.manifest["candidate"][0]["gates"] = ["test"]
        with self.assertRaisesRegex(EvidenceError, "gates"):
            self.compare()

    def test_malformed_receipt_objects_and_symlink_escapes_are_unknown(self):
        spec = self.manifest["candidate"][0]
        for value in [{"steps": ["invalid"]}, {"version": 1, "steps": None}, {"version": 1}]:
            with self.subTest(value=value):
                spec["receipt_sha256"] = self.write(spec["receipt"], value)
                result = self.invoke("--json")
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "external.json"
            target.write_text("{}")
            (self.root / "linked.json").symlink_to(target)
            spec["receipt"] = "linked.json"
            self.assertEqual(self.invoke().returncode, 2)

    def test_real_existing_profile_receipt_is_consumed_without_a_new_validation_framework(self):
        runner = SCRIPTS.parent / "actions/ci-profile/run.py"
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, timeout=10)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=CI fixture", "-c",
                        "user.email=ci@example.invalid", "commit", "--allow-empty", "-qm", "fixture"],
                       check=True, timeout=10)
        (self.root / "test_real.py").write_text("def test_real(): pass\n")
        profile = {"version": 1, "test_globs": ["test_real.py"], "dependency_files": [],
                   "steps": [{"name": p, "phase": p, "argv": [sys.executable, "-c", "pass"]}
                             for p in ["install", "verify", "build", "test", "acceptance"]]}
        self.write("profile.json", profile)
        run = subprocess.run([sys.executable, str(runner), "profile.json"], cwd=self.root,
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads((self.root / ".ci-results/ci-profile.json").read_text())
        from ci_experiment_evidence import execution
        parsed = execution(data, "ci-profile-v1")
        self.assertTrue(parsed["known"])
        self.assertFalse(parsed["failed"])
        self.assertEqual(parsed["source_sha"], data["source_sha"])

    def test_retained_kinocut_pilot_reproduces_rejection(self):
        path = SCRIPTS.parent / "examples/ci-experiment/kinocut/manifest.json"
        result = subprocess.run([sys.executable, str(SCRIPTS / "ci_experiment.py"), str(path), "--json"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["decision"], "reject")
        self.assertEqual(report["tests"]["count"], 9219)
        self.assertEqual(report["baseline"]["elapsed_seconds"]["median"], 964)
        self.assertEqual(report["candidate"]["elapsed_seconds"]["median"], 944)
        self.assertAlmostEqual(report["observed_change_percent"]["aggregate_job_increase"], 3.5265, places=3)
        self.assertTrue(any("below" in s for s in report["limitations"]))
