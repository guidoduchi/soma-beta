from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import (
    CommandBoundary, CommandEnvelope, CommandExecutionResult, PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .queries.rfc_hard_delete import (
    RfcHardDeleteDependencyProvider, RfcHardDeleteQueryService, RfcSourceProvenanceProvider,
)
from .rfc_terminal_cascade_execute import DeliberateActionProofProvider, DeliberateActionTargetV1
from .validation import validate_optional_sha256, validate_rfc_no


@dataclass(frozen=True, slots=True)
class HardDeleteRfcResult:
    outcome: str
    rfc_id: str
    rfc_no: str
    reviewed_revision: int
    eligibility_fingerprint: str
    hard_delete_evidence_id: str
    replayed: bool

    def to_response(self) -> dict[str, object]:
        return {
            "outcome": self.outcome, "rfc_id": self.rfc_id, "rfc_no": self.rfc_no,
            "reviewed_revision": self.reviewed_revision,
            "eligibility_fingerprint": self.eligibility_fingerprint,
            "hard_delete_evidence_id": self.hard_delete_evidence_id,
        }


def _result_from_execution(result: CommandExecutionResult) -> HardDeleteRfcResult:
    response = result.response
    if (
        result.response_schema != "HardDeleteRfcResultV1" or result.response_version != 1
        or result.no_change or not isinstance(response, dict)
        or set(response) != {"outcome", "rfc_id", "rfc_no", "reviewed_revision",
                             "eligibility_fingerprint", "hard_delete_evidence_id"}
    ):
        raise IntegrityFailure("RFC hard-delete committed response contract is invalid")
    try:
        require_uuid4(response["rfc_id"])
        require_uuid4(response["hard_delete_evidence_id"])
        validate_rfc_no(response["rfc_no"])
        fingerprint = validate_optional_sha256(response["eligibility_fingerprint"], field="eligibility_fingerprint")
    except SomaError as exc:
        raise IntegrityFailure("RFC hard-delete committed identity or fingerprint is invalid") from exc
    if (
        response["outcome"] != "deleted" or fingerprint is None
        or type(response["reviewed_revision"]) is not int or response["reviewed_revision"] <= 0
        or result.result_type != "hard_delete_evidence" or result.result_id != response["hard_delete_evidence_id"]
    ):
        raise IntegrityFailure("RFC hard-delete committed evidence is invalid")
    return HardDeleteRfcResult(**response, replayed=result.replayed)


class RfcHardDeleteService:
    """Delete only the reviewed, provably untouched RFC; retain immutable evidence."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        source_evidence_provider: RfcSourceProvenanceProvider,
        task_participant: RfcHardDeleteDependencyProvider,
        inventory_provider: RfcHardDeleteDependencyProvider,
        communication_participant: RfcHardDeleteDependencyProvider,
        proof_provider: DeliberateActionProofProvider,
    ) -> None:
        self._queries = RfcHardDeleteQueryService(
            connection_factory, source_evidence_provider, task_participant,
            inventory_provider, communication_participant,
        )
        self._proof_provider = proof_provider
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_tickets_audit_registry()))

    def hard_delete(
        self, *, command_id: str, rfc_id: str, base_revision: int,
        eligibility_fingerprint: str, deliberate_action_proof: object,
        actor_kind: str = "local_user", actor_id: str | None = None,
    ) -> HardDeleteRfcResult:
        canonical_id = require_uuid4(rfc_id)
        fingerprint = validate_optional_sha256(eligibility_fingerprint, field="eligibility_fingerprint")
        if fingerprint is None:
            raise ValidationError("eligibility_fingerprint is required")
        envelope = CommandEnvelope(
            command_id=command_id, command_type="HardDeleteRfc", target_type="rfc", target_id=canonical_id,
            semantic_payload={}, base_revisions={"rfc": base_revision},
            authorizing_fingerprints={"eligibility_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            identity = self._queries.load_identity(uow, canonical_id)
            rfc_no, revision, _ = identity
            if revision != base_revision:
                raise SomaError("RFC_HARD_DELETE_PREVIEW_STALE", "RFC revision changed since preview")
            preview = self._queries.evaluate(uow, rfc_id=canonical_id, identity=identity)
            if not preview.eligible:
                raise SomaError("RFC_HARD_DELETE_BLOCKED", "RFC hard deletion is blocked by current evidence")
            if preview.eligibility_fingerprint != fingerprint:
                raise SomaError("RFC_HARD_DELETE_PREVIEW_STALE", "RFC hard-delete eligibility changed since preview")
            try:
                validated = self._proof_provider.validate_and_consume(
                    uow, deliberate_action_proof, "tickets.rfc.hard_delete",
                    DeliberateActionTargetV1("rfc", canonical_id), base_revision, fingerprint,
                )
                if validated is None or isinstance(validated, bool):
                    raise ValueError("proof was not validated")
            except Exception as exc:
                raise SomaError(
                    "RFC_HARD_DELETE_CONFIRMATION_REQUIRED", "RFC hard-delete deliberate-action proof is invalid"
                ) from exc
            evidence_id = new_uuid4()
            response = HardDeleteRfcResult(
                "deleted", canonical_id, rfc_no, revision, fingerprint, evidence_id, False
            ).to_response()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                return AuditEventInput(
                    audit_event_id=evidence_id, action_type="ticket.rfc.hard_deleted", action_version=1,
                    actor_kind=actor_kind, actor_id=actor_id, target_type="rfc", target_id=canonical_id,
                    command_id=command_id, payload_schema="RfcHardDeleteAuditV1", payload_version=1,
                    payload={"rfc_id": canonical_id, "rfc_no": rfc_no, "reviewed_revision": revision,
                             "eligibility_fingerprint": fingerprint, "result": "deleted"},
                    resulting_event_refs=(AuditResultRef("hard_delete_evidence", evidence_id),),
                )

            def delete_after_audit(inner: UnitOfWork) -> None:
                # The boundary has already appended the surviving evidence in this same UoW.
                deleted = inner.connection.execute(
                    "DELETE FROM rfcs WHERE rfc_id=? AND revision=?", (canonical_id, revision)
                )
                if deleted.rowcount != 1:
                    raise IntegrityFailure("RFC disappeared before its reviewed deletion")

            return PreparedMutation(
                False, "hard_delete_evidence", evidence_id, apply,
                response_schema="HardDeleteRfcResultV1", response_version=1, response=response,
                after_audit=delete_after_audit,
            )

        return _result_from_execution(self._boundary.execute(envelope, prepare))
