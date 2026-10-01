from __future__ import annotations

import hashlib
import sqlite3

import pytest

from soma.communications.services.housekeeping import HousekeepingService
from soma.communications.services.retention import reconcile_retention
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork


def seed(path, *, pending=True, due=220):
    scope, comm, attachment = new_uuid4(), new_uuid4(), new_uuid4()
    with sqlite3.connect(path) as connection:
        connection.execute('INSERT INTO communication_source_scopes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (scope, 'Mailbox', 'libpff', 'test', 'OPERATOR_CONFIRMED_LOCAL_SCOPE', new_uuid4(),
                            'ExternalSourceMustSurvive.pst', 'READY', 0, 1, 1, 1, 'mailbox'))
        connection.execute("INSERT INTO communications(communication_id,source_scope_id,provider_identity_kind,provider_identity_digest,provider_identity_bytes,fallback_version,fallback_digest,fallback_canonical_json,identity_state,chronology_known,chronology_source_kind,direction,subject,body_kind,body_text,content_state,content_revision,created_at_utc,updated_at_utc) VALUES (?,?, 'MAPI_RECORD_KEY',?,?,1,?,'{\"subject\":\"SecretSubject\"}','PROVIDER_STABLE',0,'UNKNOWN','RECEIVED','SecretSubject','TEXT','SecretBody','RETAINED',1,1,1)",
                           (comm, scope, 'a' * 64, b'provider-key', 'b' * 64))
        connection.execute('INSERT INTO communication_retention VALUES (?,?,?,?,?,1,100)',
                           (comm, 'ORPHAN_PENDING_PURGE' if pending else 'RETAINED', 100 if pending else None, due if pending else None, None))
        connection.execute("INSERT INTO communication_participants VALUES (?,?, 'FROM',0,'SecretAddress@example.com','SecretSender',NULL,NULL,1)", (new_uuid4(), comm))
        content = b'SecretAttachment'
        digest = hashlib.sha256(content).hexdigest()
        connection.execute('INSERT INTO communication_attachments VALUES (?,?,0,?,?,?, ?,1)', (attachment, comm, 'SecretFilename', 'text/plain', len(content), digest))
        connection.execute('INSERT INTO communication_attachment_chunks VALUES (?,0,?,?)', (attachment, content, digest))
    return comm


def search_count(connection):
    return connection.execute("SELECT count(*) FROM communication_search_fts WHERE communication_search_fts MATCH 'SecretBody'").fetchone()[0]


def test_lld09_a042_a044_a045_p005_due_purge_removes_content_and_preserves_identity(communication_database):
    path, factory = communication_database
    comm = seed(path)
    service = HousekeepingService(factory)
    assert service.select_due(now_utc=219) == []
    selected = service.select_due(now_utc=220)
    assert selected == [{'communication_id': comm, 'revision': 1, 'purge_due_utc': 220}]
    before = service.purge_due(command_id=new_uuid4(), communication_id=comm, selected_revision=1, now_utc=219)
    assert before['status'] == 'NO_CHANGE'
    command = new_uuid4()
    result = service.purge_due(command_id=command, communication_id=comm, selected_revision=1, now_utc=220)
    assert result['new_revision'] == 2
    assert service.purge_due(command_id=command, communication_id=comm, selected_revision=1, now_utc=220) == result
    assert service.purge_due(command_id=new_uuid4(), communication_id=comm, selected_revision=2, now_utc=300)['status'] == 'NO_CHANGE'
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT content_state,subject,body_text,body_kind,fallback_canonical_json,provider_identity_bytes,fallback_digest,content_revision FROM communications').fetchone() == ('PURGED', None, None, 'NONE', None, b'provider-key', 'b' * 64, 2)
        for table in ('communication_participants', 'communication_attachments', 'communication_attachment_chunks'):
            assert connection.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
        assert search_count(connection) == 0
        assert connection.execute('SELECT state,revision FROM communication_retention').fetchone() == ('PURGED', 2)
        assert connection.execute('SELECT count(*) FROM communication_retention_events').fetchone()[0] == 1
        audits = connection.execute('SELECT action_type,payload_json FROM audit_events').fetchall()
        assert len(audits) == 1 and audits[0][0] == 'communications.orphan_purged'
        assert 'Secret' not in audits[0][1] and 'ExternalSource' not in audits[0][1]
        assert connection.execute('SELECT processing_enabled,current_location FROM communication_source_scopes').fetchone() == (0, 'ExternalSourceMustSurvive.pst')


def test_lld09_a043_restored_hold_cancels_pending_purge_with_truthful_audit(communication_database):
    path, factory = communication_database
    comm = seed(path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO communication_protection_holds VALUES (?,?, 'PROTECTED_EXPORT',?,'ACTIVE',200,NULL)", (new_uuid4(), comm, new_uuid4()))
    service = HousekeepingService(factory)
    result = service.purge_due(command_id=new_uuid4(), communication_id=comm, selected_revision=1, now_utc=220)
    assert result['status'] == 'APPLIED'
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT state,purge_due_utc FROM communication_retention').fetchone() == ('RETAINED', None)
        assert connection.execute('SELECT subject,body_text FROM communications').fetchone() == ('SecretSubject', 'SecretBody')
        assert search_count(connection) == 1
        assert connection.execute('SELECT action_type FROM audit_events').fetchall() == [('communications.orphan_grace.cancelled',)]


def test_lld09_f009_purge_audit_failure_rolls_back_all_content_and_fts(communication_database, monkeypatch):
    path, factory = communication_database
    comm = seed(path)
    service = HousekeepingService(factory)
    command = new_uuid4()
    def fail(*args):
        raise RuntimeError('injected audit failure')
    monkeypatch.setattr(service._boundary._audit_writer, 'write', fail)
    with pytest.raises(RuntimeError):
        service.purge_due(command_id=command, communication_id=comm, selected_revision=1, now_utc=220)
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT state,revision FROM communication_retention').fetchone() == ('ORPHAN_PENDING_PURGE', 1)
        assert connection.execute('SELECT content_state,body_text FROM communications').fetchone() == ('RETAINED', 'SecretBody')
        assert search_count(connection) == 1
        assert connection.execute('SELECT count(*) FROM communication_attachment_chunks').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM command_receipts WHERE command_id=?', (command,)).fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM communication_retention_events').fetchone()[0] == 0


def receipt(uow):
    command = new_uuid4()
    uow.connection.execute('INSERT INTO command_receipts VALUES (?,?,?, ?,NULL,100,NULL,NULL)',
                           (command, 'test.dependency.changed', 'c' * 64, 'communication'))
    return command


def test_elapsed_grace_preserves_pending_due_and_records_each_cancelled_interval(communication_database):
    path, factory = communication_database
    comm = seed(path, pending=False)
    hold = new_uuid4()
    with UnitOfWork(factory) as uow:
        command = receipt(uow)
        started = reconcile_retention(uow, comm, dependency_event_id=new_uuid4(), event_time=100, grace_minutes=2, command_id=command)
        assert started.to_state == 'ORPHAN_PENDING_PURGE'
        assert reconcile_retention(uow, comm, dependency_event_id=new_uuid4(), event_time=120, grace_minutes=100, command_id=command) is None
        assert uow.connection.execute('SELECT purge_due_utc FROM communication_retention').fetchone()[0] == 220
        uow.connection.execute("INSERT INTO communication_protection_holds VALUES (?,?, 'PROPOSAL',?,'ACTIVE',150,NULL)", (hold, comm, new_uuid4()))
        cancelled = reconcile_retention(uow, comm, dependency_event_id=new_uuid4(), event_time=150, grace_minutes=5, command_id=command)
        assert cancelled.to_state == 'RETAINED'
        uow.connection.execute("UPDATE communication_protection_holds SET state='CLOSED',closed_at_utc=200 WHERE protection_hold_id=?", (hold,))
        restarted = reconcile_retention(uow, comm, dependency_event_id=new_uuid4(), event_time=200, grace_minutes=5, command_id=command)
        assert restarted.new_revision == 4
        assert uow.connection.execute('SELECT orphan_since_utc,purge_due_utc FROM communication_retention').fetchone() == (200, 500)
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT from_state,to_state FROM communication_retention_events ORDER BY recorded_at_utc').fetchall() == [('RETAINED', 'ORPHAN_PENDING_PURGE'), ('ORPHAN_PENDING_PURGE', 'RETAINED'), ('RETAINED', 'ORPHAN_PENDING_PURGE')]
