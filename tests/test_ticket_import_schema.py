from __future__ import annotations

import pytest

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork


_TABLES = {
    "import_runs",
    "import_source_checkpoints",
    "import_recovery_reviews",
    "import_recovery_events",
    "source_observations",
    "source_observation_fields",
    "import_findings",
    "reconciliation_proposals",
    "reconciliation_proposal_changes",
    "proposal_dispositions",
    "proposal_equivalence_decisions",
}
_INDEXES = {
    "idx_import_runs_family_state",
    "idx_import_runs_family_chronology",
    "idx_import_runs_fingerprint",
    "idx_import_checkpoint_run_fk",
    "idx_import_recovery_review_run_fk",
    "idx_import_recovery_review_checkpoint_fk",
    "idx_import_recovery_review_command_fk",
    "idx_import_recovery_run_fk",
    "idx_import_recovery_prior_fk",
    "idx_import_recovery_command_fk",
    "idx_source_observation_run",
    "idx_source_observation_identity",
    "idx_source_observation_parent",
    "uq_source_observation_field",
    "idx_finding_run",
    "idx_finding_observation_fk",
    "idx_proposal_run_state",
    "idx_proposal_target",
    "idx_proposal_observation_fk",
    "idx_proposal_prior_observation_fk",
    "idx_proposal_change_field_fk",
    "idx_disposition_proposal_fk",
    "idx_disposition_command_fk",
    "idx_equivalence_target",
    "idx_equivalence_source_fk",
    "idx_equivalence_command_fk",
}


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _receipt(uow: UnitOfWork, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?, 'TestImportCommand', ?, 'import_run', NULL, 0, NULL, NULL)",
        (command_id, "0" * 64),
    )


def _run(
    uow: UnitOfWork,
    *,
    import_run_id: str,
    state: str,
    family: str = "advanced_search_sr",
    chronology: int = 100,
) -> None:
    published = state in {
        "staged",
        "waiting_review",
        "partially_accepted",
        "accepted",
        "rejected",
        "noop_pending_checkpoint",
        "noop",
        "recovery_required",
    }
    terminal = state in {"partially_accepted", "accepted", "rejected", "noop", "failed"}
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,"
        "parser_profile_id,candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,"
        "candidate_chronology_kind,candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
        "staged_at_utc,completed_at_utc"
        ") VALUES (?, ?, 'manual', 'PROFILE_V1', 'HEADERS_V1', 'VOCAB_V1', 'PARSER_V1', ?, 1, 1, "
        "'embedded_filename_timestamp_utc', ?, ?, ?, 0, ?, ?)",
        (
            import_run_id,
            family,
            f"candidate-{import_run_id}.xlsx",
            chronology,
            "1" * 64 if published else None,
            state,
            1 if published else None,
            2 if terminal else None,
        ),
    )


def _observation(uow: UnitOfWork, *, run_id: str, observation_id: str, sr_no: str = "12345678") -> None:
    uow.connection.execute(
        "INSERT INTO source_observations("
        "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,"
        "canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc"
        ") VALUES (?, ?, 'advanced_search_sr', 'service_request', 'valid', ?, NULL, 1, 1, ?, 100, 'observed_valid_identity', 1)",
        (observation_id, run_id, sr_no, "2" * 64),
    )


def _field(uow: UnitOfWork, *, observation_id: str, field_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO source_observation_fields("
        "source_observation_field_id,source_observation_id,field_key,field_class,value_state,value_kind,source_text,"
        "normalized_text,integer_value,vocabulary_id,field_logical_sha256"
        ") VALUES (?, ?, 'problem_summary', 'active', 'usable', 'text', 'Problem', 'Problem', NULL, NULL, ?)",
        (field_id, observation_id, "3" * 64),
    )


def _finding(uow: UnitOfWork, *, run_id: str, observation_id: str, finding_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO import_findings(import_finding_id,import_run_id,source_observation_id,field_key,finding_code,severity,"
        "scope_kind,message_text,recorded_at_utc) VALUES (?, ?, ?, 'problem_summary', 'TEST_WARNING', 'warning', 'field', 'warning', 1)",
        (finding_id, run_id, observation_id),
    )


def _proposal(
    uow: UnitOfWork,
    *,
    run_id: str,
    observation_id: str,
    proposal_id: str,
    risk_class: str = "medium",
) -> None:
    uow.connection.execute(
        "INSERT INTO reconciliation_proposals("
        "reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,prior_source_observation_id,"
        "proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,base_state_token_sha256,"
        "proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc"
        ") VALUES (?, ?, 'observed_row', ?, NULL, 'sr_source_projection', 'service_request', NULL, '12345678', ?, ?, ?, 'pending', 1, 1, NULL)",
        (proposal_id, run_id, observation_id, risk_class, "4" * 64, "5" * 64),
    )


def test_ticket_import_schema_is_strict_complete_and_fk_clean(initialized_database) -> None:
    factory = _factory(initialized_database)
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT name,sql FROM sqlite_schema WHERE type='table' AND name IN ("
            + ",".join("?" for _ in _TABLES)
            + ")",
            tuple(sorted(_TABLES)),
        ).fetchall()
        assert {str(row[0]) for row in rows} == _TABLES
        for _name, sql in rows:
            assert str(sql).rstrip().endswith("STRICT")

        indexes = {
            str(row[0])
            for row in snapshot.connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='index' AND name IS NOT NULL"
            ).fetchall()
        }
        assert _INDEXES <= indexes
        assert snapshot.connection.execute("PRAGMA foreign_key_check").fetchall() == []

    invalid_run = new_uuid4()
    with pytest.raises(Exception):
        with UnitOfWork(factory) as uow:
            _run(uow, import_run_id=invalid_run, state="validating", family="not_a_source_family")


def test_unpublished_staging_can_be_cleaned_but_published_evidence_is_append_only(initialized_database) -> None:
    factory = _factory(initialized_database)
    staging_run = new_uuid4()
    staging_observation = new_uuid4()
    staging_field = new_uuid4()
    staging_finding = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, import_run_id=staging_run, state="validating")
        _observation(uow, run_id=staging_run, observation_id=staging_observation)
        _field(uow, observation_id=staging_observation, field_id=staging_field)
        _finding(uow, run_id=staging_run, observation_id=staging_observation, finding_id=staging_finding)
        uow.connection.execute("DELETE FROM import_findings WHERE import_finding_id=?", (staging_finding,))
        uow.connection.execute("DELETE FROM source_observation_fields WHERE source_observation_field_id=?", (staging_field,))
        uow.connection.execute("DELETE FROM source_observations WHERE source_observation_id=?", (staging_observation,))

    published_run = new_uuid4()
    published_observation = new_uuid4()
    published_field = new_uuid4()
    published_finding = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, import_run_id=published_run, state="waiting_review")
        _observation(uow, run_id=published_run, observation_id=published_observation)
        _field(uow, observation_id=published_observation, field_id=published_field)
        _finding(uow, run_id=published_run, observation_id=published_observation, finding_id=published_finding)

    with UnitOfWork(factory) as uow:
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "UPDATE source_observations SET canonical_primary_id='87654321' WHERE source_observation_id=?",
                (published_observation,),
            )
        assert "IMPORT_SOURCE_EVIDENCE_APPEND_ONLY" in str(excinfo.value)
        with pytest.raises(Exception):
            uow.connection.execute("DELETE FROM import_findings WHERE import_finding_id=?", (published_finding,))
        with pytest.raises(Exception):
            uow.connection.execute("DELETE FROM source_observation_fields WHERE source_observation_field_id=?", (published_field,))
        with pytest.raises(Exception):
            uow.connection.execute("DELETE FROM source_observations WHERE source_observation_id=?", (published_observation,))


def test_import_run_provenance_and_terminal_state_are_guarded(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, import_run_id=run_id, state="validating")

    with UnitOfWork(factory) as uow:
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "UPDATE import_runs SET candidate_filename='rewritten.xlsx',run_state='waiting_review',"
                "logical_fingerprint_sha256=?,staged_at_utc=1,revision=2 WHERE import_run_id=?",
                ("6" * 64, run_id),
            )
        assert "IMPORT_RUN_IMMUTABLE_PROVENANCE" in str(excinfo.value)

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE import_runs SET run_state='waiting_review',logical_fingerprint_sha256=?,staged_at_utc=1,revision=2 "
            "WHERE import_run_id=?",
            ("6" * 64, run_id),
        )
    with UnitOfWork(factory) as uow:
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "UPDATE import_runs SET logical_fingerprint_sha256=?,run_state='waiting_review',revision=3 WHERE import_run_id=?",
                ("7" * 64, run_id),
            )
        assert "IMPORT_RUN_IMMUTABLE_PROVENANCE" in str(excinfo.value)

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE import_runs SET run_state='accepted',completed_at_utc=2,revision=3 WHERE import_run_id=?",
            (run_id,),
        )
    with UnitOfWork(factory) as uow:
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "UPDATE import_runs SET run_state='rejected',completed_at_utc=3,revision=4 WHERE import_run_id=?",
                (run_id,),
            )
        assert "IMPORT_RUN_TERMINAL" in str(excinfo.value)


def test_proposal_transition_disposition_and_equivalence_history_are_append_only(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    proposal_id = new_uuid4()
    disposition_id = new_uuid4()
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, import_run_id=run_id, state="waiting_review")
        _observation(uow, run_id=run_id, observation_id=observation_id)
        _proposal(uow, run_id=run_id, observation_id=observation_id, proposal_id=proposal_id)
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'problem_summary','set','text','old','new',NULL,NULL,NULL)",
            (proposal_id,),
        )
        _receipt(uow, command_id)
        uow.connection.execute(
            "UPDATE reconciliation_proposals SET proposal_state='accepted',revision=2,decided_at_utc=2 "
            "WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        )
        uow.connection.execute(
            "INSERT INTO proposal_dispositions(proposal_disposition_id,reconciliation_proposal_id,decision,proposal_revision,"
            "proposal_fingerprint_sha256,base_state_token_sha256,reason_category,decision_origin,occurred_at_utc,command_id) "
            "VALUES (?,?,'accepted',1,?,?, 'reviewed', 'operator',2,?)",
            (disposition_id, proposal_id, "5" * 64, "4" * 64, command_id),
        )

    with UnitOfWork(factory) as uow:
        for statement, params in (
            ("UPDATE reconciliation_proposals SET proposal_state='rejected',revision=3,decided_at_utc=3 WHERE reconciliation_proposal_id=?", (proposal_id,)),
            ("DELETE FROM reconciliation_proposals WHERE reconciliation_proposal_id=?", (proposal_id,)),
            ("UPDATE proposal_dispositions SET reason_category='changed' WHERE proposal_disposition_id=?", (disposition_id,)),
            ("DELETE FROM proposal_dispositions WHERE proposal_disposition_id=?", (disposition_id,)),
            ("UPDATE reconciliation_proposal_changes SET after_text='rewritten' WHERE reconciliation_proposal_id=? AND ordinal=0", (proposal_id,)),
        ):
            with pytest.raises(Exception) as excinfo:
                uow.connection.execute(statement, params)
            assert "IMPORT_PROPOSAL_HISTORY_APPEND_ONLY" in str(excinfo.value)

    blocked_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _proposal(uow, run_id=run_id, observation_id=observation_id, proposal_id=blocked_id, risk_class="blocked")
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "UPDATE reconciliation_proposals SET proposal_state='accepted',revision=2,decided_at_utc=2 "
                "WHERE reconciliation_proposal_id=?",
                (blocked_id,),
            )
        assert "IMPORT_PROPOSAL_BLOCKED" in str(excinfo.value)

    rejected_id = new_uuid4()
    equivalence_id = new_uuid4()
    equivalence_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _proposal(uow, run_id=run_id, observation_id=observation_id, proposal_id=rejected_id)
        _receipt(uow, equivalence_command)
        uow.connection.execute(
            "UPDATE reconciliation_proposals SET proposal_state='rejected',revision=2,decided_at_utc=2 "
            "WHERE reconciliation_proposal_id=?",
            (rejected_id,),
        )
        uow.connection.execute(
            "INSERT INTO proposal_equivalence_decisions(proposal_equivalence_decision_id,proposal_kind,target_internal_id,"
            "target_business_id,material_input_fingerprint_sha256,decision,source_proposal_id,created_at_utc,command_id) "
            "VALUES (?,'sr_source_projection',NULL,'12345678',?,'rejected',?,2,?)",
            (equivalence_id, "8" * 64, rejected_id, equivalence_command),
        )
    with UnitOfWork(factory) as uow:
        with pytest.raises(Exception) as excinfo:
            uow.connection.execute(
                "DELETE FROM proposal_equivalence_decisions WHERE proposal_equivalence_decision_id=?",
                (equivalence_id,),
            )
        assert "IMPORT_PROPOSAL_HISTORY_APPEND_ONLY" in str(excinfo.value)


def test_recovery_review_and_completion_evidence_are_append_only(initialized_database) -> None:
    factory = _factory(initialized_database)
    checkpoint_run = new_uuid4()
    recovery_run = new_uuid4()
    command_id = new_uuid4()
    review_id = new_uuid4()
    event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, import_run_id=checkpoint_run, state="accepted", chronology=200)
        _run(uow, import_run_id=recovery_run, state="recovery_required", chronology=100)
        _receipt(uow, command_id)
        uow.connection.execute(
            "INSERT INTO import_recovery_reviews(import_recovery_review_id,import_run_id,checkpoint_import_run_id,review_ordinal,"
            "run_revision,checkpoint_revision,review_fingerprint_sha256,decision,reason_category,occurred_at_utc,command_id) "
            "VALUES (?,?,?,1,1,1,?,'authorized','older_source_review',2,?)",
            (review_id, recovery_run, checkpoint_run, "9" * 64, command_id),
        )
        uow.connection.execute(
            "INSERT INTO import_recovery_events(import_recovery_event_id,source_family,import_run_id,prior_checkpoint_run_id,"
            "recovery_reason_category,review_fingerprint_sha256,occurred_at_utc,command_id) "
            "VALUES (?,'advanced_search_sr',?,?, 'older_source_review',?,3,?)",
            (event_id, recovery_run, checkpoint_run, "9" * 64, command_id),
        )

    with UnitOfWork(factory) as uow:
        for table, column, row_id in (
            ("import_recovery_reviews", "import_recovery_review_id", review_id),
            ("import_recovery_events", "import_recovery_event_id", event_id),
        ):
            with pytest.raises(Exception) as excinfo:
                uow.connection.execute(f"DELETE FROM {table} WHERE {column}=?", (row_id,))
            assert "IMPORT_RECOVERY_HISTORY_APPEND_ONLY" in str(excinfo.value)
