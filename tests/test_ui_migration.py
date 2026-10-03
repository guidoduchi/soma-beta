import sqlite3

from soma.foundation.migrations.verification import verify_foreign_key_index_coverage
from test_foundation_durable_job_migration import _runner, _stage_prefix, _schema


def test_prefix_sixteen_upgrade_matches_fresh_seventeen_without_rewriting_history(tmp_path, migration_directory, security_provider):
    prefix = tmp_path / 'prefix-sixteen'
    _stage_prefix(migration_directory, prefix, 16)
    ui_release = tmp_path / 'prefix-seventeen'
    _stage_prefix(migration_directory, ui_release, 17)
    upgraded, fresh = tmp_path / 'upgrade.db', tmp_path / 'fresh.db'
    assert _runner(upgraded, prefix, security_provider).initialize_or_migrate() == 16
    with sqlite3.connect(upgraded) as db:
        old = db.execute('SELECT * FROM schema_migrations ORDER BY sequence').fetchall()
    assert _runner(upgraded, ui_release, security_provider).initialize_or_migrate() == 17
    assert _runner(fresh, ui_release, security_provider).initialize_or_migrate() == 17
    assert _schema(upgraded) == _schema(fresh)
    with sqlite3.connect(upgraded) as db:
        assert db.execute('SELECT * FROM schema_migrations ORDER BY sequence').fetchall()[:16] == old
        verify_foreign_key_index_coverage(db)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
