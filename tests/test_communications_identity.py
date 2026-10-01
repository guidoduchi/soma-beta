from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from dataclasses import replace

import pytest

from soma.communications.contracts.common import Chronology, UNKNOWN_CHRONOLOGY
from soma.communications.contracts.message import CommunicationParticipant, ProviderMessageIdentity, TransientAttachment, TransientMessage
from soma.communications.contracts.source import ProviderCheckpoint, SourceFolder
from soma.communications.domain.communication import AttachmentIdentity, canonical_message_identity, normalized_address
from soma.communications.repositories.identity import resolve_identity
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot


def message(**changes):
    original = TransientMessage(SourceFolder('inbox', 'INBOX', 'Inbox'), None, Chronology(True, 100, 'RECEIVED_TIME'),
                                ' Subject\x00', 'TEXT', 'body\r\ntext\x00',
                                (CommunicationParticipant('FROM', 0, 'User@EXAMPLE.COM', ' Sender ', None),
                                 CommunicationParticipant('TO', 1, 'to@example.com', None, None)),
                                (), ProviderCheckpoint('POSITION', 'AA', 100001), ' <id@EXAMPLE> ', False)
    return replace(original, **changes)


def test_lld09_a017_a019_provider_binary_and_fallback_are_separate_identity_facts():
    scope = new_uuid4()
    original = message(provider_identity=ProviderMessageIdentity('MAPI_RECORD_KEY', b'\x00Ab\xff'))
    evidence = canonical_message_identity(scope, original, ())
    assert evidence.provider_digest == hashlib.sha256(b'MAPI_RECORD_KEY\x00\x00Ab\xff').hexdigest()
    obj = json.loads(evidence.fallback_canonical_json)
    assert obj['internet_message_id'] == '<id@EXAMPLE>'
    assert obj['from'][0] == {'role': 'FROM', 'ordinal': 0, 'address': 'User@example.com', 'display_name': 'Sender'}
    assert obj['body_sha256'] == hashlib.sha256(b'body\ntext').hexdigest()
    relocated = replace(original, folder=SourceFolder('relocated', 'INBOX', 'Different name'),
                        provider_position=ProviderCheckpoint('POSITION', 'BB', 999999))
    assert canonical_message_identity(scope, relocated, ()) == evidence
    assert canonical_message_identity(new_uuid4(), original, ()).fallback_digest != evidence.fallback_digest
    assert canonical_message_identity(scope, replace(original, internet_message_id='<different>'), ()).fallback_digest != evidence.fallback_digest
    assert canonical_message_identity(scope, replace(original, body='body\ntext'), ()).fallback_digest == evidence.fallback_digest
    assert canonical_message_identity(scope, replace(original, body='body\ntext '), ()).fallback_digest != evidence.fallback_digest
    conflict = canonical_message_identity(scope, replace(original, direction_conflict=True), ())
    assert json.loads(conflict.fallback_canonical_json)['direction'] == 'UNKNOWN'
    assert conflict.fallback_digest != evidence.fallback_digest
    with pytest.raises(ValidationError):
        replace(original, direction_conflict=1)
    assert original.independently_distinct_source_item is False
    assert canonical_message_identity(scope, replace(original, independently_distinct_source_item=True), ()) == evidence
    with pytest.raises(ValidationError):
        replace(original, independently_distinct_source_item=1)
    with pytest.raises(ValidationError):
        ProviderMessageIdentity.from_value({'kind': 'MAPI_RECORD_KEY', 'value_bytes_b64': 'AB==', 'normalization_version': 1})


def test_fallback_preserves_unknown_and_exact_local_part_and_requires_all_attachment_evidence():
    scope = new_uuid4()
    content = b'SecretAttachmentBytes'
    attachment = TransientAttachment(4, ' file.txt ', 'text/plain', len(content), io.BytesIO(content))
    transient = message(chronology=UNKNOWN_CHRONOLOGY, attachments=(attachment,))
    captured = (AttachmentIdentity(4, len(content), hashlib.sha256(content).hexdigest()),)
    result = canonical_message_identity(scope, transient, captured)
    obj = json.loads(result.fallback_canonical_json)
    assert obj['chronology'] == UNKNOWN_CHRONOLOGY.to_response()
    assert obj['attachments'] == [{'ordinal': 4, 'filename': 'file.txt', 'size_bytes': len(content), 'content_sha256': captured[0].content_sha256}]
    assert content.decode('ascii') not in result.fallback_canonical_json
    changed = message(participants=(CommunicationParticipant('FROM', 0, 'user@example.com', 'Sender', None),))
    assert canonical_message_identity(scope, changed, ()).fallback_digest != canonical_message_identity(scope, message(), ()).fallback_digest
    for evidence in ((), (replace(captured[0], size_bytes=0),), captured + captured):
        with pytest.raises(ValidationError):
            canonical_message_identity(scope, transient, evidence)


def test_fallback_evidence_budget_and_transient_limits_reject_without_truncation():
    huge = message(participants=(CommunicationParticipant('FROM', 0, 'sender@example.com', 'x' * 1048576, None),))
    with pytest.raises(ValidationError):
        canonical_message_identity(new_uuid4(), huge, ())
    with pytest.raises(ValidationError):
        message(subject='x' * 2049)
    with pytest.raises(ValidationError):
        message(body='x' * 5000001)
    with pytest.raises(ValidationError):
        message(participants=message().participants * 1001)
    with pytest.raises(ValidationError):
        TransientAttachment(0, 'file', None, 104857601, io.BytesIO())
    assert 'SecretBodyContent' not in repr(message(body='SecretBodyContent'))
    assert 'sender@example.com' not in repr(huge)


def test_reviewed_provider_alias_requires_exact_bytes_and_survives_purge(communication_database):
    from test_communications_housekeeping import seed
    from soma.communications.services.housekeeping import HousekeepingService
    path, factory = communication_database
    retained = seed(path)
    with sqlite3.connect(path) as db:
        scope = db.execute("SELECT source_scope_id FROM communications WHERE communication_id=?", (retained,)).fetchone()[0]
    incoming = message(provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"later-stronger-key"))
    evidence = canonical_message_identity(scope, incoming, ())
    alias = new_uuid4()
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_identity_aliases VALUES(?,?,?, ?,1,100,?)",
            (alias, retained, evidence.provider_kind, evidence.provider_digest, evidence.provider_bytes))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE communication_identity_aliases SET alias_evidence_bytes=? WHERE identity_alias_id=?", (b"different", alias))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO communication_identity_aliases VALUES(?,?,?, ?,1,100,NULL)",
                (new_uuid4(), retained, "PROVIDER_STABLE_OTHER", "f" * 64))
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, evidence).communication_id == retained
        assert resolve_identity(reader, scope, replace(evidence, provider_bytes=b"wrong-key")).disposition == "NEW"
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=retained, selected_revision=1, now_utc=220)
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, evidence).communication_id == retained
        assert reader.connection.execute("SELECT alias_evidence_bytes FROM communication_identity_aliases WHERE identity_alias_id=?", (alias,)).fetchone()[0] == evidence.provider_bytes


def test_address_normalization_preserves_international_local_bytes_and_unknown_sentinel():
    assert normalized_address(' \u00c9@EXAMPLE.COM ') == '\u00c9@example.com'
    assert normalized_address('"Foo Bar"@EXAMPLE.COM') == '"Foo Bar"@example.com'
    assert normalized_address('not an address') is None
    assert normalized_address(None) is None


def insert_scope(connection):
    scope = new_uuid4()
    connection.execute('INSERT INTO communication_source_scopes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (scope, 'Mailbox', 'libpff', 'test', 'OPERATOR_CONFIRMED_LOCAL_SCOPE', new_uuid4(),
                        'mail.pst', 'READY', 1, 1, 1, 1, 'mailbox'))
    return scope


def insert_message(connection, scope, identity, state):
    communication = new_uuid4()
    connection.execute('INSERT INTO communications(communication_id,source_scope_id,provider_identity_kind,provider_identity_digest,provider_identity_bytes,fallback_version,fallback_digest,fallback_canonical_json,identity_state,chronology_known,chronology_utc,chronology_source_kind,direction,subject,body_kind,body_text,content_state,content_revision,created_at_utc,updated_at_utc) VALUES (?,?,?,?,?,?,?,?,?,0,NULL,\'UNKNOWN\',\'RECEIVED\',\'subject\',\'TEXT\',\'body\',\'RETAINED\',1,1,1)',
                       (communication, scope, identity.provider_kind, identity.provider_digest, identity.provider_bytes,
                        1, identity.fallback_digest, identity.fallback_canonical_json, state))
    return communication


def test_lld09_a017_a020_digest_candidate_never_reuses_without_exact_evidence(communication_database):
    path, factory = communication_database
    with sqlite3.connect(path) as connection:
        scope = insert_scope(connection)
        identity = canonical_message_identity(scope, message(provider_identity=ProviderMessageIdentity('MAPI_RECORD_KEY', b'key')), ())
        stable = insert_message(connection, scope, identity, 'PROVIDER_STABLE')
        fallback_identity = canonical_message_identity(scope, message(internet_message_id='<fallback>'), ())
        fallback = insert_message(connection, scope, fallback_identity, 'FALLBACK')
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, identity).communication_id == stable
        assert resolve_identity(reader, scope, replace(identity, provider_bytes=b'different')).disposition == 'COLLISION_REVIEW'
        assert resolve_identity(reader, scope, fallback_identity).communication_id == fallback
        assert resolve_identity(reader, scope, fallback_identity, independently_distinct_source_item=True).disposition == 'COLLISION_REVIEW'
        assert resolve_identity(reader, scope, replace(fallback_identity, fallback_canonical_json='{}')).disposition == 'COLLISION_REVIEW'
        assert resolve_identity(reader, scope, canonical_message_identity(scope, message(internet_message_id='<new>'), ())).disposition == 'NEW'
    with sqlite3.connect(path) as connection:
        connection.execute('UPDATE communications SET fallback_canonical_json=NULL,subject=NULL,body_text=NULL,body_kind=\'NONE\',content_state=\'PURGED\' WHERE communication_id=?', (fallback,))
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, scope, fallback_identity).disposition == 'COLLISION_REVIEW'


def test_provider_identity_scope_isolation_and_fallback_version_changes_are_explicit(communication_database):
    from soma.communications.domain.communication import require_fallback_evidence
    path, factory = communication_database
    value = message(provider_identity=ProviderMessageIdentity('MAPI_RECORD_KEY', b'same-exact-key'))
    with sqlite3.connect(path) as db:
        first, second = insert_scope(db), insert_scope(db)
        identity = canonical_message_identity(first, value, ())
        canonical = insert_message(db, first, identity, 'PROVIDER_STABLE')
    with ReadSnapshot(factory) as reader:
        assert resolve_identity(reader, first, identity).communication_id == canonical
        assert resolve_identity(reader, second, canonical_message_identity(second, value, ())).disposition == 'NEW'
    assert canonical_message_identity(first, value, ()) == identity
    require_fallback_evidence(first, 1, identity.fallback_canonical_json)
    with pytest.raises(ValidationError):
        require_fallback_evidence(first, 2, identity.fallback_canonical_json)
