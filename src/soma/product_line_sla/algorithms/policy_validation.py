from __future__ import annotations

import re
from fractions import Fraction
from typing import Iterable, Mapping, Sequence

from soma.foundation.errors import ValidationError
from soma.foundation.strict_json import sha256_canonical_json
from soma.product_line_sla.domain.policy import (
    ExactDuration,
    PolicyTierInput,
    ValidatedPolicy,
    ValidatedPolicyTier,
    duration_from_fraction as _duration_from_fraction,
)

_BASE_SEVERITIES = ("critical", "major", "minor")
_DERIVED_SEVERITY = "non_fault_inquiry"
_TEMPLATE_IDS = frozenset({"IT_DEFAULT_V1", "NFV_DEFAULT_V1"})
_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.([0-9]+))?%?\Z")
_DURATION_UNITS = {
    "seconds": 1,
    "hours": 3_600,
    "days": 86_400,
}
_MAX_PERCENTAGE_MILLIONTHS = 100_000_000
_MAX_POLICY_TIERS = 128

_TEMPLATE_INPUTS: dict[str, dict[str, tuple[tuple[str, str, str], ...]]] = {
    "IT_DEFAULT_V1": {
        "critical": (("100", "7", "days"),),
        "major": (("85", "15", "days"), ("100", "30", "days")),
        "minor": (("85", "45", "days"), ("100", "60", "days")),
    },
    "NFV_DEFAULT_V1": {
        "critical": (("100", "3", "days"),),
        "major": (("100", "15", "days"),),
        "minor": (("100", "90", "days"),),
    },
}


def _decimal_fraction(value: str, *, label: str, max_scale: int | None = None) -> Fraction:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be finite decimal text")
    if not value or value != value.strip() or value.startswith(("+", "-")):
        raise ValidationError(f"{label} must be canonical finite decimal text")
    match = _DECIMAL_RE.fullmatch(value)
    if match is None:
        raise ValidationError(f"{label} must be canonical finite decimal text")
    numeric = value[:-1] if value.endswith("%") else value
    fraction_digits = match.group(1) or ""
    if max_scale is not None and len(fraction_digits) > max_scale:
        raise ValidationError(f"{label} exceeds the accepted decimal scale")
    whole_text, dot, fractional_text = numeric.partition(".")
    denominator = 10 ** len(fractional_text) if dot else 1
    numerator = int(whole_text) * denominator + (int(fractional_text) if fractional_text else 0)
    return Fraction(numerator, denominator)


def _percentage_millionths(value: str) -> int:
    percentage = _decimal_fraction(value, label="required percentage", max_scale=6)
    scaled = percentage * 1_000_000
    if scaled.denominator != 1:
        raise ValidationError("required percentage cannot be represented exactly in millionths")
    millionths = scaled.numerator
    if not 1 <= millionths <= _MAX_PERCENTAGE_MILLIONTHS:
        raise ValidationError("required percentage must be greater than zero and at most 100%")
    return millionths


def _duration(value: str, unit: str) -> ExactDuration:
    if unit not in _DURATION_UNITS:
        raise ValidationError("SLA duration unit must be seconds, hours, or days")
    decimal = _decimal_fraction(value, label="maximum duration")
    return _duration_from_fraction(decimal * _DURATION_UNITS[unit])


def _canonical_input(
    tiers_by_severity: Mapping[str, Sequence[PolicyTierInput]],
) -> dict[str, tuple[PolicyTierInput, ...]]:
    if not isinstance(tiers_by_severity, Mapping):
        raise ValidationError("explicit SLA policy tiers must be a severity mapping")
    unknown = set(tiers_by_severity) - set(_BASE_SEVERITIES)
    if unknown:
        if _DERIVED_SEVERITY in unknown:
            raise ValidationError("Non-fault inquiry tiers are derived and cannot be supplied explicitly")
        raise ValidationError("SLA policy contains an unsupported severity")
    result: dict[str, tuple[PolicyTierInput, ...]] = {}
    for severity in _BASE_SEVERITIES:
        raw = tiers_by_severity.get(severity)
        if raw is None or isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or not raw:
            raise ValidationError(f"SLA policy must define at least one {severity} tier")
        normalized: list[PolicyTierInput] = []
        for item in raw:
            if not isinstance(item, PolicyTierInput):
                raise ValidationError("SLA policy tier input has the wrong type")
            normalized.append(item)
        result[severity] = tuple(normalized)
    return result


def _template_inputs(template_source: str) -> dict[str, tuple[PolicyTierInput, ...]]:
    if template_source not in _TEMPLATE_IDS:
        raise ValidationError("unknown SLA policy template")
    return {
        severity: tuple(
            PolicyTierInput(required_percentage=percentage, maximum_duration=duration, duration_unit=unit)
            for percentage, duration, unit in rows
        )
        for severity, rows in _TEMPLATE_INPUTS[template_source].items()
    }


def _base_tiers(
    canonical: Mapping[str, Sequence[PolicyTierInput]],
) -> tuple[ValidatedPolicyTier, ...]:
    result: list[ValidatedPolicyTier] = []
    for severity in _BASE_SEVERITIES:
        material: list[tuple[ExactDuration, int, int]] = []
        seen: set[tuple[int, int, int]] = set()
        for input_ordinal, item in enumerate(canonical[severity]):
            percentage = _percentage_millionths(item.required_percentage)
            duration = _duration(item.maximum_duration, item.duration_unit)
            identity = (
                percentage,
                duration.numerator_seconds,
                duration.denominator,
            )
            if identity in seen:
                raise ValidationError(f"SLA policy repeats an exact {severity} tier")
            seen.add(identity)
            material.append((duration, percentage, input_ordinal))
        material.sort(
            key=lambda item: (
                item[0].fraction,
                item[1],
                item[2],
            )
        )
        for ordinal, (duration, percentage, _input_ordinal) in enumerate(material, start=1):
            result.append(
                ValidatedPolicyTier(
                    severity=severity,
                    tier_ordinal=ordinal,
                    required_percentage_millionths=percentage,
                    maximum_duration=duration,
                )
            )
    return tuple(result)


def _with_derived_non_fault(base: Sequence[ValidatedPolicyTier]) -> tuple[ValidatedPolicyTier, ...]:
    tiers = list(base)
    for minor in (tier for tier in base if tier.severity == "minor"):
        tiers.append(
            ValidatedPolicyTier(
                severity=_DERIVED_SEVERITY,
                tier_ordinal=minor.tier_ordinal,
                required_percentage_millionths=minor.required_percentage_millionths,
                maximum_duration=minor.maximum_duration.multiplied(3, 2),
                derived_from_minor_ordinal=minor.tier_ordinal,
                derivation_num=3,
                derivation_den=2,
            )
        )
    if len(tiers) > _MAX_POLICY_TIERS:
        raise ValidationError("SLA policy exceeds the accepted tier-count bound")
    return tuple(tiers)


def validate_sla_policy(
    *,
    template_source: str | None = None,
    explicit_tiers: Mapping[str, Sequence[PolicyTierInput]] | None = None,
) -> ValidatedPolicy:
    if (template_source is None) == (explicit_tiers is None):
        raise ValidationError("SLA policy must supply exactly one template or explicit tier definition")
    if template_source is not None:
        canonical = _template_inputs(template_source)
        source = template_source
    else:
        canonical = _canonical_input(explicit_tiers)  # type: ignore[arg-type]
        source = None
    tiers = _with_derived_non_fault(_base_tiers(canonical))
    fingerprint = sha256_canonical_json(
        {
            "schema": "SOMA_SLA_POLICY_CONTENT_V1",
            "template_source": source,
            "tiers": [tier.to_fingerprint_object() for tier in tiers],
        }
    )
    return ValidatedPolicy(
        template_source=source,
        tiers=tiers,
        content_fingerprint=fingerprint,
    )


__all__ = [
    "ExactDuration",
    "PolicyTierInput",
    "ValidatedPolicy",
    "ValidatedPolicyTier",
    "validate_sla_policy",
]
