from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, PersistenceFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.profiles.registry import require_profile_versions

from ..audit_registry import build_ticket_import_audit_registry
from ..jobs import (
    SOURCE_CHECK_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    derive_source_check_dedupe_key,
    validate_source_check_payload,
)


@dataclass(frozen=True, slots=True)
class ImportJobAccepted:
    job_id: str
    source_family: str
    invocation_kind: str
    replayed: bool


class StartTicketSourceImportCheckService:
    """Short public command that records intent and enqueues durable import work."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._jobs = DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
        )
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_ticket_import_audit_registry()),
        )

    @staticmethod
    def _profiles(source_family: str) -> dict[str, str]:
        versions = require_profile_versions(source_family)
        return {
            "source_profile_id": versions.source_profile_id,
            "header_registry_id": versions.header_registry_id,
            "vocabulary_registry_id": versions.vocabulary_registry_id,
            "parser_profile_id": versions.parser_profile_id,
        }

    @staticmethod
    def _automatic_setting_key(source_family: str) -> str:
        return (
            "advanced_search_import_directory"
            if source_family == "advanced_search_sr"
            else "rfc_wfm_import_directory"
        )

    @staticmethod
    def _manual_locator(*, selected_path: str | None, setting_revision: int | None) -> dict[str, object]:
        if not isinstance(selected_path, str) or setting_revision is not None:
            raise ValidationError("manual import requires selected_path and no setting_revision")
        return {"kind": "manual_path", "selected_path": selected_path}

    @staticmethod
    def _automatic_locator(
        *,
        source_family: str,
        selected_path: str | None,
        setting_revision: int | None,
    ) -> tuple[str, dict[str, object]]:
        if selected_path is not None:
            raise ValidationError("automatic import does not accept selected_path")
        if setting_revision is not None and (type(setting_revision) is not int or setting_revision < 1):
            raise ValidationError("setting_revision must be a positive integer when supplied")
        setting_key = StartTicketSourceImportCheckService._automatic_setting_key(source_family)
        return setting_key, {"kind": "configured_setting", "setting_key": setting_key}

    @staticmethod
    def _from_execution(execution: CommandExecutionResult) -> ImportJobAccepted:
        if execution.response_schema != "ImportJobAcceptedV1" or execution.response_version != 1:
            raise IntegrityFailure("import job acceptance result schema/version is invalid")
        response = execution.response
        if not isinstance(response, dict) or set(response) != {
            "job_id",
            "source_family",
            "invocation_kind",
        }:
            raise IntegrityFailure("import job acceptance result shape is invalid")
        if not all(isinstance(response[key], str) and response[key] for key in response):
            raise IntegrityFailure("import job acceptance result fields are invalid")
        return ImportJobAccepted(
            job_id=str(response["job_id"]),
            source_family=str(response["source_family"]),
            invocation_kind=str(response["invocation_kind"]),
            replayed=execution.replayed,
        )

    def start(
        self,
        *,
        command_id: str,
        source_family: str,
        invocation_kind: str,
        selected_path: str | None = None,
        setting_revision: int | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ImportJobAccepted:
        profiles = self._profiles(source_family)
        automatic_setting_key: str | None = None
        if invocation_kind == "manual":
            request_locator = self._manual_locator(
                selected_path=selected_path,
                setting_revision=setting_revision,
            )
        elif invocation_kind == "automatic":
            automatic_setting_key, request_locator = self._automatic_locator(
                source_family=source_family,
                selected_path=selected_path,
                setting_revision=setting_revision,
            )
        else:
            raise ValidationError("invocation_kind must be automatic or manual")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="StartTicketSourceImportCheck",
            target_type="import_source_family",
            target_id=source_family,
            semantic_payload={
                "source_family": source_family,
                "invocation_kind": invocation_kind,
                "source_locator": request_locator,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            if invocation_kind == "automatic":
                assert automatic_setting_key is not None
                row = uow.connection.execute(
                    "SELECT revision FROM setting_values WHERE setting_key=?",
                    (automatic_setting_key,),
                ).fetchone()
                if row is None:
                    raise SomaError("IMPORT_SOURCE_NOT_CONFIGURED", "automatic import directory is not configured")
                current_setting_revision = int(row[0])
                if setting_revision is not None and current_setting_revision != setting_revision:
                    raise SomaError("STALE_REVISION", "automatic import directory setting changed")
                source_locator: dict[str, object] = {
                    "kind": "setting_revision",
                    "setting_key": automatic_setting_key,
                    "setting_revision": current_setting_revision,
                }
            else:
                source_locator = request_locator

            payload = {
                "source_family": source_family,
                "invocation_kind": invocation_kind,
                "profile_ids": profiles,
                "source_locator": source_locator,
                "requested_by_command_id": command_id,
            }
            validate_source_check_payload(payload)
            dedupe_key = derive_source_check_dedupe_key(payload)
            holder: dict[str, str] = {}

            def apply(inner: UnitOfWork) -> AuditEventInput:
                job_id = self._jobs.enqueue_or_coalesce(
                    inner,
                    SOURCE_CHECK_JOB_TYPE,
                    1,
                    payload,
                    dedupe_key,
                )
                holder["job_id"] = job_id
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="ticket_import.check_started",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="import_source_family",
                    target_id=source_family,
                    command_id=command_id,
                    job_id=job_id,
                    payload_schema="ImportCheckStartedAuditV1",
                    payload_version=1,
                    payload={
                        "source_family": source_family,
                        "invocation_kind": invocation_kind,
                        "job_id": job_id,
                    },
                    resulting_event_refs=(AuditResultRef("durable_job", job_id),),
                )

            def response_factory(_inner: UnitOfWork) -> dict[str, object]:
                job_id = holder.get("job_id")
                if job_id is None:
                    raise PersistenceFailure("started import job identity disappeared before response capture")
                return {
                    "job_id": job_id,
                    "source_family": source_family,
                    "invocation_kind": invocation_kind,
                }

            return PreparedMutation(
                False,
                "import_source_family",
                source_family,
                apply,
                response_schema="ImportJobAcceptedV1",
                response_factory=response_factory,
            )

        return self._from_execution(self._boundary.execute(envelope, prepare))


__all__ = ["ImportJobAccepted", "StartTicketSourceImportCheckService"]
