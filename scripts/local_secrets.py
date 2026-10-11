"""Store local credentials interactively without echoing or printing values."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


def _private_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


def _write_private(path: Path, content: str, *, replace: bool, private_parent: bool = True) -> None:
    if private_parent:
        _private_dir(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FileExistsError(f"{path.name} already exists; use --replace to overwrite it")
    fd, temp_name = tempfile.mkstemp(prefix=".credential-", dir=path.parent)
    temporary = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def save_discord_token(
    root: Path, *, prompt_secret: Callable[[str], str] = getpass.getpass, replace: bool = False,
) -> None:
    token = prompt_secret("Discord bot token (input hidden): ").strip()
    if not token:
        raise ValueError("token cannot be empty")
    _write_private(root / "discord-bot-token", token + "\n", replace=replace)


def initialize_crcon(
    project_root: Path, *, replace: bool = False,
) -> None:
    source = project_root / "default.env"
    destination = project_root / ".env"
    if not source.is_file():
        raise FileNotFoundError("upstream default.env template is missing")
    if destination.exists() and not replace:
        raise FileExistsError(".env already exists; refusing to replace local configuration")
    _private_dir(project_root / ".local-secrets")
    values = {
        "HLL_DB_PASSWORD": secrets.token_hex(32),
        "RCONWEB_API_SECRET": secrets.token_hex(32),
        # The backend requires HLL_HOST, but this fixture points only at its own
        # loopback on an unused port. It cannot reach the remote game server.
        "HLL_HOST": "127.0.0.1",
        "HLL_PORT": "1",
        "HLL_PASSWORD": "NOT-A-REAL-GAME-PASSWORD",
        "DONT_SEED_ADMIN_USER": "1",
        # These are service-to-service ports; the local host mappings are
        # separately pinned in docker-compose.local.yaml.
        "HLL_DB_HOST_PORT": "5432",
        "HLL_REDIS_HOST_PORT": "6379",
        "RCONWEB_PORT": "8780",
        "RCONWEB_PORT_HTTPS": "8782",
        "PUBLIC_STATS_PORT": "8781",
        "PUBLIC_STATS_PORT_HTTPS": "8783",
        "RCONWEB_EXTERNAL_ADDRESS": "localhost",
    }
    lines = source.read_text(encoding="utf-8").splitlines()
    found = set()
    for index, line in enumerate(lines):
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            lines[index] = f"{key}={values[key]}"
            found.add(key)
    missing = set(values) - found
    if missing:
        raise ValueError(f"upstream env template is missing required keys: {', '.join(sorted(missing))}")
    _write_private(destination, "\n".join(lines) + "\n", replace=replace, private_parent=False)


def presence(root: Path) -> dict[str, bool]:
    return {
        "discord_token": _is_private_file(root / "discord-bot-token"),
        "crcon_internal_secrets": _is_private_file(root.parent / ".env"),
    }


def create_crcon_admin(
    project_root: Path, *, prompt_secret: Callable[[str], str] = getpass.getpass,
    prompt_text: Callable[[str], str] = input,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    username = prompt_text("CRCON administrator username: ").strip()
    password = prompt_secret("CRCON administrator password (input hidden): ")
    confirmation = prompt_secret("Confirm CRCON administrator password (input hidden): ")
    if not username or not password or password != confirmation:
        raise ValueError("username/password is empty or the passwords do not match")
    # The static code and command contain no credentials. Password travels only
    # over stdin to a local one-off Compose exec with no TTY and no output echo.
    django_code = (
        "import json, sys; from django.contrib.auth.models import User; "
        "data=json.load(sys.stdin); "
        "User.objects.create_superuser(data['username'], '', data['password']) "
        "if not User.objects.filter(username=data['username']).exists() "
        "else (_ for _ in ()).throw(RuntimeError('username already exists')); "
        "print('administrator-created')"
    )
    command = [
        "docker", "compose",
        "-f", "docker-compose.local.base.yaml",
        "-f", "docker-compose.dev.yml",
        "-f", "docker-compose.local.yaml",
        "exec", "-T", "backend_1", "python", "rconweb/manage.py", "shell", "-c", django_code,
    ]
    result = run(
        command, cwd=project_root, input=json.dumps({"username": username, "password": password}),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        # Do not forward process output: it may contain environment diagnostics.
        raise RuntimeError("CRCON administrator creation failed; no secret values were displayed")


def _is_private_file(path: Path) -> bool:
    return (
        not path.is_symlink() and path.is_file()
        and stat.S_IMODE(path.stat().st_mode) == 0o600
        and path.stat().st_uid == os.getuid()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage local-only credentials using hidden prompts")
    parser.add_argument("action", choices=("set-discord-token", "init-crcon", "create-crcon-admin", "check"))
    parser.add_argument("--replace", action="store_true", help="replace an existing local credential")
    parser.add_argument("--root", type=Path, default=Path(".local-secrets"), help=argparse.SUPPRESS)
    parser.add_argument("--project-root", type=Path, default=Path("."), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.action == "set-discord-token":
        save_discord_token(args.root, replace=args.replace)
        print("Discord token stored locally (value not displayed).")
    elif args.action == "init-crcon":
        initialize_crcon(args.project_root, replace=args.replace)
        print("Local CRCON config and internal secrets created (values not displayed).")
    elif args.action == "create-crcon-admin":
        create_crcon_admin(args.project_root)
        print("CRCON administrator created (password not stored).")
    else:
        for name, present in presence(args.root).items():
            print(f"{name}={'present' if present else 'missing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
