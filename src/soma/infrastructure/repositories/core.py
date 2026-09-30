from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

# SQL identifiers are internal owner declarations, never request-derived.
TABLE_KEYS = {
    "sites": "site_id", "site_dispatch_locations": "site_id",
    "rooms": "room_id", "racks": "rack_id", "network_elements": "network_element_id",
    "network_element_models": "network_element_model_id", "cloud_types": "cloud_type_id",
    "cloud_deployments": "cloud_deployment_id",
    "network_element_placement_current": "network_element_id",
    "network_element_containment_current": "child_network_element_id",
    "network_element_model_current": "network_element_id",
    "cloud_assignment_current": "network_element_id",
    "network_element_ip_current": "network_element_ip_id",
    "installed_component_current": "installed_component_id",
    "device_reference_resolution_current": "device_reference_id",
    "device_part_component_resolution_current": "device_part_unit_id",
    "model_bom_compatibility_current": "compatibility_relation_id",
    "infrastructure_workbook_runs": "workbook_run_id",
    "infrastructure_workbook_proposals": "proposal_id",
}


def one(reader, sql: str, params=()):
    cursor = reader.connection.execute(sql, params)
    row = cursor.fetchone()
    return None if row is None else dict(zip((column[0] for column in cursor.description), row))


def rows(reader, sql: str, params=()):
    cursor = reader.connection.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def get(reader, table: str, identity: str, *, active=False, revision=None, optional=False):
    key = TABLE_KEYS[table]
    row = one(reader, f"SELECT * FROM {table} WHERE {key}=?", (identity,))
    if row is None:
        if optional:
            return None
        raise SomaError("INFRA_NOT_FOUND", "Infrastructure entity does not exist")
    if revision is not None and row["revision"] != revision:
        raise SomaError("INFRA_STALE", "Infrastructure revision changed")
    if active and row.get("lifecycle_state") != "active":
        code = "MODEL_ARCHIVED" if table == "network_element_models" else "INFRA_STALE"
        raise SomaError(code, "Infrastructure entity is archived")
    return row


def count(reader, sql: str, params=()) -> int:
    return int(reader.connection.execute(sql, params).fetchone()[0])


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass
class MutationPlan:
    kind: str
    identity: str
    revision: int
    command_id: str
    writes: list[Callable[[UnitOfWork], None]] = field(default_factory=list)
    result_refs: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.result_refs.append({"kind": self.kind, "id": self.identity})

    @property
    def no_change(self):
        return not self.writes

    def sql(self, statement: str, values=()):
        self.writes.append(lambda uow: uow.connection.execute(statement, values))

    def insert(self, table: str, values: dict):
        fields = tuple(values)
        self.sql(f"INSERT INTO {table}({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                 tuple(values[field] for field in fields))

    def update(self, table: str, identity: str, values: dict):
        fields = tuple(values)
        self.sql(f"UPDATE {table} SET {','.join(field + '=?' for field in fields)} WHERE {TABLE_KEYS[table]}=?",
                 (*[values[field] for field in fields], identity))

    def delete(self, table: str, identity: str):
        self.sql(f"DELETE FROM {table} WHERE {TABLE_KEYS[table]}=?", (identity,))

    def event(self, table: str, id_field: str, values: dict) -> str:
        identity = new_uuid4()
        self.insert(table, {id_field: identity, **values, "recorded_at_utc": utc_epoch_seconds(),
                            "command_id": self.command_id})
        return identity

    def apply(self, uow):
        for write in self.writes:
            write(uow)

    def response(self):
        return {"command_id": self.command_id, "target": {"kind": self.kind, "id": self.identity},
                "revision": self.revision, "result_refs": self.result_refs, "no_change": self.no_change}


def fingerprint(value):
    return sha256_canonical_json(value)
