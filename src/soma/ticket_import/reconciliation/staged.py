from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.ticket_import.repositories.observations import (
    SourceObservationRepository,
    StagedFindingEvidence,
    StagedObservationEvidence,
    StagedRunEvidence,
)
from soma.ticket_import.repositories.runs import SourceCheckpointRepository, SourceCheckpointState

from .engine import (
    LogicalField,
    LogicalFinding,
    LogicalFingerprintResult,
    LogicalRow,
    classify_replay,
    compute_logical_fingerprint,
    field_logical_sha256,
    row_logical_sha256,
)


@dataclass(frozen=True, slots=True)
class VerifiedLogicalObservation:
    source_observation_id: str
    row: LogicalRow


@dataclass(frozen=True, slots=True)
class VerifiedStagedRun:
    evidence: StagedRunEvidence
    observations: tuple[VerifiedLogicalObservation, ...]
    global_findings: tuple[LogicalFinding, ...]
    fingerprint: LogicalFingerprintResult
    checkpoint: SourceCheckpointState | None
    replay_classification: str


def _logical_finding(finding: StagedFindingEvidence) -> LogicalFinding:
    return LogicalFinding(
        finding_code=finding.finding_code,
        severity=finding.severity,
        scope_kind=finding.scope_kind,
        field_key=finding.field_key,
    )


def _verified_row(observation: StagedObservationEvidence) -> LogicalRow:
    fields: list[LogicalField] = []
    for persisted in observation.fields:
        logical = LogicalField(
            field_key=persisted.field_key,
            field_class=persisted.field_class,
            value_state=persisted.value_state,
            value_kind=persisted.value_kind,
            vocabulary_id=persisted.vocabulary_id,
            source_text=persisted.source_text,
            normalized_text=persisted.normalized_text,
            integer_value=persisted.integer_value,
        )
        if field_logical_sha256(logical) != persisted.field_logical_sha256:
            raise IntegrityFailure("staged field logical hash disagrees with recomputed SOMA_IMPORT_LOGICAL_V1 evidence")
        fields.append(logical)

    row = LogicalRow(
        identity_state=observation.identity_state,
        entity_kind=observation.entity_kind,
        canonical_primary_id=observation.canonical_primary_id,
        canonical_parent_rfc_no=observation.canonical_parent_rfc_no,
        fields=tuple(fields),
        findings=tuple(_logical_finding(finding) for finding in observation.findings),
    )
    if row_logical_sha256(row) != observation.row_logical_sha256:
        raise IntegrityFailure("staged row logical hash disagrees with recomputed SOMA_IMPORT_LOGICAL_V1 evidence")
    return row


def verify_staged_logical_run(
    reader: Any,
    *,
    import_run_id: str,
    expected_run_revision: int,
) -> VerifiedStagedRun:
    evidence = SourceObservationRepository.load_validating_evidence(
        reader,
        import_run_id=import_run_id,
        expected_run_revision=expected_run_revision,
    )
    observations = tuple(
        VerifiedLogicalObservation(
            source_observation_id=observation.source_observation_id,
            row=_verified_row(observation),
        )
        for observation in evidence.observations
    )
    global_findings = tuple(_logical_finding(finding) for finding in evidence.global_findings)
    fingerprint = compute_logical_fingerprint(
        source_family=evidence.source_family,
        source_profile_id=evidence.source_profile_id,
        header_registry_id=evidence.header_registry_id,
        vocabulary_registry_id=evidence.vocabulary_registry_id,
        parser_profile_id=evidence.parser_profile_id,
        rows=tuple(observation.row for observation in observations),
        global_findings=global_findings,
    )

    checkpoint = SourceCheckpointRepository.get(reader, evidence.source_family)
    if checkpoint is not None and checkpoint.chronology_kind != evidence.candidate_chronology_kind:
        raise IntegrityFailure("source checkpoint chronology kind disagrees with the validating source-profile chronology")
    replay_classification = classify_replay(
        candidate_chronology=evidence.candidate_chronology_value,
        logical_fingerprint_sha256=fingerprint.logical_fingerprint_sha256,
        checkpoint_chronology=None if checkpoint is None else checkpoint.chronology_value,
        checkpoint_logical_fingerprint_sha256=None if checkpoint is None else checkpoint.logical_fingerprint,
    )
    return VerifiedStagedRun(
        evidence=evidence,
        observations=observations,
        global_findings=global_findings,
        fingerprint=fingerprint,
        checkpoint=checkpoint,
        replay_classification=replay_classification,
    )
