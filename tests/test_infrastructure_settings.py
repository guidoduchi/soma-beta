from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.settings import (
    IMPORT_DIRECTORY_KEY, build_import_directory_setting_registry,
    observe_import_directory, require_saved_import_directory, validate_import_directory,
)
from soma.reference.application.settings_service import SettingService


def test_import_directory_uses_ordinary_setting_store_without_persisting_default():
    definition = build_import_directory_setting_registry(
        r"D:\SOMA\Data",
    ).require(IMPORT_DIRECTORY_KEY)
    assert definition.storage_class == "ordinary_nonsecret"
    assert definition.default_provider() == {"path": r"D:\SOMA\Data\Infrastructure Import"}
    assert definition.semantic_equals(
        {"path": r"D:\SOMA\Data\Infrastructure Import"},
        {"path": "d:\\soma\\data\\.\\INFRASTRUCTURE IMPORT\\"},
    )


@pytest.mark.parametrize("value", [
    {"path": r"relative\folder"},
    {"path": r"\rooted"},
    {"path": "C:\\bad\x00path"},
    {"path": r"C:\valid", "other": True},
    {"path": "C:\\" + "x" * 4096},
])
def test_import_directory_rejects_invalid_paths(value):
    with pytest.raises(ValidationError):
        validate_import_directory(value)


def test_import_directory_default_and_explicit_write_use_lld02_setting_store(initialized_database):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    settings = SettingService(
        factory, build_import_directory_setting_registry(r"D:\SOMA\Data"),
    )
    default = settings.get(IMPORT_DIRECTORY_KEY)
    assert default.source == "DEFAULT" and default.revision is None
    with pytest.raises(SomaError) as error:
        require_saved_import_directory(default, 1)
    assert error.value.code == "INFRA_STALE"
    with ReadSnapshot(factory) as snapshot:
        in_snapshot = settings.get_in_reader(snapshot, IMPORT_DIRECTORY_KEY)
        assert in_snapshot.source == "DEFAULT" and in_snapshot.revision is None
        assert snapshot.connection.execute(
            "SELECT count(*) FROM setting_values WHERE setting_key=?", (IMPORT_DIRECTORY_KEY,),
        ).fetchone()[0] == 0
    written = settings.write(
        command_id=new_uuid4(), setting_key=IMPORT_DIRECTORY_KEY,
        base_revision=None, value={"path": r"D:\Imports"},
    )
    assert written.source == "PERSISTED" and written.revision == 1
    assert settings.get(IMPORT_DIRECTORY_KEY).value == {"path": r"D:\Imports"}
    assert require_saved_import_directory(written, 1) == {"path": r"D:\Imports"}
    with pytest.raises(SomaError) as error:
        require_saved_import_directory(written, 2)
    assert error.value.code == "INFRA_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert settings.get_in_reader(snapshot, IMPORT_DIRECTORY_KEY).revision == 1


def test_import_directory_access_is_observational(tmp_path):
    existing = tmp_path / "Infrastructure Import"
    existing.mkdir()
    assert observe_import_directory({"path": str(existing)}) == existing
    missing = tmp_path / "missing"
    with pytest.raises(SomaError) as error:
        observe_import_directory({"path": str(missing)})
    assert error.value.code == "WORKBOOK_DIRECTORY_UNAVAILABLE"
    assert not missing.exists()
