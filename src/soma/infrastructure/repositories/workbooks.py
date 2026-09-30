from __future__ import annotations

from soma.foundation.errors import SomaError, ValidationError
from soma.infrastructure.repositories.core import get, one, rows


def cleanup_terminal_staging(uow, run_id: str, *, limit: int = 500) -> int:
    """Remove one bounded batch of technical staging in the caller's UnitOfWork."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValidationError("Workbook cleanup limit must be in 1..500")
    run = get(uow, "infrastructure_workbook_runs", run_id)
    if run["state"] not in ("accepted", "rejected", "failed"):
        raise SomaError("WORKBOOK_STALE", "Workbook run is still reviewable")
    if one(uow, "SELECT 1 FROM infrastructure_workbook_proposals "
           "WHERE workbook_run_id=? AND state='pending' LIMIT 1", (run_id,)) is not None:
        raise SomaError("WORKBOOK_STALE", "Workbook has pending proposals")
    batch = rows(
        uow,
        "SELECT staging_row_id FROM infrastructure_workbook_staging_rows "
        "WHERE workbook_run_id=? ORDER BY sheet_kind,row_ordinal LIMIT ?",
        (run_id, limit),
    )
    for item in batch:
        # The migration trigger requires exact durable row-decision evidence.
        # Proposal payloads cascade; run, decision, audit and replay rows do not.
        uow.connection.execute(
            "DELETE FROM infrastructure_workbook_staging_rows WHERE staging_row_id=?",
            (item["staging_row_id"],),
        )
    return len(batch)
