from __future__ import annotations

import json

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.dispatch_service import DispatchLocationService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_dispatch_update_replay_returns_original_reference_mutation_result(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    service = DispatchLocationService(factory)
    created = service.create_standalone(
        command_id=new_uuid4(),
        name="Quito Dispatch",
        address_text="Av. Original 1\nQuito",
    )
    command_id = new_uuid4()
    first = service.update_descriptive_data(
        command_id=command_id,
        dispatch_location_id=created.dispatch_location_id,
        base_revision=1,
        name="Quito Dispatch Updated",
        address_text="Av. Original 1\nQuito",
    )
    assert first.outcome == "APPLIED"
    assert first.revision == 2
    assert first.replayed is False

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE dispatch_locations SET name='Later owner state',name_match_key='later owner state',revision=7 "
            "WHERE dispatch_location_id=?",
            (created.dispatch_location_id,),
        )

    def forbidden_owner_read(*_args, **_kwargs):
        raise AssertionError("Dispatch owner state must not be read during committed replay")

    monkeypatch.setattr(DispatchLocationService, "_active_dispatch", staticmethod(forbidden_owner_read))
    replay = service.update_descriptive_data(
        command_id=command_id,
        dispatch_location_id=created.dispatch_location_id,
        base_revision=1,
        name="Quito Dispatch Updated",
        address_text="Av. Original 1\nQuito",
    )
    assert replay.replayed is True
    assert replay.outcome == "APPLIED"
    assert replay.target_id == created.dispatch_location_id
    assert replay.revision == 2

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        row = connection.execute(
            "SELECT response_schema,response_version,response_json FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(row[:2]) == ("ReferenceMutationResultV1", 1)
        assert json.loads(str(row[2])) == {
            "outcome": "APPLIED",
            "revision": 2,
            "target_id": created.dispatch_location_id,
        }
        assert connection.execute(
            "SELECT revision FROM dispatch_locations WHERE dispatch_location_id=?",
            (created.dispatch_location_id,),
        ).fetchone()[0] == 7
    finally:
        connection.close()


def test_dispatch_no_change_replay_keeps_original_revision(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    service = DispatchLocationService(factory)
    created = service.create_standalone(
        command_id=new_uuid4(),
        name="Cuenca Dispatch",
        address_text="Address 1",
    )
    command_id = new_uuid4()
    first = service.update_descriptive_data(
        command_id=command_id,
        dispatch_location_id=created.dispatch_location_id,
        base_revision=1,
        name="Cuenca Dispatch",
        address_text="Address 1",
    )
    assert first.no_change is True
    assert first.revision == 1

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE dispatch_locations SET name='Changed later',name_match_key='changed later',revision=9 "
            "WHERE dispatch_location_id=?",
            (created.dispatch_location_id,),
        )

    monkeypatch.setattr(
        DispatchLocationService,
        "_active_dispatch",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("owner read during replay"))),
    )
    replay = service.update_descriptive_data(
        command_id=command_id,
        dispatch_location_id=created.dispatch_location_id,
        base_revision=1,
        name="Cuenca Dispatch",
        address_text="Address 1",
    )
    assert replay.replayed is True
    assert replay.no_change is True
    assert replay.revision == 1
