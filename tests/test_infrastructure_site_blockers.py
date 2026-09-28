from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.infrastructure.queries.core import InfrastructureQueries
from soma.infrastructure.services.core import InfrastructureService
from soma.reference.application.customer_service import CustomerReferenceService


def test_site_blockers_fill_pages_across_provider_batches(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(), name="Blocker customer").customer_org_id
    blockers = sorted(new_uuid4() for _ in range(205))

    class Provider:
        def __init__(self, identities):
            self.identities = identities

        def count_blockers(self, snapshot, site_id):
            return len(self.identities)

        def list_blockers(self, snapshot, site_id, cursor, limit):
            eligible = [identity for identity in self.identities if cursor is None or identity > cursor]
            page = eligible[:limit]
            return {"blockers": page, "continuation": page[-1] if len(eligible) > limit else None}

    service = InfrastructureService(factory, site_dependencies=(Provider(blockers), Provider([]), Provider([])))
    site_id = service.execute("CreateSite", command_id=new_uuid4(), payload={
        "customer_org_id": customer, "name": "Site", "address_text": "1 Main Street",
    }).response["target"]["id"]
    queries = InfrastructureQueries(service)
    collected = []
    cursor = None
    while True:
        result = queries.execute("SiteArchiveBlockerQuery", {
            "site_id": site_id, "limit": 100, **({"cursor": cursor} if cursor else {}),
        })
        assert result["exact_count"] == 205
        assert not result["indeterminate"]
        collected.extend(row["blocker_id"] for row in result["items"])
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert collected == blockers


def test_site_blockers_full_physical_page_has_continuation(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(), name="Physical blocker customer").customer_org_id

    class EmptyProvider:
        def count_blockers(self, snapshot, site_id):
            return 0

        def list_blockers(self, snapshot, site_id, cursor, limit):
            return {"blockers": [], "continuation": None}

    service = InfrastructureService(factory, site_dependencies=(EmptyProvider(), EmptyProvider(), EmptyProvider()))
    command_id = new_uuid4()
    site_id = service.execute("CreateSite", command_id=command_id, payload={
        "customer_org_id": customer, "name": "Site", "address_text": "2 Main Street",
    }).response["target"]["id"]
    room_ids = sorted(new_uuid4() for _ in range(501))
    with UnitOfWork(factory) as uow:
        uow.connection.executemany(
            "INSERT INTO rooms (room_id,site_id,name,name_match_key,lifecycle_state,"
            "created_at_utc,created_command_id,last_command_id) VALUES (?,?,?,?,?,?,?,?)",
            [(room_id, site_id, "Room", "room", "active", 1, command_id, command_id)
             for room_id in room_ids],
        )
    queries = InfrastructureQueries(service)
    first = queries.execute("SiteArchiveBlockerQuery", {"site_id": site_id, "limit": 500})
    assert len(first["items"]) == 500
    assert first["next_cursor"] is not None
    second = queries.execute("SiteArchiveBlockerQuery", {
        "site_id": site_id, "limit": 500, "cursor": first["next_cursor"],
    })
    assert second["next_cursor"] is None
    assert [row["blocker_id"] for row in first["items"] + second["items"]] == room_ids
