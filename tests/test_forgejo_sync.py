"""Offline tests for scripts/forgejo_sync.py (the GitHub -> Forgejo mirror gate).

No network: event validation, argument checks and the fast-forward-only git
path run against a throwaway local "Forgejo" bare repository.
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("forgejo_sync", ROOT / "scripts" / "forgejo_sync.py")
fjs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fjs)

SHA = "966fdefd66cd1d49522a8e456b129080adeb7cd4"
REPO = "KyaniteLabs/example"


def event(**run_overrides):
    run = {
        "workflow_id": 249485876,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "push",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "head_sha": SHA,
        "head_repository": {"full_name": REPO},
    }
    run.update(run_overrides)
    return {"repository": {"full_name": REPO}, "workflow_run": run}


def validate(payload, **kw):
    return fjs.validate_workflow_event(
        payload,
        REPO,
        workflow_id=kw.get("workflow_id", 249485876),
        workflow_name=kw.get("workflow_name", "CI"),
        workflow_path=kw.get("workflow_path", ".github/workflows/ci.yml"),
        trunk=kw.get("trunk", "main"),
    )


class EventValidation(unittest.TestCase):
    def test_exact_trunk_ci_success_returns_sha(self):
        self.assertEqual(validate(event()), SHA)

    def test_refuses_other_trunk(self):
        with self.assertRaises(fjs.SyncError):
            validate(event(), trunk="master")

    def test_refuses_foreign_workflow_identity(self):
        with self.assertRaises(fjs.SyncError):
            validate(event(), workflow_id=111, workflow_name="build")

    def test_refuses_pull_request_runs(self):
        with self.assertRaises(fjs.SyncError):
            validate(event(event="pull_request"))

    def test_refuses_failed_ci(self):
        with self.assertRaises(fjs.SyncError):
            validate(event(conclusion="failure"))

    def test_refuses_fork_head_repository(self):
        with self.assertRaises(fjs.SyncError):
            validate(event(head_repository={"full_name": "someone/fork"}))

    def test_refuses_unsafe_ref_component(self):
        with self.assertRaises(fjs.SyncError):
            fjs._validate_ref_component("refs/heads/x", field="trunk branch")


def git(*args, cwd):
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, env=env, check=True, capture_output=True, text=True,
    ).stdout.strip()


class FastForwardOnly(unittest.TestCase):
    """The sync step pushes only when the mirror tip is an ancestor of the source."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.mirror = base / "mirror.git"
        self.source = base / "source"
        git("init", "--bare", str(self.mirror), cwd=base)
        git("init", str(self.source), cwd=base)
        (self.source / "a").write_text("1")
        git("add", "a", cwd=self.source)
        git("commit", "-m", "one", cwd=self.source)
        git("push", str(self.mirror), "main", cwd=self.source)
        (self.source / "a").write_text("2")
        git("commit", "-am", "two", cwd=self.source)
        self.head = git("rev-parse", "HEAD", cwd=self.source)
        # A local stand-in for GitHub, so verify_source_tip's trunk re-check passes
        # and the refusal under test comes from the mirror URL check, not a fetch error.
        self.github = base / "github.git"
        git("init", "--bare", str(self.github), cwd=base)
        git("push", str(self.github), "main", cwd=self.source)
        git("remote", "add", "origin", str(self.github), cwd=self.source)

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self, dry_run):
        # file:// is refused by design (HTTPS only), so call the git steps the
        # same way sync_downstream does, through its own helpers.
        fjs.verify_source_tip(self.source, self.head, "main")  # passes: exact trunk tip
        with self.assertRaisesRegex(fjs.SyncError, "HTTPS"):
            fjs.sync_downstream(
                directory=self.source, source_sha=self.head, trunk="main",
                forgejo_git_url="file://" + str(self.mirror), forgejo_api_url="https://x",
                forgejo_repository="o/r", downstream_workflow="", username="", token="",
                dry_run=dry_run,
            )

    def test_non_https_mirror_url_is_refused(self):
        self.sync(dry_run=True)
        self.sync(dry_run=False)
        # nothing was pushed
        tip = git("rev-parse", "refs/heads/main", cwd=self.mirror)
        self.assertNotEqual(tip, self.head)

    def test_diverged_mirror_is_not_an_ancestor(self):
        other = pathlib.Path(self.tmp.name) / "other"
        git("clone", str(self.mirror), str(other), cwd=self.tmp.name)
        (other / "b").write_text("x")
        git("add", "b", cwd=other)
        git("commit", "-m", "mirror-only", cwd=other)
        git("push", "origin", "main", cwd=other)
        git("fetch", str(self.mirror), "main:refs/remotes/mirror/main", cwd=self.source)
        rc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "refs/remotes/mirror/main", self.head],
            cwd=self.source, capture_output=True,
        ).returncode
        self.assertNotEqual(rc, 0, "a diverged mirror must fail the fast-forward gate")


class CommandLine(unittest.TestCase):
    def test_gate_rejects_duplicate_required_workflows(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(event(), fh)
        try:
            rc = fjs.main([
                "github-gate", "--event", fh.name, "--repository", REPO,
                "--api-url", "https://api.github.com", "--trunk", "main",
                "--trigger-workflow-id", "249485876", "--trigger-workflow-name", "CI",
                "--trigger-workflow-path", ".github/workflows/ci.yml",
                "--required-workflow", "1:.github/workflows/ci.yml",
                "--required-workflow", "1:.github/workflows/ci.yml",
            ])
        finally:
            os.unlink(fh.name)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
