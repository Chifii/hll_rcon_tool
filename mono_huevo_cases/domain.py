from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4


class CaseStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Platform(StrEnum):
    DISCORD = "discord"
    STEAM = "steam"
    HLL = "hll"


@dataclass(frozen=True)
class Identity:
    """An explicitly sourced identifier; identifiers are never cross-mapped implicitly."""

    platform: Platform
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("identity value must not be empty")


@dataclass(frozen=True)
class Case:
    case_id: str
    origin: str
    reporter: Identity
    subject: Identity
    evidence: tuple[str, ...]
    summary: str
    status: CaseStatus = CaseStatus.OPEN
    decision_by: str | None = None
    decision_note: str | None = None
    created_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        origin: str,
        reporter: Identity,
        subject: Identity,
        evidence: tuple[str, ...],
        summary: str,
    ) -> Case:
        if origin not in {"discord", "hll"}:
            raise ValueError("origin must be discord or hll")
        if not summary.strip():
            raise ValueError("summary must not be empty")
        if not evidence or any(not item.strip() for item in evidence):
            raise ValueError("at least one non-empty evidence item is required")
        return cls(
            case_id=str(uuid4()),
            origin=origin,
            reporter=reporter,
            subject=subject,
            evidence=evidence,
            summary=summary.strip(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["reporter"]["platform"] = self.reporter.platform.value
        record["subject"]["platform"] = self.subject.platform.value
        record["evidence"] = list(self.evidence)
        record["status"] = self.status.value
        return record

    @classmethod
    def from_record(cls, record: dict[str, object]) -> Case:
        reporter = record["reporter"]
        subject = record["subject"]
        assert isinstance(reporter, dict) and isinstance(subject, dict)
        return cls(
            case_id=str(record["case_id"]),
            origin=str(record["origin"]),
            reporter=Identity(Platform(str(reporter["platform"])), str(reporter["value"])),
            subject=Identity(Platform(str(subject["platform"])), str(subject["value"])),
            evidence=tuple(str(item) for item in record["evidence"]),
            summary=str(record["summary"]),
            status=CaseStatus(str(record["status"])),
            decision_by=record["decision_by"] if isinstance(record["decision_by"], str) else None,
            decision_note=record["decision_note"] if isinstance(record["decision_note"], str) else None,
            created_at=str(record["created_at"]),
        )
