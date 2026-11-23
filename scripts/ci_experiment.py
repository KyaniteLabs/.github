"""Compare source-bound CI experiment receipts against a declared policy."""

import argparse
import json
import statistics
import sys
from pathlib import Path

from ci_experiment_evidence import (
    EvidenceError, execution, identity, number, read_json, test_evidence,
)

INPUT_KEYS = {"workflow_sha256", "images", "dependencies", "cache_condition"}
SCOPE_KEYS = ("context", "trigger", "gates", "workload_sha256", "test_scope")
LIMITATIONS = [
    "Observed samples and medians do not establish statistical significance or future latency.",
    "Aggregate logged job time is elapsed execution time, not measured CPU utilization.",
    "Input declarations and retained fingerprints are not independently attested provenance.",
    "Test equivalence covers the declared fingerprint scope, not code coverage or product acceptance.",
]


def policy_from(manifest):
    if manifest.get("version") != 1 or not isinstance(manifest.get("objective"), str) or not 0 < len(manifest["objective"].strip()) <= 500:
        raise EvidenceError("declare a version 1 experiment and its objective")
    if manifest.get("design") not in ("prospective", "retrospective"):
        raise EvidenceError("declare whether the experiment design is prospective or retrospective")
    policy = manifest["policy"]
    permitted = {"min_elapsed_reduction_percent", "max_aggregate_job_increase_percent",
                 "minimum_samples", "allowed_input_changes", "equivalent_triggers",
                 "trigger_equivalence_reason"}
    if not isinstance(policy, dict) or not set(policy) <= permitted:
        raise EvidenceError("policy contains unsupported fields")
    for key in ("min_elapsed_reduction_percent", "max_aggregate_job_increase_percent"):
        number(policy[key])
    if policy["min_elapsed_reduction_percent"] > 100:
        raise EvidenceError("elapsed reduction cannot exceed 100 percent")
    if type(policy["minimum_samples"]) is not int or policy["minimum_samples"] < 2:
        raise EvidenceError("qualification requires at least two samples per side")
    changes = policy["allowed_input_changes"]
    if not isinstance(changes, list) or not set(changes) <= INPUT_KEYS:
        raise EvidenceError("allowed input changes must name supported input dimensions")
    triggers = policy.get("equivalent_triggers", [])
    if triggers:
        reason = policy.get("trigger_equivalence_reason")
        if not isinstance(triggers, list) or len(triggers) < 2 or not all(isinstance(t, str) and t for t in triggers):
            raise EvidenceError("trigger equivalence requires an explicit set of triggers")
        if not isinstance(reason, str) or not 0 < len(reason) <= 500:
            raise EvidenceError("trigger equivalence requires a bounded justification")
    return policy


def sample_from(root, spec):
    source = identity(spec["source_sha"], 40)
    data, receipt_sha = read_json(root, spec["receipt"])
    if receipt_sha != identity(spec["receipt_sha256"]):
        raise EvidenceError("receipt bytes do not match the declared digest")
    result = execution(data, spec["format"])
    if result["source_sha"] != source:
        raise EvidenceError("receipt source does not match the declared source")
    inputs = {key: spec[key] for key in (*SCOPE_KEYS, *sorted(INPUT_KEYS))}
    if inputs["context"] not in ("ci-job", "ci-workflow", "local"):
        raise EvidenceError("context must distinguish CI job, workflow and local execution")
    if spec["format"] == "ci-profile-v1" and inputs["context"] == "ci-workflow":
        raise EvidenceError("a single-job profile cannot measure whole-workflow elapsed time")
    if spec["format"] == "forgejo-logged-workflow-v1" and inputs["context"] != "ci-workflow":
        raise EvidenceError("workflow receipts require a workflow context")
    for key in ("trigger", "test_scope", "cache_condition", "run_id"):
        if not isinstance(spec[key], str) or not 0 < len(spec[key]) <= 300:
            raise EvidenceError("scope, cache conditions and run identity must be explicit and bounded")
    identity(inputs["workflow_sha256"])
    identity(inputs["workload_sha256"])
    gates = inputs["gates"]
    if not isinstance(gates, list) or not 0 < len(gates) <= 64 or not all(isinstance(g, str) and 0 < len(g) <= 300 for g in gates):
        raise EvidenceError("declare the selected nonempty gate set")
    if len(gates) != len(set(gates)) or sorted(gates) != result["gates"]:
        raise EvidenceError("declared gates do not match executed receipt gates")
    inputs["gates"] = sorted(gates)
    for key in ("images", "dependencies"):
        if not isinstance(inputs[key], dict) or not 0 < len(inputs[key]) <= 32:
            raise EvidenceError("declare toolchain identities and dependency hashes")
        if not all(isinstance(k, str) and 0 < len(k) <= 120 and isinstance(v, str) and 0 < len(v) <= 300 for k, v in inputs[key].items()):
            raise EvidenceError("toolchain and dependency identities must be nonempty strings")
    for value in inputs["dependencies"].values():
        identity(value)
    if "dependency_sha256" in data and data["dependency_sha256"] != inputs["dependencies"]:
        raise EvidenceError("dependency declarations do not match the existing profile receipt")
    tests, refs = test_evidence(root, spec["tests"], source)
    result.update(inputs=inputs, tests=tests, run_id=spec["run_id"],
                  reference={"path": spec["receipt"], "sha256": receipt_sha, "source_sha": source,
                             "workflow_sha256": inputs["workflow_sha256"], "tests": refs,
                             "timing_breakdown": result["timing_breakdown"]})
    return result


def summary(samples):
    result = {"samples": len(samples)}
    for metric in ("elapsed_seconds", "aggregate_job_seconds"):
        values = [sample[metric] for sample in samples]
        result[metric] = {"min": min(values), "median": statistics.median(values), "max": max(values)}
    return result


def compare(root, manifest, manifest_sha):
    policy = policy_from(manifest)
    sides = {}
    for side in ("baseline", "candidate"):
        specs = manifest[side]
        if not isinstance(specs, list) or not 0 < len(specs) <= 100:
            raise EvidenceError("each side requires between 1 and 100 retained samples")
        sides[side] = [sample_from(root, spec) for spec in specs]
    samples = sides["baseline"] + sides["candidate"]
    run_ids = [sample["run_id"] for sample in samples]
    hashes = [sample["reference"]["sha256"] for sample in samples]
    if len(run_ids) != len(set(run_ids)) or len(hashes) != len(set(hashes)):
        raise EvidenceError("duplicate runs or receipt bytes cannot inflate the sample count")
    report = {"version": 1, "manifest_sha256": manifest_sha, "objective": manifest["objective"],
              "design": manifest["design"],
              "policy": policy, "decision": "insufficient_evidence", "reasons": [],
              "limitations": list(LIMITATIONS), "inputs": {},
              "evidence": {side: [sample["reference"] for sample in values] for side, values in sides.items()}}
    if manifest["design"] == "retrospective":
        report["limitations"].append("Policy was supplied retrospectively; it is not a preregistered experiment.")
    if policy.get("equivalent_triggers"):
        report["limitations"].append("Trigger equivalence is operator-declared; gate and workload equivalence are still checked.")
    for side, values in sides.items():
        report[side] = summary(values)
        report["inputs"][side] = values[0]["inputs"]
        if any(sample["inputs"] != values[0]["inputs"] for sample in values):
            report["reasons"].append("input conditions vary within " + side)
    first = sides["baseline"][0]
    for sample in samples[1:]:
        for key in SCOPE_KEYS:
            if key == "trigger" and {sample["inputs"][key], first["inputs"][key]} <= set(policy.get("equivalent_triggers", [])):
                continue
            if sample["inputs"][key] != first["inputs"][key]:
                report["reasons"].append("incompatible comparison scope: " + key)
        for key in INPUT_KEYS - set(policy["allowed_input_changes"]):
            if sample["inputs"][key] != first["inputs"][key]:
                report["reasons"].append("undeclared input change: " + key)
        if sample["tests"] != first["tests"] or sample["observed_counts"] != first["observed_counts"]:
            report["reasons"].append("test identities, outcomes or observed counts differ")
    if report["reasons"]:
        report["decision"] = "incomparable"
        report["reasons"] = sorted(set(report["reasons"]))
        return report
    report["tests"] = first["tests"]
    if any(s["failed"] or s["tests"]["failed"] or s["status"] == "failure" for s in samples):
        report.update(decision="reject", reasons=["execution or test evidence reports a failure"])
        return report
    if any(not s["known"] or s["status"] != "success" for s in samples):
        report["reasons"] = ["execution outcome missing or not conclusively successful"]
        return report
    base, candidate = report["baseline"], report["candidate"]
    elapsed_gain = 100 * (1 - candidate["elapsed_seconds"]["median"] / base["elapsed_seconds"]["median"])
    aggregate_increase = 100 * (candidate["aggregate_job_seconds"]["median"] / base["aggregate_job_seconds"]["median"] - 1)
    report["observed_change_percent"] = {"elapsed_reduction": round(elapsed_gain, 4),
                                         "aggregate_job_increase": round(aggregate_increase, 4)}
    enough = all(len(values) >= policy["minimum_samples"] for values in sides.values())
    if not enough:
        report["limitations"].append("Sample count is below the declared qualification minimum.")
    if elapsed_gain < policy["min_elapsed_reduction_percent"]:
        report["reasons"].append("observed elapsed reduction misses the declared minimum")
    if aggregate_increase > policy["max_aggregate_job_increase_percent"]:
        report["reasons"].append("observed aggregate job increase exceeds the declared budget")
    if report["reasons"]:
        report["decision"] = "reject"
    elif enough:
        report["decision"] = "meets_policy"
    else:
        report["reasons"] = ["more independent samples required before qualification"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--json", action="store_true", help="emit the bounded machine-readable comparison")
    parser.add_argument("--output", type=Path, help="exclusively create a retained comparison JSON file")
    args = parser.parse_args(argv)
    try:
        path = args.manifest.resolve()
        manifest, sha = read_json(path.parent, path.name)
        report = compare(path.parent, manifest, sha)
        if len(json.dumps(report, allow_nan=False)) > 256_000:
            raise EvidenceError("comparison exceeds the 256 KB output budget; split the experiment")
    except (EvidenceError, KeyError, TypeError) as error:
        report = {"version": 1, "decision": "insufficient_evidence",
                  "reasons": [str(error)[:300]], "limitations": LIMITATIONS}
    raw = json.dumps(report, sort_keys=True, allow_nan=False, indent=2) + "\n"
    if args.output:
        try:
            with args.output.open("x") as stream:
                stream.write(raw)
        except OSError:
            print("Cannot create output: choose an unused path in an existing directory.", file=sys.stderr)
            return 2
    if args.json:
        print(raw, end="")
    else:
        print("CI experiment: " + report["decision"])
        if "observed_change_percent" in report:
            change = report["observed_change_percent"]
            print(f"Observed median elapsed reduction: {change['elapsed_reduction']:.2f}%")
            print(f"Observed median aggregate job increase: {change['aggregate_job_increase']:.2f}% (not CPU time)")
            print(f"Samples: {report['baseline']['samples']} baseline, {report['candidate']['samples']} candidate")
        for reason in report["reasons"][:8]:
            print("- " + reason)
        print("Observed evidence only; retain the JSON receipt for inputs, references and limitations.")
    return {"meets_policy": 0, "reject": 1, "insufficient_evidence": 2, "incomparable": 3}[report["decision"]]


if __name__ == "__main__":
    raise SystemExit(main())
