"""Metrics must measure only what the API recorded and never hide unavailable data."""

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ci_metrics", Path(__file__).resolve().parents[1] / "scripts/ci_metrics.py",
)
METRICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METRICS)

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def run(workflow="ci.yml", event="push", sha="a" * 40, created="2026-10-25T10:00:00Z",
        queue=30, runtime=120, status="success"):
    start = METRICS.timestamp(created).timestamp() + queue
    stop = start + runtime
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"workflow_id": workflow, "trigger_event": event, "commit_sha": sha, "status": status,
            "created": created, "started": iso(start), "stopped": iso(stop)}


class PercentileTests(unittest.TestCase):
    def test_nearest_rank(self):
        values = list(range(1, 101))
        self.assertEqual(METRICS.percentile(values, 0.5), 50)
        self.assertEqual(METRICS.percentile(values, 0.95), 95)
        self.assertEqual(METRICS.percentile([7], 0.95), 7)

    def test_empty_sample_is_none_not_zero(self):
        self.assertIsNone(METRICS.percentile([], 0.5))


class TimestampTests(unittest.TestCase):
    def test_zero_and_absent_values_mean_never_happened(self):
        for value in (None, "", "0001-01-01T00:00:00Z", "garbage"):
            self.assertIsNone(METRICS.timestamp(value))

    def test_offsets_are_respected(self):
        self.assertEqual(METRICS.timestamp("2026-10-25T16:00:00-07:00"),
                         datetime(2026, 10, 25, 23, tzinfo=timezone.utc))


class SummaryTests(unittest.TestCase):
    def test_queue_and_runtime_per_workflow_and_event(self):
        report = METRICS.summarize("o/r", [run(queue=10, runtime=60), run(queue=30, runtime=180, sha="b" * 40)])
        (row,) = report["rows"]
        self.assertEqual((row["workflow"], row["event"], row["runs"]), ("ci.yml", "push", 2))
        self.assertEqual((row["queue_p50"], row["queue_p95"]), (10, 30))
        self.assertEqual((row["runtime_p50"], row["runtime_p95"]), (60, 180))

    def test_unfinished_runs_are_counted_not_measured(self):
        waiting = run()
        waiting["started"] = waiting["stopped"] = "0001-01-01T00:00:00Z"
        report = METRICS.summarize("o/r", [waiting, run(sha="b" * 40)])
        (row,) = report["rows"]
        self.assertEqual((row["runs"], row["unmeasured"]), (2, 1))
        self.assertEqual(row["runtime_p95"], 120)

    def test_reversed_timestamps_are_unmeasured(self):
        broken = run()
        broken["stopped"] = broken["created"]
        (row,) = METRICS.summarize("o/r", [broken])["rows"]
        self.assertEqual((row["unmeasured"], row["runtime_p50"]), (1, None))

    def test_duplicates_are_per_workflow_and_commit(self):
        report = METRICS.summarize("o/r", [
            run(event="push"), run(event="pull_request"),           # same sha, two events
            run(event="push", sha="b" * 40), run(event="push", sha="b" * 40),  # same event twice
            run(workflow="lint.yml"),                                 # other workflow, not a duplicate
        ])
        self.assertEqual(report["duplicate_builds"], 2)
        self.assertEqual(report["extra_runs"], 2)
        self.assertEqual(report["cross_event_duplicates"], 1)


class PagingTests(unittest.TestCase):
    def pages(self, total):
        items = [run(sha=f"{i:040x}") for i in range(total)]
        calls = []

        def get(path):
            calls.append(path)
            page = int(path.rsplit("page=", 1)[1])
            return {"workflow_runs": items[(page - 1) * METRICS.PAGE: page * METRICS.PAGE]}

        return get, calls

    def test_stops_at_limit(self):
        get, calls = self.pages(120)
        self.assertEqual(len(METRICS.runs("o/r", get, limit=60)), 60)
        self.assertEqual(len(calls), 2)

    def test_stops_on_short_page(self):
        get, calls = self.pages(70)
        self.assertEqual(len(METRICS.runs("o/r", get, limit=200)), 70)
        self.assertEqual(len(calls), 2)

    def test_stops_at_since(self):
        old = run(created="2026-09-01T00:00:00Z")
        get = lambda path: {"workflow_runs": [run(), old, run()]}
        self.assertEqual(len(METRICS.runs("o/r", get, since=datetime(2026, 10, 1, tzinfo=timezone.utc))), 1)

    def test_malformed_response_is_a_failed_lookup(self):
        with self.assertRaises(METRICS.LookupFailed):
            METRICS.runs("o/r", lambda path: {"unexpected": True})


class MainTests(unittest.TestCase):
    def test_unavailable_repository_is_reported_and_fails(self):
        def get(path):
            if path.startswith("repos/o/bad"):
                raise METRICS.LookupFailed("lookup unavailable")
            return {"workflow_runs": [run()]}

        out = io.StringIO()
        with redirect_stdout(out):
            code = METRICS.main(["o/good", "o/bad"], get=get, now=NOW)
        self.assertEqual(code, 1)
        self.assertIn("| o/good | ci.yml | push | 1 | 0 | 30s | 30s | 2m00s | 2m00s |", out.getvalue())
        self.assertIn("| o/bad | - | - | - | - | unavailable: lookup unavailable", out.getvalue())

    def test_rejects_path_traversal(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            METRICS.main(["o/.."], get=lambda path: {}, now=NOW)


if __name__ == "__main__":
    unittest.main()
