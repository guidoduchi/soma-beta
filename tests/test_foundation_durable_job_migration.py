from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory


_ACCEPTED_PREFIX_HASHES = {
    "0001_foundation.sql": "55fb2128a91fdb9e6851b43f88dd807a6f8050b78fe4f37d50069889b0c512b2",
    "0002_identity_reference.sql": "8fc0216adf7602b208e456f8c8996dcba1a65d1db8cac89c9a19afe308797e41",
    "0003_tickets_core.sql": "2ea24d491daa3ce564e8ee9f92d9e5a4d522c1941758d9646c505aeaaa875e56",
    "0004_ticket_import.sql": "50c73b844cf2cfeb6e7273ca1d4886cfd6992653dec3d1c7ca03d98cced607dd",
    "0005_command_replay_results.sql": "2aa0b287431d72c47af0e89d5ad28b00e4f21667c40e407fea87390caf826ba7",
    "0006_objectives_tasks.sql": "af73f2551a5022e91a5b37f9cdb4b41e6ac79a85dde9c99480b1eff506cd361d",
    "0007_sr_source_presence.sql": "f1e3723eaeee67936c0b7f531b42d0d6e4e690c4e297078b07e2f63bbfd8097b",
}
_SEQUENCE_EIGHT_SHA256 = "aab4126fbc9b1e29af3e6246798f837bfe681d3bde8fbe7b26962bd06b12c3e4"


def _factory_builder(security_provider):
    return lambda path: ConnectionFactory(path, security_provider, driver=sqlite3)


def _runner(path: Path, directory: Path, security_provider) -> MigrationRunner:
    return MigrationRunner(
        canonical_database_path=path,
        manifest=MigrationManifest.load(directory),
        factory_for_path=_factory_builder(security_provider),
        app_version="test",
        ownership_assertion=lambda: True,
    )


def _stage_prefix(source: Path, target: Path, count: int) -> None:
    target.mkdir()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    prefix = {"schema": manifest["schema"], "migrations": manifest["migrations"][:count]}
    for entry in prefix["migrations"]:
        shutil.copyfile(source / entry["filename"], target / entry["filename"])
    (target / "manifest.json").write_text(
        json.dumps(prefix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _schema(path: Path) -> list[tuple[str, str, str]]:
    connection = sqlite3.connect(path)
    try:
        return [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
        ]
    finally:
        connection.close()


def test_sequence_eight_manifest_is_contiguous_and_preserves_accepted_prefix_bytes(migration_directory) -> None:
    manifest = MigrationManifest.load(migration_directory)
    assert [entry.sequence for entry in manifest.entries] == list(range(1, 9))
    assert manifest.entries[-1].migration_id == "beta_0008_durable_job_coalescing"
    assert manifest.entries[-1].filename == "0008_durable_job_coalescing.sql"
    assert manifest.entries[-1].sha256 == _SEQUENCE_EIGHT_SHA256
    for filename, expected in _ACCEPTED_PREFIX_HASHES.items():
        assert hashlib.sha256((migration_directory / filename).read_bytes()).hexdigest() == expected
    assert hashlib.sha256(
        (migration_directory / "0008_durable_job_coalescing.sql").read_bytes()
    ).hexdigest() == _SEQUENCE_EIGHT_SHA256


def test_exact_prefix_seven_upgrade_matches_fresh_sequence_eight_and_preserves_legacy_jobs(
    tmp_path, migration_directory, security_provider
) -> None:
    prefix = tmp_path / "prefix-seven"
    _stage_prefix(migration_directory, prefix, 7)
    upgraded = tmp_path / "upgraded.db"
    fresh = tmp_path / "fresh.db"
    assert _runner(upgraded, prefix, security_provider).initialize_or_migrate() == 7

    connection = sqlite3.connect(upgraded)
    try:
        connection.execute(
            "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy-completed", "legacy.kind", 1, "completed", 10, 20, 1, None, None, None, '{"x":1}', '{"p":2}', "OLD_ERROR"),
        )
        connection.execute(
            "INSERT INTO job_attempts(attempt_id,job_id,ordinal,run_id,started_at_utc,finished_at_utc,outcome,error_code) VALUES (?,?,?,?,?,?,?,?)",
            ("attempt-1", "legacy-completed", 1, "run-old", 11, 19, "failed", "OLD_ERROR"),
        )
        connection.execute(
            "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy-queued", "legacy.kind", 1, "queued", 30, 30, 0, None, None, None, '{"q":1}', None, None),
        )
        before_jobs = connection.execute(
            "SELECT job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code FROM durable_jobs ORDER BY job_id"
        ).fetchall()
        before_attempts = connection.execute(
            "SELECT attempt_id,job_id,ordinal,run_id,started_at_utc,finished_at_utc,outcome,error_code FROM job_attempts ORDER BY attempt_id"
        ).fetchall()
        connection.commit()
    finally:
        connection.close()

    assert _runner(upgraded, migration_directory, security_provider).initialize_or_migrate() == 8
    assert _runner(fresh, migration_directory, security_provider).initialize_or_migrate() == 8
    assert _schema(upgraded) == _schema(fresh)

    connection = sqlite3.connect(upgraded)
    try:
        after_jobs = connection.execute(
            "SELECT job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code,dedupe_sha256 FROM durable_jobs ORDER BY job_id"
        ).fetchall()
        after_attempts = connection.execute(
            "SELECT attempt_id,job_id,ordinal,run_id,started_at_utc,finished_at_utc,outcome,error_code FROM job_attempts ORDER BY attempt_id"
        ).fetchall()
        assert [row[:-1] for row in after_jobs] == before_jobs
        assert all(row[-1] is None for row in after_jobs)
        assert after_attempts == before_attempts
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT sequence,migration_id FROM schema_migrations ORDER BY sequence"
        ).fetchall()[-1] == (8, "beta_0008_durable_job_coalescing")
    finally:
        connection.close()


def test_sequence_eight_constraints_and_indexes_are_exact(tmp_path, migration_directory, security_provider) -> None:
    database = tmp_path / "constraints.db"
    assert _runner(database, migration_directory, security_provider).initialize_or_migrate() == 8
    connection = sqlite3.connect(database)
    try:
        columns = [str(row[1]) for row in connection.execute("PRAGMA table_info(durable_jobs)")]
        assert columns[-1] == "dedupe_sha256"
        index_columns = {
            name: [str(row[2]) for row in connection.execute(f"PRAGMA index_info({name})")]
            for name in ("idx_jobs_dedupe_state", "uq_jobs_active_dedupe")
        }
        assert index_columns["idx_jobs_dedupe_state"] == [
            "job_type", "contract_version", "dedupe_sha256", "state"
        ]
        assert index_columns["uq_jobs_active_dedupe"] == [
            "job_type", "contract_version", "dedupe_sha256"
        ]
        active_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_jobs_active_dedupe'"
        ).fetchone()[0]
        for state in ("queued", "running", "waiting_review", "retry_wait"):
            assert state in active_sql

        base = (1, 1, 0, None, None, None, '{}', None, None)
        good_hash = "a" * 64
        connection.execute(
            "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code,dedupe_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("job-1", "kind", 1, "queued", *base, good_hash),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code,dedupe_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("job-2", "kind", 1, "retry_wait", 2, 2, 0, 3, None, None, '{}', None, None, good_hash),
            )
        connection.execute(
            "UPDATE durable_jobs SET state='completed' WHERE job_id='job-1'"
        )
        connection.execute(
            "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code,dedupe_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("job-2", "kind", 1, "queued", 2, 2, 0, None, None, None, '{}', None, None, good_hash),
        )
        for bad_hash in ("A" * 64, "a" * 63, "g" * 64):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code,dedupe_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"bad-{bad_hash[:4]}", "bad-kind", 1, "queued", 3, 3, 0, None, None, None, '{}', None, None, bad_hash),
                )
    finally:
        connection.close()


def test_failed_sequence_eight_upgrade_leaves_exact_prefix_seven(
    tmp_path, migration_directory, security_provider
) -> None:
    prefix = tmp_path / "prefix-seven"
    broken = tmp_path / "broken-eight"
    _stage_prefix(migration_directory, prefix, 7)
    _stage_prefix(migration_directory, broken, 8)
    migration = broken / "0008_durable_job_coalescing.sql"
    migration.write_text(
        migration.read_text(encoding="utf-8") + "INSERT INTO table_that_does_not_exist VALUES (1);\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = json.loads((broken / "manifest.json").read_text(encoding="utf-8"))
    manifest["migrations"][-1]["sha256"] = hashlib.sha256(migration.read_bytes()).hexdigest()
    (broken / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    database = tmp_path / "failed-upgrade.db"
    assert _runner(database, prefix, security_provider).initialize_or_migrate() == 7
    with pytest.raises(sqlite3.OperationalError):
        _runner(database, broken, security_provider).initialize_or_migrate()

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT MAX(sequence) FROM schema_migrations").fetchone()[0] == 7
        columns = [str(row[1]) for row in connection.execute("PRAGMA table_info(durable_jobs)")]
        assert "dedupe_sha256" not in columns
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN ('idx_jobs_dedupe_state','uq_jobs_active_dedupe')"
        ).fetchall() == []
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
