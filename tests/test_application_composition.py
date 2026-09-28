from __future__ import annotations

import pytest

from soma.composition import (
    build_pre_lld08_reference_dependency_registry,
    build_pre_lld08_reference_lifecycle_service,
    build_pre_lld08_startup_reconciler,
)
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.migrations.verification import verify_foundation_schema_readonly
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import ObjectiveExistingTaskIntent
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.reference.application.contact_service import ContactReferenceService
from test_inventory_requester_support_acceptance import _create_request, _factory


def test_pre_lld08_composition_declares_inventory_reference_dependency(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = build_pre_lld08_reference_dependency_registry()

    assert tuple(
        validator.validator_id
        for validator in registry.ordered()
    ) == ("inventory",)

    contacts = ContactReferenceService(factory)
    requester = contacts.create_contact(
        command_id=new_uuid4(),
        name="Composed Archive Requester",
    )
    receiver = contacts.create_contact(
        command_id=new_uuid4(),
        name="Composed Archive Receiver",
    )
    _service, request_id = _create_request(
        factory,
        official_sr="97907777",
        requester_contact_id=requester.contact_id,
        receiver_contact_id=receiver.contact_id,
        bom="COMPOSITION-BOM",
    )

    lifecycle = build_pre_lld08_reference_lifecycle_service(factory)
    with pytest.raises(SomaError) as blocked:
        lifecycle.archive_reference(
            command_id=new_uuid4(),
            target_type="contact",
            target_id=requester.contact_id,
            base_revision=1,
            reason_category="operator_archive",
        )

    assert blocked.value.code == "ARCHIVE_BLOCKED"
    assert "active_spare_request_requester" in str(blocked.value)

    # The failed guard remains atomic: no archive event or state transition can
    # slip through merely because the provider is assembled at composition time.
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT lifecycle_state,revision FROM contacts WHERE contact_id=?",
            (requester.contact_id,),
        ).fetchone()
    assert tuple(row) == ("active", 1)
    assert request_id

def _objective_intent(factory, task_id: str) -> ObjectiveExistingTaskIntent:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT t.revision,c.revision,c.plan_revision_id "
            "FROM tasks t JOIN task_plan_current c ON c.task_id=t.task_id "
            "WHERE t.task_id=?",
            (task_id,),
        ).fetchone()
    assert row is not None
    return ObjectiveExistingTaskIntent(
        task_id=task_id,
        expected_task_revision=int(row[0]),
        expected_plan_revision=int(row[1]),
        expected_plan_revision_id=str(row[2]),
    )


def _create_single_task_objective(factory, *, name: str, start: int, end: int) -> str:
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name=name,
        schedule=AcceptedTaskSchedule(
            start_utc=start,
            end_utc=end,
            scheduling_timezone_iana="America/Guayaquil",
        ),
    )
    intent = _objective_intent(factory, task.task_id)
    preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(intent,),
    )
    assert preview["mode"] == "CREATE"
    return ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    ).objective_id


def test_lld05_f036_startup_reconciler_rejects_preexisting_strict_overlap_drift(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    first = _create_single_task_objective(
        factory,
        name="F036 first",
        start=2_700_000_000,
        end=2_700_003_600,
    )
    second = _create_single_task_objective(
        factory,
        name="F036 exact-touch second",
        start=2_700_003_600,
        end=2_700_007_200,
    )

    with UnitOfWork(factory) as uow:
        trigger_sql = uow.connection.execute(
            "SELECT sql FROM sqlite_schema "
            "WHERE type='trigger' AND name='objective_envelope_update_guard'"
        ).fetchone()
        assert trigger_sql is not None and trigger_sql[0]
        exact_trigger_sql = str(trigger_sql[0])
        uow.connection.execute("DROP TRIGGER objective_envelope_update_guard")
        uow.connection.execute(
            "UPDATE objective_envelope_projection "
            "SET start_utc=?,revision=revision+1 "
            "WHERE objective_id=?",
            (2_700_003_599, second),
        )
        uow.connection.execute(exact_trigger_sql)

    connection = factory.open_authoritative(read_only=False, require_wal=True)
    try:
        assert verify_foundation_schema_readonly(connection) is True
    finally:
        connection.close()

    with ReadSnapshot(factory) as snapshot:
        before = {
            str(row[0]): tuple(row[1:])
            for row in snapshot.connection.execute(
                "SELECT objective_id,start_utc,end_utc,revision,last_command_id "
                "FROM objective_envelope_projection "
                "WHERE objective_id IN (?,?) ORDER BY objective_id",
                (first, second),
            ).fetchall()
        }
        assert int(before[first][0]) < int(before[second][1])
        assert int(before[first][1]) > int(before[second][0])

    reconcile = build_pre_lld08_startup_reconciler(factory)
    with pytest.raises(IntegrityFailure, match="strict-overlap drift"):
        reconcile(new_uuid4(), 2_700_010_000)

    with ReadSnapshot(factory) as snapshot:
        after = {
            str(row[0]): tuple(row[1:])
            for row in snapshot.connection.execute(
                "SELECT objective_id,start_utc,end_utc,revision,last_command_id "
                "FROM objective_envelope_projection "
                "WHERE objective_id IN (?,?) ORDER BY objective_id",
                (first, second),
            ).fetchall()
        }
    assert after == before

