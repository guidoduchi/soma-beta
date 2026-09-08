from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json


_SR_POINTERS: tuple[tuple[str, str], ...] = (
    ("problem_summary", "problem_summary_observation_id"),
    ("report_date", "report_date_observation_id"),
    ("customer_contact_label", "customer_contact_observation_id"),
    ("customer_severity", "customer_severity_observation_id"),
    ("current_handler_label", "current_handler_observation_id"),
    ("status", "status_observation_id"),
    ("customer_org_label", "customer_org_observation_id"),
    ("customer_account_code", "customer_account_code_observation_id"),
    ("suspend_planned_end", "suspend_planned_end_observation_id"),
    ("suspension_duration", "suspension_duration_observation_id"),
    ("last_update", "last_update_observation_id"),
)


@dataclass(frozen=True, slots=True)
class ServiceRequestDetail:
    service_request_id: str
    identity: dict[str, str | None]
    revision: int
    source_projection: dict[str, Any] | None
    reference_context: dict[str, Any]
    linked_root_rfc_count: int
    device_reference_count: int
    warnings: tuple[str, ...]


class ServiceRequestQueryService:
    """Read-only LLD-03 point projection for Service Requests."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _lookup(connection, *, service_request_id: str | None, business_identity: str | None):
        if (service_request_id is None) == (business_identity is None):
            raise ValidationError("exactly one Service Request lookup identity is required")
        if service_request_id is not None:
            return connection.execute(
                "SELECT service_request_id,official_sr_no,local_sr_no,revision FROM service_requests WHERE service_request_id=?",
                (service_request_id,),
            ).fetchone()
        assert business_identity is not None
        if len(business_identity) == 8 and business_identity.isascii() and business_identity.isdigit():
            return connection.execute(
                "SELECT service_request_id,official_sr_no,local_sr_no,revision FROM service_requests WHERE official_sr_no=?",
                (business_identity,),
            ).fetchone()
        if len(business_identity) == 12 and business_identity.startswith("LSR-") and business_identity[4:].isascii() and business_identity[4:].isdigit():
            return connection.execute(
                "SELECT service_request_id,official_sr_no,local_sr_no,revision FROM service_requests WHERE local_sr_no=?",
                (business_identity,),
            ).fetchone()
        raise ValidationError("Service Request business identity must be exact SR-8 or LSR-########")

    @staticmethod
    def _source_projection(connection, service_request_id: str) -> dict[str, Any] | None:
        columns = [column for _, column in _SR_POINTERS]
        row = connection.execute(
            "SELECT " + ",".join(columns) + ",revision FROM sr_current_source_projection WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if row is None:
            return None
        pointers = row[:-1]
        if not any(pointer is not None for pointer in pointers):
            return None
        fields: dict[str, Any] = {}
        for (expected_field, _column), observation_id in zip(_SR_POINTERS, pointers, strict=True):
            if observation_id is None:
                continue
            observation = connection.execute(
                "SELECT field_key,value_state,value_kind,text_value,integer_value,source_chronology_utc,"
                "precedence_basis,source_observation_field_id FROM sr_source_field_observations "
                "WHERE sr_source_field_observation_id=? AND service_request_id=?",
                (observation_id, service_request_id),
            ).fetchone()
            if observation is None or str(observation[0]) != expected_field:
                raise SomaError("PERSISTENCE_FAILURE", "Service Request source projection points to invalid evidence")
            fields[expected_field] = {
                "observation_id": str(observation_id),
                "value_state": str(observation[1]),
                "value_kind": str(observation[2]),
                "value": observation[3] if observation[3] is not None else observation[4],
                "source_chronology_utc": observation[5],
                "precedence_basis": str(observation[6]),
                "source_observation_field_id": str(observation[7]),
            }
        return {"revision": int(row[-1]), "fields": fields}

    @staticmethod
    def _reference_context(connection, service_request_id: str, sr_revision: int) -> tuple[dict[str, Any], tuple[str, ...]]:
        warnings: list[str] = []
        customer_row = connection.execute(
            "SELECT rel.sr_customer_relationship_id,rel.customer_org_id,rel.origin_kind,rel.opened_at_utc,"
            "org.revision,org.lifecycle_state FROM sr_customer_relationships rel "
            "JOIN customer_organizations org ON org.customer_org_id=rel.customer_org_id "
            "WHERE rel.service_request_id=? AND rel.relationship_state='active'",
            (service_request_id,),
        ).fetchone()
        customer: dict[str, Any] | None = None
        customer_token: dict[str, Any] | None = None
        if customer_row is not None:
            customer = {
                "relationship_id": str(customer_row[0]),
                "customer_org_id": str(customer_row[1]),
                "origin_kind": str(customer_row[2]),
                "opened_at_utc": int(customer_row[3]),
                "customer_revision": int(customer_row[4]),
                "customer_lifecycle_state": str(customer_row[5]),
            }
            customer_token = {
                "relationship_id": str(customer_row[0]),
                "customer_org_id": str(customer_row[1]),
                "target_revision": int(customer_row[4]),
                "target_lifecycle": str(customer_row[5]),
            }
            if str(customer_row[5]) != "active":
                warnings.append("SR_CUSTOMER_REFERENCE_ARCHIVED")

        projection = connection.execute(
            "SELECT customer_org_observation_id,customer_account_code_observation_id,current_handler_observation_id "
            "FROM sr_current_source_projection WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        source_customer_present = bool(projection and (projection[0] is not None or projection[1] is not None))
        current_handler_observation_id = None if projection is None or projection[2] is None else str(projection[2])
        current_handler_usable = False
        if current_handler_observation_id is not None:
            handler_obs = connection.execute(
                "SELECT value_state FROM sr_source_field_observations WHERE sr_source_field_observation_id=? AND service_request_id=? AND field_key='current_handler_label'",
                (current_handler_observation_id, service_request_id),
            ).fetchone()
            current_handler_usable = handler_obs is not None and str(handler_obs[0]) == "usable"
        if customer is None and source_customer_present:
            warnings.append("SR_CUSTOMER_UNRESOLVED")

        contacts: dict[str, Any] = {}
        contact_tokens: dict[str, Any] = {}
        for role in ("customer_contact", "current_handler_reference"):
            row = connection.execute(
                "SELECT rel.sr_contact_relationship_id,rel.contact_id,rel.customer_org_context_id,"
                "rel.supporting_sr_source_field_observation_id,rel.origin_kind,rel.opened_at_utc,"
                "c.revision,c.lifecycle_state,a.contact_affiliation_id,a.customer_org_id "
                "FROM sr_contact_relationships rel "
                "JOIN contacts c ON c.contact_id=rel.contact_id "
                "LEFT JOIN contact_affiliations a ON a.contact_id=c.contact_id AND a.is_current=1 "
                "WHERE rel.service_request_id=? AND rel.reference_role=? AND rel.relationship_state='active'",
                (service_request_id, role),
            ).fetchone()
            if row is None:
                contacts[role] = None
                contact_tokens[role] = None
                continue
            supporting_observation_id = None if row[3] is None else str(row[3])
            alignment = None
            if role == "current_handler_reference":
                alignment = (
                    "aligned"
                    if current_handler_usable and supporting_observation_id == current_handler_observation_id
                    else "stale"
                )
                if alignment == "stale":
                    warnings.append("SR_HANDLER_REFERENCE_STALE")
            contacts[role] = {
                "relationship_id": str(row[0]),
                "contact_id": str(row[1]),
                "customer_org_context_id": None if row[2] is None else str(row[2]),
                "supporting_sr_source_field_observation_id": supporting_observation_id,
                "origin_kind": str(row[4]),
                "opened_at_utc": int(row[5]),
                "contact_revision": int(row[6]),
                "contact_lifecycle_state": str(row[7]),
                "current_affiliation_id": None if row[8] is None else str(row[8]),
                "current_affiliation_customer_org_id": None if row[9] is None else str(row[9]),
                "alignment": alignment,
            }
            contact_tokens[role] = {
                "relationship_id": str(row[0]),
                "contact_id": str(row[1]),
                "target_revision": int(row[6]),
                "target_lifecycle": str(row[7]),
                "current_affiliation_id": None if row[8] is None else str(row[8]),
                "current_affiliation_customer_org_id": None if row[9] is None else str(row[9]),
                "supporting_observation_id": supporting_observation_id,
            }
            if str(row[7]) != "active":
                warnings.append(f"SR_{role.upper()}_REFERENCE_ARCHIVED")

        fingerprint = sha256_canonical_json(
            {
                "service_request_id": service_request_id,
                "sr_revision": sr_revision,
                "customer": customer_token,
                "contacts": contact_tokens,
                "current_handler_observation_id": current_handler_observation_id,
            }
        )
        context = {
            "service_request_id": service_request_id,
            "customer": customer,
            "contacts": contacts,
            "review_fingerprint": fingerprint,
        }
        return context, tuple(sorted(set(warnings)))

    def get(
        self,
        *,
        service_request_id: str | None = None,
        business_identity: str | None = None,
    ) -> ServiceRequestDetail:
        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            row = self._lookup(connection, service_request_id=service_request_id, business_identity=business_identity)
            if row is None:
                raise SomaError("NOT_FOUND", "Service Request does not exist")
            sr_id = str(row[0])
            revision = int(row[3])
            source_projection = self._source_projection(connection, sr_id)
            reference_context, reference_warnings = self._reference_context(connection, sr_id, revision)
            linked_root_rfc_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM sr_rfc_links WHERE service_request_id=? AND link_state='active'",
                    (sr_id,),
                ).fetchone()[0]
            )
            device_reference_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM sr_device_reference_links WHERE service_request_id=? AND link_state='active'",
                    (sr_id,),
                ).fetchone()[0]
            )
        return ServiceRequestDetail(
            service_request_id=sr_id,
            identity={
                "official_sr_no": None if row[1] is None else str(row[1]),
                "local_sr_no": None if row[2] is None else str(row[2]),
            },
            revision=revision,
            source_projection=source_projection,
            reference_context=reference_context,
            linked_root_rfc_count=linked_root_rfc_count,
            device_reference_count=device_reference_count,
            warnings=reference_warnings,
        )
