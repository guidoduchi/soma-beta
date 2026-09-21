from __future__ import annotations

import shutil
import sqlite3

import pytest

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope
from soma.foundation.audit.registry import AuditRegistry
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import (
    MigrationError,
    PersistenceFailure,
    PersistenceRollbackFailure,
    ValidationError,
)
from soma.foundation.identifiers import new_uuid4
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract, canonical_json_bytes, loads_strict


@pytest.mark.parametrize('fingerprint', ['g' * 64, 'A' * 64, 'é' * 64, '0' * 63, '0' * 65, None, 64])
def test_authorizing_fingerprint_fails_before_opening_connection(fingerprint):
    class UnavailableFactory:
        def open_authoritative(self, **kwargs):
            pytest.fail('invalid authorization reached persistence')

    envelope = CommandEnvelope(
        new_uuid4(), 'Test', 'test', None, {}, authorizing_fingerprints={'review': fingerprint}
    )
    with pytest.raises(ValidationError):
        CommandBoundary(UnavailableFactory(), AuditWriter(AuditRegistry())).execute(
            envelope, lambda uow: pytest.fail('invalid authorization reached preparation')
        )


def test_lowercase_hex_fingerprint_remains_valid():
    envelope = CommandEnvelope(
        new_uuid4(), 'Test', 'test', None, {}, authorizing_fingerprints={'review': '0123456789abcdef' * 4}
    )
    assert len(envelope.request_hash()) == 64


@pytest.mark.parametrize('rollback_fails', [False, True])
def test_commit_failure_explicitly_rolls_back_and_surfaces_rollback_failure(initialized_database, rollback_fails):
    path, factory_for_path = initialized_database
    factory = factory_for_path(path)
    operations = []

    class FailingConnection:
        def __init__(self, connection):
            self.connection = connection

        @property
        def in_transaction(self):
            return self.connection.in_transaction

        def execute(self, statement, *args):
            operations.append(statement)
            if statement == 'COMMIT' or (rollback_fails and statement == 'ROLLBACK'):
                raise sqlite3.OperationalError('injected private transport detail')
            return self.connection.execute(statement, *args)

        def close(self):
            operations.append('CLOSE')
            self.connection.close()

    class FailingFactory:
        def open_authoritative(self, **kwargs):
            return FailingConnection(factory.open_authoritative(**kwargs))

    expected = PersistenceRollbackFailure if rollback_fails else PersistenceFailure
    with pytest.raises(expected) as failure:
        with UnitOfWork(FailingFactory()) as uow:
            uow.connection.execute('CREATE TABLE rollback_probe(value INTEGER) STRICT')
    assert operations[-3:] == ['COMMIT', 'ROLLBACK', 'CLOSE']
    assert 'private transport detail' not in str(failure.value)
    with UnitOfWork(factory) as uow:
        assert uow.connection.execute("SELECT 1 FROM sqlite_schema WHERE name='rollback_probe'").fetchone() is None


@pytest.mark.parametrize('drift', ['changed_sql', 'unlisted_migration'])
def test_migration_drift_after_manifest_load_fails_before_database_creation(tmp_path, migration_directory, security_provider, drift):
    directory = tmp_path / 'migrations'
    shutil.copytree(migration_directory, directory)
    manifest = MigrationManifest.load(directory)
    if drift == 'changed_sql':
        first = directory / manifest.entries[0].filename
        first.write_bytes(first.read_bytes() + b'CREATE TABLE unaccepted(value INTEGER) STRICT;\n')
    else:
        (directory / '9999_unlisted.sql').write_bytes(b'CREATE TABLE unaccepted(value INTEGER) STRICT;\n')
    opened = []

    def factory_for_path(path):
        opened.append(path)
        return ConnectionFactory(path, security_provider, driver=sqlite3)

    path = tmp_path / 'soma.db'
    runner = MigrationRunner(
        canonical_database_path=path, manifest=manifest, factory_for_path=factory_for_path,
        app_version='test', ownership_assertion=lambda: True,
    )
    with pytest.raises(MigrationError):
        runner.initialize_or_migrate()
    assert opened == []
    assert not path.exists()


def test_migration_bytes_are_revalidated_before_execution(tmp_path, migration_directory):
    directory = tmp_path / 'migrations'
    shutil.copytree(migration_directory, directory)
    manifest = MigrationManifest.load(directory)
    entry = manifest.entries[0]
    path = directory / entry.filename
    path.write_bytes(path.read_bytes() + b'CREATE TABLE unaccepted(value INTEGER) STRICT;\n')
    with pytest.raises(MigrationError) as failure:
        manifest.text(entry)
    assert failure.value.code == 'MIGRATION_HASH_MISMATCH'


@pytest.mark.parametrize('document', [
    '{"value":1e999}', '{"value":-1e999}',
    r'{"value":"\ud800"}', r'{"\udfff":"value"}',
    '{"value":"\ud800"}',
])
def test_strict_json_rejects_invalid_unicode_and_overflow(document):
    with pytest.raises(ValidationError):
        loads_strict(document)


def test_json_contract_enforces_declared_depth_without_recursion_error():
    contract = ObjectContract('Test', 1, frozenset({'value'}), frozenset({'value'}))
    value = 0
    for _ in range(2000):
        value = [value]
    with pytest.raises(ValidationError):
        contract.validate({'value': value})


def test_json_valid_surrogate_pair_and_finite_numbers_remain_valid():
    assert loads_strict(r'{"value":"\ud83d\ude00","n":1e300}') == {'value': '😀', 'n': 1e300}


def test_canonical_json_rejects_unpaired_surrogate_with_stable_error():
    with pytest.raises(ValidationError):
        canonical_json_bytes({'value': '\ud800'})


def test_json_validation_errors_do_not_echo_untrusted_keys():
    private = 'private_source_path_and_credential'
    with pytest.raises(ValidationError) as duplicate:
        loads_strict('{"' + private + '":0,"' + private + '":1}')
    assert private not in str(duplicate.value)
    contract = ObjectContract('Test', 1, frozenset(), frozenset())
    with pytest.raises(ValidationError) as unknown:
        contract.validate({private: 1})
    assert private not in str(unknown.value)
