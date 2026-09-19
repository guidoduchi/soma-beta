from __future__ import annotations

import hashlib
import sqlite3

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory

_SEQUENCE_NINE_SHA256 = "2ea6c47e1f3ffc1b8894a41e7b2b9f73481396703b543c10b0a7d06473811059"
_OWNED_TABLES = {
    "product_lines",
    "contracts",
    "contract_product_lines",
    "sla_classification_mappings",
    "sr_classification_events",
    "sr_classification_current",
    "sla_policy_revisions",
    "sla_policy_tiers",
    "sla_report_attempts",
    "sla_report_member_snapshots",
    "sla_report_member_tier_results",
    "sla_report_cohort_snapshots",
    "report_section_snapshots",
    "sla_report_job_refs",
}


def _factory_builder(security_provider):
    return lambda path: ConnectionFactory(path, security_provider, driver=sqlite3)


def test_sequence_nine_manifest_and_relational_backbone_are_exact(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    manifest = MigrationManifest.load(migration_directory)
    assert [entry.sequence for entry in manifest.entries[:9]] == list(range(1, 10))
    sequence_nine = manifest.entries[8]
    assert sequence_nine.migration_id == "beta_0009_product_line_sla"
    assert sequence_nine.filename == "0009_product_line_sla.sql"
    assert sequence_nine.sha256 == _SEQUENCE_NINE_SHA256
    assert hashlib.sha256(
        (migration_directory / sequence_nine.filename).read_bytes()
    ).hexdigest() == _SEQUENCE_NINE_SHA256

    database = tmp_path / "sequence-nine.db"
    runner = MigrationRunner(
        canonical_database_path=database,
        manifest=manifest,
        factory_for_path=_factory_builder(security_provider),
        app_version="test",
        ownership_assertion=lambda: True,
    )
    current_sequence = manifest.entries[-1].sequence
    current_migration_id = manifest.entries[-1].migration_id
    assert runner.initialize_or_migrate() == current_sequence

    connection = sqlite3.connect(database)
    try:
        actual_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert _OWNED_TABLES <= actual_tables

        for table in sorted(_OWNED_TABLES):
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
            assert str(sql).rstrip().endswith("STRICT")

        trigger_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert {
            "cpl_policy_owner_update_guard",
            "sla_policy_revision_update_guard",
            "sla_policy_tier_update_guard",
            "sr_classification_event_update_guard",
            "sla_report_terminal_update_guard",
            "sla_report_complete_counts_guard",
            "sla_report_member_insert_guard",
            "sla_report_tier_insert_guard",
            "sla_report_cohort_insert_guard",
            "report_section_insert_guard",
        } <= trigger_names
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT sequence,migration_id FROM schema_migrations ORDER BY sequence DESC LIMIT 1"
        ).fetchone() == (current_sequence, current_migration_id)
    finally:
        connection.close()
