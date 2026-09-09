from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta


_PUBLISHED_RUN_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)
_RFC_STATUS_CLASSES = {
    "Implement": "implement_eligible",
    "Closed": "terminal_closed",
    "Cancelled": "terminal_cancelled",
}


@dataclass(frozen=True, slots=True)
class PublishedRfcSourceField:
    source_observation_field_id: str
    source_observation_id: str
    import_run_id: str
    source_family: str
    entity_kind: str
    canonical_primary_id: str
    canonical_parent_rfc_no: str | None
    source_row_chronology_utc: int | None
    field_key: str
    field_class: str
    value_state: str
    value_kind: str
    normalized_text: str | None
    integer_value: int | None
    field_logical_sha256: str
    run_state: str


class TicketImportRfcSourceEvidenceProvider:
    """LLD-04 provider for exact published Enhanced RFC and provisional WFM RFC-status evidence."""

    @staticmethod
    def _load(reader: Any, source_observation_field_id: str) -> PublishedRfcSourceField | None:
        row = reader.execute(
            "SELECT f.source_observation_field_id,o.source_observation_id,o.import_run_id,o.source_family,o.entity_kind,"
            "o.canonical_primary_id,o.canonical_parent_rfc_no,o.source_row_chronology_utc,f.field_key,f.field_class,"
            "f.value_state,f.value_kind,f.normalized_text,f.integer_value,f.field_logical_sha256,r.run_state,r.source_family,"
            "o.identity_state FROM source_observation_fields f "
            "JOIN source_observations o ON o.source_observation_id=f.source_observation_id "
            "JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE f.source_observation_field_id=?",
            (source_observation_field_id,),
        ).fetchone()
        if (
            row is None
            or str(row[17]) != "valid"
            or str(row[15]) not in _PUBLISHED_RUN_STATES
            or str(row[16]) != str(row[3])
        ):
            return None
        source_family = str(row[3])
        entity_kind = str(row[4])
        if source_family == "rfc_enhanced":
            if entity_kind != "rfc" or row[5] is None:
                return None
        elif source_family == "wfm_service_provider":
            if entity_kind != "wfm" or row[5] is None or row[6] is None:
                return None
        else:
            return None
        return PublishedRfcSourceField(
            source_observation_field_id=str(row[0]),
            source_observation_id=str(row[1]),
            import_run_id=str(row[2]),
            source_family=source_family,
            entity_kind=entity_kind,
            canonical_primary_id=str(row[5]),
            canonical_parent_rfc_no=None if row[6] is None else str(row[6]),
            source_row_chronology_utc=None if row[7] is None else int(row[7]),
            field_key=str(row[8]),
            field_class=str(row[9]),
            value_state=str(row[10]),
            value_kind=str(row[11]),
            normalized_text=None if row[12] is None else str(row[12]),
            integer_value=None if row[13] is None else int(row[13]),
            field_logical_sha256=str(row[14]),
            run_state=str(row[15]),
        )

    @staticmethod
    def _rfc_no(reader: Any, rfc_id: str) -> str:
        row = reader.execute("SELECT rfc_no FROM rfcs WHERE rfc_id=?", (rfc_id,)).fetchone()
        if row is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC target no longer exists")
        return str(row[0])

    @staticmethod
    def _mapped_field(field: PublishedRfcSourceField) -> tuple[str, str] | None:
        if field.source_family == "rfc_enhanced":
            return field.field_key, "enhanced_rfc"
        if field.source_family == "wfm_service_provider" and field.field_key == "rfc_status":
            return "status", "wfm_provisional"
        return None

    @staticmethod
    def _value_matches(field: PublishedRfcSourceField, delta: RfcAcceptedFieldDelta) -> bool:
        if field.value_state != "usable" or field.value_kind != delta.value_kind:
            return False
        if field.value_kind in {"text", "controlled"}:
            return field.normalized_text == delta.value
        if field.value_kind == "instant":
            return field.integer_value == delta.value
        return False

    def validate_accepted_delta(
        self,
        uow: UnitOfWork,
        rfc_id: str,
        delta: RfcAcceptedFieldDelta,
        evidence_id: str,
    ) -> str:
        if evidence_id != delta.evidence_id:
            return "INVALID"
        field = self._load(uow.connection, evidence_id)
        if field is None or field.field_class != "active":
            return "INVALID"
        rfc_no = self._rfc_no(uow.connection, rfc_id)
        mapped = self._mapped_field(field)
        if mapped is None:
            return "INVALID"
        mapped_field_key, expected_authority = mapped
        if mapped_field_key != delta.field_key:
            return "INVALID"
        if field.source_family == "rfc_enhanced":
            if field.canonical_primary_id != rfc_no:
                return "INVALID"
        else:
            if field.canonical_parent_rfc_no != rfc_no:
                return "INVALID"
        if not self._value_matches(field, delta):
            return "INVALID"
        if delta.field_key == "status":
            if (
                field.value_kind != "controlled"
                or field.normalized_text not in _RFC_STATUS_CLASSES
                or delta.status_class != _RFC_STATUS_CLASSES[field.normalized_text]
                or delta.status_authority != expected_authority
            ):
                return "INVALID"
        elif delta.status_class is not None or delta.status_authority is not None:
            return "INVALID"
        return "VALID"

    def build_source_projection_delta(
        self,
        reader: Any,
        *,
        rfc_id: str,
        expected_import_run_id: str,
        expected_source_observation_id: str,
        source_observation_field_id: str,
        expected_field_key: str,
    ) -> RfcAcceptedFieldDelta:
        field = self._load(reader, source_observation_field_id)
        if field is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal RFC source field is no longer exact published evidence")
        if field.import_run_id != expected_import_run_id or field.source_observation_id != expected_source_observation_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal RFC source field no longer belongs to the exact published evidence")
        if field.field_class != "active" or field.value_state != "usable":
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal RFC source field is not usable active evidence")
        mapped = self._mapped_field(field)
        if mapped is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "source field has no RFC current-projection authority")
        mapped_field_key, authority = mapped
        if mapped_field_key != expected_field_key:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal RFC source field key changed")
        rfc_no = self._rfc_no(reader, rfc_id)
        if field.source_family == "rfc_enhanced":
            if field.canonical_primary_id != rfc_no:
                raise SomaError("IMPORT_PROPOSAL_STALE", "proposal RFC source field belongs to another RFC")
        elif field.canonical_parent_rfc_no != rfc_no:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal WFM RFC-status field belongs to another RFC")

        if field.value_kind in {"text", "controlled"}:
            if field.normalized_text is None:
                raise SomaError("IMPORT_PROPOSAL_STALE", "published RFC text evidence is missing its normalized value")
            value: str | int = field.normalized_text
        elif field.value_kind == "instant":
            if field.integer_value is None:
                raise SomaError("IMPORT_PROPOSAL_STALE", "published RFC instant evidence is missing its integer value")
            value = field.integer_value
        else:
            raise SomaError("IMPORT_PROPOSAL_STALE", "published RFC evidence uses an unsupported current-projection value kind")

        status_class: str | None = None
        status_authority: str | None = None
        if mapped_field_key == "status":
            if field.normalized_text not in _RFC_STATUS_CLASSES:
                raise SomaError("IMPORT_PROPOSAL_STALE", "unrecognized RFC Status has no accepted current lifecycle authority")
            status_class = _RFC_STATUS_CLASSES[field.normalized_text]
            status_authority = authority
        return RfcAcceptedFieldDelta(
            field_key=mapped_field_key,
            value_kind=field.value_kind,
            value=value,
            evidence_id=field.source_observation_field_id,
            status_class=status_class,
            status_authority=status_authority,
        )

    def source_freshness_token(self, uow: UnitOfWork, rfc_id: str) -> str:
        rfc_no = self._rfc_no(uow.connection, rfc_id)
        rows = uow.connection.execute(
            "SELECT o.source_family,f.source_observation_field_id,f.field_logical_sha256,o.source_row_chronology_utc "
            "FROM source_observation_fields f "
            "JOIN source_observations o ON o.source_observation_id=f.source_observation_id "
            "JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.identity_state='valid' AND r.source_family=o.source_family AND r.run_state IN "
            "('staged','waiting_review','recovery_required','partially_accepted','accepted','rejected') AND "
            "((o.source_family='rfc_enhanced' AND o.entity_kind='rfc' AND o.canonical_primary_id=?) OR "
            "(o.source_family='wfm_service_provider' AND o.entity_kind='wfm' AND o.canonical_parent_rfc_no=? "
            "AND f.field_key='rfc_status')) "
            "ORDER BY o.source_family ASC,f.source_observation_field_id ASC",
            (rfc_no, rfc_no),
        ).fetchall()
        return sha256_canonical_json(
            {
                "schema": "RFC_SOURCE_FRESHNESS_V1",
                "rfc_id": rfc_id,
                "rfc_no": rfc_no,
                "fields": [
                    {
                        "source_family": str(row[0]),
                        "field_id": str(row[1]),
                        "logical_sha256": str(row[2]),
                        "row_chronology_utc": None if row[3] is None else int(row[3]),
                    }
                    for row in rows
                ],
            }
        )

    def has_accepted_source_provenance(self, uow: UnitOfWork, rfc_id: str) -> str:
        rfc_no = self._rfc_no(uow.connection, rfc_id)
        row = uow.connection.execute(
            "SELECT 1 FROM source_observations o JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.identity_state='valid' AND r.source_family=o.source_family AND r.run_state IN "
            "('staged','waiting_review','recovery_required','partially_accepted','accepted','rejected') AND "
            "((o.source_family='rfc_enhanced' AND o.entity_kind='rfc' AND o.canonical_primary_id=?) OR "
            "(o.source_family='wfm_service_provider' AND o.entity_kind='wfm' AND o.canonical_parent_rfc_no=?)) LIMIT 1",
            (rfc_no, rfc_no),
        ).fetchone()
        return "YES" if row is not None else "NO"
