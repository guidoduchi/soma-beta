from __future__ import annotations

import json

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.dispatch_service import DispatchLocationService
from soma.reference.application.profile_service import LocalUserProfileService
from soma.reference.application.settings_service import SettingService
from soma.reference.domain.settings import SettingDefinition, SettingDefinitionRegistry


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _setting_registry() -> SettingDefinitionRegistry:
    registry = SettingDefinitionRegistry()

    def validate(value):
        if not isinstance(value, dict) or set(value) != {"enabled"} or type(value["enabled"]) is not bool:
            raise ValidationError("test setting must be {enabled: boolean}")
        return value

    registry.register(
        SettingDefinition(
            setting_key="test.replay.enabled",
            semantic_owner="tests",
            contract_name="ReplaySettingV1",
            current_version=1,
            default_provider=lambda: {"enabled": False},
            validator=validate,
            semantic_equals=lambda left, right: left == right,
            max_utf8_bytes=256,
            max_depth=2,
            max_collection_items=4,
        )
    )
    return registry


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


def test_setting_write_replay_returns_original_setting_value_without_owner_reads(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    service = SettingService(factory, _setting_registry())
    command_id = new_uuid4()
    first = service.write(
        command_id=command_id,
        setting_key="test.replay.enabled",
        base_revision=None,
        value={"enabled": True},
    )
    assert first.value == {"enabled": True}
    assert first.revision == 1
    assert first.source == "PERSISTED"
    assert first.semantic_owner == "tests"
    assert first.replayed is False
    assert first.no_change is False

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE setting_values SET value_json='{""enabled"":false}',revision=9 WHERE setting_key='test.replay.enabled'"
        )

    monkeypatch.setattr(
        SettingService,
        "_parse_persisted",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("setting owner read during replay"))),
    )
    replay = service.write(
        command_id=command_id,
        setting_key="test.replay.enabled",
        base_revision=None,
        value={"enabled": True},
    )
    assert replay.replayed is True
    assert replay.no_change is False
    assert replay.value == {"enabled": True}
    assert replay.revision == 1

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        row = connection.execute(
            "SELECT response_schema,response_version,response_json FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(row[:2]) == ("SettingValueV1", 1)
        assert json.loads(str(row[2])) == {
            "contract_name": "ReplaySettingV1",
            "contract_version": 1,
            "revision": 1,
            "semantic_owner": "tests",
            "setting_key": "test.replay.enabled",
            "source": "PERSISTED",
            "value": {"enabled": True},
        }
    finally:
        connection.close()


def test_setting_no_change_replay_keeps_original_value_and_revision(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = SettingService(factory, _setting_registry())
    service.write(
        command_id=new_uuid4(),
        setting_key="test.replay.enabled",
        base_revision=None,
        value={"enabled": True},
    )
    command_id = new_uuid4()
    first = service.write(
        command_id=command_id,
        setting_key="test.replay.enabled",
        base_revision=1,
        value={"enabled": True},
    )
    assert first.no_change is True
    assert first.revision == 1
    assert first.value == {"enabled": True}

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE setting_values SET value_json='{""enabled"":false}',revision=5 WHERE setting_key='test.replay.enabled'"
        )

    replay = service.write(
        command_id=command_id,
        setting_key="test.replay.enabled",
        base_revision=1,
        value={"enabled": True},
    )
    assert replay.replayed is True
    assert replay.no_change is True
    assert replay.revision == 1
    assert replay.value == {"enabled": True}


def test_local_profile_replay_returns_original_profile_without_owner_reads(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = LocalUserProfileService(factory)
    parent_command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
            "VALUES (?, 'FirstRunSetup', ?, 'local_user_profile', NULL, 0, NULL, NULL)",
            (parent_command_id, "0" * 64),
        )
        profile_id = service.ensure_singleton_local_administrator(uow, parent_command_id=parent_command_id)

    command_id = new_uuid4()
    first = service.update_display_name(
        command_id=command_id,
        base_revision=1,
        display_name="Operations Administrator",
        actor_id=profile_id,
    )
    assert first.display_name == "Operations Administrator"
    assert first.revision == 2
    assert first.replayed is False
    assert first.no_change is False

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE local_user_profiles SET display_name='Later owner state',revision=8 WHERE local_user_profile_id=?",
            (profile_id,),
        )

    replay = service.update_display_name(
        command_id=command_id,
        base_revision=1,
        display_name="Operations Administrator",
        actor_id=profile_id,
    )
    assert replay.replayed is True
    assert replay.no_change is False
    assert replay.local_user_profile_id == profile_id
    assert replay.display_name == "Operations Administrator"
    assert replay.revision == 2

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        row = connection.execute(
            "SELECT response_schema,response_version,response_json FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(row[:2]) == ("LocalUserProfileV1", 1)
        assert json.loads(str(row[2])) == {
            "display_name": "Operations Administrator",
            "local_user_profile_id": profile_id,
            "revision": 2,
        }
        assert connection.execute(
            "SELECT display_name,revision FROM local_user_profiles WHERE local_user_profile_id=?",
            (profile_id,),
        ).fetchone() == ("Later owner state", 8)
    finally:
        connection.close()
