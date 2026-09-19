from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.reference.domain.validation import validate_account_code

from ..contracts.product_line_sla import ClassificationPreview
from ..services.classification import ProductLineSlaClassificationService

_CURSOR_FIELDS = {
    "version",
    "query_id",
    "sort_registry_id",
    "last_key_tuple",
    "filter_fingerprint",
    "null_order",
}


@dataclass(frozen=True, slots=True)
class ClassificationPage:
    items: tuple[dict[str, object], ...]
    next_cursor: dict[str, object] | None
    exact_count: int


@dataclass(frozen=True, slots=True)
class BatchClassificationPreview:
    items: tuple[ClassificationPreview, ...]
    exact_count: int
    batch_fingerprint: str


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("classification page size must be an integer from 1 through 500")
    return value


def _cursor(
    *,
    query_id: str,
    sort_id: str,
    last_key: list[object],
    filter_fingerprint: str,
) -> dict[str, object]:
    return {
        "version": 1,
        "query_id": query_id,
        "sort_registry_id": sort_id,
        "last_key_tuple": last_key,
        "filter_fingerprint": filter_fingerprint,
        "null_order": "none",
    }


def _cursor_key(
    value: dict[str, object] | None,
    *,
    query_id: str,
    sort_id: str,
    fingerprint: str,
    size: int,
) -> list[object] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _CURSOR_FIELDS:
        raise ValidationError("classification cursor fields are invalid")
    if (
        value["version"] != 1
        or value["query_id"] != query_id
        or value["sort_registry_id"] != sort_id
        or value["filter_fingerprint"] != fingerprint
        or value["null_order"] != "none"
    ):
        raise ValidationError("classification cursor contract is invalid")
    key = value["last_key_tuple"]
    if not isinstance(key, list) or len(key) != size or any(not isinstance(item, str) for item in key):
        raise ValidationError("classification cursor key is invalid")
    return key


class ProductLineSlaClassificationQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def list_mappings(
        self,
        *,
        customer_org_id: str | None = None,
        customer_account_code: str | None = None,
        contract_product_line_id: str | None = None,
        active: bool | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> ClassificationPage:
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        cpl_id = None if contract_product_line_id is None else require_uuid4(contract_product_line_id)
        normalized_key = None
        if customer_account_code is not None:
            _stored, normalized_key = validate_account_code(customer_account_code)
        if active is not None and type(active) is not bool:
            raise ValidationError("active mapping filter must be bool or null")
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_CLASSIFICATION_MAPPING_LIST_FILTER_V1",
                "customer_org_id": customer_id,
                "normalized_key": normalized_key,
                "contract_product_line_id": cpl_id,
                "active": active,
            }
        )
        key = _cursor_key(
            cursor,
            query_id="ListClassificationMappings",
            sort_id="SLA_CLASSIFICATION_MAPPING_ASC_V1",
            fingerprint=fingerprint,
            size=4,
        )
        clauses: list[str] = []
        params: list[object] = []
        if customer_id is not None:
            clauses.append("customer_org_id=?")
            params.append(customer_id)
        if normalized_key is not None:
            clauses.append("normalized_key=?")
            params.append(normalized_key)
        if cpl_id is not None:
            clauses.append("contract_product_line_id=?")
            params.append(cpl_id)
        if active is not None:
            clauses.append("active=?")
            params.append(1 if active else 0)
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT mapping_id,mapping_key_type,normalized_key,customer_org_id,"
                "contract_product_line_id,active,revision,created_at_utc,opened_command_id,closed_command_id "
                f"FROM sla_classification_mappings{where} "
                "ORDER BY customer_org_id,mapping_key_type,normalized_key,mapping_id",
                tuple(params),
            ).fetchall()
        values = tuple(
            {
                "mapping_id": str(row[0]),
                "mapping_key_type": str(row[1]),
                "normalized_key": str(row[2]),
                "customer_org_id": str(row[3]),
                "contract_product_line_id": str(row[4]),
                "active": bool(int(row[5])),
                "revision": int(row[6]),
                "created_at_utc": int(row[7]),
                "opened_command_id": str(row[8]),
                "closed_command_id": None if row[9] is None else str(row[9]),
            }
            for row in rows
        )
        exact_count = len(values)
        filtered = list(values)
        if key is not None:
            key_tuple = tuple(str(item) for item in key)
            filtered = [
                item
                for item in filtered
                if (
                    str(item["customer_org_id"]),
                    str(item["mapping_key_type"]),
                    str(item["normalized_key"]),
                    str(item["mapping_id"]),
                )
                > key_tuple
            ]
        selected = filtered[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            last = page[-1]
            next_cursor = _cursor(
                query_id="ListClassificationMappings",
                sort_id="SLA_CLASSIFICATION_MAPPING_ASC_V1",
                last_key=[
                    str(last["customer_org_id"]),
                    str(last["mapping_key_type"]),
                    str(last["normalized_key"]),
                    str(last["mapping_id"]),
                ],
                filter_fingerprint=fingerprint,
            )
        return ClassificationPage(tuple(page), next_cursor, exact_count)

    def preview_service_request(
        self,
        *,
        service_request_id: str,
        contract_product_line_id: str | None = None,
    ) -> ClassificationPreview:
        sr_id = require_uuid4(service_request_id)
        cpl_id = None if contract_product_line_id is None else require_uuid4(contract_product_line_id)
        with ReadSnapshot(self._factory) as snapshot:
            if cpl_id is None:
                return ProductLineSlaClassificationService._automatic_preview_from_reader(
                    snapshot.connection,
                    service_request_id=sr_id,
                )
            return ProductLineSlaClassificationService._manual_preview_from_reader(
                snapshot.connection,
                service_request_id=sr_id,
                contract_product_line_id=cpl_id,
            )

    def preview_batch(
        self,
        *,
        service_request_ids: tuple[str, ...],
        contract_product_line_id: str | None = None,
    ) -> BatchClassificationPreview:
        if not isinstance(service_request_ids, tuple) or not 1 <= len(service_request_ids) <= 500:
            raise ValidationError("batch classification requires 1 through 500 Service Request identities")
        canonical: list[str] = []
        seen: set[str] = set()
        for value in service_request_ids:
            identity = require_uuid4(value)
            if identity in seen:
                raise ValidationError("batch classification Service Request identities must be unique")
            seen.add(identity)
            canonical.append(identity)
        cpl_id = None if contract_product_line_id is None else require_uuid4(contract_product_line_id)
        with ReadSnapshot(self._factory) as snapshot:
            items = tuple(
                (
                    ProductLineSlaClassificationService._automatic_preview_from_reader(
                        snapshot.connection,
                        service_request_id=sr_id,
                    )
                    if cpl_id is None
                    else ProductLineSlaClassificationService._manual_preview_from_reader(
                        snapshot.connection,
                        service_request_id=sr_id,
                        contract_product_line_id=cpl_id,
                    )
                )
                for sr_id in canonical
            )
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_BATCH_CLASSIFICATION_PREVIEW_V1",
                "contract_product_line_id": cpl_id,
                "members": [
                    {
                        "input_ordinal": index,
                        "service_request_id": item.service_request_id,
                        "state": item.state,
                        "input_fingerprint": item.input_fingerprint,
                        "target_contract_product_line_id": item.target_contract_product_line_id,
                        "mapping_id": item.mapping_id,
                    }
                    for index, item in enumerate(items, start=1)
                ],
            }
        )
        return BatchClassificationPreview(items=items, exact_count=len(items), batch_fingerprint=fingerprint)

    def get_current(self, *, service_request_id: str) -> dict[str, object]:
        sr_id = require_uuid4(service_request_id)
        with ReadSnapshot(self._factory) as snapshot:
            sr = ProductLineSlaClassificationService._sr_input(snapshot.connection, sr_id)
            if sr.current is None:
                return {
                    "service_request_id": sr_id,
                    "state": "unclassified",
                    "customer_org_id": sr.customer_org_id,
                    "contract_product_line_id": None,
                    "classification_event_id": None,
                    "revision": 0,
                    "current_policy_revision_id": None,
                    "compatible": None,
                }
            target = ProductLineSlaClassificationService._target(
                snapshot.connection,
                sr.current.contract_product_line_id,
            )
            if target is None:
                raise SomaError("SLA_DEPENDENCY_INDETERMINATE", "classified CPL no longer resolves")
            return {
                "service_request_id": sr_id,
                "state": "classified",
                "customer_org_id": sr.customer_org_id,
                "contract_product_line_id": sr.current.contract_product_line_id,
                "classification_event_id": sr.current.classification_event_id,
                "revision": sr.current.revision,
                "current_policy_revision_id": target.current_policy_revision_id,
                "compatible": sr.customer_org_id == target.customer_org_id,
            }

    def history(
        self,
        *,
        service_request_id: str,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> ClassificationPage:
        sr_id = require_uuid4(service_request_id)
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {"schema": "SOMA_CLASSIFICATION_HISTORY_FILTER_V1", "service_request_id": sr_id}
        )
        key = _cursor_key(
            cursor,
            query_id="GetSrClassificationHistory",
            sort_id="SLA_CLASSIFICATION_HISTORY_DESC_V1",
            fingerprint=fingerprint,
            size=2,
        )
        with ReadSnapshot(self._factory) as snapshot:
            if snapshot.connection.execute(
                "SELECT 1 FROM service_requests WHERE service_request_id=?",
                (sr_id,),
            ).fetchone() is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "Service Request does not exist")
            rows = snapshot.connection.execute(
                "SELECT classification_event_id,event_kind,prior_contract_product_line_id,"
                "new_contract_product_line_id,origin,mapping_id,reason_code,recorded_at_utc,command_id "
                "FROM sr_classification_events WHERE service_request_id=? "
                "ORDER BY recorded_at_utc DESC,classification_event_id DESC",
                (sr_id,),
            ).fetchall()
        values = [
            {
                "classification_event_id": str(row[0]),
                "event_kind": str(row[1]),
                "prior_contract_product_line_id": None if row[2] is None else str(row[2]),
                "new_contract_product_line_id": None if row[3] is None else str(row[3]),
                "origin": str(row[4]),
                "mapping_id": None if row[5] is None else str(row[5]),
                "reason_code": None if row[6] is None else str(row[6]),
                "recorded_at_utc": int(row[7]),
                "command_id": str(row[8]),
            }
            for row in rows
        ]
        exact_count = len(values)
        if key is not None:
            if not key[0].isdigit():
                raise ValidationError("classification history cursor time is invalid")
            cursor_tuple = (int(key[0]), str(key[1]))
            values = [
                item
                for item in values
                if (int(item["recorded_at_utc"]), str(item["classification_event_id"])) < cursor_tuple
            ]
        selected = values[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            last = page[-1]
            next_cursor = _cursor(
                query_id="GetSrClassificationHistory",
                sort_id="SLA_CLASSIFICATION_HISTORY_DESC_V1",
                last_key=[str(last["recorded_at_utc"]), str(last["classification_event_id"])],
                filter_fingerprint=fingerprint,
            )
        return ClassificationPage(tuple(page), next_cursor, exact_count)


__all__ = [
    "BatchClassificationPreview",
    "ClassificationPage",
    "ProductLineSlaClassificationQueryService",
]
