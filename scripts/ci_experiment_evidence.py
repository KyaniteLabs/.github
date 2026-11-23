"""Read bounded, local CI evidence without executing project commands."""

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path


class EvidenceError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(value, length=64):
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value):
        raise EvidenceError(f"expected a {length}-character lowercase hexadecimal identity")
    return value


def number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError("timings and policy thresholds must be finite numbers")
    if value < 0 or value > 1e12 or not math.isfinite(value) or (positive and value < 1e-9):
        raise EvidenceError("timings and policy thresholds must be finite and nonnegative")
    return value


def read_bytes(root, name, limit=4_000_000):
    root = root.resolve()
    if not isinstance(name, str) or not 0 < len(name) <= 300 or Path(name).is_absolute():
        raise EvidenceError("evidence paths must be relative to the manifest directory")
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise EvidenceError("evidence paths must remain inside the manifest directory")
    try:
        if not path.is_file():
            raise EvidenceError("evidence must be an available regular file")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as error:
        raise EvidenceError("evidence file unavailable; retain it beside the manifest") from error
    if len(data) > limit:
        raise EvidenceError("evidence file exceeds its size limit")
    return data


def read_json(root, name):
    data = read_bytes(root, name)
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise EvidenceError("evidence must contain valid JSON") from error
    if not isinstance(value, dict):
        raise EvidenceError("evidence must be a JSON object")
    return value, digest(data)


def junit_fingerprint(root, names):
    if not isinstance(names, list) or not 0 < len(names) <= 32 or not all(isinstance(n, dict) for n in names):
        raise EvidenceError("declare a nonempty list of distinct JUnit reports")
    paths = [n["path"] for n in names]
    if len(paths) != len(set(paths)):
        raise EvidenceError("declare each JUnit report once")
    outcomes, refs, failed = [], [], False
    for spec in names:
        name = spec["path"]
        raw = read_bytes(root, name, 16_000_000)
        if digest(raw) != identity(spec["sha256"]):
            raise EvidenceError("JUnit bytes do not match the declared digest")
        if b"<!doctype" in raw.lower() or b"<!entity" in raw.lower():
            raise EvidenceError("JUnit DTDs and entity declarations are unsupported")
        try:
            cases = list(ET.fromstring(raw).iter("testcase"))
        except ET.ParseError as error:
            raise EvidenceError("JUnit report is malformed") from error
        if not cases or len(cases) > 200_000:
            raise EvidenceError("JUnit report must contain a bounded nonempty suite")
        for case in cases:
            if not case.get("name") or not (case.get("file") or case.get("classname")):
                raise EvidenceError("JUnit cases require a name and file or classname")
            failed |= case.find("failure") is not None or case.find("error") is not None
            outcomes.append((case.get("file", ""), case.get("classname", ""),
                             case.get("name"), case.find("skipped") is not None))
        refs.append({"path": name, "sha256": digest(raw)})
    if all(row[-1] for row in outcomes):
        raise EvidenceError("JUnit evidence contains no executed tests")
    fingerprint = digest(json.dumps(sorted(outcomes), separators=(",", ":")).encode())
    return {"count": len(outcomes), "outcome_sha256": fingerprint, "failed": failed}, refs


def test_evidence(root, spec, source):
    if not isinstance(spec, dict):
        raise EvidenceError("declare test evidence as an object")
    if "junit" in spec and "summary" in spec:
        raise EvidenceError("choose JUnit reports or a retained fingerprint summary")
    if "junit" in spec:
        return junit_fingerprint(root, spec["junit"])
    data, sha = read_json(root, spec["summary"])
    if sha != identity(spec["sha256"]):
        raise EvidenceError("test summary bytes do not match the declared digest")
    if data.get("source_sha") != source:
        raise EvidenceError("test summary source does not match the sample")
    count = data.get("case_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise EvidenceError("test summary must identify a nonempty suite")
    failed = data.get("failed_cases", 0)
    if type(failed) is not int or not 0 <= failed <= count:
        raise EvidenceError("test summary failure count is invalid")
    return {"count": count, "outcome_sha256": identity(data.get("case_outcome_sha256")),
            "failed": failed > 0}, [{"path": spec["summary"], "sha256": sha}]


def execution(data, kind):
    if kind == "ci-profile-v1":
        if data.get("version") != 1:
            raise EvidenceError("expected an existing version 1 CI profile receipt")
        steps = data.get("steps") or []
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            raise EvidenceError("profile steps must be objects")
        phases = {step.get("phase") for step in steps}
        known = bool(steps) and {"install", "verify", "build", "test", "acceptance"} <= phases
        known &= all(type(step.get("exit_code")) is int for step in steps)
        failed = any(type(step.get("exit_code")) is int and step["exit_code"] != 0 for step in steps)
        elapsed = number(data.get("elapsed_seconds"), positive=True)
        return {"source_sha": data.get("source_sha"), "elapsed_seconds": elapsed,
                "aggregate_job_seconds": elapsed, "gates": sorted(phases),
                "known": known, "failed": failed, "status": data.get("status"),
                "observed_counts": None,
                "timing_breakdown": {"queue_seconds": number(data["queue_seconds"]) if data.get("queue_seconds") is not None else None, "phase_seconds": {
                    phase: sum(number(s.get("elapsed_seconds")) for s in steps if s.get("phase") == phase)
                    for phase in sorted(phases)}}}
    if kind != "forgejo-logged-workflow-v1":
        raise EvidenceError("unsupported receipt format")
    jobs = data.get("jobs") or []
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        raise EvidenceError("workflow jobs must be objects")
    gates = [job.get("job") for job in jobs]
    if not all(isinstance(name, str) and name for name in gates) or len(gates) != len(set(gates)):
        raise EvidenceError("workflow jobs need distinct nonempty names")
    # Retained Forgejo log adapter: status 1 is a successful job. No exit is inferred.
    known = bool(jobs) and all(type(job.get("status")) is int and job["status"] == 1 for job in jobs)
    spans = [number(job.get("span_s")) for job in jobs]
    aggregate = number(data.get("aggregate_logged_job_span_s"), positive=True)
    if not math.isclose(sum(spans), aggregate, abs_tol=0.02):
        raise EvidenceError("aggregate logged time does not match its job spans")
    counts = [job for job in jobs if "passed" in job]
    for job in counts:
        if any(type(job.get(key)) is not int or job[key] < 0 for key in ("passed", "skipped")):
            raise EvidenceError("reported test counts must be nonnegative integers")
    return {"source_sha": data.get("commit"),
            "elapsed_seconds": number(data.get("elapsed_s"), positive=True),
            "aggregate_job_seconds": aggregate, "gates": sorted(gates),
            "known": known, "failed": data.get("status") == "failure",
            "status": data.get("status"),
            "timing_breakdown": {"queue_seconds": number(data["queue_seconds"]) if data.get("queue_seconds") is not None else None,
                                 "aggregate_before_pytest_seconds": sum(number(j["before_pytest_s"]) for j in jobs if "before_pytest_s" in j) if any("before_pytest_s" in j for j in jobs) else None,
                                 "aggregate_pytest_seconds": sum(number(j["pytest_s"]) for j in jobs if "pytest_s" in j) if any("pytest_s" in j for j in jobs) else None},
            "observed_counts": [sum(j["passed"] for j in counts), sum(j["skipped"] for j in counts)]}
