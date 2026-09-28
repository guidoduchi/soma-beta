from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure


def verify_objectives_tasks_startup_integrity(reader: Any) -> None:
    """Fail closed when current accepted Objective topology is already corrupt.

    This validator is deliberately read-only. Startup/recovery tooling may
    diagnose the offending Objectives, but ordinary startup must never repair,
    delete, merge, or regroup operational history implicitly.
    """

    row = reader.execute(
        "SELECT a.objective_id,b.objective_id,"
        "a.start_utc,a.end_utc,b.start_utc,b.end_utc "
        "FROM objective_envelope_projection a "
        "JOIN objectives oa ON oa.objective_id=a.objective_id "
        "JOIN objective_envelope_projection b ON b.objective_id>a.objective_id "
        "JOIN objectives ob ON ob.objective_id=b.objective_id "
        "WHERE oa.superseded_by_objective_id IS NULL "
        "AND ob.superseded_by_objective_id IS NULL "
        "AND a.start_utc<b.end_utc AND a.end_utc>b.start_utc "
        "ORDER BY a.start_utc,a.end_utc,a.objective_id,"
        "b.start_utc,b.end_utc,b.objective_id "
        "LIMIT 1"
    ).fetchone()
    if row is None:
        return
    raise IntegrityFailure(
        "current accepted Objective strict-overlap drift detected: "
        f"{row[0]}[{row[2]},{row[3]}) overlaps "
        f"{row[1]}[{row[4]},{row[5]})"
    )


__all__ = ["verify_objectives_tasks_startup_integrity"]
