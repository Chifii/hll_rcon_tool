from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .adapters import ReportEvent
from .domain import Case, CaseStatus, IdentityBasis, Platform
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

    def create_case(self, event: ReportEvent, community_id: str | None = None) -> Case:
        case = Case.create(
            origin=event.origin, reporter=event.reporter, subject=event.subject,
            evidence=event.evidence, summary=event.summary,
            subject_identity_basis=event.subject_identity_basis,
            community_id=community_id,
        )
        self.store.create_case_with_audit(
            case, actor=case.reporter.value, at=datetime.now(timezone.utc).isoformat(),
            details={"origin": case.origin, "subject_identity_basis": case.subject_identity_basis.value},
        )
        return case

    def review(self, actor: str, case_id: str, community_id: str | None = None) -> Case:
        self._require(actor, "owner", "operator")
        case = self._get(case_id, community_id)
        if case.status is not CaseStatus.OPEN:
            raise ValueError("only open cases can enter review")
        updated = Case(**{**case.__dict__, "status": CaseStatus.IN_REVIEW})
        return self.store.transition_case_with_audit(
            case, updated, actor=actor, action="case_review_started",
            at=datetime.now(timezone.utc).isoformat(), details={},
        )

    def decide(self, actor: str, case_id: str, *, approve: bool, note: str, community_id: str | None = None) -> Case:
        self._require(actor, "owner", "operator")
        if not note.strip():
            raise ValueError("decision note is required")
        case = self._get(case_id, community_id)
        if case.status is not CaseStatus.IN_REVIEW:
            raise ValueError("only cases in review can be decided")
        status = CaseStatus.APPROVED if approve else CaseStatus.REJECTED
        updated = Case(**{
            **case.__dict__, "status": status, "decision_by": actor, "decision_note": note.strip()
        })
        updated = self.store.transition_case_with_audit(
            case, updated, actor=actor, action="case_decided",
            at=datetime.now(timezone.utc).isoformat(), details={"status": status.value, "note": note.strip()},
        )
        # Deliberately no RCON, ban, kick, or other sanction adapter is called here.
        return updated

    def propose_vip(
        self, actor: str, subject_platform: str, subject_id: str, reason: str,
        community_id: str | None = None,
    ) -> str:
        self._require(actor, "owner")
        try:
            platform = Platform(subject_platform)
        except (TypeError, ValueError) as error:
            raise ValueError("unsupported VIP identity platform") from error
        if platform is not Platform.STEAM:
            raise ValueError("VIP proposals require an explicit Steam identity")
        if (
            not isinstance(subject_id, str) or not subject_id.strip()
            or not isinstance(reason, str) or not reason.strip()
        ):
            raise ValueError("VIP subject and reason are required")
        proposal_id = str(uuid4())
        proposal = {
            "proposal_id": proposal_id,
            "subject_platform": platform.value,
            "subject_id": subject_id,
            "identity_basis": IdentityBasis.OWNER_SUPPLIED.value,
            "proposed_by": actor,
            "reason": reason.strip(),
            "status": "proposed",
        }
        self.store.create_vip_proposal_with_audit(
            proposal, at=datetime.now(timezone.utc).isoformat(), community_id=community_id,
        )
        return proposal_id

    def _get(self, case_id: str, community_id: str | None = None) -> Case:
        case = self.store.get_case(case_id)
        if case is None or (community_id is not None and case.community_id != community_id):
            raise ValueError(f"unknown case {case_id}")
        return case
