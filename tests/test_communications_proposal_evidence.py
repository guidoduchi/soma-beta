from __future__ import annotations

import sqlite3

import pytest

from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.domain.proposals import proposal_fingerprint, source_fingerprint
from soma.communications.repositories.sources import one
from soma.communications.services.proposal_evidence import CommunicationProposalEvidenceProvider
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.inventory.services.participants import InventoryProposalTargetService

from test_communications_housekeeping import seed
from test_communications_identity_providers import providers
from test_inventory_proposal_target_participant import _draft


def prepare(path, factory):
    target, draft = _draft(factory)
    comm = seed(path, pending=False)
    identity = new_uuid4()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE communications SET direction='SENT' WHERE communication_id=?", (comm,))
    with UnitOfWork(factory) as uow:
        message = one(uow, "SELECT * FROM communications WHERE communication_id=?", (comm,))
        payload = CommunicationProposalContractRegistry().validate("COMM_INVENTORY_SUBMISSION_V1", 1, "SPARE_REQUEST", {
            "schema": "COMM_INVENTORY_SUBMISSION_V1", "facts": {"schema": "INVENTORY_PROPOSAL_TARGET_V1",
            "expected_draft_fingerprint": draft, "effective_submission_at_utc": None},
        })
        source = source_fingerprint(message, 1)
        exact = proposal_fingerprint(source, target, 1, payload)
        uow.connection.execute(
            "INSERT INTO communication_proposals(communication_proposal_id,communication_id,target_type,target_id,target_revision,"
            "proposal_contract_id,proposal_contract_version,payload_json,source_fingerprint,proposal_fingerprint,state,revision,created_at_utc) "
            "VALUES (?,?,'SPARE_REQUEST',?,1,?,1,?,?,?,'PENDING',1,1)",
            (identity, comm, target, payload.contract_id, payload.canonical_json, source, exact),
        )
        uow.connection.execute("INSERT INTO communication_protection_holds VALUES (?,?, 'PROPOSAL',?,'ACTIVE',1,NULL)", (new_uuid4(), comm, identity))
    return comm, identity, exact


def test_lld09_a033_owner_evidence_checks_source_target_and_typed_fact_freshness(communication_database):
    path, factory = communication_database
    comm, identity, exact = prepare(path, factory)
    provider = CommunicationProposalEvidenceProvider(providers(), InventoryProposalTargetService())
    with UnitOfWork(factory) as uow:
        result = provider.get_for_owner_command(uow, identity, 1, exact)
        assert isinstance(result, dict) and result["communication_id"] == comm
        assert set(result) == {"proposal_id", "proposal_revision", "communication_id", "source_scope_id", "target_type", "target_id",
                               "target_revision", "proposal_contract_id", "proposal_contract_version", "payload", "source_fingerprint", "proposal_fingerprint"}
        assert provider.get_for_owner_command(uow, identity, 2, exact) == "STALE"
        assert provider.get_for_owner_command(uow, identity, 1, 'd' * 64) == "STALE"
        uow.connection.execute("UPDATE communication_source_scopes SET revision=2 WHERE source_scope_id=?", (result["source_scope_id"],))
        assert provider.get_for_owner_command(uow, identity, 1, exact) == "STALE"
    with pytest.raises(ValidationError):
        provider.get_for_owner_command(None, identity, True, exact)


def test_evidence_does_not_read_or_return_message_content_and_missing_owner_fails_closed(communication_database):
    path, factory = communication_database
    comm, identity, exact = prepare(path, factory)
    provider = CommunicationProposalEvidenceProvider(providers())
    with UnitOfWork(factory) as uow:
        statements = []
        uow.connection.set_trace_callback(statements.append)
        assert provider.get_for_owner_command(uow, identity, 1, exact) == "INDETERMINATE"
        assert not any("SELECT * FROM communications " in statement or "body_text" in statement for statement in statements)
        uow.connection.set_trace_callback(None)
        with pytest.raises(sqlite3.IntegrityError):
            uow.connection.execute("UPDATE communication_proposals SET payload_json='{}' WHERE communication_proposal_id=?", (identity,))
        uow.connection.execute("UPDATE communications SET content_revision=2 WHERE communication_id=?", (comm,))
        assert provider.get_for_owner_command(uow, identity, 1, exact) == "STALE"
