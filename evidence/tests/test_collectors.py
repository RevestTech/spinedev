"""Collector tests — uses ``rows=`` injection seam (no DB)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from evidence.collectors.approval import APPROVAL_ACTIONS, collect_approvals
from evidence.collectors.audit_chain import (
    DEFAULT_ACTION_TYPE_MAP, collect_audit_chain,
)
from evidence.collectors.deploy import DEPLOY_ACTIONS, collect_deploys
from evidence.collectors.role_decision import (
    ROLE_DECISION_ACTIONS, collect_role_decisions,
)
from evidence.collectors.vault_access import (
    VAULT_ACTIONS, collect_vault_access,
)


_TS = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)


def _audit_row(**over):
    base = {
        "event_uuid": "11111111-1111-1111-1111-111111111111",
        "ts": _TS.isoformat(),
        "role": "engineer",
        "actor": "engineer",
        "action": "verify_audit",
        "subsystem": "verify",
        "subject_type": "build_artifact",
        "subject_id": "art-1",
        "rationale": "ok",
        "metadata": {"framework": "SOC2", "control_id": "CC6.1"},
        "content_hash": "a" * 64,
        "phase": "verify_in_progress",
    }
    base.update(over)
    return base


class AuditChainTests(unittest.TestCase):
    def test_maps_action_to_evidence_type(self):
        rows = [_audit_row(action="approval_granted")]
        out = collect_audit_chain(framework="SOC2", control_id="CC6.1",
                                  rows=rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].evidence_type, "access_review")
        self.assertEqual(out[0].framework, "SOC2")
        self.assertEqual(out[0].source_audit_record_id,
                         "11111111-1111-1111-1111-111111111111")

    def test_unknown_action_defaults_to_scan_result(self):
        rows = [_audit_row(action="some_brand_new_action")]
        out = collect_audit_chain(framework="SOC2", control_id="CC6.1", rows=rows)
        self.assertEqual(out[0].evidence_type, "scan_result")

    def test_empty_rows_yields_empty_list(self):
        out = collect_audit_chain(framework="SOC2", control_id="CC6.1", rows=[])
        self.assertEqual(out, [])

    def test_action_map_contains_all_expected_actions(self):
        for action in ("verify_audit", "approval_granted", "llm_call"):
            self.assertIn(action, DEFAULT_ACTION_TYPE_MAP)


class RoleDecisionTests(unittest.TestCase):
    def test_emits_one_payload_per_row(self):
        rows = [_audit_row(action="gate_check"), _audit_row(action="phase_advanced")]
        out = collect_role_decisions(framework="SOC2", control_id="CC6.1", rows=rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].evidence_type, "access_review")
        self.assertEqual(out[0].body["decision_action"], "gate_check")

    def test_role_decision_actions_includes_approval(self):
        self.assertIn("approval_granted", ROLE_DECISION_ACTIONS)
        self.assertIn("gate_check", ROLE_DECISION_ACTIONS)


class VaultAccessTests(unittest.TestCase):
    def test_vault_action_payload(self):
        rows = [_audit_row(action="vault_read",
                           subsystem="shared",
                           metadata={"path": "evidence/vanta/api_key",
                                     "adapter": "vault"})]
        out = collect_vault_access(framework="SOC2", control_id="CC6.1", rows=rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].body["vault_action"], "vault_read")
        self.assertEqual(out[0].body["vault_path"], "evidence/vanta/api_key")
        self.assertEqual(out[0].body["adapter"], "vault")
        self.assertEqual(out[0].body["outcome"], "ok")

    def test_denied_outcome(self):
        rows = [_audit_row(action="vault_denied", subsystem="shared",
                           metadata={"path": "secret/x"})]
        out = collect_vault_access(framework="SOC2", control_id="CC6.1", rows=rows)
        self.assertEqual(out[0].body["outcome"], "denied")

    def test_vault_actions_taxonomy(self):
        for verb in ("vault_read", "vault_write", "vault_delete",
                     "vault_denied", "vault_list"):
            self.assertIn(verb, VAULT_ACTIONS)


class DeployTests(unittest.TestCase):
    def test_deploy_payload(self):
        rows = [{
            "action_id": "aaa-bbb",
            "ts": _TS.isoformat(),
            "action": "deploy",
            "payload_jsonb": {"image": "spine:1.0"},
            "actor_user_id": "user-1",
            "audit_anchor_hex": "deadbeef" * 8,
            "plane_name": "deploy",
            "project_id": 42,
        }]
        out = collect_deploys(framework="SOC2", control_id="CC8.1", rows=rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].evidence_type, "config_snapshot")
        self.assertEqual(out[0].body["deploy_action"], "deploy")
        self.assertEqual(out[0].body["plane_name"], "deploy")
        # The audit_anchor_hex doubles as the source_audit_record_id since
        # action_log rows reference the audit row by hash anchor.
        self.assertEqual(out[0].source_audit_record_id, "deadbeef" * 8)

    def test_deploy_actions(self):
        self.assertIn("deploy", DEPLOY_ACTIONS)
        self.assertIn("rollback", DEPLOY_ACTIONS)


class ApprovalTests(unittest.TestCase):
    def test_approval_payload(self):
        rows = [_audit_row(action="approval_granted",
                           role="approver", actor="kkash")]
        out = collect_approvals(framework="SOC2", control_id="CC1.4", rows=rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].body["approval_action"], "approval_granted")
        self.assertEqual(out[0].body["approver_actor"], "kkash")
        self.assertEqual(out[0].evidence_type, "access_review")

    def test_approval_actions(self):
        for verb in ("approval_granted", "approval_revoked",
                     "emergency_override_granted"):
            self.assertIn(verb, APPROVAL_ACTIONS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
