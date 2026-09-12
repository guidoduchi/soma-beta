from __future__ import annotations

import pytest

from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.audit_registry import build_objectives_tasks_audit_registry
from soma.objectives_tasks.services.task_explicit_lock import TaskExplicitLockService
from soma.objectives_tasks.services.wfm_import import (
    WfmCreateOrAdoptFromSourceMutation,
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
    WfmReviewedOperationalPlanMutation,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.tickets.queries.rfc_archive import RfcArchiveQueryService
from soma.tickets.rfc_archive import RfcArchiveService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, suffix: int) -> tuple[str, str]:
    rfc_no = f"NC{suffix:014d}"
    result = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    return result.rfc_id, rfc_no


def _insert_outer_receipt(uow: UnitOfWork, *, command_id: str) -> str:
    proposal_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) "
        "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "a" * 64, proposal_id),
    )
    return proposal_id


def _write_owner_audits(uow: UnitOfWork, events) -> None:
    writer = AuditWriter(build_objectives_tasks_audit_registry())
    for event in events:
        writer.write(uow, event)


def _register_manual_wfm(factory, *, suffix: int):
    rfc_id, _ = _create_rfc(factory, suffix)
    result = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=f"TK{suffix:014d}",
        rfc_id=rfc_id,
    )
    return rfc_id, result


def _source_token(factory, *, task_no: str, task_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, task_id),
        )


def _plan_token(factory, *, task_no: str, task_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_plan_reconciliation", task_no, task_id),
        )


def _apply_active_source_plan(
    factory,
    *,
    task_id: str,
    task_no: str,
    start_utc: int,
    end_utc: int,
) -> tuple[str, str]:
    observation_id = new_uuid4()
    base_token = _source_token(factory, task_no=task_no, task_id=task_id)
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=command_id)
        result = WfmImportMutationParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionAcceptanceMutation(
                task_id=task_id,
                task_no=task_no,
                expected_source_projection_revision=0,
                provider_status_token="Implementation",
                provider_lifecycle_class="active",
                source_plan_start_utc=start_utc,
                source_plan_end_utc=end_utc,
                accepted_source_observation_id=observation_id,
                base_state_token=base_token,
                accepted_command_id=command_id,
            ),
        )
        assert result.source_projection_revision == 1
        assert result.audit_events == ()
    return observation_id, command_id


def test_wfm_import_base_tokens_are_deterministic_and_source_acceptance_ignores_local_lock_churn(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfc_id, registered = _register_manual_wfm(factory, suffix=301)
    task_no = "TK00000000000301"

    with ReadSnapshot(factory) as snapshot:
        target = WfmImportBaseTarget("wfm_source_projection", task_no, registered.task_id)
        first = WfmImportReader.source_acceptance_base_token(snapshot.connection, target)
        second = WfmImportReader.source_acceptance_base_token(snapshot.connection, target)
        assert first == second
        identity = WfmImportReader.get_by_task_no(snapshot.connection, task_no)
        assert identity is not None
        assert identity["current_rfc_id"] == rfc_id

    locked = TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=new_uuid4(),
        task_id=registered.task_id,
        task_revision=registered.revision,
        lock_projection_revision=0,
        lock_kind="plan",
        action="lock",
        reason_category="prove_import_freshness_partition",
    )
    assert locked.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        after = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, registered.task_id),
        )
    assert after == first


def test_plan_reconciliation_token_changes_when_effective_plan_lock_changes(initialized_database) -> None:
    factory = _factory(initialized_database)
    _rfc_id, registered = _register_manual_wfm(factory, suffix=302)
    task_no = "TK00000000000302"
    _apply_active_source_plan(
        factory,
        task_id=registered.task_id,
        task_no=task_no,
        start_utc=2_030_000_000,
        end_utc=2_030_003_600,
    )
    before = _plan_token(factory, task_no=task_no, task_id=registered.task_id)

    locked = TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=new_uuid4(),
        task_id=registered.task_id,
        task_revision=registered.revision,
        lock_projection_revision=0,
        lock_kind="plan",
        action="lock",
        reason_category="invalidate_reviewed_source_plan",
    )
    assert locked.outcome == "APPLIED"
    after = _plan_token(factory, task_no=task_no, task_id=registered.task_id)
    assert after != before


def test_active_source_creation_requires_eligible_rfc_but_terminal_source_may_create_historical_identity(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfc_id, _rfc_no = _create_rfc(factory, 303)
    preview = RfcArchiveQueryService(factory).preview(rfc_id=rfc_id, scope_kind="exact_rfc")
    archived = RfcArchiveService(factory).archive(
        command_id=new_uuid4(),
        rfc_id=rfc_id,
        scope_kind="exact_rfc",
        reviewed_scope_fingerprint=preview.scope_fingerprint,
    )
    assert archived.outcome == "archived"

    active_task_no = "TK00000000000303"
    with ReadSnapshot(factory) as snapshot:
        active_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_create_or_adopt", active_task_no, None),
        )
    active_command = new_uuid4()
    with pytest.raises(SomaError) as caught:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id=active_command)
            WfmImportMutationParticipant.create_or_adopt_wfm_from_source(
                uow,
                WfmCreateOrAdoptFromSourceMutation(
                    task_no=active_task_no,
                    expected_task_id=None,
                    rfc_id=rfc_id,
                    source_lifecycle_class="active",
                    base_state_token=active_token,
                    accepted_command_id=active_command,
                ),
            )
    assert caught.value.code == "WFM_RFC_NOT_ELIGIBLE"

    historical_task_no = "TK00000000001303"
    with ReadSnapshot(factory) as snapshot:
        historical_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_create_or_adopt", historical_task_no, None),
        )
    historical_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=historical_command)
        result = WfmImportMutationParticipant.create_or_adopt_wfm_from_source(
            uow,
            WfmCreateOrAdoptFromSourceMutation(
                task_no=historical_task_no,
                expected_task_id=None,
                rfc_id=rfc_id,
                source_lifecycle_class="complete",
                base_state_token=historical_token,
                accepted_command_id=historical_command,
            ),
        )
        _write_owner_audits(uow, result.audit_events)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (active_command,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_task_identities WHERE task_no=?", (active_task_no,)
        ).fetchone()[0] == 0
        row = snapshot.connection.execute(
            "SELECT t.creation_origin,w.current_rfc_id FROM tasks t JOIN wfm_task_identities w ON w.task_id=t.task_id "
            "WHERE w.task_no=?",
            (historical_task_no,),
        ).fetchone()
        assert tuple(row) == ("historical_source", rfc_id)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_source_projection_cache WHERE task_id=?", (result.task_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_current WHERE task_id=?", (result.task_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.wfm_registered'",
            (historical_command,),
        ).fetchone()[0] == 1


def test_source_created_active_wfm_identity_is_audited_without_fabricating_other_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id, rfc_no = _create_rfc(factory, 304)
    task_no = "TK00000000000304"
    with ReadSnapshot(factory) as snapshot:
        assert RfcImportReader.get_by_number(snapshot.connection, rfc_no)["rfc_id"] == rfc_id
        assert RfcImportReader.governing_root(snapshot.connection, rfc_id) == rfc_id
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_create_or_adopt", task_no, None),
        )

    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=command_id)
        result = WfmImportMutationParticipant.create_or_adopt_wfm_from_source(
            uow,
            WfmCreateOrAdoptFromSourceMutation(
                task_no=task_no,
                expected_task_id=None,
                rfc_id=rfc_id,
                source_lifecycle_class="active",
                base_state_token=base_token,
                accepted_command_id=command_id,
            ),
        )
        _write_owner_audits(uow, result.audit_events)

    assert result.resulting_task_revision == 1
    with ReadSnapshot(factory) as snapshot:
        task = snapshot.connection.execute(
            "SELECT task_kind,creation_origin,revision FROM tasks WHERE task_id=?", (result.task_id,)
        ).fetchone()
        assert tuple(task) == ("wfm", "wfm_source_adoption", 1)
        assignment = snapshot.connection.execute(
            "SELECT prior_rfc_id,new_rfc_id,reason_code,review_risk FROM wfm_rfc_assignment_events WHERE task_id=?",
            (result.task_id,),
        ).fetchone()
        assert tuple(assignment) == (None, rfc_id, "source_adoption", "low")
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_source_projection_cache WHERE task_id=?", (result.task_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_revisions WHERE task_id=?", (result.task_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (result.task_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (result.task_id,)
        ).fetchone()[0] == 0


def test_source_projection_advances_only_source_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    _rfc_id, registered = _register_manual_wfm(factory, suffix=305)
    task_no = "TK00000000000305"
    observation_id, command_id = _apply_active_source_plan(
        factory,
        task_id=registered.task_id,
        task_no=task_no,
        start_utc=2_031_000_000,
        end_utc=2_031_003_600,
    )

    with ReadSnapshot(factory) as snapshot:
        task_revision = snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (registered.task_id,)
        ).fetchone()[0]
        assert task_revision == registered.revision
        source = snapshot.connection.execute(
            "SELECT provider_lifecycle_class,source_plan_start_utc,source_plan_end_utc,accepted_source_observation_id,"
            "source_projection_revision,last_command_id FROM wfm_source_projection_cache WHERE task_id=?",
            (registered.task_id,),
        ).fetchone()
        assert tuple(source) == (
            "active",
            2_031_000_000,
            2_031_003_600,
            observation_id,
            1,
            command_id,
        )
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_current WHERE task_id=?", (registered.task_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0


def test_reviewed_source_plan_adoption_uses_guayaquil_context_and_advances_task_plan_once(initialized_database) -> None:
    factory = _factory(initialized_database)
    _rfc_id, registered = _register_manual_wfm(factory, suffix=306)
    task_no = "TK00000000000306"
    start_utc = 2_032_000_000
    end_utc = 2_032_003_600
    observation_id, _source_command = _apply_active_source_plan(
        factory,
        task_id=registered.task_id,
        task_no=task_no,
        start_utc=start_utc,
        end_utc=end_utc,
    )
    base_token = _plan_token(factory, task_no=task_no, task_id=registered.task_id)
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=command_id)
        result = WfmImportMutationParticipant.apply_reviewed_operational_plan_from_source(
            uow,
            WfmReviewedOperationalPlanMutation(
                task_id=registered.task_id,
                task_no=task_no,
                expected_task_revision=registered.revision,
                expected_current_plan_revision=0,
                expected_source_projection_revision=1,
                accepted_source_observation_id=observation_id,
                start_utc=start_utc,
                end_utc=end_utc,
                base_state_token=base_token,
                accepted_command_id=command_id,
                reason_category="accept_reviewed_provider_plan",
            ),
        )
        _write_owner_audits(uow, result.audit_events)

    assert result.resulting_task_revision == registered.revision + 1
    with ReadSnapshot(factory) as snapshot:
        task_revision = snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (registered.task_id,)
        ).fetchone()[0]
        assert task_revision == registered.revision + 1
        plan = snapshot.connection.execute(
            "SELECT c.revision,p.start_utc,p.end_utc,p.origin,p.scheduling_timezone_iana,p.source_observation_id "
            "FROM task_plan_current c JOIN task_plan_revisions p ON p.plan_revision_id=c.plan_revision_id "
            "WHERE c.task_id=?",
            (registered.task_id,),
        ).fetchone()
        assert tuple(plan) == (
            1,
            start_utc,
            end_utc,
            "wfm_source_adoption",
            "America/Guayaquil",
            observation_id,
        )
        assert snapshot.connection.execute(
            "SELECT source_projection_revision,accepted_source_observation_id FROM wfm_source_projection_cache "
            "WHERE task_id=?",
            (registered.task_id,),
        ).fetchone() == (1, observation_id)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.plan_changed'",
            (command_id,),
        ).fetchone()[0] == 1


def test_stale_plan_token_after_lock_rejects_before_owner_write_and_outer_receipt_rolls_back(initialized_database) -> None:
    factory = _factory(initialized_database)
    _rfc_id, registered = _register_manual_wfm(factory, suffix=307)
    task_no = "TK00000000000307"
    start_utc = 2_033_000_000
    end_utc = 2_033_003_600
    observation_id, _source_command = _apply_active_source_plan(
        factory,
        task_id=registered.task_id,
        task_no=task_no,
        start_utc=start_utc,
        end_utc=end_utc,
    )
    stale_token = _plan_token(factory, task_no=task_no, task_id=registered.task_id)
    locked = TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=new_uuid4(),
        task_id=registered.task_id,
        task_revision=registered.revision,
        lock_projection_revision=0,
        lock_kind="plan",
        action="lock",
        reason_category="stale_review_proof",
    )
    assert locked.outcome == "APPLIED"

    command_id = new_uuid4()
    with pytest.raises(SomaError) as caught:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id=command_id)
            WfmImportMutationParticipant.apply_reviewed_operational_plan_from_source(
                uow,
                WfmReviewedOperationalPlanMutation(
                    task_id=registered.task_id,
                    task_no=task_no,
                    expected_task_revision=registered.revision,
                    expected_current_plan_revision=0,
                    expected_source_projection_revision=1,
                    accepted_source_observation_id=observation_id,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    base_state_token=stale_token,
                    accepted_command_id=command_id,
                ),
            )
    assert caught.value.code == "TASK_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_current WHERE task_id=?", (registered.task_id,)
        ).fetchone()[0] == 0


def test_outer_uow_failure_rolls_back_source_created_identity_and_audit(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id, _rfc_no = _create_rfc(factory, 308)
    task_no = "TK00000000000308"
    with ReadSnapshot(factory) as snapshot:
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_create_or_adopt", task_no, None),
        )
    command_id = new_uuid4()

    with pytest.raises(RuntimeError, match="inject outer failure"):
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id=command_id)
            result = WfmImportMutationParticipant.create_or_adopt_wfm_from_source(
                uow,
                WfmCreateOrAdoptFromSourceMutation(
                    task_no=task_no,
                    expected_task_id=None,
                    rfc_id=rfc_id,
                    source_lifecycle_class="active",
                    base_state_token=base_token,
                    accepted_command_id=command_id,
                ),
            )
            _write_owner_audits(uow, result.audit_events)
            raise RuntimeError("inject outer failure")

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_task_identities WHERE task_no=?", (task_no,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
