from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json
from soma.product_line_sla.algorithms import policy_validation
from soma.product_line_sla.algorithms.report_snapshot import build_report_snapshot
from soma.product_line_sla.domain import catalog, classification, policy, reports
from soma.product_line_sla.repositories import catalog as catalog_repo
from soma.product_line_sla.repositories import classification as classification_repo
from soma.product_line_sla.repositories import policy as policy_repo
from soma.product_line_sla.repositories import reports as reports_repo


@pytest.mark.parametrize("domain, legacy, names", [
    (catalog, catalog_repo, ("ProductLineRecord", "ContractRecord", "ContractProductLineRecord")),
    (classification, classification_repo, ("ClassificationMappingRecord", "SrClassificationCurrentRecord")),
    (policy, policy_repo, ("SlaPolicyRevisionRecord", "SlaPolicyTierRecord")),
    (reports, reports_repo, ("ReportAttemptRecord",)),
    (policy, policy_validation, ("ExactDuration", "PolicyTierInput", "ValidatedPolicyTier", "ValidatedPolicy")),
])
def test_canonical_values_have_one_class_identity(domain, legacy, names):
    for name in names:
        value_type = getattr(domain, name)
        assert getattr(legacy, name) is value_type
        assert value_type.__module__ == domain.__name__
        assert value_type.__dataclass_params__.frozen


def test_exact_duration_retains_reduced_rational_and_immutability():
    duration = policy.ExactDuration(7, 3)
    assert duration.multiplied(3, 7) == policy.ExactDuration(1, 1)
    assert policy.duration_from_fraction(Fraction(6, 8)) == policy.ExactDuration(3, 4)
    with pytest.raises(FrozenInstanceError):
        duration.denominator = 4
    for numerator, denominator in ((True, 1), (1.0, 1), (2, 4), (0, 1), (1, 0), (1, 1_000_000_001)):
        with pytest.raises(ValidationError):
            policy.ExactDuration(numerator, denominator)


def _snapshot_fixture():
    attempt = reports.ReportAttemptRecord(
        report_attempt_id="00000000-0000-4000-8000-000000000001",
        period_type="monthly", period_start_utc=100, period_end_utc=200,
        period_timezone="America/Guayaquil", scope_kind="all_customers",
        customer_org_id=None, as_of_utc=150, state="ready_to_generate",
        snapshot_hash=None, snapshot_member_count=1, snapshot_cohort_count=1,
        snapshot_section_row_count=1, artifact_filename=None, artifact_sha256=None,
        artifact_size_bytes=None, verified_at_utc=None, failure_code=None,
        created_at_utc=140, completed_at_utc=None, revision=1,
        created_command_id="00000000-0000-4000-8000-000000000002",
        last_command_id="00000000-0000-4000-8000-000000000002",
    )
    rows = dict(
        member_rows=[(1, "sr", "customer", "contract", "cpl", "policy", None,
                      "minor", 110, "active", None, 1, 3, 119, 3, "calculable",
                      "token", "date", "status", None, '{"label":"Frozen"}')],
        tier_rows=[("sr", "tier", "within", 1)],
        cohort_rows=[(1, "2026-09", "customer", "contract", "cpl", "policy",
                      "tier", "minor", 1, 0, 0, 1, 0, "provisional", 0, "input")],
        section_rows=[("inventory", "InventoryV1", 1, 1, 1, "sr", '{"count":2}', "payload")],
    )
    return attempt, rows


def test_snapshot_materialization_preserves_exact_values_and_detaches_payloads():
    attempt, rows = _snapshot_fixture()
    value = build_report_snapshot(attempt, **rows)
    assert value["members"][0]["elapsed_num"] == 119
    assert value["members"][0]["elapsed_den"] == 3
    assert value["members"][0]["classification_event_id"] is None
    assert value["tiers"][0]["inclusive_boundary_met"] is True
    assert value["cohorts"][0]["is_final"] is False
    assert value["sections"][0]["payload"] == {"count": 2}
    original_bytes = canonical_json_bytes(value)
    value["sections"][0]["payload"]["count"] = 999
    value["members"][0]["display_values"]["label"] = "Changed"
    assert canonical_json_bytes(build_report_snapshot(attempt, **rows)) == original_bytes
    completed = replace(attempt, state="completed", revision=10,
                        artifact_filename="later.xlsx", artifact_sha256="x" * 64,
                        artifact_size_bytes=99, completed_at_utc=199)
    assert canonical_json_bytes(build_report_snapshot(completed, **rows)) == original_bytes


def test_repository_hash_uses_only_ordered_snapshot_rows():
    attempt, rows = _snapshot_fixture()

    class Reader:
        def __init__(self):
            self.pending = iter(rows.values())
            self.reads = []

        def execute(self, sql, parameters):
            assert "ORDER BY" in sql
            assert parameters == (attempt.report_attempt_id,)
            self.reads.append(sql)
            self.current = next(self.pending)
            return self

        def fetchall(self):
            return self.current

    class Repository(reports_repo.ReportRepository):
        @staticmethod
        def get_attempt(reader, report_attempt_id):
            assert report_attempt_id == attempt.report_attempt_id
            return attempt

    reader = Reader()
    expected = build_report_snapshot(attempt, **rows)
    # Captured from the pre-extraction repository at closure 624a5922.
    assert sha256_canonical_json(expected) == "b0a526df5136e3cf57f05c44a3451ef32a97f75016eaa8abf810726393be73c9"
    assert Repository.snapshot_semantic_value(reader, attempt.report_attempt_id) == expected
    assert len(reader.reads) == 4
    assert Repository.snapshot_canonical_bytes(Reader(), attempt.report_attempt_id) == canonical_json_bytes(expected)
    assert Repository.snapshot_hash(Reader(), attempt.report_attempt_id) == sha256_canonical_json(expected)
