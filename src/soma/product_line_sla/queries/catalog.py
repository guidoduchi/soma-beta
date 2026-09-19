from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.reference.domain.matching import normalize_match_key

_CURSOR_FIELDS = {
    "version",
    "query_id",
    "sort_registry_id",
    "last_key_tuple",
    "filter_fingerprint",
    "null_order",
}
_LIFECYCLES = {"active", "archived"}


@dataclass(frozen=True, slots=True)
class CatalogPage:
    items: tuple[dict[str, object], ...]
    next_cursor: dict[str, object] | None
    exact_count: int


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("catalog page size must be an integer from 1 through 500")
    return value


def _lifecycle(value: str | None) -> str | None:
    if value is not None and value not in _LIFECYCLES:
        raise ValidationError("catalog lifecycle filter is invalid")
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
        raise ValidationError("catalog cursor fields are invalid")
    if (
        value["version"] != 1
        or value["query_id"] != query_id
        or value["sort_registry_id"] != sort_id
        or value["filter_fingerprint"] != fingerprint
        or value["null_order"] != "none"
    ):
        raise ValidationError("catalog cursor contract is invalid")
    key = value["last_key_tuple"]
    if not isinstance(key, list) or len(key) != size:
        raise ValidationError("catalog cursor key is invalid")
    return key


def _product_name_key(name: str) -> str:
    return normalize_match_key(
        name,
        raw_max_utf8_bytes=640,
        key_max_utf8_bytes=2048,
    )


class ProductLineSlaCatalogQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def list_product_lines(
        self,
        *,
        lifecycle_state: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> CatalogPage:
        state = _lifecycle(lifecycle_state)
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {"schema": "SOMA_PRODUCT_LINE_LIST_FILTER_V1", "lifecycle_state": state}
        )
        key = _cursor_key(
            cursor,
            query_id="ListProductLines",
            sort_id="PRODUCT_LINE_PRESENTATION_ASC_V1",
            fingerprint=fingerprint,
            size=2,
        )
        with ReadSnapshot(self._factory) as snapshot:
            if state is None:
                rows = snapshot.connection.execute(
                    "SELECT product_line_id,name,lifecycle_state,revision FROM product_lines"
                ).fetchall()
            else:
                rows = snapshot.connection.execute(
                    "SELECT product_line_id,name,lifecycle_state,revision FROM product_lines "
                    "WHERE lifecycle_state=?",
                    (state,),
                ).fetchall()
        values = [
            {
                "product_line_id": str(row[0]),
                "name": str(row[1]),
                "lifecycle_state": str(row[2]),
                "revision": int(row[3]),
            }
            for row in rows
        ]
        values.sort(key=lambda item: (_product_name_key(str(item["name"])), str(item["product_line_id"])))
        exact_count = len(values)
        if key is not None:
            if any(not isinstance(item, str) for item in key):
                raise ValidationError("Product Line cursor key is invalid")
            key_tuple = (str(key[0]), str(key[1]))
            values = [
                item
                for item in values
                if (_product_name_key(str(item["name"])), str(item["product_line_id"])) > key_tuple
            ]
        selected = values[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            last = page[-1]
            next_cursor = _cursor(
                query_id="ListProductLines",
                sort_id="PRODUCT_LINE_PRESENTATION_ASC_V1",
                last_key=[_product_name_key(str(last["name"])), str(last["product_line_id"])],
                filter_fingerprint=fingerprint,
            )
        return CatalogPage(tuple(page), next_cursor, exact_count)

    def list_contracts(
        self,
        *,
        customer_org_id: str | None = None,
        lifecycle_state: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> CatalogPage:
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        state = _lifecycle(lifecycle_state)
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_CONTRACT_LIST_FILTER_V1",
                "customer_org_id": customer_id,
                "lifecycle_state": state,
            }
        )
        key = _cursor_key(
            cursor,
            query_id="ListContracts",
            sort_id="CONTRACT_CANONICAL_ASC_V1",
            fingerprint=fingerprint,
            size=3,
        )
        clauses: list[str] = []
        params: list[object] = []
        if customer_id is not None:
            clauses.append("customer_org_id=?")
            params.append(customer_id)
        if state is not None:
            clauses.append("lifecycle_state=?")
            params.append(state)
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT contract_id,customer_org_id,name,contract_reference,lifecycle_state,revision "
                f"FROM contracts{where} ORDER BY customer_org_id,contract_reference,contract_id",
                tuple(params),
            ).fetchall()
        values = [
            {
                "contract_id": str(row[0]),
                "customer_org_id": str(row[1]),
                "name": str(row[2]),
                "contract_reference": str(row[3]),
                "lifecycle_state": str(row[4]),
                "revision": int(row[5]),
            }
            for row in rows
        ]
        exact_count = len(values)
        if key is not None:
            if any(not isinstance(item, str) for item in key):
                raise ValidationError("Contract cursor key is invalid")
            key_tuple = tuple(str(item) for item in key)
            values = [
                item
                for item in values
                if (
                    str(item["customer_org_id"]),
                    str(item["contract_reference"]),
                    str(item["contract_id"]),
                )
                > key_tuple
            ]
        selected = values[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            last = page[-1]
            next_cursor = _cursor(
                query_id="ListContracts",
                sort_id="CONTRACT_CANONICAL_ASC_V1",
                last_key=[
                    str(last["customer_org_id"]),
                    str(last["contract_reference"]),
                    str(last["contract_id"]),
                ],
                filter_fingerprint=fingerprint,
            )
        return CatalogPage(tuple(page), next_cursor, exact_count)

    def list_contract_product_lines(
        self,
        *,
        customer_org_id: str | None = None,
        contract_id: str | None = None,
        product_line_id: str | None = None,
        lifecycle_state: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> CatalogPage:
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        contract_identity = None if contract_id is None else require_uuid4(contract_id)
        product_identity = None if product_line_id is None else require_uuid4(product_line_id)
        state = _lifecycle(lifecycle_state)
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_CPL_LIST_FILTER_V1",
                "customer_org_id": customer_id,
                "contract_id": contract_identity,
                "product_line_id": product_identity,
                "lifecycle_state": state,
            }
        )
        key = _cursor_key(
            cursor,
            query_id="ListContractProductLines",
            sort_id="CPL_CANONICAL_ASC_V1",
            fingerprint=fingerprint,
            size=3,
        )
        clauses: list[str] = []
        params: list[object] = []
        if customer_id is not None:
            clauses.append("ct.customer_org_id=?")
            params.append(customer_id)
        if contract_identity is not None:
            clauses.append("c.contract_id=?")
            params.append(contract_identity)
        if product_identity is not None:
            clauses.append("c.product_line_id=?")
            params.append(product_identity)
        if state is not None:
            clauses.append("c.lifecycle_state=?")
            params.append(state)
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT c.contract_product_line_id,c.contract_id,c.product_line_id,c.lifecycle_state,"
                "c.current_policy_revision_id,c.revision,ct.customer_org_id,ct.contract_reference,p.name,"
                "pr.revision_ordinal,pr.policy_name,pr.template_source "
                "FROM contract_product_lines c "
                "JOIN contracts ct ON ct.contract_id=c.contract_id "
                "JOIN product_lines p ON p.product_line_id=c.product_line_id "
                "LEFT JOIN sla_policy_revisions pr ON pr.policy_revision_id=c.current_policy_revision_id "
                f"{where} ORDER BY c.contract_id,c.product_line_id,c.contract_product_line_id",
                tuple(params),
            ).fetchall()
        values = [
            {
                "contract_product_line_id": str(row[0]),
                "contract_id": str(row[1]),
                "product_line_id": str(row[2]),
                "lifecycle_state": str(row[3]),
                "current_policy_revision_id": None if row[4] is None else str(row[4]),
                "revision": int(row[5]),
                "customer_org_id": str(row[6]),
                "contract_reference": str(row[7]),
                "product_line_name": str(row[8]),
                "policy_revision_ordinal": None if row[9] is None else int(row[9]),
                "policy_name": None if row[10] is None else str(row[10]),
                "policy_template_source": None if row[11] is None else str(row[11]),
            }
            for row in rows
        ]
        exact_count = len(values)
        if key is not None:
            if any(not isinstance(item, str) for item in key):
                raise ValidationError("CPL cursor key is invalid")
            key_tuple = tuple(str(item) for item in key)
            values = [
                item
                for item in values
                if (
                    str(item["contract_id"]),
                    str(item["product_line_id"]),
                    str(item["contract_product_line_id"]),
                )
                > key_tuple
            ]
        selected = values[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            last = page[-1]
            next_cursor = _cursor(
                query_id="ListContractProductLines",
                sort_id="CPL_CANONICAL_ASC_V1",
                last_key=[
                    str(last["contract_id"]),
                    str(last["product_line_id"]),
                    str(last["contract_product_line_id"]),
                ],
                filter_fingerprint=fingerprint,
            )
        return CatalogPage(tuple(page), next_cursor, exact_count)

    def get_policy_history(
        self,
        *,
        contract_product_line_id: str,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> CatalogPage:
        cpl_id = require_uuid4(contract_product_line_id)
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {"schema": "SOMA_POLICY_HISTORY_FILTER_V1", "contract_product_line_id": cpl_id}
        )
        key = _cursor_key(
            cursor,
            query_id="GetPolicyHistory",
            sort_id="POLICY_REVISION_DESC_V1",
            fingerprint=fingerprint,
            size=2,
        )
        with ReadSnapshot(self._factory) as snapshot:
            if snapshot.connection.execute(
                "SELECT 1 FROM contract_product_lines WHERE contract_product_line_id=?",
                (cpl_id,),
            ).fetchone() is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "Contract Product Line does not exist")
            revisions = snapshot.connection.execute(
                "SELECT policy_revision_id,revision_ordinal,policy_name,template_source,created_at_utc,"
                "created_command_id FROM sla_policy_revisions WHERE contract_product_line_id=? "
                "ORDER BY revision_ordinal DESC,policy_revision_id DESC",
                (cpl_id,),
            ).fetchall()
            values: list[dict[str, object]] = []
            for row in revisions:
                policy_id = str(row[0])
                tiers = snapshot.connection.execute(
                    "SELECT policy_tier_id,severity,tier_ordinal,required_percentage_millionths,"
                    "maximum_duration_numerator_seconds,maximum_duration_denominator,derived_from_tier_id,"
                    "derivation_num,derivation_den FROM sla_policy_tiers WHERE policy_revision_id=? "
                    "ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'major' THEN 2 WHEN 'minor' THEN 3 ELSE 4 END,"
                    "tier_ordinal,policy_tier_id",
                    (policy_id,),
                ).fetchall()
                values.append(
                    {
                        "policy_revision_id": policy_id,
                        "revision_ordinal": int(row[1]),
                        "policy_name": str(row[2]),
                        "template_source": None if row[3] is None else str(row[3]),
                        "created_at_utc": int(row[4]),
                        "created_command_id": str(row[5]),
                        "tiers": tuple(
                            {
                                "policy_tier_id": str(tier[0]),
                                "severity": str(tier[1]),
                                "tier_ordinal": int(tier[2]),
                                "required_percentage_millionths": int(tier[3]),
                                "maximum_duration_numerator_seconds": int(tier[4]),
                                "maximum_duration_denominator": int(tier[5]),
                                "derived_from_tier_id": None if tier[6] is None else str(tier[6]),
                                "derivation_num": None if tier[7] is None else int(tier[7]),
                                "derivation_den": None if tier[8] is None else int(tier[8]),
                            }
                            for tier in tiers
                        ),
                    }
                )
        exact_count = len(values)
        if key is not None:
            if type(key[0]) is not int or not isinstance(key[1], str):
                raise ValidationError("Policy history cursor key is invalid")
            cursor_tuple = (int(key[0]), str(key[1]))
            values = [
                item
                for item in values
                if (int(item["revision_ordinal"]), str(item["policy_revision_id"])) < cursor_tuple
            ]
        selected = values[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            last = page[-1]
            next_cursor = _cursor(
                query_id="GetPolicyHistory",
                sort_id="POLICY_REVISION_DESC_V1",
                last_key=[int(last["revision_ordinal"]), str(last["policy_revision_id"])],
                filter_fingerprint=fingerprint,
            )
        return CatalogPage(tuple(page), next_cursor, exact_count)


__all__ = ["CatalogPage", "ProductLineSlaCatalogQueryService"]
