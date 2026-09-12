from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.relationships import ServiceRequestRfcRelationshipService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _new_rfc(factory, serial: int):
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{serial:014d}",
        creation_context="manual",
    )


def _read(factory):
    return factory.open_authoritative(read_only=True, require_wal=True)


def _insert_source_projection(factory, rfc_id: str) -> dict[str, object]:
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfc_current_source_projection("
            "rfc_id,summary_text,summary_evidence_id,external_created_at_utc,external_created_evidence_id,"
            "status_text,status_class,status_authority,status_evidence_id,last_update_utc,last_update_evidence_id,revision"
            ") VALUES (?, 'Maintenance window', 'summary-evidence', 1700000000, 'created-evidence', "
            "'Implement', 'implement_eligible', 'enhanced_rfc', 'status-evidence', 1700003600, 'update-evidence', 3)",
            (rfc_id,),
        )
    return {
        "summary_text": "Maintenance window",
        "summary_evidence_id": "summary-evidence",
        "external_created_at_utc": 1700000000,
        "external_created_evidence_id": "created-evidence",
        "creator_text": None,
        "creator_evidence_id": None,
        "customer_account_number_text": None,
        "customer_account_number_evidence_id": None,
        "customer_account_name_text": None,
        "customer_account_name_evidence_id": None,
        "severity_text": None,
        "severity_evidence_id": None,
        "status_text": "Implement",
        "status_class": "implement_eligible",
        "status_authority": "enhanced_rfc",
        "status_evidence_id": "status-evidence",
        "terminal_epoch_id": None,
        "owner_external_id_text": None,
        "owner_external_id_evidence_id": None,
        "owner_name_text": None,
        "owner_name_evidence_id": None,
        "l1_handler_name_text": None,
        "l1_handler_name_evidence_id": None,
        "l2_handler_name_text": None,
        "l2_handler_name_evidence_id": None,
        "last_update_utc": 1700003600,
        "last_update_evidence_id": "update-evidence",
        "revision": 3,
    }


def test_rfc_import_source_token_uses_exact_closed_source_authority_and_ignores_local_link_revision(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory, 8101)

    connection = _read(factory)
    try:
        identity = RfcImportReader.get_by_number(connection, rfc.rfc_no)
        assert identity == {
            "rfc_id": rfc.rfc_id,
            "rfc_no": rfc.rfc_no,
            "customer_org_id": None,
            "local_archive_state": "active",
            "revision": 1,
        }
        empty_token = RfcImportReader.source_acceptance_base_token(connection, rfc.rfc_id)
    finally:
        connection.close()

    assert empty_token == sha256_canonical_json(
        {
            "schema": "SOMA_RFC_SOURCE_ACCEPTANCE_BASE_V1",
            "rfc_id": rfc.rfc_id,
            "rfc_no": rfc.rfc_no,
            "source_projection": None,
        }
    )

    expected_projection = _insert_source_projection(factory, rfc.rfc_id)
    connection = _read(factory)
    try:
        projection = RfcImportReader.current_source_projection(connection, rfc.rfc_id)
        assert projection == {"rfc_id": rfc.rfc_id, **expected_projection}
        source_token = RfcImportReader.source_acceptance_base_token(connection, rfc.rfc_id)
    finally:
        connection.close()

    assert source_token == sha256_canonical_json(
        {
            "schema": "SOMA_RFC_SOURCE_ACCEPTANCE_BASE_V1",
            "rfc_id": rfc.rfc_id,
            "rfc_no": rfc.rfc_no,
            "source_projection": expected_projection,
        }
    )
    assert source_token != empty_token

    sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    relationships = ServiceRequestRfcRelationshipService(factory)
    preview = relationships.preview_link(service_request_id=sr.service_request_id, rfc_id=rfc.rfc_id)
    linked = relationships.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=rfc.rfc_id,
        sr_base_revision=preview.sr_revision,
        rfc_base_revision=preview.rfc_revision,
        review_fingerprint=preview.review_fingerprint,
    )
    assert linked.outcome == "APPLIED"

    connection = _read(factory)
    try:
        state = RfcImportReader.current_link_state(connection, sr.service_request_id, rfc.rfc_id)
        assert state["state"] == "ACTIVE"
        assert isinstance(state["sr_rfc_link_id"], str)
        assert RfcImportReader.source_acceptance_base_token(connection, rfc.rfc_id) == source_token
    finally:
        connection.close()

    unlinked = relationships.unlink(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        root_rfc_id=rfc.rfc_id,
        sr_base_revision=linked.revision,
        rfc_base_revision=2,
        reason_category="reviewed_unlink",
    )
    assert unlinked.outcome == "APPLIED"

    connection = _read(factory)
    try:
        assert RfcImportReader.current_link_state(connection, sr.service_request_id, rfc.rfc_id) == {
            "state": "ABSENT",
            "sr_rfc_link_id": None,
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=? AND link_state='unlinked'",
            (sr.service_request_id, rfc.rfc_id),
        ).fetchone()[0] == 1
        assert RfcImportReader.source_acceptance_base_token(connection, rfc.rfc_id) == source_token
    finally:
        connection.close()


def test_rfc_source_projection_change_changes_source_acceptance_token(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory, 8102)
    _insert_source_projection(factory, rfc.rfc_id)

    connection = _read(factory)
    try:
        before = RfcImportReader.source_acceptance_base_token(connection, rfc.rfc_id)
    finally:
        connection.close()

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE rfc_current_source_projection SET summary_text='Changed maintenance',"
            "summary_evidence_id='summary-evidence-2',revision=revision+1 WHERE rfc_id=?",
            (rfc.rfc_id,),
        )

    connection = _read(factory)
    try:
        after = RfcImportReader.source_acceptance_base_token(connection, rfc.rfc_id)
    finally:
        connection.close()
    assert after != before


def test_rfc_import_reader_resolves_governing_root_and_rejects_subordinate_link_lookup(initialized_database) -> None:
    factory = _factory(initialized_database)
    root = _new_rfc(factory, 8103)
    child = _new_rfc(factory, 8104)

    connection = _read(factory)
    try:
        child_token_before = RfcImportReader.source_acceptance_base_token(connection, child.rfc_id)
    finally:
        connection.close()

    RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={root.rfc_id: root.revision, child.rfc_id: child.revision},
        reason_category="manual_review",
    )

    sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    connection = _read(factory)
    try:
        assert RfcImportReader.governing_root(connection, root.rfc_id) == root.rfc_id
        assert RfcImportReader.governing_root(connection, child.rfc_id) == root.rfc_id
        assert RfcImportReader.source_acceptance_base_token(connection, child.rfc_id) == child_token_before
        with pytest.raises(IntegrityFailure):
            RfcImportReader.current_link_state(connection, sr.service_request_id, child.rfc_id)
    finally:
        connection.close()


def test_rfc_import_reader_missing_identity_fails_without_guessing(initialized_database) -> None:
    factory = _factory(initialized_database)
    missing_id = new_uuid4()
    connection = _read(factory)
    try:
        with pytest.raises(SomaError) as source_exc:
            RfcImportReader.source_acceptance_base_token(connection, missing_id)
        assert source_exc.value.code == "NOT_FOUND"
        with pytest.raises(SomaError) as root_exc:
            RfcImportReader.governing_root(connection, missing_id)
        assert root_exc.value.code == "NOT_FOUND"
        assert RfcImportReader.get_by_number(connection, "NC99999999999999") is None
    finally:
        connection.close()
