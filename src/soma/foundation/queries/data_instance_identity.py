"""LLD-01's read-only data-instance identity provider."""

from __future__ import annotations

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4


class DataInstanceIdentityReader:
    @staticmethod
    def get(snapshot_or_verified_reader) -> str:
        connection = getattr(snapshot_or_verified_reader, "connection", snapshot_or_verified_reader)
        rows = connection.execute(
            "SELECT data_instance_id FROM instance_metadata WHERE singleton=1 LIMIT 2"
        ).fetchall()
        if len(rows) != 1:
            raise IntegrityFailure("canonical data-instance identity is unavailable")
        try:
            return require_uuid4(str(rows[0][0]))
        except Exception as exc:
            raise IntegrityFailure("canonical data-instance identity is malformed") from exc
