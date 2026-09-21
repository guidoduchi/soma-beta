from __future__ import annotations

import sqlite3

import pytest

from soma.foundation.errors import PersistenceConnectionUnsafe
from soma.foundation.persistence.connections import ConnectionFactory


@pytest.mark.parametrize(
    ('pragma', 'unsafe_value'),
    [
        ('foreign_keys', 'OFF'),
        ('busy_timeout', '0'),
        ('trusted_schema', 'ON'),
        ('temp_store', 'FILE'),
        ('synchronous', 'OFF'),
        ('secure_delete', 'OFF'),
        ('read_uncommitted', 'ON'),
        ('wal_autocheckpoint', '10'),
    ],
)
def test_ignored_safety_setting_blocks_authoritative_connection(
    initialized_database, security_provider, pragma, unsafe_value,
):
    path, _ = initialized_database
    opened = []

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, *args):
            if statement.startswith(f'PRAGMA {pragma}='):
                return self.connection.execute('SELECT 0')
            return self.connection.execute(statement, *args)

        def enable_load_extension(self, enabled):
            self.connection.enable_load_extension(enabled)

        def close(self):
            self.connection.close()

    class Driver:
        def connect(self, database, **kwargs):
            connection = sqlite3.connect(database, **kwargs)
            connection.execute(f'PRAGMA {pragma}={unsafe_value}')
            opened.append(connection)
            return Connection(connection)

    factory = ConnectionFactory(path, security_provider, driver=Driver())
    with pytest.raises(PersistenceConnectionUnsafe):
        factory.open_authoritative()
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        opened[0].execute('SELECT 1')


@pytest.mark.parametrize('failure', [AttributeError, NotImplementedError, sqlite3.OperationalError])
def test_extension_disable_failure_blocks_and_closes_connection(
    initialized_database, security_provider, failure,
):
    path, _ = initialized_database
    opened = []

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, *args):
            return self.connection.execute(*args)

        def enable_load_extension(self, enabled):
            assert enabled is False
            raise failure('private provider diagnostic')

        def close(self):
            self.connection.close()

    class Driver:
        def connect(self, database, **kwargs):
            connection = sqlite3.connect(database, **kwargs)
            opened.append(connection)
            return Connection(connection)

    with pytest.raises(PersistenceConnectionUnsafe) as caught:
        ConnectionFactory(path, security_provider, driver=Driver()).open_authoritative()
    assert 'private provider diagnostic' not in str(caught.value)
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        opened[0].execute('SELECT 1')


def test_read_connection_verifies_all_required_settings(initialized_database):
    path, factory_for_path = initialized_database
    connection = factory_for_path(path).open_authoritative(read_only=True)
    try:
        expected = {
            'foreign_keys': 1, 'busy_timeout': 5000, 'trusted_schema': 0,
            'temp_store': 2, 'synchronous': 2, 'secure_delete': 2,
            'read_uncommitted': 0, 'wal_autocheckpoint': 1000, 'query_only': 1,
        }
        for pragma, value in expected.items():
            assert connection.execute(f'PRAGMA {pragma}').fetchone() == (value,)
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            connection.execute('CREATE TABLE forbidden(value TEXT) STRICT')
    finally:
        connection.close()
