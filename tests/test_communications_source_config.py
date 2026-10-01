from __future__ import annotations

import sqlite3

import pytest

from soma.communications.contracts.source import SourceFolder, SourceProbe
from soma.communications.queries.previews import CommunicationPreviews
from soma.communications.queries.sources import SourceQueries
from soma.communications.services.source_config import SourceConfigurationService
from soma.foundation.errors import IdempotencyConflict, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4


class ReadOnlyAdapter:
    def __init__(self, candidate='mailbox-A'):
        self.calls = 0
        self.fail = False
        self.candidate = candidate

    def probe_read_only(self, location, profile):
        self.calls += 1
        if self.fail:
            raise AssertionError('Exact replay must not open source content')
        return SourceProbe('READY', 'libpff', 'test-1', self.candidate,
                           (SourceFolder('inbox', 'INBOX', 'Inbox'), SourceFolder('sent', 'SENT', 'Sent')))


def request(scope=None, revision=None, location='mail.pst'):
    return {'source_scope_id': scope, 'base_revision': revision, 'display_name': 'Mailbox',
            'source_location': location, 'selected_folder_keys': ['inbox']}


def configure(service, previews, value, command=None):
    preview = previews.preview_source_scope_configuration(value)
    payload = {key: item for key, item in value.items() if key != 'selected_folder_keys'}
    payload.update(command_id=command or new_uuid4(), preview_fingerprint=preview['preview_fingerprint'],
                   selected_folders=[folder for folder in preview['probe']['folders'] if folder['folder_key'] in value['selected_folder_keys']])
    return service.configure_source_scope(payload), payload


def test_lld09_a001_a002_scope_relocation_preserves_identity_and_replay(communication_database):
    path, factory = communication_database
    adapter = ReadOnlyAdapter()
    service, previews = SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter)
    created, original = configure(service, previews, request())
    relocated, payload = configure(service, previews, request(created['target_id'], 1, 'moved.pst'))
    assert relocated['target_id'] == created['target_id']
    assert relocated['new_revision'] == 2
    adapter.fail = True
    assert service.configure_source_scope(payload) == relocated
    assert service.configure_source_scope(original) == created
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT count(*) FROM communication_source_scopes').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM communication_source_scope_events').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM audit_events WHERE action_type=?', ('communications.source_scope.configured',)).fetchone()[0] == 2
        assert 'moved.pst' not in str(connection.execute('SELECT payload_json FROM audit_events').fetchall())
    changed = payload | {'display_name': 'Changed'}
    with pytest.raises(IdempotencyConflict):
        service.configure_source_scope(changed)


def test_semantic_no_change_creates_replay_only_and_no_false_history(communication_database):
    path, factory = communication_database
    adapter = ReadOnlyAdapter()
    service, previews = SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter)
    created, _ = configure(service, previews, request())
    result, payload = configure(service, previews, request(created['target_id'], 1))
    assert result == {'status': 'NO_CHANGE', 'target_id': created['target_id'], 'new_revision': 1, 'result_refs': []}
    adapter.fail = True
    assert service.configure_source_scope(payload) == result
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT count(*) FROM communication_source_scope_events').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM command_receipts').fetchone()[0] == 2


def test_lld09_a003_different_mailbox_cannot_reuse_existing_scope(communication_database):
    path, factory = communication_database
    adapter = ReadOnlyAdapter()
    service, previews = SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter)
    created, _ = configure(service, previews, request())
    adapter.candidate = 'mailbox-B'
    review = previews.preview_source_scope_configuration(request(created['target_id'], 1))
    assert review['identity_disposition'] == 'RECONCILIATION_REQUIRED'
    with pytest.raises(SomaError) as raised:
        configure(service, previews, request(created['target_id'], 1))
    assert raised.value.code == 'COMM_SOURCE_SCOPE_CONFLICT'
    different, _ = configure(service, previews, request())
    assert different['target_id'] != created['target_id']


def test_stale_preview_and_audit_failure_leave_no_scope_or_receipt(communication_database, monkeypatch):
    path, factory = communication_database
    adapter = ReadOnlyAdapter()
    service, previews = SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter)
    preview = previews.preview_source_scope_configuration(request())
    payload = {key: item for key, item in request().items() if key != 'selected_folder_keys'}
    payload.update(command_id=new_uuid4(), preview_fingerprint=preview['preview_fingerprint'], selected_folders=[preview['probe']['folders'][0]])
    adapter.candidate = 'mailbox-B'
    with pytest.raises(SomaError) as raised:
        service.configure_source_scope(payload)
    assert raised.value.code == 'COMM_STALE'
    def fail_audit(*args):
        raise RuntimeError('injected audit failure')
    monkeypatch.setattr(service._boundary._audit_writer, 'write', fail_audit)
    with pytest.raises(RuntimeError):
        configure(service, previews, request())
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT count(*) FROM communication_source_scopes').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM command_receipts').fetchone()[0] == 0


def test_local_confirmed_scope_identity_is_path_independent(communication_database):
    path, factory = communication_database
    adapter = ReadOnlyAdapter(None)
    service, previews = SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter)
    first, _ = configure(service, previews, request())
    with sqlite3.connect(path) as connection:
        before = connection.execute('SELECT scope_identity_value FROM communication_source_scopes').fetchone()[0]
    configure(service, previews, request(first['target_id'], 1, 'renamed.pst'))
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT scope_identity_kind,scope_identity_value FROM communication_source_scopes').fetchone() == ('OPERATOR_CONFIRMED_LOCAL_SCOPE', before)


def test_source_pages_keep_complete_folded_tie_key_and_bound_filters(communication_database):
    path, factory = communication_database
    adapter = ReadOnlyAdapter()
    service, previews = SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter)
    ids = []
    for index, name in enumerate(('Alpha', 'ALPHA', 'Beta', 'Ａｌｐｈａ')):
        adapter.candidate = f'mailbox-{index}'
        result, _ = configure(service, previews, request() | {'display_name': name})
        ids.append(result['target_id'])
    queries = SourceQueries(factory)
    adapter.fail = True
    seen, cursor = [], None
    while True:
        page = queries.list_source_scopes({'limit': 1, 'cursor': cursor})
        assert len(page['items']) == 1
        item = page['items'][0]
        assert set(item) == {'source_scope_id', 'revision', 'display_name', 'health_state', 'processing_enabled', 'selected_folders'}
        seen.append(item['source_scope_id'])
        cursor = page['next_cursor']
        if cursor is None:
            break
        assert len(cursor['last_key_tuple']) == 2
    assert seen == sorted((ids[0], ids[1], ids[3])) + [ids[2]]
    first = queries.list_source_scopes({'limit': 1})['next_cursor']
    for value in ({'cursor': first, 'health_state': 'PARTIAL'}, {'cursor': first | {'version': True}},
                  {'cursor': first | {'last_key_tuple': ['alpha']}}, {'limit': True}, {'limit': 101}):
        with pytest.raises(ValidationError):
            queries.list_source_scopes(value)
    with sqlite3.connect(path) as connection:
        for sql, params in (
            ('SELECT source_scope_id FROM communication_source_scopes WHERE (display_name_folded,source_scope_id)>(?,?) ORDER BY display_name_folded,source_scope_id LIMIT ?', ('alpha', ids[0], 2)),
            ('SELECT source_scope_id FROM communication_source_scopes WHERE health_state=? AND (display_name_folded,source_scope_id)>(?,?) ORDER BY display_name_folded,source_scope_id LIMIT ?', ('READY', 'alpha', ids[0], 2)),
        ):
            plan = str(connection.execute('EXPLAIN QUERY PLAN ' + sql, params).fetchall())
            assert 'SEARCH' in plan and 'TEMP B-TREE' not in plan
