"""Synthetic registered contracts prove the mechanism, not production entries."""
import json
import sqlite3
from pathlib import Path

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract
from soma.reference.application.profile_service import LocalUserProfileService
from soma.ui.commands import WorkingCopyCommands
from soma.ui.contracts import WorkingCopyContractRegistry, WorkingCopyDraftContract
from soma.ui.queries import WorkingCopyQueries
from test_reference_final_authorities import _parent_receipt


@pytest.fixture
def ui_database(communication_database):
    path, factory = communication_database
    parent = new_uuid4()
    with UnitOfWork(factory) as writer:
        _parent_receipt(writer, parent, 'FirstRunSetup')
        profile = LocalUserProfileService(factory).ensure_singleton_local_administrator(writer, parent_command_id=parent)
    return path, factory, profile


def registry():
    def validate(value):
        if not isinstance(value['note'], str):
            raise ValidationError('Synthetic note requires text')
    return WorkingCopyContractRegistry((WorkingCopyDraftContract('SYNTHETIC_TARGET', 'synthetic.notes',
        ObjectContract('SyntheticNoteDraftV1', 1, frozenset({'note'}), frozenset({'note'}), max_utf8_bytes=262144),
        frozenset({'/note'}), validate, require_uuid4),))


def request(*, target=None, expected=0, note='PRIVATE_SYNTHETIC_CANARY'):
    return {'command_id': new_uuid4(), 'key': {'target_type': 'SYNTHETIC_TARGET', 'target_id': target or new_uuid4(), 'scope_key': 'synthetic.notes'},
        'expected_generation': expected, 'payload': {'draft_contract_id': 'SyntheticNoteDraftV1', 'draft_contract_version': 1,
        'base_revision_token': 'owner-revision-1', 'draft': {'note': note}, 'dirty_paths': ['/note']}}


class RevisionReader:
    value = 'owner-revision-1'
    def current_revision_token(self, snapshot, *args):
        return self.value


def test_checkpoint_generation_expiry_nochange_and_exact_metadata_replay_after_discard(ui_database):
    path, factory, profile = ui_database
    clock = [1000]
    commands = WorkingCopyCommands(factory, registry(), clock=lambda: clock[0])
    value = request()
    first = commands.checkpoint_working_copy(value, owner_profile_id=profile)
    assert set(first) == {'working_copy_id', 'generation', 'content_hash', 'updated_at_utc', 'expires_at_utc'}
    assert first['generation'] == 1 and first['expires_at_utc'] == 605800
    clock[0] = 1100
    same = commands.checkpoint_working_copy(value | {'command_id': new_uuid4(), 'expected_generation': 1}, owner_profile_id=profile)
    assert same == first
    changed = commands.checkpoint_working_copy(value | {'command_id': new_uuid4(), 'expected_generation': 1,
        'payload': value['payload'] | {'draft': {'note': 'changed synthetic intent'}}}, owner_profile_id=profile)
    assert changed['generation'] == 2 and changed['expires_at_utc'] == 605900
    discard = {'command_id': new_uuid4(), 'working_copy_id': first['working_copy_id'], 'expected_generation': 2}
    deleted = commands.discard_working_copy(discard, owner_profile_id=profile)
    assert commands.discard_working_copy(discard, owner_profile_id=profile) == deleted
    assert commands.checkpoint_working_copy(value, owner_profile_id=profile) == first
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM ui_working_copies').fetchone() == (0,)
        for table, column in (('audit_events', 'payload_json'), ('command_receipt_results', 'response_json')):
            text = '\n'.join(row[0] for row in db.execute(f'SELECT {column} FROM {table}'))
            assert 'PRIVATE_SYNTHETIC_CANARY' not in text and 'changed synthetic intent' not in text
    with pytest.raises(SomaError) as absent:
        commands.discard_working_copy(discard | {'command_id': new_uuid4()}, owner_profile_id=profile)
    assert absent.value.code == 'UI_WORKING_COPY_NOT_FOUND'


@pytest.mark.parametrize('freshness,value', [('CURRENT', 'owner-revision-1'), ('STALE', 'owner-revision-2'), ('TARGET_MISSING', 'MISSING'), ('INDETERMINATE', 'INDETERMINATE')])
def test_restore_is_read_only_and_classifies_owner_freshness(ui_database, freshness, value):
    path, factory, profile = ui_database
    saved = WorkingCopyCommands(factory, registry(), clock=lambda: 1000).checkpoint_working_copy(request(), owner_profile_id=profile)
    reader = RevisionReader(); reader.value = value
    query = WorkingCopyQueries(factory, registry(), reader, clock=lambda: 1001)
    result = query.get_working_copy({'working_copy_id': saved['working_copy_id']}, owner_profile_id=profile)['restore']
    assert result['freshness'] == freshness
    assert result['restore_allowed'] == (freshness in {'CURRENT', 'STALE'})
    assert result['requires_conflict_review'] == (freshness == 'STALE')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT generation FROM ui_working_copies').fetchone() == (1,)


def test_empty_production_registry_and_closed_synthetic_schema_fail_before_mutation(ui_database):
    path, factory, profile = ui_database
    value = request()
    for contract_registry, payload in (
        (WorkingCopyContractRegistry(), value),
        (registry(), value | {'payload': value['payload'] | {'draft': {'note': 'safe', 'unknown': True}}}),
        (registry(), value | {'payload': value['payload'] | {'dirty_paths': ['/unknown']}}),
        (registry(), value | {'payload': value['payload'] | {'draft_contract_version': True}}),
    ):
        with pytest.raises(SomaError) as result:
            WorkingCopyCommands(factory, contract_registry).checkpoint_working_copy(payload, owner_profile_id=profile)
        assert result.value.code == 'UI_WORKING_COPY_CONTRACT_INVALID'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM ui_working_copies').fetchone() == (0,)


def test_failed_audit_rolls_back_checkpoint_receipt_and_discard(ui_database, monkeypatch):
    path, factory, profile = ui_database
    commands = WorkingCopyCommands(factory, registry(), clock=lambda: 1000)
    value = request()
    original = commands._boundary._audit_writer.write
    def fail(*args):
        raise RuntimeError('injected audit failure')
    monkeypatch.setattr(commands._boundary._audit_writer, 'write', fail)
    with pytest.raises(RuntimeError):
        commands.checkpoint_working_copy(value, owner_profile_id=profile)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM ui_working_copies').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM command_receipts WHERE command_id=?', (value['command_id'],)).fetchone() == (0,)
    monkeypatch.setattr(commands._boundary._audit_writer, 'write', original)
    saved = commands.checkpoint_working_copy(value, owner_profile_id=profile)
    monkeypatch.setattr(commands._boundary._audit_writer, 'write', fail)
    with pytest.raises(RuntimeError):
        commands.discard_working_copy({'command_id': new_uuid4(), 'working_copy_id': saved['working_copy_id'], 'expected_generation': 1}, owner_profile_id=profile)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT generation FROM ui_working_copies').fetchone() == (1,)


def test_cursor_filter_identity_and_generation_conflicts_preserve_newer_copy(ui_database):
    _, factory, profile = ui_database
    commands = WorkingCopyCommands(factory, registry(), clock=lambda: 1000)
    reader = RevisionReader(); query = WorkingCopyQueries(factory, registry(), reader, clock=lambda: 1001)
    saved = [commands.checkpoint_working_copy(request(), owner_profile_id=profile) for _ in range(3)]
    page = query.list_restore_candidates({'limit': 1}, owner_profile_id=profile)
    assert len(page['items']) == 1 and len(page['next_cursor']['last_key_tuple']) == 2
    with pytest.raises(SomaError) as invalid:
        query.list_restore_candidates({'limit': 1, 'target_type': 'other', 'cursor': page['next_cursor']}, owner_profile_id=profile)
    assert invalid.value.code == 'INVALID_CURSOR'
    with pytest.raises(SomaError) as conflict:
        commands.discard_working_copy({'command_id': new_uuid4(), 'working_copy_id': saved[0]['working_copy_id'], 'expected_generation': 2}, owner_profile_id=profile)
    assert conflict.value.code == 'UI_WORKING_COPY_CONFLICT'
    assert query.get_working_copy({'working_copy_id': saved[0]['working_copy_id']}, owner_profile_id=new_uuid4())['state'] == 'NOT_FOUND'


def test_installation_capacity_refresh_and_bounded_expiry_prune_with_exact_replay(ui_database):
    path, factory, profile = ui_database
    clock = [1000]
    commands = WorkingCopyCommands(factory, registry(), clock=lambda: clock[0])
    values = [request() for _ in range(256)]
    results = [commands.checkpoint_working_copy(value, owner_profile_id=profile) for value in values]
    with pytest.raises(SomaError) as capacity:
        commands.checkpoint_working_copy(request(), owner_profile_id=profile)
    assert capacity.value.code == 'UI_WORKING_COPY_CAPACITY'
    clock[0] = 1001
    refreshed = commands.checkpoint_working_copy(values[0] | {'command_id': new_uuid4(), 'expected_generation': 1,
        'payload': values[0]['payload'] | {'draft': {'note': 'refreshed intent'}}}, owner_profile_id=profile)
    assert refreshed['generation'] == 2
    clock[0] = 605800
    prune = {'command_id': new_uuid4(), 'batch_limit': 100}
    assert commands.prune_expired_working_copies(prune) == {'deleted_count': 100, 'more_due': True}
    assert commands.prune_expired_working_copies(prune) == {'deleted_count': 100, 'more_due': True}
    assert commands.prune_expired_working_copies(prune | {'command_id': new_uuid4()}) == {'deleted_count': 100, 'more_due': True}
    assert commands.prune_expired_working_copies(prune | {'command_id': new_uuid4()}) == {'deleted_count': 55, 'more_due': False}
    assert commands.prune_expired_working_copies(prune | {'command_id': new_uuid4()}) == {'deleted_count': 0, 'more_due': False}
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT working_copy_id,generation FROM ui_working_copies').fetchall() == [(results[0]['working_copy_id'], 2)]
        assert 'idx_ui_working_copy_expiry' in ' '.join(str(row) for row in db.execute(
            'EXPLAIN QUERY PLAN SELECT working_copy_id FROM ui_working_copies WHERE expires_at_utc<=? ORDER BY expires_at_utc,working_copy_id LIMIT 100', (clock[0],)))


def test_payload_utf8_bound_and_duplicate_metadata_integrity(ui_database):
    from soma.foundation.errors import IntegrityFailure
    path, factory, profile = ui_database
    commands = WorkingCopyCommands(factory, registry(), clock=lambda: 1000)
    with pytest.raises(SomaError) as too_large:
        commands.checkpoint_working_copy(request(note='\u00e9' * 131072), owner_profile_id=profile)
    assert too_large.value.code == 'UI_WORKING_COPY_TOO_LARGE'
    saved = commands.checkpoint_working_copy(request(), owner_profile_id=profile)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE ui_working_copies SET base_revision_token=?', ('tampered duplicate',))
    with pytest.raises(IntegrityFailure):
        WorkingCopyQueries(factory, registry(), RevisionReader(), clock=lambda: 1001).get_working_copy(
            {'working_copy_id': saved['working_copy_id']}, owner_profile_id=profile)


def test_routes_use_authenticated_actor_and_never_accept_client_owner_identity(ui_database):
    from types import SimpleNamespace
    from soma.ui.routes import WorkingCopyRoutes
    _, factory, profile = ui_database
    class Security:
        def validate_request(self, request, mutation):
            assert request == 'authenticated transport'
            assert mutation is True
            return SimpleNamespace(actor_id=profile)
    routes = WorkingCopyRoutes(WorkingCopyCommands(factory, registry(), clock=lambda: 1000),
        WorkingCopyQueries(factory, registry(), RevisionReader()), Security())
    value = request()
    result = routes.dispatch('POST', '/api/v1/ui/working-copies/checkpoint', 'authenticated transport', value)
    assert result.response_type == 'WorkingCopyCheckpointResultV1'
    assert 'payload' not in result.body
    with pytest.raises(ValidationError):
        routes.dispatch('POST', '/api/v1/ui/working-copies/checkpoint', 'authenticated transport', value | {'owner_profile_id': new_uuid4()})


@pytest.mark.parametrize('failure_point', ['row', 'receipt', 'result'])
def test_checkpoint_write_failures_leave_no_partial_authority_and_retry_succeeds(ui_database, monkeypatch, failure_point):
    """F001-F003: fail after each actual write, including immutable result storage."""
    path, factory, profile = ui_database
    commands = WorkingCopyCommands(factory, registry(), clock=lambda: 1000)
    value = request()
    owner, method = {
        'row': (commands._repository, 'insert'),
        'receipt': (commands._boundary._receipt_store, 'insert'),
        'result': (commands._boundary._receipt_store, 'insert_exact_result'),
    }[failure_point]
    original = getattr(owner, method)
    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError('injected failure after write')
    with sqlite3.connect(path) as db:
        baseline = db.execute('SELECT count(*) FROM audit_events').fetchone()
    with monkeypatch.context() as patch:
        patch.setattr(owner, method, fail_after_write)
        with pytest.raises(sqlite3.OperationalError):
            commands.checkpoint_working_copy(value, owner_profile_id=profile)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM ui_working_copies').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM command_receipts WHERE command_id=?', (value['command_id'],)).fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM command_receipt_results WHERE command_id=?', (value['command_id'],)).fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM audit_events').fetchone() == baseline
    saved = commands.checkpoint_working_copy(value, owner_profile_id=profile)
    assert saved['generation'] == 1
    assert commands.checkpoint_working_copy(value, owner_profile_id=profile) == saved


def test_cleanup_interruption_after_partial_delete_rolls_back_whole_batch(ui_database, monkeypatch):
    """F005: cancellation unwinds the UoW even for a BaseException interruption."""
    path, factory, profile = ui_database
    clock = [1000]
    commands = WorkingCopyCommands(factory, registry(), clock=lambda: clock[0])
    saved = [commands.checkpoint_working_copy(request(), owner_profile_id=profile) for _ in range(3)]
    prune = {'command_id': new_uuid4(), 'batch_limit': 100}
    clock[0] = 605800
    original = commands._repository.delete
    deleted = []
    def interrupt_after_second_delete(writer, identity, generation):
        original(writer, identity, generation)
        deleted.append(identity)
        if len(deleted) == 2:
            raise KeyboardInterrupt('injected cleanup interruption')
    with sqlite3.connect(path) as db:
        baseline = db.execute('SELECT count(*) FROM audit_events').fetchone()
    with monkeypatch.context() as patch:
        patch.setattr(commands._repository, 'delete', interrupt_after_second_delete)
        with pytest.raises(KeyboardInterrupt):
            commands.prune_expired_working_copies(prune)
    with sqlite3.connect(path) as db:
        assert set(db.execute('SELECT working_copy_id,generation FROM ui_working_copies')) == {(row['working_copy_id'], 1) for row in saved}
        assert db.execute('SELECT count(*) FROM command_receipts WHERE command_id=?', (prune['command_id'],)).fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM command_receipt_results WHERE command_id=?', (prune['command_id'],)).fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM audit_events').fetchone() == baseline
    assert commands.prune_expired_working_copies(prune) == {'deleted_count': 3, 'more_due': False}
