from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import ObjectContract, canonical_json_bytes, sha256_canonical_json
from soma.product_line_sla.report_sections import (
    ReportSectionContributorRegistry,
    ReportSectionDescriptor,
    ReportSectionRow,
)


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _contract(name: str = "TestReportSectionV1") -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=frozenset({"value"}),
        allowed_fields=frozenset({"value"}),
        max_depth=2,
        max_collection_items=4,
        max_utf8_bytes=1024,
    )


class _GoodContributor:
    def section_descriptor(self) -> ReportSectionDescriptor:
        return ReportSectionDescriptor(
            section_kind="test_section",
            schema_name="TestReportSectionV1",
            schema_version=1,
            ordinal=7,
            payload_contract=_contract(),
        )

    def stream_snapshot_rows(self, snapshot, report_request, as_of_utc):
        assert report_request["report_attempt_id"] == "test-attempt"
        assert as_of_utc == 123
        snapshot.execute("SELECT 1").fetchone()
        return (
            ReportSectionRow("a", {"value": "alpha"}),
            ReportSectionRow("b", {"value": "beta"}),
        )


class _UnorderedContributor(_GoodContributor):
    def stream_snapshot_rows(self, snapshot, report_request, as_of_utc):
        return (
            ReportSectionRow("b", {"value": "beta"}),
            ReportSectionRow("a", {"value": "alpha"}),
        )


class _MutationProbeContributor:
    def section_descriptor(self) -> ReportSectionDescriptor:
        return ReportSectionDescriptor(
            section_kind="mutation_probe",
            schema_name="MutationProbeV1",
            schema_version=1,
            ordinal=8,
            payload_contract=ObjectContract(
                name="MutationProbeV1",
                version=1,
                required_fields=frozenset({"value"}),
                allowed_fields=frozenset({"value"}),
                max_depth=2,
                max_collection_items=4,
                max_utf8_bytes=1024,
            ),
        )

    def stream_snapshot_rows(self, snapshot, report_request, as_of_utc):
        mutation_rejected = False
        try:
            snapshot.execute(
                "DELETE FROM service_requests WHERE 1=0"
            )
        except BaseException:
            mutation_rejected = True
        if not mutation_rejected:
            raise AssertionError("report contributor unexpectedly obtained write authority")
        return (ReportSectionRow("mutation", {"value": "rejected"}),)


def test_report_section_registry_accepts_only_registered_versioned_payloads_t035(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = ReportSectionContributorRegistry((_GoodContributor(),))

    with ReadSnapshot(factory) as snapshot:
        emitted = registry.emit_rows(
            snapshot=snapshot.connection,
            report_kind="monthly",
            report_request={"report_attempt_id": "test-attempt"},
            as_of_utc=123,
        )

    assert [row["canonical_row_key"] for row in emitted] == ["a", "b"]
    assert [row["row_ordinal"] for row in emitted] == [1, 2]
    assert all(row["section_ordinal"] == 7 for row in emitted)

    first = emitted[0]
    payload_json = canonical_json_bytes(first["payload"]).decode("utf-8")
    normalized = registry.validate_staged_row(
        section_kind="test_section",
        schema_name="TestReportSectionV1",
        schema_version=1,
        section_ordinal=7,
        canonical_row_key="a",
        payload_json=payload_json,
        payload_sha256=sha256_canonical_json(first["payload"]),
    )
    assert normalized == {"value": "alpha"}

    with pytest.raises(ValidationError):
        registry.validate_staged_row(
            section_kind="test_section",
            schema_name="UnknownSectionV1",
            schema_version=1,
            section_ordinal=7,
            canonical_row_key="a",
            payload_json=payload_json,
            payload_sha256=sha256_canonical_json(first["payload"]),
        )

    with pytest.raises(ValidationError):
        registry.validate_staged_row(
            section_kind="test_section",
            schema_name="TestReportSectionV1",
            schema_version=2,
            section_ordinal=7,
            canonical_row_key="a",
            payload_json=payload_json,
            payload_sha256=sha256_canonical_json(first["payload"]),
        )


def test_report_section_registry_requires_canonical_contributor_order_t035(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = ReportSectionContributorRegistry((_UnorderedContributor(),))
    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(IntegrityFailure):
            registry.emit_rows(
                snapshot=snapshot.connection,
                report_kind="monthly",
                report_request={"report_attempt_id": "test-attempt"},
                as_of_utc=123,
            )


def test_report_section_contributor_receives_read_only_snapshot_t035(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = ReportSectionContributorRegistry((_MutationProbeContributor(),))

    with ReadSnapshot(factory) as snapshot:
        before = snapshot.connection.execute(
            "SELECT COUNT(*) FROM service_requests"
        ).fetchone()[0]
        emitted = registry.emit_rows(
            snapshot=snapshot.connection,
            report_kind="monthly",
            report_request={"report_attempt_id": "test-attempt"},
            as_of_utc=123,
        )
        after = snapshot.connection.execute(
            "SELECT COUNT(*) FROM service_requests"
        ).fetchone()[0]

    assert before == after
    assert emitted[0]["payload"] == {"value": "rejected"}
