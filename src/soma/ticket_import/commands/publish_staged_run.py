from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.contracts.foundation import DurableJobClaim
from soma.foundation.errors import (
    IntegrityFailure,
    JobClaimConflict,
    PersistenceFailure,
    SomaError,
    ValidationError,
)
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes_bounded, loads_canonical_json
from soma.objectives_tasks.services.wfm_import import WfmImportReader

from ..audit_registry import build_ticket_import_audit_registry
from ..jobs import (
    SOURCE_CHECK_JOB_TYPE,
    SR_REAPPEARANCE_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    validate_source_check_checkpoint,
    validate_source_check_payload,
)
from ..reconciliation.advanced_search import build_advanced_search_sr_source_projection_proposals
from ..reconciliation.advanced_search_contact import (
    build_advanced_search_sr_contact_reconciliation_proposals,
)
from ..reconciliation.advanced_search_current_handler import (
    build_advanced_search_sr_current_handler_reconciliation_proposals,
)
from ..reconciliation.advanced_search_customer import (
    build_advanced_search_sr_customer_reconciliation_proposals,
)
from ..reconciliation.advanced_search_disappearance import (
    PopulationAbsenceProposalDraft,
    build_advanced_search_sr_disappearance_proposals,
)
from ..reconciliation.advanced_search_identity import build_advanced_search_sr_identity_proposals
from ..reconciliation.engine import ProposalChangeDraft, ReconciliationProposalDraft, row_logical_sha256
from ..reconciliation.rfc_enhanced import build_rfc_enhanced_source_projection_proposals
from ..reconciliation.rfc_enhanced_customer import build_rfc_enhanced_customer_reconciliation_proposals
from ..reconciliation.rfc_enhanced_identity import build_rfc_enhanced_identity_proposals
from ..reconciliation.rfc_enhanced_sr_link import build_rfc_enhanced_sr_link_candidate_proposals
from ..reconciliation.staged import VerifiedStagedRun, verify_staged_logical_run
from ..reconciliation.wfm_provisional_eligibility import build_wfm_service_provider_proposals
from ..repositories.findings import NormalizedFindingEvidence, SourceFindingRepository
from ..repositories.observations import SourceObservationRepository
from ..repositories.proposals import (
    PendingProposalWrite,
    ProposalChangeRecord,
    ProposalRepository,
)
from ..repositories.runs import (
    ImportRunPublicationResult,
    ImportRunRepository,
    SourceCheckpointState,
)


_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_PROFILE_KEYS = frozenset(
    {"source_profile_id", "header_registry_id", "vocabulary_registry_id", "parser_profile_id"}
)
_JOB_JSON_BYTES = 65_536
_JOB_JSON_DEPTH = 8
_JOB_JSON_ITEMS = 512
_PUBLICATION_RESULT_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "noop_pending_checkpoint", "noop"}
)
_NON_NOOP_CLASSIFICATIONS = frozenset(
    {"NEW_SOURCE", "CHRONOLOGY_CONTENT_CONFLICT", "OLDER_SOURCE_RECOVERY_REQUIRED"}
)
_NOOP_CLASSIFICATIONS = frozenset({"EXACT_REPLAY_NOOP", "NEWER_IDENTICAL_NO_DOMAIN_CHANGE"})


@dataclass(frozen=True, slots=True)
class PublishStagedImportRunResult:
    import_run_id: str
    run_state: str
    revision: int
    proposal_count: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class _RunAuthority:
    import_run_id: str
    source_family: str
    invocation_kind: str
    source_profile_id: str
    header_registry_id: str
    vocabulary_registry_id: str
    parser_profile_id: str
    candidate_filename: str
    candidate_file_size_bytes: int
    candidate_stable_mtime_ns: int
    candidate_chronology_kind: str
    candidate_chronology_value: int
    run_state: str
    revision: int

    @property
    def profile_ids(self) -> dict[str, str]:
        return {
            "source_profile_id": self.source_profile_id,
            "header_registry_id": self.header_registry_id,
            "vocabulary_registry_id": self.vocabulary_registry_id,
            "parser_profile_id": self.parser_profile_id,
        }


@dataclass(frozen=True, slots=True)
class _PublicationPreflight:
    replay_classification: str
    checkpoint: SourceCheckpointState | None
    proposal_writes: tuple[PendingProposalWrite, ...]
    reconciliation_findings: tuple[NormalizedFindingEvidence, ...]
    target_state: str


class PublishStagedImportRunService:
    """Final atomic LLD-04 publication boundary for staged Ticket Import evidence."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._runs = ImportRunRepository()
        self._proposals = ProposalRepository()
        self._jobs = DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
        )
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_ticket_import_audit_registry()),
        )

    @staticmethod
    def _require_sha256(value: str, *, label: str) -> str:
        if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
            raise ValidationError(f"{label} must be lowercase SHA-256 hex")
        return value

    @staticmethod
    def _validate_profile_ids(value: dict[str, object]) -> dict[str, str]:
        if not isinstance(value, dict) or set(value) != _PROFILE_KEYS:
            raise ValidationError("profile_ids must contain exactly the registered profile keys")
        resolved: dict[str, str] = {}
        for key in sorted(_PROFILE_KEYS):
            item = value[key]
            if not isinstance(item, str) or not item:
                raise ValidationError("profile_ids values must be nonempty strings")
            try:
                item.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise ValidationError("profile_ids values must be valid Unicode") from exc
            resolved[key] = item
        return resolved

    @staticmethod
    def _load_job_json(text: str, *, label: str) -> dict[str, Any]:
        try:
            value = loads_canonical_json(
                text,
                max_bytes=_JOB_JSON_BYTES,
                max_depth=_JOB_JSON_DEPTH,
                max_collection_items=_JOB_JSON_ITEMS,
            )
        except ValidationError as exc:
            raise IntegrityFailure(f"{label} is not canonical registered durable-job JSON") from exc
        if not isinstance(value, dict):
            raise IntegrityFailure(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _run_authority(reader: Any, import_run_id: str) -> _RunAuthority:
        row = reader.execute(
            "SELECT import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,"
            "vocabulary_registry_id,parser_profile_id,candidate_filename,candidate_file_size_bytes,"
            "candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,run_state,revision "
            "FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
        return _RunAuthority(
            import_run_id=require_uuid4(str(row[0])),
            source_family=str(row[1]),
            invocation_kind=str(row[2]),
            source_profile_id=str(row[3]),
            header_registry_id=str(row[4]),
            vocabulary_registry_id=str(row[5]),
            parser_profile_id=str(row[6]),
            candidate_filename=str(row[7]),
            candidate_file_size_bytes=int(row[8]),
            candidate_stable_mtime_ns=int(row[9]),
            candidate_chronology_kind=str(row[10]),
            candidate_chronology_value=int(row[11]),
            run_state=str(row[12]),
            revision=int(row[13]),
        )

    @staticmethod
    def _candidate_matches_run(candidate: dict[str, Any], run: _RunAuthority) -> bool:
        return (
            candidate.get("filename") == run.candidate_filename
            and candidate.get("stable_size_bytes") == run.candidate_file_size_bytes
            and candidate.get("stable_mtime_ns") == run.candidate_stable_mtime_ns
            and candidate.get("source_chronology_kind") == run.candidate_chronology_kind
            and candidate.get("source_chronology_value") == run.candidate_chronology_value
        )

    @staticmethod
    def _change_record(change: ProposalChangeDraft) -> ProposalChangeRecord:
        return ProposalChangeRecord(
            ordinal=change.ordinal,
            field_key=change.field_key,
            change_kind=change.change_kind,
            value_kind=change.value_kind,
            before_text=change.before_text,
            after_text=change.after_text,
            before_integer=change.before_integer,
            after_integer=change.after_integer,
            source_observation_field_id=change.source_observation_field_id,
        )

    @classmethod
    def _observed_pending_write(cls, draft: ReconciliationProposalDraft) -> PendingProposalWrite:
        return PendingProposalWrite(
            import_run_id=draft.import_run_id,
            evidence_mode=draft.evidence_mode,
            source_observation_id=draft.source_observation_id,
            prior_source_observation_id=None,
            proposal_kind=draft.proposal_kind,
            target_kind=draft.target_kind,
            target_internal_id=draft.target_internal_id,
            target_business_id=draft.target_business_id,
            risk_class=draft.risk_class,
            base_state_token=draft.base_state_token_sha256,
            proposal_fingerprint=draft.proposal_fingerprint_sha256,
            changes=tuple(cls._change_record(change) for change in draft.changes),
        )

    @classmethod
    def _absence_pending_write(cls, draft: PopulationAbsenceProposalDraft) -> PendingProposalWrite:
        return PendingProposalWrite(
            import_run_id=draft.import_run_id,
            evidence_mode="population_absence",
            source_observation_id=None,
            prior_source_observation_id=draft.prior_source_observation_id,
            proposal_kind="sr_source_disappearance_review",
            target_kind="source_presence",
            target_internal_id=draft.target_internal_id,
            target_business_id=draft.target_business_id,
            risk_class="high",
            base_state_token=draft.base_state_token_sha256,
            proposal_fingerprint=draft.proposal_fingerprint_sha256,
            changes=tuple(cls._change_record(change) for change in draft.changes),
        )

    @classmethod
    def _advanced_search_proposal_writes(
        cls,
        reader: Any,
        verified: VerifiedStagedRun,
    ) -> tuple[PendingProposalWrite, ...]:
        if verified.evidence.source_family != "advanced_search_sr":
            raise ValidationError("Advanced Search proposal builder received another source family")
        writes: list[PendingProposalWrite] = []
        for observation in verified.observations:
            row = observation.row
            if row.identity_state != "valid" or row.entity_kind != "service_request":
                continue
            kwargs = {
                "import_run_id": verified.evidence.import_run_id,
                "source_observation_id": observation.source_observation_id,
            }
            builders = (
                build_advanced_search_sr_identity_proposals,
                build_advanced_search_sr_source_projection_proposals,
                build_advanced_search_sr_customer_reconciliation_proposals,
                build_advanced_search_sr_contact_reconciliation_proposals,
                build_advanced_search_sr_current_handler_reconciliation_proposals,
            )
            for builder in builders:
                result = builder(reader, **kwargs)
                writes.extend(cls._observed_pending_write(draft) for draft in result.proposals)

        if verified.replay_classification != "OLDER_SOURCE_RECOVERY_REQUIRED":
            disappearance = build_advanced_search_sr_disappearance_proposals(
                reader,
                import_run_id=verified.evidence.import_run_id,
                logical_fingerprint_sha256=verified.fingerprint.logical_fingerprint_sha256,
            )
            writes.extend(cls._absence_pending_write(draft) for draft in disappearance)
        return tuple(writes)

    @classmethod
    def _rfc_enhanced_proposal_writes(
        cls,
        reader: Any,
        verified: VerifiedStagedRun,
    ) -> tuple[PendingProposalWrite, ...]:
        if verified.evidence.source_family != "rfc_enhanced":
            raise ValidationError("Enhanced RFC proposal builder received another source family")
        writes: list[PendingProposalWrite] = []
        for observation in verified.observations:
            row = observation.row
            if row.identity_state != "valid" or row.entity_kind != "rfc":
                continue
            kwargs = {
                "import_run_id": verified.evidence.import_run_id,
                "source_observation_id": observation.source_observation_id,
            }
            builders = (
                build_rfc_enhanced_identity_proposals,
                build_rfc_enhanced_source_projection_proposals,
                build_rfc_enhanced_customer_reconciliation_proposals,
                build_rfc_enhanced_sr_link_candidate_proposals,
            )
            for builder in builders:
                result = builder(reader, **kwargs)
                writes.extend(cls._observed_pending_write(draft) for draft in result.proposals)
        return tuple(writes)

    @staticmethod
    def _wfm_reconciliation_findings(
        reader: Any,
        verified: VerifiedStagedRun,
    ) -> tuple[NormalizedFindingEvidence, ...]:
        if verified.evidence.source_family != "wfm_service_provider":
            raise ValidationError("WFM reconciliation finding builder received another source family")
        groups: dict[str, list[tuple[str, str]]] = {}
        for observation in verified.observations:
            row = observation.row
            if row.identity_state != "valid" or row.entity_kind != "wfm" or row.canonical_primary_id is None:
                continue
            groups.setdefault(row.canonical_primary_id, []).append(
                (observation.source_observation_id, row_logical_sha256(row))
            )

        findings: list[NormalizedFindingEvidence] = []
        for task_no in sorted(groups):
            variants = groups[task_no]
            distinct_hashes = {digest for _observation_id, digest in variants}
            if len(distinct_hashes) != 1:
                continue
            canonical_observation_id = min(observation_id for observation_id, _digest in variants)
            status = WfmImportReader.task_no_status(reader, task_no)
            if status == "RETIRED":
                findings.append(
                    NormalizedFindingEvidence(
                        source_observation_id=canonical_observation_id,
                        field_key="task_no",
                        finding_code="WFM_TASK_ID_RETIRED",
                        severity="error",
                        scope_kind="identity",
                        message_text="WFM Task No is permanently retired and cannot be reused from source evidence",
                    )
                )
            elif status not in {"ACTIVE", "ABSENT"}:
                raise IntegrityFailure("LLD-05 returned an invalid WFM Task No status during publication")
        return tuple(findings)

    @classmethod
    def _wfm_proposal_writes(
        cls,
        reader: Any,
        verified: VerifiedStagedRun,
    ) -> tuple[PendingProposalWrite, ...]:
        if verified.evidence.source_family != "wfm_service_provider":
            raise ValidationError("WFM proposal builder received another source family")
        writes: list[PendingProposalWrite] = []
        for observation in verified.observations:
            row = observation.row
            if row.identity_state != "valid" or row.entity_kind != "wfm":
                continue
            result = build_wfm_service_provider_proposals(
                reader,
                import_run_id=verified.evidence.import_run_id,
                source_observation_id=observation.source_observation_id,
            )
            writes.extend(cls._observed_pending_write(draft) for draft in result.proposals)
        return tuple(writes)

    @staticmethod
    def _persist_exact_proposal_set(
        uow: UnitOfWork,
        repository: ProposalRepository,
        *,
        import_run_id: str,
        writes: tuple[PendingProposalWrite, ...],
    ) -> int:
        persisted_ids: set[str] = set()
        for write in writes:
            persisted = repository.insert_or_reuse_pending(uow, write)
            if persisted.proposal_id in persisted_ids:
                raise IntegrityFailure("publication proposal builders produced duplicate material proposals")
            persisted_ids.add(persisted.proposal_id)
        rows = uow.connection.execute(
            "SELECT reconciliation_proposal_id,proposal_state FROM reconciliation_proposals "
            "WHERE import_run_id=? ORDER BY reconciliation_proposal_id ASC",
            (import_run_id,),
        ).fetchall()
        if any(str(row[1]) != "pending" for row in rows):
            raise IntegrityFailure("validating publication contains a non-pending reconciliation proposal")
        actual_ids = {require_uuid4(str(row[0])) for row in rows}
        if actual_ids != persisted_ids or len(rows) != len(persisted_ids):
            raise IntegrityFailure("validating publication contains proposal evidence outside the exact generated set")
        return len(persisted_ids)

    @staticmethod
    def _response(uow: UnitOfWork, import_run_id: str) -> dict[str, object]:
        row = uow.connection.execute(
            "SELECT run_state,revision,proposal_count FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        if row is None:
            raise PersistenceFailure("publication response run disappeared before commit")
        return {
            "import_run_id": import_run_id,
            "run_state": str(row[0]),
            "revision": int(row[1]),
            "proposal_count": int(row[2]),
        }

    @staticmethod
    def _result_from_execution(execution: CommandExecutionResult) -> PublishStagedImportRunResult:
        if execution.response_schema != "ImportRunPublicationResultV1" or execution.response_version != 1:
            raise IntegrityFailure("publication result schema/version is invalid")
        response = execution.response
        if not isinstance(response, dict) or set(response) != {
            "import_run_id",
            "run_state",
            "revision",
            "proposal_count",
        }:
            raise IntegrityFailure("publication result payload is invalid")
        import_run_id = response.get("import_run_id")
        run_state = response.get("run_state")
        revision = response.get("revision")
        proposal_count = response.get("proposal_count")
        if (
            not isinstance(import_run_id, str)
            or not isinstance(run_state, str)
            or run_state not in _PUBLICATION_RESULT_STATES
            or type(revision) is not int
            or revision <= 0
            or type(proposal_count) is not int
            or proposal_count < 0
        ):
            raise IntegrityFailure("publication result fields are invalid")
        require_uuid4(import_run_id)
        return PublishStagedImportRunResult(
            import_run_id=import_run_id,
            run_state=run_state,
            revision=revision,
            proposal_count=proposal_count,
            replayed=execution.replayed,
        )

    @staticmethod
    def _published_audit(
        *,
        command_id: str,
        claim: DurableJobClaim,
        run: _RunAuthority,
        result: ImportRunPublicationResult,
        actor_kind: str,
        actor_id: str | None,
    ) -> AuditEventInput:
        counters = result.counters
        return AuditEventInput(
            audit_event_id=new_uuid4(),
            action_type="ticket_import.run_published",
            action_version=1,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type="import_run",
            target_id=run.import_run_id,
            command_id=command_id,
            job_id=claim.job_id,
            import_run_id=run.import_run_id,
            payload_schema="ImportRunPublishedAuditV1",
            payload_version=1,
            payload={
                "import_run_id": run.import_run_id,
                "source_family": run.source_family,
                "run_state": result.run_state,
                "profile_ids": run.profile_ids,
                "candidate_filename": run.candidate_filename,
                "candidate_chronology_kind": run.candidate_chronology_kind,
                "candidate_chronology_value": run.candidate_chronology_value,
                "logical_fingerprint": result.logical_fingerprint,
                "counts": {
                    "observed_row_count": counters.observed_row_count,
                    "valid_identity_count": counters.valid_identity_count,
                    "invalid_row_count": counters.invalid_row_count,
                    "warning_count": counters.warning_count,
                    "proposal_count": counters.proposal_count,
                    "pending_proposal_count": counters.pending_proposal_count,
                    "accepted_proposal_count": counters.accepted_proposal_count,
                    "rejected_proposal_count": counters.rejected_proposal_count,
                    "deferred_proposal_count": counters.deferred_proposal_count,
                },
                "revision": result.revision,
            },
            resulting_event_refs=(AuditResultRef("import_run", run.import_run_id),),
        )

    @staticmethod
    def _noop_audit(
        *,
        command_id: str,
        claim: DurableJobClaim,
        run: _RunAuthority,
        result: ImportRunPublicationResult,
        replay_classification: str,
        actor_kind: str,
        actor_id: str | None,
    ) -> AuditEventInput:
        return AuditEventInput(
            audit_event_id=new_uuid4(),
            action_type="ticket_import.run_noop_classified",
            action_version=1,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type="import_run",
            target_id=run.import_run_id,
            command_id=command_id,
            job_id=claim.job_id,
            import_run_id=run.import_run_id,
            payload_schema="ImportRunNoopClassifiedAuditV1",
            payload_version=1,
            payload={
                "import_run_id": run.import_run_id,
                "source_family": run.source_family,
                "replay_classification": replay_classification,
                "run_state": result.run_state,
                "candidate_chronology_kind": run.candidate_chronology_kind,
                "candidate_chronology_value": run.candidate_chronology_value,
                "logical_fingerprint": result.logical_fingerprint,
                "revision": result.revision,
            },
            resulting_event_refs=(AuditResultRef("import_run", run.import_run_id),),
        )

    def _committed_receipt_exists(self, command_id: str) -> bool:
        with ReadSnapshot(self._factory) as snapshot:
            return (
                snapshot.connection.execute(
                    "SELECT 1 FROM command_receipts WHERE command_id=? LIMIT 1",
                    (command_id,),
                ).fetchone()
                is not None
            )

    @staticmethod
    def _target_state(
        classification: str,
        proposal_writes: tuple[PendingProposalWrite, ...],
    ) -> str:
        if classification == "EXACT_REPLAY_NOOP":
            return "noop"
        if classification == "NEWER_IDENTICAL_NO_DOMAIN_CHANGE":
            return "noop_pending_checkpoint"
        if classification == "NEW_SOURCE":
            return "waiting_review" if proposal_writes else "staged"
        if classification in {"CHRONOLOGY_CONTENT_CONFLICT", "OLDER_SOURCE_RECOVERY_REQUIRED"}:
            return "recovery_required"
        raise IntegrityFailure("staged replay classification is outside the closed publication vocabulary")

    def _preflight_publication(
        self,
        *,
        import_run_id: str,
        expected_run_revision: int,
        expected_fingerprint: str,
    ) -> _PublicationPreflight:
        with ReadSnapshot(self._factory) as snapshot:
            verified = verify_staged_logical_run(
                snapshot.connection,
                import_run_id=import_run_id,
                expected_run_revision=expected_run_revision,
            )
            if not hmac.compare_digest(
                verified.fingerprint.logical_fingerprint_sha256,
                expected_fingerprint,
            ):
                raise SomaError("IMPORT_RUN_STALE", "recomputed staged logical fingerprint changed")
            classification = verified.replay_classification
            if classification not in _NON_NOOP_CLASSIFICATIONS | _NOOP_CLASSIFICATIONS:
                raise IntegrityFailure("staged replay classification is outside the closed publication vocabulary")
            if classification in _NOOP_CLASSIFICATIONS:
                existing = snapshot.connection.execute(
                    "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=?",
                    (import_run_id,),
                ).fetchone()
                if existing is None or int(existing[0]) != 0:
                    raise IntegrityFailure("replay/noop classification found pre-existing proposal authority")
                proposal_writes: tuple[PendingProposalWrite, ...] = ()
                reconciliation_findings: tuple[NormalizedFindingEvidence, ...] = ()
            elif verified.evidence.source_family == "advanced_search_sr":
                proposal_writes = self._advanced_search_proposal_writes(snapshot.connection, verified)
                reconciliation_findings = ()
            elif verified.evidence.source_family == "rfc_enhanced":
                proposal_writes = self._rfc_enhanced_proposal_writes(snapshot.connection, verified)
                reconciliation_findings = ()
            elif verified.evidence.source_family == "wfm_service_provider":
                proposal_writes = self._wfm_proposal_writes(snapshot.connection, verified)
                reconciliation_findings = self._wfm_reconciliation_findings(snapshot.connection, verified)
            else:
                raise SomaError(
                    "IMPORT_RUN_STALE",
                    "changed-source publication orchestration is not yet implemented for this source family",
                )
            return _PublicationPreflight(
                replay_classification=classification,
                checkpoint=verified.checkpoint,
                proposal_writes=proposal_writes,
                reconciliation_findings=reconciliation_findings,
                target_state=self._target_state(classification, proposal_writes),
            )

    def publish(
        self,
        *,
        command_id: str,
        claim: DurableJobClaim,
        import_run_id: str,
        expected_run_revision: int,
        profile_ids: dict[str, object],
        publishing_checkpoint: dict[str, object],
        logical_fingerprint: str,
        actor_kind: str = "system",
        actor_id: str | None = None,
    ) -> PublishStagedImportRunResult:
        canonical_run_id = require_uuid4(import_run_id)
        if type(expected_run_revision) is not int or expected_run_revision < 1:
            raise ValidationError("expected_run_revision must be a positive integer")
        expected_profiles = self._validate_profile_ids(profile_ids)
        validate_source_check_checkpoint(publishing_checkpoint)
        if publishing_checkpoint.get("phase") != "publishing":
            raise ValidationError("publication checkpoint phase must be publishing")
        expected_fingerprint = self._require_sha256(
            logical_fingerprint,
            label="logical_fingerprint",
        )
        candidate_identity = publishing_checkpoint.get("candidate_identity")
        if not isinstance(candidate_identity, dict):
            raise ValidationError("publication checkpoint requires candidate_identity")
        canonical_json_bytes_bounded(
            candidate_identity,
            max_bytes=_JOB_JSON_BYTES,
            max_depth=4,
            max_collection_items=32,
        )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="PublishStagedImportRun",
            target_type="import_run",
            target_id=canonical_run_id,
            semantic_payload={
                "job_id": claim.job_id,
                "claim_run_id": claim.run_id,
                "claim_attempt_ordinal": claim.attempt_ordinal,
                "import_run_id": canonical_run_id,
                "profile_ids": expected_profiles,
                "candidate_identity": candidate_identity,
                "logical_fingerprint": expected_fingerprint,
            },
            base_revisions={"import_run": expected_run_revision},
            authorizing_fingerprints={"logical_fingerprint": expected_fingerprint},
        )
        envelope.request_hash()

        def response_factory(inner: UnitOfWork) -> dict[str, object]:
            return self._response(inner, canonical_run_id)

        if self._committed_receipt_exists(command_id):
            def replay_only_prepare(_uow: UnitOfWork) -> PreparedMutation:
                raise PersistenceFailure("committed publication receipt disappeared after replay probe")

            return self._result_from_execution(
                self._boundary.execute(envelope, replay_only_prepare)
            )

        preflight = self._preflight_publication(
            import_run_id=canonical_run_id,
            expected_run_revision=expected_run_revision,
            expected_fingerprint=expected_fingerprint,
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current_checkpoint_json = self._jobs.assert_claim_current(uow, claim)
            if current_checkpoint_json is None:
                raise IntegrityFailure("running source-check publication claim has no current checkpoint")
            current_checkpoint = self._load_job_json(
                current_checkpoint_json,
                label="current source-check checkpoint",
            )
            try:
                validate_source_check_checkpoint(current_checkpoint)
            except ValidationError as exc:
                raise IntegrityFailure("persisted source-check checkpoint violates its registered contract") from exc
            if current_checkpoint != publishing_checkpoint:
                raise JobClaimConflict("source-check publication checkpoint changed")
            if (
                current_checkpoint.get("phase") != "publishing"
                or current_checkpoint.get("import_run_id") != canonical_run_id
                or current_checkpoint.get("run_revision") != expected_run_revision
                or current_checkpoint.get("parser_profile_id") != expected_profiles["parser_profile_id"]
                or current_checkpoint.get("candidate_identity") != candidate_identity
            ):
                raise JobClaimConflict("source-check publication checkpoint does not authorize this run")

            claim_payload = self._load_job_json(claim.payload_json, label="source-check claim payload")
            try:
                validate_source_check_payload(claim_payload)
            except ValidationError as exc:
                raise IntegrityFailure("persisted source-check claim payload violates its registered contract") from exc
            if claim.job_type != SOURCE_CHECK_JOB_TYPE or claim.contract_version != 1:
                raise IntegrityFailure("publication claim is not ticket_import.source_check v1")

            run = self._run_authority(uow.connection, canonical_run_id)
            if run.run_state != "validating" or run.revision != expected_run_revision:
                raise SomaError("IMPORT_RUN_STALE", "import run changed before publication")
            if (
                claim_payload.get("source_family") != run.source_family
                or claim_payload.get("invocation_kind") != run.invocation_kind
                or claim_payload.get("profile_ids") != expected_profiles
                or run.profile_ids != expected_profiles
            ):
                raise SomaError("IMPORT_RUN_STALE", "source-check claim/profile authority does not match the validating run")
            if not self._candidate_matches_run(candidate_identity, run):
                raise SomaError("IMPORT_RUN_STALE", "publication candidate identity does not match the validating run")

            verified = verify_staged_logical_run(
                uow.connection,
                import_run_id=canonical_run_id,
                expected_run_revision=expected_run_revision,
            )
            if not hmac.compare_digest(
                verified.fingerprint.logical_fingerprint_sha256,
                expected_fingerprint,
            ):
                raise SomaError("IMPORT_RUN_STALE", "recomputed staged logical fingerprint changed")
            classification = verified.replay_classification
            if classification != preflight.replay_classification:
                raise SomaError("IMPORT_RUN_STALE", "source replay classification changed after publication preflight")
            if verified.checkpoint != preflight.checkpoint:
                raise SomaError("IMPORT_RUN_STALE", "source checkpoint changed after publication preflight")
            if classification not in _NON_NOOP_CLASSIFICATIONS | _NOOP_CLASSIFICATIONS:
                raise IntegrityFailure("staged replay classification is outside the closed publication vocabulary")

            if classification in _NOOP_CLASSIFICATIONS:
                existing = uow.connection.execute(
                    "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=?",
                    (canonical_run_id,),
                ).fetchone()
                if existing is None or int(existing[0]) != 0:
                    raise IntegrityFailure("replay/noop classification found pre-existing proposal authority")
                proposal_writes: tuple[PendingProposalWrite, ...] = ()
                reconciliation_findings: tuple[NormalizedFindingEvidence, ...] = ()
            elif run.source_family == "advanced_search_sr":
                proposal_writes = preflight.proposal_writes
                reconciliation_findings = ()
            elif run.source_family == "rfc_enhanced":
                proposal_writes = preflight.proposal_writes
                reconciliation_findings = ()
            elif run.source_family == "wfm_service_provider":
                proposal_writes = preflight.proposal_writes
                reconciliation_findings = self._wfm_reconciliation_findings(uow.connection, verified)
                if reconciliation_findings != preflight.reconciliation_findings:
                    raise SomaError(
                        "IMPORT_RUN_STALE",
                        "WFM retired-identity reconciliation evidence changed after publication preflight",
                    )
            else:
                raise SomaError(
                    "IMPORT_RUN_STALE",
                    "changed-source publication orchestration is not yet implemented for this source family",
                )

            target_state = self._target_state(classification, proposal_writes)
            if target_state != preflight.target_state:
                raise IntegrityFailure("publication target state disagrees with preflight classification")

            def apply(inner: UnitOfWork) -> AuditEventInput:
                now = utc_epoch_seconds()
                if classification in _NOOP_CLASSIFICATIONS:
                    SourceObservationRepository.cleanup_unpublished(
                        inner,
                        import_run_id=canonical_run_id,
                        expected_run_revision=expected_run_revision,
                    )
                    published = self._runs.publish_validating_run(
                        inner,
                        import_run_id=canonical_run_id,
                        expected_revision=expected_run_revision,
                        logical_fingerprint=expected_fingerprint,
                        staged_at_utc=now,
                        target_state=target_state,
                        completed_at_utc=now if target_state == "noop" else None,
                    )
                    return self._noop_audit(
                        command_id=command_id,
                        claim=claim,
                        run=run,
                        result=published,
                        replay_classification=classification,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                    )

                proposal_count = self._persist_exact_proposal_set(
                    inner,
                    self._proposals,
                    import_run_id=canonical_run_id,
                    writes=proposal_writes,
                )
                inserted_reconciliation_findings = SourceFindingRepository.append_reconciliation_findings_after_source_verification(
                    inner,
                    import_run_id=canonical_run_id,
                    expected_run_revision=expected_run_revision,
                    findings=reconciliation_findings,
                )
                if len(inserted_reconciliation_findings) != len(reconciliation_findings):
                    raise IntegrityFailure("publication reconciliation finding count disagrees with preflight")
                published = self._runs.publish_validating_run(
                    inner,
                    import_run_id=canonical_run_id,
                    expected_revision=expected_run_revision,
                    logical_fingerprint=expected_fingerprint,
                    staged_at_utc=now,
                    target_state=target_state,
                )
                if published.counters.proposal_count != proposal_count:
                    raise IntegrityFailure("publication proposal count disagrees with exact generated set")
                if run.source_family == "advanced_search_sr" and classification == "NEW_SOURCE":
                    payload = {
                        "import_run_id": canonical_run_id,
                        "source_family": "advanced_search_sr",
                        "published_run_revision": published.revision,
                        "requested_by_command_id": command_id,
                    }
                    self._jobs.enqueue_or_coalesce(
                        inner,
                        SR_REAPPEARANCE_JOB_TYPE,
                        1,
                        payload,
                        canonical_run_id,
                    )
                return self._published_audit(
                    command_id=command_id,
                    claim=claim,
                    run=run,
                    result=published,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                )

            return PreparedMutation(
                False,
                "import_run",
                canonical_run_id,
                apply,
                response_schema="ImportRunPublicationResultV1",
                response_factory=response_factory,
            )

        return self._result_from_execution(self._boundary.execute(envelope, prepare))
