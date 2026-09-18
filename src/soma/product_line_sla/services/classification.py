from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.reference.domain.validation import validate_account_code

from ..audit_registry import build_product_line_sla_audit_registry
from ..contracts.product_line_sla import (
    CatalogMutationResult,
    ClassificationMutationResult,
    ClassificationPreview,
    catalog_result_from_execution,
    classification_result_from_execution,
)
from ..repositories.classification import (
    ClassificationMappingRecord,
    ClassificationMappingRepository,
    SrClassificationCurrentRecord,
    SrClassificationRepository,
)
from ..validation import validate_reason_code


@dataclass(frozen=True, slots=True)
class _SrClassificationInput:
    sr_revision: int
    customer_relationship_id: str | None
    customer_org_id: str | None
    source_projection_revision: int
    account_observation_id: str | None
    account_code_text: str | None
    current: SrClassificationCurrentRecord | None


@dataclass(frozen=True, slots=True)
class _TargetAuthority:
    contract_product_line_id: str
    cpl_revision: int
    cpl_lifecycle: str
    current_policy_revision_id: str | None
    contract_id: str
    contract_revision: int
    contract_lifecycle: str
    customer_org_id: str


class ProductLineSlaClassificationService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._audit_writer = AuditWriter(build_product_line_sla_audit_registry())
        self._boundary = CommandBoundary(connection_factory, self._audit_writer)

    @staticmethod
    def _sr_input(reader, service_request_id: str) -> _SrClassificationInput:
        row = reader.execute(
            "SELECT s.revision,cr.sr_customer_relationship_id,cr.customer_org_id,"
            "COALESCE(p.revision,0),p.customer_account_code_observation_id,o.text_value "
            "FROM service_requests s "
            "LEFT JOIN sr_customer_relationships cr ON cr.service_request_id=s.service_request_id "
            "AND cr.relationship_state='active' "
            "LEFT JOIN sr_current_source_projection p ON p.service_request_id=s.service_request_id "
            "LEFT JOIN sr_source_field_observations o "
            "ON o.sr_source_field_observation_id=p.customer_account_code_observation_id "
            "WHERE s.service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if row is None:
            raise SomaError("SLA_CATALOG_NOT_FOUND", "Service Request does not exist")
        return _SrClassificationInput(
            sr_revision=int(row[0]),
            customer_relationship_id=None if row[1] is None else str(row[1]),
            customer_org_id=None if row[2] is None else str(row[2]),
            source_projection_revision=int(row[3]),
            account_observation_id=None if row[4] is None else str(row[4]),
            account_code_text=None if row[5] is None else str(row[5]),
            current=SrClassificationRepository.current(reader, service_request_id),
        )

    @staticmethod
    def _target(reader, contract_product_line_id: str) -> _TargetAuthority | None:
        row = reader.execute(
            "SELECT c.contract_product_line_id,c.revision,c.lifecycle_state,c.current_policy_revision_id,"
            "ct.contract_id,ct.revision,ct.lifecycle_state,ct.customer_org_id "
            "FROM contract_product_lines c JOIN contracts ct ON ct.contract_id=c.contract_id "
            "WHERE c.contract_product_line_id=?",
            (contract_product_line_id,),
        ).fetchone()
        if row is None:
            return None
        return _TargetAuthority(
            contract_product_line_id=str(row[0]),
            cpl_revision=int(row[1]),
            cpl_lifecycle=str(row[2]),
            current_policy_revision_id=None if row[3] is None else str(row[3]),
            contract_id=str(row[4]),
            contract_revision=int(row[5]),
            contract_lifecycle=str(row[6]),
            customer_org_id=str(row[7]),
        )

    @staticmethod
    def _preview_fingerprint(
        *,
        sr: _SrClassificationInput,
        target: _TargetAuthority | None,
        mapping_id: str | None,
        mapping_revision: int | None,
        mapping_key: str | None,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_SLA_CLASSIFICATION_PREVIEW_V1",
                "sr_revision": sr.sr_revision,
                "customer_relationship_id": sr.customer_relationship_id,
                "customer_org_id": sr.customer_org_id,
                "source_projection_revision": sr.source_projection_revision,
                "account_observation_id": sr.account_observation_id,
                "account_code_text": sr.account_code_text,
                "current_contract_product_line_id": None if sr.current is None else sr.current.contract_product_line_id,
                "current_classification_revision": 0 if sr.current is None else sr.current.revision,
                "target": None
                if target is None
                else {
                    "contract_product_line_id": target.contract_product_line_id,
                    "cpl_revision": target.cpl_revision,
                    "cpl_lifecycle": target.cpl_lifecycle,
                    "current_policy_revision_id": target.current_policy_revision_id,
                    "contract_id": target.contract_id,
                    "contract_revision": target.contract_revision,
                    "contract_lifecycle": target.contract_lifecycle,
                    "customer_org_id": target.customer_org_id,
                },
                "mapping_id": mapping_id,
                "mapping_revision": mapping_revision,
                "mapping_key": mapping_key,
            }
        )

    @staticmethod
    def _target_state(sr: _SrClassificationInput, target: _TargetAuthority | None) -> str:
        if sr.customer_org_id is None:
            return "customer_unresolved"
        if target is None:
            return "incompatible"
        if target.customer_org_id != sr.customer_org_id:
            return "cross_customer"
        if (
            target.cpl_lifecycle != "active"
            or target.contract_lifecycle != "active"
            or target.current_policy_revision_id is None
        ):
            return "incompatible"
        if sr.current is not None and sr.current.contract_product_line_id == target.contract_product_line_id:
            return "unchanged"
        return "eligible"

    @classmethod
    def _manual_preview_from_reader(
        cls,
        reader,
        *,
        service_request_id: str,
        contract_product_line_id: str,
    ) -> ClassificationPreview:
        sr = cls._sr_input(reader, service_request_id)
        target = cls._target(reader, contract_product_line_id)
        state = cls._target_state(sr, target)
        return ClassificationPreview(
            service_request_id=service_request_id,
            state=state,
            customer_org_id=sr.customer_org_id,
            target_contract_product_line_id=contract_product_line_id,
            mapping_id=None,
            current_contract_product_line_id=None if sr.current is None else sr.current.contract_product_line_id,
            current_revision=0 if sr.current is None else sr.current.revision,
            input_fingerprint=cls._preview_fingerprint(
                sr=sr,
                target=target,
                mapping_id=None,
                mapping_revision=None,
                mapping_key=None,
            ),
        )

    @classmethod
    def _automatic_preview_from_reader(cls, reader, *, service_request_id: str) -> ClassificationPreview:
        sr = cls._sr_input(reader, service_request_id)
        if sr.customer_org_id is None:
            return ClassificationPreview(
                service_request_id=service_request_id,
                state="customer_unresolved",
                customer_org_id=None,
                target_contract_product_line_id=None,
                mapping_id=None,
                current_contract_product_line_id=None if sr.current is None else sr.current.contract_product_line_id,
                current_revision=0 if sr.current is None else sr.current.revision,
                input_fingerprint=cls._preview_fingerprint(
                    sr=sr, target=None, mapping_id=None, mapping_revision=None, mapping_key=None
                ),
            )
        if sr.account_code_text is None:
            return ClassificationPreview(
                service_request_id=service_request_id,
                state="unclassified",
                customer_org_id=sr.customer_org_id,
                target_contract_product_line_id=None,
                mapping_id=None,
                current_contract_product_line_id=None if sr.current is None else sr.current.contract_product_line_id,
                current_revision=0 if sr.current is None else sr.current.revision,
                input_fingerprint=cls._preview_fingerprint(
                    sr=sr, target=None, mapping_id=None, mapping_revision=None, mapping_key=None
                ),
            )
        try:
            _stored, match_key = validate_account_code(sr.account_code_text)
        except ValidationError as exc:
            raise SomaError("SLA_INPUT_INDETERMINATE", "accepted Customer Account Code cannot be normalized") from exc
        matches = ClassificationMappingRepository.match(reader, match_key, sr.customer_org_id)
        if len(matches) != 1:
            state = "unclassified" if not matches else "ambiguous"
            return ClassificationPreview(
                service_request_id=service_request_id,
                state=state,
                customer_org_id=sr.customer_org_id,
                target_contract_product_line_id=None,
                mapping_id=None,
                current_contract_product_line_id=None if sr.current is None else sr.current.contract_product_line_id,
                current_revision=0 if sr.current is None else sr.current.revision,
                input_fingerprint=cls._preview_fingerprint(
                    sr=sr, target=None, mapping_id=None, mapping_revision=None, mapping_key=match_key
                ),
            )
        mapping_id = str(matches[0][0])
        target_id = str(matches[0][1])
        mapping_revision = int(matches[0][2])
        target = cls._target(reader, target_id)
        state = cls._target_state(sr, target)
        return ClassificationPreview(
            service_request_id=service_request_id,
            state=state,
            customer_org_id=sr.customer_org_id,
            target_contract_product_line_id=target_id,
            mapping_id=mapping_id,
            current_contract_product_line_id=None if sr.current is None else sr.current.contract_product_line_id,
            current_revision=0 if sr.current is None else sr.current.revision,
            input_fingerprint=cls._preview_fingerprint(
                sr=sr,
                target=target,
                mapping_id=mapping_id,
                mapping_revision=mapping_revision,
                mapping_key=match_key,
            ),
        )

    def preview_manual(
        self,
        *,
        service_request_id: str,
        contract_product_line_id: str,
    ) -> ClassificationPreview:
        sr_id = require_uuid4(service_request_id)
        cpl_id = require_uuid4(contract_product_line_id)
        with ReadSnapshot(self._factory) as snapshot:
            return self._manual_preview_from_reader(
                snapshot.connection,
                service_request_id=sr_id,
                contract_product_line_id=cpl_id,
            )

    def preview_automatic(self, *, service_request_id: str) -> ClassificationPreview:
        sr_id = require_uuid4(service_request_id)
        with ReadSnapshot(self._factory) as snapshot:
            return self._automatic_preview_from_reader(snapshot.connection, service_request_id=sr_id)

    def create_mapping(
        self,
        *,
        command_id: str,
        customer_org_id: str,
        customer_account_code: str,
        contract_product_line_id: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CatalogMutationResult:
        customer_id = require_uuid4(customer_org_id)
        cpl_id = require_uuid4(contract_product_line_id)
        _stored_code, match_key = validate_account_code(customer_account_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateClassificationMapping",
            target_type="classification_mapping",
            target_id=None,
            semantic_payload={
                "customer_org_id": customer_id,
                "mapping_key_type": "customer_account_code",
                "normalized_key": match_key,
                "contract_product_line_id": cpl_id,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            customer = uow.connection.execute(
                "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
                (customer_id,),
            ).fetchone()
            if customer is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "Customer Organization does not exist")
            if str(customer[0]) != "active":
                raise SomaError("SLA_CATALOG_ARCHIVED", "Customer Organization is archived")
            target = self._target(uow.connection, cpl_id)
            if target is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "Contract Product Line does not exist")
            if target.customer_org_id != customer_id:
                raise SomaError("SLA_CLASSIFICATION_CROSS_CUSTOMER", "mapping target belongs to another Customer")
            if target.cpl_lifecycle != "active" or target.contract_lifecycle != "active":
                raise SomaError("SLA_CATALOG_ARCHIVED", "mapping target is archived")
            mapping_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                ClassificationMappingRepository.insert(
                    inner,
                    ClassificationMappingRecord(
                        mapping_id=mapping_id,
                        mapping_key_type="customer_account_code",
                        normalized_key=match_key,
                        customer_org_id=customer_id,
                        contract_product_line_id=cpl_id,
                        active=True,
                        revision=1,
                        created_at_utc=now,
                        opened_command_id=command_id,
                        closed_command_id=None,
                    ),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.classification_mapping.created_or_superseded",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="classification_mapping",
                    target_id=mapping_id,
                    command_id=command_id,
                    payload_schema="ClassificationMappingAuditV1",
                    payload_version=1,
                    payload={
                        "mapping_id": mapping_id,
                        "customer_org_id": customer_id,
                        "mapping_key_type": "customer_account_code",
                        "normalized_key_fingerprint": hashlib.sha256(match_key.encode("utf-8")).hexdigest(),
                        "contract_product_line_id": cpl_id,
                        "action": "CREATE",
                        "resulting_revision": 1,
                        "reason_category": None,
                    },
                    resulting_event_refs=(AuditResultRef("classification_mapping", mapping_id),),
                )

            return PreparedMutation(
                False,
                "classification_mapping",
                mapping_id,
                apply,
                response_schema="SlaCatalogMutationResultV1",
                response={
                    "target_type": "classification_mapping",
                    "target_id": mapping_id,
                    "revision": 1,
                    "policy_revision_id": None,
                },
            )

        return catalog_result_from_execution(self._boundary.execute(envelope, prepare))

    @staticmethod
    def _raise_preview_state(state: str) -> None:
        if state == "customer_unresolved":
            raise SomaError("SLA_CLASSIFICATION_CUSTOMER_UNRESOLVED", "Service Request Customer is unresolved")
        if state == "cross_customer":
            raise SomaError("SLA_CLASSIFICATION_CROSS_CUSTOMER", "target CPL belongs to another Customer")
        if state == "ambiguous":
            raise SomaError("SLA_CLASSIFICATION_MAPPING_AMBIGUOUS", "more than one trusted mapping applies")
        if state == "unclassified":
            raise SomaError("SLA_CLASSIFICATION_MAPPING_MISSING", "no trusted mapping applies")
        raise SomaError("SLA_CLASSIFICATION_INCOMPATIBLE", "target CPL is not eligible")

    def classify_service_request(
        self,
        *,
        command_id: str,
        service_request_id: str,
        target_contract_product_line_id: str,
        preview_fingerprint: str,
        origin: str,
        reason_category: str,
        mapping_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ClassificationMutationResult:
        sr_id = require_uuid4(service_request_id)
        cpl_id = require_uuid4(target_contract_product_line_id)
        if not isinstance(preview_fingerprint, str) or len(preview_fingerprint) != 64:
            raise ValidationError("preview_fingerprint must be SHA-256 text")
        if origin not in {"manual_review", "automatic_mapping"}:
            raise ValidationError("classification origin must be manual_review or automatic_mapping")
        canonical_mapping_id = None if mapping_id is None else require_uuid4(mapping_id)
        if (origin == "automatic_mapping") != (canonical_mapping_id is not None):
            raise ValidationError("automatic classification requires exactly one mapping_id")
        reason = validate_reason_code(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ClassifyServiceRequest",
            target_type="service_request",
            target_id=sr_id,
            semantic_payload={
                "target_contract_product_line_id": cpl_id,
                "origin": origin,
                "mapping_id": canonical_mapping_id,
                "reason_category": reason,
                "preview_fingerprint": preview_fingerprint,
            },
            authorizing_fingerprints={"classification_preview": preview_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = (
                self._automatic_preview_from_reader(uow.connection, service_request_id=sr_id)
                if origin == "automatic_mapping"
                else self._manual_preview_from_reader(
                    uow.connection,
                    service_request_id=sr_id,
                    contract_product_line_id=cpl_id,
                )
            )
            if not hmac.compare_digest(preview.input_fingerprint, preview_fingerprint):
                raise SomaError("SLA_CLASSIFICATION_STALE", "classification preview changed")
            if preview.target_contract_product_line_id != cpl_id:
                raise SomaError("SLA_CLASSIFICATION_STALE", "classification target changed")
            if origin == "automatic_mapping" and preview.mapping_id != canonical_mapping_id:
                raise SomaError("SLA_CLASSIFICATION_STALE", "classification mapping changed")

            sr = self._sr_input(uow.connection, sr_id)
            if preview.state == "unchanged":
                assert sr.current is not None
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="SlaClassificationMutationResultV1",
                    response={
                        "service_request_id": sr_id,
                        "contract_product_line_id": sr.current.contract_product_line_id,
                        "classification_event_id": sr.current.classification_event_id,
                        "revision": sr.current.revision,
                        "outcome": "NO_CHANGE",
                    },
                )
            if preview.state != "eligible":
                self._raise_preview_state(preview.state)

            target = self._target(uow.connection, cpl_id)
            if target is None or target.current_policy_revision_id is None or sr.customer_org_id is None:
                raise SomaError("SLA_CLASSIFICATION_STALE", "classification authority changed")
            event_id = new_uuid4()
            prior_id = None if sr.current is None else sr.current.contract_product_line_id
            resulting_revision = 1 if sr.current is None else sr.current.revision + 1
            event_kind = "assign" if sr.current is None else "reclassify"
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                SrClassificationRepository.append_event(
                    inner,
                    classification_event_id=event_id,
                    service_request_id=sr_id,
                    event_kind=event_kind,
                    prior_contract_product_line_id=prior_id,
                    new_contract_product_line_id=cpl_id,
                    origin=origin,
                    mapping_id=canonical_mapping_id,
                    reason_code=reason,
                    recorded_at_utc=now,
                    command_id=command_id,
                )
                SrClassificationRepository.set_current(
                    inner,
                    service_request_id=sr_id,
                    contract_product_line_id=cpl_id,
                    classification_event_id=event_id,
                    revision=resulting_revision,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.service_request.classification_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request",
                    target_id=sr_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ServiceRequestClassificationAuditV1",
                    payload_version=1,
                    payload={
                        "service_request_id": sr_id,
                        "classification_event_id": event_id,
                        "event_kind": "ASSIGN" if event_kind == "assign" else "RECLASSIFY",
                        "prior_contract_product_line_id": prior_id,
                        "new_contract_product_line_id": cpl_id,
                        "policy_revision_id": target.current_policy_revision_id,
                        "customer_org_id": sr.customer_org_id,
                        "input_fingerprint": preview.input_fingerprint,
                        "origin": origin,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("sr_classification_event", event_id),),
                )

            return PreparedMutation(
                False,
                "sr_classification_event",
                event_id,
                apply,
                response_schema="SlaClassificationMutationResultV1",
                response={
                    "service_request_id": sr_id,
                    "contract_product_line_id": cpl_id,
                    "classification_event_id": event_id,
                    "revision": resulting_revision,
                    "outcome": "APPLIED",
                },
            )

        return classification_result_from_execution(self._boundary.execute(envelope, prepare))

    def supersede_mapping(
        self,
        *,
        command_id: str,
        mapping_id: str,
        base_revision: int,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CatalogMutationResult:
        identity = require_uuid4(mapping_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be a positive integer")
        reason = validate_reason_code(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SupersedeClassificationMapping",
            target_type="classification_mapping",
            target_id=identity,
            semantic_payload={
                "reason_category": reason,
            },
            base_revisions={"classification_mapping": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = ClassificationMappingRepository.get(uow.connection, identity)
            if current is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "classification mapping does not exist")
            if current.revision != base_revision or not current.active:
                raise SomaError("SLA_STALE", "classification mapping is stale or already superseded")
            resulting_revision = base_revision + 1
            normalized_fingerprint = hashlib.sha256(
                current.normalized_key.encode("utf-8", errors="strict")
            ).hexdigest()

            def apply(inner: UnitOfWork):
                updated = inner.connection.execute(
                    "UPDATE sla_classification_mappings SET active=0,revision=?,closed_command_id=? "
                    "WHERE mapping_id=? AND revision=? AND active=1",
                    (resulting_revision, command_id, identity, base_revision),
                )
                if updated.rowcount != 1:
                    raise SomaError("SLA_STALE", "classification mapping changed")
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.classification_mapping.created_or_superseded",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="classification_mapping",
                    target_id=identity,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ClassificationMappingAuditV1",
                    payload_version=1,
                    payload={
                        "mapping_id": identity,
                        "customer_org_id": current.customer_org_id,
                        "mapping_key_type": current.mapping_key_type,
                        "normalized_key_fingerprint": normalized_fingerprint,
                        "contract_product_line_id": current.contract_product_line_id,
                        "action": "SUPERSEDE",
                        "resulting_revision": resulting_revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("classification_mapping", identity),),
                )

            return PreparedMutation(
                False,
                "classification_mapping",
                identity,
                apply,
                response_schema="SlaCatalogMutationResultV1",
                response={
                    "target_type": "classification_mapping",
                    "target_id": identity,
                    "revision": resulting_revision,
                    "policy_revision_id": None,
                },
            )

        return catalog_result_from_execution(self._boundary.execute(envelope, prepare))

    def clear_service_request_classification(
        self,
        *,
        command_id: str,
        service_request_id: str,
        classification_revision: int,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ClassificationMutationResult:
        sr_id = require_uuid4(service_request_id)
        if type(classification_revision) is not int or classification_revision <= 0:
            raise ValidationError("classification_revision must be a positive integer")
        reason = validate_reason_code(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ClearSrClassification",
            target_type="service_request",
            target_id=sr_id,
            semantic_payload={
                "classification_revision": classification_revision,
                "reason_category": reason,
            },
            base_revisions={"classification": classification_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = SrClassificationRepository.current(uow.connection, sr_id)
            if current is None or current.revision != classification_revision:
                raise SomaError("SLA_CLASSIFICATION_STALE", "current classification changed")
            sr = self._sr_input(uow.connection, sr_id)
            target = self._target(uow.connection, current.contract_product_line_id)
            if target is None:
                raise SomaError(
                    "SLA_DEPENDENCY_INDETERMINATE",
                    "current classification target no longer resolves",
                )
            event_id = new_uuid4()
            resulting_revision = classification_revision + 1
            fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_SLA_CLASSIFICATION_CLEAR_V1",
                    "service_request_id": sr_id,
                    "classification_event_id": current.classification_event_id,
                    "classification_revision": classification_revision,
                    "contract_product_line_id": current.contract_product_line_id,
                    "customer_org_id": sr.customer_org_id,
                    "current_policy_revision_id": target.current_policy_revision_id,
                }
            )
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                SrClassificationRepository.append_event(
                    inner,
                    classification_event_id=event_id,
                    service_request_id=sr_id,
                    event_kind="clear",
                    prior_contract_product_line_id=current.contract_product_line_id,
                    new_contract_product_line_id=None,
                    origin="manual_review",
                    mapping_id=None,
                    reason_code=reason,
                    recorded_at_utc=now,
                    command_id=command_id,
                )
                SrClassificationRepository.clear_current(inner, sr_id)
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.service_request.classification_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request",
                    target_id=sr_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ServiceRequestClassificationAuditV1",
                    payload_version=1,
                    payload={
                        "service_request_id": sr_id,
                        "classification_event_id": event_id,
                        "event_kind": "CLEAR",
                        "prior_contract_product_line_id": current.contract_product_line_id,
                        "new_contract_product_line_id": None,
                        "policy_revision_id": target.current_policy_revision_id,
                        "customer_org_id": sr.customer_org_id,
                        "input_fingerprint": fingerprint,
                        "origin": "clear",
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("sr_classification_event", event_id),),
                )

            return PreparedMutation(
                False,
                "sr_classification_event",
                event_id,
                apply,
                response_schema="SlaClassificationMutationResultV1",
                response={
                    "service_request_id": sr_id,
                    "contract_product_line_id": None,
                    "classification_event_id": event_id,
                    "revision": resulting_revision,
                    "outcome": "CLEARED",
                },
            )

        return classification_result_from_execution(self._boundary.execute(envelope, prepare))

    def preview_customer_change(self, reader, sr_id: str, new_customer_org_id: str | None) -> object:
        current = SrClassificationRepository.current(reader, sr_id)
        if current is None:
            return {"impact": "NO_CHANGE"}
        target = self._target(reader, current.contract_product_line_id)
        if target is None:
            return {"impact": "INDETERMINATE"}
        return {
            "impact": "NO_CHANGE" if target.customer_org_id == new_customer_org_id else "INVALIDATE",
            "contract_product_line_id": current.contract_product_line_id,
        }

    def apply_customer_change(
        self,
        uow: UnitOfWork,
        sr_id: str,
        new_customer_org_id: str | None,
        command_context: dict[str, object],
    ) -> object:
        current = SrClassificationRepository.current(uow.connection, sr_id)
        if current is None:
            return "NO_CHANGE"
        target = self._target(uow.connection, current.contract_product_line_id)
        if target is None:
            return "INDETERMINATE"
        if target.customer_org_id == new_customer_org_id:
            return "NO_CHANGE"
        command_id = command_context.get("command_id")
        if not isinstance(command_id, str):
            return "INDETERMINATE"
        try:
            require_uuid4(command_id)
        except ValidationError:
            return "INDETERMINATE"
        reason_value = command_context.get("reason_category")
        reason = reason_value if isinstance(reason_value, str) and reason_value else "customer_change"
        event_id = new_uuid4()
        now = utc_epoch_seconds()
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_SLA_CUSTOMER_INVALIDATION_V1",
                "service_request_id": sr_id,
                "prior_contract_product_line_id": current.contract_product_line_id,
                "classification_revision": current.revision,
                "contract_customer_org_id": target.customer_org_id,
                "new_customer_org_id": new_customer_org_id,
            }
        )
        SrClassificationRepository.append_event(
            uow,
            classification_event_id=event_id,
            service_request_id=sr_id,
            event_kind="invalidate_customer",
            prior_contract_product_line_id=current.contract_product_line_id,
            new_contract_product_line_id=None,
            origin="customer_correction",
            mapping_id=None,
            reason_code=reason,
            recorded_at_utc=now,
            command_id=command_id,
        )
        SrClassificationRepository.clear_current(uow, sr_id)
        self._audit_writer.write(
            uow,
            AuditEventInput(
                audit_event_id=new_uuid4(),
                action_type="sla.service_request.classification_changed",
                action_version=1,
                actor_kind=str(command_context.get("actor_kind") or "local_user"),
                actor_id=command_context.get("actor_id") if isinstance(command_context.get("actor_id"), str) else None,
                target_type="service_request",
                target_id=sr_id,
                reason_category=reason,
                command_id=command_id,
                payload_schema="ServiceRequestClassificationAuditV1",
                payload_version=1,
                payload={
                    "service_request_id": sr_id,
                    "classification_event_id": event_id,
                    "event_kind": "INVALIDATE_CUSTOMER",
                    "prior_contract_product_line_id": current.contract_product_line_id,
                    "new_contract_product_line_id": None,
                    "policy_revision_id": target.current_policy_revision_id,
                    "customer_org_id": new_customer_org_id,
                    "input_fingerprint": fingerprint,
                    "origin": "customer_change",
                    "reason_category": reason,
                },
                resulting_event_refs=(AuditResultRef("sr_classification_event", event_id),),
            ),
        )
        return {"outcome": "INVALIDATED", "classification_event_id": event_id}


__all__ = ["ProductLineSlaClassificationService"]
