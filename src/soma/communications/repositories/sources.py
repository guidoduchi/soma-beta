from __future__ import annotations


def one(reader, sql: str, values=()) -> dict | None:
    cursor = reader.connection.execute(sql, values)
    row = cursor.fetchone()
    return None if row is None else dict(zip((x[0] for x in cursor.description), row))


def scope(reader, identity: str) -> dict | None:
    return one(reader, "SELECT * FROM communication_source_scopes WHERE source_scope_id=?", (identity,))


def provider_scope(reader, family: str, candidate: str) -> dict | None:
    return one(reader, "SELECT * FROM communication_source_scopes WHERE adapter_family=? AND scope_identity_kind='PROVIDER_ACCOUNT' AND scope_identity_value=?", (family, candidate))


def enabled_folders(reader, identity: str) -> list[dict]:
    cursor = reader.connection.execute(
        "SELECT * FROM communication_source_folders WHERE source_scope_id=? AND enabled=1 ORDER BY provider_folder_key LIMIT 65", (identity,))
    return [dict(zip((x[0] for x in cursor.description), row)) for row in cursor.fetchall()]
