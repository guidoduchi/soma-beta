"""Native development driver evidence; no plaintext authoritative substitute."""
import os
import secrets

import pytest

from soma.foundation.errors import SecurityNotReady
from soma.foundation.identifiers import new_uuid4
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.runtime.instance_lock import DataInstanceLock
from soma.security.crypto.live_key import LiveDataKeyProvider
from soma.security.crypto.sqlcipher_provider import SqlCipherConnectionSecurityProvider
from soma.security.runtime.windows import WindowsAclProvider

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows SQLCipher development wheel")


def test_real_encrypted_migrations_and_security_profile(tmp_path, migration_directory):
    pytest.importorskip("sqlcipher3", reason="local pinned native development wheel not installed")
    files = WindowsAclProvider()
    root = tmp_path / "encrypted-instance"
    files.ensure_owner_only_directory(root)
    files.ensure_owner_only_directory(root / "data")
    database = root / "data" / "soma.db"
    lock = DataInstanceLock.acquire(root / "data" / "soma.instance.lock")
    try:
        live_key = LiveDataKeyProvider(root, new_uuid4(), ownership_assertion=lambda: lock.held, file_security=files)
        live_key.prepare()
        provider = SqlCipherConnectionSecurityProvider(live_key)
        factory = lambda target: ConnectionFactory(target, provider)
        runner = MigrationRunner(canonical_database_path=database,
            manifest=MigrationManifest.load(migration_directory), factory_for_path=factory,
            app_version="native-source-development", ownership_assertion=lambda: lock.held)
        assert runner.initialize_or_migrate() == 19
        assert runner.initialize_or_migrate() == 19
        connection = factory(database).open_authoritative(read_only=False, require_wal=True)
        try:
            assert connection.execute("PRAGMA cipher_version").fetchone() == ("4.17.0 community",)
            assert provider.verify_cipher_connection(connection).cipher_version == "4.17.0"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone() == (19,)
            assert connection.execute("SELECT count(*) FROM security_auth_credentials").fetchone() == (0,)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
        assert not database.read_bytes().startswith(b"SQLite format 3\0")
        import sqlcipher3
        wrong = sqlcipher3.connect(str(database))
        try:
            provider.key_connection(wrong, secrets.token_bytes(32))
            with pytest.raises(SecurityNotReady):
                provider.verify_cipher_connection(wrong)
        finally:
            wrong.close()
    finally:
        lock.release()
