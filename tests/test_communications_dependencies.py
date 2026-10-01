from __future__ import annotations

import sqlite3

import pytest

from soma.communications.services.dependencies import InventoryCommunicationDependencyProvider
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from test_communications_housekeeping import seed
from test_communications_queries import add_link


def test_inventory_dependency_predicate_preserves_closed_history_and_owner_scope(communication_database):
    path, factory = communication_database
    comm = seed(path)
    target, other = new_uuid4(), new_uuid4()
    provider = InventoryCommunicationDependencyProvider()
    with ReadSnapshot(factory) as reader:
        assert provider.classify_inventory_hard_delete_dependency(reader, "spare_request", target) == "CLEAR"
    with sqlite3.connect(path) as connection:
        link = add_link(connection, comm, target, state="CLOSED")
        connection.execute("UPDATE communication_links SET target_type='SPARE_REQUEST' WHERE communication_link_id=?", (link,))
    for read_context in (ReadSnapshot, UnitOfWork):
        with read_context(factory) as reader:
            assert provider.classify_inventory_hard_delete_dependency(reader, "spare_request", target) == "BLOCKED"
            assert provider.classify_inventory_hard_delete_dependency(reader, "SPARE_REQUEST", target) == "BLOCKED"
            assert provider.classify_inventory_hard_delete_dependency(reader, "FAULT_TAG", target) == "CLEAR"
            assert provider.classify_inventory_hard_delete_dependency(reader, "SPARE_REQUEST", other) == "CLEAR"
    with pytest.raises(ValidationError):
        provider.classify_inventory_hard_delete_dependency(None, "RMA", target)


def test_exported_draft_blocks_inventory_hard_delete_without_counting_as_a_message(communication_database, tmp_path):
    from soma.communications.services.drafts import MsgDraftService
    from test_communications_drafts import payload, spare_origin
    from test_communications_identity_providers import providers
    _, factory = communication_database
    origin = spare_origin(factory)
    target = origin[2]
    MsgDraftService(factory, providers()).generate_msg_draft(payload(origin, tmp_path / "dependency.msg"))
    with ReadSnapshot(factory) as reader:
        assert InventoryCommunicationDependencyProvider().classify_inventory_hard_delete_dependency(reader, "spare_request", target) == "BLOCKED"
        assert reader.connection.execute("SELECT count(*) FROM communications").fetchone()[0] == 0
