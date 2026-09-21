from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json

_STATUS_CLASSES = {
    "Closed": "closed",
    "Resolved": "resolved",
    "Cancelled": "cancelled",
    "Customer Agreed Suspend": "active",
}
_SEVERITY_CLASSES = {
    "Critical": "critical",
    "Major": "major",
    "Minor": "minor",
    "Non-fault inquiry": "non_fault_inquiry",
}


@dataclass(frozen=True, slots=True)
class SlaEvidenceValue:
    sr_source_field_observation_id: str
    source_observation_field_id: str
    value: str | int
    source_chronology_utc: int | None
    precedence_basis: str


@dataclass(frozen=True, slots=True)
class ServiceRequestSlaInput:
    service_request_id: str
    official_sr_no: str | None
    customer_org_id: str | None
    customer_relationship_id: str | None
    source_projection_revision: int
    report_date_utc: int | None
    report_date_evidence_id: str | None
    severity: str | None
    severity_evidence_id: str | None
    status_token: str | None
    status_class: str
    status_evidence_id: str | None
    first_resolved_closed_endpoint_utc: int | None
    endpoint_status_evidence_id: str | None
    suspension_numerator_seconds: int
    suspension_denominator: int
    suspension_evidence_id: str | None
    suspend_planned_end_utc: int | None
    suspend_planned_end_evidence_id: str | None
    input_token: str


@dataclass(frozen=True, slots=True)
class SlaInputPage:
    items: tuple[ServiceRequestSlaInput, ...]
    next_cursor: str | None
    exact_count: int


def _current_relationship(reader: Any, service_request_id: str) -> tuple[str | None, str | None]:
    rows = reader.execute(
        "SELECT sr_customer_relationship_id,customer_org_id FROM sr_customer_relationships "
        "WHERE service_request_id=? AND relationship_state='active'",
        (service_request_id,),
    ).fetchall()
    if len(rows) > 1:
        raise IntegrityFailure("Service Request has multiple active Customer relationships")
    if not rows:
        return None, None
    return require_uuid4(str(rows[0][0])), require_uuid4(str(rows[0][1]))


def _field(
    reader: Any,
    *,
    service_request_id: str,
    observation_id: object,
    expected_field: str,
    expected_kind: str,
) -> SlaEvidenceValue | None:
    if observation_id is None:
        return None
    if not isinstance(observation_id, str):
        raise IntegrityFailure("Service Request SLA projection pointer is not an identity")
    canonical = require_uuid4(observation_id)
    row = reader.execute(
        "SELECT sr_source_field_observation_id,source_observation_field_id,field_key,value_state,value_kind,"
        "text_value,integer_value,source_chronology_utc,precedence_basis "
        "FROM sr_source_field_observations WHERE sr_source_field_observation_id=? AND service_request_id=?",
        (canonical, service_request_id),
    ).fetchone()
    if row is None:
        raise IntegrityFailure("Service Request SLA projection points to missing accepted evidence")
    if str(row[0]) != canonical or str(row[2]) != expected_field or str(row[3]) != "usable":
        raise IntegrityFailure("Service Request SLA projection points to mismatched accepted evidence")
    if str(row[4]) != expected_kind:
        raise IntegrityFailure("Service Request SLA projection value kind is invalid")
    source_evidence_id = require_uuid4(str(row[1]))
    value = row[5] if expected_kind in {"text", "controlled"} else row[6]
    if expected_kind in {"text", "controlled"}:
        if not isinstance(value, str):
            raise IntegrityFailure("Service Request SLA text evidence has no usable value")
    else:
        if type(value) is not int or value < 0:
            raise IntegrityFailure("Service Request SLA integer evidence has no usable value")
    chronology = None if row[7] is None else int(row[7])
    if chronology is not None and chronology < 0:
        raise IntegrityFailure("Service Request SLA source chronology is invalid")
    precedence = str(row[8])
    if precedence not in {"source_chronology", "reviewed_correction"}:
        raise IntegrityFailure("Service Request SLA evidence precedence is invalid")
    return SlaEvidenceValue(
        sr_source_field_observation_id=canonical,
        source_observation_field_id=source_evidence_id,
        value=value,
        source_chronology_utc=chronology,
        precedence_basis=precedence,
    )


def _terminal_endpoint(
    reader: Any,
    *,
    service_request_id: str,
    current_status: SlaEvidenceValue,
) -> tuple[int | None, str | None]:
    if current_status.value not in {"Resolved", "Closed"}:
        return None, None
    current_chronology = current_status.source_chronology_utc
    if current_chronology is None:
        return None, None

    rows = reader.execute(
        "SELECT source_observation_field_id,text_value,source_chronology_utc "
        "FROM sr_source_field_observations "
        "WHERE service_request_id=? AND field_key='status' AND value_state='usable' "
        "AND value_kind='controlled' AND source_chronology_utc IS NOT NULL "
        "AND source_chronology_utc<=? "
        "ORDER BY source_chronology_utc,sr_source_field_observation_id",
        (service_request_id, current_chronology),
    ).fetchall()

    boundary = -1
    for row in rows:
        token = str(row[1])
        chronology = int(row[2])
        if token in {"Customer Agreed Suspend", "Cancelled"}:
            boundary = max(boundary, chronology)

    candidates: list[tuple[int, str]] = []
    for row in rows:
        token = str(row[1])
        chronology = int(row[2])
        if token in {"Resolved", "Closed"} and chronology > boundary:
            candidates.append((chronology, require_uuid4(str(row[0]))))
    if not candidates:
        return None, None
    candidates.sort(key=lambda value: (value[0], value[1].encode("utf-8")))
    return candidates[0]


class ServiceRequestSlaInputReader:
    """LLD-03 typed accepted-state provider consumed by LLD-06 SLA projection."""

    @classmethod
    def get(cls, reader: Any, sr_id: str) -> ServiceRequestSlaInput:
        service_request_id = require_uuid4(sr_id)
        sr = reader.execute(
            "SELECT official_sr_no FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if sr is None:
            raise ValidationError("Service Request does not exist")
        official_sr_no = None if sr[0] is None else str(sr[0])
        relationship_id, customer_org_id = _current_relationship(reader, service_request_id)

        projection = reader.execute(
            "SELECT report_date_observation_id,customer_severity_observation_id,status_observation_id,"
            "suspend_planned_end_observation_id,suspension_duration_observation_id,revision "
            "FROM sr_current_source_projection WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if projection is None:
            source_revision = 0
            report_date = severity = status = planned_end = suspension = None
        else:
            source_revision = int(projection[5])
            if source_revision <= 0:
                raise IntegrityFailure("Service Request source projection revision is invalid")
            report_date = _field(
                reader,
                service_request_id=service_request_id,
                observation_id=projection[0],
                expected_field="report_date",
                expected_kind="instant",
            )
            severity = _field(
                reader,
                service_request_id=service_request_id,
                observation_id=projection[1],
                expected_field="customer_severity",
                expected_kind="controlled",
            )
            status = _field(
                reader,
                service_request_id=service_request_id,
                observation_id=projection[2],
                expected_field="status",
                expected_kind="controlled",
            )
            planned_end = _field(
                reader,
                service_request_id=service_request_id,
                observation_id=projection[3],
                expected_field="suspend_planned_end",
                expected_kind="instant",
            )
            suspension = _field(
                reader,
                service_request_id=service_request_id,
                observation_id=projection[4],
                expected_field="suspension_duration",
                expected_kind="duration_seconds",
            )

        severity_token: str | None = None
        if severity is not None:
            severity_token = _SEVERITY_CLASSES.get(str(severity.value))
            if severity_token is None:
                raise IntegrityFailure("accepted current Service Request severity is outside its closed vocabulary")

        status_token = None if status is None else str(status.value)
        status_class = "active" if status is None else _STATUS_CLASSES.get(status_token)
        if status_class is None:
            raise IntegrityFailure("accepted current Service Request status is outside its closed vocabulary")

        endpoint_utc: int | None = None
        endpoint_evidence_id: str | None = None
        if status is not None and status_class in {"resolved", "closed"}:
            endpoint_utc, endpoint_evidence_id = _terminal_endpoint(
                reader,
                service_request_id=service_request_id,
                current_status=status,
            )

        report_date_utc = None if report_date is None else int(report_date.value)
        planned_end_utc = None if planned_end is None else int(planned_end.value)
        suspension_seconds = 0 if suspension is None else int(suspension.value)

        token = sha256_canonical_json(
            {
                "schema": "SOMA_SERVICE_REQUEST_SLA_INPUT_V1",
                "service_request_id": service_request_id,
                "official_sr_no": official_sr_no,
                "customer_relationship_id": relationship_id,
                "customer_org_id": customer_org_id,
                "source_projection_revision": source_revision,
                "report_date": None
                if report_date is None
                else {
                    "evidence_id": report_date.source_observation_field_id,
                    "value": report_date_utc,
                },
                "severity": None
                if severity is None
                else {
                    "evidence_id": severity.source_observation_field_id,
                    "value": severity_token,
                },
                "status": None
                if status is None
                else {
                    "evidence_id": status.source_observation_field_id,
                    "token": status_token,
                    "class": status_class,
                    "source_chronology_utc": status.source_chronology_utc,
                },
                "first_resolved_closed_endpoint": None
                if endpoint_utc is None
                else {
                    "evidence_id": endpoint_evidence_id,
                    "value": endpoint_utc,
                },
                "suspension": None
                if suspension is None
                else {
                    "evidence_id": suspension.source_observation_field_id,
                    "numerator_seconds": suspension_seconds,
                    "denominator": 1,
                },
                "suspend_planned_end": None
                if planned_end is None
                else {
                    "evidence_id": planned_end.source_observation_field_id,
                    "value": planned_end_utc,
                },
            }
        )
        return ServiceRequestSlaInput(
            service_request_id=service_request_id,
            official_sr_no=official_sr_no,
            customer_org_id=customer_org_id,
            customer_relationship_id=relationship_id,
            source_projection_revision=source_revision,
            report_date_utc=report_date_utc,
            report_date_evidence_id=None if report_date is None else report_date.source_observation_field_id,
            severity=severity_token,
            severity_evidence_id=None if severity is None else severity.source_observation_field_id,
            status_token=status_token,
            status_class=status_class,
            status_evidence_id=None if status is None else status.source_observation_field_id,
            first_resolved_closed_endpoint_utc=endpoint_utc,
            endpoint_status_evidence_id=endpoint_evidence_id,
            suspension_numerator_seconds=suspension_seconds,
            suspension_denominator=1,
            suspension_evidence_id=None if suspension is None else suspension.source_observation_field_id,
            suspend_planned_end_utc=planned_end_utc,
            suspend_planned_end_evidence_id=None
            if planned_end is None
            else planned_end.source_observation_field_id,
            input_token=token,
        )

    @classmethod
    def input_token(cls, reader: Any, sr_id: str) -> str:
        return cls.get(reader, sr_id).input_token

    @classmethod
    def list_report_date_month(
        cls,
        reader: Any,
        month_start_utc: int,
        month_end_utc: int,
        customer_scope: str | None,
        cursor: str | None,
        limit: int,
    ) -> SlaInputPage:
        if (
            type(month_start_utc) is not int
            or type(month_end_utc) is not int
            or month_start_utc < 0
            or month_end_utc <= month_start_utc
        ):
            raise ValidationError("report-date month bounds are invalid")
        if type(limit) is not int or limit < 1 or limit > 500:
            raise ValidationError("SLA input page limit must be between 1 and 500")
        customer_id = None if customer_scope is None else require_uuid4(customer_scope)
        cursor_id = None if cursor is None else require_uuid4(cursor)

        predicates = [
            "o.field_key='report_date'",
            "o.value_state='usable'",
            "o.integer_value>=?",
            "o.integer_value<?",
        ]
        params: list[object] = [month_start_utc, month_end_utc]
        if customer_id is not None:
            predicates.append("cr.customer_org_id=?")
            params.append(customer_id)
        if cursor_id is not None:
            predicates.append("p.service_request_id>?")
            params.append(cursor_id)
        where = " AND ".join(predicates)
        rows = reader.execute(
            "SELECT p.service_request_id FROM sr_current_source_projection p "
            "JOIN sr_source_field_observations o ON o.sr_source_field_observation_id=p.report_date_observation_id "
            "LEFT JOIN sr_customer_relationships cr ON cr.service_request_id=p.service_request_id "
            "AND cr.relationship_state='active' "
            f"WHERE {where} ORDER BY p.service_request_id LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(cls.get(reader, str(row[0])) for row in selected)

        count_predicates = [
            "o.field_key='report_date'",
            "o.value_state='usable'",
            "o.integer_value>=?",
            "o.integer_value<?",
        ]
        count_params: list[object] = [month_start_utc, month_end_utc]
        if customer_id is not None:
            count_predicates.append("cr.customer_org_id=?")
            count_params.append(customer_id)
        exact_count = int(
            reader.execute(
                "SELECT COUNT(*) FROM sr_current_source_projection p "
                "JOIN sr_source_field_observations o ON o.sr_source_field_observation_id=p.report_date_observation_id "
                "LEFT JOIN sr_customer_relationships cr ON cr.service_request_id=p.service_request_id "
                "AND cr.relationship_state='active' "
                f"WHERE {' AND '.join(count_predicates)}",
                tuple(count_params),
            ).fetchone()[0]
        )
        return SlaInputPage(
            items=items,
            next_cursor=str(selected[-1][0]) if has_more and selected else None,
            exact_count=exact_count,
        )


class CustomerAccountCodeEvidenceReader:
    @staticmethod
    def current_customer_account_code(reader: Any, sr_id: str) -> dict[str, object]:
        input_value = ServiceRequestSlaInputReader.get(reader, sr_id)
        row = reader.execute(
            "SELECT o.source_observation_field_id,o.text_value FROM sr_current_source_projection p "
            "JOIN sr_source_field_observations o "
            "ON o.sr_source_field_observation_id=p.customer_account_code_observation_id "
            "WHERE p.service_request_id=?",
            (input_value.service_request_id,),
        ).fetchone()
        if row is None:
            return {"state": "Missing"}
        value = str(row[1])
        from soma.reference.domain.validation import validate_account_code

        _stored, key = validate_account_code(value)
        return {
            "state": "ExactExternalKey",
            "value": value,
            "normalized_key": key,
            "source_observation_field_id": require_uuid4(str(row[0])),
        }

    @staticmethod
    def normalize_account_code(value: str) -> str:
        from soma.reference.domain.validation import validate_account_code

        _stored, key = validate_account_code(value)
        return key


__all__ = [
    "CustomerAccountCodeEvidenceReader",
    "ServiceRequestSlaInput",
    "ServiceRequestSlaInputReader",
    "SlaEvidenceValue",
    "SlaInputPage",
]
