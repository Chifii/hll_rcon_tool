from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from mono_huevo_cases.discord_gateway import (
    DiscordGateway, DiscordGatewayConfig, GatewayDisabled, InvalidInteraction, _ephemeral,
)
from mono_huevo_cases.domain import CaseStatus, IdentityBasis, Platform
from mono_huevo_cases.store import CaseStore


class FakeResponse:
    def __init__(self) -> None:
        self.content = None
        self.ephemeral = None

    async def send_message(self, content: str, *, ephemeral: bool) -> None:
        self.content = content
        self.ephemeral = ephemeral


def fake_interaction(*, guild_id: str | None = "guild-fixture", actor_id: str = "actor-fixture",
                     roles: tuple[str, ...] = ()):
    guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
    user = SimpleNamespace(
        id=actor_id, guild=SimpleNamespace(id=guild_id) if guild_id is not None else None,
        roles=[SimpleNamespace(id=role) for role in roles],
    )
    return SimpleNamespace(guild=guild, user=user, response=FakeResponse())


class DiscordGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = CaseStore(Path(self.temp.name) / "cases.sqlite3")
        self.config = DiscordGatewayConfig(
            guild_id="guild-fixture", owner_discord_id="owner-fixture",
            staff_role_ids=frozenset({"staff-role-fixture"}), enabled=True,
        )
        self.gateway = DiscordGateway.from_store(self.config, self.store)
        self.sanctions = Mock()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_gateway_is_disabled_by_default(self) -> None:
        disabled = DiscordGateway.from_store(
            DiscordGatewayConfig("guild-fixture", "owner-fixture", frozenset()), self.store,
        )
        with self.assertRaises(GatewayDisabled):
            disabled.reportar(
                fake_interaction(), subject_platform="discord", subject_id="subject",
                summary="report", evidence="fixture://evidence",
            )

    def test_wrong_guild_and_dm_are_rejected(self) -> None:
        args = dict(subject_platform="discord", subject_id="subject-fixture",
                    summary="fixture report", evidence="fixture://evidence")
        with self.assertRaises(InvalidInteraction):
            self.gateway.reportar(fake_interaction(guild_id="foreign-guild"), **args)
        with self.assertRaises(InvalidInteraction):
            self.gateway.reportar(fake_interaction(guild_id=None), **args)
        self.assertEqual(self.store.list_cases(), [])

    def test_actor_and_roles_come_from_sdk_objects_and_report_keeps_identity_basis(self) -> None:
        interaction = fake_interaction(actor_id="verified-actor", roles=("staff-role-fixture",))
        case = self.gateway.reportar(
            interaction, subject_platform="steam", subject_id="steam-explicit-fixture",
            summary="fixture report", evidence="fixture://evidence",
        )
        self.assertEqual(case.reporter.value, "verified-actor")
        self.assertEqual(case.reporter.platform, Platform.DISCORD)
        self.assertEqual(case.subject.value, "steam-explicit-fixture")
        self.assertEqual(case.subject.platform, Platform.STEAM)
        self.assertEqual(case.subject_identity_basis, IdentityBasis.REPORTER_SUPPLIED)
        self.assertEqual(case.community_id, "guild-fixture")

    def test_only_reporter_or_staff_can_view_case_status(self) -> None:
        created = self.gateway.reportar(
            fake_interaction(actor_id="reporter-fixture"), subject_platform="discord",
            subject_id="subject-fixture", summary="fixture report", evidence="fixture://evidence",
        )
        self.assertEqual(self.gateway.caso(
            fake_interaction(actor_id="reporter-fixture"), case_id=created.case_id,
        ).case_id, created.case_id)
        self.assertIsNone(self.gateway.caso(
            fake_interaction(actor_id="other-member"), case_id=created.case_id,
        ))
        self.assertEqual(self.gateway.caso(
            fake_interaction(actor_id="staff-fixture", roles=("staff-role-fixture",)),
            case_id=created.case_id,
        ).status, CaseStatus.OPEN)
        self.assertEqual(self.gateway.caso(
            fake_interaction(actor_id="owner-fixture"), case_id=created.case_id,
        ).status, CaseStatus.OPEN)
        with self.assertRaises(InvalidInteraction):
            self.gateway.caso(
                fake_interaction(guild_id="other-guild", actor_id="reporter-fixture"),
                case_id=created.case_id,
            )

    def test_replies_are_ephemeral_and_there_are_no_decision_or_sanction_commands(self) -> None:
        interaction = fake_interaction(actor_id="reporter-fixture")
        created = self.gateway.reportar(
            interaction, subject_platform="discord", subject_id="subject-fixture",
            summary="fixture report", evidence="fixture://evidence",
        )
        asyncio.run(_ephemeral(interaction, f"Case {created.case_id}"))
        self.assertTrue(interaction.response.ephemeral)
        self.assertIn(created.case_id, interaction.response.content)
        self.assertFalse(hasattr(self.gateway, "decide"))
        self.assertFalse(hasattr(self.gateway, "review"))
        self.sanctions.assert_not_called()
        self.assertEqual(self.store.get_case(created.case_id).status, CaseStatus.OPEN)
        self.assertEqual([event["action"] for event in self.store.audit_events()], ["case_created"])

    def test_user_supplied_role_claim_does_not_authorize(self) -> None:
        interaction = fake_interaction(actor_id="member-fixture")
        interaction.role = "owner"
        _, actor = self.gateway._actor(interaction)
        self.assertEqual(actor.role, "member")


if __name__ == "__main__":
    unittest.main()
