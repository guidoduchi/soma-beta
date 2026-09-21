from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.product_line_sla.algorithms.policy_validation import (
    PolicyTierInput,
    validate_sla_policy,
)


def test_it_template_materializes_exact_base_and_derived_tiers() -> None:
    policy = validate_sla_policy(template_source="IT_DEFAULT_V1")

    assert policy.template_source == "IT_DEFAULT_V1"
    assert len(policy.tiers) == 7
    assert [
        (
            tier.severity,
            tier.tier_ordinal,
            tier.required_percentage_millionths,
            tier.maximum_duration.numerator_seconds,
            tier.maximum_duration.denominator,
            tier.derived_from_minor_ordinal,
        )
        for tier in policy.tiers
    ] == [
        ("critical", 1, 100_000_000, 604_800, 1, None),
        ("major", 1, 85_000_000, 1_296_000, 1, None),
        ("major", 2, 100_000_000, 2_592_000, 1, None),
        ("minor", 1, 85_000_000, 3_888_000, 1, None),
        ("minor", 2, 100_000_000, 5_184_000, 1, None),
        ("non_fault_inquiry", 1, 85_000_000, 5_832_000, 1, 1),
        ("non_fault_inquiry", 2, 100_000_000, 7_776_000, 1, 2),
    ]
    assert len(policy.content_fingerprint) == 64


def test_nfv_template_materializes_exact_thresholds() -> None:
    policy = validate_sla_policy(template_source="NFV_DEFAULT_V1")

    assert [
        (
            tier.severity,
            tier.required_percentage_millionths,
            tier.maximum_duration.numerator_seconds,
            tier.maximum_duration.denominator,
        )
        for tier in policy.tiers
    ] == [
        ("critical", 100_000_000, 259_200, 1),
        ("major", 100_000_000, 1_296_000, 1),
        ("minor", 100_000_000, 7_776_000, 1),
        ("non_fault_inquiry", 100_000_000, 11_664_000, 1),
    ]


def test_explicit_policy_preserves_fractional_duration_exactly() -> None:
    policy = validate_sla_policy(
        explicit_tiers={
            "critical": (PolicyTierInput("100", "1", "seconds"),),
            "major": (PolicyTierInput("85.000001", "0.5", "seconds"),),
            "minor": (PolicyTierInput("100", "1", "seconds"),),
        }
    )

    major = policy.tiers_for("major")[0]
    assert major.required_percentage_millionths == 85_000_001
    assert major.maximum_duration.numerator_seconds == 1
    assert major.maximum_duration.denominator == 2

    non_fault = policy.tiers_for("non_fault_inquiry")[0]
    assert non_fault.maximum_duration.numerator_seconds == 3
    assert non_fault.maximum_duration.denominator == 2
    assert non_fault.derivation_num == 3
    assert non_fault.derivation_den == 2


@pytest.mark.parametrize(
    "percentage",
    ["0", "100.000001", "85.0000001", "8.5e1", "-1", "+85", ".5", "nan", "inf"],
)
def test_policy_percentage_rejects_out_of_contract_text(percentage: str) -> None:
    with pytest.raises(ValidationError):
        validate_sla_policy(
            explicit_tiers={
                "critical": (PolicyTierInput("100", "1", "days"),),
                "major": (PolicyTierInput(percentage, "1", "days"),),
                "minor": (PolicyTierInput("100", "1", "days"),),
            }
        )


def test_policy_rejects_duplicate_tiers_and_explicit_non_fault() -> None:
    with pytest.raises(ValidationError):
        validate_sla_policy(
            explicit_tiers={
                "critical": (PolicyTierInput("100", "1", "days"),),
                "major": (
                    PolicyTierInput("85", "15", "days"),
                    PolicyTierInput("85.0", "15.0", "days"),
                ),
                "minor": (PolicyTierInput("100", "30", "days"),),
            }
        )

    with pytest.raises(ValidationError):
        validate_sla_policy(
            explicit_tiers={
                "critical": (PolicyTierInput("100", "1", "days"),),
                "major": (PolicyTierInput("100", "1", "days"),),
                "minor": (PolicyTierInput("100", "1", "days"),),
                "non_fault_inquiry": (PolicyTierInput("100", "1.5", "days"),),
            }
        )



def test_f009_policy_rejects_duration_above_exact_rational_bound() -> None:
    with pytest.raises(
        ValidationError,
        match="duration numerator exceeds the accepted bound",
    ):
        validate_sla_policy(
            explicit_tiers={
                "critical": (PolicyTierInput("100", "1", "seconds"),),
                "major": (PolicyTierInput("100", "1", "seconds"),),
                "minor": (
                    PolicyTierInput(
                        "100",
                        "9223372036854775808",
                        "seconds",
                    ),
                ),
            }
        )


def test_f010_non_fault_exact_derivation_overflow_rejects_whole_policy() -> None:
    # The Minor duration itself is within the accepted signed-64-bit numerator
    # bound. Its exact Non-fault derivation is 6_148_914_691_236_517_206 * 3/2
    # = 9_223_372_036_854_775_809 seconds, which is two seconds above the cap.
    with pytest.raises(
        ValidationError,
        match="duration numerator exceeds the accepted bound",
    ):
        validate_sla_policy(
            explicit_tiers={
                "critical": (PolicyTierInput("100", "1", "seconds"),),
                "major": (PolicyTierInput("100", "1", "seconds"),),
                "minor": (
                    PolicyTierInput(
                        "100",
                        "6148914691236517206",
                        "seconds",
                    ),
                ),
            }
        )
