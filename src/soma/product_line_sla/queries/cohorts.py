from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..algorithms.cohort_state import (
    CanonicalCohortCalculator,
    CohortProjection,
    decode_cohort_key,
)
from ..algorithms.individual_sla import IndividualSlaResult

_COHORT_QUERY_ID = "ListCanonicalCohorts"
_COHORT_SORT_ID = "SLA_COHORT_CANONICAL_ASC_V1"
_MEMBER_QUERY_ID = "GetCohortMembers"
_MEMBER_SORT_ID = "SLA_COHORT_MEMBER_SR_ASC_V1"
_CURSOR_FIELDS = {
    "version",
    "query_id",
    "sort_registry_id",
    "last_key_tuple",
    "filter_fingerprint",
    "null_order",
}
_SEVERITIES = {"critical", "major", "minor", "non_fault_inquiry"}


@dataclass(frozen=True, slots=True)
class CohortPage:
    items: tuple[CohortProjection, ...]
    next_cursor: dict[str, object] | None
    exact_count: int


@dataclass(frozen=True, slots=True)
class CohortDetail:
    cohort: CohortProjection
    members: tuple[IndividualSlaResult, ...]
    next_cursor: dict[str, object] | None
    member_exact_count: int


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("cohort page size must be an integer from 1 through 500")
    return value


def _cohort_key_tuple(cohort: CohortProjection) -> tuple[str, str, str, str, str, str]:
    return (
        cohort.calendar_month,
        cohort.customer_org_id,
        cohort.contract_id,
        cohort.contract_product_line_id,
        cohort.severity,
        cohort.policy_tier_id,
    )


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


def _validate_cursor(
    value: dict[str, object] | None,
    *,
    query_id: str,
    sort_id: str,
    filter_fingerprint: str,
    key_size: int,
) -> list[object] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _CURSOR_FIELDS:
        raise ValidationError("cohort cursor fields are invalid")
    if (
        value["version"] != 1
        or value["query_id"] != query_id
        or value["sort_registry_id"] != sort_id
        or value["filter_fingerprint"] != filter_fingerprint
        or value["null_order"] != "none"
    ):
        raise ValidationError("cohort cursor contract is invalid")
    key = value["last_key_tuple"]
    if (
        not isinstance(key, list)
        or len(key) != key_size
        or any(not isinstance(item, str) for item in key)
    ):
        raise ValidationError("cohort cursor key is invalid")
    return key


class CohortQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def list_canonical(
        self,
        *,
        calendar_month: str,
        as_of_utc: int,
        customer_org_id: str | None = None,
        contract_product_line_id: str | None = None,
        severity: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> CohortPage:
        page_limit = _limit(limit)
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        cpl_id = (
            None
            if contract_product_line_id is None
            else require_uuid4(contract_product_line_id)
        )
        if severity is not None and severity not in _SEVERITIES:
            raise ValidationError("cohort severity filter is invalid")

        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_SLA_COHORT_LIST_FILTER_V1",
                "calendar_month": calendar_month,
                "as_of_utc": as_of_utc,
                "customer_org_id": customer_id,
                "contract_product_line_id": cpl_id,
                "severity": severity,
            }
        )
        cursor_key = _validate_cursor(
            cursor,
            query_id=_COHORT_QUERY_ID,
            sort_id=_COHORT_SORT_ID,
            filter_fingerprint=fingerprint,
            key_size=6,
        )

        with ReadSnapshot(self._factory) as snapshot:
            projection = CanonicalCohortCalculator.calculate_month(
                snapshot.connection,
                calendar_month=calendar_month,
                as_of_utc=as_of_utc,
                customer_scope=customer_id,
            )

        items = [
            cohort
            for cohort in projection.cohorts
            if (cpl_id is None or cohort.contract_product_line_id == cpl_id)
            and (severity is None or cohort.severity == severity)
        ]
        if cursor_key is not None:
            cursor_tuple = tuple(str(item) for item in cursor_key)
            items = [cohort for cohort in items if _cohort_key_tuple(cohort) > cursor_tuple]

        exact_count = sum(
            1
            for cohort in projection.cohorts
            if (cpl_id is None or cohort.contract_product_line_id == cpl_id)
            and (severity is None or cohort.severity == severity)
        )
        selected = items[: page_limit + 1]
        has_more = len(selected) > page_limit
        page_items = tuple(selected[:page_limit])
        next_cursor = None
        if has_more and page_items:
            next_cursor = _cursor(
                query_id=_COHORT_QUERY_ID,
                sort_id=_COHORT_SORT_ID,
                last_key=list(_cohort_key_tuple(page_items[-1])),
                filter_fingerprint=fingerprint,
            )
        return CohortPage(
            items=page_items,
            next_cursor=next_cursor,
            exact_count=exact_count,
        )

    def get_members(
        self,
        *,
        cohort_key: str,
        as_of_utc: int,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> CohortDetail:
        page_limit = _limit(limit)
        key_parts = decode_cohort_key(cohort_key)
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_SLA_COHORT_MEMBER_FILTER_V1",
                "cohort_key": cohort_key,
                "as_of_utc": as_of_utc,
            }
        )
        cursor_key = _validate_cursor(
            cursor,
            query_id=_MEMBER_QUERY_ID,
            sort_id=_MEMBER_SORT_ID,
            filter_fingerprint=fingerprint,
            key_size=1,
        )
        cursor_sr = None
        if cursor_key is not None:
            cursor_sr = require_uuid4(str(cursor_key[0]))

        with ReadSnapshot(self._factory) as snapshot:
            projection = CanonicalCohortCalculator.calculate_month(
                snapshot.connection,
                calendar_month=key_parts.calendar_month,
                as_of_utc=as_of_utc,
                customer_scope=key_parts.customer_org_id,
            )

        cohort_matches = [
            cohort for cohort in projection.cohorts if cohort.cohort_key == cohort_key
        ]
        if len(cohort_matches) != 1:
            raise ValidationError("cohort key does not identify a current canonical cohort")
        cohort = cohort_matches[0]

        members = [
            member.individual_result
            for member in projection.members
            if member.cohort_key.opaque_key == cohort_key
        ]
        members.sort(key=lambda member: member.service_request_id.encode("utf-8"))
        exact_count = len(members)
        if cursor_sr is not None:
            members = [
                member
                for member in members
                if member.service_request_id.encode("utf-8") > cursor_sr.encode("utf-8")
            ]

        selected = members[: page_limit + 1]
        has_more = len(selected) > page_limit
        page_members = tuple(selected[:page_limit])
        next_cursor = None
        if has_more and page_members:
            next_cursor = _cursor(
                query_id=_MEMBER_QUERY_ID,
                sort_id=_MEMBER_SORT_ID,
                last_key=[page_members[-1].service_request_id],
                filter_fingerprint=fingerprint,
            )
        return CohortDetail(
            cohort=cohort,
            members=page_members,
            next_cursor=next_cursor,
            member_exact_count=exact_count,
        )


__all__ = ["CohortDetail", "CohortPage", "CohortQueryService"]
