from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from importlib.resources import files
from typing import Any

from soma.foundation.errors import MigrationError

FOUNDATION_TABLES = {
    "instance_metadata",
    "schema_migrations",
    "command_receipts",
    "command_receipt_results",
    "audit_events",
    "audit_event_results",
    "durable_jobs",
    "job_attempts",
}

FOUNDATION_INDEXES = {
    "idx_audit_recorded_at",
    "idx_audit_target",
    "idx_audit_command",
    "idx_jobs_state_due",
    "idx_jobs_type_state",
}

FOUNDATION_TRIGGERS = {
    "audit_events_before_update_append_only",
    "audit_events_before_delete_append_only",
    "audit_event_results_before_update_append_only",
    "audit_event_results_before_delete_append_only",
    "command_receipt_results_before_update_append_only",
    "command_receipt_results_before_delete_append_only",
}

_RELEASE_SCHEMA = "SOMA-RELEASE-SCHEMA-MANIFEST-V1"


def _schema_error(message: str) -> MigrationError:
    return MigrationError("MIGRATION_SCHEMA_MISMATCH", message)


def _load_release_manifest() -> dict[str, object]:
    try:
        raw = files("soma").joinpath("schema_manifest.json").read_text(encoding="utf-8")
        value = json.loads(raw)
    except Exception as exc:
        raise _schema_error("release schema manifest is unavailable or invalid") from exc
    if not isinstance(value, dict) or value.get("schema") != _RELEASE_SCHEMA:
        raise _schema_error("release schema manifest contract is invalid")
    for key in ("migration_lineage", "objects", "tables", "indexes"):
        if not isinstance(value.get(key), list):
            raise _schema_error(f"release schema manifest {key} is invalid")
    return value


def verify_foreign_keys(connection: Any) -> None:
    failures = connection.execute("PRAGMA foreign_key_check").fetchall()
    if failures:
        raise MigrationError(
            "MIGRATION_FOREIGN_KEY_FAILURE",
            f"foreign_key_check returned {len(failures)} row(s)",
        )


def _verify_quick_check(connection: Any) -> None:
    rows = connection.execute("PRAGMA quick_check").fetchall()
    if len(rows) != 1 or str(rows[0][0]).lower() != "ok":
        raise MigrationError(
            "MIGRATION_INTEGRITY_FAILURE",
            "quick_check did not return exactly one ok row",
        )


def _sqlite_master_names(connection: Any, object_type: str) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = ? AND name NOT LIKE 'sqlite_%'",
        (object_type,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _actual_objects(connection: Any) -> list[dict[str, object]]:
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
            "sql_sha256": (
                None
                if row[3] is None
                else hashlib.sha256(str(row[3]).encode("utf-8")).hexdigest()
            ),
        }
        for row in rows
    ]


def _actual_tables(connection: Any) -> list[dict[str, object]]:
    table_flags = {
        str(row[1]): {
            "without_rowid": bool(int(row[4])),
            "strict": bool(int(row[5])),
        }
        for row in connection.execute("PRAGMA table_list").fetchall()
        if len(row) >= 6
        and str(row[2]) == "table"
        and not str(row[1]).startswith("sqlite_")
    }
    result: list[dict[str, object]] = []
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
        foreign_keys.sort(key=lambda item: (int(item["id"]), int(item["sequence"])))
        result.append(
            {
                "name": table_name,
                **table_flags[table_name],
                "columns": columns,
                "foreign_keys": foreign_keys,
            }
        )
    return result


def _actual_indexes(connection: Any) -> list[dict[str, object]]:
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
                }
                for item in connection.execute(
                    f"PRAGMA index_xinfo({json.dumps(index_name)})"
                ).fetchall()
                if bool(int(item[5]))
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


def _normalized_tables(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise _schema_error("release schema table contract is invalid")
    normalized: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise _schema_error("release schema table entry is invalid")
        copied = dict(item)
        foreign_keys = copied.get("foreign_keys")
        if not isinstance(foreign_keys, list):
            raise _schema_error("release schema foreign-key contract is invalid")
        copied["foreign_keys"] = sorted(
            (dict(fk) for fk in foreign_keys),
            key=lambda fk: (int(fk["id"]), int(fk["sequence"])),
        )
        normalized.append(copied)
    return normalized


def _verify_exact_contract(
    *,
    label: str,
    expected: object,
    actual: object,
) -> None:
    if expected == actual:
        return
    if isinstance(expected, list) and isinstance(actual, list):
        expected_names = {
            str(item.get("name"))
            for item in expected
            if isinstance(item, dict) and "name" in item
        }
        actual_names = {
            str(item.get("name"))
            for item in actual
            if isinstance(item, dict) and "name" in item
        }
        missing = sorted(expected_names - actual_names)[:8]
        extra = sorted(actual_names - expected_names)[:8]
        changed = sorted(
            expected_names & actual_names
        )[:8] if not missing and not extra else []
        raise _schema_error(
            f"{label} differs from release manifest: "
            f"missing={missing!r} extra={extra!r} changed_candidates={changed!r}"
        )
    raise _schema_error(f"{label} differs from release manifest")


def _verify_migration_lineage(connection: Any, manifest: dict[str, object]) -> bool:
    expected = manifest["migration_lineage"]
    if not isinstance(expected, list) or not expected:
        raise _schema_error("release migration lineage contract is invalid")
    actual = [
        {
            "sequence": int(row[0]),
            "migration_id": str(row[1]),
            "sha256": str(row[2]),
        }
        for row in connection.execute(
            "SELECT sequence,migration_id,sha256 FROM schema_migrations ORDER BY sequence"
        ).fetchall()
    ]
    if not actual or len(actual) > len(expected) or actual != expected[: len(actual)]:
        raise _schema_error("database migration lineage differs from release manifest")
    return len(actual) == len(expected)


def _expect_rejected(
    connection: Any,
    sql: str,
    params: tuple[object, ...],
    *,
    label: str,
) -> None:
    try:
        connection.execute(sql, params)
    except Exception:
        return
    raise _schema_error(f"append-only verification probe was accepted for {label}")


def _verify_append_only_behavior(connection: Any) -> None:
    marker = "__soma_schema_verification_probe__"
    command_id = marker + "command"
    audit_event_id = marker + "audit"
    connection.execute("SAVEPOINT soma_schema_verification_probe")
    try:
        connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id"
            ") VALUES (?, 'SchemaVerificationProbe', ?, 'schema_verification', NULL, 0, NULL, NULL)",
            (command_id, "0" * 64),
        )
        connection.execute(
            "INSERT INTO command_receipt_results("
            "command_id,response_schema,response_version,response_json,response_sha256"
            ") VALUES (?, 'SchemaVerificationProbeV1', 1, '{}', ?)",
            (command_id, "0" * 64),
        )
        _expect_rejected(
            connection,
            "UPDATE command_receipt_results SET response_version=response_version WHERE command_id=?",
            (command_id,),
            label="command_receipt_results update",
        )
        _expect_rejected(
            connection,
            "DELETE FROM command_receipt_results WHERE command_id=?",
            (command_id,),
            label="command_receipt_results delete",
        )

        connection.execute(
            "INSERT INTO audit_events("
            "audit_event_id,action_type,action_version,recorded_at_utc,actor_kind,"
            "target_type,target_id,command_id,payload_schema,payload_version,payload_json"
            ") VALUES (?, 'schema.verification_probe', 1, 0, 'system',"
            "'schema_verification', NULL, ?, 'SchemaVerificationProbeV1', 1, '{}')",
            (audit_event_id, command_id),
        )
        _expect_rejected(
            connection,
            "UPDATE audit_events SET action_type=action_type WHERE audit_event_id=?",
            (audit_event_id,),
            label="audit_events update",
        )
        _expect_rejected(
            connection,
            "DELETE FROM audit_events WHERE audit_event_id=?",
            (audit_event_id,),
            label="audit_events delete",
        )

        connection.execute(
            "INSERT INTO audit_event_results("
            "audit_event_id,ordinal,result_type,result_id"
            ") VALUES (?, 0, 'schema_verification', 'probe')",
            (audit_event_id,),
        )
        _expect_rejected(
            connection,
            "UPDATE audit_event_results SET ordinal=ordinal WHERE audit_event_id=? AND ordinal=0",
            (audit_event_id,),
            label="audit_event_results update",
        )
        _expect_rejected(
            connection,
            "DELETE FROM audit_event_results WHERE audit_event_id=? AND ordinal=0",
            (audit_event_id,),
            label="audit_event_results delete",
        )
    except MigrationError:
        raise
    except Exception as exc:
        raise _schema_error("append-only verification probe could not be executed") from exc
    finally:
        try:
            connection.execute("ROLLBACK TO SAVEPOINT soma_schema_verification_probe")
        finally:
            connection.execute("RELEASE SAVEPOINT soma_schema_verification_probe")


def verify_foundation_schema(connection: Any) -> None:
    manifest = _load_release_manifest()
    verify_foreign_keys(connection)
    _verify_quick_check(connection)
    is_current_release = _verify_migration_lineage(connection, manifest)

    rows = connection.execute(
        "SELECT singleton,data_instance_id FROM instance_metadata"
    ).fetchall()
    if len(rows) != 1 or int(rows[0][0]) != 1 or not str(rows[0][1]):
        raise _schema_error("instance_metadata must contain exactly one valid singleton row")

    # Historical migration-prefix databases are valid inputs to the forward-only
    # migration runner. Their ledger must be an exact prefix of the accepted
    # release lineage, but the current-release structural manifest cannot be
    # applied until the runner has brought them to the full accepted lineage.
    if not is_current_release:
        return

    _verify_exact_contract(
        label="authoritative schema objects",
        expected=manifest["objects"],
        actual=_actual_objects(connection),
    )
    _verify_exact_contract(
        label="table structure",
        expected=_normalized_tables(manifest["tables"]),
        actual=_actual_tables(connection),
    )
    _verify_exact_contract(
        label="index structure",
        expected=manifest["indexes"],
        actual=_actual_indexes(connection),
    )

    _verify_append_only_behavior(connection)


def verify_expected_objects(
    connection: Any,
    *,
    tables: Iterable[str] = (),
    indexes: Iterable[str] = (),
    triggers: Iterable[str] = (),
) -> None:
    expected = {
        "table": set(tables),
        "index": set(indexes),
        "trigger": set(triggers),
    }
    for object_type, names in expected.items():
        missing = names - _sqlite_master_names(connection, object_type)
        if missing:
            raise _schema_error(
                f"missing {object_type} objects: {sorted(missing)!r}"
            )
