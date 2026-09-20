from __future__ import annotations

from typing import Protocol

from soma.foundation.persistence.uow import UnitOfWork


class SpareRequestSubmissionEvidenceValidator(Protocol):
    def validate_indexed_sent_evidence(
        self,
        uow: UnitOfWork,
        *,
        spare_request_id: str,
        spare_request_revision: int,
        evidence_kind: str,
        evidence_id: str,
    ) -> str:
        """Return VALID, STALE, INVALID, or INDETERMINATE without mutating or committing."""


__all__ = ["SpareRequestSubmissionEvidenceValidator"]
