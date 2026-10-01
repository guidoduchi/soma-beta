import hashlib
import sqlite3
from io import BytesIO

import pytest

from soma.communications.contracts.message import CommunicationParticipant, ProviderMessageIdentity, TransientAttachment
from soma.communications.domain.attachments import capture_attachments, CHUNK_BYTES
from soma.communications.domain.communication import canonical_message_identity
from soma.communications.repositories.communications import insert_retained
from soma.communications.repositories.identity import resolve_identity
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from test_communications_housekeeping import seed
from test_communications_identity import message


def test_owned_content_write_uses_captured_bytes_normalization_and_exact_identity(communication_database):
    path, factory = communication_database
    seed(path, pending=False)
    with sqlite3.connect(path) as db:
        scope = db.execute("SELECT source_scope_id FROM communication_source_scopes LIMIT 1").fetchone()[0]
    content = b"abcd" * (CHUNK_BYTES // 4 + 3)
    stream = BytesIO(content)
    transient = message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"immutable-key"),
        participants=(CommunicationParticipant("FROM", 0, "User@EXAMPLE.COM", " Sender ", new_uuid4()),),
        attachments=(TransientAttachment(5, " file.bin ", "application/octet-stream", len(content), stream),))
    captured = capture_attachments(transient)
    identity = canonical_message_identity(scope, transient, tuple(item.identity for item in captured))
    stream.seek(0)
    stream.write(b"different source bytes")
    communication, hold = new_uuid4(), new_uuid4()
    with UnitOfWork(factory) as writer:
        insert_retained(writer, communication, scope, transient, identity, captured, identity_state="PROVIDER_STABLE", now=1000)
        writer.connection.execute("INSERT INTO communication_retention VALUES(?,'RETAINED',NULL,NULL,?,1,1000)", (communication, hold))
        writer.connection.execute("INSERT INTO communication_protection_holds VALUES(?,?,'COLLISION_REVIEW',?,'ACTIVE',1000,NULL)", (hold, communication, communication))
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, identity).communication_id == communication
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT subject,body_text,direction,chronology_utc FROM communications WHERE communication_id=?", (communication,)).fetchone() == ("Subject", "body\ntext", "RECEIVED", 100)
        assert db.execute("SELECT normalized_address,display_name,contact_id,contact_revision FROM communication_participants WHERE communication_id=?", (communication,)).fetchone() == ("User@example.com", "Sender", None, None)
        attachment = db.execute("SELECT communication_attachment_id,ordinal,filename,size_bytes,sha256,chunk_count FROM communication_attachments WHERE communication_id=?", (communication,)).fetchone()
        assert attachment[1:] == (5, "file.bin", len(content), hashlib.sha256(content).hexdigest(), 2)
        chunks = db.execute("SELECT content,chunk_sha256 FROM communication_attachment_chunks WHERE communication_attachment_id=? ORDER BY chunk_index", (attachment[0],)).fetchall()
        assert b"".join(row[0] for row in chunks) == content
        assert all(hashlib.sha256(row[0]).hexdigest() == row[1] for row in chunks)
        assert db.execute("SELECT count(*) FROM communication_search_fts WHERE communication_search_fts MATCH 'body' AND rowid=(SELECT rowid FROM communications WHERE communication_id=?)", (communication,)).fetchone()[0] == 1


def test_owned_content_failure_rolls_back_body_children_search_and_identity(communication_database):
    path, factory = communication_database
    seed(path, pending=False)
    with sqlite3.connect(path) as db:
        scope = db.execute("SELECT source_scope_id FROM communication_source_scopes LIMIT 1").fetchone()[0]
    transient = message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"rollback-key"),
        attachments=(TransientAttachment(0, "example.txt", None, 3, BytesIO(b"abc")),))
    captured = capture_attachments(transient)
    identity = canonical_message_identity(scope, transient, tuple(item.identity for item in captured))
    communication = new_uuid4()
    with pytest.raises(RuntimeError), UnitOfWork(factory) as writer:
        insert_retained(writer, communication, scope, transient, identity, captured, identity_state="PROVIDER_STABLE", now=1000)
        raise RuntimeError("injected caller failure after complete content write")
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, identity).disposition == "NEW"
    with sqlite3.connect(path) as db:
        for table in ("communications", "communication_participants", "communication_attachments"):
            assert db.execute(f"SELECT count(*) FROM {table} WHERE communication_id=?", (communication,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM communication_search_fts WHERE communication_search_fts MATCH 'body'").fetchone()[0] == 0
