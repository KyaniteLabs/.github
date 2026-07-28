#!/usr/bin/env python3
"""Verify one fresh, signed G006 report without network or third-party modules."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_SECOND = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ROOT_KEYS = frozenset({
    "schema_version", "phase", "generated_at", "read_only", "secret_values_printed",
    "status", "source", "summary", "inventory", "pairs", "integrity_sha256",
})
SUMMARY_KEYS = frozenset({
    "inventory_count", "github_count", "forgejo_count", "pair_count", "readme_records",
    "access_errors", "parity_current", "parity_mismatch", "blocked_pairs",
})
INVENTORY_KEYS = frozenset({"host", "full_name", "status", "default_branch", "head_sha", "access_error", "readmes"})
README_KEYS = frozenset({"path", "blob_sha", "raw_sha256", "bytes"})
PAIR_KEYS = frozenset({
    "pair_id", "github", "forgejo", "status", "mismatches", "blocked_reasons",
    "readme_count", "github_head_sha", "forgejo_head_sha",
})


class VerificationError(ValueError):
    """A report failed the G006 verification contract."""


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError("report contains duplicate JSON keys")
        result[key] = value
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def require_keys(value: Any, required: set[str], allowed: frozenset[str], label: str) -> None:
    require(isinstance(value, dict), f"{label} is not an object")
    require(required.issubset(value), f"{label} is missing required fields")
    require(set(value).issubset(allowed), f"{label} contains unexpected fields")


def validate_schema_contract(report: Any) -> None:
    require_keys(report, set(ROOT_KEYS), ROOT_KEYS, "report")
    require(report["schema_version"] == "G006.report.v1", "invalid report schema version")
    require(report["phase"] == "G006", "invalid report phase")
    require(isinstance(report["generated_at"], str) and UTC_SECOND.fullmatch(report["generated_at"]), "generated_at is not UTC second precision")
    require(report["read_only"] is True and report["secret_values_printed"] is False, "report is not read-only and secret-safe")
    require(report["status"] in {"passed", "blocked"}, "invalid report status")

    source = report["source"]
    require_keys(source, {"config_sha256", "no_remote_mutation"}, frozenset({"config_sha256", "no_remote_mutation"}), "source")
    require(isinstance(source["config_sha256"], str) and HEX64.fullmatch(source["config_sha256"]), "invalid config hash")
    require(source["no_remote_mutation"] is True, "report does not prove no remote mutation")

    summary = report["summary"]
    require_keys(summary, SUMMARY_KEYS, SUMMARY_KEYS, "summary")
    require(summary["inventory_count"] == 198 and summary["github_count"] == 103 and summary["forgejo_count"] == 95, "report inventory counts are not pinned")
    require(summary["pair_count"] == 58, "report pair count is not pinned")
    for key in ("readme_records", "access_errors", "parity_current", "parity_mismatch", "blocked_pairs"):
        require(isinstance(summary[key], int) and not isinstance(summary[key], bool) and summary[key] >= 0, f"invalid summary field: {key}")

    inventory = report["inventory"]
    pairs = report["pairs"]
    require(isinstance(inventory, list) and len(inventory) == 198, "report inventory is not exactly 198 rows")
    require(isinstance(pairs, list) and len(pairs) == 58, "report pairs are not exactly 58 rows")
    inventory_ids: set[str] = set()
    for row in inventory:
        require_keys(row, {"host", "full_name", "status", "readmes"}, INVENTORY_KEYS, "inventory row")
        require(row["host"] in {"github", "forgejo"}, "invalid inventory host")
        require(isinstance(row["full_name"], str) and row["full_name"].count("/") == 1 and all(row["full_name"].split("/")), "invalid inventory identity")
        identity = f"{row['host']}:{row['full_name']}"
        require(identity not in inventory_ids, "duplicate inventory identity")
        inventory_ids.add(identity)
        require(row["status"] in {"ok", "ok_empty", "access_error"}, "invalid inventory status")
        require(isinstance(row["readmes"], list), "inventory readmes is not an array")
        for key in ("default_branch", "head_sha"):
            if key in row:
                require(row[key] is None or isinstance(row[key], str), f"invalid inventory field: {key}")
        if "access_error" in row:
            require(isinstance(row["access_error"], dict), "invalid inventory access error")
        for readme in row["readmes"]:
            require_keys(readme, set(README_KEYS), README_KEYS, "README record")
            require(isinstance(readme["path"], str), "invalid README path")
            require(isinstance(readme["blob_sha"], str) and len(readme["blob_sha"]) >= 7, "invalid README blob hash")
            require(isinstance(readme["raw_sha256"], str) and HEX64.fullmatch(readme["raw_sha256"]), "invalid README content hash")
            require(isinstance(readme["bytes"], int) and not isinstance(readme["bytes"], bool) and readme["bytes"] >= 0, "invalid README byte count")

    pair_ids: set[str] = set()
    for pair in pairs:
        require_keys(pair, {"pair_id", "github", "forgejo", "status", "mismatches", "github_head_sha", "forgejo_head_sha"}, PAIR_KEYS, "pair row")
        require(all(isinstance(pair[key], str) for key in ("pair_id", "github", "forgejo")), "invalid pair identity")
        require(pair["pair_id"] not in pair_ids, "duplicate pair identity")
        pair_ids.add(pair["pair_id"])
        require(pair["status"] in {"parity_current", "parity_mismatch", "blocked_access"}, "invalid pair status")
        require(isinstance(pair["mismatches"], list), "invalid pair mismatches")
        for key in ("github_head_sha", "forgejo_head_sha"):
            require(pair[key] is None or isinstance(pair[key], str), f"invalid pair field: {key}")
        if "blocked_reasons" in pair:
            require(isinstance(pair["blocked_reasons"], list) and all(isinstance(item, str) for item in pair["blocked_reasons"]), "invalid blocked reasons")
        if "readme_count" in pair:
            require(isinstance(pair["readme_count"], dict), "invalid pair README count")

    require(report["status"] == "passed", "signed report is not passed")
    require(summary["access_errors"] == 0 and summary["parity_current"] == 58 and summary["parity_mismatch"] == 0 and summary["blocked_pairs"] == 0, "passed report contains blocked or mismatched work")
    integrity = report["integrity_sha256"]
    require(isinstance(integrity, str) and HEX64.fullmatch(integrity), "missing report integrity hash")
    unsigned = dict(report)
    del unsigned["integrity_sha256"]
    require(integrity == hashlib.sha256(canonical(unsigned)).hexdigest(), "report integrity hash does not match canonical payload")


def regular_file(path: Path, label: str) -> None:
    require(not path.is_symlink() and path.is_file(), f"{label} is not a regular file")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value: str) -> datetime:
    require(bool(UTC_SECOND.fullmatch(value)), "timestamp is not UTC second precision")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def verify_signature(report: Path, signature: Path, public_key: Path) -> None:
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(public_key), "-signature", str(signature), str(report)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    require(result.returncode == 0, "report signature verification failed")


def verify(report_path: Path, signature_path: Path, public_key_path: Path, schema_path: Path, expected_config_sha256: str, expected_schema_sha256: str, expected_public_key_sha256: str, now: str, max_age_seconds: int) -> dict[str, object]:
    for path, label in ((report_path, "report"), (signature_path, "signature"), (public_key_path, "public key"), (schema_path, "schema")):
        regular_file(path, label)
    require(HEX64.fullmatch(expected_config_sha256) is not None, "expected config hash is invalid")
    require(HEX64.fullmatch(expected_schema_sha256) is not None, "expected schema hash is invalid")
    require(HEX64.fullmatch(expected_public_key_sha256) is not None, "expected public-key hash is invalid")
    require(max_age_seconds > 0, "freshness window is invalid")
    require(sha256_file(schema_path) == expected_schema_sha256, "schema hash is not pinned")
    require(sha256_file(public_key_path) == expected_public_key_sha256, "public-key hash is not pinned")
    report_bytes = report_path.read_bytes()
    require(report_bytes, "report is empty")
    require(len(signature_path.read_bytes()) <= 4096, "signature is unexpectedly large")
    try:
        report = json.loads(report_bytes.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("report is not valid UTF-8 JSON") from exc
    validate_schema_contract(report)
    require(report_bytes == canonical(report), "report is not canonical JSON")
    require(report["source"]["config_sha256"] == expected_config_sha256, "report config hash is not trusted")
    generated = parse_time(report["generated_at"])
    current = parse_time(now)
    age = (current - generated).total_seconds()
    require(0 <= age <= max_age_seconds, "signed report is outside freshness window")
    verify_signature(report_path, signature_path, public_key_path)
    return {"status": "verified", "fresh": True, "signature": "valid", "schema": "pinned", "config": "pinned", "public_key": "pinned", "remote_access": "not_used", "secret_values_printed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--expected-schema-sha256", required=True)
    parser.add_argument("--expected-public-key-sha256", required=True)
    parser.add_argument("--now", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    parser.add_argument("--max-age-seconds", type=int, default=93600)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.report, args.signature, args.public_key, args.schema, args.expected_config_sha256, args.expected_schema_sha256, args.expected_public_key_sha256, args.now, args.max_age_seconds), sort_keys=True))
        return 0
    except (OSError, VerificationError, ValueError) as exc:
        print(f"G006 signed-report gate blocked: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
