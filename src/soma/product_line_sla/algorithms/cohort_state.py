from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes, loads_strict_bytes, sha256_canonical_json
from soma.tickets.service_request_sla_input import ServiceRequestSlaInputReader

from .individual_sla import (
    IndividualSlaCalculator,
    IndividualSlaReadCache,
    IndividualSlaResult,
    IndividualTierResult,
)

_SLA_TIMEZONE = "America/Guayaquil"
_MONTH_RE = re.compile(r"^(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])$")
_PERCENT_SCALE = 100_000_000


@dataclass(frozen=True, slots=True)
class CohortKeyParts:
    calendar_month: str
    customer_org_id: str
    contract_id: str
    contract_product_line_id: str
    severity: str
    policy_tier_id: str

    @property
    def opaque_key(self) -> str:
        return encode_cohort_key(self)


@dataclass(frozen=True, slots=True)
class CanonicalCohortMember:
    cohort_key: CohortKeyParts
    service_request_id: str
    policy_revision_id: str
    tier_result: IndividualTierResult
    individual_result: IndividualSlaResult


@dataclass(frozen=True, slots=True)
class CohortProjection:
    cohort_key: str
    calendar_month: str
    timezone: str
    customer_org_id: str
    contract_id: str
    contract_product_line_id: str
    policy_revision_id: str
    policy_tier_id: str
    severity: str
    required_percentage_millionths: int
    maximum_duration_numerator_seconds: int
    maximum_duration_denominator: int
    denominator: int
    terminal_met_count: int
    terminal_exceeded_count: int
    active_within_count: int
    active_exceeded_count: int
    lower_bound_met_count: int
    best_possible_met_count: int
    lower_bound_percentage_numerator: int
    lower_bound_percentage_denominator: int
    best_possible_percentage_numerator: int
    best_possible_percentage_denominator: int
    state: str
    is_final: bool
    member_exact_count: int
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class CohortMonthProjection:
    calendar_month: str
    timezone: str
    month_start_utc: int
    month_end_utc: int
    as_of_utc: int
    cohorts: tuple[CohortProjection, ...]
    members: tuple[CanonicalCohortMember, ...]


def _guayaquil_timezone(local: datetime):
    try:
        return ZoneInfo(_SLA_TIMEZONE)
    except ZoneInfoNotFoundError:
        # Supported Windows Python installations do not necessarily ship IANA tzdata.
        # Mainland Ecuador is UTC-05 in the supported modern operational period.
        if local.year < 1993:
            raise ValidationError(
                "America/Guayaquil historical timezone data is unavailable"
            )
        return timezone(timedelta(hours=-5), name=_SLA_TIMEZONE)


def encode_cohort_key(parts: CohortKeyParts) -> str:
    payload = {
        "schema": "SOMA_SLA_COHORT_KEY_V1",
        "calendar_month": parts.calendar_month,
        "customer_org_id": require_uuid4(parts.customer_org_id),
        "contract_id": require_uuid4(parts.contract_id),
        "contract_product_line_id": require_uuid4(parts.contract_product_line_id),
        "severity": parts.severity,
        "policy_tier_id": require_uuid4(parts.policy_tier_id),
    }
    if parts.severity not in {"critical", "major", "minor", "non_fault_inquiry"}:
        raise ValidationError("cohort key severity is invalid")
    canonical_month_bounds(parts.calendar_month)
    token = base64.urlsafe_b64encode(canonical_json_bytes(payload)).decode("ascii").rstrip("=")
    return "v1." + token


def decode_cohort_key(value: str) -> CohortKeyParts:
    if not isinstance(value, str) or not value.startswith("v1.") or len(value) > 2048:
        raise ValidationError("cohort key is invalid")
    encoded = value[3:]
    if not encoded:
        raise ValidationError("cohort key is invalid")
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        raw = base64.b64decode(
            (encoded + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ValidationError("cohort key is invalid") from exc
    payload = loads_strict_bytes(raw, max_bytes=1536)
    expected = {
        "schema",
        "calendar_month",
        "customer_org_id",
        "contract_id",
        "contract_product_line_id",
        "severity",
        "policy_tier_id",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValidationError("cohort key shape is invalid")
    if payload["schema"] != "SOMA_SLA_COHORT_KEY_V1":
        raise ValidationError("cohort key schema is invalid")
    for key in (
        "calendar_month",
        "customer_org_id",
        "contract_id",
        "contract_product_line_id",
        "severity",
        "policy_tier_id",
    ):
        if not isinstance(payload[key], str):
            raise ValidationError("cohort key field type is invalid")
    parts = CohortKeyParts(
        calendar_month=payload["calendar_month"],
        customer_org_id=require_uuid4(payload["customer_org_id"]),
        contract_id=require_uuid4(payload["contract_id"]),
        contract_product_line_id=require_uuid4(payload["contract_product_line_id"]),
        severity=payload["severity"],
        policy_tier_id=require_uuid4(payload["policy_tier_id"]),
    )
    if parts.severity not in {"critical", "major", "minor", "non_fault_inquiry"}:
        raise ValidationError("cohort key severity is invalid")
    canonical_month_bounds(parts.calendar_month)
    if encode_cohort_key(parts) != value:
        raise ValidationError("cohort key is not canonical")
    return parts


def canonical_month_bounds(calendar_month: str) -> tuple[int, int]:
    if not isinstance(calendar_month, str):
        raise ValidationError("calendar month must use YYYY-MM")
    match = _MONTH_RE.fullmatch(calendar_month)
    if match is None:
        raise ValidationError("calendar month must use YYYY-MM")
    year = int(match.group("year"))
    month = int(match.group("month"))
    if year < 1970 or year >= 9999:
        raise ValidationError("calendar month is outside the supported UTC epoch range")

    start_local = datetime(year, month, 1)
    if month == 12:
        end_local = datetime(year + 1, 1, 1)
    else:
        end_local = datetime(year, month + 1, 1)

    start_zone = _guayaquil_timezone(start_local)
    end_zone = _guayaquil_timezone(end_local)
    start_utc = int(start_local.replace(tzinfo=start_zone, fold=0).astimezone(UTC).timestamp())
    end_utc = int(end_local.replace(tzinfo=end_zone, fold=0).astimezone(UTC).timestamp())
    if start_utc < 0 or end_utc <= start_utc:
        raise ValidationError("calendar month produced invalid UTC bounds")
    return start_utc, end_utc


def _passes_percentage(met_count: int, denominator: int, required: int) -> bool:
    return met_count * _PERCENT_SCALE >= required * denominator


def _percentage_fraction(met_count: int, denominator: int) -> Fraction:
    return Fraction(met_count * 100, denominator)


def _cohort_sort_key(key: CohortKeyParts) -> tuple[str, str, str, str, str, str]:
    return (
        key.calendar_month,
        key.customer_org_id,
        key.contract_id,
        key.contract_product_line_id,
        key.severity,
        key.policy_tier_id,
    )


class CanonicalCohortCalculator:
    """Pure COHORT_STATE_V1 projection over one accepted-state reader."""

    @classmethod
    def calculate_month(
        cls,
        reader: Any,
        *,
        calendar_month: str,
        as_of_utc: int,
        customer_scope: str | None = None,
        read_cache: IndividualSlaReadCache | None = None,
    ) -> CohortMonthProjection:
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("as_of_utc must be a nonnegative whole-second UTC instant")
        month_start_utc, month_end_utc = canonical_month_bounds(calendar_month)
        if read_cache is None:
            read_cache = IndividualSlaReadCache()

        groups: dict[CohortKeyParts, list[CanonicalCohortMember]] = {}
        cursor: str | None = None
        while True:
            page = ServiceRequestSlaInputReader.list_report_date_month(
                reader,
                month_start_utc,
                month_end_utc,
                customer_scope,
                cursor,
                500,
            )
            for sla_input in page.items:
                individual = IndividualSlaCalculator.calculate(
                    reader,
                    sla_input.service_request_id,
                    as_of_utc,
                    sla_input=sla_input,
                    read_cache=read_cache,
                )
                if individual.calculation_state != "calculable":
                    continue
                if individual.status_class == "cancelled":
                    continue
                if (
                    individual.customer_org_id is None
                    or individual.contract_id is None
                    or individual.contract_product_line_id is None
                    or individual.policy_revision_id is None
                    or individual.severity is None
                    or individual.report_date_utc is None
                ):
                    raise IntegrityFailure(
                        "calculable individual SLA lacks canonical cohort authority"
                    )
                if not (
                    month_start_utc <= individual.report_date_utc < month_end_utc
                ):
                    raise IntegrityFailure(
                        "SLA month candidate changed Report Date inside one stable read"
                    )

                for tier in individual.tier_results:
                    key = CohortKeyParts(
                        calendar_month=calendar_month,
                        customer_org_id=individual.customer_org_id,
                        contract_id=individual.contract_id,
                        contract_product_line_id=individual.contract_product_line_id,
                        severity=individual.severity,
                        policy_tier_id=tier.policy_tier_id,
                    )
                    groups.setdefault(key, []).append(
                        CanonicalCohortMember(
                            cohort_key=key,
                            service_request_id=individual.service_request_id,
                            policy_revision_id=individual.policy_revision_id,
                            tier_result=tier,
                            individual_result=individual,
                        )
                    )
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        cohorts: list[CohortProjection] = []
        all_members: list[CanonicalCohortMember] = []
        month_closed = as_of_utc >= month_end_utc

        for key in sorted(groups, key=_cohort_sort_key):
            members = sorted(
                groups[key],
                key=lambda member: member.service_request_id.encode("utf-8"),
            )
            if not members:
                continue

            policy_revision_id = members[0].policy_revision_id
            required = members[0].tier_result.required_percentage_millionths
            duration_num = members[0].tier_result.maximum_duration_numerator_seconds
            duration_den = members[0].tier_result.maximum_duration_denominator
            for member in members[1:]:
                tier = member.tier_result
                if (
                    member.policy_revision_id != policy_revision_id
                    or tier.required_percentage_millionths != required
                    or tier.maximum_duration_numerator_seconds != duration_num
                    or tier.maximum_duration_denominator != duration_den
                ):
                    raise IntegrityFailure(
                        "one canonical cohort key resolved conflicting policy-tier authority"
                    )

            counts = {
                "terminal_met": 0,
                "terminal_exceeded": 0,
                "active_within": 0,
                "active_exceeded": 0,
            }
            for member in members:
                state = member.tier_result.individual_state
                if state not in counts:
                    raise IntegrityFailure("individual SLA returned unknown cohort state")
                counts[state] += 1

            denominator = len(members)
            terminal_met = counts["terminal_met"]
            terminal_exceeded = counts["terminal_exceeded"]
            active_within = counts["active_within"]
            active_exceeded = counts["active_exceeded"]
            lower = terminal_met
            best = terminal_met + active_within
            lower_passes = _passes_percentage(lower, denominator, required)
            best_passes = _passes_percentage(best, denominator, required)
            is_final = month_closed and active_within == 0 and active_exceeded == 0

            if is_final and lower_passes:
                state = "final_met"
            elif not best_passes:
                state = "breached"
            elif lower_passes:
                state = "currently_met"
            elif terminal_exceeded + active_exceeded > 0:
                state = "at_risk"
            else:
                state = "pending"

            lower_fraction = _percentage_fraction(lower, denominator)
            best_fraction = _percentage_fraction(best, denominator)
            input_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_COHORT_INPUT_V1",
                    "cohort_key": key.opaque_key,
                    "as_of_utc": as_of_utc,
                    "policy_revision_id": policy_revision_id,
                    "required_percentage_millionths": required,
                    "maximum_duration": {
                        "numerator_seconds": duration_num,
                        "denominator": duration_den,
                    },
                    "members": [
                        {
                            "service_request_id": member.service_request_id,
                            "individual_input_fingerprint": member.individual_result.input_fingerprint,
                            "individual_state": member.tier_result.individual_state,
                        }
                        for member in members
                    ],
                }
            )
            cohorts.append(
                CohortProjection(
                    cohort_key=key.opaque_key,
                    calendar_month=calendar_month,
                    timezone=_SLA_TIMEZONE,
                    customer_org_id=key.customer_org_id,
                    contract_id=key.contract_id,
                    contract_product_line_id=key.contract_product_line_id,
                    policy_revision_id=policy_revision_id,
                    policy_tier_id=key.policy_tier_id,
                    severity=key.severity,
                    required_percentage_millionths=required,
                    maximum_duration_numerator_seconds=duration_num,
                    maximum_duration_denominator=duration_den,
                    denominator=denominator,
                    terminal_met_count=terminal_met,
                    terminal_exceeded_count=terminal_exceeded,
                    active_within_count=active_within,
                    active_exceeded_count=active_exceeded,
                    lower_bound_met_count=lower,
                    best_possible_met_count=best,
                    lower_bound_percentage_numerator=lower_fraction.numerator,
                    lower_bound_percentage_denominator=lower_fraction.denominator,
                    best_possible_percentage_numerator=best_fraction.numerator,
                    best_possible_percentage_denominator=best_fraction.denominator,
                    state=state,
                    is_final=is_final,
                    member_exact_count=denominator,
                    input_fingerprint=input_fingerprint,
                )
            )
            all_members.extend(members)

        return CohortMonthProjection(
            calendar_month=calendar_month,
            timezone=_SLA_TIMEZONE,
            month_start_utc=month_start_utc,
            month_end_utc=month_end_utc,
            as_of_utc=as_of_utc,
            cohorts=tuple(cohorts),
            members=tuple(
                sorted(
                    all_members,
                    key=lambda member: (
                        *_cohort_sort_key(member.cohort_key),
                        member.service_request_id,
                    ),
                )
            ),
        )


__all__ = [
    "CanonicalCohortCalculator",
    "CanonicalCohortMember",
    "CohortKeyParts",
    "CohortMonthProjection",
    "CohortProjection",
    "canonical_month_bounds",
    "decode_cohort_key",
    "encode_cohort_key",
]
