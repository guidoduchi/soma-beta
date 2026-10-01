from __future__ import annotations

import hashlib

from soma.communications.adapters.msg_publication import MsgDraftPublisher, destination, require_unprotected
from soma.communications.adapters.msg_writer import MsgDraftWriter
from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed, integer, text
from soma.communications.contracts.drafts import MsgDraftSnapshot, draft_recipients
from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json


_FIELDS = {"command_id", "origin_domain", "origin_command_id", "origin_target_type", "origin_target_id",
           "template_id", "template_version", "subject", "body_format", "body", "recipients", "destination_path"}


def _protected_sources(reader):
    """Stream configuration evidence, without opening mail content."""
    return reader.connection.execute(
        "SELECT source_scope_id,revision,current_location FROM communication_source_scopes ORDER BY source_scope_id"
    )


def _source_fingerprint(reader, path=None):
    digest = hashlib.sha256(b"MSG_PROTECTED_SOURCES_V1\0")
    for row in _protected_sources(reader):
        if path is not None:
            require_unprotected(path, (row[2],))
        digest.update(bytes.fromhex(sha256_canonical_json(list(row))))
    return digest.hexdigest()


def _existing(reader, origin_command_id, content_fingerprint):
    row = reader.connection.execute(
        "SELECT msg_draft_id,origin_domain,origin_target_type,origin_target_id FROM communication_msg_drafts "
        "WHERE origin_command_id=? AND content_fingerprint=?", (origin_command_id, content_fingerprint),
    ).fetchone()
    return row


class MsgDraftService:
    def __init__(self, connection_factory, identity_providers, *, writer=None, publisher=None):
        self._factory = connection_factory
        self._owners = identity_providers
        self._writer = writer or MsgDraftWriter()
        self._publisher = publisher or MsgDraftPublisher()
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_communications_audit_registry()))

    def generate_msg_draft(self, value, *, actor_kind="local_user", actor_id=None):
        payload = dict(closed(value, _FIELDS))
        for key in ("command_id", "origin_command_id", "origin_target_id"):
            require_uuid4(payload[key])
        text(payload["origin_domain"], minimum=1, maximum=128)
        text(payload["origin_target_type"], minimum=1, maximum=128)
        text(payload["template_id"], maximum=128)
        integer(payload["template_version"], minimum=1)
        text(payload["destination_path"], minimum=1, maximum=1024)
        snapshot = MsgDraftSnapshot(payload["subject"], payload["body_format"], payload["body"], draft_recipients(payload["recipients"]))
        # Input order within each role is semantic; incidental interleaving of
        # roles is canonicalized consistently with the MSG recipient storage.
        payload["recipients"] = [item.to_value() for item in snapshot.role_ordered_recipients]
        semantic = {key: item for key, item in payload.items() if key != "command_id"}
        envelope = CommandEnvelope(payload["command_id"], "GenerateMsgDraft", "communication_msg_draft", None, semantic)
        replay = self._boundary.lookup_replay(envelope)
        if replay is not None:
            return replay.response
        path = destination(payload["destination_path"])
        authored = {key: item for key, item in semantic.items() if key not in {"destination_path", "origin_command_id"}}
        content_fingerprint = sha256_canonical_json({"schema": "MSG_DRAFT_CONTENT_V1", **authored})
        with ReadSnapshot(self._factory) as reader:
            origin_fingerprint = self._owners.msg_draft_origin(reader, payload["origin_domain"], payload["origin_target_type"],
                                                              payload["origin_target_id"], payload["origin_command_id"])
            protection = _source_fingerprint(reader, path)
        artifact = self._writer.build(snapshot)
        self._publisher.publish(path, artifact)
        # Locations are personal metadata. Persist only the optional fingerprint,
        # and never put a location, subject, body or address in audit evidence.
        location_fingerprint = sha256_canonical_json({"schema": "MSG_EXPORT_LOCATION_V1", "path": str(path)})

        def prepare(uow):
            current = self._owners.msg_draft_origin(uow, payload["origin_domain"], payload["origin_target_type"],
                                                  payload["origin_target_id"], payload["origin_command_id"])
            if current != origin_fingerprint or _source_fingerprint(uow) != protection:
                raise SomaError("COMM_STALE", "MSG draft origin or source protection changed during publication")
            old = _existing(uow, payload["origin_command_id"], content_fingerprint)
            if old is not None and tuple(old[1:]) != (payload["origin_domain"], payload["origin_target_type"], payload["origin_target_id"]):
                raise IntegrityFailure("MSG draft semantic identity disagrees with its recorded origin")
            draft_id = old[0] if old is not None else new_uuid4()
            response = {"msg_draft_id": draft_id, "artifact_sha256": artifact.sha256,
                        "artifact_size_bytes": artifact.size_bytes, "state": "EXPORTED"}
            prior = uow.connection.execute(
                "SELECT 1 FROM communication_msg_draft_exports WHERE msg_draft_id=? AND artifact_sha256=? "
                "AND artifact_size_bytes=? AND location_fingerprint=? LIMIT 1",
                (draft_id, artifact.sha256, artifact.size_bytes, location_fingerprint),
            ).fetchone()
            if prior is not None:
                return PreparedMutation(True, None, None, response_schema="MsgDraftResultV1", response=response)
            export_id, now = new_uuid4(), utc_epoch_seconds()

            def apply(inner):
                if old is None:
                    inner.connection.execute(
                        "INSERT INTO communication_msg_drafts(msg_draft_id,origin_domain,origin_command_id,origin_target_type,origin_target_id,"
                        "template_id,template_version,subject_snapshot,body_format,body_snapshot,content_fingerprint,state,revision,generated_at_utc) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,'EXPORTED',1,?)",
                        (draft_id, payload["origin_domain"], payload["origin_command_id"], payload["origin_target_type"], payload["origin_target_id"],
                         payload["template_id"], payload["template_version"], snapshot.subject, snapshot.body_format, snapshot.body, content_fingerprint, now),
                    )
                    for ordinal, recipient in enumerate(snapshot.role_ordered_recipients):
                        inner.connection.execute("INSERT INTO communication_msg_draft_recipients VALUES(?,?,?,?,?,?)",
                            (new_uuid4(), draft_id, recipient.role, ordinal, recipient.address, recipient.display_name))
                inner.connection.execute("INSERT INTO communication_msg_draft_exports VALUES(?,?,?,?,?,?)",
                    (export_id, draft_id, artifact.sha256, artifact.size_bytes, now, location_fingerprint))
                return audit_event("communications.msg_draft.exported", command_id=payload["command_id"],
                    target_type="communication_msg_draft", target_id=draft_id,
                    payload={"artifact_sha256": artifact.sha256, "artifact_size_bytes": artifact.size_bytes,
                             "template_id": payload["template_id"], "template_version": payload["template_version"], "recipient_count": len(snapshot.recipients)},
                    refs=(AuditResultRef("communication_msg_draft", draft_id), AuditResultRef("communication_msg_draft_export", export_id)),
                    actor_kind=actor_kind, actor_id=actor_id)

            return PreparedMutation(False, "communication_msg_draft", draft_id, apply,
                                    response_schema="MsgDraftResultV1", response=response)

        return self._boundary.execute(envelope, prepare).response
