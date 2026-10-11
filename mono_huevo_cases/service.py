from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .adapters import ReportEvent
from .domain import Case, CaseStatus
from .store import CaseStore


class PermissionDenied(PermissionError):
    pass


class CaseService:
    def __init__(self, store: CaseStore, roles: dict[str, str]):
        self.store = store
        self.roles = roles

    def _require(self, actor: str, *allowed: str) -> None:
        if self.roles.get(actor) not in allowed:
            raise PermissionDenied(f"actor {actor!r} lacks required role")

    def _audit(self, actor: str, action: str, case_id: str | None, details: dict[str, str]) -> None:
        self.store.append_audit(
            at=datetime.now(timezone.utc).isoformat(), actor=actor, action=action,
            case_id=case_id, details=details,
        )

    def create_case(self, event: ReportEvent) -> Case:
        case = Case.create(
            origin=event.origin, reporter=event.reporter, subject=event.subject,
            evidence=event.evidence, summary=event.summary,
        )
        self.store.save_case(case)
        self._audit(case.reporter.value, "case_created", case.case_id, {"origin": case.origin})
        return case

    def review(self, actor: str, case_id: str) -> Case:
        self._require(actor, "owner", "operator")
        case = self._get(case_id)
        if case.status is not CaseStatus.OPEN:
            raise ValueError("only open cases can enter review")
        updated = Case(**{**case.__dict__, "status": CaseStatus.IN_REVIEW})
        self.store.save_case(updated)
        self._audit(actor, "case_review_started", case_id, {})
        return updated

    def decide(self, actor: str, case_id: str, *, approve: bool, note: str) -> Case:
        self._require(actor, "owner", "operator")
        if not note.strip():
            raise ValueError("decision note is required")
        case = self._get(case_id)
        if case.status is not CaseStatus.IN_REVIEW:
            raise ValueError("only cases in review can be decided")
        status = CaseStatus.APPROVED if approve else CaseStatus.REJECTED
        updated = Case(**{
            **case.__dict__, "status": status, "decision_by": actor, "decision_note": note.strip()
        })
        self.store.save_case(updated)
        self._audit(actor, "case_decided", case_id, {"status": status.value, "note": note.strip()})
        # Deliberately no RCON, ban, kick, or other sanction adapter is called here.
        return updated

    def propose_vip(self, actor: str, subject_platform: str, subject_id: str, reason: str) -> str:
        self._require(actor, "owner")
        if not subject_id.strip() or not reason.strip():
            raise ValueError("VIP subject and reason are required")
        proposal_id = str(uuid4())
        proposal = {
            "proposal_id": proposal_id,
            "subject_platform": subject_platform,
            "subject_id": subject_id,
            "proposed_by": actor,
            "reason": reason.strip(),
            "status": "proposed",
        }
        self.store.save_vip_proposal(proposal)
        self._audit(actor, "vip_proposed", None, proposal)
        return proposal_id

    def _get(self, case_id: str) -> Case:
        case = self.store.get_case(case_id)
        if case is None:
            raise ValueError(f"unknown case {case_id}")
        return case
