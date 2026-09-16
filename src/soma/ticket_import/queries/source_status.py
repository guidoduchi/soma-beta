from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ..profiles.registry import require_profile_versions
from ..repositories.runs import SourceCheckpointRepository
from .runs import _RUN_SELECT, ImportRunSummary, checkpoint_summary, run_summary_from_row


@dataclass(frozen=True, slots=True)
class ImportSourceStatus:
    source_family: str
    configured: bool
    profile_ids: dict[str, str]
    checkpoint: dict[str, object] | None
    latest_run: ImportRunSummary | None

    def to_response(self) -> dict[str, object]:
        return {
            "source_family": self.source_family,
            "configured": self.configured,
            "profile_ids": dict(self.profile_ids),
            "checkpoint": self.checkpoint,
            "latest_run": None if self.latest_run is None else self.latest_run.to_response(),
        }


class ImportSourceStatusQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def get_status(self, source_family: str) -> ImportSourceStatus:
        versions = require_profile_versions(source_family)
        setting_key = (
            "advanced_search_import_directory"
            if source_family == "advanced_search_sr"
            else "rfc_wfm_import_directory"
        )
        with ReadSnapshot(self._factory) as snapshot:
            configured = snapshot.connection.execute(
                "SELECT 1 FROM setting_values WHERE setting_key=?",
                (setting_key,),
            ).fetchone() is not None
            checkpoint = SourceCheckpointRepository.get(snapshot.connection, source_family)
            row = snapshot.connection.execute(
                f"SELECT {_RUN_SELECT} FROM import_runs WHERE source_family=? "
                "ORDER BY started_at_utc DESC,import_run_id DESC LIMIT 1",
                (source_family,),
            ).fetchone()
            return ImportSourceStatus(
                source_family=source_family,
                configured=configured,
                profile_ids={
                    "source_profile_id": versions.source_profile_id,
                    "header_registry_id": versions.header_registry_id,
                    "vocabulary_registry_id": versions.vocabulary_registry_id,
                    "parser_profile_id": versions.parser_profile_id,
                },
                checkpoint=checkpoint_summary(checkpoint),
                latest_run=None if row is None else run_summary_from_row(row),
            )


__all__ = ["ImportSourceStatus", "ImportSourceStatusQueryService"]
