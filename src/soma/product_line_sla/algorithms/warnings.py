from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.service_request_sla_input import ServiceRequestSlaInputReader

from .cohort_state import CohortProjection
from .individual_sla import IndividualSlaCalculator


@dataclass(frozen=True, slots=True)
class SlaWarning:
    warning_key: str
    warning_kind: str
    target_type: str
    target_id: str
    policy_tier_id: str | None
    condition_fingerprint: str


def _warning(
    *,
    warning_kind: str,
    target_type: str,
    target_id: str,
    policy_tier_id: str | None = None,
    condition: dict[str, object],
) -> SlaWarning:
    identity = {
        "schema": "SOMA_SLA_WARNING_KEY_V1",
        "warning_kind": warning_kind,
        "target_type": target_type,
        "target_id": target_id,
        "policy_tier_id": policy_tier_id,
    }
    return SlaWarning(
        warning_key=sha256_canonical_json(identity),
        warning_kind=warning_kind,
        target_type=target_type,
        target_id=target_id,
        policy_tier_id=policy_tier_id,
        condition_fingerprint=sha256_canonical_json(
            {
                "schema": "SOMA_SLA_WARNING_CONDITION_V1",
                **identity,
                "condition": condition,
            }
        ),
    )


class SlaWarningCalculator:
    """Pure warning projection. Warnings never become SLA/lifecycle authority."""

    @classmethod
    def individual(
        cls,
        reader: Any,
        *,
        service_request_id: str,
        as_of_utc: int,
        suspension_ending_soon_threshold_seconds: int | None = None,
    ) -> tuple[SlaWarning, ...]:
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("as_of_utc must be a nonnegative whole-second UTC instant")
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

        sla_input = ServiceRequestSlaInputReader.get(reader, service_request_id)
        result = IndividualSlaCalculator.calculate(reader, service_request_id, as_of_utc)
        warnings: list[SlaWarning] = []

        if result.classification_state in {"unclassified", "incompatible"}:
            warnings.append(
                _warning(
                    warning_kind="sla_unclassified",
                    target_type="service_request",
                    target_id=result.service_request_id,
                    condition={
                        "classification_state": result.classification_state,
                        "sla_input_token": result.sla_input_token,
                    },
                )
            )

        if result.calculation_state == "missing_report_date":
            warnings.append(
                _warning(
                    warning_kind="sla_uncalculable_missing_report_date",
                    target_type="service_request",
                    target_id=result.service_request_id,
                    condition={
                        "classification_event_id": result.classification_event_id,
                        "sla_input_token": result.sla_input_token,
                    },
                )
            )

        # Terminal and Cancelled status suppress live individual SLA-risk warnings.
        if result.status_class == "active":
            for tier in result.tier_results:
                if tier.individual_state == "active_exceeded":
                    warnings.append(
                        _warning(
                            warning_kind="individual_tier_exceeded",
                            target_type="service_request",
                            target_id=result.service_request_id,
                            policy_tier_id=tier.policy_tier_id,
                            condition={
                                "individual_input_fingerprint": result.input_fingerprint,
                                "individual_state": tier.individual_state,
                            },
                        )
                    )

        if sla_input.status_token == "Customer Agreed Suspend":
            planned_end = sla_input.suspend_planned_end_utc
            if planned_end is None or planned_end <= as_of_utc:
                warnings.append(
                    _warning(
                        warning_kind="suspension_end_missing_or_expired",
                        target_type="service_request",
                        target_id=result.service_request_id,
                        condition={
                            "as_of_utc": as_of_utc,
                            "planned_end_utc": planned_end,
                            "planned_end_evidence_id": sla_input.suspend_planned_end_evidence_id,
                            "status_evidence_id": sla_input.status_evidence_id,
                        },
                    )
                )
            elif (
                suspension_ending_soon_threshold_seconds is not None
                and planned_end - as_of_utc
                <= suspension_ending_soon_threshold_seconds
            ):
                warnings.append(
                    _warning(
                        warning_kind="suspension_ending_soon",
                        target_type="service_request",
                        target_id=result.service_request_id,
                        condition={
                            "as_of_utc": as_of_utc,
                            "planned_end_utc": planned_end,
                            "threshold_seconds": suspension_ending_soon_threshold_seconds,
                            "planned_end_evidence_id": sla_input.suspend_planned_end_evidence_id,
                            "status_evidence_id": sla_input.status_evidence_id,
                        },
                    )
                )

        return tuple(
            sorted(
                warnings,
                key=lambda warning: (
                    warning.warning_kind,
                    warning.target_type,
                    warning.target_id,
                    "" if warning.policy_tier_id is None else warning.policy_tier_id,
                ),
            )
        )

    @classmethod
    def cohort(cls, cohort: CohortProjection) -> tuple[SlaWarning, ...]:
        if cohort.state not in {"at_risk", "breached"}:
            return ()
        kind = "cohort_at_risk" if cohort.state == "at_risk" else "cohort_breached"
        return (
            _warning(
                warning_kind=kind,
                target_type="sla_cohort",
                target_id=cohort.cohort_key,
                policy_tier_id=cohort.policy_tier_id,
                condition={
                    "input_fingerprint": cohort.input_fingerprint,
                    "state": cohort.state,
                    "denominator": cohort.denominator,
                    "lower_bound_met_count": cohort.lower_bound_met_count,
                    "best_possible_met_count": cohort.best_possible_met_count,
                },
            ),
        )


__all__ = ["SlaWarning", "SlaWarningCalculator"]
