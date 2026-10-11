# Discord gateway (offline milestone)

`mono_huevo_cases.discord_gateway` is an optional `discord.py` slash-command adapter. It has no public HTTP endpoint and does not look up a token, connect, sync commands, or run on import. The runner requires both `enabled: true` in private local configuration and an explicit `--enable` flag. On login, it syncs commands only to the one configured guild. Keep the guild ID, owner Discord ID, and staff role IDs in ignored local configuration. The adapter uses only `/reportar` and `/caso`, with ephemeral replies.

The Gateway adapter is the pilot path. The separate HTTP interaction prototype was discarded; no extra cryptography dependency is needed.

The adapter consumes `interaction.guild`, `interaction.user.id`, the guild member reference, and the member's role objects. It scopes cases to the configured guild. A case reporter or configured staff/owner can view its status; other members receive the same inaccessible/not-found result. Steam values entered for a report are explicitly reporter-supplied and unverified. No Discord-to-Steam link is inferred. No review, decision, VIP, or sanction command is exposed.

`build_discord_client(config, store)` requires the existing `discord.py` dependency and builds the client without logging in. Its login hook syncs only the configured guild. `mono_huevo_cases.discord_gateway_runner` reads a token only after both enable gates pass. This runner is implemented but has not been invoked; no Discord object was created or contacted in this milestone.

## Local setup, when approved

1. Copy `examples/discord-gateway.local.example.json` to `.local-secrets/discord-gateway.json`, replace the placeholders with the intended guild, owner and staff role IDs, set `enabled` to `true`, then run `chmod 600 .local-secrets/discord-gateway.json`.
2. Run `python3 scripts/local_secrets.py set-discord-token` and enter the token into the hidden prompt. This only stores a token supplied by the owner; it does not create a Discord application or bot.
3. Inspect presence without exposing values with `python3 scripts/local_secrets.py check`.
4. When the owner explicitly approves the Discord login and command registration, start with `docker compose -f compose.gateway.local.yaml --profile discord-gateway up --build`. This logs in and syncs the two guild-only commands. No such command has been run.

For the pilot, install with OAuth scopes `bot` and `applications.commands`, zero bot permission bits, and only the non-privileged `GUILDS` intent. Do not request `MESSAGE_CONTENT`, `GUILD_MEMBERS`, or `GUILD_PRESENCES`, and do not grant ban, kick, message-management, or administrator permissions. The client has no sanction action. Discord terms/setup and the exact owner/staff Discord IDs remain pending approval.
