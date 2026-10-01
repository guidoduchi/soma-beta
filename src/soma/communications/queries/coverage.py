from __future__ import annotations

import hashlib

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.contracts.common import closed
from soma.communications.contracts.source import ProviderCheckpoint
from soma.communications.repositories import sources


def coverage_in_reader(reader, source_scope_id, *, folder_keys=None):
    require_uuid4(source_scope_id)
    source = sources.scope(reader, source_scope_id)
    if source is None:
        raise SomaError("COMM_SOURCE_NOT_FOUND", "Communication source scope is unavailable")
    rows = reader.connection.execute(
        "SELECT f.source_folder_id,f.provider_folder_key,f.role,f.display_name,c.adapter_version,"
        "c.checkpoint_kind,c.checkpoint_token,c.provider_time_source_epoch_ms,c.state "
        "FROM communication_source_folders f LEFT JOIN communication_forward_coverage c "
        "ON c.source_scope_id=f.source_scope_id AND c.source_folder_id=f.source_folder_id "
        "WHERE f.source_scope_id=? AND f.enabled=1 ORDER BY "
        "CASE f.role WHEN 'INBOX' THEN 0 WHEN 'SENT' THEN 1 ELSE 2 END,f.display_name,f.source_folder_id LIMIT 65",
        (source_scope_id,),
    ).fetchall()
    if len(rows) > 64:
        raise IntegrityFailure("Communication scope exceeds the selected-folder bound")
    selected = [row for row in rows if folder_keys is None or row[1] in folder_keys]
    history = {}
    if selected:
        placeholders = ",".join("?" for _ in selected)
        history = {(folder, state): count for folder, state, count in reader.connection.execute(
            "SELECT source_folder_id,state,COUNT(*) FROM communication_historical_coverage_segments "
            f"WHERE source_scope_id=? AND source_folder_id IN ({placeholders}) GROUP BY source_folder_id,state",
            (source_scope_id, *(row[0] for row in selected)),
        )}
    items, warnings = [], set()
    for folder, key, role, name, adapter, kind, token, instant, forward_state in selected:
        current_warnings = []
        high_water = None
        if kind is not None:
            high_water = ProviderCheckpoint(kind, token, instant).to_response()
        if adapter is not None and adapter != source["adapter_version"]:
            current_warnings.append("COMM_COVERAGE_ADAPTER_CHANGED")
            forward_state = "UNKNOWN"
            high_water = None
        forward_state = forward_state or "NONE"
        historical_state = ("UNKNOWN" if history.get((folder, "UNKNOWN")) else
                            "PARTIAL" if history.get((folder, "PARTIAL")) else
                            "BOUNDED_COMPLETE" if history.get((folder, "BOUNDED_COMPLETE")) else "NONE")
        if forward_state in {"PARTIAL", "UNKNOWN"} or historical_state in {"PARTIAL", "UNKNOWN"}:
            current_warnings.append("COMM_COVERAGE_INCOMPLETE")
        warnings.update(current_warnings)
        items.append({"source_scope_id": source_scope_id, "folder_key": key, "forward_state": forward_state,
                      "high_water": high_water, "historical_state": historical_state,
                      "warnings": sorted(current_warnings)})
    return {"source_scope_id": source_scope_id, "folders": items, "warnings": sorted(warnings)}


def coverage_fingerprint(reader, source_scope_id, folder_keys):
    """Bind exact recorded range evidence using one streaming, indexed read.

    The bounded projection alone cannot distinguish changed historical bounds.
    No source content or operational owner data enters this fingerprint.
    """
    folders = sources.enabled_folders(reader, source_scope_id)
    selected = sorted(row["source_folder_id"] for row in folders if row["provider_folder_key"] in folder_keys)
    digest = hashlib.sha256(b"SOMA_COMM_COVERAGE_FINGERPRINT_V1\x00")
    if selected:
        placeholders = ",".join("?" for _ in selected)
        for table, columns, ordering in (
            ("communication_forward_coverage", "source_folder_id,adapter_version,checkpoint_kind,checkpoint_token,provider_time_source_epoch_ms,state,revision", "source_folder_id"),
            ("communication_historical_coverage_segments", "source_folder_id,coverage_segment_id,lower_bound_json,upper_bound_json,state,job_id,recorded_at_utc", "source_folder_id,recorded_at_utc,coverage_segment_id"),
        ):
            digest.update(table.encode("ascii") + b"\x00")
            for row in reader.connection.execute(
                f"SELECT {columns} FROM {table} WHERE source_scope_id=? AND source_folder_id IN ({placeholders}) ORDER BY {ordering}",
                (source_scope_id, *selected),
            ):
                encoded = canonical_json_bytes(list(row))
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
    return digest.hexdigest()


class CoverageQueries:
    def __init__(self, connection_factory):
        self._factory = connection_factory

    def get_coverage(self, request):
        identity = closed(request, {"source_scope_id"})["source_scope_id"]
        with ReadSnapshot(self._factory) as reader:
            return coverage_in_reader(reader, identity)
