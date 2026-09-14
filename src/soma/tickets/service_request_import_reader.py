from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4

from .import_mutations import (
    ServiceRequestImportMutationService,
    ServiceRequestImportReader as _ServiceRequestImportReader,
)


class ServiceRequestImportReader(_ServiceRequestImportReader):
    """Canonical LLD-03 import reader for governed reconciliation freshness."""

    @staticmethod
    def source_identity_base_token(reader: Any, official_sr_no: str) -> str:
        return ServiceRequestImportMutationService.source_identity_base_token(reader, official_sr_no)

    @staticmethod
    def current_source_presence(reader: Any, service_request_id: str, source_family: str = "advanced_search_sr"):
        return _ServiceRequestImportReader.current_source_presence(reader, service_request_id, source_family)

    @staticmethod
    def source_presence_base_token(reader: Any, service_request_id: str, source_family: str = "advanced_search_sr") -> str:
        return _ServiceRequestImportReader.source_presence_base_token(reader, service_request_id, source_family)

    @staticmethod
    def customer_reconciliation_base_token(
        reader: Any,
        service_request_id: str,
        target_customer_org_id: str,
    ) -> str:
        return ServiceRequestImportMutationService.customer_reconciliation_base_token(
            reader,
            service_request_id,
            target_customer_org_id,
        )

    @staticmethod
    def contact_reconciliation_base_token(
        reader: Any,
        service_request_id: str,
        reference_role: str,
        target_contact_id: str,
        source_observation_field_id: str,
    ) -> str:
        return ServiceRequestImportMutationService.contact_reconciliation_base_token(
            reader,
            service_request_id,
            reference_role,
            target_contact_id,
            source_observation_field_id,
        )

    @staticmethod
    def current_source_projection(reader: Any, service_request_id: str) -> dict[str, object] | None:
        projection = _ServiceRequestImportReader.current_source_projection(reader, service_request_id)
        if projection is None:
            return None
        result = dict(projection)
        canonical_sr_id = require_uuid4(service_request_id)
        pointer_row = reader.execute(
            "SELECT current_handler_observation_id FROM sr_current_source_projection WHERE service_request_id=?",
            (canonical_sr_id,),
        ).fetchone()
        if pointer_row is None:
            raise IntegrityFailure("Service Request source projection disappeared while resolving Current Handler authority")
        pointer = pointer_row[0]
        if pointer is None:
            result["current_handler_authority"] = None
            return result
        if not isinstance(pointer, str):
            raise IntegrityFailure("Service Request Current Handler projection pointer is not a canonical identity")
        canonical_pointer = require_uuid4(pointer)
        row = reader.execute(
            "SELECT sr_source_field_observation_id,source_observation_field_id,field_key,value_state,value_kind,"
            "text_value,integer_value,source_chronology_utc,precedence_basis "
            "FROM sr_source_field_observations WHERE sr_source_field_observation_id=? AND service_request_id=?",
            (canonical_pointer, canonical_sr_id),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Service Request Current Handler projection points to missing owner evidence")
        observation_id = require_uuid4(str(row[0]))
        source_field_id = require_uuid4(str(row[1]))
        field_key = str(row[2])
        value_state = str(row[3])
        value_kind = str(row[4])
        text_value = None if row[5] is None else str(row[5])
        integer_value = row[6]
        chronology = None if row[7] is None else int(row[7])
        precedence_basis = str(row[8])
        if observation_id != canonical_pointer or field_key != "current_handler_label" or value_kind != "text":
            raise IntegrityFailure("Service Request Current Handler projection points to mismatched owner evidence")
        if value_state not in {"usable", "explicit_clear"}:
            raise IntegrityFailure("Service Request Current Handler owner evidence has invalid value state")
        if value_state == "usable" and text_value is None:
            raise IntegrityFailure("usable Current Handler owner evidence has no text authority")
        if value_state == "explicit_clear" and text_value is not None:
            raise IntegrityFailure("explicit Current Handler clear unexpectedly carries text authority")
        if integer_value is not None:
            raise IntegrityFailure("Current Handler owner evidence unexpectedly carries integer authority")
        if chronology is not None and chronology < 0:
            raise IntegrityFailure("Current Handler owner evidence has invalid chronology")
        if precedence_basis not in {"source_chronology", "reviewed_correction"}:
            raise IntegrityFailure("Current Handler owner evidence has invalid precedence basis")
        result["current_handler_authority"] = {
            "sr_source_field_observation_id": observation_id,
            "source_observation_field_id": source_field_id,
            "field_key": field_key,
            "value_state": value_state,
            "value_kind": value_kind,
            "text_value": text_value,
            "integer_value": None,
            "source_chronology_utc": chronology,
            "precedence_basis": precedence_basis,
        }
        return result
