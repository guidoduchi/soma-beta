from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.infrastructure.domain.relationships import normalize_ip
from soma.infrastructure.domain.sites import match_key
from soma.infrastructure.repositories.core import MutationPlan, encoded, fingerprint, get, rows
from .placement import add_placement

COMMAND_NAMES = frozenset({"CreateNetworkElement", "UpdateNetworkElementDescriptive", "ChangeNetworkElementLifecycle"})


def candidate_fingerprint(uow, p):
    return fingerprint(rows(uow, "SELECT network_element_id,revision FROM network_elements WHERE name_match_key=? OR serial_match_key=? ORDER BY network_element_id",
                            (match_key(p["operational_name"]), match_key(p.get("manufacturer_serial")))))


def create_plan(uow, values, command_id):
    from .relationships import add_ip, set_relation
    get(uow, "sites", values["site_id"], active=True)
    identity = new_uuid4()
    plan = MutationPlan("network_element", identity, 1, command_id)
    element = dict(network_element_id=identity, site_id=values["site_id"],
                   operational_name=values["operational_name"], name_match_key=match_key(values["operational_name"]),
                   manufacturer_serial=values.get("manufacturer_serial"),
                   serial_match_key=match_key(values.get("manufacturer_serial")),
                   lifecycle_state="active", revision=1, created_at_utc=utc_epoch_seconds(),
                   created_command_id=command_id, last_command_id=command_id)
    plan.insert("network_elements", element)
    plan.event("network_element_lifecycle_events", "network_element_event_id",
               dict(network_element_id=identity, event_kind="created",
                    details_json=encoded({"operational_name": values["operational_name"],
                                          "manufacturer_serial": values.get("manufacturer_serial")})))
    add_placement(uow, plan, element, values.get("placement"))
    if values.get("model_id"):
        set_relation(uow, plan, "model", element, values["model_id"], None)
    if values.get("cloud_deployment_id"):
        set_relation(uow, plan, "cloud", element, values["cloud_deployment_id"], None)
    ips = values.get("ips") or []
    addresses = [normalize_ip(ip["address"]).canonical_text for ip in ips]
    if len(set(addresses)) != len(addresses):
        raise SomaError("IP_DUPLICATE_ON_ELEMENT", "New Network Element has duplicate canonical IPs")
    if sum(ip["make_primary"] for ip in ips) > 1:
        raise SomaError("IP_PRIMARY_CONFLICT", "New Network Element has multiple primary IPs")
    for ip in ips:
        add_ip(uow, plan, identity, ip["address"], ip["make_primary"])
    return plan


def prepare(service, uow, command, p, command_id):
    if command == "CreateNetworkElement":
        if p.get("candidate_preview_fingerprint") is not None and candidate_fingerprint(uow, p["new_element"]) != p["candidate_preview_fingerprint"]:
            raise SomaError("INFRA_STALE", "Network Element candidate preview changed")
        return create_plan(uow, p["new_element"], command_id)
    identity = p["network_element_id"]
    old = get(uow, "network_elements", identity, revision=p["base_revision"])
    plan = MutationPlan("network_element", identity, old["revision"], command_id)
    if command == "UpdateNetworkElementDescriptive":
        values = dict(operational_name=p["operational_name"], name_match_key=match_key(p["operational_name"]),
                      manufacturer_serial=p.get("manufacturer_serial"), serial_match_key=match_key(p.get("manufacturer_serial")))
        event_kind = "descriptive_corrected"
    else:
        if p["target_state"] == "active":
            get(uow, "sites", old["site_id"], active=True)
        values = {"lifecycle_state": p["target_state"]}
        event_kind = "archived" if p["target_state"] == "archived" else "reactivated"
    if all(old[key] == value for key, value in values.items()):
        return plan
    plan.revision += 1
    plan.update("network_elements", identity, {**values, "revision": plan.revision, "last_command_id": command_id})
    plan.event("network_element_lifecycle_events", "network_element_event_id",
               dict(network_element_id=identity, event_kind=event_kind,
                    details_json=encoded({"prior": {key: old[key] for key in values}, "new": values}),
                    reason_code=p.get("reason_code")))
    return plan
