from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from soma.foundation.contracts.foundation import DurableJobClaim
from soma.foundation.errors import IntegrityFailure, JobClaimConflict, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes_bounded, loads_canonical_json
from soma.ticket_import.commands.finalize_run import ImportRunFinalizationService
from soma.ticket_import.commands.publish_staged_run import PublishStagedImportRunService
from soma.ticket_import.parsing.advanced_search import parse_advanced_search
from soma.ticket_import.parsing.discovery import (
    CandidateDescriptor,
    discover_advanced_search_automatic,
    discover_advanced_search_manual,
)
from soma.ticket_import.parsing.staging import stage_advanced_search_parse_batch
from soma.ticket_import.profiles.registry import require_profile_versions
from soma.ticket_import.reconciliation.staged import verify_staged_logical_run
from soma.ticket_import.repositories.runs import ImportRunRepository, SourceCheckpointRepository

from . import (
    SOURCE_CHECK_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    validate_source_check_checkpoint,
    validate_source_check_payload,
)


_JOB_JSON_BYTES = 65_536
_JOB_JSON_DEPTH = 8
_JOB_JSON_ITEMS = 512


class TicketImportSourceCheckWorker:
    """Advanced Search source-check conductor over durable bounded transitions."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._jobs = DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
        )
        self._runs = ImportRunRepository()
        self._publish = PublishStagedImportRunService(connection_factory)
        self._finalize = ImportRunFinalizationService(connection_factory)

    @staticmethod
    def _load_json(text: str, *, label: str) -> dict[str, Any]:
        try:
            value = loads_canonical_json(
                text,
                max_bytes=_JOB_JSON_BYTES,
                max_depth=_JOB_JSON_DEPTH,
                max_collection_items=_JOB_JSON_ITEMS,
            )
        except ValidationError as exc:
            raise IntegrityFailure(f"persisted {label} is not canonical JSON") from exc
        if not isinstance(value, dict):
            raise IntegrityFailure(f"persisted {label} must be an object")
        return value

    @classmethod
    def _payload(cls, claim: DurableJobClaim) -> dict[str, Any]:
        if claim.job_type != SOURCE_CHECK_JOB_TYPE or claim.contract_version != 1:
            raise ValidationError("claim is not ticket_import.source_check v1")
        payload = cls._load_json(claim.payload_json, label="source-check payload")
        try:
            validate_source_check_payload(payload)
        except ValidationError as exc:
            raise IntegrityFailure("persisted source-check payload violates its contract") from exc
        return payload

    @classmethod
    def _checkpoint(cls, claim: DurableJobClaim) -> dict[str, Any] | None:
        if claim.checkpoint_json is None:
            return None
        checkpoint = cls._load_json(claim.checkpoint_json, label="source-check checkpoint")
        try:
            validate_source_check_checkpoint(checkpoint)
        except ValidationError as exc:
            raise IntegrityFailure("persisted source-check checkpoint violates its contract") from exc
        return checkpoint

    @staticmethod
    def _profiles(payload: dict[str, Any]) -> dict[str, str]:
        source_family = str(payload["source_family"])
        expected = require_profile_versions(source_family)
        profiles = payload["profile_ids"]
        exact = {
            "source_profile_id": expected.source_profile_id,
            "header_registry_id": expected.header_registry_id,
            "vocabulary_registry_id": expected.vocabulary_registry_id,
            "parser_profile_id": expected.parser_profile_id,
        }
        if profiles != exact:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "source-check job uses stale profile IDs")
        return exact

    def _automatic_directory(self, payload: dict[str, Any]) -> str:
        locator = payload["source_locator"]
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT contract_name,contract_version,value_json,revision FROM setting_values "
                "WHERE setting_key=?",
                (locator["setting_key"],),
            ).fetchone()
        if row is None:
            raise SomaError("IMPORT_SOURCE_NOT_CONFIGURED", "automatic import directory is not configured")
        if int(row[3]) != int(locator["setting_revision"]):
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "automatic import directory revision changed")
        try:
            value = loads_canonical_json(
                str(row[2]),
                max_bytes=4096,
                max_depth=2,
                max_collection_items=4,
            )
        except ValidationError as exc:
            raise IntegrityFailure("persisted import directory setting is invalid") from exc
        if not isinstance(value, dict) or set(value) != {"path"} or not isinstance(value["path"], str):
            raise IntegrityFailure("persisted import directory setting has the wrong shape")
        return str(value["path"])

    def _discover(self, payload: dict[str, Any]) -> CandidateDescriptor:
        if payload["source_family"] != "advanced_search_sr":
            raise SomaError(
                "IMPORT_SOURCE_PROFILE_MISMATCH",
                "source-check runtime parser is not yet implemented for this source family",
            )
        locator = payload["source_locator"]
        if payload["invocation_kind"] == "manual":
            return discover_advanced_search_manual(str(locator["selected_path"]))
        return discover_advanced_search_automatic(self._automatic_directory(payload))

    @staticmethod
    def _locator_fingerprint(candidate: CandidateDescriptor) -> str:
        encoded = canonical_json_bytes_bounded(
            {
                "path": str(Path(candidate.path)),
                "filename": candidate.filename,
                "stable_size_bytes": candidate.stable_size_bytes,
                "stable_mtime_ns": candidate.stable_mtime_ns,
                "chronology_kind": candidate.chronology_kind,
                "chronology_value": candidate.chronology_value,
            },
            max_bytes=8192,
            max_depth=2,
            max_collection_items=12,
        )
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _candidate_identity(cls, candidate: CandidateDescriptor) -> dict[str, object]:
        return {
            "filename": candidate.filename,
            "stable_size_bytes": candidate.stable_size_bytes,
            "stable_mtime_ns": candidate.stable_mtime_ns,
            "source_chronology_kind": candidate.chronology_kind,
            "source_chronology_value": candidate.chronology_value,
            "locator_fingerprint": cls._locator_fingerprint(candidate),
        }

    @staticmethod
    def _command_id(schema: str, payload: dict[str, object]) -> str:
        encoded = canonical_json_bytes_bounded(
            {"schema": schema, **payload},
            max_bytes=8192,
            max_depth=3,
            max_collection_items=16,
        )
        value = bytearray(hashlib.sha256(encoded).digest()[:16])
        value[6] = (value[6] & 0x0F) | 0x40
        value[8] = (value[8] & 0x3F) | 0x80
        return str(uuid.UUID(bytes=bytes(value)))

    def _start_run(
        self,
        claim: DurableJobClaim,
        payload: dict[str, Any],
        profiles: dict[str, str],
        candidate: CandidateDescriptor,
    ) -> tuple[str, dict[str, Any]]:
        import_run_id = new_uuid4()
        checkpoint = {
            "phase": "validating",
            "import_run_id": import_run_id,
            "run_revision": 1,
            "parser_profile_id": profiles["parser_profile_id"],
            "candidate_identity": self._candidate_identity(candidate),
            "last_committed_batch": None,
        }
        with UnitOfWork(self._factory) as uow:
            if self._jobs.assert_claim_current(uow, claim) is not None:
                raise JobClaimConflict("fresh source-check claim unexpectedly gained a checkpoint")
            self._runs.start_validating_run(
                uow,
                import_run_id=import_run_id,
                source_family=str(payload["source_family"]),
                invocation_kind=str(payload["invocation_kind"]),
                profile_ids=profiles,
                candidate_filename=candidate.filename,
                candidate_file_size_bytes=candidate.stable_size_bytes,
                candidate_stable_mtime_ns=candidate.stable_mtime_ns,
                candidate_chronology_kind=candidate.chronology_kind,
                candidate_chronology_value=candidate.chronology_value,
                started_at_utc=utc_epoch_seconds(),
            )
            self._jobs.checkpoint_in_uow(uow, claim, checkpoint)
        return import_run_id, checkpoint

    @staticmethod
    def _require_candidate_match(checkpoint: dict[str, Any], candidate: CandidateDescriptor) -> None:
        if checkpoint["candidate_identity"] != TicketImportSourceCheckWorker._candidate_identity(candidate):
            raise SomaError("IMPORT_FILE_UNSTABLE", "source candidate changed since the durable checkpoint")

    def _stage(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        candidate: CandidateDescriptor,
    ) -> dict[str, Any]:
        parsed = parse_advanced_search(candidate.path, preflight=candidate.preflight)
        batch = checkpoint.get("last_committed_batch")
        start_index = 0 if batch is None else int(batch.get("next_index", -1))
        global_staged = False if batch is None else bool(batch.get("global_findings_staged", False))
        if start_index < 0 or start_index > len(parsed.rows):
            raise IntegrityFailure("source-check parser checkpoint is invalid")
        while True:
            with UnitOfWork(self._factory) as uow:
                result = stage_advanced_search_parse_batch(
                    uow,
                    import_run_id=str(checkpoint["import_run_id"]),
                    expected_run_revision=int(checkpoint["run_revision"]),
                    parsed=parsed,
                    start_index=start_index,
                    include_global_findings=not global_staged,
                )
                global_staged = True
                staged_checkpoint = {
                    **checkpoint,
                    "phase": "staging",
                    "last_committed_batch": {
                        "next_index": result.next_index,
                        "global_findings_staged": global_staged,
                    },
                }
                self._jobs.checkpoint_in_uow(uow, claim, staged_checkpoint)
            checkpoint = staged_checkpoint
            start_index = result.next_index
            if result.complete:
                return checkpoint

    def _publishing_checkpoint(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        with ReadSnapshot(self._factory) as snapshot:
            verified = verify_staged_logical_run(
                snapshot.connection,
                import_run_id=str(checkpoint["import_run_id"]),
                expected_run_revision=int(checkpoint["run_revision"]),
            )
        prior_batch = checkpoint.get("last_committed_batch")
        publishing = {
            **checkpoint,
            "phase": "publishing",
            "last_committed_batch": {
                **({} if prior_batch is None else prior_batch),
                "logical_fingerprint_sha256": verified.fingerprint.logical_fingerprint_sha256,
            },
        }
        self._jobs.checkpoint(claim, publishing)
        return publishing, verified.fingerprint.logical_fingerprint_sha256

    @staticmethod
    def _checkpoint_fingerprint(checkpoint: dict[str, Any]) -> str:
        batch = checkpoint.get("last_committed_batch")
        fingerprint = None if not isinstance(batch, dict) else batch.get("logical_fingerprint_sha256")
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in fingerprint)
        ):
            raise IntegrityFailure("publishing source-check checkpoint lacks its logical fingerprint")
        return fingerprint

    def _finalize_noop(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        source_family: str,
        fingerprint: str,
        run_revision: int,
    ) -> None:
        import_run_id = str(checkpoint["import_run_id"])
        batch = checkpoint.get("last_committed_batch")
        expected_checkpoint_revision = (
            None if not isinstance(batch, dict) else batch.get("source_checkpoint_revision")
        )
        if type(expected_checkpoint_revision) is not int or expected_checkpoint_revision < 1:
            raise IntegrityFailure("noop checkpoint lacks its reviewed source-checkpoint revision")
        final_command_id = self._command_id(
            "SOMA_RECORD_NEWER_IDENTICAL_COMMAND_ID_V1",
            {"job_id": claim.job_id, "import_run_id": import_run_id, "fingerprint": fingerprint},
        )
        candidate = checkpoint["candidate_identity"]
        self._finalize.record_newer_identical_source_check(
            command_id=final_command_id,
            job_id=claim.job_id,
            import_run_id=import_run_id,
            expected_run_revision=run_revision,
            expected_checkpoint_revision=expected_checkpoint_revision,
            chronology_kind=str(candidate["source_chronology_kind"]),
            chronology_value=int(candidate["source_chronology_value"]),
            logical_fingerprint=fingerprint,
        )

    def _publish_run(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        profiles: dict[str, str],
        fingerprint: str,
    ) -> None:
        import_run_id = str(checkpoint["import_run_id"])
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT run_state,revision,logical_fingerprint_sha256 FROM import_runs WHERE import_run_id=?",
                (import_run_id,),
            ).fetchone()
        if row is None:
            raise IntegrityFailure("source-check import run disappeared before publication")
        existing_state = str(row[0])
        existing_revision = int(row[1])
        existing_fingerprint = None if row[2] is None else str(row[2])
        if existing_state == "validating":
            command_id = self._command_id(
                "SOMA_PUBLISH_STAGED_RUN_COMMAND_ID_V1",
                {
                    "job_id": claim.job_id,
                    "claim_run_id": claim.run_id,
                    "attempt_ordinal": claim.attempt_ordinal,
                    "import_run_id": import_run_id,
                    "fingerprint": fingerprint,
                },
            )
            result = self._publish.publish(
                command_id=command_id,
                claim=claim,
                import_run_id=import_run_id,
                expected_run_revision=int(checkpoint["run_revision"]),
                profile_ids=profiles,
                publishing_checkpoint=checkpoint,
                logical_fingerprint=fingerprint,
            )
            run_state = result.run_state
            run_revision = result.revision
        else:
            if existing_fingerprint != fingerprint:
                raise IntegrityFailure("published source-check run fingerprint changed")
            run_state = existing_state
            run_revision = existing_revision

        if run_state == "noop_pending_checkpoint":
            with ReadSnapshot(self._factory) as snapshot:
                source_checkpoint = SourceCheckpointRepository.get(
                    snapshot.connection,
                    str(self._payload(claim)["source_family"]),
                )
            if source_checkpoint is None:
                raise IntegrityFailure("newer-identical run has no source checkpoint")
            prior_batch = checkpoint.get("last_committed_batch")
            noop_checkpoint = {
                **checkpoint,
                "phase": "noop_checkpoint",
                "run_revision": run_revision,
                "last_committed_batch": {
                    **({} if prior_batch is None else prior_batch),
                    "source_checkpoint_revision": source_checkpoint.revision,
                },
            }
            self._jobs.checkpoint(claim, noop_checkpoint)
            self._finalize_noop(
                claim,
                noop_checkpoint,
                source_family=str(self._payload(claim)["source_family"]),
                fingerprint=fingerprint,
                run_revision=run_revision,
            )
        self._jobs.complete(claim)

    def run(self, claim: DurableJobClaim) -> str:
        payload = self._payload(claim)
        profiles = self._profiles(payload)
        checkpoint = self._checkpoint(claim)
        candidate = self._discover(payload)
        if candidate.profile_id != profiles["source_profile_id"]:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "discovered candidate uses the wrong profile")

        if checkpoint is None:
            _import_run_id, checkpoint = self._start_run(claim, payload, profiles, candidate)
        else:
            self._require_candidate_match(checkpoint, candidate)

        phase = str(checkpoint["phase"])
        if phase in {"validating", "staging"}:
            checkpoint = self._stage(claim, checkpoint, candidate)
            checkpoint, fingerprint = self._publishing_checkpoint(claim, checkpoint)
        elif phase in {"publishing", "noop_checkpoint"}:
            fingerprint = self._checkpoint_fingerprint(checkpoint)
        else:
            raise IntegrityFailure("source-check claim is in an unsupported execution phase")

        if phase == "noop_checkpoint":
            self._finalize_noop(
                claim,
                checkpoint,
                source_family=str(payload["source_family"]),
                fingerprint=fingerprint,
                run_revision=int(checkpoint["run_revision"]),
            )
            self._jobs.complete(claim)
            return str(checkpoint["import_run_id"])
        self._publish_run(claim, checkpoint, profiles, fingerprint)
        return str(checkpoint["import_run_id"])


def run(claim: DurableJobClaim, connection_factory: ConnectionFactory) -> str:
    return TicketImportSourceCheckWorker(connection_factory).run(claim)


__all__ = ["TicketImportSourceCheckWorker", "run"]
