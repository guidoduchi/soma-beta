from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.services.participants import InventoryReportSectionContributor
from soma.product_line_sla.algorithms.cohort_state import canonical_month_bounds
from soma.product_line_sla.report_sections import ReportSectionContributorRegistry
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_source_projection import (
    AcceptedSrFieldDelta,
    AcceptedSrFieldDeltaSet,
    SrSourceProjectionService,
)


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


def test_inventory_report_contributor_emits_exact_minimized_report_scope_t062(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    month_start, month_end = canonical_month_bounds("2026-09")
    included = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="99000061",
    )
    excluded = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="99000062",
    )
    _apply_report_date(factory, included.service_request_id, month_start + 60)
    _apply_report_date(factory, excluded.service_request_id, month_end + 60)

    registry = ReportSectionContributorRegistry((InventoryReportSectionContributor(),))
    with ReadSnapshot(factory) as snapshot:
        before_receipts = int(
            snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]
        )
        emitted = registry.emit_rows(
            snapshot=snapshot.connection,
            report_kind="monthly",
            report_request={
                "period_start_utc": month_start,
                "period_end_utc": month_end,
                "customer_org_id": None,
            },
            as_of_utc=month_end,
        )
        after_receipts = int(
            snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]
        )

    assert before_receipts == after_receipts
    assert len(emitted) == 1
    assert emitted[0]["canonical_row_key"] == included.service_request_id
    assert emitted[0]["section_kind"] == "inventory_summary"
    assert emitted[0]["payload"] == {
        "service_request_id": included.service_request_id,
        "as_of_utc": month_end,
        "spare_need_count": 0,
        "active_spare_need_count": 0,
        "spare_request_count": 0,
        "open_rma_count": 0,
        "fault_tag_count": 0,
        "open_return_obligation_count": 0,
        "attention_count": 0,
    }
    assert not any(
        "communication" in key or "lifecycle" in key or "evidence" in key
        for key in emitted[0]["payload"]
    )
