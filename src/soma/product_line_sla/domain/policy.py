"""Exact SLA policy values shared by validation and persistence."""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from soma.foundation.errors import ValidationError

_SUPPORTED_SEVERITIES = frozenset({"critical", "major", "minor", "non_fault_inquiry"})
_MAX_DURATION_NUMERATOR = 9_223_372_036_854_775_807
_MAX_DURATION_DENOMINATOR = 1_000_000_000


@dataclass(frozen=True, slots=True)
class ExactDuration:
    numerator_seconds: int
    denominator: int

    def __post_init__(self) -> None:
        if (
            type(self.numerator_seconds) is not int
            or type(self.denominator) is not int
            or self.numerator_seconds <= 0
            or self.denominator <= 0
        ):
            raise ValidationError("SLA duration must be a positive rational number of seconds")
        divisor = math.gcd(self.numerator_seconds, self.denominator)
        if divisor != 1:
            raise ValidationError("SLA duration rational must be reduced")
        if self.numerator_seconds > _MAX_DURATION_NUMERATOR:
            raise ValidationError("SLA duration numerator exceeds the accepted bound")
        if self.denominator > _MAX_DURATION_DENOMINATOR:
            raise ValidationError("SLA duration denominator exceeds the accepted bound")

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator_seconds, self.denominator)

    def multiplied(self, numerator: int, denominator: int) -> "ExactDuration":
        if type(numerator) is not int or type(denominator) is not int or numerator <= 0 or denominator <= 0:
            raise ValidationError("SLA duration multiplier must be a positive rational")
        value = self.fraction * Fraction(numerator, denominator)
        return duration_from_fraction(value)

    def to_fingerprint_object(self) -> dict[str, int]:
        return {
            "numerator_seconds": self.numerator_seconds,
            "denominator": self.denominator,
        }


@dataclass(frozen=True, slots=True)
class PolicyTierInput:
    required_percentage: str
    maximum_duration: str
    duration_unit: str


@dataclass(frozen=True, slots=True)
class ValidatedPolicyTier:
    severity: str
    tier_ordinal: int
    required_percentage_millionths: int
    maximum_duration: ExactDuration
    derived_from_minor_ordinal: int | None = None
    derivation_num: int | None = None
    derivation_den: int | None = None

    def to_fingerprint_object(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "tier_ordinal": self.tier_ordinal,
            "required_percentage_millionths": self.required_percentage_millionths,
            "maximum_duration": self.maximum_duration.to_fingerprint_object(),
            "derived_from_minor_ordinal": self.derived_from_minor_ordinal,
            "derivation_num": self.derivation_num,
            "derivation_den": self.derivation_den,
        }


@dataclass(frozen=True, slots=True)
class ValidatedPolicy:
    template_source: str | None
    tiers: tuple[ValidatedPolicyTier, ...]
    content_fingerprint: str

    def tiers_for(self, severity: str) -> tuple[ValidatedPolicyTier, ...]:
        if severity not in _SUPPORTED_SEVERITIES:
            raise ValidationError("unsupported SLA severity")
        return tuple(tier for tier in self.tiers if tier.severity == severity)


def duration_from_fraction(value: Fraction) -> ExactDuration:
    if value <= 0:
        raise ValidationError("SLA duration must be positive")
    reduced = Fraction(value.numerator, value.denominator)
    return ExactDuration(reduced.numerator, reduced.denominator)


@dataclass(frozen=True, slots=True)
class SlaPolicyRevisionRecord:
    policy_revision_id: str
    contract_product_line_id: str
    revision_ordinal: int
    policy_name: str
    template_source: str | None
    created_at_utc: int
    created_command_id: str


@dataclass(frozen=True, slots=True)
class SlaPolicyTierRecord:
    policy_tier_id: str
    policy_revision_id: str
    severity: str
    tier_ordinal: int
    required_percentage_millionths: int
    maximum_duration_numerator_seconds: int
    maximum_duration_denominator: int
    derived_from_tier_id: str | None
    derivation_num: int | None
    derivation_den: int | None


__all__ = [
    "ExactDuration", "PolicyTierInput", "ValidatedPolicy", "ValidatedPolicyTier",
    "SlaPolicyRevisionRecord", "SlaPolicyTierRecord", "duration_from_fraction",
]
