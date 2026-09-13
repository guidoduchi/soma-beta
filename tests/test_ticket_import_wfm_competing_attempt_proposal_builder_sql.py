from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.providers.wfm_competing_attempt_evidence import (
    PublishedWfmCompetingAttemptEvidence,
)
from soma.ticket_import.reconciliation.engine import build_wfm_competing_attempt_review_proposal


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


class _EvidenceProvider:
    def __init__(self, evidence: PublishedWfmCompetingAttemptEvidence) -> None:
        self.evidence = evidence

    def load_exact(self, reader, *, expected_import_run_id: str, source_observation_id: str):
        assert expected_import_run_id == self.evidence.import_run_id
        assert source_observation_id == self.evidence.source_observation_id
        return self.evidence


class _RfcReader:
    def __init__(self, rfc_id: str) -> None:
        self.rfc_id = rfc_id

    def get_by_number(self, reader, rfc_no: str):
        return {"rfc_id": self.rfc_id, "rfc_no": rfc_no}


class _WfmReader:
    def __init__(self, *, task_id: str, rfc_id: str, lineage_id: str, counterpart_id: str) -> None:
        self.task_id = task_id
        self.rfc_id = rfc_id
        self.lineage_id = lineage_id
        self.counterpart_id = counterpart_id

    def task_no_status(self, reader, task_no: str) -> str:
        return "ACTIVE"

    def get_by_task_no(self, reader, task_no: str):
        return {
            "task_id": self.task_id,
            "task_no": task_no,
            "current_rfc_id": self.rfc_id,
            "assignment_revision": 1,
            "task_revision": 4,
        }

    def activity_conflicts(self, reader, subject, interval, counterpart_task_id=None):
        assert counterpart_task_id is None
        return {
            "classification": "SAME_REVIEWED_LINEAGE_OVERLAP",
            "subject_task_id": self.task_id,
            "activity_lineage_id": self.lineage_id,
            "exact_conflict_count": 1,
            "suggested_counterpart_task_id": self.counterpart_id,
            "selected_counterpart": None,
            "conflict_fingerprint": "d" * 64,
        }


def test_competing_attempt_builder_reads_real_migrated_source_authority_without_writes(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    task_id = new_uuid4()
    rfc_id = new_uuid4()
    lineage_id = new_uuid4()
    counterpart_id = new_uuid4()
    task_no = "TK00000000004444"
    rfc_no = "NC00000000008888"
    row_hash = "e" * 64

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,revision"
            ") VALUES (?,'wfm_service_provider','manual','WFM_SERVICE_PROVIDER_V1','WFM_HEADERS_V1','WFM_VOCAB_V1','WFM_PARSER_V1',"
            "'WFM Service Provider.xlsx',100,1,'embedded_filename_timestamp_utc',10,?,'waiting_review',0,1,1,1,1)",
            (run_id, "f" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations("
            "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
            "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc"
            ") VALUES (?,?,'wfm_service_provider','wfm','valid',?,?,1,1,?,10,'observed_valid_identity',1)",
            (observation_id, run_id, task_no, rfc_no, row_hash),
        )

    evidence = PublishedWfmCompetingAttemptEvidence(
        source_observation_id=observation_id,
        import_run_id=run_id,
        task_no=task_no,
        parent_rfc_no=rfc_no,
        planned_start_field_id=new_uuid4(),
        planned_start_utc=2_100_000_000,
        planned_end_field_id=new_uuid4(),
        planned_end_utc=2_100_003_600,
    )
    with UnitOfWork(factory) as uow:
        draft = build_wfm_competing_attempt_review_proposal(
            uow.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
            rfc_reader=_RfcReader(rfc_id),
            wfm_reader=_WfmReader(
                task_id=task_id,
                rfc_id=rfc_id,
                lineage_id=lineage_id,
                counterpart_id=counterpart_id,
            ),
            evidence_provider=_EvidenceProvider(evidence),
        )
        assert draft is not None
        assert draft.source_observation_id == observation_id
        assert draft.target_internal_id == lineage_id
        assert draft.target_business_id == task_no
        assert draft.changes[0].after_text == counterpart_id
        assert draft.base_state_token_sha256 == "d" * 64
        assert draft.proposal_fingerprint_sha256

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT count(*) FROM reconciliation_proposals").fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT count(*) FROM reconciliation_proposal_changes").fetchone()[0] == 0
