from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json

from .rfc_source_projection import RfcSourceProjectionService
from .validation import validate_rfc_no

_SOURCE_PROJECTION_FIELDS = (
    "summary_text",
    "summary_evidence_id",
    "external_created_at_utc",
    "external_created_evidence_id",
    "creator_text",
    "creator_evidence_id",
    "customer_account_number_text",
    "customer_account_number_evidence_id",
    "customer_account_name_text",
    "customer_account_name_evidence_id",
    "severity_text",
    "severity_evidence_id",
    "status_text",
    "status_class",
    "status_authority",
    "status_evidence_id",
    "terminal_epoch_id",
    "owner_external_id_text",
    "owner_external_id_evidence_id",
    "owner_name_text",
    "owner_name_evidence_id",
    "l1_handler_name_text",
    "l1_handler_name_evidence_id",
    "l2_handler_name_text",
    "l2_handler_name_evidence_id",
    "last_update_utc",
    "last_update_evidence_id",
    "revision",
)
_ARCHIVE_STATES = frozenset({"active", "archived"})


def _request_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be canonical UUIDv4 text")
    return require_uuid4(value)


def _stored_uuid(value: object, *, field: str) -> str:
    try:
        if not isinstance(value, str):
            raise ValidationError(f"stored {field} must be UUID text")
        return require_uuid4(value)
    except ValidationError as exc:
        raise IntegrityFailure(f"stored {field} is not canonical UUIDv4") from exc


def _stored_rfc_no(value: object) -> str:
    try:
        if not isinstance(value, str):
            raise ValidationError("stored RFC No. must be text")
        return validate_rfc_no(value)
    except ValidationError as exc:
        raise IntegrityFailure("stored RFC No. is not canonical") from exc


def _projection_payload(projection: dict[str, object] | None, *, rfc_id: str) -> dict[str, object] | None:
    if projection is None:
        return None
    expected_fields = {"rfc_id", *_SOURCE_PROJECTION_FIELDS}
    if set(projection) != expected_fields:
        raise IntegrityFailure("RFC source projection has the wrong closed authority shape")
    if _stored_uuid(projection.get("rfc_id"), field="RFC source projection owner") != rfc_id:
        raise IntegrityFailure("RFC source projection belongs to another RFC")
    revision = projection.get("revision")
    if type(revision) is not int or revision <= 0:
        raise IntegrityFailure("RFC source projection revision is invalid")
    return {field: projection[field] for field in _SOURCE_PROJECTION_FIELDS}


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
        rfc_id = _stored_uuid(row[0], field="RFC identity")
        stored_no = _stored_rfc_no(row[1])
        if stored_no != canonical:
            raise IntegrityFailure("RFC number lookup resolved conflicting identity authority")
        customer_org_id = None if row[2] is None else _stored_uuid(row[2], field="RFC Customer identity")
        archive_state = str(row[3])
        revision = row[4]
        if archive_state not in _ARCHIVE_STATES or type(revision) is not int or revision <= 0:
            raise IntegrityFailure("RFC import identity has invalid current authority")
        return {
            "rfc_id": rfc_id,
            "rfc_no": stored_no,
            "customer_org_id": customer_org_id,
            "local_archive_state": archive_state,
            "revision": revision,
        }

    @staticmethod
    def current_source_projection(reader: Any, rfc_id: str) -> dict[str, object] | None:
        canonical_rfc_id = _request_uuid(rfc_id, field="rfc_id")
        if reader.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (canonical_rfc_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        projection = RfcSourceProjectionService._current(reader, canonical_rfc_id)
        _projection_payload(projection, rfc_id=canonical_rfc_id)
        return projection

    @staticmethod
    def governing_root(reader: Any, rfc_id: str) -> str:
        canonical_rfc_id = _request_uuid(rfc_id, field="rfc_id")
        if reader.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (canonical_rfc_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        rows = reader.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges "
            "WHERE child_rfc_id=? AND edge_state='active' ORDER BY parent_rfc_id",
            (canonical_rfc_id,),
        ).fetchall()
        if len(rows) > 1:
            raise IntegrityFailure("RFC has more than one active governing parent")
        if not rows:
            return canonical_rfc_id

        parent_id = _stored_uuid(rows[0][0], field="RFC governing parent identity")
        if parent_id == canonical_rfc_id:
            raise IntegrityFailure("RFC hierarchy contains a self-parent edge")
        if reader.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (parent_id,)).fetchone() is None:
            raise IntegrityFailure("RFC governing parent does not exist")
        parent_rows = reader.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges "
            "WHERE child_rfc_id=? AND edge_state='active' ORDER BY parent_rfc_id",
            (parent_id,),
        ).fetchall()
        if parent_rows:
            raise IntegrityFailure("RFC hierarchy exceeds the accepted two-level invariant")
        return parent_id

    @staticmethod
    def current_link_state(reader: Any, sr_id: str, root_rfc_id: str) -> dict[str, object]:
        canonical_sr_id = _request_uuid(sr_id, field="sr_id")
        canonical_root_id = _request_uuid(root_rfc_id, field="root_rfc_id")
        if reader.execute(
            "SELECT 1 FROM service_requests WHERE service_request_id=?",
            (canonical_sr_id,),
        ).fetchone() is None:
            raise SomaError("NOT_FOUND", "Service Request does not exist")
        if reader.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (canonical_root_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        parent_rows = reader.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges "
            "WHERE child_rfc_id=? AND edge_state='active' ORDER BY parent_rfc_id",
            (canonical_root_id,),
        ).fetchall()
        if parent_rows:
            raise IntegrityFailure("RFC import link-state lookup requires a current governing root")

        rows = reader.execute(
            "SELECT sr_rfc_link_id FROM sr_rfc_links "
            "WHERE service_request_id=? AND rfc_id=? AND link_state='active' ORDER BY sr_rfc_link_id",
            (canonical_sr_id, canonical_root_id),
        ).fetchall()
        if len(rows) > 1:
            raise IntegrityFailure("Service Request and root RFC have duplicate active direct links")
        if not rows:
            return {"state": "ABSENT", "sr_rfc_link_id": None}
        return {
            "state": "ACTIVE",
            "sr_rfc_link_id": _stored_uuid(rows[0][0], field="Service Request RFC link identity"),
        }

    @staticmethod
    def source_acceptance_base_token(reader: Any, rfc_id: str) -> str:
        canonical_rfc_id = _request_uuid(rfc_id, field="rfc_id")
        row = reader.execute(
            "SELECT rfc_no FROM rfcs WHERE rfc_id=?",
            (canonical_rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        rfc_no = _stored_rfc_no(row[0])
        projection = RfcSourceProjectionService._current(reader, canonical_rfc_id)
        source_projection = _projection_payload(projection, rfc_id=canonical_rfc_id)
        return sha256_canonical_json(
            {
                "schema": "SOMA_RFC_SOURCE_ACCEPTANCE_BASE_V1",
                "rfc_id": canonical_rfc_id,
                "rfc_no": rfc_no,
                "source_projection": source_projection,
            }
        )
