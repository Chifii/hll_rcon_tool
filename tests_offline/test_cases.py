from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mono_huevo_cases.adapters import MockDiscordAdapter, MockHLLAdapter
from mono_huevo_cases.domain import CaseStatus, IdentityBasis, Platform
from mono_huevo_cases.service import CaseService, PermissionDenied
from mono_huevo_cases.store import CaseStore


class CaseWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = CaseStore(Path(self.temp.name) / "cases.sqlite3")
        self.service = CaseService(self.store, {
            "member-demo": "member", "ops-demo": "operator", "owner-demo": "owner",
        })

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_discord_case_keeps_discord_id_and_requires_explicit_steam_link(self) -> None:
        event = MockDiscordAdapter.report(
            reporter_discord_id="discord-101", subject_discord_id="discord-202",
            evidence=("message://demo/42",), summary="Test report",
        )
        case = self.service.create_case(event)
        self.assertEqual(case.origin, "discord")
        self.assertEqual(case.subject.platform, Platform.DISCORD)
        self.assertEqual(case.subject.value, "discord-202")
        self.assertNotEqual(case.subject.value, "steam-202")
        self.assertEqual(case.subject_identity_basis, IdentityBasis.DISCORD_NATIVE)

    def test_hll_adapter_preserves_steam_identity_and_evidence(self) -> None:
        case = self.service.create_case(MockHLLAdapter.report(
            reporter_steam_id="steam-demo-1", subject_steam_id="steam-demo-2",
            evidence=("match-log://sample/1",), summary="Synthetic HLL event",
        ))
        self.assertEqual(case.origin, "hll")
        self.assertEqual(case.subject.platform, Platform.STEAM)
        self.assertEqual(case.subject_identity_basis, IdentityBasis.HLL_NATIVE)
        self.assertEqual(case.evidence, ("match-log://sample/1",))

    def test_member_cannot_review_or_approve_and_no_decision_is_written(self) -> None:
        case = self.service.create_case(MockHLLAdapter.report(
            reporter_steam_id="steam-demo-1", subject_steam_id="steam-demo-2",
            evidence=("fixture",), summary="fixture",
        ))
        with self.assertRaises(PermissionDenied):
            self.service.review("member-demo", case.case_id)
        with self.assertRaises(PermissionDenied):
            self.service.decide("member-demo", case.case_id, approve=True, note="No")
        self.assertEqual(self.store.get_case(case.case_id).status, CaseStatus.OPEN)

    def test_operator_review_and_human_decision_are_audited_without_sanction(self) -> None:
        case = self.service.create_case(MockDiscordAdapter.report(
            reporter_discord_id="discord-101", subject_discord_id="discord-202",
            evidence=("attachment://synthetic/evidence",), summary="fixture",
        ))
        self.service.review("ops-demo", case.case_id)
        decided = self.service.decide("ops-demo", case.case_id, approve=True, note="Reviewed by a human")
        self.assertEqual(decided.status, CaseStatus.APPROVED)
        self.assertEqual(decided.decision_by, "ops-demo")
        actions = [event["action"] for event in self.store.audit_events()]
        self.assertEqual(actions, ["case_created", "case_review_started", "case_decided"])
        self.assertNotIn("sanction_executed", actions)

    def test_vip_proposals_are_owner_only_and_only_recorded(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.service.propose_vip("ops-demo", "steam", "steam-demo-3", "test")
        proposal_id = self.service.propose_vip("owner-demo", "steam", "steam-demo-3", "manual review")
        event = self.store.audit_events()[0]
        self.assertTrue(proposal_id)
        self.assertEqual(event["action"], "vip_proposed")
        self.assertEqual(event["details"]["status"], "proposed")
        self.assertEqual(event["details"]["identity_basis"], IdentityBasis.OWNER_SUPPLIED.value)

    def test_discord_case_cannot_claim_steam_is_a_linked_identity(self) -> None:
        from mono_huevo_cases.adapters import ReportEvent
        from mono_huevo_cases.domain import Identity

        event = ReportEvent(
            origin="discord",
            reporter=Identity(Platform.DISCORD, "discord-demo"),
            subject=Identity(Platform.STEAM, "steam-demo"),
            evidence=("fixture",),
            summary="Reported Steam ID, mislabeled as a link",
            subject_identity_basis=IdentityBasis.DISCORD_NATIVE,
        )
        with self.assertRaisesRegex(ValueError, "explicit reporter-supplied"):
            self.service.create_case(event)
        self.assertEqual(self.store.list_cases(), [])

    def test_vip_service_rejects_non_steam_subject_even_for_owner(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit Steam identity"):
            self.service.propose_vip("owner-demo", "discord", "discord-demo", "not a Steam ID")
        with self.assertRaisesRegex(ValueError, "unsupported VIP identity platform"):
            self.service.propose_vip("owner-demo", "not-a-platform", "target-demo", "fixture")

    def test_case_listing_is_scoped_to_community(self) -> None:
        for community in ("community-a", "community-b"):
            self.service.create_case(
                MockHLLAdapter.report(
                    reporter_steam_id="steam-reporter-demo", subject_steam_id="steam-subject-demo",
                    evidence=("fixture",), summary="community fixture",
                ),
                community_id=community,
            )
        self.assertEqual(len(self.store.list_cases(community_id="community-a")), 1)
        self.assertEqual(len(self.store.list_cases(community_id="community-b")), 1)
        self.assertEqual(self.store.list_cases(community_id="other-community"), [])

    def test_approval_requires_review_and_a_nonempty_decision_note(self) -> None:
        case = self.service.create_case(MockHLLAdapter.report(
            reporter_steam_id="steam-demo-1", subject_steam_id="steam-demo-2",
            evidence=("fixture",), summary="fixture",
        ))
        with self.assertRaisesRegex(ValueError, "only cases in review"):
            self.service.decide("ops-demo", case.case_id, approve=True, note="Reviewed")
        self.service.review("owner-demo", case.case_id)
        with self.assertRaisesRegex(ValueError, "decision note is required"):
            self.service.decide("owner-demo", case.case_id, approve=False, note=" ")


if __name__ == "__main__":
    unittest.main()
