from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from ..algorithms.policy_validation import PolicyTierInput, ValidatedPolicy, validate_sla_policy
from ..audit_registry import build_product_line_sla_audit_registry
from ..contracts.product_line_sla import CatalogMutationResult, catalog_result_from_execution
from ..repositories.catalog import (
    ContractProductLineRecord,
    ContractProductLineRepository,
    ContractRecord,
    ContractRepository,
    ProductLineRecord,
    ProductLineRepository,
)
from ..validation import validate_bounded_text, validate_reason_code
from .policy import _allocate_policy_ids, _materialize_validated_policy

_INITIAL_POLICY_REASON = "initial_policy_materialization"


def _fingerprint_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


class ProductLineSlaCatalogService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_product_line_sla_audit_registry()),
        )

    @staticmethod
    def _catalog_response(
        *,
        target_type: str,
        target_id: str,
        revision: int,
        policy_revision_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "target_type": target_type,
            "target_id": target_id,
            "revision": revision,
            "policy_revision_id": policy_revision_id,
        }

    @staticmethod
    def _require_active_customer(connection, customer_org_id: str) -> None:
        row = connection.execute(
            "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
            (customer_org_id,),
        ).fetchone()
        if row is None:
            raise SomaError("SLA_CATALOG_NOT_FOUND", "Customer Organization does not exist")
        if str(row[0]) != "active":
            raise SomaError("SLA_CATALOG_ARCHIVED", "Customer Organization is archived")

    def create_product_line(
        self,
        *,
        command_id: str,
        name: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CatalogMutationResult:
        stored_name = validate_bounded_text(name, field="product_line_name")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateProductLine",
            target_type="product_line",
            target_id=None,
            semantic_payload={"name": stored_name},
        )

        def prepare(_uow: UnitOfWork) -> PreparedMutation:
            product_line_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                ProductLineRepository.insert(
                    inner,
                    ProductLineRecord(
                        product_line_id=product_line_id,
                        name=stored_name,
                        lifecycle_state="active",
                        revision=1,
                        created_at_utc=now,
                        created_command_id=command_id,
                        last_command_id=command_id,
                    ),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.product_line.created_or_updated",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="product_line",
                    target_id=product_line_id,
                    command_id=command_id,
                    payload_schema="ProductLineAuditV1",
                    payload_version=1,
                    payload={
                        "product_line_id": product_line_id,
                        "change_kind": "CREATE",
                        "prior_revision": None,
                        "resulting_revision": 1,
                        "name_fingerprint": _fingerprint_text(stored_name),
                        "reason_category": None,
                    },
                    resulting_event_refs=(AuditResultRef("product_line", product_line_id),),
                )

            return PreparedMutation(
                False,
                "product_line",
                product_line_id,
                apply,
                response_schema="SlaCatalogMutationResultV1",
                response=self._catalog_response(
                    target_type="product_line",
                    target_id=product_line_id,
                    revision=1,
                ),
            )

        return catalog_result_from_execution(self._boundary.execute(envelope, prepare))

    def create_contract(
        self,
        *,
        command_id: str,
        customer_org_id: str,
        name: str,
        contract_reference: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CatalogMutationResult:
        customer_id = require_uuid4(customer_org_id)
        stored_name = validate_bounded_text(name, field="contract_name")
        stored_reference = validate_bounded_text(contract_reference, field="contract_reference")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateContract",
            target_type="contract",
            target_id=None,
            semantic_payload={
                "customer_org_id": customer_id,
                "name": stored_name,
                "contract_reference": stored_reference,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._require_active_customer(uow.connection, customer_id)
            contract_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                ContractRepository.insert(
                    inner,
                    ContractRecord(
                        contract_id=contract_id,
                        customer_org_id=customer_id,
                        name=stored_name,
                        contract_reference=stored_reference,
                        lifecycle_state="active",
                        revision=1,
                        created_at_utc=now,
                        created_command_id=command_id,
                        last_command_id=command_id,
                    ),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.contract.created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="contract",
                    target_id=contract_id,
                    command_id=command_id,
                    payload_schema="ContractAuditV1",
                    payload_version=1,
                    payload={
                        "contract_id": contract_id,
                        "customer_org_id": customer_id,
                        "resulting_revision": 1,
                        "contract_reference_fingerprint": _fingerprint_text(stored_reference),
                        "name_fingerprint": _fingerprint_text(stored_name),
                    },
                    resulting_event_refs=(AuditResultRef("contract", contract_id),),
                )

            return PreparedMutation(
                False,
                "contract",
                contract_id,
                apply,
                response_schema="SlaCatalogMutationResultV1",
                response=self._catalog_response(
                    target_type="contract",
                    target_id=contract_id,
                    revision=1,
                ),
            )

        return catalog_result_from_execution(self._boundary.execute(envelope, prepare))

    def create_contract_product_line(
        self,
        *,
        command_id: str,
        contract_id: str,
        product_line_id: str,
        initial_policy_name: str | None = None,
        initial_template_source: str | None = None,
        initial_explicit_tiers: Mapping[str, Sequence[PolicyTierInput]] | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CatalogMutationResult:
        contract_identity = require_uuid4(contract_id)
        product_identity = require_uuid4(product_line_id)
        has_policy_spec = initial_template_source is not None or initial_explicit_tiers is not None
        if has_policy_spec != (initial_policy_name is not None):
            raise ValidationError("initial policy name and policy specification must be supplied together")
        validated_policy: ValidatedPolicy | None = None
        stored_policy_name: str | None = None
        if has_policy_spec:
            stored_policy_name = validate_bounded_text(initial_policy_name, field="policy_name")  # type: ignore[arg-type]
            validated_policy = validate_sla_policy(
                template_source=initial_template_source,
                explicit_tiers=initial_explicit_tiers,
            )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateContractProductLine",
            target_type="contract_product_line",
            target_id=None,
            semantic_payload={
                "contract_id": contract_identity,
                "product_line_id": product_identity,
                "initial_policy_name": stored_policy_name,
                "initial_template_source": None if validated_policy is None else validated_policy.template_source,
                "initial_policy_fingerprint": None if validated_policy is None else validated_policy.content_fingerprint,
            },
            authorizing_fingerprints=(
                {}
                if validated_policy is None
                else {"initial_policy_content": validated_policy.content_fingerprint}
            ),
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            contract = ContractRepository.get(uow.connection, contract_identity)
            if contract is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "Contract does not exist")
            product_line = ProductLineRepository.get(uow.connection, product_identity)
            if product_line is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "Product Line does not exist")
            if contract.lifecycle_state != "active" or product_line.lifecycle_state != "active":
                raise SomaError("SLA_CATALOG_ARCHIVED", "Contract or Product Line is archived")

            cpl_id = new_uuid4()
            now = utc_epoch_seconds()
            policy_revision_id: str | None = None
            tier_ids: tuple[str, ...] = ()
            if validated_policy is not None:
                policy_revision_id, tier_ids = _allocate_policy_ids(validated_policy)

            def apply(inner: UnitOfWork):
                ContractProductLineRepository.insert(
                    inner,
                    ContractProductLineRecord(
                        contract_product_line_id=cpl_id,
                        contract_id=contract_identity,
                        product_line_id=product_identity,
                        lifecycle_state="active",
                        current_policy_revision_id=None,
                        revision=1,
                        created_at_utc=now,
                        created_command_id=command_id,
                        last_command_id=command_id,
                    ),
                )
                events: list[AuditEventInput] = []
                events.append(
                    AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="sla.contract_product_line.created",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="contract_product_line",
                        target_id=cpl_id,
                        command_id=command_id,
                        payload_schema="ContractProductLineAuditV1",
                        payload_version=1,
                        payload={
                            "contract_product_line_id": cpl_id,
                            "contract_id": contract_identity,
                            "product_line_id": product_identity,
                            "customer_org_id": contract.customer_org_id,
                            "resulting_revision": 1,
                            "initial_policy_revision_id": policy_revision_id,
                        },
                        resulting_event_refs=(AuditResultRef("contract_product_line", cpl_id),),
                    )
                )
                if validated_policy is not None:
                    assert stored_policy_name is not None and policy_revision_id is not None
                    materialized = _materialize_validated_policy(
                        inner,
                        contract_product_line_id=cpl_id,
                        policy_revision_id=policy_revision_id,
                        tier_ids=tier_ids,
                        policy_revision_ordinal=1,
                        policy_name=stored_policy_name,
                        validated=validated_policy,
                        command_id=command_id,
                        created_at_utc=now,
                    )
                    inner.connection.execute(
                        "UPDATE contract_product_lines SET current_policy_revision_id=? WHERE contract_product_line_id=?",
                        (policy_revision_id, cpl_id),
                    )
                    events.append(
                        AuditEventInput(
                            audit_event_id=new_uuid4(),
                            action_type="sla.policy.revised",
                            action_version=1,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                            target_type="contract_product_line",
                            target_id=cpl_id,
                            command_id=command_id,
                            reason_category=_INITIAL_POLICY_REASON,
                            payload_schema="SlaPolicyAuditV1",
                            payload_version=1,
                            payload={
                                "contract_product_line_id": cpl_id,
                                "prior_policy_revision_id": None,
                                "new_policy_revision_id": policy_revision_id,
                                "policy_revision_ordinal": 1,
                                "resulting_cpl_revision": 1,
                                "tier_count": len(materialized.tier_ids),
                                "policy_fingerprint": validated_policy.content_fingerprint,
                                "reason_category": _INITIAL_POLICY_REASON,
                            },
                            resulting_event_refs=(
                                AuditResultRef("contract_product_line", cpl_id),
                                AuditResultRef("sla_policy_revision", policy_revision_id),
                                *tuple(AuditResultRef("sla_policy_tier", tier_id) for tier_id in materialized.tier_ids),
                            ),
                        )
                    )
                return tuple(events)

            return PreparedMutation(
                False,
                "contract_product_line",
                cpl_id,
                apply,
                response_schema="SlaCatalogMutationResultV1",
                response=self._catalog_response(
                    target_type="contract_product_line",
                    target_id=cpl_id,
                    revision=1,
                    policy_revision_id=policy_revision_id,
                ),
            )

        return catalog_result_from_execution(self._boundary.execute(envelope, prepare))


    def update_product_line(
        self,
        *,
        command_id: str,
        product_line_id: str,
        base_revision: int,
        name: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CatalogMutationResult:
        product_id = require_uuid4(product_line_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be a positive integer")
        stored_name = validate_bounded_text(name, field="product_line_name")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UpdateProductLine",
            target_type="product_line",
            target_id=product_id,
            semantic_payload={"name": stored_name},
            base_revisions={"product_line": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = ProductLineRepository.get(uow.connection, product_id)
            if current is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "Product Line does not exist")
            if current.revision != base_revision:
                raise SomaError("SLA_STALE", "Product Line revision changed")
            if current.name == stored_name:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="SlaCatalogMutationResultV1",
                    response=self._catalog_response(
                        target_type="product_line",
                        target_id=product_id,
                        revision=base_revision,
                    ),
                )
            resulting_revision = base_revision + 1

            def apply(inner: UnitOfWork):
                updated = inner.connection.execute(
                    "UPDATE product_lines SET name=?,revision=?,last_command_id=? "
                    "WHERE product_line_id=? AND revision=?",
                    (stored_name, resulting_revision, command_id, product_id, base_revision),
                )
                if updated.rowcount != 1:
                    raise SomaError("SLA_STALE", "Product Line revision changed")
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.product_line.created_or_updated",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="product_line",
                    target_id=product_id,
                    command_id=command_id,
                    payload_schema="ProductLineAuditV1",
                    payload_version=1,
                    payload={
                        "product_line_id": product_id,
                        "change_kind": "UPDATE",
                        "prior_revision": base_revision,
                        "resulting_revision": resulting_revision,
                        "name_fingerprint": _fingerprint_text(stored_name),
                        "reason_category": None,
                    },
                    resulting_event_refs=(AuditResultRef("product_line", product_id),),
                )

            return PreparedMutation(
                False,
                "product_line",
                product_id,
                apply,
                response_schema="SlaCatalogMutationResultV1",
                response=self._catalog_response(
                    target_type="product_line",
                    target_id=product_id,
                    revision=resulting_revision,
                ),
            )

        return catalog_result_from_execution(self._boundary.execute(envelope, prepare))

    def set_catalog_lifecycle(
        self,
        *,
        command_id: str,
        target_type: str,
        target_id: str,
        base_revision: int,
        lifecycle_state: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CatalogMutationResult:
        tables = {
            "product_line": ("product_lines", "product_line_id"),
            "contract": ("contracts", "contract_id"),
            "contract_product_line": ("contract_product_lines", "contract_product_line_id"),
        }
        if target_type not in tables:
            raise ValidationError("catalog lifecycle target_type is invalid")
        identity = require_uuid4(target_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be a positive integer")
        if lifecycle_state not in {"active", "archived"}:
            raise ValidationError("catalog lifecycle state must be active or archived")
        reason = validate_reason_code(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetCatalogLifecycle",
            target_type=target_type,
            target_id=identity,
            semantic_payload={
                "lifecycle_state": lifecycle_state,
                "reason_category": reason,
            },
            base_revisions={target_type: base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            table, id_column = tables[target_type]
            row = uow.connection.execute(
                f"SELECT lifecycle_state,revision FROM {table} WHERE {id_column}=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "catalog target does not exist")
            prior_state = str(row[0])
            current_revision = int(row[1])
            if current_revision != base_revision:
                raise SomaError("SLA_STALE", "catalog target revision changed")

            dependency_state: dict[str, object] = {
                "schema": "SOMA_SLA_CATALOG_LIFECYCLE_DEPENDENCY_V1",
                "target_type": target_type,
                "target_id": identity,
                "prior_state": prior_state,
                "requested_state": lifecycle_state,
                "base_revision": base_revision,
            }

            if target_type == "product_line":
                active_cpls = [
                    str(dep[0])
                    for dep in uow.connection.execute(
                        "SELECT contract_product_line_id FROM contract_product_lines "
                        "WHERE product_line_id=? AND lifecycle_state='active' "
                        "ORDER BY contract_product_line_id",
                        (identity,),
                    ).fetchall()
                ]
                dependency_state["active_contract_product_line_ids"] = active_cpls
                if lifecycle_state == "archived" and active_cpls:
                    raise SomaError(
                        "SLA_DEPENDENCY_INDETERMINATE",
                        "Product Line archival is blocked by active Contract Product Lines",
                    )
            elif target_type == "contract":
                contract = uow.connection.execute(
                    "SELECT customer_org_id FROM contracts WHERE contract_id=?",
                    (identity,),
                ).fetchone()
                if contract is None:
                    raise SomaError("SLA_CATALOG_NOT_FOUND", "Contract does not exist")
                customer_id = str(contract[0])
                customer = uow.connection.execute(
                    "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
                    (customer_id,),
                ).fetchone()
                customer_state = None if customer is None else str(customer[0])
                active_cpls = [
                    str(dep[0])
                    for dep in uow.connection.execute(
                        "SELECT contract_product_line_id FROM contract_product_lines "
                        "WHERE contract_id=? AND lifecycle_state='active' "
                        "ORDER BY contract_product_line_id",
                        (identity,),
                    ).fetchall()
                ]
                dependency_state["customer_org_id"] = customer_id
                dependency_state["customer_lifecycle_state"] = customer_state
                dependency_state["active_contract_product_line_ids"] = active_cpls
                if lifecycle_state == "archived" and active_cpls:
                    raise SomaError(
                        "SLA_DEPENDENCY_INDETERMINATE",
                        "Contract archival is blocked by active Contract Product Lines",
                    )
                if lifecycle_state == "active" and customer_state != "active":
                    raise SomaError(
                        "SLA_DEPENDENCY_INDETERMINATE",
                        "Contract cannot reactivate while its Customer is unavailable",
                    )
            else:
                owners = uow.connection.execute(
                    "SELECT ct.lifecycle_state,p.lifecycle_state,c.current_policy_revision_id "
                    "FROM contract_product_lines c "
                    "JOIN contracts ct ON ct.contract_id=c.contract_id "
                    "JOIN product_lines p ON p.product_line_id=c.product_line_id "
                    "WHERE c.contract_product_line_id=?",
                    (identity,),
                ).fetchone()
                if owners is None:
                    raise SomaError("SLA_CATALOG_NOT_FOUND", "Contract Product Line does not exist")
                current_classifications = [
                    str(dep[0])
                    for dep in uow.connection.execute(
                        "SELECT service_request_id FROM sr_classification_current "
                        "WHERE contract_product_line_id=? ORDER BY service_request_id",
                        (identity,),
                    ).fetchall()
                ]
                dependency_state["contract_lifecycle_state"] = str(owners[0])
                dependency_state["product_line_lifecycle_state"] = str(owners[1])
                dependency_state["current_policy_revision_id"] = None if owners[2] is None else str(owners[2])
                dependency_state["current_classified_service_request_ids"] = current_classifications
                if lifecycle_state == "archived" and current_classifications:
                    raise SomaError(
                        "SLA_DEPENDENCY_INDETERMINATE",
                        "Contract Product Line archival is blocked by current Service Request classifications",
                    )
                if lifecycle_state == "active" and (str(owners[0]) != "active" or str(owners[1]) != "active"):
                    raise SomaError(
                        "SLA_DEPENDENCY_INDETERMINATE",
                        "Contract Product Line cannot reactivate under archived catalog owners",
                    )

            dependency_fingerprint = sha256_canonical_json(dependency_state)
            if prior_state == lifecycle_state:
                policy_id = None
                if target_type == "contract_product_line":
                    current = ContractProductLineRepository.get(uow.connection, identity)
                    policy_id = None if current is None else current.current_policy_revision_id
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="SlaCatalogMutationResultV1",
                    response=self._catalog_response(
                        target_type=target_type,
                        target_id=identity,
                        revision=base_revision,
                        policy_revision_id=policy_id,
                    ),
                )

            resulting_revision = base_revision + 1

            def apply(inner: UnitOfWork):
                updated = inner.connection.execute(
                    f"UPDATE {table} SET lifecycle_state=?,revision=?,last_command_id=? "
                    f"WHERE {id_column}=? AND revision=?",
                    (lifecycle_state, resulting_revision, command_id, identity, base_revision),
                )
                if updated.rowcount != 1:
                    raise SomaError("SLA_STALE", "catalog target revision changed")
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.catalog_lifecycle.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type=target_type,
                    target_id=identity,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="CatalogLifecycleAuditV1",
                    payload_version=1,
                    payload={
                        "target_type": target_type,
                        "target_id": identity,
                        "prior_state": prior_state,
                        "new_state": lifecycle_state,
                        "prior_revision": base_revision,
                        "resulting_revision": resulting_revision,
                        "dependency_fingerprint": dependency_fingerprint,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("catalog_entity", identity),),
                )

            policy_id = None
            if target_type == "contract_product_line":
                current = ContractProductLineRepository.get(uow.connection, identity)
                policy_id = None if current is None else current.current_policy_revision_id
            return PreparedMutation(
                False,
                target_type,
                identity,
                apply,
                response_schema="SlaCatalogMutationResultV1",
                response=self._catalog_response(
                    target_type=target_type,
                    target_id=identity,
                    revision=resulting_revision,
                    policy_revision_id=policy_id,
                ),
            )

        return catalog_result_from_execution(self._boundary.execute(envelope, prepare))


__all__ = ["ProductLineSlaCatalogService"]
