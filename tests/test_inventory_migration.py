from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory

_SEQUENCE_TEN_SHA256 = "9c5d4ffe2c28e60b8d5a826a35fe833522af5cf5e02d97bd160b358225309ab9"
_OWNED_TABLES = [
    'inventory_tracking_allocators',
    'device_part_units',
    'device_part_lifecycle_events',
    'device_part_current_projection',
    'spare_needs',
    'spare_need_lifecycle_events',
    'spare_need_current_projection',
    'spare_need_active_keys',
    'spare_need_contributors',
    'spare_requests',
    'spare_request_need_allocations',
    'spare_request_draft_logistics',
    'spare_request_lifecycle_events',
    'spare_request_identifier_events',
    'spare_request_identifier_aliases',
    'spare_request_submission_snapshots',
    'spare_request_submission_allocations',
    'spare_request_current_projection',
    'rma_authorization_batches',
    'rmas',
    'rma_identifier_events',
    'rma_identifier_aliases',
    'rma_assignment_events',
    'rma_current_assignment',
    'spare_part_units',
    'rma_direct_inbound_units',
    'spare_part_lifecycle_events',
    'spare_part_current_projection',
    'task_unit_allocation_events',
    'task_unit_allocation_current',
    'local_need_fulfillment_events',
    'inventory_physical_consequences',
    'physical_consequence_events',
    'physical_consequence_current',
    'rma_return_selection_events',
    'rma_return_obligation_current',
    'actual_logistics_events',
    'logistics_rma_participants',
    'logistics_spare_unit_participants',
    'logistics_device_part_participants',
    'fault_tags',
    'fault_tag_memberships',
    'fault_tag_lifecycle_events',
    'fault_tag_submission_snapshots',
    'fault_tag_membership_submission_snapshots',
    'fault_tag_membership_events',
    'fault_tag_membership_current',
    'fault_tag_current_projection',
    'fault_tag_lineage',
    'rma_lifecycle_projection',
    'inventory_lifecycle_batches',
    'inventory_proposals',
    'inventory_proposal_targets',
    'inventory_attention_projection'
]


def _factory_builder(security_provider):
    return lambda path: ConnectionFactory(path, security_provider, driver=sqlite3)


def test_sequence_ten_inventory_manifest_and_full_backbone(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    manifest = MigrationManifest.load(migration_directory)
    assert [entry.sequence for entry in manifest.entries] == list(range(1, 11))
    entry = manifest.entries[9]
    assert entry.migration_id == "beta_0010_inventory"
    assert entry.filename == "0010_inventory.sql"
    assert entry.sha256 == _SEQUENCE_TEN_SHA256
    assert hashlib.sha256(
        (migration_directory / entry.filename).read_bytes()
    ).hexdigest() == _SEQUENCE_TEN_SHA256

    database = tmp_path / "sequence-ten.db"
    runner = MigrationRunner(
        canonical_database_path=database,
        manifest=manifest,
        factory_for_path=_factory_builder(security_provider),
        app_version="test",
        ownership_assertion=lambda: True,
    )
    assert runner.initialize_or_migrate() == 10

    connection = sqlite3.connect(database)
    try:
        actual = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert set(_OWNED_TABLES) <= actual
        for table in _OWNED_TABLES:
            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
            assert str(table_sql).rstrip().endswith("STRICT")

        allocators = connection.execute(
            "SELECT allocator_kind,next_sequence,revision,last_command_id "
            "FROM inventory_tracking_allocators ORDER BY allocator_kind"
        ).fetchall()
        assert allocators == [
            ("device_part_creation", 1, 1, None),
            ("fault_tag", 1, 1, None),
            ("local_spare_unit", 1, 1, None),
            ("spare_request", 1, 1, None),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT sequence,migration_id FROM schema_migrations ORDER BY sequence DESC LIMIT 1"
        ).fetchone() == (10, "beta_0010_inventory")
    finally:
        connection.close()



def _stage_prefix(source, target, count: int) -> None:
    target.mkdir()
    raw = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    prefix = {"schema": raw["schema"], "migrations": raw["migrations"][:count]}
    for entry in prefix["migrations"]:
        shutil.copyfile(source / entry["filename"], target / entry["filename"])
    (target / "manifest.json").write_text(
        json.dumps(prefix, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _schema(path):
    connection = sqlite3.connect(path)
    try:
        return [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
        ]
    finally:
        connection.close()


def test_exact_sequence_nine_upgrade_matches_fresh_sequence_ten(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    prefix = tmp_path / "prefix-nine"
    _stage_prefix(migration_directory, prefix, 9)
    upgraded = tmp_path / "upgraded.db"
    fresh = tmp_path / "fresh.db"

    prefix_runner = MigrationRunner(
        canonical_database_path=upgraded,
        manifest=MigrationManifest.load(prefix),
        factory_for_path=_factory_builder(security_provider),
        app_version="test",
        ownership_assertion=lambda: True,
    )
    assert prefix_runner.initialize_or_migrate() == 9

    current_manifest = MigrationManifest.load(migration_directory)
    upgraded_runner = MigrationRunner(
        canonical_database_path=upgraded,
        manifest=current_manifest,
        factory_for_path=_factory_builder(security_provider),
        app_version="test",
        ownership_assertion=lambda: True,
    )
    fresh_runner = MigrationRunner(
        canonical_database_path=fresh,
        manifest=current_manifest,
        factory_for_path=_factory_builder(security_provider),
        app_version="test",
        ownership_assertion=lambda: True,
    )
    assert upgraded_runner.initialize_or_migrate() == 10
    assert fresh_runner.initialize_or_migrate() == 10
    assert _schema(upgraded) == _schema(fresh)

    connection = sqlite3.connect(upgraded)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT sequence,migration_id FROM schema_migrations ORDER BY sequence"
        ).fetchall()[-1] == (10, "beta_0010_inventory")
    finally:
        connection.close()
