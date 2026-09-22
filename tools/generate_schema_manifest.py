from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory

_SCHEMA = "SOMA-RELEASE-SCHEMA-MANIFEST-V1"


class _BuildOnlySecurityProvider:
    """Build-time seam for generating a release schema contract.

    Production runtime never imports this tool and never substitutes plaintext SQLite
    for the LLD-12 SQLCipher provider.
    """

    @staticmethod
    def acquire_live_dek_handle() -> object:
        return object()

    @staticmethod
    def key_connection(connection: Any, key_handle: object) -> None:
        return None

    @staticmethod
    def verify_cipher_connection(connection: Any) -> None:
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()


def _factory(path: Path) -> ConnectionFactory:
    return ConnectionFactory(
        path,
        _BuildOnlySecurityProvider(),
        driver=sqlite3,
    )


def _schema_objects(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema "
        "WHERE type IN ('table','index','trigger') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type,name"
    ).fetchall()
    return [
        {
            "type": str(row[0]),
            "name": str(row[1]),
            "table_name": str(row[2]),
            "sql": None if row[3] is None else str(row[3]),
        }
        for row in rows
    ]


def _tables(connection: sqlite3.Connection) -> list[dict[str, object]]:
    table_flags = {
        str(row[1]): {
            "without_rowid": bool(int(row[4])),
            "strict": bool(int(row[5])),
        }
        for row in connection.execute("PRAGMA table_list").fetchall()
        if len(row) >= 6 and str(row[2]) == "table" and not str(row[1]).startswith("sqlite_")
    }
    tables: list[dict[str, object]] = []
    for table_name in sorted(table_flags):
        columns = [
            {
                "cid": int(row[0]),
                "name": str(row[1]),
                "declared_type": str(row[2]),
                "not_null": bool(int(row[3])),
                "default_sql": None if row[4] is None else str(row[4]),
                "primary_key_ordinal": int(row[5]),
                "hidden": int(row[6]),
            }
            for row in connection.execute(
                f"PRAGMA table_xinfo({json.dumps(table_name)})"
            ).fetchall()
        ]
        foreign_keys = [
            {
                "id": int(row[0]),
                "sequence": int(row[1]),
                "parent_table": str(row[2]),
                "child_column": None if row[3] is None else str(row[3]),
                "parent_column": None if row[4] is None else str(row[4]),
                "on_update": str(row[5]),
                "on_delete": str(row[6]),
                "match": str(row[7]),
            }
            for row in connection.execute(
                f"PRAGMA foreign_key_list({json.dumps(table_name)})"
            ).fetchall()
        ]
        tables.append(
            {
                "name": table_name,
                **table_flags[table_name],
                "columns": columns,
                "foreign_keys": foreign_keys,
            }
        )
    return tables


def _indexes(connection: sqlite3.Connection) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    table_names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    for table_name in table_names:
        for row in connection.execute(
            f"PRAGMA index_list({json.dumps(table_name)})"
        ).fetchall():
            index_name = str(row[1])
            if index_name.startswith("sqlite_"):
                continue
            keys = [
                {
                    "sequence": int(item[0]),
                    "cid": int(item[1]),
                    "name": None if item[2] is None else str(item[2]),
                    "descending": bool(int(item[3])),
                    "collation": None if item[4] is None else str(item[4]),
                    "key": bool(int(item[5])),
                }
                for item in connection.execute(
                    f"PRAGMA index_xinfo({json.dumps(index_name)})"
                ).fetchall()
            ]
            result.append(
                {
                    "name": index_name,
                    "table_name": table_name,
                    "unique": bool(int(row[2])),
                    "origin": str(row[3]),
                    "partial": bool(int(row[4])),
                    "keys": keys,
                }
            )
    result.sort(key=lambda item: str(item["name"]))
    return result


def build_manifest(repo_root: Path) -> dict[str, object]:
    migration_directory = repo_root / "src" / "soma" / "migrations"
    migration_manifest = MigrationManifest.load(migration_directory)

    with tempfile.TemporaryDirectory(prefix="soma-schema-manifest-") as temp:
        database = Path(temp) / "soma.db"
        runner = MigrationRunner(
            canonical_database_path=database,
            manifest=migration_manifest,
            factory_for_path=_factory,
            app_version="schema-manifest-generator",
            ownership_assertion=lambda: True,
        )
        runner.initialize_or_migrate()

        connection = sqlite3.connect(database)
        try:
            objects = _schema_objects(connection)
            tables = _tables(connection)
            indexes = _indexes(connection)
        finally:
            connection.close()

    return {
        "schema": _SCHEMA,
        "migration_lineage": [
            {
                "sequence": entry.sequence,
                "migration_id": entry.migration_id,
                "sha256": entry.sha256,
            }
            for entry in migration_manifest.entries
        ],
        "objects": objects,
        "tables": tables,
        "indexes": indexes,
    }


def render_manifest(repo_root: Path) -> str:
    return json.dumps(
        build_manifest(repo_root),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stdout-markers", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    rendered = render_manifest(repo_root)

    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    if args.stdout_markers:
        print("SOMA_SCHEMA_MANIFEST_BEGIN")
        print(rendered, end="")
        print("SOMA_SCHEMA_MANIFEST_END")
    if args.output is None and not args.stdout_markers:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
