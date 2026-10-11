from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .domain import Case


class CaseStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    record TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    case_id TEXT,
                    details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vip_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    subject_platform TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    proposed_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                """
            )

    def save_case(self, case: Case) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO cases(case_id, record) VALUES(?, ?)",
                (case.case_id, json.dumps(case.to_record(), ensure_ascii=False)),
            )

    def get_case(self, case_id: str) -> Case | None:
        with self._connect() as db:
            row = db.execute("SELECT record FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return Case.from_record(json.loads(row["record"])) if row else None

    def list_cases(self) -> list[Case]:
        with self._connect() as db:
            rows = db.execute("SELECT record FROM cases ORDER BY rowid").fetchall()
        return [Case.from_record(json.loads(row["record"])) for row in rows]

    def append_audit(self, *, at: str, actor: str, action: str, case_id: str | None, details: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO audit(at, actor, action, case_id, details) VALUES(?, ?, ?, ?, ?)",
                (at, actor, action, case_id, json.dumps(details, ensure_ascii=False, sort_keys=True)),
            )

    def audit_events(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY sequence").fetchall()
        return [
            {"sequence": row["sequence"], "at": row["at"], "actor": row["actor"], "action": row["action"],
             "case_id": row["case_id"], "details": json.loads(row["details"])}
            for row in rows
        ]

    def save_vip_proposal(self, proposal: dict[str, str]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO vip_proposals VALUES(?, ?, ?, ?, ?, ?)",
                (proposal["proposal_id"], proposal["subject_platform"], proposal["subject_id"],
                 proposal["proposed_by"], proposal["reason"], proposal["status"]),
            )
