from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .validation import validate_official_sr_no

SOURCE_FAMILY = "advanced_search_sr"
WARNING_CODE = "SR_SOURCE_DISAPPEARANCE_REVIEWED"


class SrSourcePresenceEvidenceProvider(Protocol):
    def validate_disappearance_acceptance(
        self,
        reader: Any,
        proposal_id: str,
        sr_id: str,
        source_family: str,
        import_run_id: str,
        prior_source_observation_id: str,
        command_context: dict[str, object],
    ) -> str: ...

    def validate_reappearance_evidence(
        self,
        reader: Any,
        sr_id: str,
        source_family: str,
        import_run_id: str,
        source_observation_id: str,
        command_context: dict[str, object],
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class SrSourcePresenceState:
    service_request_id: str
    source_family: str
    latest_event_id: str | None
    latest_event_kind: str | None
    active_disappearance_event_id: str | None
    warning_active: bool
    base_token_sha256: str


@dataclass(frozen=True, slots=True)
class SrSourcePresenceApplyResult:
    service_request_id: str
    source_family: str
    presence_event_id: str
    event_kind: str
    prior_presence_event_id: str | None
    warning_active: bool
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]


@dataclass(frozen=True, slots=True)
class SrSourceDisappearanceMutation:
    service_request_id: str
    base_state_token: str
    reconciliation_proposal_id: str
    import_run_id: str
    prior_source_observation_id: str
    accepted_command_id: str
    proposal_revision: int
    proposal_fingerprint: str
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class SrSourceReappearanceMutation:
    service_request_id: str
    expected_active_disappearance_event_id: str
    import_run_id: str
    source_observation_id: str
    accepted_command_id: str
    actor_kind: str = "system"
    actor_id: str | None = None


class ServiceRequestSourcePresenceRepository:
    @staticmethod
    def _identity(reader: Any, service_request_id: str) -> tuple[str | None, int]:
        canonical_id = require_uuid4(service_request_id)
        row = reader.execute(
            "SELECT official_sr_no,revision FROM service_requests WHERE service_request_id=?",
            (canonical_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Service Request does not exist")
        official = None if row[0] is None else validate_official_sr_no(str(row[0]))
        return official, int(row[1])

    @classmethod
    def current(cls, reader: Any, service_request_id: str, source_family: str) -> SrSourcePresenceState:
        if source_family != SOURCE_FAMILY:
            raise ValidationError("unsupported Service Request source family")
        official_sr_no, revision = cls._identity(reader, service_request_id)
        rows = reader.execute(
            "SELECT e.sr_source_presence_event_id,e.event_kind "
            "FROM sr_source_presence_events e LEFT JOIN sr_source_presence_events successor "
            "ON successor.prior_presence_event_id=e.sr_source_presence_event_id "
            "WHERE e.service_request_id=? AND e.source_family=? AND successor.sr_source_presence_event_id IS NULL",
            (service_request_id, source_family),
        ).fetchall()
        if len(rows) > 1:
            raise IntegrityFailure("Service Request source-presence history has multiple current heads")
        latest_id = latest_kind = None
        if rows:
            latest_id = require_uuid4(str(rows[0][0]))
            latest_kind = str(rows[0][1])
            if latest_kind not in {"disappearance_reviewed", "reappearance_confirmed"}:
                raise IntegrityFailure("Service Request source-presence head has invalid event kind")
        active_id = latest_id if latest_kind == "disappearance_reviewed" else None
        token = sha256_canonical_json(
            {
                "schema": "SOMA_SR_SOURCE_PRESENCE_BASE_V1",
                "service_request_id": require_uuid4(service_request_id),
                "official_sr_no": official_sr_no,
                "service_request_revision": revision,
                "source_family": source_family,
                "latest_event_id": latest_id,
                "latest_event_kind": latest_kind,
                "active_disappearance_event_id": active_id,
            }
        )
        return SrSourcePresenceState(
            service_request_id=service_request_id,
            source_family=source_family,
            latest_event_id=latest_id,
            latest_event_kind=latest_kind,
            active_disappearance_event_id=active_id,
            warning_active=active_id is not None,
            base_token_sha256=token,
        )

    @classmethod
    def base_token(cls, reader: Any, service_request_id: str, source_family: str) -> str:
        official, _revision = cls._identity(reader, service_request_id)
        if official is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "source presence requires official Service Request identity")
        return cls.current(reader, service_request_id, source_family).base_token_sha256

    @staticmethod
    def history(reader: Any, service_request_id: str, source_family: str) -> tuple[dict[str, object], ...]:
        if source_family != SOURCE_FAMILY:
            raise ValidationError("unsupported Service Request source family")
        rows = reader.execute(
            "SELECT sr_source_presence_event_id,event_kind,prior_presence_event_id,import_run_id,"
            "source_observation_id,prior_source_observation_id,reconciliation_proposal_id,"
            "accepted_command_id,recorded_at_utc FROM sr_source_presence_events "
            "WHERE service_request_id=? AND source_family=? ORDER BY recorded_at_utc,sr_source_presence_event_id",
            (require_uuid4(service_request_id), source_family),
        ).fetchall()
        return tuple(
            {
                "presence_event_id": str(row[0]),
                "event_kind": str(row[1]),
                "prior_presence_event_id": None if row[2] is None else str(row[2]),
                "import_run_id": str(row[3]),
                "source_observation_id": None if row[4] is None else str(row[4]),
                "prior_source_observation_id": None if row[5] is None else str(row[5]),
                "reconciliation_proposal_id": None if row[6] is None else str(row[6]),
                "accepted_command_id": str(row[7]),
                "recorded_at_utc": int(row[8]),
            }
            for row in rows
        )

    @staticmethod
    def append_event(
        uow: UnitOfWork,
        *,
        event_id: str,
        service_request_id: str,
        event_kind: str,
        prior_event_id: str | None,
        import_run_id: str,
        source_observation_id: str | None,
        prior_source_observation_id: str | None,
        reconciliation_proposal_id: str | None,
        command_id: str,
        recorded_at_utc: int,
    ) -> None:
        uow.connection.execute(
            "INSERT INTO sr_source_presence_events(sr_source_presence_event_id,service_request_id,source_family,"
            "event_kind,prior_presence_event_id,import_run_id,source_observation_id,prior_source_observation_id,"
            "reconciliation_proposal_id,accepted_command_id,recorded_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, service_request_id, SOURCE_FAMILY, event_kind, prior_event_id, import_run_id,
                source_observation_id, prior_source_observation_id, reconciliation_proposal_id, command_id,
                recorded_at_utc,
            ),
        )


class ServiceRequestSourcePresenceService:
    def __init__(self, evidence_provider: SrSourcePresenceEvidenceProvider) -> None:
        self._evidence = evidence_provider
        self._repository = ServiceRequestSourcePresenceRepository()

    @staticmethod
    def _audit(
        *,
        mutation: SrSourceDisappearanceMutation | SrSourceReappearanceMutation,
        event_id: str,
        event_kind: str,
        prior_event_id: str | None,
        source_observation_id: str | None,
        prior_source_observation_id: str | None,
        proposal_id: str | None,
        warning_active: bool,
    ) -> AuditEventInput:
        return AuditEventInput(
            audit_event_id=new_uuid4(),
            action_type="ticket.service_request.source_presence_changed",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="service_request",
            target_id=mutation.service_request_id,
            command_id=mutation.accepted_command_id,
            import_run_id=mutation.import_run_id,
            proposal_id=proposal_id,
            payload_schema="ServiceRequestSourcePresenceAuditV1",
            payload_version=1,
            payload={
                "service_request_id": mutation.service_request_id,
                "source_family": SOURCE_FAMILY,
                "presence_event_id": event_id,
                "event_kind": event_kind,
                "prior_presence_event_id": prior_event_id,
                "import_run_id": mutation.import_run_id,
                "source_observation_id": source_observation_id,
                "prior_source_observation_id": prior_source_observation_id,
                "reconciliation_proposal_id": proposal_id,
                "warning_active": warning_active,
            },
            resulting_event_refs=(AuditResultRef("service_request_source_presence_history", event_id),),
        )

    def apply_disappearance(
        self, uow: UnitOfWork, mutation: SrSourceDisappearanceMutation
    ) -> SrSourcePresenceApplyResult:
        state = self._repository.current(uow.connection, mutation.service_request_id, SOURCE_FAMILY)
        if not hmac.compare_digest(state.base_token_sha256, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request source-presence base state changed")
        if state.warning_active:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request disappearance warning is already active")
        validation = self._evidence.validate_disappearance_acceptance(
            uow.connection,
            mutation.reconciliation_proposal_id,
            mutation.service_request_id,
            SOURCE_FAMILY,
            mutation.import_run_id,
            mutation.prior_source_observation_id,
            {"command_id": mutation.accepted_command_id, "proposal_revision": mutation.proposal_revision,
             "proposal_fingerprint": mutation.proposal_fingerprint},
        )
        if validation != "VALID":
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request disappearance evidence is no longer exact")
        event_id = new_uuid4()
        self._repository.append_event(
            uow,
            event_id=event_id,
            service_request_id=mutation.service_request_id,
            event_kind="disappearance_reviewed",
            prior_event_id=state.latest_event_id,
            import_run_id=mutation.import_run_id,
            source_observation_id=None,
            prior_source_observation_id=mutation.prior_source_observation_id,
            reconciliation_proposal_id=mutation.reconciliation_proposal_id,
            command_id=mutation.accepted_command_id,
            recorded_at_utc=utc_epoch_seconds(),
        )
        audit = self._audit(
            mutation=mutation, event_id=event_id, event_kind="disappearance_reviewed",
            prior_event_id=state.latest_event_id, source_observation_id=None,
            prior_source_observation_id=mutation.prior_source_observation_id,
            proposal_id=mutation.reconciliation_proposal_id, warning_active=True,
        )
        refs = (("service_request_source_presence_history", event_id),)
        return SrSourcePresenceApplyResult(
            mutation.service_request_id, SOURCE_FAMILY, event_id, "disappearance_reviewed",
            state.latest_event_id, True, refs, (audit,),
        )

    def apply_reappearance(
        self, uow: UnitOfWork, mutation: SrSourceReappearanceMutation
    ) -> SrSourcePresenceApplyResult:
        state = self._repository.current(uow.connection, mutation.service_request_id, SOURCE_FAMILY)
        if state.active_disappearance_event_id != require_uuid4(mutation.expected_active_disappearance_event_id):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request active disappearance changed")
        validation = self._evidence.validate_reappearance_evidence(
            uow.connection,
            mutation.service_request_id,
            SOURCE_FAMILY,
            mutation.import_run_id,
            mutation.source_observation_id,
            {"command_id": mutation.accepted_command_id,
             "expected_active_disappearance_event_id": mutation.expected_active_disappearance_event_id},
        )
        if validation != "VALID":
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request reappearance evidence is no longer exact")
        event_id = new_uuid4()
        self._repository.append_event(
            uow,
            event_id=event_id,
            service_request_id=mutation.service_request_id,
            event_kind="reappearance_confirmed",
            prior_event_id=state.active_disappearance_event_id,
            import_run_id=mutation.import_run_id,
            source_observation_id=mutation.source_observation_id,
            prior_source_observation_id=None,
            reconciliation_proposal_id=None,
            command_id=mutation.accepted_command_id,
            recorded_at_utc=utc_epoch_seconds(),
        )
        audit = self._audit(
            mutation=mutation, event_id=event_id, event_kind="reappearance_confirmed",
            prior_event_id=state.active_disappearance_event_id,
            source_observation_id=mutation.source_observation_id,
            prior_source_observation_id=None, proposal_id=None, warning_active=False,
        )
        refs = (("service_request_source_presence_history", event_id),)
        return SrSourcePresenceApplyResult(
            mutation.service_request_id, SOURCE_FAMILY, event_id, "reappearance_confirmed",
            state.active_disappearance_event_id, False, refs, (audit,),
        )
