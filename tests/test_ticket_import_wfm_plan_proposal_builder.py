from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.ticket_import.providers.wfm_competing_attempt_evidence import PublishedWfmCompetingAttemptEvidence
from soma.ticket_import.reconciliation.wfm_follow_on import build_wfm_plan_reconciliation_proposal


class _SelectOnlyReader:
    def __init__(self, source_row: tuple[object, ...]) -> None:
        self.source_row = source_row
        self.statements: list[str] = []

    def execute(self, sql: str, parameters=()):
        assert sql.lstrip().upper().startswith("SELECT")
        self.statements.append(sql)
        return self

    def fetchone(self):
        return self.source_row


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
    def __init__(
        self,
        *,
        task_id: str,
        rfc_id: str,
        observation_id: str,
        start: int,
        end: int,
        base_token: str,
        operational: dict[str, object] | None,
    ) -> None:
        self.task_id = task_id
        self.rfc_id = rfc_id
        self.observation_id = observation_id
        self.start = start
        self.end = end
        self.base_token = base_token
        self.operational = operational

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

    def source_projection(self, reader, task_id: str):
        assert task_id == self.task_id
        return {
            "source_projection_revision": 3,
            "provider_status_token": "Implementation",
            "provider_lifecycle_class": "active",
            "source_plan_start_utc": self.start,
            "source_plan_end_utc": self.end,
            "accepted_source_observation_id": self.observation_id,
            "source_base_token": "f" * 64,
        }

    def operational_plan_context(self, reader, task_id: str):
        assert task_id == self.task_id
        return self.operational

    def source_acceptance_base_token(self, reader, target):
        assert target.proposal_kind == "wfm_plan_reconciliation"
        assert target.task_id == self.task_id
        return self.base_token


def _scope():
    run_id = new_uuid4()
    observation_id = new_uuid4()
    task_id = new_uuid4()
    rfc_id = new_uuid4()
    start_id = new_uuid4()
    end_id = new_uuid4()
    task_no = "TK00000000005555"
    rfc_no = "NC00000000006666"
    start = 2_300_000_000
    end = start + 3_600
    source_row = (
        run_id,
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
    evidence = PublishedWfmCompetingAttemptEvidence(
        source_observation_id=observation_id,
        import_run_id=run_id,
        task_no=task_no,
        parent_rfc_no=rfc_no,
        planned_start_field_id=start_id,
        planned_start_utc=start,
        planned_end_field_id=end_id,
        planned_end_utc=end,
    )
    return locals()


def test_plan_follow_on_builder_binds_exact_accepted_source_plan_and_owner_token() -> None:
    scope = _scope()
    reader = _SelectOnlyReader(scope["source_row"])
    wfm = _WfmReader(
        task_id=scope["task_id"],
        rfc_id=scope["rfc_id"],
        observation_id=scope["observation_id"],
        start=scope["start"],
        end=scope["end"],
        base_token="c" * 64,
        operational=None,
    )
    draft = build_wfm_plan_reconciliation_proposal(
        reader,
        import_run_id=scope["run_id"],
        source_observation_id=scope["observation_id"],
        rfc_reader=_RfcReader(scope["rfc_id"]),
        wfm_reader=wfm,
        evidence_provider=_EvidenceProvider(scope["evidence"]),
    )
    assert draft is not None
    assert draft.proposal_kind == "wfm_plan_reconciliation"
    assert draft.target_kind == "task_plan"
    assert draft.target_internal_id == scope["task_id"]
    assert draft.target_business_id == scope["task_no"]
    assert draft.risk_class == "high"
    assert draft.base_state_token_sha256 == "c" * 64
    assert [
        (
            change.ordinal,
            change.field_key,
            change.change_kind,
            change.value_kind,
            change.before_integer,
            change.after_integer,
            change.source_observation_field_id,
        )
        for change in draft.changes
    ] == [
        (0, "planned_start", "set", "instant", None, scope["start"], scope["start_id"]),
        (1, "planned_end", "set", "instant", None, scope["end"], scope["end_id"]),
    ]
    expected = sha256_canonical_json(
        {
            "schema": "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1",
            "source": {
                "import_run_id": scope["run_id"],
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
                "proposal_kind": "wfm_plan_reconciliation",
                "evidence_mode": "observed_row",
                "risk_class": "high",
                "target_kind": "task_plan",
                "target_internal_id": scope["task_id"],
                "target_business_id": scope["task_no"],
            },
            "changes": [change.fingerprint_object() for change in draft.changes],
        }
    )
    assert draft.proposal_fingerprint_sha256 == expected


def test_plan_follow_on_builder_emits_nothing_when_operational_plan_already_matches() -> None:
    scope = _scope()
    reader = _SelectOnlyReader(scope["source_row"])
    wfm = _WfmReader(
        task_id=scope["task_id"],
        rfc_id=scope["rfc_id"],
        observation_id=scope["observation_id"],
        start=scope["start"],
        end=scope["end"],
        base_token="d" * 64,
        operational={
            "plan_revision_id": new_uuid4(),
            "revision": 2,
            "start_utc": scope["start"],
            "end_utc": scope["end"],
            "origin": "manual",
            "source_observation_id": None,
        },
    )
    assert build_wfm_plan_reconciliation_proposal(
        reader,
        import_run_id=scope["run_id"],
        source_observation_id=scope["observation_id"],
        rfc_reader=_RfcReader(scope["rfc_id"]),
        wfm_reader=wfm,
        evidence_provider=_EvidenceProvider(scope["evidence"]),
    ) is None
