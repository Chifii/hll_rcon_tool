from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mono_huevo_cases.adapters import MockHLLAdapter
from mono_huevo_cases.service import CaseService
from mono_huevo_cases.store import CaseStore, ConcurrentUpdateError


class FailingAuditStore(CaseStore):
    fail_action: str | None = None

    def _insert_audit(self, db, *, at, actor, action, case_id, details):
        if action == self.fail_action:
            raise sqlite3.IntegrityError("synthetic audit insert failure")
        return super()._insert_audit(
            db, at=at, actor=actor, action=action, case_id=case_id, details=details,
        )


class BarrierReadStore(CaseStore):
    def __init__(self, path: str | Path, barrier: threading.Barrier):
        self.barrier = barrier
        self.read_count = 0
        self.read_lock = threading.Lock()
        super().__init__(path)

    def get_case(self, case_id):
        case = super().get_case(case_id)
        if case is not None:
            with self.read_lock:
                self.read_count += 1
                should_wait = self.read_count <= 2
            if should_wait:
                self.barrier.wait(timeout=5)
        return case


class CaseStoreTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "cases.sqlite3"
        self.store = FailingAuditStore(self.db_path)
        self.service = CaseService(self.store, {"ops-fixture": "operator", "owner-fixture": "owner"})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_case(self):
        return self.service.create_case(MockHLLAdapter.report(
            reporter_steam_id="steam-reporter-fixture", subject_steam_id="steam-subject-fixture",
            evidence=("fixture://log/1",), summary="Synthetic incident",
        ))

    def test_create_rolls_back_case_when_audit_insert_fails(self) -> None:
        self.store.fail_action = "case_created"
        with self.assertRaises(sqlite3.IntegrityError):
            self.create_case()
        self.assertEqual(self.store.list_cases(), [])
        self.assertEqual(self.store.audit_events(), [])

    def test_review_rolls_back_status_when_audit_insert_fails(self) -> None:
        case = self.create_case()
        self.store.fail_action = "case_review_started"
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.review("ops-fixture", case.case_id)
        self.assertEqual(self.store.get_case(case.case_id).status.value, "open")
        self.assertEqual([e["action"] for e in self.store.audit_events()], ["case_created"])

    def test_decision_rolls_back_status_when_audit_insert_fails(self) -> None:
        case = self.create_case()
        self.service.review("ops-fixture", case.case_id)
        self.store.fail_action = "case_decided"
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.decide("ops-fixture", case.case_id, approve=True, note="Human review")
        self.assertEqual(self.store.get_case(case.case_id).status.value, "in_review")
        self.assertEqual([e["action"] for e in self.store.audit_events()], [
            "case_created", "case_review_started",
        ])

    def test_vip_proposal_rolls_back_when_audit_insert_fails(self) -> None:
        self.store.fail_action = "vip_proposed"
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.propose_vip("owner-fixture", "steam", "steam-target-fixture", "fixture")
        with closing(sqlite3.connect(self.db_path)) as db:
            with db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM vip_proposals").fetchone()[0], 0)
        self.assertEqual(self.store.audit_events(), [])

    def test_only_one_concurrent_review_transition_wins(self) -> None:
        case = self.create_case()
        store = BarrierReadStore(self.db_path, threading.Barrier(2))
        service = CaseService(store, {"ops-fixture": "operator"})

        def review():
            try:
                return service.review("ops-fixture", case.case_id)
            except ConcurrentUpdateError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: review(), range(2)))
        self.assertEqual(sum(not isinstance(result, Exception) for result in results), 1)
        self.assertEqual(sum(isinstance(result, ConcurrentUpdateError) for result in results), 1)
        self.assertEqual(store.get_case(case.case_id).status.value, "in_review")
        self.assertEqual([e["action"] for e in store.audit_events()].count("case_review_started"), 1)

    def test_only_one_concurrent_decision_wins(self) -> None:
        case = self.create_case()
        case = self.service.review("ops-fixture", case.case_id)
        store = BarrierReadStore(self.db_path, threading.Barrier(2))
        service = CaseService(store, {"ops-fixture": "operator"})

        def decide(approve):
            try:
                return service.decide("ops-fixture", case.case_id, approve=approve, note="Human decision")
            except ConcurrentUpdateError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(decide, (True, False)))
        self.assertEqual(sum(not isinstance(result, Exception) for result in results), 1)
        self.assertEqual(sum(isinstance(result, ConcurrentUpdateError) for result in results), 1)
        self.assertIn(self.store.get_case(case.case_id).status.value, {"approved", "rejected"})
        self.assertEqual([e["action"] for e in store.audit_events()].count("case_decided"), 1)


if __name__ == "__main__":
    unittest.main()
