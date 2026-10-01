from __future__ import annotations

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.reference.application.settings_service import SettingService
from soma.reference.audit_registry import build_reference_audit_registry

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed, fingerprint, integer
from soma.communications.settings import GRACE_KEY, SCHEDULE_KEYS, build_communications_setting_registry


class CommunicationSettingsService:
    def __init__(self, connection_factory):
        self._factory = connection_factory
        self.settings = SettingService(connection_factory, build_communications_setting_registry())
        registry = build_communications_audit_registry()
        registry.extend(build_reference_audit_registry())
        self._boundary = CommandBoundary(connection_factory, AuditWriter(registry))

    def _schedule(self, reader):
        settings = tuple(self.settings.get_in_reader(reader, key) for key in SCHEDULE_KEYS)
        token = sha256_canonical_json({"schema": "SOMA_COMM_SCHEDULE_SETTINGS_V1", "settings": [
            {"key": setting.setting_key, "contract": setting.contract_name, "version": setting.contract_version,
             "revision": setting.revision, "value": setting.value} for setting in settings]})
        return settings, token

    def schedule_state(self) -> dict:
        with ReadSnapshot(self._factory) as reader:
            values, token = self._schedule(reader)
            return {"enabled": values[0].value, "interval_minutes": values[1].value, "overlap_messages": values[2].value,
                    "settings_revision_fingerprint": token}

    def set_processing_schedule(self, payload: dict, *, actor_kind="local_user", actor_id=None) -> dict:
        closed(payload, {"command_id", "enabled", "interval_minutes", "overlap_messages", "settings_revision_fingerprint"})
        command = require_uuid4(payload["command_id"])
        if type(payload["enabled"]) is not bool:
            raise ValidationError("Communication processing enabled requires an exact boolean")
        integer(payload["interval_minutes"], minimum=1, maximum=10080)
        integer(payload["overlap_messages"], maximum=500)
        fingerprint(payload["settings_revision_fingerprint"])
        desired = (payload["enabled"], payload["interval_minutes"], payload["overlap_messages"])
        envelope = CommandEnvelope(command, "SetCommunicationProcessingSchedule", "setting", SCHEDULE_KEYS[0],
                                   {key: value for key, value in payload.items() if key != "command_id"},
                                   authorizing_fingerprints={"settings": payload["settings_revision_fingerprint"]})

        def prepare(uow):
            current, token = self._schedule(uow)
            if token != payload["settings_revision_fingerprint"]:
                raise SomaError("COMM_STALE", "Communication schedule settings changed")
            changed = [(setting, value) for setting, value in zip(current, desired) if setting.value != value]
            if not changed:
                return self._no_change(SCHEDULE_KEYS[0], None)
            participants = [self.settings.prepare_write_participant(
                uow, command_id=command, setting_key=setting.setting_key, base_revision=setting.revision, value=value,
                actor_kind=actor_kind, actor_id=actor_id) for setting, value in changed]

            def apply(inner):
                audits = tuple(participant.apply(inner) for participant in participants)
                return audits + (audit_event("communications.processing_schedule.changed", command_id=command,
                    target_type="setting", target_id=SCHEDULE_KEYS[0], payload={"enabled": desired[0], "interval_minutes": desired[1], "overlap_messages": desired[2]},
                    actor_kind=actor_kind, actor_id=actor_id, refs=tuple(AuditResultRef("setting", p.setting_key) for p in participants)),)

            return PreparedMutation(False, "setting", SCHEDULE_KEYS[0], apply, response_schema="CommunicationMutationResultV1",
                                    response={"status": "APPLIED", "target_id": SCHEDULE_KEYS[0], "new_revision": None,
                                              "result_refs": [{"type": "setting", "id": p.setting_key} for p in participants]})
        return self._boundary.execute(envelope, prepare).response

    def set_orphan_grace(self, payload: dict, *, actor_kind="local_user", actor_id=None) -> dict:
        closed(payload, {"command_id", "grace_minutes", "setting_revision"})
        command = require_uuid4(payload["command_id"])
        integer(payload["grace_minutes"], minimum=1, maximum=525600)
        revision = integer(payload["setting_revision"])
        envelope = CommandEnvelope(command, "SetCommunicationOrphanGrace", "setting", GRACE_KEY,
                                   {"grace_minutes": payload["grace_minutes"], "setting_revision": revision},
                                   base_revisions={} if revision == 0 else {"setting": revision})

        def prepare(uow):
            current = self.settings.get_in_reader(uow, GRACE_KEY)
            if (current.revision or 0) != revision:
                raise SomaError("COMM_STALE", "Communication orphan grace setting changed")
            if current.value == payload["grace_minutes"]:
                return self._no_change(GRACE_KEY, current.revision or 0)
            participant = self.settings.prepare_write_participant(
                uow, command_id=command, setting_key=GRACE_KEY, base_revision=current.revision, value=payload["grace_minutes"],
                actor_kind=actor_kind, actor_id=actor_id)

            def apply(inner):
                return (participant.apply(inner), audit_event("communications.orphan_grace.changed", command_id=command,
                    target_type="setting", target_id=GRACE_KEY, payload={"prior_minutes": current.value, "new_minutes": payload["grace_minutes"]},
                    actor_kind=actor_kind, actor_id=actor_id, refs=(AuditResultRef("setting", GRACE_KEY),)))

            return PreparedMutation(False, "setting", GRACE_KEY, apply, response_schema="CommunicationMutationResultV1",
                                    response={"status": "APPLIED", "target_id": GRACE_KEY, "new_revision": participant.new_revision,
                                              "result_refs": [{"type": "setting", "id": GRACE_KEY}]})
        return self._boundary.execute(envelope, prepare).response

    @staticmethod
    def _no_change(target, revision):
        return PreparedMutation(True, None, None, response_schema="CommunicationMutationResultV1",
                                response={"status": "NO_CHANGE", "target_id": target, "new_revision": revision, "result_refs": []})
