from __future__ import annotations

from typing import Any

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_source_projection import (
    AcceptedSrFieldDelta,
    AcceptedSrFieldDeltaSet,
    SrSourceProjectionService,
)


_FIELD_KINDS = {
    "problem_summary": "text",
    "report_date": "instant",
    "customer_contact_label": "text",
    "customer_severity": "controlled",
    "current_handler_label": "text",
    "status": "controlled",
    "customer_org_label": "text",
    "customer_account_code": "text",
    "suspend_planned_end": "instant",
    "suspension_duration": "duration_seconds",
    "last_update": "instant",
}


class FakeSrSourceEvidenceProvider:
    def __init__(self) -> None:
        self.states: dict[str, str] = {}
        self.provenance_state = "YES"
        self.calls: list[tuple[str, str, str, dict[str, object | None]]] = []

    def validate_published_field(
        self,
        uow: UnitOfWork,
        sr_id: str,
        field_key: str,
        source_observation_field_id: str,
        accepted_value: dict[str, object | None],
    ) -> str:
        self.calls.append((sr_id, field_key, source_observation_field_id, accepted_value))
        return self.states.get(source_observation_field_id, "VALID")

    def source_freshness_token(self, uow: UnitOfWork, sr_id: str) -> str:
        return "1" * 64

    def has_accepted_source_provenance(self, uow: UnitOfWork, sr_id: str) -> str:
        return self.provenance_state


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _insert_outer_receipt(uow: UnitOfWork, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?, 'AcceptImportProposal', ?, 'reconciliation_proposal', NULL, 0, NULL, NULL)",
        (command_id, "0" * 64),
    )


def _delta(
    field_key: str,
    value: str | int | None,
    *,
    chronology: int | None,
    evidence_id: str | None = None,
    precedence_basis: str = "source_chronology",
    value_state: str = "usable",
    value_kind: str | None = None,
) -> AcceptedSrFieldDelta:
    return AcceptedSrFieldDelta(
        field_key=field_key,
        value_state=value_state,
        value_kind=_FIELD_KINDS.get(field_key, "text") if value_kind is None else value_kind,
        value=value,
        source_chronology_utc=chronology,
        precedence_basis=precedence_basis,
        source_observation_field_id=new_uuid4() if evidence_id is None else evidence_id,
    )


def _apply(factory, service: SrSourceProjectionService, service_request_id: str, *deltas: AcceptedSrFieldDelta):
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id)
        result = service.apply_accepted_field_deltas(
            uow,
            service_request_id,
            AcceptedSrFieldDeltaSet(accepted_command_id=command_id, deltas=tuple(deltas)),
        )
    return command_id, result


def _official_sr(factory, official_sr_no: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=official_sr_no,
    )


def test_source_projection_fields_advance_independently_and_equal_values_do_not_append(initialized_database) -> None:
    factory = _factory(initialized_database)
    provider = FakeSrSourceEvidenceProvider()
    service = SrSourceProjectionService(provider)
    sr = _official_sr(factory, "10000001")

    _command1, first = _apply(
        factory,
        service,
        sr.service_request_id,
        _delta("problem_summary", "Initial problem", chronology=100),
        _delta("status", "Customer Agreed Suspend", chronology=100),
    )
    assert first.no_change is False
    assert first.projection_revision == 1
    assert first.changed_field_keys == ("problem_summary", "status")

    with ReadSnapshot(factory) as snapshot:
        projection1 = service.current(snapshot.connection, sr.service_request_id)
        assert projection1 is not None
        problem1 = str(projection1["problem_summary_observation_id"])
        status1 = str(projection1["status_observation_id"])
        count1 = snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_source_field_observations WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0]
    assert count1 == 2

    _command2, repeated = _apply(
        factory,
        service,
        sr.service_request_id,
        _delta("problem_summary", "Initial problem", chronology=200),
        _delta("status", "Customer Agreed Suspend", chronology=200),
    )
    assert repeated.no_change is True
    assert repeated.projection_revision == 1
    assert repeated.inserted_observation_ids == ()

    _command3, changed = _apply(
        factory,
        service,
        sr.service_request_id,
        _delta("problem_summary", "Changed problem", chronology=300),
    )
    assert changed.no_change is False
    assert changed.projection_revision == 2
    assert changed.changed_field_keys == ("problem_summary",)

    with ReadSnapshot(factory) as snapshot:
        projection2 = service.current(snapshot.connection, sr.service_request_id)
        assert projection2 is not None
        assert str(projection2["problem_summary_observation_id"]) != problem1
        assert str(projection2["status_observation_id"]) == status1
        assert int(projection2["revision"]) == 2
        count2 = snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_source_field_observations WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0]
    assert count2 == 3
    assert len(provider.calls) == 5


def test_explicit_current_handler_clear_is_persisted_but_other_field_clear_is_rejected(initialized_database) -> None:
    factory = _factory(initialized_database)
    provider = FakeSrSourceEvidenceProvider()
    service = SrSourceProjectionService(provider)
    sr = _official_sr(factory, "10000002")

    _apply(
        factory,
        service,
        sr.service_request_id,
        _delta("current_handler_label", "Handler One", chronology=100),
    )
    _clear_command, cleared = _apply(
        factory,
        service,
        sr.service_request_id,
        _delta(
            "current_handler_label",
            None,
            chronology=200,
            value_state="explicit_clear",
        ),
    )
    assert cleared.projection_revision == 2

    with ReadSnapshot(factory) as snapshot:
        projection = service.current(snapshot.connection, sr.service_request_id)
        assert projection is not None
        row = snapshot.connection.execute(
            "SELECT value_state,text_value,integer_value FROM sr_source_field_observations "
            "WHERE sr_source_field_observation_id=?",
            (projection["current_handler_observation_id"],),
        ).fetchone()
    assert tuple(row) == ("explicit_clear", None, None)

    rejected_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, rejected_command)
            service.apply_accepted_field_deltas(
                uow,
                sr.service_request_id,
                AcceptedSrFieldDeltaSet(
                    accepted_command_id=rejected_command,
                    deltas=(
                        _delta(
                            "problem_summary",
                            None,
                            chronology=300,
                            value_state="explicit_clear",
                        ),
                    ),
                ),
            )
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (rejected_command,),
        ).fetchone() is None


def test_indeterminate_source_evidence_rolls_back_outer_receipt_and_projection(initialized_database) -> None:
    factory = _factory(initialized_database)
    provider = FakeSrSourceEvidenceProvider()
    provider.states["evidence-indeterminate"] = "INDETERMINATE"
    service = SrSourceProjectionService(provider)
    sr = _official_sr(factory, "10000003")
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id)
            service.apply_accepted_field_deltas(
                uow,
                sr.service_request_id,
                AcceptedSrFieldDeltaSet(
                    accepted_command_id=command_id,
                    deltas=(
                        _delta(
                            "problem_summary",
                            "Cannot accept",
                            chronology=100,
                            evidence_id="evidence-indeterminate",
                        ),
                    ),
                ),
            )
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert service.current(snapshot.connection, sr.service_request_id) is None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_source_field_observations WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0


def test_changed_value_requires_newer_chronology_or_reviewed_correction(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = SrSourceProjectionService(FakeSrSourceEvidenceProvider())
    sr = _official_sr(factory, "10000004")

    _apply(factory, service, sr.service_request_id, _delta("problem_summary", "A", chronology=100))
    stale_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, stale_command)
            service.apply_accepted_field_deltas(
                uow,
                sr.service_request_id,
                AcceptedSrFieldDeltaSet(
                    accepted_command_id=stale_command,
                    deltas=(_delta("problem_summary", "B", chronology=100),),
                ),
            )
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"

    _correction_command, corrected = _apply(
        factory,
        service,
        sr.service_request_id,
        _delta(
            "problem_summary",
            "B",
            chronology=None,
            precedence_basis="reviewed_correction",
        ),
    )
    assert corrected.projection_revision == 2
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (stale_command,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_source_field_observations WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 2


def test_terminal_status_kind_change_and_reversal_require_reviewed_correction(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = SrSourceProjectionService(FakeSrSourceEvidenceProvider())
    sr = _official_sr(factory, "10000005")

    _apply(factory, service, sr.service_request_id, _delta("status", "Closed", chronology=100))

    terminal_kind_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, terminal_kind_command)
            service.apply_accepted_field_deltas(
                uow,
                sr.service_request_id,
                AcceptedSrFieldDeltaSet(
                    accepted_command_id=terminal_kind_command,
                    deltas=(_delta("status", "Resolved", chronology=200),),
                ),
            )
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"

    _apply(
        factory,
        service,
        sr.service_request_id,
        _delta("status", "Resolved", chronology=200, precedence_basis="reviewed_correction"),
    )

    reversal_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, reversal_command)
            service.apply_accepted_field_deltas(
                uow,
                sr.service_request_id,
                AcceptedSrFieldDeltaSet(
                    accepted_command_id=reversal_command,
                    deltas=(_delta("status", "Customer Agreed Suspend", chronology=300),),
                ),
            )
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"

    _command, reviewed = _apply(
        factory,
        service,
        sr.service_request_id,
        _delta(
            "status",
            "Customer Agreed Suspend",
            chronology=300,
            precedence_basis="reviewed_correction",
        ),
    )
    assert reviewed.projection_revision == 3


def test_suspension_duration_zero_regression_requires_reviewed_correction(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = SrSourceProjectionService(FakeSrSourceEvidenceProvider())
    sr = _official_sr(factory, "10000006")

    _apply(factory, service, sr.service_request_id, _delta("suspension_duration", 3600, chronology=100))
    regression_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, regression_command)
            service.apply_accepted_field_deltas(
                uow,
                sr.service_request_id,
                AcceptedSrFieldDeltaSet(
                    accepted_command_id=regression_command,
                    deltas=(_delta("suspension_duration", 0, chronology=200),),
                ),
            )
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"

    _command, reviewed = _apply(
        factory,
        service,
        sr.service_request_id,
        _delta(
            "suspension_duration",
            0,
            chronology=200,
            precedence_basis="reviewed_correction",
        ),
    )
    assert reviewed.projection_revision == 2


def test_projection_database_guards_reject_wrong_field_cross_sr_and_observation_rewrite(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = SrSourceProjectionService(FakeSrSourceEvidenceProvider())
    sr_a = _official_sr(factory, "10000007")
    sr_b = _official_sr(factory, "10000008")

    _apply(
        factory,
        service,
        sr_a.service_request_id,
        _delta("problem_summary", "A problem", chronology=100),
        _delta("status", "Customer Agreed Suspend", chronology=100),
    )
    _apply(factory, service, sr_b.service_request_id, _delta("problem_summary", "B problem", chronology=100))

    with ReadSnapshot(factory) as snapshot:
        projection_a = service.current(snapshot.connection, sr_a.service_request_id)
        projection_b = service.current(snapshot.connection, sr_b.service_request_id)
        assert projection_a is not None and projection_b is not None
        a_problem = str(projection_a["problem_summary_observation_id"])
        a_status = str(projection_a["status_observation_id"])
        b_problem = str(projection_b["problem_summary_observation_id"])

    with UnitOfWork(factory) as uow:
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "UPDATE sr_current_source_projection SET problem_summary_observation_id=?,revision=revision+1 "
                "WHERE service_request_id=?",
                (a_status, sr_a.service_request_id),
            )
        assert "SR_SOURCE_PROJECTION_INVALID" in str(excinfo.value)

    with UnitOfWork(factory) as uow:
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "UPDATE sr_current_source_projection SET problem_summary_observation_id=?,revision=revision+1 "
                "WHERE service_request_id=?",
                (b_problem, sr_a.service_request_id),
            )
        assert "SR_SOURCE_PROJECTION_INVALID" in str(excinfo.value)

    with UnitOfWork(factory) as uow:
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "UPDATE sr_source_field_observations SET text_value='rewritten' "
                "WHERE sr_source_field_observation_id=?",
                (a_problem,),
            )
        assert "SR_SOURCE_OBSERVATION_APPEND_ONLY" in str(excinfo.value)

    with ReadSnapshot(factory) as snapshot:
        projection_after = service.current(snapshot.connection, sr_a.service_request_id)
        assert projection_after is not None
        assert str(projection_after["problem_summary_observation_id"]) == a_problem
        assert int(projection_after["revision"]) == 1


def test_structural_registry_rejects_unknown_wrong_kind_duplicate_and_bad_chronology(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = SrSourceProjectionService(FakeSrSourceEvidenceProvider())
    sr = _official_sr(factory, "10000009")

    cases = (
        (_delta("future_field", "x", chronology=100),),
        (_delta("problem_summary", 123, chronology=100, value_kind="text"),),
        (_delta("problem_summary", "x", chronology="bad"),),  # type: ignore[arg-type]
        (
            _delta("problem_summary", "x", chronology=100),
            _delta("problem_summary", "y", chronology=200),
        ),
    )
    for deltas in cases:
        command_id = new_uuid4()
        with pytest.raises(SomaError) as excinfo:
            with UnitOfWork(factory) as uow:
                _insert_outer_receipt(uow, command_id)
                service.apply_accepted_field_deltas(
                    uow,
                    sr.service_request_id,
                    AcceptedSrFieldDeltaSet(accepted_command_id=command_id, deltas=tuple(deltas)),
                )
        assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"
        with ReadSnapshot(factory) as snapshot:
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?",
                (command_id,),
            ).fetchone() is None


def test_source_projection_requires_official_identity_and_existing_outer_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = SrSourceProjectionService(FakeSrSourceEvidenceProvider())
    local_sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    local_command = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, local_command)
            service.apply_accepted_field_deltas(
                uow,
                local_sr.service_request_id,
                AcceptedSrFieldDeltaSet(
                    accepted_command_id=local_command,
                    deltas=(_delta("problem_summary", "source", chronology=100),),
                ),
            )
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"

    official_sr = _official_sr(factory, "10000010")
    missing_receipt_id = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            service.apply_accepted_field_deltas(
                uow,
                official_sr.service_request_id,
                AcceptedSrFieldDeltaSet(
                    accepted_command_id=missing_receipt_id,
                    deltas=(_delta("problem_summary", "source", chronology=100),),
                ),
            )
    assert excinfo.value.code == "PERSISTENCE_FAILURE"


def test_source_provenance_classification_is_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    provider = FakeSrSourceEvidenceProvider()
    service = SrSourceProjectionService(provider)
    sr = _official_sr(factory, "10000011")

    with UnitOfWork(factory) as uow:
        assert service.has_accepted_source_provenance(uow, sr.service_request_id) == "YES"

    provider.provenance_state = "MAYBE"
    with pytest.raises(SomaError) as excinfo:
        with UnitOfWork(factory) as uow:
            service.has_accepted_source_provenance(uow, sr.service_request_id)
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"
