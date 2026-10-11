# Mono Huevo | HLL LATAM: offline case prototype

This small package is kept separate from CRCON's existing moderation and VIP paths. It uses Python's standard library and SQLite. The Discord and HLL inputs are synthetic adapters only. It does not connect to Discord, HLL, CRCON RCON, an AI provider, or a network socket. Case approval records a human decision; it does not ban, kick, or change server state. VIP handling only writes owner proposals to the audit log.

## Run on the Mac

From this directory, copy the example role file to the ignored local config:

```sh
cp settings.example.json settings.local.json
```

Edit only the local role assignments with the operator IDs you intend to test. Do not commit that file. The included IDs are fake examples. No passwords, tokens, Steam IDs from real people, or Discord credentials are included.

Create sample cases and inspect the workflow:

```sh
python3 -m mono_huevo_cases mock-discord-report --reporter discord-user-demo --subject discord-subject-demo --summary "Synthetic Discord report" --evidence "fixture://message/1"
python3 -m mono_huevo_cases mock-hll-report --reporter steam-user-demo --subject steam-subject-demo --summary "Synthetic HLL report" --evidence "fixture://match/1"
python3 -m mono_huevo_cases cases
python3 -m mono_huevo_cases review CASE_ID --actor operator-demo
python3 -m mono_huevo_cases approve CASE_ID --actor operator-demo --note "Human-reviewed fixture"
python3 -m mono_huevo_cases audit
python3 -m mono_huevo_cases vip-propose --actor owner-demo --platform steam --subject steam-subject-demo --reason "Manual owner review"
```

Replace `CASE_ID` with the UUID shown by the report command. The database defaults to `.local-data/cases.sqlite3`; both it and the local roles file are ignored by Git. To use a different file, pass `--db /path/to/cases.sqlite3`.

## Identity and authorization

Each case stores its origin, reporter identity, subject identity, evidence, current state, decision-maker, and decision note. A Discord report remains a Discord identity; an HLL report remains a Steam identity. There is no Discord-to-Steam inference or link flow. A later explicit link flow must be an audited, user-confirmed action before a Discord case may name a Steam player.

The `settings.local.json` role map exists only to exercise offline authorization. It is not production authentication: the eventual Discord adapter must derive actor IDs and roles from verified Discord interaction data and the configured guild, never accept a user-supplied role. Operators can open/review/decide cases; only owners can propose VIP entries. No VIP write-through exists.

AI is not wired in. If introduced later, its output should be a non-binding recommendation stored with provenance; humans remain responsible for every decision.

## Discord permissions to request for a future implementation

For the planned interaction-only flow (`/report`, `/case review`, `/case approve`, `/case reject`, `/vip propose`) use guild-scoped commands for private testing. With Discord's HTTP interaction endpoint, request the `applications.commands` OAuth scope and no guild permission bitfield. If we choose a long-running Gateway bot instead, install it with `bot` plus `applications.commands` and a zero-permission bot role for command interactions. If it must post case summaries into a staff channel, add only `View Channel` and `Send Messages` there, plus `Embed Links` only if the chosen format needs embeds. Keep moderation permissions such as `Ban Members`, `Kick Members`, `Manage Messages`, and `Administrator` disabled.

The interaction-only design needs no Gateway privileged intents. Do not enable `MESSAGE_CONTENT`, `GUILD_MEMBERS`, or `GUILD_PRESENCES`; if a future request changes the design to read ordinary chat messages, revisit that scope explicitly. `GUILDS` is a non-privileged intent and may be used by a Gateway library for guild metadata. See Discord's [Application Commands](https://docs.discord.com/developers/interactions/application-commands) and [Gateway intents](https://docs.discord.com/developers/events/gateway) docs. Actual slash-command adapter, bot application, guild, and tokens are deliberately not created in this step.

## Local to Beelink

The source is portable and the runtime needs only Python 3.11+; current Mac Python 3.13.5 is compatible. Before a Beelink move, stop the process, copy the ignored settings and SQLite database over a secure channel, check filesystem permissions, and start with a backup. Do not copy any credential because this prototype has none. Keep any later Discord token in the host's secret store/environment, outside the repository and command-line arguments.

Docker Compose is installed on this Mac, but the Docker daemon is currently unavailable. The prototype is a one-shot CLI with no service port, so it has no Compose service to expose yet. CRCON's own Compose config is separate and was not started; its server-specific RCON credentials and a running HLL game server are not configured here.
