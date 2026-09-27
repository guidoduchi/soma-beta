import json

from soma.infrastructure.repositories.core import one
from .core import page

QUERY_NAMES = frozenset({"InfrastructureHistoryQuery"})
EVENTS = {
    "site": [("site_lifecycle_events", "site_event_id", "site_id")],
    "room": [("room_rack_lifecycle_events", "placement_reference_event_id", "room_id")],
    "rack": [("room_rack_lifecycle_events", "placement_reference_event_id", "rack_id")],
    "network_element": [
        ("network_element_lifecycle_events", "network_element_event_id", "network_element_id"),
        ("network_element_placement_events", "placement_event_id", "network_element_id"),
        ("network_element_containment_events", "containment_event_id", "child_network_element_id"),
        ("cloud_assignment_events", "cloud_assignment_event_id", "network_element_id"),
        ("network_element_model_assignment_events", "model_assignment_event_id", "network_element_id")],
    "model": [("model_lifecycle_events", "model_event_id", "network_element_model_id"),
              ("model_bom_compatibility_events", "compatibility_event_id", "network_element_model_id")],
    "installed_component": [("installed_component_events", "installed_component_event_id", "installed_component_id")],
    "device_reference": [("device_reference_resolution_events", "resolution_event_id", "device_reference_id")],
    "device_part_unit": [("device_part_component_resolution_events", "resolution_event_id", "device_part_unit_id")],
    "ip": [("network_element_ip_events", "ip_event_id", "network_element_ip_id")],
}


def history_value(value):
    kind = "null" if value is None else "boolean" if type(value) is bool else "integer" if type(value) is int else "text"
    text = None
    if kind == "text":
        text = str(value).encode("utf-8")[:1600].decode("utf-8", errors="ignore")
    return dict(kind=kind, text_value=text, integer_value=value if kind == "integer" else None,
                boolean_value=value if kind == "boolean" else None, entity_ref=None)


def execute(service, reader, query, p):
    tables = EVENTS.get(p["target_kind"], [])
    if not tables:
        # Cloud lifecycle and workbook commands retain their owner audit chronology.
        sql = ("SELECT audit_event_id event_id,action_type event_kind,occurred_at_utc recorded_at_utc,"
               "command_id,'audit_events' source FROM audit_events WHERE target_type=? AND target_id=?")
        params = [p["target_kind"], p["target_id"]]
    else:
        sql = " UNION ALL ".join(f"SELECT {key} event_id,event_kind,recorded_at_utc,command_id,'{table}' source FROM {table} WHERE {target}=?" for table, key, target in tables)
        params = [p["target_id"]] * len(tables)
    result, continuation = page(reader, query, p, sql, params, ["recorded_at_utc", "event_id"], ["DESC", "DESC"])
    events = []
    for row in result:
        changes, reason, effective = [], None, None
        if row["source"] != "audit_events":
            table, key, _ = next(item for item in tables if item[0] == row["source"])
            event = one(reader, f"SELECT * FROM {table} WHERE {key}=?", (row["event_id"],))
            reason, effective = event.get("reason_code"), event.get("effective_at_utc")
            for field in event:
                if field.startswith("new_"):
                    stem = field[4:]
                    changes.append(dict(field=stem, prior=history_value(event.get("prior_" + stem)), new=history_value(event[field])))
            if event.get("details_json"):
                detail = json.loads(event["details_json"])
                before, after = detail.get("prior", {}), detail.get("new", {})
                for field in sorted(set(before) | set(after)):
                    if before.get(field) != after.get(field):
                        changes.append(dict(field=field, prior=history_value(before.get(field)), new=history_value(after.get(field))))
        events.append(dict(event_id=row["event_id"], event_kind=row["event_kind"], recorded_at_utc=row["recorded_at_utc"],
                           effective_at_utc=effective, command_id=row["command_id"],
                           summary=dict(changes=changes[:32], reason_code=reason, warning_codes=[])))
    return dict(events=events, next_cursor=continuation)
