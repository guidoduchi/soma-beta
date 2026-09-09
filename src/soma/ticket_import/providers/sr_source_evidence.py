from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.sr_source_projection import AcceptedSrFieldDelta


_PUBLISHED_RUN_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)


@dataclass(frozen=True, slots=True)
class PublishedSrSourceField:
    source_observation_field_id: str
    source_observation_id: str
    import_run_id: str
    canonical_sr_no: str
    source_row_chronology_utc: int | None
    field_key: str
    field_class: str
    value_state: str
    value_kind: str
    normalized_text: str | None
    integer_value: int | None
    field_logical_sha256: str
    run_state: str


class TicketImportSrSourceEvidenceProvider:
    """LLD-04 provider for exact published Advanced Search SR field evidence."""

    @staticmethod
    def _load(reader: Any, source_observation_field_id: str) -> PublishedSrSourceField | None:
        row = reader.execute(
            "SELECT f.source_observation_field_id,o.source_observation_id,o.import_run_id,o.canonical_primary_id,"
            "o.source_row_chronology_utc,f.field_key,f.field_class,f.value_state,f.value_kind,f.normalized_text,"
            "f.integer_value,f.field_logical_sha256,r.run_state,o.source_family,o.entity_kind,o.identity_state,r.source_family "
            "FROM source_observation_fields f "
            "JOIN source_observations o ON o.source_observation_id=f.source_observation_id "
            "JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE f.source_observation_field_id=?",
            (source_observation_field_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            str(row[13]) != "advanced_search_sr"
            or str(row[14]) != "service_request"
            or str(row[15]) != "valid"
            or str(row[16]) != "advanced_search_sr"
        ):
            return None
        if str(row[12]) not in _PUBLISHED_RUN_STATES:
            return None
        if row[3] is None:
            return None
        return PublishedSrSourceField(
            source_observation_field_id=str(row[0]),
            source_observation_id=str(row[1]),
            import_run_id=str(row[2]),
            canonical_sr_no=str(row[3]),
            source_row_chronology_utc=None if row[4] is None else int(row[4]),
            field_key=str(row[5]),
            field_class=str(row[6]),
            value_state=str(row[7]),
            value_kind=str(row[8]),
            normalized_text=None if row[9] is None else str(row[9]),
            integer_value=None if row[10] is None else int(row[10]),
            field_logical_sha256=str(row[11]),
            run_state=str(row[12]),
        )

    @staticmethod
    def _official_sr_no(reader: Any, service_request_id: str) -> str | None:
        row = reader.execute(
            "SELECT official_sr_no FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request target no longer exists")
        return None if row[0] is None else str(row[0])

    def validate_published_field(
        self,
        uow: UnitOfWork,
        sr_id: str,
        field_key: str,
        source_observation_field_id: str,
        accepted_value: dict[str, object | None],
    ) -> str:
        field = self._load(uow.connection, source_observation_field_id)
        if field is None:
            return "INVALID"
        official_sr_no = self._official_sr_no(uow.connection, sr_id)
        if official_sr_no is None or field.canonical_sr_no != official_sr_no:
            return "INVALID"
        if field.field_class != "active" or field.field_key != field_key:
            return "INVALID"
        value_state = accepted_value.get("value_state")
        value_kind = accepted_value.get("value_kind")
        value = accepted_value.get("value")
        chronology = accepted_value.get("source_chronology_utc")
        precedence = accepted_value.get("precedence_basis")
        if value_kind != field.value_kind or precedence not in {"source_chronology", "reviewed_correction"}:
            return "INVALID"
        if chronology != field.source_row_chronology_utc:
            return "INVALID"
        if precedence == "source_chronology" and chronology is None:
            return "INVALID"
        if value_state == "explicit_clear":
            if (
                field.field_key != "current_handler_label"
                or field.value_kind != "text"
                or field.value_state != "blank"
                or value is not None
            ):
                return "INVALID"
            return "VALID"
        if value_state != "usable" or field.value_state != "usable":
            return "INVALID"
        if field.value_kind in {"text", "controlled"}:
            return "VALID" if value == field.normalized_text else "INVALID"
        return "VALID" if value == field.integer_value else "INVALID"

    def build_source_projection_delta(
        self,
        reader: Any,
        *,
        service_request_id: str,
        expected_import_run_id: str,
        expected_source_observation_id: str,
        source_observation_field_id: str,
        field_key: str,
        change_kind: str,
        change_value_kind: str,
        after_text: str | None,
        after_integer: int | None,
        precedence_basis: str = "source_chronology",
    ) -> AcceptedSrFieldDelta:
        field = self._load(reader, source_observation_field_id)
        if field is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal source field is no longer exact published evidence")
        official_sr_no = self._official_sr_no(reader, service_request_id)
        if (
            official_sr_no is None
            or field.canonical_sr_no != official_sr_no
            or field.import_run_id != expected_import_run_id
            or field.source_observation_id != expected_source_observation_id
            or field.field_class != "active"
            or field.field_key != field_key
            or field.value_kind != change_value_kind
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal change no longer binds the exact SR source field")
        if change_kind in {"set", "create"}:
            if field.value_state != "usable":
                raise SomaError("IMPORT_PROPOSAL_STALE", "set/create proposal change does not bind usable source evidence")
            value: str | int | None
            if field.value_kind in {"text", "controlled"}:
                value = field.normalized_text
                if after_text != value or after_integer is not None:
                    raise SomaError("IMPORT_PROPOSAL_STALE", "proposal text change does not match published field evidence")
            else:
                value = field.integer_value
                if after_integer != value or after_text is not None:
                    raise SomaError("IMPORT_PROPOSAL_STALE", "proposal numeric change does not match published field evidence")
            value_state = "usable"
        elif change_kind == "clear":
            if (
                field.field_key != "current_handler_label"
                or field.value_kind != "text"
                or field.value_state != "blank"
                or after_text is not None
                or after_integer is not None
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "clear proposal is not exact Current Handler blank evidence")
            value = None
            value_state = "explicit_clear"
        else:
            raise SomaError("IMPORT_PROPOSAL_STALE", "source projection proposal contains an unsupported change kind")
        if precedence_basis == "source_chronology" and field.source_row_chronology_utc is None:
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "changed source field lacks comparable row chronology and requires a reviewed correction proposal",
            )
        return AcceptedSrFieldDelta(
            field_key=field.field_key,
            value_state=value_state,
            value_kind=field.value_kind,
            value=value,
            source_chronology_utc=field.source_row_chronology_utc,
            precedence_basis=precedence_basis,
            source_observation_field_id=field.source_observation_field_id,
        )

    def source_freshness_token(self, uow: UnitOfWork, sr_id: str) -> str:
        official_sr_no = self._official_sr_no(uow.connection, sr_id)
        if official_sr_no is None:
            return sha256_canonical_json({"schema": "SR_SOURCE_FRESHNESS_V1", "service_request_id": sr_id, "fields": []})
        rows = uow.connection.execute(
            "SELECT f.source_observation_field_id,f.field_logical_sha256,o.source_row_chronology_utc "
            "FROM source_observation_fields f "
            "JOIN source_observations o ON o.source_observation_id=f.source_observation_id "
            "JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.source_family='advanced_search_sr' AND r.source_family=o.source_family "
            "AND o.identity_state='valid' AND o.canonical_primary_id=? "
            "AND r.run_state IN ('staged','waiting_review','recovery_required','partially_accepted','accepted','rejected') "
            "ORDER BY f.source_observation_field_id ASC",
            (official_sr_no,),
        ).fetchall()
        return sha256_canonical_json(
            {
                "schema": "SR_SOURCE_FRESHNESS_V1",
                "service_request_id": sr_id,
                "official_sr_no": official_sr_no,
                "fields": [
                    {
                        "field_id": str(row[0]),
                        "logical_sha256": str(row[1]),
                        "row_chronology_utc": None if row[2] is None else int(row[2]),
                    }
                    for row in rows
                ],
            }
        )

    def has_accepted_source_provenance(self, uow: UnitOfWork, sr_id: str) -> str:
        official_sr_no = self._official_sr_no(uow.connection, sr_id)
        if official_sr_no is None:
            return "NO"
        row = uow.connection.execute(
            "SELECT 1 FROM source_observations o JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.source_family='advanced_search_sr' AND r.source_family=o.source_family "
            "AND o.entity_kind='service_request' AND o.identity_state='valid' "
            "AND o.canonical_primary_id=? AND r.run_state IN "
            "('staged','waiting_review','recovery_required','partially_accepted','accepted','rejected') LIMIT 1",
            (official_sr_no,),
        ).fetchone()
        return "YES" if row is not None else "NO"
