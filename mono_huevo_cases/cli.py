from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import MockDiscordAdapter, MockHLLAdapter
from .domain import Platform
from .service import CaseService, PermissionDenied
from .store import CaseStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mono Huevo offline report and review prototype")
    parser.add_argument("--settings", default="settings.local.json", help="local roles file; see settings.example.json")
    parser.add_argument("--db", default=".local-data/cases.sqlite3", help="local SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)
    for origin in ("discord", "hll"):
        report = sub.add_parser(f"mock-{origin}-report", help=f"create a synthetic {origin} report")
        report.add_argument("--reporter", required=True, help="synthetic source-platform reporter ID")
        report.add_argument("--subject", required=True, help="synthetic source-platform subject ID")
        report.add_argument("--summary", required=True)
        report.add_argument("--evidence", action="append", required=True, help="repeat for multiple items")
    sub.add_parser("cases", help="list cases")
    for name in ("review", "approve", "reject"):
        command = sub.add_parser(name)
        command.add_argument("case_id")
        command.add_argument("--actor", required=True, help="ID present in the local role configuration")
        if name in {"approve", "reject"}:
            command.add_argument("--note", required=True)
    vip = sub.add_parser("vip-propose", help="record an owner-only VIP proposal")
    vip.add_argument("--actor", required=True)
    vip.add_argument("--platform", choices=[p.value for p in Platform], required=True)
    vip.add_argument("--subject", required=True)
    vip.add_argument("--reason", required=True)
    audit = sub.add_parser("audit", help="show append-only audit records")
    audit.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings_path = Path(args.settings)
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        roles = settings["roles"]
        if not isinstance(roles, dict) or any(role not in {"owner", "operator", "member"} for role in roles.values()):
            raise ValueError("settings.roles must map actor IDs to owner, operator, or member")
        service = CaseService(CaseStore(args.db), roles)
        if args.command.startswith("mock-"):
            if args.command == "mock-discord-report":
                event = MockDiscordAdapter.report(
                    reporter_discord_id=args.reporter, subject_discord_id=args.subject,
                    evidence=tuple(args.evidence), summary=args.summary,
                )
            else:
                event = MockHLLAdapter.report(
                    reporter_steam_id=args.reporter, subject_steam_id=args.subject,
                    evidence=tuple(args.evidence), summary=args.summary,
                )
            result = service.create_case(event).to_record()
        elif args.command == "cases":
            result = [case.to_record() for case in service.store.list_cases()]
        elif args.command == "review":
            result = service.review(args.actor, args.case_id).to_record()
        elif args.command in {"approve", "reject"}:
            result = service.decide(
                args.actor, args.case_id, approve=args.command == "approve", note=args.note,
            ).to_record()
        elif args.command == "vip-propose":
            result = {"proposal_id": service.propose_vip(args.actor, args.platform, args.subject, args.reason),
                      "status": "proposed"}
        else:
            result = service.store.audit_events()[-args.limit:]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, PermissionDenied) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
