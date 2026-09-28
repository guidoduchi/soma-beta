from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.application.dispatch_service import DispatchLocationService
from soma.reference.queries.matching import ReferenceMatchingQueries


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _set_profile(factory, value: str) -> None:
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE reference_metadata SET matching_profile_id=? WHERE singleton_guard=1",
            (value,),
        )


def test_unsupported_persisted_matching_profile_blocks_matching_read_and_write(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customers.create_customer_organization(
        command_id=new_uuid4(),
        name="Existing Customer",
    )

    _set_profile(factory, "UNICODE_MATCH_V2")

    with pytest.raises(SomaError) as query_error:
        ReferenceMatchingQueries(factory).match_customer_organization(
            raw_name="Existing Customer",
        )
    assert query_error.value.code == "MATCH_PROFILE_UNSUPPORTED"

    command_id = new_uuid4()
    with pytest.raises(ValidationError, match="migration/reindex"):
        customers.create_customer_organization(
            command_id=command_id,
            name="Blocked Customer",
        )

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute(
            "SELECT count(*) FROM customer_organizations WHERE name='Blocked Customer'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_site_dispatch_shared_uow_rejects_unsupported_matching_profile_atomically(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _set_profile(factory, "UNICODE_MATCH_V2")
    parent_command = new_uuid4()

    with pytest.raises(ValidationError, match="migration/reindex"):
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "INSERT INTO command_receipts("
                "command_id,command_type,request_hash,target_type,target_id,"
                "committed_at_utc,result_type,result_id"
                ") VALUES (?, 'CreateSite', ?, 'site', NULL, 1, NULL, NULL)",
                (parent_command, "0" * 64),
            )
            DispatchLocationService.create_dedicated_for_site(
                uow,
                parent_command_id=parent_command,
                name="Blocked Site Dispatch",
                precomputed_match_key="blocked site dispatch",
            )

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute(
            "SELECT count(*) FROM dispatch_locations WHERE name='Blocked Site Dispatch'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (parent_command,),
        ).fetchone()[0] == 0
    finally:
        connection.close()
