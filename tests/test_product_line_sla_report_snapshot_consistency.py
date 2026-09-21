from __future__ import annotations

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import ObjectContract
from soma.product_line_sla.algorithms.cohort_state import canonical_month_bounds
from soma.product_line_sla.jobs import PRODUCT_LINE_SLA_JOB_CONTRACTS
from soma.product_line_sla.jobs.report_generation import SlaReportGenerationWorker
from soma.product_line_sla.report_sections import (
    ReportSectionContributorRegistry,
    ReportSectionDescriptor,
    ReportSectionRow,
)
from soma.product_line_sla.repositories.reports import ReportRepository
from soma.product_line_sla.services.report_orchestration import SlaReportOrchestrationService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_source_projection import (
    AcceptedSrFieldDelta,
    AcceptedSrFieldDeltaSet,
    SrSourceProjectionService,
)

MONTH = "2026-09"
DESTINATION_TOKEN = "d" * 64


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


class _EvidenceProvider:
    def validate_published_field(self, *_args, **_kwargs) -> str:
        return "VALID"

    def source_freshness_token(self, *_args, **_kwargs) -> str:
        return "a" * 64

    def has_accepted_source_provenance(self, *_args, **_kwargs) -> str:
        return "YES"


def _apply_report_date(factory, service_request_id: str, report_date: int) -> None:
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                command_id,
                "TestAcceptedSourceProjection",
                "a" * 64,
                "service_request",
                service_request_id,
                1,
                None,
                None,
            ),
        )
        SrSourceProjectionService(_EvidenceProvider()).apply_accepted_field_deltas(
            uow,
            service_request_id,
            AcceptedSrFieldDeltaSet(
                accepted_command_id=command_id,
                deltas=(
                    AcceptedSrFieldDelta(
                        field_key="report_date",
                        value_state="usable",
                        value_kind="instant",
                        value=report_date,
                        source_chronology_utc=report_date,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                ),
            ),
        )


class _ConcurrentMutationContributor:
    def __init__(self, factory, report_date: int) -> None:
        self._factory = factory
        self._report_date = report_date
        self._mutated = False

    def section_descriptor(self) -> ReportSectionDescriptor:
        return ReportSectionDescriptor(
            section_kind="snapshot_probe",
            schema_name="SnapshotProbeV1",
            schema_version=1,
            ordinal=1,
            payload_contract=ObjectContract(
                name="SnapshotProbeV1",
                version=1,
                required_fields=frozenset(
                    {"service_request_count", "as_of_utc", "scope_kind"}
                ),
                allowed_fields=frozenset(
                    {"service_request_count", "as_of_utc", "scope_kind"}
                ),
                max_depth=2,
                max_collection_items=8,
                max_utf8_bytes=1024,
            ),
        )

    def stream_snapshot_rows(self, snapshot, report_request, as_of_utc):
        before = int(
            snapshot.execute("SELECT COUNT(*) FROM service_requests").fetchone()[0]
        )
        if not self._mutated:
            created = ServiceRequestService(
                self._factory
            ).create_manual_service_request(
                command_id=new_uuid4(),
                official_sr_no="99000005",
            )
            _apply_report_date(
                self._factory,
                created.service_request_id,
                self._report_date,
            )
            self._mutated = True

        # The same stable snapshot must not observe the concurrent committed write.
        after = int(
            snapshot.execute("SELECT COUNT(*) FROM service_requests").fetchone()[0]
        )
        assert after == before
        return (
            ReportSectionRow(
                canonical_row_key="snapshot",
                payload={
                    "service_request_count": after,
                    "as_of_utc": as_of_utc,
                    "scope_kind": report_request["scope_kind"],
                },
            ),
        )


def _start_claim_and_seal(factory, registry, *, as_of_utc: int) -> str:
    started = SlaReportOrchestrationService(factory).start_monthly(
        command_id=new_uuid4(),
        calendar_month=MONTH,
        as_of_utc=as_of_utc,
        customer_org_id=None,
        destination_request_token=DESTINATION_TOKEN,
    )
    jobs = DurableJobCoordinator(
        factory,
        JobTypeRegistry(PRODUCT_LINE_SLA_JOB_CONTRACTS),
    )
    claim = jobs.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None
    report_id = str(started["report_attempt_id"])
    SlaReportGenerationWorker(
        factory,
        section_registry=registry,
    ).snapshot_and_seal(claim)
    return report_id


def test_report_materialization_uses_one_stable_domain_snapshot_t030(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + 60
    as_of_utc = month_start + 3600

    first_sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="99000004",
    )
    _apply_report_date(factory, first_sr.service_request_id, report_date)

    contributor = _ConcurrentMutationContributor(factory, report_date)
    registry = ReportSectionContributorRegistry((contributor,))

    first_report_id = _start_claim_and_seal(
        factory,
        registry,
        as_of_utc=as_of_utc,
    )
    with ReadSnapshot(factory) as snapshot:
        first = ReportRepository.get_attempt(snapshot.connection, first_report_id)
        assert first is not None
        assert first.state == "ready_to_generate"
        assert first.as_of_utc == as_of_utc
        assert first.scope_kind == "all_customers"
        assert first.snapshot_member_count == 1
        assert first.snapshot_section_row_count == 1
        first_semantic = ReportRepository.snapshot_semantic_value(
            snapshot.connection,
            first_report_id,
        )
        assert len(first_semantic["members"]) == 1
        assert first_semantic["sections"][0]["payload"] == {
            "service_request_count": 1,
            "as_of_utc": as_of_utc,
            "scope_kind": "all_customers",
        }
        assert first_semantic["report_request"]["as_of_utc"] == as_of_utc
        assert first_semantic["report_request"]["scope_kind"] == "all_customers"
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM service_requests"
        ).fetchone()[0] == 2

    second_report_id = _start_claim_and_seal(
        factory,
        registry,
        as_of_utc=as_of_utc,
    )
    with ReadSnapshot(factory) as snapshot:
        second = ReportRepository.get_attempt(snapshot.connection, second_report_id)
        assert second is not None
        assert second.state == "ready_to_generate"
        assert second.snapshot_member_count == 2
        assert second.snapshot_section_row_count == 1
        second_semantic = ReportRepository.snapshot_semantic_value(
            snapshot.connection,
            second_report_id,
        )
        assert len(second_semantic["members"]) == 2
        assert second_semantic["sections"][0]["payload"] == {
            "service_request_count": 2,
            "as_of_utc": as_of_utc,
            "scope_kind": "all_customers",
        }

    assert first_report_id != second_report_id
