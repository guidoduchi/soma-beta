from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..algorithms.policy_validation import PolicyTierInput, ValidatedPolicy, validate_sla_policy
from ..audit_registry import build_product_line_sla_audit_registry
from ..contracts.product_line_sla import PolicyRevisionResult, policy_result_from_execution
from ..repositories.policy import SlaPolicyRepository, SlaPolicyRevisionRecord, SlaPolicyTierRecord
from ..validation import validate_bounded_text, validate_reason_code


@dataclass(frozen=True, slots=True)
class _MaterializedPolicy:
    policy_revision_id: str
    policy_revision_ordinal: int
    tier_ids: tuple[str, ...]


def _allocate_policy_ids(validated: ValidatedPolicy) -> tuple[str, tuple[str, ...]]:
    return new_uuid4(), tuple(new_uuid4() for _ in validated.tiers)


def _materialize_validated_policy(
    uow: UnitOfWork,
    *,
    contract_product_line_id: str,
    policy_revision_id: str,
    tier_ids: tuple[str, ...],
    policy_revision_ordinal: int,
    policy_name: str,
    validated: ValidatedPolicy,
    command_id: str,
    created_at_utc: int,
) -> _MaterializedPolicy:
    if len(tier_ids) != len(validated.tiers):
        raise ValidationError("SLA policy tier identity allocation is incomplete")
    ids_by_key = {
        (tier.severity, tier.tier_ordinal): tier_ids[index]
        for index, tier in enumerate(validated.tiers)
    }
    tiers: list[SlaPolicyTierRecord] = []
    for tier in validated.tiers:
        derived_id = None
        if tier.derived_from_minor_ordinal is not None:
            derived_id = ids_by_key[("minor", tier.derived_from_minor_ordinal)]
        tiers.append(
            SlaPolicyTierRecord(
                policy_tier_id=ids_by_key[(tier.severity, tier.tier_ordinal)],
                policy_revision_id=policy_revision_id,
                severity=tier.severity,
                tier_ordinal=tier.tier_ordinal,
                required_percentage_millionths=tier.required_percentage_millionths,
                maximum_duration_numerator_seconds=tier.maximum_duration.numerator_seconds,
                maximum_duration_denominator=tier.maximum_duration.denominator,
                derived_from_tier_id=derived_id,
                derivation_num=tier.derivation_num,
                derivation_den=tier.derivation_den,
            )
        )
    SlaPolicyRepository.insert_revision_with_tiers(
        uow,
        SlaPolicyRevisionRecord(
            policy_revision_id=policy_revision_id,
            contract_product_line_id=contract_product_line_id,
            revision_ordinal=policy_revision_ordinal,
            policy_name=policy_name,
            template_source=validated.template_source,
            created_at_utc=created_at_utc,
            created_command_id=command_id,
        ),
        tuple(tiers),
    )
    return _MaterializedPolicy(
        policy_revision_id=policy_revision_id,
        policy_revision_ordinal=policy_revision_ordinal,
        tier_ids=tuple(tier.policy_tier_id for tier in tiers),
    )


class ProductLineSlaPolicyService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_product_line_sla_audit_registry()),
        )

    def revise_policy(
        self,
        *,
        command_id: str,
        contract_product_line_id: str,
        base_revision: int,
        policy_name: str,
        reason_category: str,
        template_source: str | None = None,
        explicit_tiers: Mapping[str, Sequence[PolicyTierInput]] | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> PolicyRevisionResult:
        cpl_id = require_uuid4(contract_product_line_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be a positive integer")
        stored_name = validate_bounded_text(policy_name, field="policy_name")
        reason = validate_reason_code(reason_category)
        validated = validate_sla_policy(
            template_source=template_source,
            explicit_tiers=explicit_tiers,
        )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReviseSlaPolicy",
            target_type="contract_product_line",
            target_id=cpl_id,
            semantic_payload={
                "policy_name": stored_name,
                "reason_category": reason,
                "template_source": validated.template_source,
                "policy_content_fingerprint": validated.content_fingerprint,
            },
            base_revisions={"contract_product_line": base_revision},
            authorizing_fingerprints={"policy_content": validated.content_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT c.contract_id,c.lifecycle_state,c.revision,c.current_policy_revision_id,"
                "ct.lifecycle_state FROM contract_product_lines c "
                "JOIN contracts ct ON ct.contract_id=c.contract_id "
                "WHERE c.contract_product_line_id=?",
                (cpl_id,),
            ).fetchone()
            if row is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "Contract Product Line does not exist")
            if int(row[2]) != base_revision:
                raise SomaError("SLA_POLICY_STALE", "Contract Product Line revision changed")
            if str(row[1]) != "active" or str(row[4]) != "active":
                raise SomaError("SLA_CATALOG_ARCHIVED", "Contract Product Line or owning Contract is archived")

            prior_policy_id = None if row[3] is None else str(row[3])
            ordinal = SlaPolicyRepository.next_ordinal(uow.connection, cpl_id)
            now = utc_epoch_seconds()
            policy_revision_id, tier_ids = _allocate_policy_ids(validated)
            materialized = _MaterializedPolicy(
                policy_revision_id=policy_revision_id,
                policy_revision_ordinal=ordinal,
                tier_ids=tier_ids,
            )

            def apply(inner: UnitOfWork):
                _materialize_validated_policy(
                    inner,
                    contract_product_line_id=cpl_id,
                    policy_revision_id=policy_revision_id,
                    tier_ids=tier_ids,
                    policy_revision_ordinal=ordinal,
                    policy_name=stored_name,
                    validated=validated,
                    command_id=command_id,
                    created_at_utc=now,
                )
                inner.connection.execute(
                    "UPDATE contract_product_lines SET current_policy_revision_id=?,revision=revision+1,last_command_id=? "
                    "WHERE contract_product_line_id=?",
                    (materialized.policy_revision_id, command_id, cpl_id),
                )
                refs = (
                    AuditResultRef("contract_product_line", cpl_id),
                    AuditResultRef("sla_policy_revision", materialized.policy_revision_id),
                    *tuple(AuditResultRef("sla_policy_tier", tier_id) for tier_id in materialized.tier_ids),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.policy.revised",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="contract_product_line",
                    target_id=cpl_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="SlaPolicyAuditV1",
                    payload_version=1,
                    payload={
                        "contract_product_line_id": cpl_id,
                        "prior_policy_revision_id": prior_policy_id,
                        "new_policy_revision_id": materialized.policy_revision_id,
                        "policy_revision_ordinal": ordinal,
                        "resulting_cpl_revision": base_revision + 1,
                        "tier_count": len(materialized.tier_ids),
                        "policy_fingerprint": validated.content_fingerprint,
                        "reason_category": reason,
                    },
                    resulting_event_refs=refs,
                )

            return PreparedMutation(
                False,
                "sla_policy_revision",
                policy_revision_id,
                apply,
                response_schema="SlaPolicyRevisionResultV1",
                response={
                    "contract_product_line_id": cpl_id,
                    "policy_revision_id": policy_revision_id,
                    "policy_revision_ordinal": ordinal,
                    "cpl_revision": base_revision + 1,
                    "tier_count": len(tier_ids),
                    "content_fingerprint": validated.content_fingerprint,
                },
            )

        return policy_result_from_execution(self._boundary.execute(envelope, prepare))


__all__ = [
    "ProductLineSlaPolicyService",
    "_MaterializedPolicy",
    "_allocate_policy_ids",
    "_materialize_validated_policy",
]
