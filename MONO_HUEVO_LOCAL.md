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

## Discord pilot permissions

The pilot uses `/reportar` and `/caso` guild-scoped commands. Install with `bot` plus `applications.commands` OAuth scopes and a zero-permission bot role. It does not post to channels. Keep `Ban Members`, `Kick Members`, `Manage Messages`, and `Administrator` disabled.

The Gateway pilot uses only the non-privileged `GUILDS` intent; do not enable `MESSAGE_CONTENT`, `GUILD_MEMBERS`, or `GUILD_PRESENCES`. The slash-command adapter and a gated runner are implemented, but no bot application, guild installation, terms acceptance, or token setup has occurred. See Discord's [Application Commands](https://docs.discord.com/developers/interactions/application-commands) and [Gateway intents](https://docs.discord.com/developers/events/gateway) docs.

## Local to Beelink

The source is portable and the runtime needs Python 3.12+ (matching upstream); current Mac Python 3.13.5 is compatible. For a Beelink move, stop the process, transfer the ignored config/token and SQLite data over a secure channel, check filesystem permissions, and start with a backup. Local credential entry uses hidden prompts and 0600 files outside Git.

The offline gateway is explicitly gated and not started. To prepare local config only after the Discord setup decision, copy `examples/discord-gateway.local.example.json` to `.local-secrets/discord-gateway.json`, edit it, then `chmod 600` the file. `python3 scripts/local_secrets.py set-discord-token` stores a supplied token using a hidden prompt; `python3 scripts/local_secrets.py check` reports presence only. The runner requires both `enabled: true` and `--enable` and syncs only guild-scoped commands upon login.

## Docker on this Mac

`docker-compose.local.base.yaml` is the v12.3.0 one-server template rooted at the repository directory. Combine it with `docker-compose.dev.yml` and `docker-compose.local.yaml`. The local override pins every published port to loopback (`8780`, `8781`, `55432`, `56380`) and sets restart policies to `no`. The standalone gateway profile in `compose.gateway.local.yaml` exposes no ports and has restart disabled.

Earlier in this task, a standalone Redis test was bound to `127.0.0.1:56379`; the full CRCON stack therefore publishes its Redis at `127.0.0.1:56380`. This avoids stopping or reconfiguring that existing container.

The local initializer generates `HLL_DB_PASSWORD` and `RCONWEB_API_SECRET` with Python's system CSPRNG into ignored `.env` (mode 0600). It sets `DONT_SEED_ADMIN_USER=1` to prevent upstream's insecure `admin/admin` account. The game endpoint is deliberately `127.0.0.1:1` with a non-real placeholder password, so no remote HLL service is contacted. `scripts/local_secrets.py create-crcon-admin` prompts for your username and password twice with hidden password input, then sends it over stdin to a local one-off Django command; it does not store the password. The upstream entrypoint's environment dump and shell tracing were removed to keep runtime secrets out of logs. Discord login, terms, app installation, and token remain unapproved/unconfigured.

Build succeeded, but the first CRCON backend start is blocked: upstream runs `remove_orphaned_map_ids` during startup and immediately calls live RCON `GetClientReferenceData`. With the intentionally disconnected `127.0.0.1:1` target it exits with `ConnectionRefusedError` before its healthcheck. Postgres, Redis and migrations were healthy. This upstream has no disconnected startup mode. I stopped the partial CRCON stack after recording this, preserving its ignored local DB/log data; no game server was contacted. The server's HLLServer executable and real RCON password are still unavailable. The admin input command must wait until the backend has a usable HLL RCON endpoint.

After `.env` has been initialized, the local CRCON start command is:

```sh
docker compose -f docker-compose.local.base.yaml -f docker-compose.dev.yml -f docker-compose.local.yaml up --build -d
```

The override binds web, stats, Postgres, and Redis only to `127.0.0.1` and disables automatic restarts. Wait for `maintenance`, `backend_1`, and `frontend_1` health before running `python3 scripts/local_secrets.py create-crcon-admin`. No game-server RCON password is configured, and the server cannot be reached through this dummy loopback target.
