from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.dispatch_service import DispatchLocationService
from soma.reference.application.lifecycle_service import ReferenceLifecycleService
from soma.reference.application.profile_service import LocalUserProfileService
from soma.reference.application.settings_service import SettingService
from soma.reference.domain.dependencies import (
    DependencyBlocker,
    DependencyGuard,
    DependencyPage,
    ReferenceDependencyRegistry,
    ReferenceTarget,
)
from soma.reference.domain.settings import SettingDefinition, SettingDefinitionRegistry


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _read(initialized_database):
    return _factory(initialized_database).open_authoritative(read_only=True, require_wal=True)


def _parent_receipt(uow: UnitOfWork, command_id: str, command_type: str = "ParentCoordinator") -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?, ?, ?, 'coordinator', NULL, ?, NULL, NULL)",
        (command_id, command_type, "0" * 64, utc_epoch_seconds()),
    )


def test_dispatch_standalone_is_customer_neutral(initialized_database) -> None:
    service = DispatchLocationService(_factory(initialized_database))
    created = service.create_standalone(
        command_id=new_uuid4(), name="Quito Spare Warehouse", address_text="Av. Example 123\r\nQuito"
    )
    connection = _read(initialized_database)
    try:
        row = connection.execute(
            "SELECT address_mode,standalone_address_text,lifecycle_state,revision FROM dispatch_locations WHERE dispatch_location_id=?",
            (created.dispatch_location_id,),
        ).fetchone()
        assert tuple(row) == ("standalone", "Av. Example 123\nQuito", "active", 1)
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(dispatch_locations)").fetchall()}
        assert "customer_org_id" not in columns
        assert "site_id" not in columns
    finally:
        connection.close()


def test_site_derived_dispatch_participant_is_atomic_and_has_no_address(initialized_database) -> None:
    factory = _factory(initialized_database)
    rolled_back_command = new_uuid4()
    with pytest.raises(RuntimeError):
        with UnitOfWork(factory) as uow:
            _parent_receipt(uow, rolled_back_command, "CreateSite")
            DispatchLocationService.create_dedicated_for_site(
                uow,
                parent_command_id=rolled_back_command,
                name="Rollback Site Dispatch",
                precomputed_match_key="rollback site dispatch",
            )
            raise RuntimeError("simulate Site relation failure")
    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT count(*) FROM dispatch_locations WHERE name='Rollback Site Dispatch'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (rolled_back_command,)
        ).fetchone()[0] == 0
    finally:
        connection.close()

    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _parent_receipt(uow, command_id, "CreateSite")
        dispatch_id = DispatchLocationService.create_dedicated_for_site(
            uow,
            parent_command_id=command_id,
            name="Site Dispatch",
            precomputed_match_key="site dispatch",
        )
    connection = _read(initialized_database)
    try:
        assert tuple(
            connection.execute(
                "SELECT address_mode,standalone_address_text FROM dispatch_locations WHERE dispatch_location_id=?",
                (dispatch_id,),
            ).fetchone()
        ) == ("site_derived", None)
    finally:
        connection.close()


@dataclass
class FakeDependencyValidator:
    validator_id: str
    archive_state: str = "CLEAR"
    reactivate_state: str = "CLEAR"
    archive_blockers: tuple[str, ...] = ()
    reactivate_blockers: tuple[str, ...] = ()

    def guard_archive(self, uow, target: ReferenceTarget) -> DependencyGuard:
        return DependencyGuard(self.archive_state, "fake_archive_blocker" if self.archive_state != "CLEAR" else None)

    def guard_reactivate(self, uow, target: ReferenceTarget) -> DependencyGuard:
        return DependencyGuard(self.reactivate_state, "fake_reactivate_blocker" if self.reactivate_state != "CLEAR" else None)

    @staticmethod
    def _page(values: tuple[str, ...], cursor: str | None, limit: int) -> DependencyPage:
        ordered = sorted(value for value in values if cursor is None or value > cursor)
        visible = ordered[:limit]
        continuation = visible[-1] if len(ordered) > limit and visible else None
        return DependencyPage(tuple(DependencyBlocker(value, "blocked") for value in visible), continuation)

    def count_archive_blockers(self, snapshot, target: ReferenceTarget) -> int:
        return len(self.archive_blockers)

    def list_archive_blockers(self, snapshot, target: ReferenceTarget, cursor: str | None, limit: int) -> DependencyPage:
        return self._page(self.archive_blockers, cursor, limit)

    def count_reactivation_blockers(self, snapshot, target: ReferenceTarget) -> int:
        return len(self.reactivate_blockers)

    def list_reactivation_blockers(self, snapshot, target: ReferenceTarget, cursor: str | None, limit: int) -> DependencyPage:
        return self._page(self.reactivate_blockers, cursor, limit)


def test_archive_blocked_or_indeterminate_commits_nothing(initialized_database) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(command_id=new_uuid4(), name="Blocked Contact")
    registry = ReferenceDependencyRegistry()
    registry.register(FakeDependencyValidator("inventory", archive_state="BLOCKED", archive_blockers=("sr7-1",)))
    service = ReferenceLifecycleService(factory, registry)
    command_id = new_uuid4()
    with pytest.raises(SomaError) as exc:
        service.archive_reference(
            command_id=command_id,
            target_type="contact",
            target_id=contact.contact_id,
            base_revision=1,
            reason_category="operator_archive",
        )
    assert exc.value.code == "ARCHIVE_BLOCKED"
    connection = _read(initialized_database)
    try:
        assert tuple(connection.execute(
            "SELECT lifecycle_state,revision FROM contacts WHERE contact_id=?", (contact.contact_id,)
        ).fetchone()) == ("active", 1)
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM reference_lifecycle_events WHERE target_id=? AND event_type='archived'", (contact.contact_id,)
        ).fetchone()[0] == 0
    finally:
        connection.close()

    registry2 = ReferenceDependencyRegistry()
    registry2.register(FakeDependencyValidator("tickets", archive_state="INDETERMINATE"))
    with pytest.raises(SomaError) as exc2:
        ReferenceLifecycleService(factory, registry2).archive_reference(
            command_id=new_uuid4(),
            target_type="contact",
            target_id=contact.contact_id,
            base_revision=1,
            reason_category="operator_archive",
        )
    assert exc2.value.code == "DEPENDENCY_VALIDATION_FAILED"


def test_archive_preview_exact_count_is_paged_and_read_only(initialized_database) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(command_id=new_uuid4(), name="Preview Contact")
    registry = ReferenceDependencyRegistry()
    registry.register(FakeDependencyValidator("a-owner", archive_blockers=("a1", "a2")))
    registry.register(FakeDependencyValidator("b-owner", archive_blockers=("b1",)))
    service = ReferenceLifecycleService(factory, registry)
    connection = _read(initialized_database)
    try:
        before = (
            connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0],
            connection.execute("SELECT count(*) FROM audit_events").fetchone()[0],
        )
    finally:
        connection.close()
    first = service.preview(operation="archive", target_type="contact", target_id=contact.contact_id, limit=2)
    second = service.preview(
        operation="archive",
        target_type="contact",
        target_id=contact.contact_id,
        after=first.continuation,
        limit=2,
    )
    assert first.exact_blocker_count == second.exact_blocker_count == 3
    assert first.would_be_eligible is second.would_be_eligible is False
    assert len(first.blockers) == 2 and len(second.blockers) == 1
    connection = _read(initialized_database)
    try:
        assert (
            connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0],
            connection.execute("SELECT count(*) FROM audit_events").fetchone()[0],
        ) == before
    finally:
        connection.close()


def test_archive_then_reactivate_preserves_append_only_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(command_id=new_uuid4(), name="Lifecycle Contact")
    service = ReferenceLifecycleService(factory)
    service.archive_reference(
        command_id=new_uuid4(), target_type="contact", target_id=contact.contact_id,
        base_revision=1, reason_category="operator_archive"
    )
    service.reactivate_reference(
        command_id=new_uuid4(), target_type="contact", target_id=contact.contact_id,
        base_revision=2, reason_category="operator_reactivate"
    )
    connection = _read(initialized_database)
    try:
        assert tuple(connection.execute(
            "SELECT lifecycle_state,revision FROM contacts WHERE contact_id=?", (contact.contact_id,)
        ).fetchone()) == ("active", 3)
        events = connection.execute(
            "SELECT reference_lifecycle_event_id,event_type FROM reference_lifecycle_events WHERE target_id=?",
            (contact.contact_id,),
        ).fetchall()
        assert {row[1] for row in events} == {"created", "archived", "reactivated"}
        with pytest.raises(Exception):
            connection.execute(
                "UPDATE reference_lifecycle_events SET reason_category='rewrite' WHERE reference_lifecycle_event_id=?",
                (events[0][0],),
            )
    finally:
        connection.close()


def _boolean_definition() -> SettingDefinition:
    def validate(value):
        if not isinstance(value, dict) or set(value) != {"enabled"} or type(value["enabled"]) is not bool:
            raise ValidationError("example setting must be {enabled: boolean}")
        return value
    return SettingDefinition(
        setting_key="test.example.enabled",
        semantic_owner="tests",
        contract_name="ExampleSettingV1",
        current_version=1,
        default_provider=lambda: {"enabled": False},
        validator=validate,
        semantic_equals=lambda left, right: left == right,
        max_utf8_bytes=256,
        max_depth=2,
        max_collection_items=4,
    )


def test_settings_are_read_pure_typed_atomic_and_secret_excluding(initialized_database) -> None:
    registry = SettingDefinitionRegistry()
    registry.register(_boolean_definition())
    service = SettingService(_factory(initialized_database), registry)
    default = service.get("test.example.enabled")
    assert default.source == "DEFAULT" and default.revision is None and default.value == {"enabled": False}
    connection = _read(initialized_database)
    try:
        assert connection.execute("SELECT count(*) FROM setting_values").fetchone()[0] == 0
    finally:
        connection.close()
    with pytest.raises(SomaError) as unknown:
        service.get("unknown.setting")
    assert unknown.value.code == "SETTING_UNKNOWN"

    assert service.write(
        command_id=new_uuid4(), setting_key="test.example.enabled", base_revision=None, value={"enabled": True}
    ).no_change is False
    assert service.write(
        command_id=new_uuid4(), setting_key="test.example.enabled", base_revision=1, value={"enabled": True}
    ).no_change is True
    with pytest.raises(SomaError) as stale:
        service.write(
            command_id=new_uuid4(), setting_key="test.example.enabled", base_revision=99, value={"enabled": False}
        )
    assert stale.value.code == "STALE_REVISION"
    connection = _read(initialized_database)
    try:
        row = connection.execute(
            "SELECT revision,value_json FROM setting_values WHERE setting_key='test.example.enabled'"
        ).fetchone()
        assert row[0] == 1
        payload = json.loads(connection.execute(
            "SELECT payload_json FROM audit_events WHERE action_type='setting.written'"
        ).fetchone()[0])
        assert set(payload) == {
            "setting_key", "contract_id", "contract_version", "prior_revision", "new_revision", "change_kind"
        }
        assert "value" not in payload and payload["setting_key"] == "test.example.enabled"
    finally:
        connection.close()

    with pytest.raises(SomaError) as secret:
        registry.register(SettingDefinition(
            setting_key="security.password",
            semantic_owner="security",
            contract_name="SecretV1",
            current_version=1,
            default_provider=lambda: {},
            validator=lambda value: value,
            semantic_equals=lambda left, right: left == right,
            storage_class="secret",
        ))
    assert secret.value.code == "SETTING_SECRET_FORBIDDEN"


def test_local_profile_has_no_login_authority_and_display_edit_is_stale_safe(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = LocalUserProfileService(factory)
    parent = new_uuid4()
    with UnitOfWork(factory) as uow:
        _parent_receipt(uow, parent, "FirstRunSetup")
        profile_id = service.ensure_singleton_local_administrator(uow, parent_command_id=parent)
    profile = service.get_singleton()
    assert profile is not None
    assert (profile.local_user_profile_id, profile.display_name, profile.revision) == (
        profile_id, "Local Administrator", 1
    )
    connection = _read(initialized_database)
    try:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(local_user_profiles)").fetchall()}
        assert {"username", "login_name", "password", "verifier", "token"}.isdisjoint(columns)
        created_payload = connection.execute(
            "SELECT payload_json FROM audit_events WHERE action_type='local_user_profile.created'"
        ).fetchone()[0]
        assert "Local Administrator" not in created_payload
    finally:
        connection.close()

    command_id = new_uuid4()
    assert service.update_display_name(
        command_id=command_id, base_revision=1, display_name="Operations Administrator", actor_id=profile_id
    ).no_change is False
    assert service.update_display_name(
        command_id=command_id, base_revision=1, display_name="Operations Administrator", actor_id=profile_id
    ).replayed is True
    with pytest.raises(SomaError) as stale:
        service.update_display_name(
            command_id=new_uuid4(), base_revision=1, display_name="Stale overwrite", actor_id=profile_id
        )
    assert stale.value.code == "STALE_REVISION"
    profile = service.get_singleton()
    assert profile is not None and profile.display_name == "Operations Administrator" and profile.revision == 2
    connection = _read(initialized_database)
    try:
        payload = connection.execute(
            "SELECT payload_json FROM audit_events WHERE action_type='local_user_profile.display_name_updated'"
        ).fetchone()[0]
        assert "Operations Administrator" not in payload and "Stale overwrite" not in payload
    finally:
        connection.close()
