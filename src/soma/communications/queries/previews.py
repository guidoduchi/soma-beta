from __future__ import annotations

from soma.communications.contracts.common import closed, integer, text
from soma.communications.contracts.source import SourceProbe
from soma.communications.repositories import sources
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.communications.contracts.jobs import validate_job_json
from soma.communications.services.scan_scope import communication_settings, scan_preview_in_reader


def source_request(value: dict) -> dict:
    value = dict(closed(value, {"source_scope_id", "base_revision", "display_name", "source_location", "selected_folder_keys"}))
    if value["source_scope_id"] is None:
        if value["base_revision"] is not None:
            raise ValidationError("New Communication scope cannot have a base revision")
    else:
        require_uuid4(value["source_scope_id"])
        integer(value["base_revision"], minimum=1)
    text(value["display_name"], minimum=1, maximum=120)
    text(value["source_location"], minimum=1, maximum=1024)
    keys = value["selected_folder_keys"]
    if not isinstance(keys, list) or not 1 <= len(keys) <= 64:
        raise ValidationError("Communication scope requires 1..64 selected folders")
    for key in keys:
        text(key, minimum=1, maximum=512)
    if len(set(keys)) != len(keys):
        raise ValidationError("Communication folder selection contains duplicates")
    value["selected_folder_keys"] = sorted(keys)
    return value


def source_preview_in_reader(reader, request: dict, probe: SourceProbe) -> dict:
    if not isinstance(probe, SourceProbe):
        raise IntegrityFailure("Communication adapter returned an invalid probe")
    error = {"MISSING": "COMM_SOURCE_NOT_FOUND", "LOCKED": "COMM_SOURCE_LOCKED", "CORRUPT": "COMM_SOURCE_UNSUPPORTED", "UNSUPPORTED": "COMM_SOURCE_UNSUPPORTED"}.get(probe.health)
    if error:
        raise SomaError(error, "Communication source cannot be configured")
    selected = [x.to_response() for x in probe.folders if x.folder_key in request["selected_folder_keys"]]
    selected.sort(key=lambda x: x["folder_key"])
    if len(selected) != len(request["selected_folder_keys"]):
        raise SomaError("COMM_STALE", "Communication source folder selection changed")
    existing = sources.scope(reader, request["source_scope_id"]) if request["source_scope_id"] else None
    if request["source_scope_id"] and (existing is None or existing["revision"] != request["base_revision"]):
        raise SomaError("COMM_STALE", "Communication source scope changed")
    candidate = None if probe.scope_identity_candidate is None else sources.provider_scope(reader, probe.adapter_family, probe.scope_identity_candidate)
    conflict = False
    if existing:
        conflict = existing["adapter_family"] != probe.adapter_family or existing["adapter_version"] != probe.adapter_version
        if existing["scope_identity_kind"] == "PROVIDER_ACCOUNT":
            conflict |= probe.scope_identity_candidate != existing["scope_identity_value"]
        if candidate is not None and candidate["source_scope_id"] != existing["source_scope_id"]:
            conflict = True
    elif candidate is not None:
        existing = candidate
    current_folders = sources.enabled_folders(reader, existing["source_scope_id"]) if existing else []
    if len(current_folders) > 64:
        raise IntegrityFailure("Communication scope exceeds selected-folder bounds")
    disposition = "RECONCILIATION_REQUIRED" if conflict else "REUSE_EXISTING" if existing else "CREATE_NEW"
    warnings = ["COMM_OPERATOR_SCOPE_CONFIRMATION_REQUIRED"] if probe.scope_identity_candidate is None and not existing else []
    if probe.health == "PARTIAL":
        warnings.append("COMM_SOURCE_PARTIAL")
    token = sha256_canonical_json({"schema": "SOMA_COMM_SOURCE_PREVIEW_V1", "request": request,
        "probe": probe.to_response(), "disposition": disposition, "existing": existing,
        "current_folders": current_folders})
    return {"probe": probe.to_response(), "identity_disposition": disposition,
            "existing_source_scope_id": None if existing is None else existing["source_scope_id"],
            "preview_fingerprint": token, "warnings": warnings}


class CommunicationPreviews:
    def __init__(self, connection_factory, adapter, identities=None):
        self._factory = connection_factory
        self._adapter = adapter
        self._identities = identities
        self._settings = communication_settings(connection_factory)

    def preview_source_scope_configuration(self, payload: dict) -> dict:
        request = source_request(payload)
        probe = self._adapter.probe_read_only(request["source_location"], None)
        with ReadSnapshot(self._factory) as snapshot:
            return source_preview_in_reader(snapshot, request, probe)

    def preview_deep_scan(self, payload):
        request = scan_request(payload, kind="DEEP_SCAN")
        with ReadSnapshot(self._factory) as reader:
            return scan_preview_in_reader(reader, request, kind="DEEP_SCAN", settings=self._settings, adapter=self._adapter)

    def preview_targeted_backfill(self, payload):
        request = scan_request(payload, kind="TARGETED_BACKFILL")
        if self._identities is None:
            raise IntegrityFailure("Communication identity owners are unavailable")
        with ReadSnapshot(self._factory) as reader:
            return scan_preview_in_reader(reader, request, kind="TARGETED_BACKFILL", settings=self._settings,
                                          identities=self._identities, adapter=self._adapter)


def scan_request(payload, *, kind):
    selection = "folder_keys" if kind == "DEEP_SCAN" else "target_identity_ids"
    request = dict(closed(payload, {"source_scope_id", "source_scope_revision", selection, "lower_bound", "upper_bound"}))
    require_uuid4(request["source_scope_id"])
    integer(request["source_scope_revision"], minimum=1)
    values = request[selection]
    if not isinstance(values, list) or not values:
        raise ValidationError("Communication scan selection requires a nonempty array")
    if selection == "folder_keys" and len(values) > 64:
        raise ValidationError("Communication scan folder selection exceeds its bound")
    for value in values:
        if selection == "folder_keys":
            text(value, minimum=1, maximum=512)
        else:
            require_uuid4(value)
    if len(set(values)) != len(values):
        raise ValidationError("Communication scan selection is duplicated")
    request[selection] = sorted(values)
    validate_job_json(request)
    return request
