from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork


_FIELD_SPECS: dict[str, tuple[str, str]] = {
    "problem_summary": ("text", "problem_summary_observation_id"),
    "report_date": ("instant", "report_date_observation_id"),
    "customer_contact_label": ("text", "customer_contact_observation_id"),
    "customer_severity": ("controlled", "customer_severity_observation_id"),
    "current_handler_label": ("text", "current_handler_observation_id"),
    "status": ("controlled", "status_observation_id"),
    "customer_org_label": ("text", "customer_org_observation_id"),
    "customer_account_code": ("text", "customer_account_code_observation_id"),
    "suspend_planned_end": ("instant", "suspend_planned_end_observation_id"),
    "suspension_duration": ("duration_seconds", "suspension_duration_observation_id"),
    "last_update": ("instant", "last_update_observation_id"),
}
_TERMINAL_SR_STATUSES = frozenset({"Closed", "Resolved", "Cancelled"})


class SrSourceEvidenceProvider(Protocol):
    def validate_published_field(
        self,
        uow: UnitOfWork,
        sr_id: str,
        field_key: str,
        source_observation_field_id: str,
        accepted_value: dict[str, object | None],
    ) -> str: ...

    def source_freshness_token(self, uow: UnitOfWork, sr_id: str) -> str: ...

    def has_accepted_source_provenance(self, uow: UnitOfWork, sr_id: str) -> str: ...


@dataclass(frozen=True, slots=True)
class AcceptedSrFieldDelta:
    field_key: str
    value_state: str
    value_kind: str
    value: str | int | None
    source_chronology_utc: int | None
    precedence_basis: str
    source_observation_field_id: str

    def provider_value(self) -> dict[str, object | None]:
        return {
            "value_state": self.value_state,
            "value_kind": self.value_kind,
            "value": self.value,
            "source_chronology_utc": self.source_chronology_utc,
            "precedence_basis": self.precedence_basis,
        }


@dataclass(frozen=True, slots=True)
class AcceptedSrFieldDeltaSet:
    accepted_command_id: str
    deltas: tuple[AcceptedSrFieldDelta, ...]


@dataclass(frozen=True, slots=True)
class SrSourceProjectionApplyResult:
    service_request_id: str
    projection_revision: int | None
    changed_field_keys: tuple[str, ...]
    inserted_observation_ids: tuple[str, ...]
    no_change: bool


@dataclass(frozen=True, slots=True)
class _CurrentObservation:
    observation_id: str
    value_state: str
    value_kind: str
    value: str | int | None
    source_chronology_utc: int | None
    precedence_basis: str


@dataclass(frozen=True, slots=True)
class _PlannedChange:
    delta: AcceptedSrFieldDelta
    projection_column: str
    observation_id: str


def _invalid(message: str) -> SomaError:
    return SomaError("SR_SOURCE_EVIDENCE_INVALID", message)


def _validate_delta_shape(delta: AcceptedSrFieldDelta) -> tuple[str, str]:
    try:
        expected_kind, projection_column = _FIELD_SPECS[delta.field_key]
    except KeyError as exc:
        raise _invalid("source field is not active in the Beta 1.0 Service Request projection") from exc
    if delta.value_kind != expected_kind:
        raise _invalid("source field value kind does not match the closed Service Request field registry")
    if delta.precedence_basis not in {"source_chronology", "reviewed_correction"}:
        raise _invalid("source field precedence basis is invalid")
    if delta.source_chronology_utc is not None and (
        type(delta.source_chronology_utc) is not int or delta.source_chronology_utc < 0
    ):
        raise _invalid("source chronology must be a non-negative integer or null")
    if delta.precedence_basis == "source_chronology" and delta.source_chronology_utc is None:
        raise _invalid("changed source value requires comparable chronology or reviewed correction")
    if not isinstance(delta.source_observation_field_id, str) or not delta.source_observation_field_id:
        raise _invalid("source observation field identity is required")

    if delta.value_state == "explicit_clear":
        if delta.field_key != "current_handler_label" or delta.value_kind != "text" or delta.value is not None:
            raise _invalid("only Current Handler supports an explicit source clear")
    elif delta.value_state == "usable":
        if delta.value_kind in {"text", "controlled"}:
            if not isinstance(delta.value, str):
                raise _invalid("text/controlled source value must be a string")
        elif type(delta.value) is not int:
            raise _invalid("instant/duration source value must be an integer")
    else:
        raise _invalid("only usable values and explicit Current Handler clear may enter accepted projection")
    return expected_kind, projection_column


def _same_value(current: _CurrentObservation, delta: AcceptedSrFieldDelta) -> bool:
    return (
        current.value_state == delta.value_state
        and current.value_kind == delta.value_kind
        and current.value == delta.value
    )


def _current_observation(connection: Any, service_request_id: str, projection_column: str) -> _CurrentObservation | None:
    projection = connection.execute(
        f"SELECT {projection_column} FROM sr_current_source_projection WHERE service_request_id=?",
        (service_request_id,),
    ).fetchone()
    if projection is None or projection[0] is None:
        return None
    observation_id = str(projection[0])
    row = connection.execute(
        "SELECT value_state,value_kind,text_value,integer_value,source_chronology_utc,precedence_basis "
        "FROM sr_source_field_observations WHERE sr_source_field_observation_id=? AND service_request_id=?",
        (observation_id, service_request_id),
    ).fetchone()
    if row is None:
        raise SomaError("PERSISTENCE_FAILURE", "Service Request source projection points to missing observation")
    value = row[2] if row[2] is not None else row[3]
    return _CurrentObservation(
        observation_id=observation_id,
        value_state=str(row[0]),
        value_kind=str(row[1]),
        value=value,
        source_chronology_utc=None if row[4] is None else int(row[4]),
        precedence_basis=str(row[5]),
    )


def _validate_precedence(current: _CurrentObservation | None, delta: AcceptedSrFieldDelta) -> None:
    if current is None or _same_value(current, delta):
        return
    if delta.precedence_basis == "reviewed_correction":
        return
    assert delta.source_chronology_utc is not None
    if current.source_chronology_utc is None or delta.source_chronology_utc <= current.source_chronology_utc:
        raise _invalid("changed source value is not demonstrably newer than current accepted evidence")
    if (
        delta.field_key == "status"
        and current.value_state == "usable"
        and current.value in _TERMINAL_SR_STATUSES
        and delta.value_state == "usable"
        and delta.value != current.value
    ):
        raise _invalid("terminal Service Request status correction or reversal requires reviewed correction")
    if (
        delta.field_key == "suspension_duration"
        and current.value_state == "usable"
        and isinstance(current.value, int)
        and current.value > 0
        and delta.value_state == "usable"
        and delta.value == 0
    ):
        raise _invalid("suspension duration regression requires reviewed correction")


class SrSourceProjectionService:
    """LLD-03 owner of accepted, compact Advanced Search SR source projection state."""

    def __init__(self, evidence_provider: SrSourceEvidenceProvider) -> None:
        self._evidence_provider = evidence_provider

    @staticmethod
    def current(reader: Any, service_request_id: str) -> dict[str, object] | None:
        cursor = reader.execute(
            "SELECT * FROM sr_current_source_projection WHERE service_request_id=?",
            (service_request_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        names = tuple(column[0] for column in cursor.description)
        return {name: value for name, value in zip(names, row, strict=True)}

    def has_accepted_source_provenance(self, uow: UnitOfWork, service_request_id: str) -> str:
        state = self._evidence_provider.has_accepted_source_provenance(uow, service_request_id)
        if state not in {"YES", "NO", "INDETERMINATE"}:
            raise _invalid("source provenance provider returned an invalid classification")
        return state

    def apply_accepted_field_deltas(
        self,
        uow: UnitOfWork,
        service_request_id: str,
        accepted_delta_set: AcceptedSrFieldDeltaSet,
    ) -> SrSourceProjectionApplyResult:
        sr_row = uow.connection.execute(
            "SELECT official_sr_no FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if sr_row is None:
            raise SomaError("NOT_FOUND", "Service Request does not exist")
        if sr_row[0] is None:
            raise _invalid("source projection requires an adopted official Service Request identity")
        receipt = uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (accepted_delta_set.accepted_command_id,),
        ).fetchone()
        if receipt is None:
            raise SomaError("PERSISTENCE_FAILURE", "accepted source projection requires the outer command receipt")

        seen: set[str] = set()
        planned: list[_PlannedChange] = []
        for delta in accepted_delta_set.deltas:
            _expected_kind, projection_column = _validate_delta_shape(delta)
            if delta.field_key in seen:
                raise _invalid("accepted source delta set contains the same field more than once")
            seen.add(delta.field_key)
            provider_state = self._evidence_provider.validate_published_field(
                uow,
                service_request_id,
                delta.field_key,
                delta.source_observation_field_id,
                delta.provider_value(),
            )
            if provider_state != "VALID":
                raise _invalid("accepted source field does not resolve to exact published LLD-04 evidence")
            current = _current_observation(uow.connection, service_request_id, projection_column)
            if current is not None and _same_value(current, delta):
                continue
            _validate_precedence(current, delta)
            planned.append(
                _PlannedChange(
                    delta=delta,
                    projection_column=projection_column,
                    observation_id=new_uuid4(),
                )
            )

        current_projection = self.current(uow.connection, service_request_id)
        current_revision = None if current_projection is None else int(current_projection["revision"])
        if not planned:
            return SrSourceProjectionApplyResult(
                service_request_id=service_request_id,
                projection_revision=current_revision,
                changed_field_keys=(),
                inserted_observation_ids=(),
                no_change=True,
            )

        now = utc_epoch_seconds()
        for change in planned:
            delta = change.delta
            text_value = delta.value if delta.value_kind in {"text", "controlled"} else None
            integer_value = delta.value if delta.value_kind in {"instant", "duration_seconds"} else None
            uow.connection.execute(
                "INSERT INTO sr_source_field_observations("
                "sr_source_field_observation_id,service_request_id,field_key,value_state,value_kind,text_value,integer_value,"
                "source_chronology_utc,precedence_basis,source_observation_field_id,accepted_command_id,recorded_at_utc"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    change.observation_id,
                    service_request_id,
                    delta.field_key,
                    delta.value_state,
                    delta.value_kind,
                    text_value,
                    integer_value,
                    delta.source_chronology_utc,
                    delta.precedence_basis,
                    delta.source_observation_field_id,
                    accepted_delta_set.accepted_command_id,
                    now,
                ),
            )

        assignments = {change.projection_column: change.observation_id for change in planned}
        if current_projection is None:
            columns = ["service_request_id", *assignments.keys(), "revision"]
            placeholders = ",".join("?" for _ in columns)
            values = [service_request_id, *assignments.values(), 1]
            uow.connection.execute(
                f"INSERT INTO sr_current_source_projection({','.join(columns)}) VALUES ({placeholders})",
                values,
            )
            resulting_revision = 1
        else:
            set_clause = ",".join(f"{column}=?" for column in assignments)
            cursor = uow.connection.execute(
                f"UPDATE sr_current_source_projection SET {set_clause},revision=revision+1 "
                "WHERE service_request_id=? AND revision=?",
                [*assignments.values(), service_request_id, current_revision],
            )
            if cursor.rowcount != 1:
                raise _invalid("Service Request source projection changed before accepted deltas were applied")
            resulting_revision = int(current_revision) + 1

        return SrSourceProjectionApplyResult(
            service_request_id=service_request_id,
            projection_revision=resulting_revision,
            changed_field_keys=tuple(sorted(change.delta.field_key for change in planned)),
            inserted_observation_ids=tuple(change.observation_id for change in planned),
            no_change=False,
        )
