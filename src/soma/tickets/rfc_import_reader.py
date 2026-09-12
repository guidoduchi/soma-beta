from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError

from .rfc_source_projection import RfcSourceProjectionService
from .validation import validate_rfc_no


class RfcImportReader:
    """Bounded read-only LLD-03 adapter consumed by LLD-04 import orchestration."""

    @staticmethod
    def get_by_number(reader: Any, rfc_no: str) -> dict[str, object] | None:
        canonical = validate_rfc_no(rfc_no)
        row = reader.execute(
            "SELECT rfc_id,rfc_no,customer_org_id,local_archive_state,revision "
            "FROM rfcs WHERE rfc_no=?",
            (canonical,),
        ).fetchone()
        if row is None:
            return None
        revision = int(row[4])
        if revision <= 0:
            raise IntegrityFailure("RFC import identity has invalid revision authority")
        return {
            "rfc_id": str(row[0]),
            "rfc_no": str(row[1]),
            "customer_org_id": None if row[2] is None else str(row[2]),
            "local_archive_state": str(row[3]),
            "revision": revision,
        }

    @staticmethod
    def current_source_projection(reader: Any, rfc_id: str) -> dict[str, object] | None:
        if reader.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (rfc_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        return RfcSourceProjectionService._current(reader, rfc_id)

    @staticmethod
    def governing_root(reader: Any, rfc_id: str) -> str:
        if reader.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (rfc_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        rows = reader.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges "
            "WHERE child_rfc_id=? AND edge_state='active' ORDER BY parent_rfc_id",
            (rfc_id,),
        ).fetchall()
        if len(rows) > 1:
            raise IntegrityFailure("RFC has more than one active governing parent")
        return rfc_id if not rows else str(rows[0][0])
