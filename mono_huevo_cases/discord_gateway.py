"""Optional discord.py gateway for private case commands.

Importing this module works without discord.py. It does not connect, read tokens,
sync commands with Discord, or expose an HTTP endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapters import ReportEvent
from .domain import Case, Identity, IdentityBasis, Platform
from .service import CaseService
from .store import CaseStore


class GatewayDisabled(RuntimeError):
    pass


class InvalidInteraction(ValueError):
    pass


@dataclass(frozen=True)
class DiscordGatewayConfig:
    """Local-only guild and role allowlist; IDs are strings, never hardcoded here."""

    guild_id: str
    owner_discord_id: str
    staff_role_ids: frozenset[str]
    enabled: bool = False


@dataclass(frozen=True)
class GatewayActor:
    discord_id: str
    role: str


class DiscordGateway:
    """Testable boundary that derives authorization only from SDK Interaction objects."""

    def __init__(self, config: DiscordGatewayConfig, service: CaseService):
        self.config = config
        self.service = service

    @classmethod
    def from_store(cls, config: DiscordGatewayConfig, store: CaseStore) -> DiscordGateway:
        return cls(config, CaseService(store, {}))

    def _actor(self, interaction: Any) -> tuple[str, GatewayActor]:
        if not self.config.enabled:
            raise GatewayDisabled("Discord gateway is disabled")
        guild = getattr(interaction, "guild", None)
        user = getattr(interaction, "user", None)
        guild_id = getattr(guild, "id", None)
        actor_id = getattr(user, "id", None)
        if guild is None or guild_id is None or str(guild_id) != self.config.guild_id:
            raise InvalidInteraction("command is only available in the configured guild")
        if user is None or actor_id is None:
            raise InvalidInteraction("guild member identity is required")
        member_guild = getattr(user, "guild", None)
        if member_guild is None or str(getattr(member_guild, "id", "")) != self.config.guild_id:
            raise InvalidInteraction("trusted guild member data is required")
        raw_roles = getattr(user, "roles", None)
        if raw_roles is None:
            raise InvalidInteraction("trusted guild roles are required")
        role_ids = {
            str(role_id) for role in raw_roles
            if (role_id := getattr(role, "id", None)) is not None
        }
        actor_id = str(actor_id)
        if actor_id == self.config.owner_discord_id:
            role = "owner"
        elif role_ids & self.config.staff_role_ids:
            role = "operator"
        else:
            role = "member"
        return str(guild_id), GatewayActor(actor_id, role)

    def reportar(
        self, interaction: Any, *, subject_platform: str, subject_id: str,
        summary: str, evidence: str,
    ) -> Case:
        guild_id, actor = self._actor(interaction)
        platform = Platform(subject_platform)
        if platform not in {Platform.DISCORD, Platform.STEAM}:
            raise ValueError("subject platform must be discord or steam")
        event = ReportEvent(
            origin="discord",
            reporter=Identity(Platform.DISCORD, actor.discord_id),
            subject=Identity(platform, subject_id.strip()),
            evidence=(evidence.strip(),),
            summary=summary.strip(),
            subject_identity_basis=(
                IdentityBasis.DISCORD_NATIVE if platform is Platform.DISCORD
                else IdentityBasis.REPORTER_SUPPLIED
            ),
        )
        return self.service.create_case(event, community_id=guild_id)

    def caso(self, interaction: Any, *, case_id: str) -> Case | None:
        guild_id, actor = self._actor(interaction)
        case = self.service.store.get_case(case_id.strip())
        if case is None or case.community_id != guild_id:
            return None
        is_staff = actor.role in {"owner", "operator"}
        is_reporter = (
            case.reporter.platform is Platform.DISCORD
            and case.reporter.value == actor.discord_id
        )
        return case if (is_staff or is_reporter) else None

async def _ephemeral(interaction: Any, content: str) -> None:
    response = getattr(interaction, "response", None)
    send_message = getattr(response, "send_message", None)
    if send_message is None:
        raise InvalidInteraction("interaction response is unavailable")
    await send_message(content[:1900], ephemeral=True)


def build_discord_client(config: DiscordGatewayConfig, store: CaseStore) -> Any:
    """Build a client without logging in; login syncs only configured guild commands."""
    if not config.enabled:
        raise GatewayDisabled("Discord gateway is disabled")
    try:
        import discord
        from discord import app_commands
    except ImportError as error:
        raise RuntimeError("discord.py is required to build the Discord client") from error

    guild = discord.Object(id=int(config.guild_id))
    gateway = DiscordGateway.from_store(config, store)
    intents = discord.Intents.none()
    intents.guilds = True
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    async def setup_hook() -> None:
        # discord.py calls setup_hook only after an explicit login. This is the
        # sole registration path: no global command sync and no import side effect.
        await tree.sync(guild=guild)

    client.setup_hook = setup_hook

    @tree.command(name="reportar", description="Enviar un reporte para revisión humana", guild=guild)
    @app_commands.describe(
        subject_platform="Plataforma de la identidad reportada",
        subject_id="ID de Discord o Steam indicado explícitamente",
        summary="Resumen del reporte",
        evidence="URL o referencia de evidencia",
    )
    @app_commands.choices(subject_platform=[
        app_commands.Choice(name="Discord", value="discord"),
        app_commands.Choice(name="Steam (no verificado)", value="steam"),
    ])
    async def reportar(
        interaction: discord.Interaction, subject_platform: app_commands.Choice[str],
        subject_id: str, summary: str, evidence: str,
    ) -> None:
        try:
            case = gateway.reportar(
                interaction, subject_platform=subject_platform.value, subject_id=subject_id,
                summary=summary, evidence=evidence,
            )
            message = f"Reporte guardado como {case.case_id}. Queda pendiente de revisión humana."
        except (InvalidInteraction, ValueError, GatewayDisabled):
            message = "No se pudo guardar el reporte. Revisa el servidor y los datos enviados."
        await _ephemeral(interaction, message)

    @tree.command(name="caso", description="Ver el estado de un caso autorizado", guild=guild)
    @app_commands.describe(case_id="Identificador del caso")
    async def caso(interaction: discord.Interaction, case_id: str) -> None:
        try:
            record = gateway.caso(interaction, case_id=case_id)
            message = (
                f"Caso {record.case_id}: {record.status.value}."
                if record is not None else "Caso no encontrado o sin acceso."
            )
        except (InvalidInteraction, ValueError, GatewayDisabled):
            message = "Caso no encontrado o sin acceso."
        await _ephemeral(interaction, message)

    return client
