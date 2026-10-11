from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .domain import Case, CaseStatus


class ConcurrentUpdateError(RuntimeError):
    """The case changed after it was read; callers must reload before retrying."""


class CaseStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._session() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    record TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    community_id TEXT,
                    version INTEGER NOT NULL DEFAULT 0
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
                    identity_basis TEXT NOT NULL DEFAULT 'owner_supplied',
                    proposed_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    community_id TEXT
                );
                """
            )
            self._add_column_if_missing(db, "cases", "status", "TEXT NOT NULL DEFAULT 'open'")
            self._add_column_if_missing(db, "cases", "community_id", "TEXT")
            self._add_column_if_missing(db, "cases", "version", "INTEGER NOT NULL DEFAULT 0")
            self._add_column_if_missing(
                db, "vip_proposals", "identity_basis", "TEXT NOT NULL DEFAULT 'owner_supplied'",
            )
            self._add_column_if_missing(db, "vip_proposals", "community_id", "TEXT")
            # Migrate records written by the first offline prototype, which stored
            # status and community only inside its JSON payload.
            rows = db.execute("SELECT case_id, record FROM cases").fetchall()
            for row in rows:
                record = json.loads(row["record"])
                status = str(record.get("status", CaseStatus.OPEN.value))
                community_id = record.get("community_id")
                version = int(record.get("version", 0))
                db.execute(
                    "UPDATE cases SET status = ?, community_id = ?, version = ? WHERE case_id = ?",
                    (status, community_id, version, row["case_id"]),
                )

    @staticmethod
    def _add_column_if_missing(db: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @staticmethod
    def _insert_audit(
        db: sqlite3.Connection, *, at: str, actor: str, action: str,
        case_id: str | None, details: dict[str, Any],
    ) -> None:
        db.execute(
            "INSERT INTO audit(at, actor, action, case_id, details) VALUES(?, ?, ?, ?, ?)",
            (at, actor, action, case_id, json.dumps(details, ensure_ascii=False, sort_keys=True)),
        )

    def create_case_with_audit(
        self, case: Case, *, actor: str, at: str, details: dict[str, Any],
    ) -> None:
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO cases(case_id, record, status, community_id, version) VALUES(?, ?, ?, ?, ?)",
                (case.case_id, json.dumps(case.to_record(), ensure_ascii=False),
                 case.status.value, case.community_id, case.version),
            )
            self._insert_audit(
                db, at=at, actor=actor, action="case_created", case_id=case.case_id, details=details,
            )

    def transition_case_with_audit(
        self, previous: Case, updated: Case, *, actor: str, action: str,
        at: str, details: dict[str, Any],
    ) -> Case:
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status, community_id, version FROM cases WHERE case_id = ?",
                (previous.case_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != previous.status.value
                or row["community_id"] != previous.community_id
                or row["version"] != previous.version
            ):
                raise ConcurrentUpdateError("case changed; reload before deciding")
            saved = Case(**{**updated.__dict__, "version": previous.version + 1})
            cursor = db.execute(
                "UPDATE cases SET record = ?, status = ?, community_id = ?, version = ? "
                "WHERE case_id = ? AND status = ? AND version = ?",
                (json.dumps(saved.to_record(), ensure_ascii=False), saved.status.value,
                 saved.community_id, saved.version, saved.case_id, previous.status.value, previous.version),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdateError("case changed; reload before deciding")
            self._insert_audit(
                db, at=at, actor=actor, action=action, case_id=saved.case_id, details=details,
            )
            return saved

    def create_vip_proposal_with_audit(
        self, proposal: dict[str, str], *, at: str, community_id: str | None,
    ) -> None:
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO vip_proposals(proposal_id, subject_platform, subject_id, identity_basis, "
                "proposed_by, reason, status, community_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (proposal["proposal_id"], proposal["subject_platform"], proposal["subject_id"],
                 proposal["identity_basis"], proposal["proposed_by"], proposal["reason"],
                 proposal["status"], community_id),
            )
            self._insert_audit(
                db, at=at, actor=proposal["proposed_by"], action="vip_proposed", case_id=None,
                details={**proposal, "community_id": community_id or "offline"},
            )

    def get_case(self, case_id: str) -> Case | None:
        with self._session() as db:
            row = db.execute("SELECT record FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return Case.from_record(json.loads(row["record"])) if row else None

    def list_cases(self, community_id: str | None = None) -> list[Case]:
        with self._session() as db:
            if community_id is None:
                rows = db.execute("SELECT record FROM cases ORDER BY rowid").fetchall()
            else:
                rows = db.execute(
                    "SELECT record FROM cases WHERE community_id = ? ORDER BY rowid", (community_id,),
                ).fetchall()
        return [Case.from_record(json.loads(row["record"])) for row in rows]

    def audit_events(self) -> list[dict[str, Any]]:
        with self._session() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY sequence").fetchall()
        return [
            {"sequence": row["sequence"], "at": row["at"], "actor": row["actor"], "action": row["action"],
             "case_id": row["case_id"], "details": json.loads(row["details"])}
            for row in rows
        ]
