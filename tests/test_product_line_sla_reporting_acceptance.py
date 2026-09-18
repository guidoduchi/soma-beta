from __future__ import annotations

import zipfile

import pytest

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import ObjectContract
from soma.product_line_sla.algorithms.cohort_state import canonical_month_bounds
from soma.product_line_sla.artifacts.xlsx_report import (
    BoundReportDestination,
    SlaReportXlsxArtifact,
)
from soma.product_line_sla.jobs import PRODUCT_LINE_SLA_JOB_CONTRACTS
from soma.product_line_sla.jobs.report_generation import SlaReportGenerationWorker
from soma.product_line_sla.queries.reports import ProductLineSlaReportQueryService
from soma.product_line_sla.report_sections import (
    ReportSectionContributorRegistry,
    ReportSectionDescriptor,
    ReportSectionRow,
)
from soma.product_line_sla.repositories.reports import ReportRepository
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import (
    ProductLineSlaClassificationService,
)
from soma.product_line_sla.services.report_orchestration import (
    SlaReportOrchestrationService,
)
from soma.product_line_sla.services.report_worker import SlaReportWorkerService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.application.profile_service import LocalUserProfileService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService
from soma.tickets.sr_source_projection import (
    AcceptedSrFieldDelta,
    AcceptedSrFieldDeltaSet,
    SrSourceProjectionService,
)
from soma.tickets.working_notes import WorkingNoteService

MONTH = "2026-09"
DESTINATION_TOKEN = "d" * 64
SUMMARY_SECRET = "MINIMIZATION_SECRET_SUMMARY_7e3c7b"
ACCOUNT_SECRET = "MINIMIZATION_SECRET_ACCOUNT_4d2a91"
NOTE_SECRET = "MINIMIZATION_SECRET_WORKING_NOTE_8f1b63"


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


class _TestSectionContributor:
    def section_descriptor(self) -> ReportSectionDescriptor:
        return ReportSectionDescriptor(
            section_kind="acceptance_probe",
            schema_name="AcceptanceProbeV1",
            schema_version=1,
            ordinal=1,
            payload_contract=ObjectContract(
                name="AcceptanceProbeV1",
                version=1,
                required_fields=frozenset({"label"}),
                allowed_fields=frozenset({"label"}),
                max_depth=2,
                max_collection_items=4,
                max_utf8_bytes=1024,
            ),
        )

    def stream_snapshot_rows(self, snapshot, report_request, as_of_utc):
        snapshot.execute("SELECT 1").fetchone()
        return (
            ReportSectionRow(
                canonical_row_key="probe",
                payload={"label": "bounded-safe-section"},
            ),
        )


def _ensure_profile(factory) -> str:
    profile_id = new_uuid4()
    profiles = LocalUserProfileService(factory)
    with UnitOfWork(factory) as uow:
        command_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id"
            ") VALUES (?, 'TestSetupProfile', ?, 'local_user_profile', NULL, 1, NULL, NULL)",
            (command_id, "0" * 64),
        )
        profiles.ensure_singleton_local_administrator(
            uow,
            parent_command_id=command_id,
            profile_id=profile_id,
        )
    return profile_id


def _apply_source(
    factory,
    service_request_id: str,
    *,
    report_date_utc: int,
) -> None:
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
                        value=report_date_utc,
                        source_chronology_utc=report_date_utc,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                    AcceptedSrFieldDelta(
                        field_key="customer_severity",
                        value_state="usable",
                        value_kind="controlled",
                        value="Critical",
                        source_chronology_utc=report_date_utc,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                    AcceptedSrFieldDelta(
                        field_key="problem_summary",
                        value_state="usable",
                        value_kind="text",
                        value=SUMMARY_SECRET,
                        source_chronology_utc=report_date_utc,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                    AcceptedSrFieldDelta(
                        field_key="customer_account_code",
                        value_state="usable",
                        value_kind="text",
                        value=ACCOUNT_SECRET,
                        source_chronology_utc=report_date_utc,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                ),
            ),
        )


def _classified_sr(factory):
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + 86_400

    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Reporting Acceptance Customer",
    )
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(
        command_id=new_uuid4(),
        name="Reporting Acceptance Product",
    )
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name="Reporting Acceptance Contract",
        contract_reference="REPORT-ACCEPTANCE",
    )
    cpl = catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name="Reporting Acceptance Policy",
        initial_template_source="IT_DEFAULT_V1",
    )

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="97500001",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="report_acceptance_customer",
    )
    preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl.target_id,
    )
    classification.classify_service_request(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        target_contract_product_line_id=cpl.target_id,
        preview_fingerprint=preview.input_fingerprint,
        origin="manual_review",
        reason_category="report_acceptance_classification",
    )
    _apply_source(
        factory,
        sr.service_request_id,
        report_date_utc=report_date,
    )
    return customer.customer_org_id, sr.service_request_id, report_date


def _start_claim(
    factory,
    *,
    customer_org_id: str | None,
    as_of_utc: int,
):
    started = SlaReportOrchestrationService(factory).start_monthly(
        command_id=new_uuid4(),
        calendar_month=MONTH,
        as_of_utc=as_of_utc,
        customer_org_id=customer_org_id,
        destination_request_token=DESTINATION_TOKEN,
    )
    jobs = DurableJobCoordinator(
        factory,
        JobTypeRegistry(PRODUCT_LINE_SLA_JOB_CONTRACTS),
    )
    claim = jobs.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None
    return str(started["report_attempt_id"]), jobs, claim


def _artifact(factory, tmp_path) -> SlaReportXlsxArtifact:
    return SlaReportXlsxArtifact(
        factory,
        BoundReportDestination(DESTINATION_TOKEN, tmp_path),
    )


def _complete_real_report(factory, tmp_path):
    _ensure_profile(factory)
    customer_org_id, service_request_id, report_date = _classified_sr(factory)
    WorkingNoteService(factory).add(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=service_request_id,
        body_text=NOTE_SECRET,
    )
    report_id, jobs, claim = _start_claim(
        factory,
        customer_org_id=customer_org_id,
        as_of_utc=report_date + 3_600,
    )
    artifact = _artifact(factory, tmp_path)
    registry = ReportSectionContributorRegistry((_TestSectionContributor(),))
    SlaReportGenerationWorker(
        factory,
        section_registry=registry,
        artifact=artifact,
    ).run_to_completion(claim)
    return report_id, jobs, claim, artifact, service_request_id


def test_report_snapshot_is_minimized_and_excludes_unrelated_ticket_text_t031(
    initialized_database,
    tmp_path,
) -> None:
    factory = _factory(initialized_database)
    report_id, _jobs, _claim, _artifact_adapter, service_request_id = (
        _complete_real_report(factory, tmp_path)
    )

    with ReadSnapshot(factory) as snapshot:
        attempt = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert attempt is not None
        assert attempt.state == "completed"
        assert attempt.artifact_filename is not None

        semantic = ReportRepository.snapshot_semantic_value(
            snapshot.connection,
            report_id,
        )
        canonical = ReportRepository.snapshot_canonical_bytes(
            snapshot.connection,
            report_id,
        )
        members = semantic["members"]
        assert isinstance(members, list)
        assert len(members) == 1
        member = members[0]
        assert isinstance(member, dict)
        assert member["service_request_id"] == service_request_id
        assert member["display_values"] is None
        assert set(member) == {
            "member_ordinal",
            "service_request_id",
            "customer_org_id",
            "contract_id",
            "contract_product_line_id",
            "policy_revision_id",
            "classification_event_id",
            "severity",
            "report_date_utc",
            "status_class",
            "endpoint_utc",
            "suspension_num",
            "suspension_den",
            "elapsed_num",
            "elapsed_den",
            "calculation_state",
            "sla_input_token",
            "source_report_date_evidence_id",
            "source_status_evidence_id",
            "source_suspension_evidence_id",
            "display_values",
        }

        source_row = snapshot.connection.execute(
            "SELECT p.problem_summary_observation_id,p.customer_account_code_observation_id "
            "FROM sr_current_source_projection p WHERE p.service_request_id=?",
            (service_request_id,),
        ).fetchone()
        assert source_row is not None
        assert source_row[0] is not None
        assert source_row[1] is not None

        note = snapshot.connection.execute(
            "SELECT body_text FROM sr_working_notes WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        assert note is not None
        assert str(note[0]) == NOTE_SECRET

        final_path = tmp_path / attempt.artifact_filename

    for forbidden in (SUMMARY_SECRET, ACCOUNT_SECRET, NOTE_SECRET, "Product"):
        assert forbidden.encode("utf-8") not in canonical

    # XLSX is a ZIP container; inspect decompressed entries rather than relying
    # on accidental compression to hide forbidden text.
    with zipfile.ZipFile(final_path, "r") as archive:
        represented_bytes = b"".join(
            archive.read(name)
            for name in sorted(archive.namelist())
        )
    for forbidden in (SUMMARY_SECRET, ACCOUNT_SECRET, NOTE_SECRET):
        assert forbidden.encode("utf-8") not in represented_bytes

    # LLD-06 has no Communications domain dependency in the snapshot contract,
    # and no unrestricted source-row/body field is present in any semantic row.
    serialized_keys = repr(semantic)
    assert "communication_body" not in serialized_keys
    assert "working_note" not in serialized_keys
    assert "problem_summary" not in serialized_keys
    assert "customer_account_code" not in serialized_keys
    assert "product" not in serialized_keys.lower()


def test_written_but_unverified_xlsx_is_not_completed_t032(
    initialized_database,
    tmp_path,
) -> None:
    factory = _factory(initialized_database)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_id, jobs, claim = _start_claim(
        factory,
        customer_org_id=None,
        as_of_utc=month_start + 1,
    )
    artifact = _artifact(factory, tmp_path)
    generation = SlaReportGenerationWorker(factory, artifact=artifact)
    generation.snapshot_and_seal(claim)

    with ReadSnapshot(factory) as snapshot:
        sealed = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert sealed is not None
        assert sealed.state == "ready_to_generate"
        assert sealed.snapshot_hash is not None
        snapshot_hash = sealed.snapshot_hash
        sealed_revision = sealed.revision
        assert sealed.completed_at_utc is None
        assert sealed.verified_at_utc is None

    worker = SlaReportWorkerService(factory)
    generating = worker.mark_generating(
        command_id=new_uuid4(),
        report_attempt_id=report_id,
        expected_attempt_revision=sealed_revision,
        snapshot_hash=snapshot_hash,
    )
    candidate = artifact.write_candidate(
        report_attempt_id=report_id,
        snapshot_hash=snapshot_hash,
        destination_request_token=DESTINATION_TOKEN,
    )
    assert (tmp_path / candidate).is_file()

    # A fully written XLSX alone has zero completion authority.
    with ReadSnapshot(factory) as snapshot:
        written = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert written is not None
        assert written.state == "generating"
        assert written.completed_at_utc is None
        assert written.verified_at_utc is None
        assert written.artifact_sha256 is None
        assert written.artifact_size_bytes is None

    verifying = worker.mark_verifying(
        command_id=new_uuid4(),
        report_attempt_id=report_id,
        expected_attempt_revision=int(generating["resulting_attempt_revision"]),
        snapshot_hash=snapshot_hash,
        candidate_filename=candidate,
    )
    verification = artifact.verify_candidate(
        report_attempt_id=report_id,
        snapshot_hash=snapshot_hash,
        destination_request_token=DESTINATION_TOKEN,
        candidate_filename=candidate,
    )

    # Verification itself still does not mutate completed authority.
    with ReadSnapshot(factory) as snapshot:
        verified_not_complete = ReportRepository.get_attempt(
            snapshot.connection,
            report_id,
        )
        assert verified_not_complete is not None
        assert verified_not_complete.state == "verifying"
        assert verified_not_complete.completed_at_utc is None
        assert verified_not_complete.artifact_sha256 is None

    proof = artifact.publish_verified(
        verification=verification,
        destination_request_token=DESTINATION_TOKEN,
    )
    completed = worker.complete(
        command_id=new_uuid4(),
        report_attempt_id=report_id,
        expected_attempt_revision=int(verifying["resulting_attempt_revision"]),
        snapshot_hash=snapshot_hash,
        artifact_completion=proof,
    )
    assert completed["state"] == "completed"
    jobs.complete(claim)

    with ReadSnapshot(factory) as snapshot:
        authoritative = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert authoritative is not None
        assert authoritative.state == "completed"
        assert authoritative.verified_at_utc == verification.verified_at_utc
        assert authoritative.artifact_sha256 == verification.artifact_sha256
        assert authoritative.artifact_size_bytes == verification.artifact_size_bytes
        assert authoritative.completed_at_utc is not None


def test_completed_reports_expose_no_cleanup_authority_t038(
    initialized_database,
    tmp_path,
) -> None:
    factory = _factory(initialized_database)
    report_id, _jobs, _claim, _artifact_adapter, _service_request_id = (
        _complete_real_report(factory, tmp_path)
    )

    orchestration = SlaReportOrchestrationService(factory)
    queries = ProductLineSlaReportQueryService(factory)
    forbidden_actions = {
        "cleanup",
        "delete",
        "archive",
        "finalize",
        "minimize",
        "purge",
        "expire",
    }
    for action in forbidden_actions:
        assert not hasattr(orchestration, action)
        assert not hasattr(queries, action)
        assert not hasattr(orchestration, f"{action}_report")
        assert not hasattr(queries, f"{action}_report")

    with ReadSnapshot(factory) as snapshot:
        attempt = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert attempt is not None
        assert attempt.state == "completed"
        assert ReportRepository.counts(snapshot.connection, report_id) == (1, 1, 1, 1)
        immutable_before = ReportRepository.snapshot_semantic_value(
            snapshot.connection,
            report_id,
        )
        hash_before = ReportRepository.snapshot_hash(
            snapshot.connection,
            report_id,
        )

    # Age and completed status never confer deletion authority. Every completed
    # evidence family is protected independently by migration-9 guards.
    delete_statements = (
        "DELETE FROM sla_report_member_tier_results WHERE report_attempt_id=?",
        "DELETE FROM sla_report_member_snapshots WHERE report_attempt_id=?",
        "DELETE FROM sla_report_cohort_snapshots WHERE report_attempt_id=?",
        "DELETE FROM report_section_snapshots WHERE report_attempt_id=?",
        "DELETE FROM sla_report_attempts WHERE report_attempt_id=?",
    )
    for statement in delete_statements:
        with pytest.raises(Exception):
            with UnitOfWork(factory) as uow:
                uow.connection.execute(statement, (report_id,))

    # Terminal metadata cannot be rewritten into an age/cleanup flag either.
    with pytest.raises(Exception):
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "UPDATE sla_report_attempts SET completed_at_utc=0 "
                "WHERE report_attempt_id=?",
                (report_id,),
            )

    with ReadSnapshot(factory) as snapshot:
        after = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert after is not None
        assert after.state == "completed"
        assert ReportRepository.counts(snapshot.connection, report_id) == (1, 1, 1, 1)
        assert (
            ReportRepository.snapshot_semantic_value(snapshot.connection, report_id)
            == immutable_before
        )
        assert ReportRepository.snapshot_hash(snapshot.connection, report_id) == hash_before
