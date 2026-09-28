from __future__ import annotations

import ntpath
import os
from pathlib import Path

from soma.foundation.errors import SomaError, ValidationError
from soma.reference.domain.settings import SettingDefinition, SettingDefinitionRegistry


IMPORT_DIRECTORY_KEY = "infrastructure.import_directory"


def _normal_path(path: str) -> str:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValidationError("Infrastructure import directory must be a Windows path")
    try:
        if len(path.encode("utf-8", errors="strict")) > 4096:
            raise ValidationError("Infrastructure import directory exceeds its path bound")
    except UnicodeError as exc:
        raise ValidationError("Infrastructure import directory is not valid UTF-8") from exc
    if not ntpath.isabs(path) or not ntpath.splitdrive(path)[0]:
        raise ValidationError("Infrastructure import directory must be absolute")
    normalized = ntpath.normpath(path)
    if normalized in (".", "\\"):
        raise ValidationError("Infrastructure import directory is not directory-shaped")
    return normalized


def validate_import_directory(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path"}:
        raise ValidationError("Infrastructure import directory requires only path")
    return {"path": _normal_path(value["path"])}


def observe_import_directory(value: object) -> Path:
    """Check the configured directory without creating or changing it."""
    path = Path(validate_import_directory(value)["path"])
    try:
        if not path.is_dir():
            raise SomaError("WORKBOOK_DIRECTORY_UNAVAILABLE", "Infrastructure import directory is unavailable")
        with os.scandir(path):
            pass
    except OSError as exc:
        raise SomaError(
            "WORKBOOK_DIRECTORY_UNAVAILABLE", "Infrastructure import directory is unavailable",
        ) from exc
    return path


def build_import_directory_setting_registry(
    installation_data_directory: str,
) -> SettingDefinitionRegistry:
    default_path = _normal_path(ntpath.join(
        _normal_path(installation_data_directory), "Infrastructure Import",
    ))
    registry = SettingDefinitionRegistry()
    registry.register(SettingDefinition(
        setting_key=IMPORT_DIRECTORY_KEY,
        semantic_owner="LLD-08",
        contract_name="INFRA_IMPORT_DIRECTORY_V1",
        current_version=1,
        default_provider=lambda: {"path": default_path},
        validator=validate_import_directory,
        semantic_equals=lambda left, right: (
            ntpath.normcase(_normal_path(left["path"]))
            == ntpath.normcase(_normal_path(right["path"]))
        ),
        unknown_field_policy="reject",
        storage_class="ordinary_nonsecret",
        # LLD-02 also enforces the setting's 4096-byte encoded value bound.
        max_utf8_bytes=4096,
        max_depth=2,
        max_collection_items=1,
    ))
    return registry
