"""Explicitly gated local runner for the private Discord case pilot."""
from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any, Callable

from .discord_gateway import DiscordGatewayConfig, build_discord_client
from .store import CaseStore


def _read_private_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"private config file is missing or invalid: {path}")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PermissionError(f"private config must be mode 0600: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("private config must contain a JSON object")
    return value


def _read_token(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Discord token file is missing or invalid")
    info = path.stat()
    # Compose mounts host-owned files into a container whose UID can differ;
    # enforce private mode and reject symlinks while the host helper enforces owner.
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise PermissionError("Discord token file must have mode 0600")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Discord token file is empty")
    return token


def run_gateway(
    *, config_path: Path = Path(".local-secrets/discord-gateway.json"),
    token_path: Path = Path(".local-secrets/discord-bot-token"),
    data_path: Path = Path(".local-data/cases.sqlite3"),
    enable: bool = False,
    client_factory: Callable[[DiscordGatewayConfig, CaseStore], Any] = build_discord_client,
) -> int:
    """Run only after both private config and the explicit CLI gate enable it."""
    raw = _read_private_json(config_path)
    if raw.get("enabled") is not True or not enable:
        raise PermissionError("gateway requires enabled=true and the explicit --enable flag")
    guild_id = str(raw.get("guild_id", "")).strip()
    owner_id = str(raw.get("owner_discord_id", "")).strip()
    roles = raw.get("staff_role_ids", [])
    if not guild_id.isdecimal() or not owner_id.isdecimal():
        raise ValueError("guild_id and owner_discord_id must be numeric Discord IDs")
    if not isinstance(roles, list) or any(not str(role).isdecimal() for role in roles):
        raise ValueError("staff_role_ids must be a list of numeric Discord IDs")
    config = DiscordGatewayConfig(
        guild_id=guild_id, owner_discord_id=owner_id,
        staff_role_ids=frozenset(str(role) for role in roles), enabled=True,
    )
    token = _read_token(token_path)
    client = client_factory(config, CaseStore(data_path))
    # discord.py runs setup_hook after login; that hook syncs only this guild.
    client.run(token, log_handler=None)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the gated Mono Huevo Discord case pilot")
    parser.add_argument("--enable", action="store_true", help="explicitly enable login and guild command sync")
    parser.add_argument("--config", type=Path, default=Path(".local-secrets/discord-gateway.json"))
    parser.add_argument("--token-file", type=Path, default=Path(".local-secrets/discord-bot-token"))
    parser.add_argument("--data", type=Path, default=Path(".local-data/cases.sqlite3"))
    args = parser.parse_args(argv)
    return run_gateway(
        config_path=args.config, token_path=args.token_file, data_path=args.data,
        enable=args.enable,
    )


if __name__ == "__main__":
    raise SystemExit(main())
