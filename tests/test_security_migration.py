"""Forward allocation and complete security schema, using the test-only driver."""
import sqlite3

import pytest

from test_foundation_durable_job_migration import _runner, _schema, _stage_prefix


def test_overview_noop_and_full_security_upgrade_preserve_accepted_history(
    tmp_path, migration_directory, security_provider
):
    seventeen, eighteen = tmp_path / "17", tmp_path / "18"
    _stage_prefix(migration_directory, seventeen, 17)
    _stage_prefix(migration_directory, eighteen, 18)
    upgraded, fresh = tmp_path / "upgrade.db", tmp_path / "fresh.db"
    assert _runner(upgraded, seventeen, security_provider).initialize_or_migrate() == 17
    before_schema = _schema(upgraded)
    with sqlite3.connect(upgraded) as db:
        history = db.execute("SELECT * FROM schema_migrations ORDER BY sequence").fetchall()
    assert _runner(upgraded, eighteen, security_provider).initialize_or_migrate() == 18
    assert _schema(upgraded) == before_schema
    assert _runner(upgraded, migration_directory, security_provider).initialize_or_migrate() == 19
    assert _runner(fresh, migration_directory, security_provider).initialize_or_migrate() == 19
    assert _schema(upgraded) == _schema(fresh)
    with sqlite3.connect(upgraded) as db:
        assert db.execute("SELECT * FROM schema_migrations ORDER BY sequence").fetchall()[:17] == history
        tables = {r[1]: r[5] for r in db.execute("PRAGMA table_list")}
        for name in ("security_auth_credentials", "security_auto_login", "managed_backup_catalog"):
            assert tables[name] == 1  # STRICT
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_list(security_auth_credentials)").fetchone()[2:7] == (
            "local_user_profiles", "local_user_profile_id", "local_user_profile_id", "RESTRICT", "RESTRICT"
        )
        assert [r[2] for r in db.execute("PRAGMA index_xinfo(idx_managed_backup_verified_created)") if r[5]] == [
            "state", "created_at_utc", "backup_id"
        ]


def test_security_storage_constraints_and_immutable_backup_identity(initialized_database):
    path, _ = initialized_database
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO security_auth_credentials VALUES(1,'absent',?,'ARGON2ID_V1',1,0,0,?)", ("x" * 32, bytes(32)))
        db.execute("INSERT INTO local_user_profiles VALUES('profile',1,'Local Administrator',1,0,0)")
        db.execute("INSERT INTO security_auth_credentials VALUES(1,'profile',?,'ARGON2ID_V1',1,0,0,?)", ("x" * 32, bytes(32)))
        with pytest.raises(sqlite3.IntegrityError, match="DELETE forbidden"):
            db.execute("DELETE FROM security_auth_credentials")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE security_auth_credentials SET security_revision=0")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE security_auth_credentials SET updated_at_utc=-1")
        db.execute("INSERT INTO security_auto_login VALUES(1,'credential',?,0,1,0)", (bytes(32),))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE security_auto_login SET token_verifier_sha256=x'00'")
        db.execute("INSERT INTO managed_backup_catalog VALUES('backup',1,'building','backup.soma',NULL,19,NULL,NULL,1)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE managed_backup_catalog SET state='verified'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE managed_backup_catalog SET created_at_utc=2")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE managed_backup_catalog SET backup_id='other'")
        db.execute("UPDATE managed_backup_catalog SET state='verified',artifact_sha256=?,verified_at_utc=2", (bytes(32),))
        db.execute("UPDATE managed_backup_catalog SET state='pruned'")
        assert db.execute("SELECT artifact_sha256,created_at_utc FROM managed_backup_catalog").fetchone() == (bytes(32), 1)
