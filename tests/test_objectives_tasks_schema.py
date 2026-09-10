from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from soma.foundation.identifiers import new_uuid4
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.tickets.rfcs import RfcService


_TABLES = {
    "tasks",
    "wfm_task_identities",
    "wfm_rfc_assignment_events",
    "wfm_source_projection_cache",
    "task_plan_revisions",
    "task_plan_current",
    "task_execution_events",
    "task_execution_projection",
    "task_outcome_events",
    "task_outcome_current",
    "task_lock_events",
    "task_lock_projection",
    "task_sr_links",
    "task_rfc_links",
    "task_device_links",
    "task_retry_relations",
    "task_activity_lineages",
    "task_activity_lineage_events",
    "task_activity_lineage_current",
    "task_operational_count_events",
    "task_operational_count_current",
    "objective_tracking_allocator",
    "objectives",
    "objective_membership_events",
    "objective_task_membership_current",
    "objective_envelope_projection",
    "objective_aggregate_projection",
    "objective_review_events",
    "objective_archive_events",
    "objective_archive_projection",
    "regroup_proposals",
    "regroup_proposal_task_changes",
    "regroup_proposal_objective_changes",
    "regroup_rejection_events",
    "historical_objective_proposals",
    "wfm_source_terminal_reviews",
}

_REQUIRED_QUERY_INDEXES = {
    "idx_wfm_identity_rfc_task",
    "idx_wfm_assignment_task_recorded",
    "idx_task_plan_task_accepted",
    "idx_task_execution_task_recorded",
    "idx_task_outcome_task_reviewed",
    "idx_task_sr_links_task_active_target",
    "uq_task_sr_links_active",
    "idx_task_rfc_links_task_active_target",
    "uq_task_rfc_links_active",
    "idx_task_device_links_task_active_target",
    "uq_task_device_links_active",
    "idx_task_activity_lineage_current_lineage_task",
    "idx_objective_membership_current_objective_task",
    "idx_objective_membership_event_task_recorded",
    "idx_objective_membership_event_to_recorded",
    "idx_objective_envelope_interval",
    "idx_objective_aggregate_state_attention",
    "idx_objective_review_objective_reviewed",
    "idx_regroup_proposals_state_created",
    "uq_regroup_task_change_proposal_task",
    "idx_regroup_task_change_task_proposal",
    "idx_regroup_rejection_fingerprint_recorded",
    "idx_historical_proposal_task_state",
    "idx_wfm_terminal_review_task_state_created",
    "idx_wfm_terminal_review_fingerprint_state",
    "idx_wfm_terminal_review_source_revision_task",
}

_MIGRATION_6_SHA256 = "97ceed6eb398dd88fbdefeed964cbbd3334360243d060c2194344df548a89c27"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _receipt(
    uow: UnitOfWork,
    command_id: str,
    *,
    command_type: str,
    target_type: str,
    target_id: str | None,
) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?, ?, ?, ?, ?, 0, NULL, NULL)",
        (command_id, command_type, "0" * 64, target_type, target_id),
    )


def _local_task_with_plan(
    uow: UnitOfWork,
    *,
    task_id: str,
    plan_id: str,
    command_id: str,
    start_utc: int,
    end_utc: int,
) -> None:
    _receipt(uow, command_id, command_type="CreateLocalTask", target_type="task", target_id=task_id)
    uow.connection.execute(
        "INSERT INTO tasks(task_id,task_kind,local_task_name,creation_origin,revision,created_at_utc,created_command_id) "
        "VALUES (?, 'local', 'Task', 'manual', 1, 0, ?)",
        (task_id, command_id),
    )
    uow.connection.execute(
        "INSERT INTO task_plan_revisions(plan_revision_id,task_id,start_utc,end_utc,origin,scheduling_timezone_iana,"
        "source_observation_id,predecessor_plan_revision_id,reason_code,accepted_at_utc,command_id) "
        "VALUES (?, ?, ?, ?, 'manual', 'America/Guayaquil', NULL, NULL, NULL, 0, ?)",
        (plan_id, task_id, start_utc, end_utc, command_id),
    )
    uow.connection.execute(
        "INSERT INTO task_plan_current(task_id,plan_revision_id,revision,last_command_id) VALUES (?, ?, 1, ?)",
        (task_id, plan_id, command_id),
    )


def _manual_objective(
    uow: UnitOfWork,
    *,
    objective_id: str,
    sequence: int,
    task_id: str,
    plan_id: str,
    command_id: str,
    start_utc: int,
    end_utc: int,
) -> str:
    _receipt(
        uow,
        command_id,
        command_type="CreateObjectiveFromPreview",
        target_type="objective",
        target_id=objective_id,
    )
    membership_event_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO objectives(objective_id,tracking_sequence,tracking_id,creation_origin,superseded_by_objective_id,"
        "revision,created_at_utc,created_command_id) VALUES (?, ?, ?, 'manual', NULL, 1, 0, ?)",
        (objective_id, sequence, f"MW-{sequence:08d}", command_id),
    )
    uow.connection.execute(
        "INSERT INTO objective_membership_events(membership_event_id,task_id,event_kind,from_objective_id,to_objective_id,"
        "accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id) "
        "VALUES (?, ?, 'add', NULL, ?, ?, NULL, NULL, 0, ?)",
        (membership_event_id, task_id, objective_id, plan_id, command_id),
    )
    uow.connection.execute(
        "INSERT INTO objective_task_membership_current(task_id,objective_id,accepted_plan_revision_id,membership_revision,"
        "last_event_id,last_command_id) VALUES (?, ?, ?, 1, ?, ?)",
        (task_id, objective_id, plan_id, membership_event_id, command_id),
    )
    uow.connection.execute(
        "INSERT INTO objective_envelope_projection(objective_id,start_utc,end_utc,member_count,membership_input_fingerprint,"
        "revision,last_command_id) VALUES (?, ?, ?, 1, ?, 1, ?)",
        (objective_id, start_utc, end_utc, "1" * 64, command_id),
    )
    uow.connection.execute(
        "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,actual_start_utc,"
        "actual_end_utc,attention_reason,included_task_count,excluded_task_count,aggregate_input_fingerprint,revision,last_command_id) "
        "VALUES (?, 'planned', NULL, NULL, NULL, NULL, 1, 0, ?, 1, ?)",
        (objective_id, "2" * 64, command_id),
    )
    return membership_event_id


def _leading_index_columns(connection, table: str) -> set[str]:
    result: set[str] = set()
    for row in connection.execute(f"PRAGMA index_list('{table}')").fetchall():
        escaped = str(row[1]).replace("'", "''")
        columns = connection.execute(f"PRAGMA index_info('{escaped}')").fetchall()
        if columns and columns[0][2] is not None:
            result.add(str(columns[0][2]))
    return result


def test_objectives_tasks_schema_is_complete_strict_indexed_and_fk_clean(initialized_database) -> None:
    factory = _factory(initialized_database)
    assert len(_TABLES) == 36
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name IN ("
            + ",".join("?" for _ in _TABLES)
            + ")",
            tuple(sorted(_TABLES)),
        ).fetchall()
        assert {str(row[0]) for row in rows} == _TABLES

        strict = {
            str(row[1]): int(row[5])
            for row in snapshot.connection.execute("PRAGMA table_list").fetchall()
            if len(row) >= 6
        }
        assert all(strict.get(table) == 1 for table in _TABLES)

        indexes = {
            str(row[0])
            for row in snapshot.connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='index' AND name IS NOT NULL"
            ).fetchall()
        }
        assert _REQUIRED_QUERY_INDEXES <= indexes

        for table in sorted(_TABLES):
            leading = _leading_index_columns(snapshot.connection, table)
            for fk in snapshot.connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall():
                child_column = str(fk[3])
                assert child_column in leading, f"{table}.{child_column} lacks a leading-prefix FK index"

        assert snapshot.connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert snapshot.connection.execute(
            "SELECT next_sequence,revision,last_command_id FROM objective_tracking_allocator WHERE singleton_id=1"
        ).fetchone() == (1, 1, None)
        ledger = snapshot.connection.execute(
            "SELECT sequence,migration_id,sha256 FROM schema_migrations ORDER BY sequence"
        ).fetchall()
        assert len(ledger) == 6
        assert tuple(ledger[-1]) == (6, "beta_0006_objectives_tasks", _MIGRATION_6_SHA256)


def test_sequence_six_upgrades_a_real_five_migration_prefix(
    tmp_path: Path,
    migration_directory: Path,
    security_provider,
) -> None:
    staged = tmp_path / "migrations"
    staged.mkdir()
    full_manifest = json.loads((migration_directory / "manifest.json").read_text(encoding="utf-8"))
    prefix = {"schema": full_manifest["schema"], "migrations": full_manifest["migrations"][:5]}
    for entry in prefix["migrations"]:
        shutil.copyfile(migration_directory / entry["filename"], staged / entry["filename"])
    (staged / "manifest.json").write_text(
        json.dumps(prefix, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    database_path = tmp_path / "upgrade.db"

    def factory_for_path(path: Path) -> ConnectionFactory:
        return ConnectionFactory(path, security_provider, driver=sqlite3)

    first = MigrationRunner(
        canonical_database_path=database_path,
        manifest=MigrationManifest.load(staged),
        factory_for_path=factory_for_path,
        app_version="test-five",
        ownership_assertion=lambda: True,
    )
    assert first.initialize_or_migrate() == 5

    factory = factory_for_path(database_path)
    sentinel = new_uuid4()
    with UnitOfWork(factory) as uow:
        _receipt(uow, sentinel, command_type="ExistingCommand", target_type="test", target_id=None)

    shutil.copyfile(migration_directory / "0006_objectives_tasks.sql", staged / "0006_objectives_tasks.sql")
    shutil.copyfile(migration_directory / "manifest.json", staged / "manifest.json")
    second = MigrationRunner(
        canonical_database_path=database_path,
        manifest=MigrationManifest.load(staged),
        factory_for_path=factory_for_path,
        app_version="test-six",
        ownership_assertion=lambda: True,
    )
    assert second.initialize_or_migrate() == 6

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (sentinel,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT sequence,migration_id FROM schema_migrations ORDER BY sequence"
        ).fetchall()[-1] == (6, "beta_0006_objectives_tasks")
        assert snapshot.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_manual_wfm_initial_assignment_is_draft_deletable_but_reassignment_is_protected(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfcs = RfcService(factory)
    rfc_a = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no="NC20260910010001", creation_context="manual"
    )
    rfc_b = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no="NC20260910010002", creation_context="manual"
    )

    draft_task = new_uuid4()
    register = new_uuid4()
    initial_event = new_uuid4()
    with UnitOfWork(factory) as uow:
        _receipt(uow, register, command_type="RegisterManualWfmTask", target_type="task", target_id=draft_task)
        uow.connection.execute(
            "INSERT INTO tasks VALUES (?, 'wfm', NULL, 'wfm_manual', 1, 0, ?)", (draft_task, register)
        )
        uow.connection.execute(
            "INSERT INTO wfm_task_identities VALUES (?, 'TK00000000000001', ?, 1, ?)",
            (draft_task, rfc_a.rfc_id, register),
        )
        uow.connection.execute(
            "INSERT INTO wfm_rfc_assignment_events VALUES (?, ?, NULL, ?, 'manual_registration', 'low', 0, ?)",
            (initial_event, draft_task, rfc_a.rfc_id, register),
        )

    with pytest.raises(Exception) as protected:
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "DELETE FROM wfm_rfc_assignment_events WHERE assignment_event_id=?", (initial_event,)
            )
    assert "WFM_ASSIGNMENT_HISTORY_APPEND_ONLY" in str(protected.value)

    with UnitOfWork(factory) as uow:
        delete_command = new_uuid4()
        _receipt(uow, delete_command, command_type="HardDeleteTask", target_type="task", target_id=draft_task)
        uow.connection.execute(
            "DELETE FROM wfm_rfc_assignment_events WHERE assignment_event_id=?", (initial_event,)
        )
        uow.connection.execute("DELETE FROM wfm_task_identities WHERE task_id=?", (draft_task,))
        uow.connection.execute("DELETE FROM tasks WHERE task_id=?", (draft_task,))

    history_task = new_uuid4()
    history_register = new_uuid4()
    first_event = new_uuid4()
    second_event = new_uuid4()
    reassign = new_uuid4()
    with UnitOfWork(factory) as uow:
        _receipt(
            uow,
            history_register,
            command_type="RegisterManualWfmTask",
            target_type="task",
            target_id=history_task,
        )
        uow.connection.execute(
            "INSERT INTO tasks VALUES (?, 'wfm', NULL, 'wfm_manual', 1, 0, ?)",
            (history_task, history_register),
        )
        uow.connection.execute(
            "INSERT INTO wfm_task_identities VALUES (?, 'TK00000000000002', ?, 1, ?)",
            (history_task, rfc_a.rfc_id, history_register),
        )
        uow.connection.execute(
            "INSERT INTO wfm_rfc_assignment_events VALUES (?, ?, NULL, ?, 'manual_registration', 'low', 0, ?)",
            (first_event, history_task, rfc_a.rfc_id, history_register),
        )
        _receipt(uow, reassign, command_type="ReassignWfmParent", target_type="task", target_id=history_task)
        uow.connection.execute(
            "UPDATE wfm_task_identities SET current_rfc_id=?,assignment_revision=2 WHERE task_id=?",
            (rfc_b.rfc_id, history_task),
        )
        uow.connection.execute(
            "INSERT INTO wfm_rfc_assignment_events VALUES (?, ?, ?, ?, 'reviewed_reassignment', 'high', 1, ?)",
            (second_event, history_task, rfc_a.rfc_id, rfc_b.rfc_id, reassign),
        )

    with UnitOfWork(factory) as uow:
        delete_command = new_uuid4()
        _receipt(uow, delete_command, command_type="HardDeleteTask", target_type="task", target_id=history_task)
        with pytest.raises(Exception) as protected_history:
            uow.connection.execute(
                "DELETE FROM wfm_rfc_assignment_events WHERE assignment_event_id=?", (second_event,)
            )
        assert "WFM_ASSIGNMENT_HISTORY_APPEND_ONLY" in str(protected_history.value)


def test_protected_execution_history_cannot_be_erased_to_manufacture_hard_delete(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task_id, plan_id, create_command = new_uuid4(), new_uuid4(), new_uuid4()
    execution_event = new_uuid4()
    with UnitOfWork(factory) as uow:
        _local_task_with_plan(
            uow,
            task_id=task_id,
            plan_id=plan_id,
            command_id=create_command,
            start_utc=10,
            end_utc=20,
        )
        uow.connection.execute(
            "INSERT INTO task_execution_events VALUES (?, ?, 'start', 10, NULL, NULL, NULL, 10, ?)",
            (execution_event, task_id, create_command),
        )

    with UnitOfWork(factory) as uow:
        delete_command = new_uuid4()
        _receipt(uow, delete_command, command_type="HardDeleteTask", target_type="task", target_id=task_id)
        with pytest.raises(Exception) as append_only:
            uow.connection.execute(
                "DELETE FROM task_execution_events WHERE execution_event_id=?", (execution_event,)
            )
        assert "TASK_EXECUTION_HISTORY_APPEND_ONLY" in str(append_only.value)
        with pytest.raises(Exception):
            uow.connection.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))


def test_objective_nonempty_exact_touch_overlap_and_hard_delete_guards(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_a, plan_a = new_uuid4(), new_uuid4()
    task_b, plan_b = new_uuid4(), new_uuid4()
    objective_a, objective_b = new_uuid4(), new_uuid4()

    with UnitOfWork(factory) as uow:
        _local_task_with_plan(
            uow, task_id=task_a, plan_id=plan_a, command_id=new_uuid4(), start_utc=10, end_utc=20
        )
        _local_task_with_plan(
            uow, task_id=task_b, plan_id=plan_b, command_id=new_uuid4(), start_utc=20, end_utc=30
        )
        membership_a = _manual_objective(
            uow,
            objective_id=objective_a,
            sequence=1,
            task_id=task_a,
            plan_id=plan_a,
            command_id=new_uuid4(),
            start_utc=10,
            end_utc=20,
        )
        _manual_objective(
            uow,
            objective_id=objective_b,
            sequence=2,
            task_id=task_b,
            plan_id=plan_b,
            command_id=new_uuid4(),
            start_utc=20,
            end_utc=30,
        )

    with pytest.raises(Exception) as overlap:
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "UPDATE objective_envelope_projection SET start_utc=19 WHERE objective_id=?", (objective_b,)
            )
    assert "OBJECTIVE_OVERLAP" in str(overlap.value)

    with pytest.raises(Exception) as empty:
        with UnitOfWork(factory) as uow:
            wrong = new_uuid4()
            _receipt(
                uow,
                wrong,
                command_type="HardDeleteObjective",
                target_type="objective",
                target_id=objective_b,
            )
            uow.connection.execute(
                "DELETE FROM objective_task_membership_current WHERE task_id=?", (task_a,)
            )
    assert "OBJECTIVE_EMPTY" in str(empty.value)

    with UnitOfWork(factory) as uow:
        exact = new_uuid4()
        _receipt(
            uow,
            exact,
            command_type="HardDeleteObjective",
            target_type="objective",
            target_id=objective_a,
        )
        uow.connection.execute("DELETE FROM objective_task_membership_current WHERE task_id=?", (task_a,))
        uow.connection.execute("DELETE FROM objective_envelope_projection WHERE objective_id=?", (objective_a,))
        uow.connection.execute("DELETE FROM objective_aggregate_projection WHERE objective_id=?", (objective_a,))
        uow.connection.execute(
            "DELETE FROM objective_membership_events WHERE membership_event_id=?", (membership_a,)
        )
        uow.connection.execute("DELETE FROM objectives WHERE objective_id=?", (objective_a,))

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM tasks WHERE task_id=?", (task_a,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objectives WHERE objective_id=?", (objective_a,)
        ).fetchone()[0] == 0


def test_exact_touch_manual_merge_can_temporarily_empty_then_supersede_old_objective(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task_a, plan_a = new_uuid4(), new_uuid4()
    task_b, plan_b = new_uuid4(), new_uuid4()
    objective_a, objective_b = new_uuid4(), new_uuid4()

    with UnitOfWork(factory) as uow:
        _local_task_with_plan(
            uow, task_id=task_a, plan_id=plan_a, command_id=new_uuid4(), start_utc=10, end_utc=20
        )
        _local_task_with_plan(
            uow, task_id=task_b, plan_id=plan_b, command_id=new_uuid4(), start_utc=20, end_utc=30
        )
        _manual_objective(
            uow,
            objective_id=objective_a,
            sequence=10,
            task_id=task_a,
            plan_id=plan_a,
            command_id=new_uuid4(),
            start_utc=10,
            end_utc=20,
        )
        _manual_objective(
            uow,
            objective_id=objective_b,
            sequence=11,
            task_id=task_b,
            plan_id=plan_b,
            command_id=new_uuid4(),
            start_utc=20,
            end_utc=30,
        )

        proposal_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO regroup_proposals VALUES (?, 'manual_merge', 'manual_request', 'normal', ?, 'pending', ?, 1, 0, NULL)",
            (proposal_id, "a" * 64, objective_a),
        )
        uow.connection.execute(
            "INSERT INTO regroup_proposal_objective_changes VALUES (?, ?, ?, 'supersede', 1, 1)",
            (new_uuid4(), proposal_id, objective_b),
        )
        accept = new_uuid4()
        _receipt(
            uow,
            accept,
            command_type="AcceptRegroupProposal",
            target_type="grouping_proposal",
            target_id=proposal_id,
        )
        move_event = new_uuid4()
        uow.connection.execute(
            "INSERT INTO objective_membership_events VALUES (?, ?, 'move', ?, ?, ?, ?, 'manual_merge', 1, ?)",
            (move_event, task_b, objective_b, objective_a, plan_b, proposal_id, accept),
        )
        uow.connection.execute(
            "UPDATE objective_task_membership_current SET objective_id=?,membership_revision=membership_revision+1,"
            "last_event_id=?,last_command_id=? WHERE task_id=?",
            (objective_a, move_event, accept, task_b),
        )
        uow.connection.execute(
            "UPDATE objectives SET superseded_by_objective_id=?,revision=revision+1 WHERE objective_id=?",
            (objective_a, objective_b),
        )
        uow.connection.execute(
            "UPDATE objective_envelope_projection SET end_utc=30,member_count=2,membership_input_fingerprint=?,"
            "revision=revision+1,last_command_id=? WHERE objective_id=?",
            ("3" * 64, accept, objective_a),
        )
        uow.connection.execute(
            "UPDATE objective_aggregate_projection SET included_task_count=2,aggregate_input_fingerprint=?,"
            "revision=revision+1,last_command_id=? WHERE objective_id=?",
            ("4" * 64, accept, objective_a),
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_task_membership_current WHERE objective_id=?", (objective_a,)
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_task_membership_current WHERE objective_id=?", (objective_b,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT superseded_by_objective_id FROM objectives WHERE objective_id=?", (objective_b,)
        ).fetchone()[0] == objective_a
        assert snapshot.connection.execute(
            "SELECT start_utc,end_utc,member_count FROM objective_envelope_projection WHERE objective_id=?",
            (objective_a,),
        ).fetchone() == (10, 30, 2)
