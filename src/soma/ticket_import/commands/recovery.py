from __future__ import annotations

import re
from dataclasses import dataclass

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, PersistenceFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_ticket_import_audit_registry
from ..repositories.proposals import ProposalRepository


_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_DECISIONS = {
    "authorize_correction": "authorized",
    "defer": "deferred",
    "reject": "rejected",
}


@dataclass(frozen=True, slots=True)
class ImportRecoveryDecisionResult:
    import_run_id: str
    review_ordinal: int
    decision: str
    run_state: str
    run_revision: int
    replayed: bool


class ResolveImportRecoveryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._proposals = ProposalRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_ticket_import_audit_registry()),
        )

    @staticmethod
    def _from_execution(execution: CommandExecutionResult) -> ImportRecoveryDecisionResult:
        if execution.response_schema != "ImportRecoveryDecisionResultV1" or execution.response_version != 1:
            raise IntegrityFailure("import recovery decision result schema/version is invalid")
        value = execution.response
        required = {"import_run_id", "review_ordinal", "decision", "run_state", "run_revision"}
        if not isinstance(value, dict) or set(value) != required:
            raise IntegrityFailure("import recovery decision result shape is invalid")
        if value["decision"] not in _DECISIONS.values():
            raise IntegrityFailure("import recovery decision result decision is invalid")
        if value["run_state"] not in {"recovery_required", "rejected"}:
            raise IntegrityFailure("import recovery decision result state is invalid")
        for key in ("review_ordinal", "run_revision"):
            if type(value[key]) is not int or value[key] < 1:
                raise IntegrityFailure("import recovery decision result revision is invalid")
        return ImportRecoveryDecisionResult(
            import_run_id=require_uuid4(str(value["import_run_id"])),
            review_ordinal=int(value["review_ordinal"]),
            decision=str(value["decision"]),
            run_state=str(value["run_state"]),
            run_revision=int(value["run_revision"]),
            replayed=execution.replayed,
        )

    def resolve(
        self,
        *,
        command_id: str,
        import_run_id: str,
        review_fingerprint: str,
        decision: str,
        reason_category: str,
        expected_run_revision: int | None = None,
        expected_checkpoint_revision: int | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ImportRecoveryDecisionResult:
        canonical_run_id = require_uuid4(import_run_id)
        if expected_run_revision is not None and (
            type(expected_run_revision) is not int or expected_run_revision < 1
        ):
            raise ValidationError("expected_run_revision must be a positive integer when supplied")
        if expected_checkpoint_revision is not None and (
            type(expected_checkpoint_revision) is not int or expected_checkpoint_revision < 1
        ):
            raise ValidationError("expected_checkpoint_revision must be a positive integer when supplied")
        if not isinstance(review_fingerprint, str) or _HEX64_RE.fullmatch(review_fingerprint) is None:
            raise ValidationError("review_fingerprint must be lowercase SHA-256 hex")
        persisted_decision = _DECISIONS.get(decision)
        if persisted_decision is None:
            raise ValidationError("decision must be authorize_correction, defer, or reject")
        if not isinstance(reason_category, str):
            raise ValidationError("reason_category must be a string")
        encoded_reason = reason_category.encode("utf-8", errors="strict")
        if (
            not encoded_reason
            or len(encoded_reason) > 120
            or "\x00" in reason_category
            or "\r" in reason_category
            or "\n" in reason_category
        ):
            raise ValidationError("reason_category violates the LLD-04 1..120 UTF-8 byte one-line contract")

        # Browser transport authority is exactly ResolveRecoveryRequestV1. Run/checkpoint
        # revisions are authoritative state reads, not request semantics. Optional legacy
        # revision arguments remain supported only as stale-state assertions for internal
        # callers and are intentionally absent from the command envelope hash.
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ResolveImportRecovery",
            target_type="import_run",
            target_id=canonical_run_id,
            semantic_payload={
                "import_run_id": canonical_run_id,
                "decision": decision,
                "reason_category": reason_category,
            },
            authorizing_fingerprints={"recovery_review": review_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            run = self._proposals.get_run(uow.connection, canonical_run_id)
            if run.run_state != "recovery_required":
                raise SomaError("IMPORT_RUN_NOT_RECOVERY_REQUIRED", "import run is not recovery-required")
            current_run_revision = run.revision
            if expected_run_revision is not None and current_run_revision != expected_run_revision:
                raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "recovery run revision changed")

            checkpoint = uow.connection.execute(
                "SELECT accepted_import_run_id,revision FROM import_source_checkpoints WHERE source_family=?",
                (run.source_family,),
            ).fetchone()
            if checkpoint is None:
                raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "recovery checkpoint disappeared")
            current_checkpoint_revision = int(checkpoint[1])
            if (
                expected_checkpoint_revision is not None
                and current_checkpoint_revision != expected_checkpoint_revision
            ):
                raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "recovery checkpoint revision changed")

            exact_fingerprint = self._proposals.recovery_review_fingerprint(uow.connection, run)
            if exact_fingerprint != review_fingerprint:
                raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "recovery review fingerprint changed")
            if persisted_decision == "rejected" and run.accepted_count != 0:
                raise SomaError(
                    "IMPORT_RECOVERY_REJECT_AFTER_ACCEPTANCE",
                    "recovery with accepted proposals cannot be rejected",
                )

            ordinal_row = uow.connection.execute(
                "SELECT COALESCE(MAX(review_ordinal),0)+1 FROM import_recovery_reviews WHERE import_run_id=?",
                (canonical_run_id,),
            ).fetchone()
            if ordinal_row is None:
                raise PersistenceFailure("recovery review ordinal query returned no aggregate row")
            review_ordinal = int(ordinal_row[0])
            now = utc_epoch_seconds()
            review_id = new_uuid4()
            audit_id = new_uuid4()
            response_state = "rejected" if persisted_decision == "rejected" else "recovery_required"
            response_revision = current_run_revision + (1 if persisted_decision == "rejected" else 0)

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO import_recovery_reviews(import_recovery_review_id,import_run_id,"
                    "checkpoint_import_run_id,review_ordinal,run_revision,checkpoint_revision,"
                    "review_fingerprint_sha256,decision,reason_category,occurred_at_utc,command_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        review_id,
                        canonical_run_id,
                        str(checkpoint[0]),
                        review_ordinal,
                        current_run_revision,
                        current_checkpoint_revision,
                        review_fingerprint,
                        persisted_decision,
                        reason_category,
                        now,
                        command_id,
                    ),
                )
                result_refs = [AuditResultRef("import_recovery_review", review_id)]
                if persisted_decision == "rejected":
                    pending = inner.connection.execute(
                        "SELECT reconciliation_proposal_id,revision,proposal_fingerprint_sha256,"
                        "base_state_token_sha256 FROM reconciliation_proposals "
                        "WHERE import_run_id=? AND proposal_state='pending' ORDER BY reconciliation_proposal_id",
                        (canonical_run_id,),
                    ).fetchall()
                    for row in pending:
                        changed = inner.connection.execute(
                            "UPDATE reconciliation_proposals SET proposal_state='superseded',"
                            "revision=revision+1,decided_at_utc=? WHERE reconciliation_proposal_id=? "
                            "AND proposal_state='pending' AND revision=?",
                            (now, str(row[0]), int(row[1])),
                        )
                        if changed.rowcount != 1:
                            raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "pending recovery proposal changed")
                        disposition_id = new_uuid4()
                        inner.connection.execute(
                            "INSERT INTO proposal_dispositions(proposal_disposition_id,reconciliation_proposal_id,"
                            "decision,proposal_revision,proposal_fingerprint_sha256,base_state_token_sha256,"
                            "reason_category,decision_origin,occurred_at_utc,command_id) "
                            "VALUES (?,?,'superseded',?,?,?,?, 'recovery',?,?)",
                            (
                                disposition_id,
                                str(row[0]),
                                int(row[1]),
                                str(row[2]),
                                str(row[3]),
                                reason_category,
                                now,
                                command_id,
                            ),
                        )
                        result_refs.append(AuditResultRef("proposal_disposition", disposition_id))
                    changed_run = inner.connection.execute(
                        "UPDATE import_runs SET run_state='rejected',pending_proposal_count=0,"
                        "completed_at_utc=?,revision=revision+1 WHERE import_run_id=? AND revision=? "
                        "AND run_state='recovery_required' AND accepted_proposal_count=0",
                        (now, canonical_run_id, current_run_revision),
                    )
                    if changed_run.rowcount != 1:
                        raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "recovery run changed before rejection")
                    result_refs.append(AuditResultRef("import_run", canonical_run_id))
                return AuditEventInput(
                    audit_event_id=audit_id,
                    action_type="ticket_import.recovery_reviewed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="import_run",
                    target_id=canonical_run_id,
                    command_id=command_id,
                    import_run_id=canonical_run_id,
                    payload_schema="ImportRecoveryReviewedAuditV1",
                    payload_version=1,
                    payload={
                        "import_run_id": canonical_run_id,
                        "review_ordinal": review_ordinal,
                        "decision": persisted_decision,
                        "reason_category": reason_category,
                        "review_fingerprint": review_fingerprint,
                        "run_state": response_state,
                        "run_revision": response_revision,
                    },
                    resulting_event_refs=tuple(result_refs),
                )

            return PreparedMutation(
                False,
                "import_recovery_review",
                review_id,
                apply,
                response_schema="ImportRecoveryDecisionResultV1",
                response={
                    "import_run_id": canonical_run_id,
                    "review_ordinal": review_ordinal,
                    "decision": persisted_decision,
                    "run_state": response_state,
                    "run_revision": response_revision,
                },
            )

        return self._from_execution(self._boundary.execute(envelope, prepare))


__all__ = ["ImportRecoveryDecisionResult", "ResolveImportRecoveryService"]
