from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..algorithms.cohort_state import CanonicalCohortCalculator
from ..algorithms.individual_sla import (
    IndividualSlaCalculator,
    IndividualSlaReadCache,
    IndividualSlaResult,
)
from ..algorithms.warnings import SlaWarning, SlaWarningCalculator

_WARNING_KINDS = frozenset(
    {
        "sla_unclassified",
        "sla_uncalculable_missing_report_date",
        "individual_tier_exceeded",
        "suspension_end_missing_or_expired",
        "suspension_ending_soon",
        "cohort_at_risk",
        "cohort_breached",
    }
)
_INDIVIDUAL_WARNING_KINDS = frozenset(
    {
        "sla_unclassified",
        "sla_uncalculable_missing_report_date",
        "individual_tier_exceeded",
        "suspension_end_missing_or_expired",
        "suspension_ending_soon",
    }
)
_COHORT_WARNING_KINDS = frozenset({"cohort_at_risk", "cohort_breached"})
_CURSOR_FIELDS = {
    "version",
    "query_id",
    "sort_registry_id",
    "last_key_tuple",
    "filter_fingerprint",
    "null_order",
}
_WARNING_QUERY_ID = "ListSlaWarnings"
_WARNING_SORT_ID = "SLA_WARNING_CANONICAL_ASC_V2"
_WARNING_NULL_ORDER = "policy_tier_id_null_first"
_SLA_TIMEZONE = "America/Guayaquil"


@dataclass(frozen=True, slots=True)
class SlaWarningPage:
    items: tuple[SlaWarning, ...]
    next_cursor: dict[str, object] | None


def _page_limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("SLA warning page size must be an integer from 1 through 500")
    return value


def _as_of(value: int | None) -> int:
    if value is None:
        return utc_epoch_seconds()
    if type(value) is not int or value < 0:
        raise ValidationError("as_of_utc must be a nonnegative whole-second UTC instant")
    return value


def _warning_kind(value: str | None) -> str | None:
    if value is not None and value not in _WARNING_KINDS:
        raise ValidationError("SLA warning kind is invalid")
    return value


def _warning_sort_key(warning: SlaWarning) -> tuple[str, str, str, str]:
    return (
        warning.warning_kind,
        warning.target_type,
        warning.target_id,
        "" if warning.policy_tier_id is None else warning.policy_tier_id,
    )


def _cursor_sort_key(value: list[object]) -> tuple[str, str, str, str]:
    if (
        len(value) != 4
        or any(not isinstance(item, str) for item in value[:3])
        or (value[3] is not None and not isinstance(value[3], str))
    ):
        raise ValidationError("SLA warning cursor key is invalid")
    policy_tier_id = value[3]
    if policy_tier_id is not None:
        policy_tier_id = require_uuid4(policy_tier_id)
    return (
        str(value[0]),
        str(value[1]),
        str(value[2]),
        "" if policy_tier_id is None else policy_tier_id,
    )


def _cursor(
    *,
    warning: SlaWarning,
    filter_fingerprint: str,
) -> dict[str, object]:
    return {
        "version": 1,
        "query_id": _WARNING_QUERY_ID,
        "sort_registry_id": _WARNING_SORT_ID,
        "last_key_tuple": [
            warning.warning_kind,
            warning.target_type,
            warning.target_id,
            warning.policy_tier_id,
        ],
        "filter_fingerprint": filter_fingerprint,
        "null_order": _WARNING_NULL_ORDER,
    }


def _cursor_key(
    value: dict[str, object] | None,
    *,
    filter_fingerprint: str,
) -> tuple[str, str, str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _CURSOR_FIELDS:
        raise ValidationError("SLA warning cursor fields are invalid")
    if (
        value["version"] != 1
        or value["query_id"] != _WARNING_QUERY_ID
        or value["sort_registry_id"] != _WARNING_SORT_ID
        or value["filter_fingerprint"] != filter_fingerprint
        or value["null_order"] != _WARNING_NULL_ORDER
    ):
        raise ValidationError("SLA warning cursor contract is invalid")
    raw_key = value["last_key_tuple"]
    if not isinstance(raw_key, list):
        raise ValidationError("SLA warning cursor key is invalid")
    return _cursor_sort_key(raw_key)


def _calendar_month_for_utc(as_of_utc: int) -> str:
    instant = datetime.fromtimestamp(as_of_utc, UTC)
    try:
        local = instant.astimezone(ZoneInfo(_SLA_TIMEZONE))
    except ZoneInfoNotFoundError:
        if instant.year < 1993:
            raise ValidationError(
                "America/Guayaquil historical timezone data is unavailable"
            )
        local = instant.astimezone(timezone(timedelta(hours=-5), name=_SLA_TIMEZONE))
    return f"{local.year:04d}-{local.month:02d}"


def _candidate_service_request_ids(connection, customer_org_id: str | None):
    if customer_org_id is None:
        cursor = connection.execute(
            "SELECT service_request_id FROM ("
            "SELECT service_request_id FROM sr_current_source_projection "
            "UNION SELECT service_request_id FROM sr_classification_current "
            "UNION SELECT service_request_id FROM sr_customer_relationships "
            "WHERE relationship_state='active'"
            ") ORDER BY service_request_id"
        )
    else:
        cursor = connection.execute(
            "SELECT candidate.service_request_id FROM ("
            "SELECT service_request_id FROM sr_current_source_projection "
            "UNION SELECT service_request_id FROM sr_classification_current "
            "UNION SELECT service_request_id FROM sr_customer_relationships "
            "WHERE relationship_state='active'"
            ") AS candidate "
            "WHERE EXISTS (SELECT 1 FROM sr_customer_relationships cr "
            "WHERE cr.service_request_id=candidate.service_request_id "
            "AND cr.relationship_state='active' AND cr.customer_org_id=?) "
            "ORDER BY candidate.service_request_id",
            (customer_org_id,),
        )
    while True:
        rows = cursor.fetchmany(500)
        if not rows:
            return
        for row in rows:
            yield require_uuid4(str(row[0]))


class IndividualSlaQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def get_individual(self, *, service_request_id: str, as_of_utc: int) -> IndividualSlaResult:
        with ReadSnapshot(self._factory) as snapshot:
            return IndividualSlaCalculator.calculate(
                snapshot.connection,
                service_request_id,
                as_of_utc,
            )


class SlaWarningQueryService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        suspension_ending_soon_threshold_seconds: int | None = None,
    ) -> None:
        if (
            suspension_ending_soon_threshold_seconds is not None
            and (
                type(suspension_ending_soon_threshold_seconds) is not int
                or suspension_ending_soon_threshold_seconds < 0
            )
        ):
            raise ValidationError(
                "suspension ending-soon threshold must be a nonnegative whole-second duration"
            )
        self._factory = connection_factory
        self._suspension_ending_soon_threshold_seconds = (
            suspension_ending_soon_threshold_seconds
        )

    def list_warnings(
        self,
        *,
        customer_org_id: str | None = None,
        warning_kind: str | None = None,
        as_of_utc: int | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> SlaWarningPage:
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        kind = _warning_kind(warning_kind)
        effective_as_of = _as_of(as_of_utc)
        page_limit = _page_limit(limit)
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_SLA_WARNING_LIST_FILTER_V1",
                "customer_org_id": customer_id,
                "warning_kind": kind,
                "as_of_utc": effective_as_of,
                "suspension_ending_soon_threshold_seconds": (
                    self._suspension_ending_soon_threshold_seconds
                ),
            }
        )
        after = _cursor_key(cursor, filter_fingerprint=filter_fingerprint)
        selected_kinds = (
            tuple(sorted(_WARNING_KINDS))
            if kind is None
            else (kind,)
        )
        buckets: dict[str, list[SlaWarning]] = {value: [] for value in selected_kinds}

        with ReadSnapshot(self._factory) as snapshot:
            reader = snapshot.connection
            read_cache = IndividualSlaReadCache()
            if any(value in _INDIVIDUAL_WARNING_KINDS for value in selected_kinds):
                for service_request_id in _candidate_service_request_ids(reader, customer_id):
                    warnings = SlaWarningCalculator.individual(
                        reader,
                        service_request_id=service_request_id,
                        as_of_utc=effective_as_of,
                        suspension_ending_soon_threshold_seconds=(
                            self._suspension_ending_soon_threshold_seconds
                        ),
                        read_cache=read_cache,
                    )
                    for warning in warnings:
                        bucket = buckets.get(warning.warning_kind)
                        if bucket is None:
                            continue
                        key = _warning_sort_key(warning)
                        if after is not None and key <= after:
                            continue
                        if len(bucket) <= page_limit:
                            bucket.append(warning)

            if any(value in _COHORT_WARNING_KINDS for value in selected_kinds):
                projection = CanonicalCohortCalculator.calculate_month(
                    reader,
                    calendar_month=_calendar_month_for_utc(effective_as_of),
                    as_of_utc=effective_as_of,
                    customer_scope=customer_id,
                    read_cache=read_cache,
                )
                for cohort in projection.cohorts:
                    for warning in SlaWarningCalculator.cohort(cohort):
                        bucket = buckets.get(warning.warning_kind)
                        if bucket is None:
                            continue
                        key = _warning_sort_key(warning)
                        if after is None or key > after:
                            bucket.append(warning)

        ordered: list[SlaWarning] = []
        for selected_kind in selected_kinds:
            bucket = buckets[selected_kind]
            bucket.sort(key=_warning_sort_key)
            ordered.extend(bucket)
            if len(ordered) > page_limit:
                break

        page = tuple(ordered[:page_limit])
        next_cursor = None
        if len(ordered) > page_limit and page:
            next_cursor = _cursor(
                warning=page[-1],
                filter_fingerprint=filter_fingerprint,
            )
        if len({warning.warning_key for warning in page}) != len(page):
            raise IntegrityFailure("SLA warning query produced duplicate warning identity")
        return SlaWarningPage(items=page, next_cursor=next_cursor)


__all__ = [
    "IndividualSlaQueryService",
    "SlaWarningPage",
    "SlaWarningQueryService",
]
