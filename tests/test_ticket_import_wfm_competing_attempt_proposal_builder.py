from __future__ import annotations

from dataclasses import replace

import pytest

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.ticket_import.providers.wfm_competing_attempt_evidence import (
    PublishedWfmCompetingAttemptEvidence,
)
from soma.ticket_import.reconciliation.engine import (
    build_wfm_competing_attempt_review_proposal,
)


class _SelectOnlyReader:
    def __init__(self, source_row: tuple[object, ...]) -> None:
        self.source_row = source_row
        self.statements: list[str] = []

    def execute(self, sql: str, parameters=()):
        normalized = sql.lstrip().upper()
        assert normalized.startswith("SELECT"), f"proposal builder attempted non-read SQL: {sql}"
        self.statements.append(sql)
        return self

    def fetchone(self):
        return self.source_row


class _EvidenceProvider:
    def __init__(self, evidence: PublishedWfmCompetingAttemptEvidence) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, str]] = []

    def load_exact(self, reader, *, expected_import_run_id: str, source_observation_id: str):
        self.calls.append((expected_import_run_id, source_observation_id))
        assert expected_import_run_id == self.evidence.import_run_id
        assert source_observation_id == self.evidence.source_observation_id
        return self.evidence


class _RfcReader:
    def __init__(self, rfc_id: str | None) -> None:
        self.rfc_id = rfc_id

    def get_by_number(self, reader, rfc_no: str):
        if self.rfc_id is None:
            return None
        return {"rfc_id": self.rfc_id, "rfc_no": rfc_no}


class _WfmReader:
    def __init__(
        self,
        *,
        task_id: str,
        rfc_id: str,
        status: str = "ACTIVE",
        classification: str = "SAME_REVIEWED_LINEAGE_OVERLAP",
        lineage_id: str | None = None,
        counterpart_id: str | None = None,
        conflict_fingerprint: str = "a" * 64,
        exact_conflict_count: int = 1,
    ) -> None:
        self.task_id = task_id
        self.rfc_id = rfc_id
        self.status = status
        self.classification = classification
        self.lineage_id = new_uuid4() if lineage_id is None else lineage_id
        self.counterpart_id = new_uuid4() if counterpart_id is None else counterpart_id
        self.conflict_fingerprint = conflict_fingerprint
        self.exact_conflict_count = exact_conflict_count
        self.conflict_calls: list[tuple[object, object, object]] = []

    def task_no_status(self, reader, task_no: str) -> str:
        return self.status

    def get_by_task_no(self, reader, task_no: str):
        return {
            "task_id": self.task_id,
            "task_no": task_no,
            "current_rfc_id": self.rfc_id,
            "assignment_revision": 1,
            "task_revision": 7,
        }

    def activity_conflicts(self, reader, subject, interval, counterpart_task_id=None):
        self.conflict_calls.append((subject, interval, counterpart_task_id))
        return {
            "classification": self.classification,
            "subject_task_id": self.task_id,
            "activity_lineage_id": self.lineage_id if self.classification == "SAME_REVIEWED_LINEAGE_OVERLAP" else None,
            "exact_conflict_count": self.exact_conflict_count if self.classification == "SAME_REVIEWED_LINEAGE_OVERLAP" else 0,
            "suggested_counterpart_task_id": (
                self.counterpart_id if self.classification == "SAME_REVIEWED_LINEAGE_OVERLAP" else None
            ),
            "selected_counterpart": None,
            "conflict_fingerprint": self.conflict_fingerprint,
        }


def _scope():
    import_run_id = new_uuid4()
    observation_id = new_uuid4()
    task_id = new_uuid4()
    rfc_id = new_uuid4()
    lineage_id = new_uuid4()
    counterpart_id = new_uuid4()
    task_no = "TK00000000001234"
    rfc_no = "NC00000000005678"
    evidence = PublishedWfmCompetingAttemptEvidence(
        source_observation_id=observation_id,
        import_run_id=import_run_id,
        task_no=task_no,
        parent_rfc_no=rfc_no,
        planned_start_field_id=new_uuid4(),
        planned_start_utc=2_000_000_000,
        planned_end_field_id=new_uuid4(),
        planned_end_utc=2_000_003_600,
    )
    source_row = (
        import_run_id,
        "wfm_service_provider",
        "WFM_SERVICE_PROVIDER_V1",
        "WFM_HEADERS_V1",
        "WFM_VOCAB_V1",
        "WFM_PARSER_V1",
        observation_id,
        "wfm_service_provider",
        "wfm",
        "valid",
        task_no,
        rfc_no,
        "b" * 64,
    )
    return {
        "import_run_id": import_run_id,
        "observation_id": observation_id,
        "task_id": task_id,
        "rfc_id": rfc_id,
        "lineage_id": lineage_id,
        "counterpart_id": counterpart_id,
        "task_no": task_no,
        "rfc_no": rfc_no,
        "evidence": evidence,
        "source_row": source_row,
    }


def _build(scope: dict[str, object], *, wfm_reader: _WfmReader, rfc_id: str | None = None):
    reader = _SelectOnlyReader(scope["source_row"])
    evidence_provider = _EvidenceProvider(scope["evidence"])
    result = build_wfm_competing_attempt_review_proposal(
        reader,
        import_run_id=str(scope["import_run_id"]),
        source_observation_id=str(scope["observation_id"]),
        rfc_reader=_RfcReader(str(scope["rfc_id"]) if rfc_id is None else rfc_id),
        wfm_reader=wfm_reader,
        evidence_provider=evidence_provider,
    )
    return result, reader, evidence_provider


def test_competing_attempt_builder_returns_exact_draft_and_canonical_fingerprint() -> None:
    scope = _scope()
    wfm = _WfmReader(
        task_id=str(scope["task_id"]),
        rfc_id=str(scope["rfc_id"]),
        lineage_id=str(scope["lineage_id"]),
        counterpart_id=str(scope["counterpart_id"]),
        conflict_fingerprint="c" * 64,
    )
    draft, reader, evidence_provider = _build(scope, wfm_reader=wfm)

    assert draft is not None
    assert draft.import_run_id == scope["import_run_id"]
    assert draft.evidence_mode == "observed_row"
    assert draft.source_observation_id == scope["observation_id"]
    assert draft.proposal_kind == "wfm_competing_attempt_review"
    assert draft.target_kind == "activity_lineage"
    assert draft.target_internal_id == scope["lineage_id"]
    assert draft.target_business_id == scope["task_no"]
    assert draft.risk_class == "high"
    assert draft.base_state_token_sha256 == "c" * 64
    assert len(draft.changes) == 1
    change = draft.changes[0]
    assert change.ordinal == 0
    assert change.field_key == "competing_attempt_counterpart"
    assert change.change_kind == "conflict"
    assert change.value_kind == "identity"
    assert change.before_text is None
    assert change.after_text == scope["counterpart_id"]
    assert change.before_integer is None
    assert change.after_integer is None
    assert change.source_observation_field_id is None

    expected = sha256_canonical_json(
        {
            "schema": "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1",
            "source": {
                "import_run_id": scope["import_run_id"],
                "source_family": "wfm_service_provider",
                "source_profile_id": "WFM_SERVICE_PROVIDER_V1",
                "header_registry_id": "WFM_HEADERS_V1",
                "vocabulary_registry_id": "WFM_VOCAB_V1",
                "parser_profile_id": "WFM_PARSER_V1",
                "source_observation_id": scope["observation_id"],
                "canonical_primary_id": scope["task_no"],
                "canonical_parent_rfc_no": scope["rfc_no"],
                "row_logical_sha256": "b" * 64,
            },
            "proposal": {
                "proposal_kind": "wfm_competing_attempt_review",
                "evidence_mode": "observed_row",
                "risk_class": "high",
                "target_kind": "activity_lineage",
                "target_internal_id": scope["lineage_id"],
                "target_business_id": scope["task_no"],
            },
            "changes": [change.fingerprint_object()],
        }
    )
    assert draft.proposal_fingerprint_sha256 == expected
    assert len(reader.statements) == 1
    assert evidence_provider.calls == [(scope["import_run_id"], scope["observation_id"])]
    assert wfm.conflict_calls == [
        (
            {
                "task_no": scope["task_no"],
                "current_rfc_id": scope["rfc_id"],
                "task_id": scope["task_id"],
            },
            {"start_utc": 2_000_000_000, "end_utc": 2_000_003_600},
            None,
        )
    ]


def test_competing_attempt_builder_keeps_proposal_fingerprint_independent_from_conflict_token() -> None:
    scope = _scope()
    first = _WfmReader(
        task_id=str(scope["task_id"]),
        rfc_id=str(scope["rfc_id"]),
        lineage_id=str(scope["lineage_id"]),
        counterpart_id=str(scope["counterpart_id"]),
        conflict_fingerprint="1" * 64,
    )
    second = _WfmReader(
        task_id=str(scope["task_id"]),
        rfc_id=str(scope["rfc_id"]),
        lineage_id=str(scope["lineage_id"]),
        counterpart_id=str(scope["counterpart_id"]),
        conflict_fingerprint="2" * 64,
    )
    first_draft, _, _ = _build(scope, wfm_reader=first)
    second_draft, _, _ = _build(scope, wfm_reader=second)
    assert first_draft is not None and second_draft is not None
    assert first_draft.proposal_fingerprint_sha256 == second_draft.proposal_fingerprint_sha256
    assert first_draft.base_state_token_sha256 == "1" * 64
    assert second_draft.base_state_token_sha256 == "2" * 64


@pytest.mark.parametrize("status", ["ABSENT", "RETIRED"])
def test_competing_attempt_builder_emits_no_proposal_for_nonactive_task_no(status: str) -> None:
    scope = _scope()
    wfm = _WfmReader(task_id=str(scope["task_id"]), rfc_id=str(scope["rfc_id"]), status=status)
    draft, reader, _ = _build(scope, wfm_reader=wfm)
    assert draft is None
    assert reader.statements == []
    assert wfm.conflict_calls == []


def test_competing_attempt_builder_emits_no_proposal_when_parent_rfc_is_missing() -> None:
    scope = _scope()
    wfm = _WfmReader(task_id=str(scope["task_id"]), rfc_id=str(scope["rfc_id"]))
    reader = _SelectOnlyReader(scope["source_row"])
    result = build_wfm_competing_attempt_review_proposal(
        reader,
        import_run_id=str(scope["import_run_id"]),
        source_observation_id=str(scope["observation_id"]),
        rfc_reader=_RfcReader(None),
        wfm_reader=wfm,
        evidence_provider=_EvidenceProvider(scope["evidence"]),
    )
    assert result is None
    assert reader.statements == []
    assert wfm.conflict_calls == []


def test_competing_attempt_builder_emits_no_proposal_when_current_parent_changed() -> None:
    scope = _scope()
    wfm = _WfmReader(task_id=str(scope["task_id"]), rfc_id=new_uuid4())
    draft, reader, _ = _build(scope, wfm_reader=wfm)
    assert draft is None
    assert reader.statements == []
    assert wfm.conflict_calls == []


@pytest.mark.parametrize("classification", ["CLEAR", "NO_REVIEWED_LINEAGE"])
def test_competing_attempt_builder_emits_no_proposal_without_same_lineage_overlap(classification: str) -> None:
    scope = _scope()
    wfm = _WfmReader(
        task_id=str(scope["task_id"]),
        rfc_id=str(scope["rfc_id"]),
        classification=classification,
    )
    draft, reader, _ = _build(scope, wfm_reader=wfm)
    assert draft is None
    assert reader.statements == []
    assert len(wfm.conflict_calls) == 1


@pytest.mark.parametrize(
    ("lineage_id", "counterpart_id", "fingerprint", "count"),
    [
        ("not-a-uuid", None, "a" * 64, 1),
        (None, "not-a-uuid", "a" * 64, 1),
        (None, None, "not-a-sha", 1),
        (None, None, "a" * 64, 0),
    ],
)
def test_competing_attempt_builder_fails_closed_on_malformed_conflict_authority(
    lineage_id: str | None,
    counterpart_id: str | None,
    fingerprint: str,
    count: int,
) -> None:
    scope = _scope()
    wfm = _WfmReader(
        task_id=str(scope["task_id"]),
        rfc_id=str(scope["rfc_id"]),
        lineage_id=lineage_id,
        counterpart_id=counterpart_id,
        conflict_fingerprint=fingerprint,
        exact_conflict_count=count,
    )
    with pytest.raises(IntegrityFailure):
        _build(scope, wfm_reader=wfm)
