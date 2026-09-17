from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.providers.rfc_source_evidence import TicketImportRfcSourceEvidenceProvider
from soma.tickets.rfc_import_mutations import (
    RfcImportMutationService,
    RfcSrLinkReviewMutation,
)
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _service() -> RfcImportMutationService:
    return RfcImportMutationService(TicketImportRfcSourceEvidenceProvider())


def _seed_rfc(factory, rfc_no: str) -> str:
    rfc_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?,?,NULL,'active',1,1,1)",
            (rfc_id, rfc_no),
        )
    return rfc_id


def test_import_owner_links_exact_sr_to_current_governing_rfc_in_same_uow(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="45678901",
    )
    rfc_id = _seed_rfc(factory, "NC20260917000021")
    service = _service()
    with ReadSnapshot(factory) as snapshot:
        context = service.sr_link_candidate_context(snapshot.connection, sr.service_request_id, rfc_id)
    assert context.duplicate_active is False
    assert context.risk_class == "medium"

    with UnitOfWork(factory) as uow:
        result = service.link_sr_from_review(
            uow,
            RfcSrLinkReviewMutation(
                service_request_id=sr.service_request_id,
                requested_rfc_id=rfc_id,
                base_state_token=context.base_state_token,
                accepted_command_id=new_uuid4(),
                reason_category="test_reviewed_import_link",
            ),
        )
        assert uow.connection.in_transaction

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT service_request_id,rfc_id,link_state FROM sr_rfc_links WHERE sr_rfc_link_id=?",
            (result.relationship_id,),
        ).fetchone()
        assert tuple(row) == (sr.service_request_id, rfc_id, "active")
        sr_revision = snapshot.connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()
        rfc_revision = snapshot.connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
    assert int(sr_revision[0]) == context.sr_revision + 1
    assert int(rfc_revision[0]) == context.rfc_revision + 1
    assert result.service_request_revision == context.sr_revision + 1
    assert result.rfc_revision == context.rfc_revision + 1


def test_import_owner_rejects_stale_sr_link_base_token(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="56789012",
    )
    rfc_id = _seed_rfc(factory, "NC20260917000022")
    service = _service()
    with ReadSnapshot(factory) as snapshot:
        context = service.sr_link_candidate_context(snapshot.connection, sr.service_request_id, rfc_id)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE rfcs SET revision=revision+1 WHERE rfc_id=?",
            (rfc_id,),
        )

    with pytest.raises(SomaError) as exc_info:
        with UnitOfWork(factory) as uow:
            service.link_sr_from_review(
                uow,
                RfcSrLinkReviewMutation(
                    service_request_id=sr.service_request_id,
                    requested_rfc_id=rfc_id,
                    base_state_token=context.base_state_token,
                    accepted_command_id=new_uuid4(),
                ),
            )
    assert exc_info.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        count = snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=? AND link_state='active'",
            (sr.service_request_id, rfc_id),
        ).fetchone()
    assert int(count[0]) == 0
