from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.contracts.foundation import DurableJobClaim
from soma.foundation.errors import IntegrityFailure, JobClaimConflict, PersistenceFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes_bounded, loads_canonical_json
from soma.ticket_import.providers.sr_source_evidence import TicketImportSrSourceEvidenceProvider
from soma.ticket_import.providers.sr_source_presence import TicketImportSrSourcePresenceEvidenceProvider
from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.import_mutations import ServiceRequestImportMutationService
from soma.tickets.service_request_import_reader import ServiceRequestImportReader
from soma.tickets.sr_source_presence import SrSourceReappearanceMutation
from soma.tickets.validation import validate_official_sr_no

from ._json import (
    JOB_JSON_MAX_BYTES,
    JOB_JSON_MAX_COLLECTION_ITEMS,
    JOB_JSON_MAX_DEPTH,
    load_persisted_job_object,
)
from . import (
    SR_REAPPEARANCE_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    validate_reappearance_checkpoint,
    validate_reappearance_payload,
)


_PUBLISHED_NON_NOOP_STATES = frozenset(
    {"staged", "waiting_review", "partially_accepted", "accepted", "rejected"}
)
_COMMAND_SCHEMA = "SOMA_SR_REAPPEARANCE_COMMAND_ID_V1"
_RESPONSE_SCHEMA = "SrSourceReappearanceCommandResultV1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DEFAULT_PAGE_SIZE = 500


@dataclass(frozen=True, slots=True)
class SrReappearanceJobRunResult:
    job_id: str
    import_run_id: str
    processed_exact_count: int
    confirmed_count: int
    no_change_count: int
    conflict_skip_count: int
    duplicate_skip_count: int


@dataclass(frozen=True, slots=True)
class _ObservationRow:
    canonical_sr_no: str
    source_observation_id: str
    row_logical_sha256: str


class AdvancedSearchSrReappearanceWorker:
    """Bounded durable worker that clears reviewed Advanced Search absence warnings."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> None:
        if type(page_size) is not int or page_size < 1 or page_size > _DEFAULT_PAGE_SIZE:
            raise ValidationError("reappearance worker page_size must be in 1..500")
        self._factory = connection_factory
        self._page_size = page_size
        self._jobs = DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
        )
        self._reader = ServiceRequestImportReader()
        self._owner = ServiceRequestImportMutationService(
            TicketImportSrSourceEvidenceProvider(),
            source_presence_evidence_provider=TicketImportSrSourcePresenceEvidenceProvider(),
        )
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    @staticmethod
    def _canonical_json(value: dict[str, Any]) -> str:
        return canonical_json_bytes_bounded(
            value,
            max_bytes=JOB_JSON_MAX_BYTES,
            max_depth=JOB_JSON_MAX_DEPTH,
            max_collection_items=JOB_JSON_MAX_COLLECTION_ITEMS,
        ).decode("utf-8")

    @classmethod
    def _payload(cls, claim: DurableJobClaim) -> dict[str, Any]:
        if claim.job_type != SR_REAPPEARANCE_JOB_TYPE or claim.contract_version != 1:
            raise ValidationError("claim is not ticket_import.sr_reappearance_reconcile v1")
        payload = load_persisted_job_object(claim.payload_json, label="reappearance payload")
        try:
            validate_reappearance_payload(payload)
        except ValidationError as exc:
            raise IntegrityFailure("persisted reappearance payload violates its registered contract") from exc
        if cls._canonical_json(payload) != claim.payload_json:
            raise IntegrityFailure("persisted reappearance payload is noncanonical")
        return payload

    @classmethod
    def _checkpoint(
        cls,
        claim: DurableJobClaim,
        import_run_id: str,
    ) -> tuple[dict[str, Any], str | None]:
        if claim.checkpoint_json is None:
            value = {
                "import_run_id": import_run_id,
                "last_canonical_sr_no": None,
                "last_source_observation_id": None,
                "processed_exact_count": 0,
            }
            return value, None
        value = load_persisted_job_object(claim.checkpoint_json, label="reappearance checkpoint")
        try:
            validate_reappearance_checkpoint(value)
        except ValidationError as exc:
            raise IntegrityFailure("persisted reappearance checkpoint violates its registered contract") from exc
        if cls._canonical_json(value) != claim.checkpoint_json:
            raise IntegrityFailure("persisted reappearance checkpoint is noncanonical")
        if value["import_run_id"] != import_run_id:
            raise IntegrityFailure("reappearance checkpoint targets a different import run")
        return value, claim.checkpoint_json

    @staticmethod
    def _validate_run(reader: Any, payload: dict[str, Any]) -> None:
        row = reader.execute(
            "SELECT source_family,run_state,revision FROM import_runs WHERE import_run_id=?",
            (payload["import_run_id"],),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_RUN_STALE", "reappearance import run does not exist")
        if str(row[0]) != "advanced_search_sr":
            raise IntegrityFailure("reappearance import run belongs to the wrong source family")
        if str(row[1]) not in _PUBLISHED_NON_NOOP_STATES:
            raise SomaError(
                "IMPORT_RUN_STALE",
                "reappearance import run is not published non-noop authority",
            )
        if int(row[2]) < int(payload["published_run_revision"]):
            raise IntegrityFailure("reappearance import run revision regressed")
        exists = reader.execute(
            "SELECT 1 FROM source_observations WHERE import_run_id=? LIMIT 1",
            (payload["import_run_id"],),
        ).fetchone()
        if exists is None:
            raise IntegrityFailure("reappearance import run has no row-bearing population")

    @staticmethod
    def _row(raw: tuple[Any, ...]) -> _ObservationRow:
        if len(raw) != 3:
            raise IntegrityFailure("reappearance observation projection has the wrong shape")
        canonical_sr_no = validate_official_sr_no(str(raw[0]))
        source_observation_id = require_uuid4(str(raw[1]))
        row_hash = str(raw[2])
        if _SHA256.fullmatch(row_hash) is None:
            raise IntegrityFailure("reappearance observation has invalid logical hash")
        return _ObservationRow(canonical_sr_no, source_observation_id, row_hash)

    def _page(self, reader: Any, import_run_id: str, checkpoint: dict[str, Any]) -> tuple[_ObservationRow, ...]:
        last_sr = checkpoint["last_canonical_sr_no"]
        last_observation = checkpoint["last_source_observation_id"]
        if last_sr is None:
            rows = reader.execute(
                "SELECT canonical_primary_id,source_observation_id,row_logical_sha256 "
                "FROM source_observations WHERE import_run_id=? AND source_family='advanced_search_sr' "
                "AND entity_kind='service_request' AND identity_state='valid' "
                "AND canonical_primary_id IS NOT NULL AND presence_state='observed_valid_identity' "
                "ORDER BY canonical_primary_id ASC,source_observation_id ASC LIMIT ?",
                (import_run_id, self._page_size),
            ).fetchall()
        else:
            rows = reader.execute(
                "SELECT canonical_primary_id,source_observation_id,row_logical_sha256 "
                "FROM source_observations WHERE import_run_id=? AND source_family='advanced_search_sr' "
                "AND entity_kind='service_request' AND identity_state='valid' "
                "AND canonical_primary_id IS NOT NULL AND presence_state='observed_valid_identity' "
                "AND (canonical_primary_id>? OR (canonical_primary_id=? AND source_observation_id>?)) "
                "ORDER BY canonical_primary_id ASC,source_observation_id ASC LIMIT ?",
                (import_run_id, last_sr, last_sr, last_observation, self._page_size),
            ).fetchall()
        return tuple(self._row(tuple(row)) for row in rows)

    def _classification(self, reader: Any, import_run_id: str, canonical_sr_no: str) -> tuple[str, str | None]:
        rows = reader.execute(
            "SELECT source_observation_id,row_logical_sha256 FROM source_observations "
            "WHERE import_run_id=? AND source_family='advanced_search_sr' "
            "AND entity_kind='service_request' AND identity_state='valid' "
            "AND canonical_primary_id=? AND presence_state='observed_valid_identity' "
            "ORDER BY source_observation_id ASC",
            (import_run_id, canonical_sr_no),
        ).fetchall()
        if not rows:
            raise IntegrityFailure("reappearance observation group disappeared")
        observation_ids: list[str] = []
        hashes: set[str] = set()
        for raw in rows:
            observation_ids.append(require_uuid4(str(raw[0])))
            row_hash = str(raw[1])
            if _SHA256.fullmatch(row_hash) is None:
                raise IntegrityFailure("reappearance observation group contains invalid logical hash")
            hashes.add(row_hash)
        if len(hashes) > 1:
            return "conflict", None
        return ("unique" if len(observation_ids) == 1 else "equivalent"), observation_ids[0]

    @staticmethod
    def derive_command_id(
        *,
        job_id: str,
        import_run_id: str,
        canonical_sr_no: str,
        source_observation_id: str,
    ) -> str:
        semantic = {
            "schema": _COMMAND_SCHEMA,
            "job_id": require_uuid4(job_id),
            "import_run_id": require_uuid4(import_run_id),
            "canonical_sr_no": validate_official_sr_no(canonical_sr_no),
            "source_observation_id": require_uuid4(source_observation_id),
        }
        encoded = canonical_json_bytes_bounded(
            semantic,
            max_bytes=2048,
            max_depth=2,
            max_collection_items=8,
        )
        value = bytearray(hashlib.sha256(encoded).digest()[:16])
        value[6] = (value[6] & 0x0F) | 0x40
        value[8] = (value[8] & 0x3F) | 0x80
        return str(uuid.UUID(bytes=bytes(value)))

    @staticmethod
    def _response(
        *,
        outcome: str,
        job_id: str,
        import_run_id: str,
        canonical_sr_no: str,
        source_observation_id: str,
        service_request_id: str | None,
        presence_event_id: str | None,
    ) -> dict[str, object]:
        return {
            "outcome": outcome,
            "job_id": job_id,
            "import_run_id": import_run_id,
            "canonical_sr_no": canonical_sr_no,
            "source_observation_id": source_observation_id,
            "service_request_id": service_request_id,
            "presence_event_id": presence_event_id,
        }

    @staticmethod
    def _validate_execution(execution: CommandExecutionResult) -> str:
        if execution.response_schema != _RESPONSE_SCHEMA or execution.response_version != 1:
            raise IntegrityFailure("reappearance command result schema/version is invalid")
        response = execution.response
        if not isinstance(response, dict) or set(response) != {
            "outcome",
            "job_id",
            "import_run_id",
            "canonical_sr_no",
            "source_observation_id",
            "service_request_id",
            "presence_event_id",
        }:
            raise IntegrityFailure("reappearance command result shape is invalid")
        outcome = response.get("outcome")
        if outcome not in {"REAPPEARANCE_CONFIRMED", "NO_CHANGE"}:
            raise IntegrityFailure("reappearance command result outcome is invalid")
        return str(outcome)

    def _execute_representative(
        self,
        claim: DurableJobClaim,
        payload: dict[str, Any],
        observation: _ObservationRow,
        expected_checkpoint_json: str | None,
    ) -> str:
        command_id = self.derive_command_id(
            job_id=claim.job_id,
            import_run_id=payload["import_run_id"],
            canonical_sr_no=observation.canonical_sr_no,
            source_observation_id=observation.source_observation_id,
        )
        semantic_payload = {
            "job_id": claim.job_id,
            "import_run_id": payload["import_run_id"],
            "canonical_sr_no": observation.canonical_sr_no,
            "source_observation_id": observation.source_observation_id,
        }
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReconcileSrSourceReappearance",
            target_type="sr_source_reappearance",
            target_id=observation.source_observation_id,
            semantic_payload=semantic_payload,
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current_checkpoint_json = self._jobs.assert_claim_current(uow, claim)
            if current_checkpoint_json != expected_checkpoint_json:
                raise JobClaimConflict("reappearance checkpoint changed before owner dispatch")
            target = self._reader.get_by_official(uow.connection, observation.canonical_sr_no)
            if target is None:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema=_RESPONSE_SCHEMA,
                    response=self._response(
                        outcome="NO_CHANGE",
                        job_id=claim.job_id,
                        import_run_id=payload["import_run_id"],
                        canonical_sr_no=observation.canonical_sr_no,
                        source_observation_id=observation.source_observation_id,
                        service_request_id=None,
                        presence_event_id=None,
                    ),
                )
            service_request_id = require_uuid4(str(target["service_request_id"]))
            state = self._reader.current_source_presence(
                uow.connection,
                service_request_id,
                "advanced_search_sr",
            )
            if not state.warning_active or state.active_disappearance_event_id is None:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema=_RESPONSE_SCHEMA,
                    response=self._response(
                        outcome="NO_CHANGE",
                        job_id=claim.job_id,
                        import_run_id=payload["import_run_id"],
                        canonical_sr_no=observation.canonical_sr_no,
                        source_observation_id=observation.source_observation_id,
                        service_request_id=service_request_id,
                        presence_event_id=None,
                    ),
                )

            holder: dict[str, Any] = {}
            mutation = SrSourceReappearanceMutation(
                service_request_id=service_request_id,
                expected_active_disappearance_event_id=state.active_disappearance_event_id,
                import_run_id=payload["import_run_id"],
                source_observation_id=observation.source_observation_id,
                accepted_command_id=command_id,
            )

            def apply(inner: UnitOfWork):
                result = self._owner.apply_source_reappearance(inner, mutation)
                holder["result"] = result
                return result.audit_events

            def response_factory(_inner: UnitOfWork) -> dict[str, object]:
                result = holder.get("result")
                if result is None:
                    raise PersistenceFailure("reappearance owner result disappeared before response capture")
                return self._response(
                    outcome="REAPPEARANCE_CONFIRMED",
                    job_id=claim.job_id,
                    import_run_id=payload["import_run_id"],
                    canonical_sr_no=observation.canonical_sr_no,
                    source_observation_id=observation.source_observation_id,
                    service_request_id=service_request_id,
                    presence_event_id=result.presence_event_id,
                )

            return PreparedMutation(
                False,
                "service_request",
                service_request_id,
                apply,
                response_schema=_RESPONSE_SCHEMA,
                response_factory=response_factory,
            )

        execution = self._boundary.execute(envelope, prepare)
        return self._validate_execution(execution)

    def run(self, claim: DurableJobClaim) -> SrReappearanceJobRunResult:
        payload = self._payload(claim)
        checkpoint, expected_checkpoint_json = self._checkpoint(claim, payload["import_run_id"])
        confirmed = no_change = conflicts = duplicates = 0

        while True:
            with ReadSnapshot(self._factory) as snapshot:
                self._validate_run(snapshot.connection, payload)
                page = self._page(snapshot.connection, payload["import_run_id"], checkpoint)
            if not page:
                self._jobs.complete(claim)
                return SrReappearanceJobRunResult(
                    job_id=claim.job_id,
                    import_run_id=payload["import_run_id"],
                    processed_exact_count=int(checkpoint["processed_exact_count"]),
                    confirmed_count=confirmed,
                    no_change_count=no_change,
                    conflict_skip_count=conflicts,
                    duplicate_skip_count=duplicates,
                )

            classifications: dict[str, tuple[str, str | None]] = {}
            with ReadSnapshot(self._factory) as snapshot:
                self._validate_run(snapshot.connection, payload)
                for sr_no in dict.fromkeys(row.canonical_sr_no for row in page):
                    classifications[sr_no] = self._classification(
                        snapshot.connection,
                        payload["import_run_id"],
                        sr_no,
                    )

            for observation in page:
                classification, representative = classifications[observation.canonical_sr_no]
                if classification == "conflict":
                    conflicts += 1
                elif representative != observation.source_observation_id:
                    duplicates += 1
                else:
                    outcome = self._execute_representative(
                        claim,
                        payload,
                        observation,
                        expected_checkpoint_json,
                    )
                    if outcome == "REAPPEARANCE_CONFIRMED":
                        confirmed += 1
                    else:
                        no_change += 1

                checkpoint = {
                    "import_run_id": payload["import_run_id"],
                    "last_canonical_sr_no": observation.canonical_sr_no,
                    "last_source_observation_id": observation.source_observation_id,
                    "processed_exact_count": int(checkpoint["processed_exact_count"]) + 1,
                }
                self._jobs.checkpoint(claim, checkpoint)
                expected_checkpoint_json = self._canonical_json(checkpoint)


def run(claim: DurableJobClaim, connection_factory: ConnectionFactory) -> SrReappearanceJobRunResult:
    """Canonical handler entry point registered as ticket_import.jobs.sr_reappearance.run."""

    return AdvancedSearchSrReappearanceWorker(connection_factory).run(claim)


__all__ = [
    "AdvancedSearchSrReappearanceWorker",
    "SrReappearanceJobRunResult",
    "run",
]
