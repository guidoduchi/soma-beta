from __future__ import annotations

import hashlib
import hmac
import re
import uuid

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import (
    IdempotencyConflict,
    IdempotencyResultUnavailable,
    IntegrityFailure,
    SomaError,
    ValidationError,
)
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import loads_canonical_json, sha256_canonical_json

from ..audit_registry import build_product_line_sla_audit_registry
from ..contracts.product_line_sla import (
    BatchClassificationResult,
    ClassificationPreview,
    batch_classification_result_from_value,
)
from ..validation import validate_reason_code
from .classification import ProductLineSlaClassificationService

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PREVIEW_STATES = frozenset(
    {
        "eligible",
        "unchanged",
        "customer_unresolved",
        "cross_customer",
        "ambiguous",
        "unclassified",
        "incompatible",
    }
)
_PREVIEW_REJECTIONS = {
    "customer_unresolved": "SLA_CLASSIFICATION_CUSTOMER_UNRESOLVED",
    "cross_customer": "SLA_CLASSIFICATION_CROSS_CUSTOMER",
    "ambiguous": "SLA_CLASSIFICATION_MAPPING_AMBIGUOUS",
    "unclassified": "SLA_CLASSIFICATION_MAPPING_MISSING",
    "incompatible": "SLA_CLASSIFICATION_INCOMPATIBLE",
}
_TARGET_REJECT_CODES = frozenset(
    {
        "SLA_CLASSIFICATION_CUSTOMER_UNRESOLVED",
        "SLA_CLASSIFICATION_CROSS_CUSTOMER",
        "SLA_CLASSIFICATION_MAPPING_MISSING",
        "SLA_CLASSIFICATION_MAPPING_AMBIGUOUS",
        "SLA_CLASSIFICATION_STALE",
        "SLA_CLASSIFICATION_INCOMPATIBLE",
        "SLA_INPUT_INDETERMINATE",
        "SLA_DEPENDENCY_INDETERMINATE",
        "IDEMPOTENCY_CONFLICT",
    }
)


class ProductLineSlaBatchClassificationService:
    """Independent-per-target batch classification orchestrator.

    The batch boundary is intentionally not one writer transaction. A small
    immutable anchor receipt binds the reviewed batch request before child
    commands begin; each selected eligible target then executes through the
    ordinary ClassifyServiceRequest command boundary under a deterministic child
    command id. The final parent command stores the exact aggregate result and
    bounded batch audit.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._single = ProductLineSlaClassificationService(connection_factory)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_product_line_sla_audit_registry()),
        )

    @staticmethod
    def _correlation(value: str) -> str:
        if not isinstance(value, str):
            raise ValidationError("batch_correlation_id must be bounded text")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValidationError("batch_correlation_id must be valid Unicode") from exc
        if (
            not encoded
            or len(encoded) > 256
            or value != value.strip()
            or "\x00" in value
            or "\r" in value
            or "\n" in value
        ):
            raise ValidationError("batch_correlation_id must be bounded one-line text")
        return value

    @staticmethod
    def _derived_command_id(
        parent_command_id: str,
        *,
        purpose: str,
        ordinal: int,
        service_request_id: str | None,
    ) -> str:
        seed = sha256_canonical_json(
            {
                "schema": "SOMA_BATCH_CHILD_COMMAND_V1",
                "parent_command_id": require_uuid4(parent_command_id),
                "purpose": purpose,
                "ordinal": ordinal,
                "service_request_id": service_request_id,
            }
        )
        raw = bytearray(bytes.fromhex(seed)[:16])
        raw[6] = (raw[6] & 0x0F) | 0x40
        raw[8] = (raw[8] & 0x3F) | 0x80
        return require_uuid4(str(uuid.UUID(bytes=bytes(raw))))

    @staticmethod
    def _preview_members(
        items: tuple[ClassificationPreview, ...],
    ) -> list[dict[str, object]]:
        return [
            {
                "input_ordinal": index,
                "service_request_id": item.service_request_id,
                "state": item.state,
                "input_fingerprint": item.input_fingerprint,
                "target_contract_product_line_id": item.target_contract_product_line_id,
                "mapping_id": item.mapping_id,
            }
            for index, item in enumerate(items, start=1)
        ]

    @classmethod
    def _validate_preview(
        cls,
        *,
        preview_fingerprint: str,
        preview_items: tuple[ClassificationPreview, ...],
        candidate_contract_product_line_id: str | None,
    ) -> tuple[str | None, list[dict[str, object]]]:
        if not isinstance(preview_fingerprint, str) or _SHA256.fullmatch(preview_fingerprint) is None:
            raise ValidationError("preview_fingerprint must be lowercase SHA-256")
        if not isinstance(preview_items, tuple) or not 1 <= len(preview_items) <= 500:
            raise ValidationError("batch classification requires 1 through 500 preview items")

        cpl_id = (
            None
            if candidate_contract_product_line_id is None
            else require_uuid4(candidate_contract_product_line_id)
        )
        seen: set[str] = set()
        for item in preview_items:
            if not isinstance(item, ClassificationPreview):
                raise ValidationError("batch preview item contract is invalid")
            sr_id = require_uuid4(item.service_request_id)
            if sr_id in seen:
                raise ValidationError("batch preview Service Request identities must be unique")
            seen.add(sr_id)
            if item.state not in _PREVIEW_STATES:
                raise ValidationError("batch preview state is invalid")
            if not isinstance(item.input_fingerprint, str) or _SHA256.fullmatch(item.input_fingerprint) is None:
                raise ValidationError("batch preview item fingerprint is invalid")
            if item.target_contract_product_line_id is not None:
                require_uuid4(item.target_contract_product_line_id)
            if item.mapping_id is not None:
                require_uuid4(item.mapping_id)
            if cpl_id is not None:
                if item.target_contract_product_line_id != cpl_id or item.mapping_id is not None:
                    raise ValidationError("manual batch preview target contract is inconsistent")
            elif item.target_contract_product_line_id is not None and item.mapping_id is None:
                raise ValidationError("automatic batch preview target lacks trusted mapping identity")

        members = cls._preview_members(preview_items)
        actual = sha256_canonical_json(
            {
                "schema": "SOMA_BATCH_CLASSIFICATION_PREVIEW_V1",
                "contract_product_line_id": cpl_id,
                "members": members,
            }
        )
        if not hmac.compare_digest(actual, preview_fingerprint):
            raise ValidationError("batch preview fingerprint does not match exact preview items")
        return cpl_id, members

    @staticmethod
    def _summary_envelope(
        *,
        command_id: str,
        batch_correlation_id: str,
        preview_fingerprint: str,
        candidate_contract_product_line_id: str | None,
        members: list[dict[str, object]],
        reason_category: str,
    ) -> CommandEnvelope:
        return CommandEnvelope(
            command_id=require_uuid4(command_id),
            command_type="ApplyBatchClassification",
            target_type="service_request_batch",
            target_id=batch_correlation_id,
            semantic_payload={
                "batch_correlation_id": batch_correlation_id,
                "preview_fingerprint": preview_fingerprint,
                "candidate_contract_product_line_id": candidate_contract_product_line_id,
                "reason_category": reason_category,
                "members": members,
            },
            authorizing_fingerprints={"batch_preview": preview_fingerprint},
            correlation_id=batch_correlation_id,
        )

    def _completed_replay(
        self,
        envelope: CommandEnvelope,
    ) -> BatchClassificationResult | None:
        request_hash = envelope.request_hash()
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT r.command_type,r.request_hash,r.target_type,r.target_id,"
                "x.response_schema,x.response_version,x.response_json,x.response_sha256 "
                "FROM command_receipts r "
                "LEFT JOIN command_receipt_results x ON x.command_id=r.command_id "
                "WHERE r.command_id=?",
                (envelope.command_id,),
            ).fetchone()
        if row is None:
            return None
        target_id = None if row[3] is None else str(row[3])
        if (
            str(row[0]) != envelope.command_type
            or str(row[1]) != request_hash
            or str(row[2]) != envelope.target_type
            or target_id != envelope.target_id
        ):
            raise IdempotencyConflict()
        if row[4] is None or row[5] is None or row[6] is None or row[7] is None:
            raise IdempotencyResultUnavailable()
        if str(row[4]) != "BatchClassificationResultV1" or int(row[5]) != 1:
            raise IntegrityFailure("batch classification replay result schema is invalid")
        response_json = str(row[6])
        try:
            encoded = response_json.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise IntegrityFailure("batch classification replay JSON is invalid") from exc
        if hashlib.sha256(encoded).hexdigest() != str(row[7]):
            raise IntegrityFailure("batch classification replay result hash is invalid")
        value = loads_canonical_json(
            response_json,
            max_bytes=524_288,
            max_depth=8,
            max_collection_items=512,
        )
        return batch_classification_result_from_value(value, replayed=True)

    def _bind_intent(
        self,
        *,
        parent: CommandEnvelope,
        preview_fingerprint: str,
    ) -> None:
        parent_request_hash = parent.request_hash()
        anchor_id = self._derived_command_id(
            parent.command_id,
            purpose="anchor",
            ordinal=0,
            service_request_id=None,
        )
        anchor = CommandEnvelope(
            command_id=anchor_id,
            command_type="ApplyBatchClassificationIntent",
            target_type="service_request_batch",
            target_id=parent.target_id,
            semantic_payload={
                "parent_command_id": parent.command_id,
                "parent_request_hash": parent_request_hash,
                "preview_fingerprint": preview_fingerprint,
            },
            authorizing_fingerprints={"batch_preview": preview_fingerprint},
            correlation_id=parent.correlation_id,
        )

        def prepare(_uow) -> PreparedMutation:
            return PreparedMutation(
                no_change=True,
                result_type=None,
                result_id=None,
                response_schema="BatchClassificationIntentV1",
                response={
                    "parent_command_id": parent.command_id,
                    "parent_request_hash": parent_request_hash,
                    "preview_fingerprint": preview_fingerprint,
                },
            )

        self._boundary.execute(anchor, prepare)

    @staticmethod
    def _initial_rejection(item: ClassificationPreview) -> str | None:
        if item.state in {"eligible", "unchanged"}:
            return None
        code = _PREVIEW_REJECTIONS.get(item.state)
        if code is None:
            raise IntegrityFailure("batch preview state has no stable disposition")
        return code

    def apply_batch(
        self,
        *,
        command_id: str,
        batch_correlation_id: str,
        preview_fingerprint: str,
        preview_items: tuple[ClassificationPreview, ...],
        candidate_contract_product_line_id: str | None,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> BatchClassificationResult:
        correlation = self._correlation(batch_correlation_id)
        reason = validate_reason_code(reason_category)
        cpl_id, members = self._validate_preview(
            preview_fingerprint=preview_fingerprint,
            preview_items=preview_items,
            candidate_contract_product_line_id=candidate_contract_product_line_id,
        )
        envelope = self._summary_envelope(
            command_id=command_id,
            batch_correlation_id=correlation,
            preview_fingerprint=preview_fingerprint,
            candidate_contract_product_line_id=cpl_id,
            members=members,
            reason_category=reason,
        )

        replay = self._completed_replay(envelope)
        if replay is not None:
            return replay

        # This no-change receipt is the crash-stable binding between the parent
        # command id and the exact reviewed batch request. It prevents a retry
        # after partial target commits from changing members, order or preview.
        self._bind_intent(parent=envelope, preview_fingerprint=preview_fingerprint)

        applied: list[str] = []
        unchanged: list[str] = []
        rejected: list[dict[str, str]] = []
        applied_event_ids: list[str] = []
        eligible_count = sum(
            1 for item in preview_items if item.state in {"eligible", "unchanged"}
        )

        for ordinal, item in enumerate(preview_items, start=1):
            initial_error = self._initial_rejection(item)
            if initial_error is not None:
                rejected.append(
                    {
                        "service_request_id": item.service_request_id,
                        "error_code": initial_error,
                    }
                )
                continue
            if item.target_contract_product_line_id is None:
                raise IntegrityFailure("eligible batch target lacks CPL identity")

            child_command_id = self._derived_command_id(
                envelope.command_id,
                purpose="target",
                ordinal=ordinal,
                service_request_id=item.service_request_id,
            )
            origin = "manual_review" if cpl_id is not None else "automatic_mapping"
            mapping_id = None if origin == "manual_review" else item.mapping_id
            if origin == "automatic_mapping" and mapping_id is None:
                raise IntegrityFailure("eligible automatic batch target lacks mapping identity")

            try:
                result = self._single.classify_service_request(
                    command_id=child_command_id,
                    service_request_id=item.service_request_id,
                    target_contract_product_line_id=item.target_contract_product_line_id,
                    preview_fingerprint=item.input_fingerprint,
                    origin=origin,
                    mapping_id=mapping_id,
                    reason_category=reason,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                )
            except SomaError as exc:
                if exc.code not in _TARGET_REJECT_CODES:
                    raise
                rejected.append(
                    {
                        "service_request_id": item.service_request_id,
                        "error_code": exc.code,
                    }
                )
                continue

            if result.outcome == "APPLIED":
                if result.classification_event_id is None:
                    raise IntegrityFailure("applied batch classification lacks event identity")
                applied.append(item.service_request_id)
                applied_event_ids.append(result.classification_event_id)
            elif result.outcome == "NO_CHANGE":
                unchanged.append(item.service_request_id)
            else:
                raise IntegrityFailure("batch classification child returned invalid outcome")

        response = {
            "applied": applied,
            "unchanged": unchanged,
            "rejected": rejected,
        }

        def prepare_summary(_uow) -> PreparedMutation:
            def apply(_inner):
                refs = tuple(
                    AuditResultRef("sr_classification_event", event_id)
                    for event_id in applied_event_ids
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.service_request.batch_classification_applied",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request_batch",
                    target_id=correlation,
                    reason_category=reason,
                    command_id=envelope.command_id,
                    correlation_id=correlation,
                    batch_id=correlation,
                    payload_schema="BatchClassificationAuditV1",
                    payload_version=1,
                    payload={
                        "batch_correlation_id": correlation,
                        "requested_count": len(preview_items),
                        "eligible_count": eligible_count,
                        "applied_count": len(applied),
                        "unchanged_count": len(unchanged),
                        "rejected_count": len(rejected),
                        "preview_fingerprint": preview_fingerprint,
                        "result_refs": list(applied_event_ids),
                    },
                    resulting_event_refs=refs,
                )

            return PreparedMutation(
                no_change=False,
                result_type="service_request_batch",
                result_id=correlation,
                apply=apply,
                response_schema="BatchClassificationResultV1",
                response=response,
            )

        execution = self._boundary.execute(envelope, prepare_summary)
        if execution.response_schema != "BatchClassificationResultV1" or execution.response_version != 1:
            raise IntegrityFailure("batch classification response contract is invalid")
        return batch_classification_result_from_value(
            execution.response,
            replayed=execution.replayed,
        )


__all__ = ["ProductLineSlaBatchClassificationService"]
