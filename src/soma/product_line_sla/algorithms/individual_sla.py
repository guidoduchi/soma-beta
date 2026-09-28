from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.service_request_sla_input import (
    ServiceRequestSlaInput,
    ServiceRequestSlaInputReader,
)


@dataclass(frozen=True, slots=True)
class IndividualTierResult:
    policy_tier_id: str
    tier_ordinal: int
    required_percentage_millionths: int
    maximum_duration_numerator_seconds: int
    maximum_duration_denominator: int
    individual_state: str
    inclusive_boundary_met: bool


@dataclass(frozen=True, slots=True)
class IndividualSlaResult:
    service_request_id: str
    as_of_utc: int
    classification_state: str
    customer_org_id: str | None
    contract_id: str | None
    contract_product_line_id: str | None
    classification_event_id: str | None
    policy_revision_id: str | None
    severity: str | None
    report_date_utc: int | None
    endpoint_kind: str
    endpoint_utc: int | None
    suspension_numerator_seconds: int
    suspension_denominator: int
    effective_elapsed_numerator_seconds: int | None
    effective_elapsed_denominator: int | None
    calculation_state: str
    status_class: str
    tier_results: tuple[IndividualTierResult, ...]
    sla_input_token: str
    input_fingerprint: str
    source_report_date_evidence_id: str | None
    source_status_evidence_id: str | None
    source_suspension_evidence_id: str | None


@dataclass(frozen=True, slots=True)
class _ClassificationAuthority:
    contract_product_line_id: str
    classification_event_id: str
    classification_revision: int
    contract_id: str
    contract_customer_org_id: str
    current_policy_revision_id: str | None


def _classification(reader: Any, service_request_id: str) -> _ClassificationAuthority | None:
    row = reader.execute(
        "SELECT cur.contract_product_line_id,cur.classification_event_id,cur.revision,"
        "cpl.contract_id,ct.customer_org_id,cpl.current_policy_revision_id "
        "FROM sr_classification_current cur "
        "JOIN contract_product_lines cpl "
        "ON cpl.contract_product_line_id=cur.contract_product_line_id "
        "JOIN contracts ct ON ct.contract_id=cpl.contract_id "
        "WHERE cur.service_request_id=?",
        (service_request_id,),
    ).fetchone()
    if row is None:
        return None
    return _ClassificationAuthority(
        contract_product_line_id=require_uuid4(str(row[0])),
        classification_event_id=require_uuid4(str(row[1])),
        classification_revision=int(row[2]),
        contract_id=require_uuid4(str(row[3])),
        contract_customer_org_id=require_uuid4(str(row[4])),
        current_policy_revision_id=None if row[5] is None else require_uuid4(str(row[5])),
    )


def _empty_result(
    *,
    sla_input: ServiceRequestSlaInput,
    as_of_utc: int,
    classification_state: str,
    calculation_state: str,
    classification: _ClassificationAuthority | None,
    endpoint_kind: str = "missing",
) -> IndividualSlaResult:
    fingerprint = sha256_canonical_json(
        {
            "schema": "SOMA_INDIVIDUAL_SLA_INPUT_V1",
            "service_request_id": sla_input.service_request_id,
            "sla_input_token": sla_input.input_token,
            "classification_state": classification_state,
            "classification_event_id": None if classification is None else classification.classification_event_id,
            "contract_product_line_id": None
            if classification is None
            else classification.contract_product_line_id,
            "policy_revision_id": None
            if classification is None
            else classification.current_policy_revision_id,
            "as_of_utc": as_of_utc,
            "calculation_state": calculation_state,
        }
    )
    return IndividualSlaResult(
        service_request_id=sla_input.service_request_id,
        as_of_utc=as_of_utc,
        classification_state=classification_state,
        customer_org_id=sla_input.customer_org_id,
        contract_id=None if classification is None else classification.contract_id,
        contract_product_line_id=None
        if classification is None
        else classification.contract_product_line_id,
        classification_event_id=None if classification is None else classification.classification_event_id,
        policy_revision_id=None
        if classification is None
        else classification.current_policy_revision_id,
        severity=sla_input.severity,
        report_date_utc=sla_input.report_date_utc,
        endpoint_kind=endpoint_kind,
        endpoint_utc=None,
        suspension_numerator_seconds=sla_input.suspension_numerator_seconds,
        suspension_denominator=sla_input.suspension_denominator,
        effective_elapsed_numerator_seconds=None,
        effective_elapsed_denominator=None,
        calculation_state=calculation_state,
        status_class=sla_input.status_class,
        tier_results=(),
        sla_input_token=sla_input.input_token,
        input_fingerprint=fingerprint,
        source_report_date_evidence_id=sla_input.report_date_evidence_id,
        source_status_evidence_id=sla_input.status_evidence_id,
        source_suspension_evidence_id=sla_input.suspension_evidence_id,
    )


@dataclass(slots=True)
class IndividualSlaReadCache:
    """Immutable-policy read reuse scoped to one calculation/read snapshot."""

    policy_owner_by_revision: dict[str, str | None] = field(default_factory=dict)
    policy_tiers_by_revision_severity: dict[
        tuple[str, str],
        tuple[tuple[object, ...], ...],
    ] = field(default_factory=dict)


class IndividualSlaCalculator:
    """Pure INDIVIDUAL_SLA_V1 projection over accepted ticket and LLD-06 authority."""

    @classmethod
    def calculate(
        cls,
        reader: Any,
        sr_id: str,
        as_of_utc: int,
        *,
        sla_input: ServiceRequestSlaInput | None = None,
        read_cache: IndividualSlaReadCache | None = None,
    ) -> IndividualSlaResult:
        service_request_id = require_uuid4(sr_id)
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("as_of_utc must be a nonnegative whole-second UTC instant")
        if sla_input is None:
            sla_input = ServiceRequestSlaInputReader.get(reader, service_request_id)
        elif sla_input.service_request_id != service_request_id:
            raise ValidationError("supplied SLA input belongs to a different Service Request")
        classification = _classification(reader, service_request_id)

        if classification is None:
            return _empty_result(
                sla_input=sla_input,
                as_of_utc=as_of_utc,
                classification_state="unclassified",
                calculation_state="unclassified",
                classification=None,
            )

        if (
            sla_input.customer_org_id is None
            or classification.contract_customer_org_id != sla_input.customer_org_id
        ):
            return _empty_result(
                sla_input=sla_input,
                as_of_utc=as_of_utc,
                classification_state="incompatible",
                calculation_state="unclassified",
                classification=classification,
            )

        policy_revision_id = classification.current_policy_revision_id
        if policy_revision_id is None:
            return _empty_result(
                sla_input=sla_input,
                as_of_utc=as_of_utc,
                classification_state="classified",
                calculation_state="policy_missing",
                classification=classification,
            )

        if (
            read_cache is not None
            and policy_revision_id in read_cache.policy_owner_by_revision
        ):
            policy_owner_id = read_cache.policy_owner_by_revision[policy_revision_id]
        else:
            policy_owner = reader.execute(
                "SELECT contract_product_line_id FROM sla_policy_revisions WHERE policy_revision_id=?",
                (policy_revision_id,),
            ).fetchone()
            policy_owner_id = None if policy_owner is None else str(policy_owner[0])
            if read_cache is not None:
                read_cache.policy_owner_by_revision[policy_revision_id] = policy_owner_id
        if policy_owner_id != classification.contract_product_line_id:
            raise SomaError(
                "SLA_INPUT_INDETERMINATE",
                "current SLA policy does not belong to the classified Contract Product Line",
            )

        if sla_input.status_class == "cancelled":
            return _empty_result(
                sla_input=sla_input,
                as_of_utc=as_of_utc,
                classification_state="classified",
                calculation_state="cancelled_excluded",
                classification=classification,
                endpoint_kind="cancelled",
            )

        if sla_input.report_date_utc is None:
            return _empty_result(
                sla_input=sla_input,
                as_of_utc=as_of_utc,
                classification_state="classified",
                calculation_state="missing_report_date",
                classification=classification,
            )

        if sla_input.severity is None:
            return _empty_result(
                sla_input=sla_input,
                as_of_utc=as_of_utc,
                classification_state="classified",
                calculation_state="severity_unresolved",
                classification=classification,
            )

        if sla_input.status_class in {"resolved", "closed"}:
            endpoint_utc = sla_input.first_resolved_closed_endpoint_utc
            if endpoint_utc is None:
                raise SomaError(
                    "SLA_INPUT_INDETERMINATE",
                    "terminal Service Request lacks an accepted effective Resolved/Closed endpoint",
                )
            if endpoint_utc > as_of_utc:
                raise SomaError(
                    "SLA_INPUT_INDETERMINATE",
                    "terminal Service Request endpoint is later than the requested as-of instant",
                )
            endpoint_kind = "first_resolved_closed"
            terminal = True
        else:
            endpoint_utc = as_of_utc
            endpoint_kind = "current"
            terminal = False

        report_date_utc = sla_input.report_date_utc
        raw_elapsed = Fraction(endpoint_utc - report_date_utc, 1) - Fraction(
            sla_input.suspension_numerator_seconds,
            sla_input.suspension_denominator,
        )
        elapsed = max(raw_elapsed, Fraction(0, 1))

        tier_cache_key = (policy_revision_id, sla_input.severity)
        if (
            read_cache is not None
            and tier_cache_key in read_cache.policy_tiers_by_revision_severity
        ):
            tier_rows = read_cache.policy_tiers_by_revision_severity[tier_cache_key]
        else:
            tier_rows = tuple(
                tuple(row)
                for row in reader.execute(
                    "SELECT policy_tier_id,tier_ordinal,required_percentage_millionths,"
                    "maximum_duration_numerator_seconds,maximum_duration_denominator "
                    "FROM sla_policy_tiers WHERE policy_revision_id=? AND severity=? "
                    "ORDER BY tier_ordinal,policy_tier_id",
                    (policy_revision_id, sla_input.severity),
                ).fetchall()
            )
            if read_cache is not None:
                read_cache.policy_tiers_by_revision_severity[tier_cache_key] = tier_rows
        if not tier_rows:
            raise SomaError(
                "SLA_INPUT_INDETERMINATE",
                "current SLA policy has no tier for the accepted Service Request severity",
            )

        results: list[IndividualTierResult] = []
        for row in tier_rows:
            policy_tier_id = require_uuid4(str(row[0]))
            tier_ordinal = int(row[1])
            required_percentage = int(row[2])
            maximum = Fraction(int(row[3]), int(row[4]))
            within = elapsed <= maximum
            state = (
                "terminal_met"
                if terminal and within
                else "terminal_exceeded"
                if terminal
                else "active_within"
                if within
                else "active_exceeded"
            )
            results.append(
                IndividualTierResult(
                    policy_tier_id=policy_tier_id,
                    tier_ordinal=tier_ordinal,
                    required_percentage_millionths=required_percentage,
                    maximum_duration_numerator_seconds=maximum.numerator,
                    maximum_duration_denominator=maximum.denominator,
                    individual_state=state,
                    inclusive_boundary_met=within,
                )
            )

        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_INDIVIDUAL_SLA_INPUT_V1",
                "service_request_id": service_request_id,
                "sla_input_token": sla_input.input_token,
                "classification_event_id": classification.classification_event_id,
                "classification_revision": classification.classification_revision,
                "contract_id": classification.contract_id,
                "contract_product_line_id": classification.contract_product_line_id,
                "policy_revision_id": policy_revision_id,
                "severity": sla_input.severity,
                "as_of_utc": as_of_utc,
                "endpoint_kind": endpoint_kind,
                "endpoint_utc": endpoint_utc,
                "endpoint_status_evidence_id": sla_input.endpoint_status_evidence_id,
                "suspension": {
                    "numerator_seconds": sla_input.suspension_numerator_seconds,
                    "denominator": sla_input.suspension_denominator,
                    "evidence_id": sla_input.suspension_evidence_id,
                },
                "tiers": [result.policy_tier_id for result in results],
            }
        )
        return IndividualSlaResult(
            service_request_id=service_request_id,
            as_of_utc=as_of_utc,
            classification_state="classified",
            customer_org_id=sla_input.customer_org_id,
            contract_id=classification.contract_id,
            contract_product_line_id=classification.contract_product_line_id,
            classification_event_id=classification.classification_event_id,
            policy_revision_id=policy_revision_id,
            severity=sla_input.severity,
            report_date_utc=report_date_utc,
            endpoint_kind=endpoint_kind,
            endpoint_utc=endpoint_utc,
            suspension_numerator_seconds=sla_input.suspension_numerator_seconds,
            suspension_denominator=sla_input.suspension_denominator,
            effective_elapsed_numerator_seconds=elapsed.numerator,
            effective_elapsed_denominator=elapsed.denominator,
            calculation_state="calculable",
            status_class=sla_input.status_class,
            tier_results=tuple(results),
            sla_input_token=sla_input.input_token,
            input_fingerprint=fingerprint,
            source_report_date_evidence_id=sla_input.report_date_evidence_id,
            source_status_evidence_id=sla_input.status_evidence_id,
            source_suspension_evidence_id=sla_input.suspension_evidence_id,
        )


__all__ = [
    "IndividualSlaCalculator",
    "IndividualSlaReadCache",
    "IndividualSlaResult",
    "IndividualTierResult",
]
