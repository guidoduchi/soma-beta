import hashlib
import sqlite3

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.verification import verify_foreign_key_index_coverage
from test_foundation_durable_job_migration import _runner, _stage_prefix, _schema


def test_prefix_fifteen_upgrade_matches_fresh_runtime_sixteen_and_preserves_history(tmp_path, migration_directory, security_provider):
    prefix = tmp_path / 'prefix-fifteen'
    _stage_prefix(migration_directory, prefix, 15)
    communication_release = tmp_path / 'prefix-sixteen'
    _stage_prefix(migration_directory, communication_release, 16)
    upgraded, fresh = tmp_path / 'upgraded.db', tmp_path / 'fresh.db'
    assert _runner(upgraded, prefix, security_provider).initialize_or_migrate() == 15
    with sqlite3.connect(upgraded) as db:
        old = db.execute('SELECT * FROM schema_migrations ORDER BY sequence').fetchall()
    assert _runner(upgraded, communication_release, security_provider).initialize_or_migrate() == 16
    assert _runner(fresh, communication_release, security_provider).initialize_or_migrate() == 16
    assert _schema(upgraded) == _schema(fresh)
    with sqlite3.connect(upgraded) as db:
        assert db.execute('SELECT * FROM schema_migrations ORDER BY sequence').fetchall()[:15] == old
        verify_foreign_key_index_coverage(db)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        plan = db.execute("EXPLAIN QUERY PLAN SELECT DISTINCT target_id,target_type,target_revision FROM communication_match_tokens "
            "WHERE job_id=? AND target_id IN (?) LIMIT 2", ('job', 'target')).fetchall()
        assert any('idx_comm_match_job_target' in row[3] for row in plan)
        assert not any('TEMP B-TREE' in row[3] for row in plan)
    entry = MigrationManifest.load(communication_release).entries[-1]
    assert entry.sequence == 16 and entry.migration_id == 'beta_0016_communications'
    assert hashlib.sha256((migration_directory / entry.filename).read_bytes()).hexdigest() == entry.sha256
