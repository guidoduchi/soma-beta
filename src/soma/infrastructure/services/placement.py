from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.infrastructure.domain.placement import validate_rack_placement
from soma.infrastructure.domain.sites import match_key
from soma.infrastructure.repositories.core import MutationPlan, count, encoded, fingerprint, get, rows

COMMAND_NAMES = frozenset({"CreateRoom", "ChangeRoomLifecycle", "CreateRack", "UpdateRack",
                           "ChangeRackLifecycle", "SetNetworkElementPlacement"})


def require_room(uow, room_id):
    room = get(uow, "rooms", room_id, active=True)
    get(uow, "sites", room["site_id"], active=True)
    return room


def placement_fingerprint(uow, element_id, placement):
    current = get(uow, "network_element_placement_current", element_id)
    rack = None
    occupied = []
    if placement:
        rack = get(uow, "racks", placement["rack_id"])
        occupied = rows(uow, "SELECT network_element_id,u_start,u_span,revision FROM network_element_placement_current WHERE rack_id=? ORDER BY network_element_id",
                        (placement["rack_id"],))
    return fingerprint({"current": current, "rack": rack, "occupants": occupied})


def add_placement(uow, plan, element, placement, old=None, reason=None):
    if placement is None:
        rack_id = start = span = None
    else:
        rack_id, start, span = placement["rack_id"], placement["u_start"], placement["u_span"]
        rack = get(uow, "racks", rack_id, active=True)
        room = require_room(uow, rack["room_id"])
        validate_rack_placement(network_element_site_id=element["site_id"],
                                rack_site_id=room["site_id"], height_u=rack["height_u"],
                                u_start=start, u_span=span)
        if count(uow, "SELECT count(*) FROM network_element_placement_current WHERE rack_id=? AND network_element_id<>? AND u_start<? AND u_start+u_span>?",
                 (rack_id, element["network_element_id"], start + span, start)):
            raise SomaError("RACK_U_OCCUPIED", "Rack U interval is occupied")
    if old and (old["rack_id"], old["u_start"], old["u_span"]) == (rack_id, start, span):
        return
    event_id = plan.event("network_element_placement_events", "placement_event_id", dict(
        network_element_id=element["network_element_id"],
        event_kind="set_unracked" if rack_id is None else "place_rack",
        prior_rack_id=old["rack_id"] if old else None, new_rack_id=rack_id,
        prior_u_start=old["u_start"] if old else None, new_u_start=start,
        prior_u_span=old["u_span"] if old else None, new_u_span=span, reason_code=reason))
    value = dict(rack_id=rack_id, u_start=start, u_span=span,
                 revision=old["revision"] + 1 if old else 1, last_event_id=event_id,
                 last_command_id=plan.command_id)
    if old:
        plan.update("network_element_placement_current", element["network_element_id"], value)
    else:
        plan.insert("network_element_placement_current", dict(network_element_id=element["network_element_id"], **value))


def prepare(service, uow, command, p, command_id):
    if command == "SetNetworkElementPlacement":
        element = get(uow, "network_elements", p["network_element_id"], active=True)
        old = get(uow, "network_element_placement_current", p["network_element_id"], revision=p["placement_revision"])
        placement = p.get("placement")
        if p["explicit_unracked"] == (placement is not None):
            raise ValidationError("Choose exactly one of Rack placement or explicit unracked")
        if placement_fingerprint(uow, p["network_element_id"], placement) != p["preview_fingerprint"]:
            raise SomaError("INFRA_STALE", "Rack placement preview changed")
        plan = MutationPlan("network_element", p["network_element_id"], old["revision"], command_id)
        add_placement(uow, plan, element, placement, old, p["reason_code"])
        if not plan.no_change:
            plan.revision += 1
        return plan
    is_room = command in ("CreateRoom", "ChangeRoomLifecycle")
    table, kind, id_key = ("rooms", "room", "room_id") if is_room else ("racks", "rack", "rack_id")
    if command.startswith("Create"):
        if is_room:
            get(uow, "sites", p["site_id"], active=True)
            values = dict(site_id=p["site_id"], name=p["name"], name_match_key=match_key(p["name"]))
        else:
            require_room(uow, p["room_id"])
            values = dict(room_id=p["room_id"], name=p["name"], name_match_key=match_key(p["name"]),
                          height_u=p["height_u"], row_label=p.get("row_label"), column_label=p.get("column_label"))
        identity = new_uuid4()
        plan = MutationPlan(kind, identity, 1, command_id)
        plan.insert(table, {id_key: identity, **values, "lifecycle_state": "active", "revision": 1,
                          "created_at_utc": utc_epoch_seconds(), "created_command_id": command_id,
                          "last_command_id": command_id})
        event_kind, prior = "created", {}
    else:
        identity = p[id_key]
        old = get(uow, table, identity, revision=p["base_revision"])
        plan = MutationPlan(kind, identity, old["revision"], command_id)
        if command == "UpdateRack":
            values = dict(name=p["name"], name_match_key=match_key(p["name"]), height_u=p["height_u"],
                          row_label=p.get("row_label"), column_label=p.get("column_label"))
            if count(uow, "SELECT count(*) FROM network_element_placement_current WHERE rack_id=? AND u_start+u_span-1>?",
                     (identity, p["height_u"])):
                raise SomaError("RACK_U_OUT_OF_RANGE", "Rack height would invalidate occupied U space")
            event_kind = "descriptive_corrected"
        else:
            values = {"lifecycle_state": p["target_state"]}
            if p["target_state"] == old["lifecycle_state"]:
                return plan
            if p["target_state"] == "archived":
                sql = ("SELECT count(*) FROM racks WHERE room_id=? AND lifecycle_state='active'" if is_room
                       else "SELECT count(*) FROM network_element_placement_current WHERE rack_id=?")
                if count(uow, sql, (identity,)):
                    raise SomaError("INFRA_STALE", "Placement reference still has active dependencies")
            elif is_room:
                get(uow, "sites", old["site_id"], active=True)
            else:
                require_room(uow, old["room_id"])
            event_kind = "archived" if p["target_state"] == "archived" else "reactivated"
        if all(old[key] == value for key, value in values.items()):
            return plan
        prior = {key: old[key] for key in values}
        plan.revision += 1
        plan.update(table, identity, {**values, "revision": plan.revision, "last_command_id": command_id})
    plan.event("room_rack_lifecycle_events", "placement_reference_event_id",
               dict(target_kind=kind, room_id=identity if is_room else None,
                    rack_id=None if is_room else identity, event_kind=event_kind,
                    details_json=encoded({"prior": prior, "new": values}), reason_code=p.get("reason_code")))
    return plan
