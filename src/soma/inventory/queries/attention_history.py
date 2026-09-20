from __future__ import annotations

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot


class InventoryAttentionHistoryQuery:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def attention(
        self,
        *,
        attention_kind: str | None = None,
        severity: str | None = None,
        after_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("limit must be in 1..500")
        after = None if after_id is None else require_uuid4(after_id)
        clauses: list[str] = []
        params: list[object] = []
        if attention_kind is not None:
            clauses.append("attention_kind=?")
            params.append(attention_kind)
        if severity is not None:
            clauses.append("severity=?")
            params.append(severity)
        base_where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            total = int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM inventory_attention_projection" + base_where,
                tuple(params),
            ).fetchone()[0])
            if after is not None:
                clauses.append("attention_id>?")
                params.append(after)
            where = "" if not clauses else " WHERE " + " AND ".join(clauses)
            rows = snapshot.connection.execute(
                "SELECT attention_id,target_kind,target_id,attention_kind,severity,"
                "input_fingerprint FROM inventory_attention_projection"
                + where + " ORDER BY attention_id LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            page = rows[:limit]
            return {
                "items": [
                    {
                        "attention_id": str(x[0]),
                        "target_kind": str(x[1]),
                        "target_id": str(x[2]),
                        "attention_kind": str(x[3]),
                        "severity": str(x[4]),
                        "input_fingerprint": str(x[5]),
                    }
                    for x in page
                ],
                "continuation": str(page[-1][0]) if len(rows) > limit and page else None,
                "exact_total": total,
            }

    def history(
        self,
        *,
        target_kind: str,
        target_id: str,
        after_recorded_at_utc: int | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        identity = require_uuid4(target_id)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("limit must be in 1..500")
        if after_recorded_at_utc is not None and (
            type(after_recorded_at_utc) is not int or after_recorded_at_utc < 0
        ):
            raise ValidationError("history cursor is invalid")
        table_map = {
            "spare_need": (
                "spare_need_lifecycle_events",
                "spare_need_id",
                "need_event_id",
                "event_kind",
            ),
            "spare_request": (
                "spare_request_lifecycle_events",
                "spare_request_id",
                "request_event_id",
                "event_kind",
            ),
            "spare_part_unit": (
                "spare_part_lifecycle_events",
                "spare_part_unit_id",
                "unit_event_id",
                "event_kind",
            ),
            "fault_tag": (
                "fault_tag_lifecycle_events",
                "fault_tag_id",
                "fault_tag_event_id",
                "event_kind",
            ),
        }
        spec = table_map.get(target_kind)
        if spec is None:
            raise ValidationError("unsupported Inventory history target kind")
        table, id_column, event_id_column, event_kind_column = spec
        params: list[object] = [identity]
        cursor = ""
        if after_recorded_at_utc is not None:
            cursor = " AND recorded_at_utc>?"
            params.append(after_recorded_at_utc)
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                f"SELECT {event_id_column},{event_kind_column},recorded_at_utc,command_id "
                f"FROM {table} WHERE {id_column}=?{cursor} "
                f"ORDER BY recorded_at_utc,{event_id_column} LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            page = rows[:limit]
            audit = snapshot.connection.execute(
                "SELECT audit_event_id,action_type,command_id,recorded_at_utc "
                "FROM audit_events WHERE target_id=? ORDER BY recorded_at_utc,audit_event_id",
                (identity,),
            ).fetchall()
            return {
                "target_kind": target_kind,
                "target_id": identity,
                "domain_events": [
                    {
                        "event_id": str(x[0]),
                        "event_kind": str(x[1]),
                        "recorded_at_utc": int(x[2]),
                        "command_id": str(x[3]),
                    }
                    for x in page
                ],
                "audit_refs": [
                    {
                        "audit_event_id": str(x[0]),
                        "action_type": str(x[1]),
                        "command_id": str(x[2]),
                        "recorded_at_utc": int(x[3]),
                    }
                    for x in audit
                ],
                "continuation": int(page[-1][2]) if len(rows) > limit and page else None,
            }


__all__ = ["InventoryAttentionHistoryQuery"]
