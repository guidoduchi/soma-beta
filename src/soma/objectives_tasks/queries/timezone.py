from __future__ import annotations

from soma.foundation.persistence.connections import ConnectionFactory
from soma.reference.application.settings_service import SettingService

from ..settings import OBJECTIVE_TIMEZONE_KEY, build_objective_timezone_setting_registry


class ObjectiveTimezoneQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._settings = SettingService(
            connection_factory,
            build_objective_timezone_setting_registry(),
        )

    def get(self) -> dict[str, object]:
        value = self._settings.get(OBJECTIVE_TIMEZONE_KEY)
        return {
            "iana_timezone": str(value.value),
            "source": value.source,
            "revision": value.revision,
        }


__all__ = ["ObjectiveTimezoneQueryService"]
