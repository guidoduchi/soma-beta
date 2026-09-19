from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta
from soma.tickets.rfc_wfm_provisional import (
    RfcWfmProvisionalEligibilityMutation,
    RfcWfmProvisionalEligibilityService,
)
from soma.tickets.rfcs import RfcService


class _AcceptAllEvidenceProvider:
    def validate_accepted_delta(self, uow, rfc_id, delta, evidence_id):
        assert evidence_id == delta.evidence_id
        return "VALID"

    def has_accepted_source_provenance(self, reader, rfc_id):
        return "YES"

    def source_freshness_token(self, uow, rfc_id):
        return "0" * 64


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _insert_outer_receipt(uow: UnitOfWork, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "a" * 64, new_uuid4()),
    )


def _implement_delta() -> RfcAcceptedFieldDelta:
    return RfcAcceptedFieldDelta(
        field_key="status",
        value_kind="controlled",
        value="Implement",
        evidence_id=new_uuid4(),
        status_class="implement_eligible",
        status_authority="wfm_provisional",
    )


def test_provisional_eligibility_token_survives_missing_to_active_identity_creation(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_no = "NC00000000000701"
    with ReadSnapshot(factory) as snapshot:
        before = RfcWfmProvisionalEligibilityService.base_state_token(snapshot.connection, rfc_no)

    RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )

    with ReadSnapshot(factory) as snapshot:
        after = RfcWfmProvisionalEligibilityService.base_state_token(snapshot.connection, rfc_no)
    assert after == before


def test_accept_provisional_eligibility_after_sibling_identity_creation(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_no = "NC00000000000702"
    with ReadSnapshot(factory) as snapshot:
        base = RfcWfmProvisionalEligibilityService.base_state_token(snapshot.connection, rfc_no)

    created = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id)
        result = RfcWfmProvisionalEligibilityService(_AcceptAllEvidenceProvider()).accept_provisional_implement_eligibility_from_wfm(
            uow,
            RfcWfmProvisionalEligibilityMutation(
                rfc_no=rfc_no,
                source_status_delta=_implement_delta(),
                base_state_token=base,
                accepted_command_id=command_id,
                review_fingerprint="b" * 64,
            ),
        )
        assert result.rfc_id == created.rfc_id
        assert result.projection_result.no_change is False

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT status_text,status_class,status_authority FROM rfc_current_source_projection WHERE rfc_id=?",
            (created.rfc_id,),
        ).fetchone()
        assert tuple(row) == ("Implement", "implement_eligible", "wfm_provisional")


def test_enhanced_rfc_status_blocks_wfm_provisional_eligibility(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_no = "NC00000000000703"
    created = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfc_current_source_projection("
            "rfc_id,status_text,status_class,status_authority,status_evidence_id,terminal_epoch_id,revision"
            ") VALUES (?,'Implement','implement_eligible','enhanced_rfc',?,NULL,1)",
            (created.rfc_id, new_uuid4()),
        )
    with ReadSnapshot(factory) as snapshot:
        base = RfcWfmProvisionalEligibilityService.base_state_token(snapshot.connection, rfc_no)

    command_id = new_uuid4()
    with pytest.raises(SomaError) as exc_info:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id)
            RfcWfmProvisionalEligibilityService(_AcceptAllEvidenceProvider()).accept_provisional_implement_eligibility_from_wfm(
                uow,
                RfcWfmProvisionalEligibilityMutation(
                    rfc_no=rfc_no,
                    source_status_delta=_implement_delta(),
                    base_state_token=base,
                    accepted_command_id=command_id,
                    review_fingerprint="c" * 64,
                ),
            )
    assert exc_info.value.code == "IMPORT_PROPOSAL_STALE"
