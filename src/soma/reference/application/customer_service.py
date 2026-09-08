from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from soma.reference.audit_registry import build_reference_audit_registry
from soma.reference.domain.account_code_review import (
    AccountCodeReviewSnapshot,
    preview_account_code_review,
    validate_account_code_review,
)
from soma.reference.domain.validation import (
    validate_account_code,
    validate_customer_name,
    validate_reason_category,
)


@dataclass(frozen=True, slots=True)
class CustomerCreateResult:
    customer_org_id: str
    replayed: bool


class CustomerReferenceService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_reference_audit_registry()),
        )

    @staticmethod
    def _active_customer(connection: Any, customer_org_id: str, *, base_revision: int | None = None) -> Any:
        row = connection.execute(
            "SELECT customer_org_id, name, name_match_key, lifecycle_state, revision "
            "FROM customer_organizations WHERE customer_org_id = ?",
            (customer_org_id,),
        ).fetchone()
        if row is None or str(row[3]) != "active":
            raise SomaError("REFERENCE_NOT_ACTIVE", "Customer Organization is missing or archived")
        if base_revision is not None and int(row[4]) != base_revision:
            raise SomaError("STALE_REVISION", "Customer Organization revision changed")
        return row

    @staticmethod
    def _active_code_claim(connection: Any, customer_org_id: str) -> Any | None:
        return connection.execute(
            "SELECT customer_org_identifier_id, value_text, match_key, created_at_utc "
            "FROM customer_org_identifiers "
            "WHERE customer_org_id = ? AND identifier_type = 'customer_account_code' "
            "AND lifecycle_state = 'active'",
            (customer_org_id,),
        ).fetchone()

    def create_customer_organization(
        self,
        *,
        command_id: str,
        name: str,
        account_code: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CustomerCreateResult:
        stored_name, name_key = validate_customer_name(name)
        code_value: str | None = None
        code_key: str | None = None
        if account_code is not None:
            code_value, code_key = validate_account_code(account_code)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateCustomerOrganization",
            target_type="customer_organization",
            target_id=None,
            semantic_payload={"name": stored_name, "account_code": code_value},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            if code_key is not None:
                conflicting = int(
                    uow.connection.execute(
                        "SELECT count(*) FROM customer_org_identifiers "
                        "WHERE identifier_type='customer_account_code' AND match_key=? "
                        "AND lifecycle_state='active'",
                        (code_key,),
                    ).fetchone()[0]
                )
                if conflicting:
                    raise SomaError(
                        "ACCOUNT_CODE_CONFLICT_REVIEW",
                        "Customer Account Code already has an active canonical claimant",
                    )

            customer_org_id = new_uuid4()
            identifier_id = new_uuid4() if code_key is not None else None
            lifecycle_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO customer_organizations("
                    "customer_org_id,name,name_match_key,lifecycle_state,revision,created_at_utc,updated_at_utc"
                    ") VALUES (?, ?, ?, 'active', 1, ?, ?)",
                    (customer_org_id, stored_name, name_key, now, now),
                )
                refs = [AuditResultRef("customer_organization", customer_org_id)]
                if identifier_id is not None and code_value is not None and code_key is not None:
                    inner.connection.execute(
                        "INSERT INTO customer_org_identifiers("
                        "customer_org_identifier_id,customer_org_id,identifier_type,value_text,match_key,"
                        "lifecycle_state,created_at_utc,created_command_id"
                        ") VALUES (?, ?, 'customer_account_code', ?, ?, 'active', ?, ?)",
                        (identifier_id, customer_org_id, code_value, code_key, now, command_id),
                    )
                    refs.append(AuditResultRef("customer_org_identifier", identifier_id))
                inner.connection.execute(
                    "INSERT INTO reference_lifecycle_events("
                    "reference_lifecycle_event_id,target_type,target_id,event_type,occurred_at_utc,command_id,reason_category"
                    ") VALUES (?, 'customer_organization', ?, 'created', ?, ?, NULL)",
                    (lifecycle_event_id, customer_org_id, now, command_id),
                )
                refs.append(AuditResultRef("reference_lifecycle_event", lifecycle_event_id))
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.customer_organization.created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="customer_organization",
                    target_id=customer_org_id,
                    command_id=command_id,
                    payload_schema="CustomerOrganizationAuditV1",
                    payload_version=1,
                    payload={
                        "customer_org_id": customer_org_id,
                        "new_revision": 1,
                        "account_code_claim_created": identifier_id is not None,
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(refs),
                )

            return PreparedMutation(
                no_change=False,
                result_type="customer_organization",
                result_id=customer_org_id,
                apply=apply,
            )

        result = self._boundary.execute(envelope, prepare)
        assert result.result_id is not None
        return CustomerCreateResult(result.result_id, result.replayed)

    def set_customer_account_code(
        self,
        *,
        command_id: str,
        customer_org_id: str,
        base_revision: int,
        account_code: str,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CommandExecutionResult:
        code_value, code_key = validate_account_code(account_code)
        reason = validate_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetCustomerAccountCode",
            target_type="customer_organization",
            target_id=customer_org_id,
            semantic_payload={"account_code": code_value, "reason_category": reason},
            base_revisions={"customer_org": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            customer = self._active_customer(uow.connection, customer_org_id, base_revision=base_revision)
            prior_revision = int(customer[4])
            current = self._active_code_claim(uow.connection, customer_org_id)
            if current is not None and str(current[2]) == code_key:
                return PreparedMutation(no_change=True, result_type=None, result_id=None)
            other_count = int(
                uow.connection.execute(
                    "SELECT count(*) FROM customer_org_identifiers "
                    "WHERE identifier_type='customer_account_code' AND match_key=? "
                    "AND lifecycle_state='active' AND customer_org_id<>?",
                    (code_key, customer_org_id),
                ).fetchone()[0]
            )
            if other_count:
                raise SomaError(
                    "ACCOUNT_CODE_CONFLICT_REVIEW",
                    "Customer Account Code has another active canonical claimant",
                )

            new_identifier_id = new_uuid4()
            superseded_identifier_id = None if current is None else str(current[0])
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if superseded_identifier_id is not None:
                    inner.connection.execute(
                        "UPDATE customer_org_identifiers SET lifecycle_state='superseded', "
                        "superseded_at_utc=?, superseded_command_id=? WHERE customer_org_identifier_id=?",
                        (now, command_id, superseded_identifier_id),
                    )
                inner.connection.execute(
                    "INSERT INTO customer_org_identifiers("
                    "customer_org_identifier_id,customer_org_id,identifier_type,value_text,match_key,"
                    "lifecycle_state,created_at_utc,created_command_id"
                    ") VALUES (?, ?, 'customer_account_code', ?, ?, 'active', ?, ?)",
                    (new_identifier_id, customer_org_id, code_value, code_key, now, command_id),
                )
                inner.connection.execute(
                    "UPDATE customer_organizations SET revision=revision+1, updated_at_utc=? "
                    "WHERE customer_org_id=?",
                    (now, customer_org_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.customer_account_code.set",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="customer_organization",
                    target_id=customer_org_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="CustomerAccountCodeAuditV1",
                    payload_version=1,
                    payload={
                        "customer_org_id": customer_org_id,
                        "customer_org_identifier_id": new_identifier_id,
                        "superseded_identifier_id": superseded_identifier_id,
                        "prior_revision": prior_revision,
                        "new_revision": prior_revision + 1,
                        "change_kind": "SET" if superseded_identifier_id is None else "REPLACE",
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("customer_org_identifier", new_identifier_id),),
                )

            return PreparedMutation(
                no_change=False,
                result_type="customer_org_identifier",
                result_id=new_identifier_id,
                apply=apply,
            )

        return self._boundary.execute(envelope, prepare)

    def preview_account_code_review(
        self,
        *,
        raw_account_code: str,
        proposed_action: str,
        target_customer_org_id: str,
        from_customer_org_id: str | None = None,
        page_size: int = 50,
        after_customer_org_id: str | None = None,
    ) -> AccountCodeReviewSnapshot:
        if proposed_action not in {"CONFIRM_SHARED_CLAIM", "REASSIGN_CLAIM"}:
            raise SomaError("REVIEW_CONTEXT_INVALID", "unsupported Account Code review action")
        with ReadSnapshot(self._factory) as snapshot:
            return preview_account_code_review(
                snapshot.connection,
                raw_account_code=raw_account_code,
                proposed_action=proposed_action,  # type: ignore[arg-type]
                target_customer_org_id=target_customer_org_id,
                from_customer_org_id=from_customer_org_id,
                page_size=page_size,
                after_customer_org_id=after_customer_org_id,
            )

    def confirm_customer_account_code_shared_claim(
        self,
        *,
        command_id: str,
        customer_org_id: str,
        base_revision: int,
        account_code: str,
        review_snapshot_hash: str,
        reason_category: str,
        review_context_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CommandExecutionResult:
        code_value, _ = validate_account_code(account_code)
        reason = validate_reason_category(reason_category)
        if reason is None:
            raise SomaError("REASON_REQUIRED", "reviewed shared claim requires reason_category")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ConfirmCustomerAccountCodeSharedClaim",
            target_type="customer_organization",
            target_id=customer_org_id,
            semantic_payload={
                "account_code": code_value,
                "proposed_action": "CONFIRM_SHARED_CLAIM",
                "review_snapshot_hash": review_snapshot_hash,
                "review_context_id": review_context_id,
                "reason_category": reason,
            },
            base_revisions={"customer_org": base_revision},
            authorizing_fingerprints={"review_snapshot": review_snapshot_hash},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            code_key, _ = validate_account_code_review(
                uow.connection,
                raw_account_code=code_value,
                proposed_action="CONFIRM_SHARED_CLAIM",
                target_customer_org_id=customer_org_id,
                review_snapshot_hash=review_snapshot_hash,
            )
            customer = self._active_customer(uow.connection, customer_org_id, base_revision=base_revision)
            prior_revision = int(customer[4])
            current = self._active_code_claim(uow.connection, customer_org_id)
            if current is not None and str(current[2]) == code_key:
                return PreparedMutation(no_change=True, result_type=None, result_id=None)

            new_identifier_id = new_uuid4()
            superseded_identifier_id = None if current is None else str(current[0])
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                changed_ids: list[str] = []
                if superseded_identifier_id is not None:
                    inner.connection.execute(
                        "UPDATE customer_org_identifiers SET lifecycle_state='superseded', "
                        "superseded_at_utc=?, superseded_command_id=? WHERE customer_org_identifier_id=?",
                        (now, command_id, superseded_identifier_id),
                    )
                    changed_ids.append(superseded_identifier_id)
                inner.connection.execute(
                    "INSERT INTO customer_org_identifiers("
                    "customer_org_identifier_id,customer_org_id,identifier_type,value_text,match_key,"
                    "lifecycle_state,created_at_utc,created_command_id"
                    ") VALUES (?, ?, 'customer_account_code', ?, ?, 'active', ?, ?)",
                    (new_identifier_id, customer_org_id, code_value, code_key, now, command_id),
                )
                changed_ids.append(new_identifier_id)
                inner.connection.execute(
                    "UPDATE customer_organizations SET revision=revision+1, updated_at_utc=? WHERE customer_org_id=?",
                    (now, customer_org_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.customer_account_code.shared_claim_confirmed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="customer_organization",
                    target_id=customer_org_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="CustomerAccountCodeReviewAuditV1",
                    payload_version=1,
                    payload={
                        "proposed_action": "CONFIRM_SHARED_CLAIM",
                        "review_snapshot_hash": review_snapshot_hash,
                        "review_context_id": review_context_id,
                        "from_customer_org_id": None,
                        "to_customer_org_id": customer_org_id,
                        "changed_identifier_ids": changed_ids,
                        "changed_customer_org_ids": [customer_org_id],
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("customer_org_identifier", new_identifier_id),),
                )

            return PreparedMutation(
                no_change=False,
                result_type="customer_org_identifier",
                result_id=new_identifier_id,
                apply=apply,
            )

        return self._boundary.execute(envelope, prepare)

    def reassign_customer_account_code(
        self,
        *,
        command_id: str,
        from_customer_org_id: str,
        from_base_revision: int,
        to_customer_org_id: str,
        to_base_revision: int,
        account_code: str,
        review_snapshot_hash: str,
        reason_category: str,
        review_context_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CommandExecutionResult:
        code_value, _ = validate_account_code(account_code)
        reason = validate_reason_category(reason_category)
        if reason is None:
            raise SomaError("REASON_REQUIRED", "reviewed reassignment requires reason_category")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReassignCustomerAccountCode",
            target_type="customer_organization",
            target_id=to_customer_org_id,
            semantic_payload={
                "from_customer_org_id": from_customer_org_id,
                "account_code": code_value,
                "proposed_action": "REASSIGN_CLAIM",
                "review_snapshot_hash": review_snapshot_hash,
                "review_context_id": review_context_id,
                "reason_category": reason,
            },
            base_revisions={"from_customer_org": from_base_revision, "to_customer_org": to_base_revision},
            authorizing_fingerprints={"review_snapshot": review_snapshot_hash},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            code_key, _ = validate_account_code_review(
                uow.connection,
                raw_account_code=code_value,
                proposed_action="REASSIGN_CLAIM",
                target_customer_org_id=to_customer_org_id,
                from_customer_org_id=from_customer_org_id,
                review_snapshot_hash=review_snapshot_hash,
            )
            from_customer = self._active_customer(
                uow.connection, from_customer_org_id, base_revision=from_base_revision
            )
            to_customer = self._active_customer(
                uow.connection, to_customer_org_id, base_revision=to_base_revision
            )
            source_claim = self._active_code_claim(uow.connection, from_customer_org_id)
            if source_claim is None or str(source_claim[2]) != code_key:
                raise SomaError("REVIEW_CONTEXT_STALE", "source Account Code claim changed")
            target_claim = self._active_code_claim(uow.connection, to_customer_org_id)
            source_identifier_id = str(source_claim[0])
            target_identifier_id = None if target_claim is None else str(target_claim[0])
            target_same_code = target_claim is not None and str(target_claim[2]) == code_key
            new_target_identifier_id = None if target_same_code else new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                changed_identifier_ids: list[str] = [source_identifier_id]
                inner.connection.execute(
                    "UPDATE customer_org_identifiers SET lifecycle_state='superseded', "
                    "superseded_at_utc=?, superseded_command_id=? WHERE customer_org_identifier_id=?",
                    (now, command_id, source_identifier_id),
                )
                if target_claim is not None and not target_same_code:
                    assert target_identifier_id is not None
                    inner.connection.execute(
                        "UPDATE customer_org_identifiers SET lifecycle_state='superseded', "
                        "superseded_at_utc=?, superseded_command_id=? WHERE customer_org_identifier_id=?",
                        (now, command_id, target_identifier_id),
                    )
                    changed_identifier_ids.append(target_identifier_id)
                if new_target_identifier_id is not None:
                    inner.connection.execute(
                        "INSERT INTO customer_org_identifiers("
                        "customer_org_identifier_id,customer_org_id,identifier_type,value_text,match_key,"
                        "lifecycle_state,created_at_utc,created_command_id"
                        ") VALUES (?, ?, 'customer_account_code', ?, ?, 'active', ?, ?)",
                        (
                            new_target_identifier_id,
                            to_customer_org_id,
                            code_value,
                            code_key,
                            now,
                            command_id,
                        ),
                    )
                    changed_identifier_ids.append(new_target_identifier_id)
                inner.connection.execute(
                    "UPDATE customer_organizations SET revision=revision+1, updated_at_utc=? WHERE customer_org_id=?",
                    (now, from_customer_org_id),
                )
                changed_customer_ids = [from_customer_org_id]
                if not target_same_code:
                    inner.connection.execute(
                        "UPDATE customer_organizations SET revision=revision+1, updated_at_utc=? WHERE customer_org_id=?",
                        (now, to_customer_org_id),
                    )
                    changed_customer_ids.append(to_customer_org_id)
                result_id = new_target_identifier_id or target_identifier_id
                refs = [AuditResultRef("customer_org_identifier", value) for value in changed_identifier_ids]
                refs.extend(AuditResultRef("customer_organization", value) for value in changed_customer_ids)
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.customer_account_code.reassigned",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="customer_organization",
                    target_id=to_customer_org_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="CustomerAccountCodeReviewAuditV1",
                    payload_version=1,
                    payload={
                        "proposed_action": "REASSIGN_CLAIM",
                        "review_snapshot_hash": review_snapshot_hash,
                        "review_context_id": review_context_id,
                        "from_customer_org_id": from_customer_org_id,
                        "to_customer_org_id": to_customer_org_id,
                        "changed_identifier_ids": changed_identifier_ids,
                        "changed_customer_org_ids": changed_customer_ids,
                        "reason_category": reason,
                    },
                    resulting_event_refs=tuple(refs),
                )

            result_id = new_target_identifier_id or target_identifier_id
            if result_id is None:
                raise SomaError("PERSISTENCE_FAILURE", "reassignment could not determine target identifier")
            return PreparedMutation(
                no_change=False,
                result_type="customer_org_identifier",
                result_id=result_id,
                apply=apply,
            )

        return self._boundary.execute(envelope, prepare)
