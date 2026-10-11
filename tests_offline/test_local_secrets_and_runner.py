from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from mono_huevo_cases.discord_gateway_runner import run_gateway
from scripts.local_secrets import create_crcon_admin, initialize_crcon, presence, save_discord_token


class LocalSecretsTests(unittest.TestCase):
    def test_internal_secrets_are_generated_privately_and_admin_password_is_not_stored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "default.env").write_text(Path("default.env").read_text())
            initialize_crcon(root)
            env_path = root / ".env"
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)
            self.assertIn("HLL_HOST=127.0.0.1", env_path.read_text())
            self.assertIn("HLL_PORT=1", env_path.read_text())
            self.assertIn("DONT_SEED_ADMIN_USER=1", env_path.read_text())
            self.assertIn("HLL_DB_HOST_PORT=5432", env_path.read_text())
            self.assertIn("HLL_REDIS_HOST_PORT=6379", env_path.read_text())
            self.assertEqual(presence(root / ".local-secrets"), {
                "discord_token": False, "crcon_internal_secrets": True,
            })
            run = Mock(return_value=Mock(returncode=0, stdout="administrator-created", stderr=""))
            prompts = iter(("fixture-password", "fixture-password"))
            create_crcon_admin(
                root, prompt_text=lambda _: "fixture-admin",
                prompt_secret=lambda _: next(prompts), run=run,
            )
            args, kwargs = run.call_args
            self.assertNotIn("fixture-password", " ".join(args[0]))
            self.assertEqual(json.loads(kwargs["input"]), {
                "username": "fixture-admin", "password": "fixture-password",
            })
            self.assertFalse((root / ".local-secrets" / "crcon-admin.json").exists())

    def test_hidden_discord_entry_writes_private_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / ".local-secrets"
            save_discord_token(root, prompt_secret=lambda _: "fixture-token-value")
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((root / "discord-bot-token").stat().st_mode), 0o600)
            self.assertEqual(presence(root)["discord_token"], True)

    def test_existing_secret_is_not_overwritten_without_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / ".local-secrets"
            save_discord_token(root, prompt_secret=lambda _: "first-fixture-token")
            with self.assertRaises(FileExistsError):
                save_discord_token(root, prompt_secret=lambda _: "second-fixture-token")
            self.assertEqual((root / "discord-bot-token").read_text().strip(), "first-fixture-token")

    def test_internal_env_will_not_be_replaced_without_explicit_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "default.env").write_text(Path("default.env").read_text())
            initialize_crcon(root)
            with self.assertRaises(FileExistsError):
                initialize_crcon(root)

    def test_admin_password_confirmation_must_match(self):
        run = Mock()
        with tempfile.TemporaryDirectory() as temp:
            prompts = iter(("one", "two"))
            with self.assertRaises(ValueError):
                create_crcon_admin(
                    Path(temp), prompt_text=lambda _: "fixture-admin",
                    prompt_secret=lambda _: next(prompts), run=run,
                )
        run.assert_not_called()


class GatewayRunnerTests(unittest.TestCase):
    def _setup_local(self, root: Path, *, enabled: bool) -> tuple[Path, Path]:
        secret_dir = root / ".local-secrets"
        secret_dir.mkdir(mode=0o700)
        config = secret_dir / "discord-gateway.json"
        config.write_text(json.dumps({
            "enabled": enabled, "guild_id": "123456", "owner_discord_id": "234567",
            "staff_role_ids": ["345678"],
        }))
        config.chmod(0o600)
        token = secret_dir / "discord-bot-token"
        token.write_text("test-only-token-fixture\n")
        token.chmod(0o600)
        return config, token

    def test_runner_requires_both_gates_before_reading_token_or_building_client(self):
        client_factory = Mock()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config, token = self._setup_local(root, enabled=True)
            with self.assertRaises(PermissionError):
                run_gateway(config_path=config, token_path=token, data_path=root / "db.sqlite", client_factory=client_factory)
            self.assertFalse(client_factory.called)
            config.write_text(json.dumps({"enabled": False, "guild_id": "123456"}))
            config.chmod(0o600)
            with self.assertRaises(PermissionError):
                run_gateway(config_path=config, token_path=token, data_path=root / "db.sqlite", enable=True, client_factory=client_factory)
            self.assertFalse(client_factory.called)

    def test_enabled_runner_passes_token_only_to_client_run(self):
        client = Mock()
        client_factory = Mock(return_value=client)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, token_path = self._setup_local(root, enabled=True)
            code = run_gateway(
                config_path=config_path, token_path=token_path, data_path=root / "db.sqlite",
                enable=True, client_factory=client_factory,
            )
            self.assertTrue((root / "db.sqlite").exists())
        self.assertEqual(code, 0)
        client.run.assert_called_once_with("test-only-token-fixture", log_handler=None)
        self.assertTrue(client_factory.call_args.args[0].enabled)
        self.assertEqual(client_factory.call_args.args[0].staff_role_ids, frozenset({"345678"}))

    def test_token_file_must_be_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, token_path = self._setup_local(root, enabled=True)
            token_path.chmod(0o644)
            with self.assertRaises(PermissionError):
                run_gateway(
                    config_path=config_path, token_path=token_path, data_path=root / "db.sqlite",
                    enable=True, client_factory=Mock(),
                )


if __name__ == "__main__":
    unittest.main()
