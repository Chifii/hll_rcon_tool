from __future__ import annotations

from dataclasses import dataclass

from .domain import Identity, IdentityBasis, Platform


@dataclass(frozen=True)
class ReportEvent:
    origin: str
    reporter: Identity
    subject: Identity
    evidence: tuple[str, ...]
    summary: str
    subject_identity_basis: IdentityBasis


class MockDiscordAdapter:
    """Maps a synthetic Discord report. Discord IDs are not interpreted as Steam IDs."""

    @staticmethod
    def report(
        *, reporter_discord_id: str, subject_discord_id: str, evidence: tuple[str, ...], summary: str
    ) -> ReportEvent:
        return ReportEvent(
            origin="discord",
            reporter=Identity(Platform.DISCORD, reporter_discord_id),
            subject=Identity(Platform.DISCORD, subject_discord_id),
            evidence=evidence,
            summary=summary,
            subject_identity_basis=IdentityBasis.DISCORD_NATIVE,
        )


class MockHLLAdapter:
    """Maps a synthetic HLL event using the Steam identifier supplied by HLL."""

    @staticmethod
    def report(
        *, reporter_steam_id: str, subject_steam_id: str, evidence: tuple[str, ...], summary: str
    ) -> ReportEvent:
        return ReportEvent(
            origin="hll",
            reporter=Identity(Platform.STEAM, reporter_steam_id),
            subject=Identity(Platform.STEAM, subject_steam_id),
            evidence=evidence,
            summary=summary,
            subject_identity_basis=IdentityBasis.HLL_NATIVE,
        )
