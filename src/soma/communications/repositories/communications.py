"""Owned content writes; the caller owns matching, protection, receipt and UoW."""
from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.errors import IntegrityFailure

from soma.communications.domain.communication import normalized_address, normalized_source_text


def insert_retained(uow, communication_id, source_scope_id, message, identity, captured_attachments, *, identity_state, now):
    uow.connection.execute(
        "INSERT INTO communications(communication_id,source_scope_id,provider_identity_kind,provider_identity_digest,provider_identity_bytes,"
        "fallback_version,fallback_digest,fallback_canonical_json,identity_state,chronology_known,chronology_utc,chronology_source_kind,"
        "direction,subject,body_kind,body_text,content_state,content_revision,created_at_utc,updated_at_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'RETAINED',1,?,?)",
        (communication_id, source_scope_id, identity.provider_kind, identity.provider_digest, identity.provider_bytes,
         identity.fallback_version, identity.fallback_digest, identity.fallback_canonical_json, identity_state,
         int(message.chronology.known), message.chronology.utc_epoch_seconds, message.chronology.source_kind, message.direction,
         normalized_source_text(message.subject, trim=True), message.body_kind, normalized_source_text(message.body, body=True), now, now),
    )
    _children(uow, communication_id, message, captured_attachments, now)


def restore_retained(uow, communication_id, message, identity, captured_attachments, *, now):
    changed = uow.connection.execute("UPDATE communications SET subject=?,body_kind=?,body_text=?,fallback_canonical_json=?,"
        "content_state='RETAINED',content_revision=content_revision+1,updated_at_utc=? WHERE communication_id=? AND content_state='PURGED'",
        (normalized_source_text(message.subject, trim=True), message.body_kind, normalized_source_text(message.body, body=True),
         identity.fallback_canonical_json, now, communication_id))
    if changed.rowcount != 1:
        raise IntegrityFailure("Communication reconstruction lost its purged state")
    _children(uow, communication_id, message, captured_attachments, now)


def _children(uow, communication_id, message, captured_attachments, now):
    for item in message.participants:
        # Source/parser participant IDs cannot authorize Contact associations.
        # Contact review uses the separate owner lookup/validation boundary.
        uow.connection.execute("INSERT INTO communication_participants VALUES(?,?,?,?,?,?,NULL,NULL,?)",
            (new_uuid4(), communication_id, item.role, item.ordinal, normalized_address(item.address),
             normalized_source_text(item.display_name, trim=True), now))
    metadata = {item.ordinal: item for item in message.attachments}
    for captured in captured_attachments:
        item, attachment_id = metadata[captured.identity.ordinal], new_uuid4()
        uow.connection.execute("INSERT INTO communication_attachments VALUES(?,?,?,?,?,?,?,?)",
            (attachment_id, communication_id, item.ordinal, normalized_source_text(item.filename, trim=True),
             normalized_source_text(item.mime_type, trim=True), captured.identity.size_bytes,
             captured.identity.content_sha256, len(captured.chunks)))
        for ordinal, (content, digest) in enumerate(zip(captured.chunks, captured.chunk_digests)):
            uow.connection.execute("INSERT INTO communication_attachment_chunks VALUES(?,?,?,?)", (attachment_id, ordinal, content, digest))
