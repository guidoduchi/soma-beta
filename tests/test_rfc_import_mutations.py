from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.tickets.rfc_import_mutations import (
    RfcCreateFromSourceMutation,
    RfcImportMutationService,
)


class _UnusedEvidenceProvider:
    def validate_accepted_delta(self, *_args, **_kwargs):
        return "INVALID"

    def has_accepted_source_provenance(self, *_args, **_kwargs):
        return "NO"

    def source_freshness_token(self, *_args, **_kwargs):
        return "0" * 64


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_rfc_import_identity_token_and_same_uow_creation(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = RfcImportMutationService(_UnusedEvidenceProvider())
    rfc_no = "NC20260916000101"

    with ReadSnapshot(factory) as snapshot:
        base_token = service.source_identity_base_token(snapshot.connection, rfc_no)

    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        result = service.create_or_adopt_from_source(
            uow,
            RfcCreateFromSourceMutation(
                rfc_no=rfc_no,
                base_state_token=base_token,
                accepted_command_id=command_id,
            ),
        )
        row = uow.connection.execute(
            "SELECT rfc_no,customer_org_id,local_archive_state,revision FROM rfcs WHERE rfc_id=?",
            (result.rfc_id,),
        ).fetchone()
        assert row is not None
        assert tuple(row) == (rfc_no, None, "active", 1)
        assert result.result_refs == (("rfc", result.rfc_id),)
        assert len(result.audit_events) == 1
        audit = result.audit_events[0]
        assert audit.action_type == "ticket.rfc.identity_created_or_adopted"
        assert audit.command_id == command_id
        assert audit.payload["creation_context"] == "accepted_source_adoption"

    with ReadSnapshot(factory) as snapshot:
        changed_token = service.source_identity_base_token(snapshot.connection, rfc_no)
    assert changed_token != base_token


def test_rfc_import_identity_creation_fails_closed_when_base_state_changes(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = RfcImportMutationService(_UnusedEvidenceProvider())
    rfc_no = "NC20260916000102"

    with ReadSnapshot(factory) as snapshot:
        stale_token = service.source_identity_base_token(snapshot.connection, rfc_no)

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?,?,NULL,'active',1,1,1)",
            (new_uuid4(), rfc_no),
        )

    with UnitOfWork(factory) as uow:
        with pytest.raises(SomaError) as excinfo:
            service.create_or_adopt_from_source(
                uow,
                RfcCreateFromSourceMutation(
                    rfc_no=rfc_no,
                    base_state_token=stale_token,
                    accepted_command_id=new_uuid4(),
                ),
            )
        assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
