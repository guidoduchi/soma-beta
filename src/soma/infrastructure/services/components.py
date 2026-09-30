from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.infrastructure.domain.sites import match_key
from soma.infrastructure.repositories.core import MutationPlan, count, encoded, fingerprint, get, one, rows

COMMAND_NAMES = frozenset({"CreateNetworkElementModel", "UpdateNetworkElementModel",
    "ChangeNetworkElementModelLifecycle", "ChangeModelBomCompatibility",
    "RegisterInstalledComponent", "RecordInstalledComponentLifecycle"})


def validate_consequence(service, uow, p, element_id, required=False):
    identity = p.get("physical_consequence_id")
    if identity is None:
        if required or p.get("task_id") is not None or p.get("physical_consequence_fingerprint") is not None:
            raise SomaError("PHYSICAL_CONSEQUENCE_STALE", "Maintenance evidence is incomplete")
        return
    provider = service.consequence_reader
    if provider is None:
        raise SomaError("DEPENDENCY_INDETERMINATE", "Inventory consequence owner is unavailable")
    try:
        state = provider.validate_current(uow, identity, p.get("physical_consequence_fingerprint"))
        evidence = provider.get_current(uow, identity) if state == "VALID" else None
    except Exception as exc:
        raise SomaError("DEPENDENCY_INDETERMINATE", "Inventory consequence owner is unavailable") from exc
    if state == "INDETERMINATE":
        raise SomaError("DEPENDENCY_INDETERMINATE", "Inventory consequence cannot be verified")
    if state != "VALID" or evidence is None or evidence["task_id"] != p.get("task_id"):
        raise SomaError("PHYSICAL_CONSEQUENCE_STALE", "Inventory consequence or Task is stale")


def check_slot(uow, element_id, slot, component_id):
    if slot and count(uow, "SELECT count(*) FROM installed_component_current WHERE network_element_id=? AND slot_match_key=? AND state='installed' AND installed_component_id<>?",
                      (element_id, match_key(slot), component_id)):
        raise SomaError("COMPONENT_SLOT_OCCUPIED", "Installed Component slot is occupied")


def component_projection(events):
    overrides = {}
    for event in events:
        if event["event_kind"] == "correction":
            overrides[event["target_event_id"]] = event
    state = dict(state="unknown", bom_code=None, bom_key=None, manufacturer_serial=None,
                 serial_match_key=None, slot_label=None, slot_match_key=None, condition_token="unknown")
    for original in events:
        if original["event_kind"] == "correction":
            continue
        event = {**original, **{key: value for key, value in overrides.get(original["installed_component_event_id"], {}).items()
                              if key not in ("event_kind", "installed_component_event_id", "target_event_id")}}
        kind = original["event_kind"]
        if kind in ("installed", "removed"):
            state["state"] = kind
        for key in ("bom_code", "manufacturer_serial", "slot_label", "condition_token"):
            if event.get(key) is not None:
                state[key] = event[key]
        state.update(bom_key=match_key(state["bom_code"]), serial_match_key=match_key(state["manufacturer_serial"]),
                     slot_match_key=match_key(state["slot_label"]))
    return state


def prepare(service, uow, command, p, command_id):
    if command == "CreateNetworkElementModel":
        identity = new_uuid4()
        plan = MutationPlan("model", identity, 1, command_id)
        values = dict(name=p["name"], name_match_key=match_key(p["name"]),
                      manufacturer=p.get("manufacturer"), manufacturer_match_key=match_key(p.get("manufacturer")))
        plan.insert("network_element_models", dict(network_element_model_id=identity, **values,
                    lifecycle_state="active", revision=1, created_at_utc=utc_epoch_seconds(),
                    created_command_id=command_id, last_command_id=command_id))
        plan.event("model_lifecycle_events", "model_event_id", dict(network_element_model_id=identity,
                   event_kind="created", details_json=encoded({"new": values})))
        return plan
    if command in ("UpdateNetworkElementModel", "ChangeNetworkElementModelLifecycle"):
        identity = p["model_id"]
        old = get(uow, "network_element_models", identity, revision=p["base_revision"],
                  active=command == "UpdateNetworkElementModel")
        plan = MutationPlan("model", identity, old["revision"], command_id)
        if command == "UpdateNetworkElementModel":
            values = dict(name=p["name"], name_match_key=match_key(p["name"]),
                          manufacturer=p.get("manufacturer"), manufacturer_match_key=match_key(p.get("manufacturer")))
            event_kind = "descriptive_corrected"
        else:
            values = {"lifecycle_state": p["target_state"]}
            event_kind = "archived" if p["target_state"] == "archived" else "reactivated"
        if all(old[key] == value for key, value in values.items()):
            return plan
        plan.revision += 1
        plan.update("network_element_models", identity, {**values, "revision": plan.revision, "last_command_id": command_id})
        plan.event("model_lifecycle_events", "model_event_id", dict(network_element_model_id=identity,
                   event_kind=event_kind, details_json=encoded({"prior": {key: old[key] for key in values}, "new": values}),
                   reason_code=p.get("reason_code")))
        return plan
    if command == "ChangeModelBomCompatibility":
        model = get(uow, "network_element_models", p["model_id"], active=p["action"] != "remove")
        old = get(uow, "model_bom_compatibility_current", p["relation_id"], optional=True)
        revision = old["revision"] if old else 0
        if revision != p["base_revision"] or (old and old["network_element_model_id"] != p["model_id"]):
            raise SomaError("INFRA_STALE", "Model compatibility relation changed")
        plan = MutationPlan("model", p["model_id"], max(1, revision), command_id)
        values = dict(network_element_model_id=p["model_id"], bom_code=p["bom_code"],
                      bom_key=match_key(p["bom_code"]), component_role=p.get("component_role"))
        if p["action"] == "remove" and old is None:
            return plan
        if p["action"] == "correct" and old is None:
            raise SomaError("INFRA_STALE", "Compatibility correction requires an existing relation")
        if old and p["action"] != "remove" and all(old[key] == value for key, value in values.items()):
            return plan
        if p["action"] != "remove" and count(uow, "SELECT count(*) FROM model_bom_compatibility_current WHERE network_element_model_id=? AND bom_key=? AND coalesce(component_role,'')=coalesce(?,'') AND compatibility_relation_id<>?",
                (p["model_id"], values["bom_key"], values["component_role"], p["relation_id"])):
            raise SomaError("INFRA_STALE", "Exact compatibility relation already exists")
        event_id = plan.event("model_bom_compatibility_events", "compatibility_event_id",
                             dict(compatibility_relation_id=p["relation_id"], event_kind=p["action"],
                                  **values, reason_code=p["reason_code"]))
        plan.revision = revision + 1
        if p["action"] == "remove":
            plan.delete("model_bom_compatibility_current", p["relation_id"])
        else:
            current = dict(**values, revision=plan.revision, last_event_id=event_id, last_command_id=command_id)
            if old:
                plan.update("model_bom_compatibility_current", p["relation_id"], current)
            else:
                plan.insert("model_bom_compatibility_current", dict(compatibility_relation_id=p["relation_id"], **current))
        return plan
    register = command == "RegisterInstalledComponent"
    if register:
        element_id = p["network_element_id"]
        get(uow, "network_elements", element_id, active=True)
        if count(uow, "SELECT count(*) FROM installed_components WHERE network_element_id=?", (element_id,)) >= 4096:
            raise ValidationError("Installed Component hard limit exceeded")
        identity, old, history = new_uuid4(), None, []
        plan = MutationPlan("installed_component", identity, 1, command_id)
        validate_consequence(service, uow, p, element_id, p["origin"] == "maintenance_consequence")
        plan.insert("installed_components", dict(installed_component_id=identity, network_element_id=element_id,
                    creation_origin=p["origin"], created_at_utc=utc_epoch_seconds(), created_command_id=command_id))
        event_kind = "installed"
    else:
        identity = p["installed_component_id"]
        old = get(uow, "installed_component_current", identity, revision=p["base_revision"])
        element_id = old["network_element_id"]
        get(uow, "network_elements", element_id, active=True)
        plan = MutationPlan("installed_component", identity, old["revision"], command_id)
        event_kind = p["action"]
        origin = one(uow, "SELECT creation_origin FROM installed_components WHERE installed_component_id=?", (identity,))
        validate_consequence(service, uow, p, element_id,
                             origin["creation_origin"] == "maintenance_consequence" and event_kind in ("installed", "removed"))
        history = rows(uow, "SELECT * FROM installed_component_events WHERE installed_component_id=? ORDER BY rowid", (identity,))
        if event_kind == "correction":
            target = next((event for event in history if event["installed_component_event_id"] == p.get("target_event_id")), None)
            if target is None or target["event_kind"] == "correction":
                raise SomaError("INFRA_STALE", "Correction requires an exact original component event")
        elif p.get("target_event_id") is not None:
            raise ValidationError("Only a correction may target an earlier event")
    event = dict(installed_component_id=identity, event_kind=event_kind,
                 bom_code=p.get("bom_code"), bom_key=match_key(p.get("bom_code")),
                 manufacturer_serial=p.get("manufacturer_serial"), serial_match_key=match_key(p.get("manufacturer_serial")),
                 slot_label=p.get("slot_label"), condition_token=p.get("condition"),
                 task_id=p.get("task_id"), inventory_physical_consequence_id=p.get("physical_consequence_id"),
                 target_event_id=p.get("target_event_id"), reason_code=p.get("reason_code"))
    candidate = {**event, "installed_component_event_id": new_uuid4()}
    current = component_projection([*history, candidate])
    if current["state"] == "installed":
        check_slot(uow, element_id, current["slot_label"], identity)
    if old and all(old[key] == value for key, value in current.items()) and event_kind != "correction":
        return plan
    if not register:
        plan.revision += 1
    event_id = plan.event("installed_component_events", "installed_component_event_id", event)
    values = dict(network_element_id=element_id, **current, revision=plan.revision,
                  input_fingerprint=fingerprint(current), last_event_id=event_id, last_command_id=command_id)
    if old:
        plan.update("installed_component_current", identity, values)
    else:
        plan.insert("installed_component_current", dict(installed_component_id=identity, **values))
    return plan
