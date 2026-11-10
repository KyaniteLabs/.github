"""State-machine tests for the provisioner report/repair lifecycle and the parity verdict."""

from __future__ import annotations

import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


parity = load_script("check_agent_parity", ROOT / "scripts" / "check-agent-parity.py")
prov = load_script("provision_agent_law", ROOT / "scripts" / "provision-agent-law.py")

Outcome = prov.Outcome
RowKind = prov.RowKind
Stage = prov.RepairStage


def cp(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout)


# ---------------------------------------------------------------------------
# Provisioner report statuses
# ---------------------------------------------------------------------------

# Every status string the pre-refactor code could write, verbatim.
LEGACY_STATUSES = {
    "skipped:not-org": (Outcome.SKIPPED, "not-org"),
    "skipped:admin-org-scope-required": (Outcome.SKIPPED, "admin-org-scope-required"),
    "skipped:repo-admin-required": (Outcome.SKIPPED, "repo-admin-required"),
    "blocked:admin-org-scope-required": (Outcome.BLOCKED, "admin-org-scope-required"),
    "blocked:repo-admin-required": (Outcome.BLOCKED, "repo-admin-required"),
    "blocked:clone-failed": (Outcome.BLOCKED, "clone-failed"),
    "blocked:payload-verification-failed": (Outcome.BLOCKED, "payload-verification-failed"),
    "exists:123": (Outcome.EXISTS, "123"),
    "missing:dry-run": (Outcome.MISSING, "dry-run"),
    "created:456": (Outcome.CREATED, "456"),
    "compliant": (Outcome.COMPLIANT, None),
    "compliant-after-checkout": (Outcome.COMPLIANT_AFTER_CHECKOUT, None),
    "pr:https://github.com/o/r/pull/1": (Outcome.PR, "https://github.com/o/r/pull/1"),
}


class StatusTests(unittest.TestCase):
    def test_legacy_values_parse_and_round_trip_byte_for_byte(self) -> None:
        for text, (outcome, detail) in LEGACY_STATUSES.items():
            with self.subTest(text=text):
                self.assertEqual(prov.parse_status(text), (outcome, detail))
                self.assertEqual(prov.status(outcome, detail), text)

    def test_every_outcome_is_covered_by_legacy_table(self) -> None:
        self.assertEqual({o for o, _ in LEGACY_STATUSES.values()}, set(Outcome))

    def test_every_outcome_belongs_to_some_row_kind(self) -> None:
        self.assertEqual(set(prov.ALLOWED_OUTCOMES), set(RowKind))
        covered = set().union(*prov.ALLOWED_OUTCOMES.values())
        self.assertEqual(covered, set(Outcome))

    def test_unknown_value_is_read_tolerantly(self) -> None:
        self.assertEqual(prov.parse_status("weird:thing"), (None, "weird:thing"))
        self.assertFalse(prov.is_blocking("weird:thing"))

    def test_status_refuses_free_text(self) -> None:
        with self.assertRaises(TypeError):
            prov.status("done")

    def test_only_blocked_is_blocking(self) -> None:
        for outcome in Outcome:
            with self.subTest(outcome=outcome):
                self.assertEqual(prov.is_blocking(prov.status(outcome, "x")), outcome is Outcome.BLOCKED)

    def test_exit_code(self) -> None:
        self.assertEqual(prov.exit_code([]), 0)
        self.assertEqual(prov.exit_code([{"status": "compliant"}, {"status": "pr:u"}]), 0)
        self.assertEqual(prov.exit_code([{"status": "compliant"}, {"status": "blocked:clone-failed"}]), 2)

    def test_make_row_allows_exactly_the_table(self) -> None:
        for kind in RowKind:
            for outcome in Outcome:
                text = prov.status(outcome, "d")
                with self.subTest(kind=kind, outcome=outcome):
                    if outcome in prov.ALLOWED_OUTCOMES[kind]:
                        self.assertEqual(
                            prov.make_row("o/r", kind, text), {"scope": "o/r", "kind": kind.value, "status": text}
                        )
                    else:
                        with self.assertRaises(ValueError):
                            prov.make_row("o/r", kind, text)

    def test_make_row_refuses_unknown_status(self) -> None:
        with self.assertRaises(ValueError):
            prov.make_row("o/r", RowKind.FILES, "done")

    def test_row_kind_values_are_the_persisted_strings(self) -> None:
        self.assertEqual([k.value for k in RowKind], ["org-ruleset", "repo-ruleset", "files"])


class RulesetTransitionTests(unittest.TestCase):
    """org and repo ruleset ensure share one transition; both must give identical outcomes."""

    def _ensure(self, which: str, *, listed: subprocess.CompletedProcess[str], apply: bool):
        calls: list[tuple[str, str]] = []

        def fake_gh_api(path, *, method="GET", payload=None, check=True):
            calls.append((method, path))
            if method == "POST":
                return cp(json.dumps({"id": 99}))
            if path.startswith("/orgs/") and path.count("/") == 2:
                return cp("{}")  # is_org probe
            return listed

        repo = prov.Repo("o/r", "main", False, False, "https://github.com/o/r")
        with mock.patch.object(prov, "gh_api", fake_gh_api):
            if which == "org":
                result = prov.ensure_org_ruleset("o", apply=apply)
            else:
                result = prov.ensure_repo_ruleset(repo, apply=apply)
        return result, calls

    def test_outcome_table(self) -> None:
        denied = cp("", 1)
        present = cp(json.dumps([{"name": "Other", "id": 1}, {"name": "Agent Law", "id": 7}]))
        absent = cp(json.dumps([{"name": "Other", "id": 1}]))
        expectations = {
            ("org", "denied", False): "skipped:admin-org-scope-required",
            ("org", "denied", True): "blocked:admin-org-scope-required",
            ("repo", "denied", False): "skipped:repo-admin-required",
            ("repo", "denied", True): "blocked:repo-admin-required",
        }
        for which in ("org", "repo"):
            for apply in (False, True):
                with self.subTest(which=which, apply=apply):
                    result, _ = self._ensure(which, listed=denied, apply=apply)
                    self.assertEqual(result, expectations[(which, "denied", apply)])
                    result, calls = self._ensure(which, listed=present, apply=apply)
                    self.assertEqual(result, "exists:7")
                    self.assertNotIn("POST", [m for m, _ in calls])
                    result, calls = self._ensure(which, listed=absent, apply=apply)
                    if apply:
                        self.assertEqual(result, "created:99")
                        self.assertIn("POST", [m for m, _ in calls])
                    else:
                        self.assertEqual(result, "missing:dry-run")
                        self.assertNotIn("POST", [m for m, _ in calls])

    def test_non_org_owner_is_skipped(self) -> None:
        with mock.patch.object(prov, "gh_api", lambda *a, **k: cp("", 1)):
            self.assertEqual(prov.ensure_org_ruleset("someone", apply=True), "skipped:not-org")


# ---------------------------------------------------------------------------
# Repair lifecycle
# ---------------------------------------------------------------------------


class RepairRunTests(unittest.TestCase):
    def test_transition_table_is_exhaustive(self) -> None:
        self.assertEqual(set(prov.REPAIR_TRANSITIONS), set(Stage))

    def test_every_legal_transition(self) -> None:
        for src, targets in prov.REPAIR_TRANSITIONS.items():
            for dst in targets:
                with self.subTest(src=src, dst=dst):
                    run = prov.RepairRun()
                    run.stage = src
                    run.resumed_branch = True
                    run.advance(dst)
                    self.assertIs(run.stage, dst)

    def test_every_illegal_transition_is_refused(self) -> None:
        for src in Stage:
            for dst in Stage:
                if dst in prov.REPAIR_TRANSITIONS[src]:
                    continue
                with self.subTest(src=src, dst=dst):
                    run = prov.RepairRun()
                    run.stage = src
                    run.resumed_branch = True
                    with self.assertRaises(prov.IllegalTransition):
                        run.advance(dst)
                    self.assertIs(run.stage, src)

    def test_fresh_branch_cannot_skip_commit(self) -> None:
        run = prov.RepairRun()
        run.advance(Stage.BRANCH_READY)
        run.advance(Stage.PAYLOAD_APPLIED)
        with self.assertRaises(prov.IllegalTransition):
            run.advance(Stage.PUSHED)

    def test_random_walks_keep_invariants(self) -> None:
        """Stateful property test: random moves, invariants checked after every step."""
        rng = random.Random(1234)
        order = list(Stage)
        for _ in range(500):
            run = prov.RepairRun()
            run.resumed_branch = rng.random() < 0.5
            committed = False
            for _ in range(12):
                dst = rng.choice(order)
                before = run.stage
                try:
                    run.advance(dst)
                except prov.IllegalTransition:
                    self.assertIs(run.stage, before)
                    continue
                self.assertIn(dst, prov.REPAIR_TRANSITIONS[before])
                committed = committed or dst is Stage.COMMITTED
                # The lifecycle only moves forward.
                self.assertGreater(order.index(run.stage), order.index(before))
                # Nothing reaches the remote unless it was committed now or was already there.
                if run.stage in (Stage.PUSHED, Stage.PR_OPEN):
                    self.assertTrue(committed or run.resumed_branch)
                if run.stage is Stage.PR_OPEN:
                    self.assertEqual(prov.REPAIR_TRANSITIONS[run.stage], frozenset())


class FakeGit:
    """Stands in for run(): clones a non-compliant repo and scripts git/gh answers."""

    def __init__(self, *, remote_branch: bool, dirty_after_payload: bool, open_pr: str = "") -> None:
        self.remote_branch = remote_branch
        self.dirty_after_payload = dirty_after_payload
        self.open_pr = open_pr
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *, cwd=None, check=True):
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "repo", "clone"]:
            Path(cmd[4]).mkdir(parents=True)
            (Path(cmd[4]) / "README.md").write_text("# repo\n")
            return cp()
        if cmd[:2] == ["git", "ls-remote"]:
            return cp("abc\trefs/heads/x\n" if self.remote_branch else "")
        if cmd[:2] == ["git", "status"]:
            return cp(" M AGENTS.md\n" if self.dirty_after_payload else "")
        if cmd[:3] == ["gh", "pr", "list"]:
            return cp(self.open_pr + "\n" if self.open_pr else "")
        if cmd[:3] == ["gh", "pr", "create"]:
            return cp("https://github.com/o/r/pull/42\n")
        return cp()

    def ran(self, *prefix: str) -> bool:
        return any(c[: len(prefix)] == list(prefix) for c in self.calls)


class RepairFilesTests(unittest.TestCase):
    repo = prov.Repo("o/r", "main", False, False, "https://github.com/o/r")

    def _repair(self, fake: FakeGit, *, apply: bool = True) -> str:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(prov, "run", fake):
            return prov.repair_files(self.repo, apply=apply, branch="b", workdir=Path(tmp))

    def test_dry_run(self) -> None:
        fake = FakeGit(remote_branch=False, dirty_after_payload=True)
        self.assertEqual(self._repair(fake, apply=False), "missing:dry-run")
        self.assertFalse(fake.ran("git", "push"))

    def test_clone_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(prov, "run", lambda *a, **k: cp("", 128)):
            self.assertEqual(
                prov.repair_files(self.repo, apply=True, branch="b", workdir=Path(tmp)), "blocked:clone-failed"
            )

    def test_fresh_branch_commits_pushes_and_opens_pr(self) -> None:
        fake = FakeGit(remote_branch=False, dirty_after_payload=True)
        self.assertEqual(self._repair(fake), "pr:https://github.com/o/r/pull/42")
        self.assertTrue(fake.ran("git", "commit"))
        self.assertTrue(fake.ran("git", "push"))

    def test_fresh_branch_without_diff_reports_compliant_after_checkout(self) -> None:
        fake = FakeGit(remote_branch=False, dirty_after_payload=False)
        self.assertEqual(self._repair(fake), "compliant-after-checkout")
        self.assertFalse(fake.ran("git", "push"))

    def test_resumed_branch_with_open_pr_reports_that_pr(self) -> None:
        fake = FakeGit(remote_branch=True, dirty_after_payload=False, open_pr="https://github.com/o/r/pull/7")
        self.assertEqual(self._repair(fake), "pr:https://github.com/o/r/pull/7")
        self.assertFalse(fake.ran("git", "commit"))
        self.assertFalse(fake.ran("gh", "pr", "create"))

    def test_bug_pushed_branch_without_pr_gets_a_pr(self) -> None:
        """Old code: an earlier run pushed the repair branch but `gh pr create` failed (or the PR was closed).
        Every later run found no diff on the resumed branch, returned "compliant-after-checkout" and never
        opened a PR, so the drifting repo was reported as compliant forever."""
        fake = FakeGit(remote_branch=True, dirty_after_payload=False)
        self.assertEqual(self._repair(fake), "pr:https://github.com/o/r/pull/42")
        self.assertTrue(fake.ran("gh", "pr", "create"))
        self.assertFalse(fake.ran("git", "commit"))

    def test_payload_verification_failure_blocks(self) -> None:
        fake = FakeGit(remote_branch=False, dirty_after_payload=True)
        with mock.patch.object(prov, "apply_payload", lambda repo_dir: None):
            self.assertEqual(self._repair(fake), "blocked:payload-verification-failed")
        self.assertFalse(fake.ran("git", "commit"))


# ---------------------------------------------------------------------------
# Parity verdict
# ---------------------------------------------------------------------------


class ParityStatusTests(unittest.TestCase):
    def test_derived_state_table(self) -> None:
        S = parity.ParityStatus
        table = [
            (1.0, True, True, S.PASS),
            (0.9, True, True, S.PASS),
            (0.89, True, True, S.WARN),
            (0.7, True, True, S.WARN),
            (0.69, True, True, S.FAIL),
            (0.0, True, True, S.FAIL),
            (1.0, True, False, S.FAIL),
            (1.0, False, True, S.FAIL),
            (1.0, False, False, S.FAIL),
        ]
        for score, has_c, has_a, expected in table:
            with self.subTest(score=score, has_c=has_c, has_a=has_a):
                self.assertIs(parity.derive_status(score, has_c, has_a), expected)
        self.assertEqual({row[-1] for row in table}, set(S))

    def test_property_missing_file_never_passes(self) -> None:
        rng = random.Random(99)
        for _ in range(1000):
            score = rng.random()
            has_c, has_a = rng.random() < 0.5, rng.random() < 0.5
            result = parity.derive_status(score, has_c, has_a)
            if not (has_c and has_a):
                self.assertIs(result, parity.ParityStatus.FAIL)
            # Monotone: raising the score never worsens the verdict.
            better = parity.derive_status(min(1.0, score + rng.random()), has_c, has_a)
            order = [parity.ParityStatus.FAIL, parity.ParityStatus.WARN, parity.ParityStatus.PASS]
            self.assertGreaterEqual(order.index(better), order.index(result))

    def test_stored_values_and_legacy_reads(self) -> None:
        self.assertEqual([s.value for s in parity.ParityStatus], ["pass", "warn", "fail"])
        for s in parity.ParityStatus:
            self.assertIs(parity.parse_status(s.value), s)
            self.assertIs(parity.parse_status(f" {s.value.upper()} "), s)
            self.assertEqual(json.dumps(s), json.dumps(s.value))
        with self.assertRaises(ValueError):
            parity.parse_status("ok")

    def test_counts_and_exit_code_cover_every_status(self) -> None:
        def result(s):
            return mock.Mock(status=s)

        results = [result(s) for s in parity.ParityStatus]
        self.assertEqual(parity.count_by_status(results), {s: 1 for s in parity.ParityStatus})
        for s in parity.ParityStatus:
            with self.subTest(status=s):
                self.assertEqual(parity.exit_code([result(s)], ci=True), 1 if s is parity.ParityStatus.FAIL else 0)
                self.assertEqual(parity.exit_code([result(s)], ci=False), 0)

    def test_bug_empty_section_body_counts_as_present(self) -> None:
        """Old code tested sections with truthiness, so a heading with only sub-headings under it (body "")
        counted as missing from both files and lowered the score without any reported reason."""
        doc = "# Organization Principles\n\n## Workflow\nsteps\n"
        score, differences = parity.check_section_parity(doc, doc)
        self.assertNotIn("Section 'Organization Principles'", " ".join(differences))
        total = len(parity.CANONICAL_SECTIONS)
        self.assertAlmostEqual(score, 1 / total)

    def test_bug_section_missing_from_both_is_reported(self) -> None:
        """Old code silently counted a section absent from both files against the score: a repo could
        fail with an empty list of differences."""
        doc = "# Organization Principles\nUseful.\n"
        score, differences = parity.check_section_parity(doc, doc)
        self.assertLess(score, 1.0)
        self.assertEqual(len(differences), len(parity.CANONICAL_SECTIONS) - 1)
        self.assertIn("Section 'Label System' missing from both CLAUDE.md and AGENTS.md", differences)

    def test_bug_hidden_named_cwd_is_still_checked(self) -> None:
        """Old code filtered the current directory by its own name, so running the checker inside this
        `.github` repo checked nothing and `--ci` exited 0."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / ".github"
            repo.mkdir()
            with mock.patch.object(Path, "cwd", return_value=repo):
                self.assertEqual(parity.discover_repos(None), [repo])

    def test_repos_dir_skips_hidden_children_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a").mkdir()
            (base / ".hidden").mkdir()
            (base / "file.txt").write_text("x")
            self.assertEqual(parity.discover_repos(str(base)), [base / "a"])


if __name__ == "__main__":
    unittest.main()
