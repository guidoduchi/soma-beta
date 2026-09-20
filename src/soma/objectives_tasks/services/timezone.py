from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.settings_service import SettingService
from soma.reference.audit_registry import build_reference_audit_registry

from ..audit_registry import build_objectives_tasks_audit_registry
from ..settings import (
    OBJECTIVE_TIMEZONE_KEY,
    build_objective_timezone_setting_registry,
)


@dataclass(frozen=True, slots=True)
class ObjectiveTimezoneMutationResult:
    iana_timezone: str
    source: str
    revision: int
    replayed: bool
    no_change: bool


def _audit_registry():
    registry = build_objectives_tasks_audit_registry()
    registry.extend(build_reference_audit_registry())
    return registry


class ObjectiveTimezoneService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        setting_registry = build_objective_timezone_setting_registry()
        self._settings = SettingService(connection_factory, setting_registry)
        self._definition = setting_registry.require(OBJECTIVE_TIMEZONE_KEY)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_audit_registry()),
        )

    @staticmethod
    def _from_execution(result: CommandExecutionResult) -> ObjectiveTimezoneMutationResult:
        payload = result.response
        if (
            result.response_schema != "ObjectiveTimezoneV1"
            or result.response_version != 1
            or not isinstance(payload, dict)
            or set(payload) != {"iana_timezone", "source", "revision"}
        ):
            raise IntegrityFailure("Objective timezone replay result contract is invalid")
        timezone = payload.get("iana_timezone")
        source = payload.get("source")
        revision = payload.get("revision")
        if not isinstance(timezone, str) or source != "PERSISTED":
            raise IntegrityFailure("Objective timezone replay result value/source is invalid")
        if type(revision) is not int or revision <= 0:
            raise IntegrityFailure("Objective timezone replay result revision is invalid")
        return ObjectiveTimezoneMutationResult(
            iana_timezone=timezone,
            source=source,
            revision=revision,
            replayed=result.replayed,
            no_change=result.no_change,
        )

    def set_timezone(
        self,
        *,
        command_id: str,
        new_timezone: str,
        base_revision: int | None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ObjectiveTimezoneMutationResult:
        canonical = self._definition.validate_value(new_timezone)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetObjectiveTimezone",
            target_type="setting",
            target_id=OBJECTIVE_TIMEZONE_KEY,
            semantic_payload={"iana_timezone": canonical},
            base_revisions={} if base_revision is None else {"setting": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            participant = self._settings.prepare_write_participant(
                uow,
                command_id=command_id,
                setting_key=OBJECTIVE_TIMEZONE_KEY,
                base_revision=base_revision,
                value=canonical,
                actor_kind=actor_kind,
                actor_id=actor_id,
            )
            response = {
                "iana_timezone": str(participant.value),
                "source": "PERSISTED",
                "revision": participant.new_revision,
            }
            if participant.no_change:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="ObjectiveTimezoneV1",
                    response_version=1,
                    response=response,
                )

            def apply(inner: UnitOfWork):
                generic_audit = participant.apply(inner)
                semantic_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="objective.timezone_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="setting",
                    target_id=OBJECTIVE_TIMEZONE_KEY,
                    command_id=command_id,
                    payload_schema="ObjectiveTimezoneAuditV1",
                    payload_version=1,
                    payload={
                        "setting_key": OBJECTIVE_TIMEZONE_KEY,
                        "prior_revision": participant.prior_revision,
                        "new_revision": participant.new_revision,
                        "iana_timezone": str(participant.value),
                        "change_kind": participant.change_kind,
                    },
                    resulting_event_refs=(
                        AuditResultRef("setting", OBJECTIVE_TIMEZONE_KEY),
                    ),
                )
                return (generic_audit, semantic_audit)

            return PreparedMutation(
                False,
                "setting",
                OBJECTIVE_TIMEZONE_KEY,
                apply,
                response_schema="ObjectiveTimezoneV1",
                response_version=1,
                response=response,
            )

        return self._from_execution(self._boundary.execute(envelope, prepare))


__all__ = ["ObjectiveTimezoneMutationResult", "ObjectiveTimezoneService"]
