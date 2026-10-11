# Discord gateway (offline milestone)

`mono_huevo_cases.discord_gateway` is an optional `discord.py` slash-command adapter. It has no public HTTP endpoint, does not look up a token, connect, sync commands, or run on import. `DiscordGatewayConfig` is disabled by default; keep the real guild ID, owner Discord ID, and staff role IDs in local configuration only. The adapter uses only `/reportar` and `/caso`, with ephemeral replies.

The Gateway adapter is the planned pilot path. The older Ed25519 HTTP interaction adapter remains disabled and is not used by the pilot.

The adapter consumes `interaction.guild`, `interaction.user.id`, the guild member reference, and the member's role objects. It scopes cases to the configured guild. A case reporter or configured staff/owner can view its status; other members receive the same inaccessible/not-found result. Steam values entered for a report are explicitly reporter-supplied and unverified. No Discord-to-Steam link is inferred. No review, decision, VIP, or sanction command is exposed.

`build_discord_client(config, store)` requires the existing `discord.py` dependency and builds the client without logging in or registering/syncing commands. The caller must deliberately enable the local config and separately decide when to run the client with its token. `CaseService` and `CaseStore` remain the persistence/workflow boundary.
