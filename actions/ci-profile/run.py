"""Run a project's explicit CI contract and retain source-bound phase timings."""

import glob
import hashlib
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REQUIRED_PHASES = {"install", "verify", "build", "test", "acceptance"}
MAX_TIMEOUT_SECONDS = 3600


def checked_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("CI paths must remain inside the checkout")
    return path


def load_profile(root, filename):
    profile = json.loads(checked_path(root, filename).read_text())
    steps = profile.get("steps", [])
    if profile.get("version") != 1 or not steps:
        raise ValueError("expected a version 1 profile with explicit steps")
    if not REQUIRED_PHASES.issubset({step.get("phase") for step in steps}):
        raise ValueError("profile must install, verify, build, test, and accept the artifact")
    for step in steps:
        argv = step.get("argv")
        timeout = step.get("timeout_seconds", 600)
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg for arg in argv):
            raise ValueError("commands must be nonempty argument arrays")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
            raise ValueError("step timeout must be between 1 and 3600 seconds")
    patterns = profile.get("test_globs", [])
    if not patterns or not any(glob.glob(str(checked_path(root, pattern)), recursive=True) for pattern in patterns):
        raise ValueError("test inventory is empty; no successful empty suites")
    return profile


def check_reports(root, patterns):
    for pattern in patterns:
        paths = glob.glob(str(checked_path(root, pattern)), recursive=True)
        if not paths:
            raise ValueError("required JUnit report is missing")
        for path in paths:
            cases = list(ET.parse(checked_path(root, path)).getroot().iter("testcase"))
            if not cases or all(case.find("skipped") is not None for case in cases):
                raise ValueError("JUnit report contains no executed tests")
            if any(case.find("failure") is not None or case.find("error") is not None for case in cases):
                raise ValueError("JUnit report contains failed tests")


def run(root, filename):
    receipt = {"version": 1, "status": "failure", "steps": []}
    started = time.monotonic()
    try:
        profile = load_profile(root, filename)
        receipt["profile_sha256"] = hashlib.sha256(checked_path(root, filename).read_bytes()).hexdigest()
        receipt["source_sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=10,
        ).strip()
        receipt["dependency_sha256"] = {
            name: hashlib.sha256(checked_path(root, name).read_bytes()).hexdigest()
            for name in profile.get("dependency_files", [])
        }
        for step in profile["steps"]:
            phase_start = time.monotonic()
            print("CI phase: " + step["name"], flush=True)
            try:
                result = subprocess.run(
                    step["argv"], cwd=root, timeout=step.get("timeout_seconds", 600), check=False,
                ).returncode
            except subprocess.TimeoutExpired:
                result = 124
            record = {"name": step["name"], "phase": step["phase"], "exit_code": result,
                      "elapsed_seconds": round(time.monotonic() - phase_start, 3)}
            receipt["steps"].append(record)
            print("CI_PHASE " + json.dumps(record, sort_keys=True), flush=True)
            if result:
                return result if result > 0 else 1
        check_reports(root, profile.get("junit_reports", []))
        receipt["status"] = "success"
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, ET.ParseError) as error:
        print("CI contract failed: " + str(error), file=sys.stderr, flush=True)
        return 1
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        # Record identities and timing only: never serialize environment variables.
        destination = checked_path(root, ".ci-results/ci-profile.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(receipt, indent=2) + "\n")
        print("CI_RECEIPT " + json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == "__main__":
    raise SystemExit(run(Path.cwd().resolve(), sys.argv[1]))
