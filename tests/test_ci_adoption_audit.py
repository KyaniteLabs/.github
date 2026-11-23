"""Offline signals must not turn disabled gates or unavailable data into proof."""

import argparse
import base64
import importlib.util
import json
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ci_audit", Path(__file__).resolve().parents[1] / "scripts/ci_adoption_audit.py",
)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class AdoptionAuditTests(unittest.TestCase):
    def fixtures(self):
        profile = {"version": 1, "junit_reports": ["results.xml"], "steps": [
            {"phase": phase, "argv": ["true"]} for phase in AUDIT.PHASES
        ]}
        workflow = "uses: example/shared/.forgejo/workflows/ci-profile.yml@" + "a" * 40 + "\n"

        def encoded(text):
            return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}

        return {
            "repos/example/app": {"default_branch": "main"},
            "repos/example/app/branches/main": {"commit": {"id": "b" * 40}},
            "repos/example/app/pulls/7": {"head": {"sha": "c" * 40}},
            "repos/example/app/commits/" + "b" * 40 + "/status": {"statuses": []},
            "repos/example/app/commits/" + "c" * 40 + "/status": {"statuses": [
                {"context": "CI / ci/required (pull_request)", "status": "success"},
            ]},
            "repos/example/app/branch_protections": [{
                "branch_name": "main", "enable_status_check": True,
                "status_check_contexts": ["CI / ci/required (pull_request)"],
                "apply_to_admins": True, "enable_push": False,
            }],
            "repos/example/app/contents/.ci/profile.json?ref=" + "b" * 40: encoded(json.dumps(profile)),
            "repos/example/app/contents/.forgejo/workflows/ci.yml?ref=" + "b" * 40: encoded(workflow),
        }

    def test_pinned_consumer_and_supplied_pr_status_are_separate_evidence(self):
        data = self.fixtures()
        result = AUDIT.audit("example/app", data.__getitem__, "example/shared", 7)
        self.assertEqual(result["shared_workflow_pins"], ["a" * 40])
        self.assertTrue(result["admin_status_enforcement"])
        self.assertEqual(result["required_contexts_absent_from_supplied_pr"], [])
        self.assertEqual(result["scope"], "adoption-signals-only")
        self.assertNotIn("qualified", result)

    def test_disabled_status_rule_with_populated_names_is_not_enforcement(self):
        data = self.fixtures()
        data["repos/example/app/branch_protections"][0]["enable_status_check"] = False
        result = AUDIT.audit("example/app", data.__getitem__)
        self.assertFalse(result["status_checks_enabled"])
        self.assertFalse(result["admin_status_enforcement"])
        self.assertIsNone(result["required_contexts_absent_from_supplied_pr"])

    def test_null_statuses_and_protection_arrays_are_empty_not_lookup_failures(self):
        data = self.fixtures()
        data["repos/example/app/commits/" + "b" * 40 + "/status"] = {"statuses": None}
        data["repos/example/app/branch_protections"] = None
        result = AUDIT.audit("example/app", data.__getitem__)
        self.assertEqual(result["observed_statuses"], [])
        self.assertFalse(result["status_checks_enabled"])
        self.assertEqual(result["audit_status"], "complete")

    def test_enabled_empty_context_list_is_not_mistaken_for_disabled_enforcement(self):
        data = self.fixtures()
        data["repos/example/app/branch_protections"][0]["status_check_contexts"] = None
        result = AUDIT.audit("example/app", data.__getitem__, pull_request=7)
        self.assertTrue(result["status_checks_enabled"])
        self.assertTrue(result["admin_status_enforcement"])
        self.assertEqual(result["required_contexts"], [])
        self.assertIsNone(result["required_contexts_absent_from_supplied_pr"])

    def test_context_patterns_are_reviewed_instead_of_compared_as_literal_names(self):
        data = self.fixtures()
        data["repos/example/app/branch_protections"][0]["status_check_contexts"] = ["CI / *"]
        result = AUDIT.audit("example/app", data.__getitem__, pull_request=7)
        self.assertEqual(result["required_context_patterns_for_review"], ["CI / *"])
        self.assertIsNone(result["required_contexts_absent_from_supplied_pr"])

    def test_stale_required_name_and_admin_bypass_are_visible(self):
        data = self.fixtures()
        rule = data["repos/example/app/branch_protections"][0]
        rule.update(status_check_contexts=["stale/test"], apply_to_admins=False)
        result = AUDIT.audit("example/app", data.__getitem__, pull_request=7)
        self.assertEqual(result["required_contexts_absent_from_supplied_pr"], ["stale/test"])
        self.assertFalse(result["admin_status_enforcement"])

    def test_unavailable_profile_is_unknown_and_marks_audit_incomplete(self):
        data = self.fixtures()
        del data["repos/example/app/contents/.ci/profile.json?ref=" + "b" * 40]
        result = AUDIT.audit("example/app", data.__getitem__)
        self.assertEqual(result["audit_status"], "incomplete")
        self.assertNotIn("profile", result)

    def test_masking_is_a_review_signal_and_mutable_pin_is_not_immutable(self):
        data = self.fixtures()
        text = "uses: example/shared/.forgejo/workflows/ci-profile.yml@main\nrun: pytest || true\n"
        data["repos/example/app/contents/.forgejo/workflows/ci.yml?ref=" + "b" * 40]["content"] = (
            base64.b64encode(text.encode()).decode()
        )
        result = AUDIT.audit("example/app", data.__getitem__, "example/shared")
        self.assertEqual(result["shared_workflow_pins"], [])
        self.assertEqual(result["failure_masking_review_lines"], [2])

    def test_profile_declarations_cannot_hide_missing_phases_or_empty_commands(self):
        result = AUDIT.profile_signals('{"version":1,"steps":[{"phase":"test","argv":[]}]}')
        self.assertEqual(result["missing_phases"], ["acceptance", "build", "install", "verify"])
        self.assertFalse(result["commands_declared"])

    def test_malformed_profile_is_incomplete_and_bad_source_identity_is_rejected(self):
        data = self.fixtures()
        key = "repos/example/app/contents/.ci/profile.json?ref=" + "b" * 40
        data[key]["content"] = base64.b64encode(b'[{"steps":[]}]').decode()
        self.assertEqual(AUDIT.audit("example/app", data.__getitem__)["audit_status"], "incomplete")
        data["repos/example/app/branches/main"]["commit"]["id"] = "main/../../other"
        with self.assertRaises(AUDIT.LookupFailed):
            AUDIT.audit("example/app", data.__getitem__)

    def test_repository_input_cannot_escape_the_requested_api_scope(self):
        for value in ["../repo", "owner/..", "owner/repo/extra", "owner/repo?token=x"]:
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                AUDIT.repository(value)

    def test_pattern_rules_require_review_instead_of_assuming_server_glob_semantics(self):
        data = self.fixtures()
        data["repos/example/app/branch_protections"][0]["branch_name"] = "ma*"
        result = AUDIT.audit("example/app", data.__getitem__)
        self.assertIsNone(result["status_checks_enabled"])
        self.assertIsNone(result["admin_status_enforcement"])
        self.assertEqual(result["pattern_rules_for_review"], ["ma*"])


if __name__ == "__main__":
    unittest.main()
