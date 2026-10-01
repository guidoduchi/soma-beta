from __future__ import annotations

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed, fingerprint
from soma.communications.contracts.source import SourceFolder
from soma.communications.queries.previews import source_preview_in_reader, source_request
from soma.communications.repositories import sources
from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.reference.domain.matching import normalize_match_key


class SourceConfigurationService:
    def __init__(self, connection_factory, adapter):
        self._adapter = adapter
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_communications_audit_registry()))

    def configure_source_scope(self, payload: dict, *, actor_kind="local_user", actor_id=None) -> dict:
        payload = dict(closed(payload, {"command_id", "source_scope_id", "base_revision", "display_name", "source_location", "selected_folders", "preview_fingerprint"}))
        command_id = require_uuid4(payload["command_id"])
        fingerprint(payload["preview_fingerprint"])
        if not isinstance(payload["selected_folders"], list) or not 1 <= len(payload["selected_folders"]) <= 64:
            raise ValidationError("Communication scope requires 1..64 folders")
        folders = sorted((SourceFolder.from_value(x) for x in payload["selected_folders"]), key=lambda x: x.folder_key)
        request = source_request({k: payload[k] for k in ("source_scope_id", "base_revision", "display_name", "source_location")} | {"selected_folder_keys": [x.folder_key for x in folders]})
        semantic = {k: v for k, v in payload.items() if k != "command_id"}
        semantic["selected_folders"] = [x.to_response() for x in folders]
        envelope = CommandEnvelope(command_id, "ConfigureSourceScope", "communication_source_scope", payload["source_scope_id"], semantic,
            base_revisions={} if payload["base_revision"] is None else {"source_scope": payload["base_revision"]},
            authorizing_fingerprints={"preview": payload["preview_fingerprint"]})
        replay = self._boundary.lookup_replay(envelope)
        if replay is not None:
            return replay.response
        probe = self._adapter.probe_read_only(payload["source_location"], None)

        def prepare(uow):
            preview = source_preview_in_reader(uow, request, probe)
            if preview["identity_disposition"] == "RECONCILIATION_REQUIRED":
                raise SomaError("COMM_SOURCE_SCOPE_CONFLICT", "Communication source scope requires reconciliation")
            if preview["preview_fingerprint"] != payload["preview_fingerprint"]:
                raise SomaError("COMM_STALE", "Communication source preview changed")
            probed = {x.folder_key: x.to_response() for x in probe.folders}
            if any(x.to_response() != probed[x.folder_key] for x in folders):
                raise SomaError("COMM_STALE", "Communication folder evidence changed")
            existing_id = preview["existing_source_scope_id"]
            # An existing provider scope must be deliberately reviewed with its
            # exact id/revision, rather than silently adopted by a create call.
            if existing_id is not None and payload["source_scope_id"] != existing_id:
                raise SomaError("COMM_SOURCE_SCOPE_CONFLICT", "Review the existing Communication source scope")
            existing = sources.scope(uow, existing_id) if existing_id else None
            current = sources.enabled_folders(uow, existing_id) if existing else []
            current_values = [{"folder_key": x["provider_folder_key"], "role": x["role"], "display_name": x["display_name"]} for x in current]
            no_change = existing is not None and existing["display_name"] == payload["display_name"] and existing["current_location"] == payload["source_location"] and existing["health_state"] == probe.health and current_values == semantic["selected_folders"]
            identity = existing_id or new_uuid4()
            revision = existing["revision"] if existing else 0
            if no_change:
                return PreparedMutation(True, None, None, response_schema="CommunicationMutationResultV1", response={"status": "NO_CHANGE", "target_id": identity, "new_revision": revision, "result_refs": []})
            new_revision = revision + 1
            now = utc_epoch_seconds()
            events = []
            if not existing:
                events.append("CREATED")
            else:
                if existing["current_location"] != payload["source_location"] or existing["display_name"] != payload["display_name"]:
                    events.append("LOCATION_CHANGED")
                if current_values != semantic["selected_folders"]:
                    events.append("FOLDERS_CHANGED")
                if existing["health_state"] != probe.health:
                    events.append("HEALTH_CHANGED")

            def apply(inner):
                if existing:
                    inner.connection.execute("UPDATE communication_source_scopes SET display_name=?,display_name_folded=?,current_location=?,health_state=?,revision=?,updated_at_utc=? WHERE source_scope_id=?",
                        (payload["display_name"], normalize_match_key(payload["display_name"], raw_max_utf8_bytes=480), payload["source_location"], probe.health, new_revision, now, identity))
                else:
                    inner.connection.execute("INSERT INTO communication_source_scopes(source_scope_id,display_name,display_name_folded,adapter_family,adapter_version,scope_identity_kind,scope_identity_value,current_location,health_state,processing_enabled,revision,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,1,1,?,?)",
                        (identity, payload["display_name"], normalize_match_key(payload["display_name"], raw_max_utf8_bytes=480), probe.adapter_family, probe.adapter_version,
                         "PROVIDER_ACCOUNT" if probe.scope_identity_candidate else "OPERATOR_CONFIRMED_LOCAL_SCOPE",
                         probe.scope_identity_candidate or new_uuid4(), payload["source_location"], probe.health, now, now))
                selected_keys = {x.folder_key for x in folders}
                for old in current:
                    if old["provider_folder_key"] not in selected_keys:
                        inner.connection.execute("UPDATE communication_source_folders SET enabled=0,revision=revision+1 WHERE source_folder_id=?", (old["source_folder_id"],))
                for folder in folders:
                    inner.connection.execute("INSERT INTO communication_source_folders(source_folder_id,source_scope_id,provider_folder_key,display_name,role,enabled,revision) VALUES(?,?,?,?,?,1,1) ON CONFLICT(source_scope_id,provider_folder_key) DO UPDATE SET display_name=excluded.display_name,role=excluded.role,enabled=1,revision=revision+1 WHERE display_name!=excluded.display_name OR role!=excluded.role OR enabled!=1",
                        (new_uuid4(), identity, folder.folder_key, folder.display_name, folder.role))
                for event in events:
                    inner.connection.execute("INSERT INTO communication_source_scope_events VALUES(?,?,?,?,?,?,?)", (new_uuid4(), identity, event, revision or None, new_revision, now, command_id))
                return audit_event("communications.source_scope.configured", command_id=command_id, target_type="communication_source_scope", target_id=identity,
                    payload={"change_kind": "CREATE" if not existing else "UPDATE", "folder_count": len(folders), "adapter_family": probe.adapter_family, "health_state": probe.health},
                    refs=(AuditResultRef("communication_source_scope", identity),), actor_kind=actor_kind, actor_id=actor_id)

            return PreparedMutation(False, "communication_source_scope", identity, apply,
                response_schema="CommunicationMutationResultV1", response={"status": "APPLIED", "target_id": identity, "new_revision": new_revision,
                "result_refs": [{"type": "communication_source_scope", "id": identity}]})

        return self._boundary.execute(envelope, prepare).response
