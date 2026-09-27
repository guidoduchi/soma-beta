from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.infrastructure.domain.relationships import normalize_ip, validate_containment_parent
from soma.infrastructure.domain.sites import match_key
from soma.infrastructure.repositories.core import MutationPlan, count, fingerprint, get, rows

COMMAND_NAMES = frozenset({"SetContainmentParent", "CreateCloudType", "CreateCloudDeployment",
    "ChangeCloudDeploymentLifecycle", "SetCloudDeploymentAssignment", "AddNetworkElementIp",
    "SetPrimaryNetworkElementIp", "CorrectNetworkElementIp", "SetNetworkElementModel"})

RELATIONS = {
    "model": ("network_element_model_current", "network_element_model_assignment_events",
              "network_element_id", "network_element_model_id", "model_assignment_event_id",
              "prior_model_id", "new_model_id"),
    "cloud": ("cloud_assignment_current", "cloud_assignment_events", "network_element_id",
              "cloud_deployment_id", "cloud_assignment_event_id", "prior_cloud_deployment_id", "new_cloud_deployment_id"),
    "containment": ("network_element_containment_current", "network_element_containment_events",
              "child_network_element_id", "parent_network_element_id", "containment_event_id",
              "prior_parent_network_element_id", "new_parent_network_element_id"),
}


def set_relation(uow, plan, relation, element, target, old, reason=None):
    table, events, owner_key, target_key, event_key, prior_key, new_key = RELATIONS[relation]
    if target:
        if relation == "model":
            get(uow, "network_element_models", target, active=True)
        elif relation == "cloud":
            deployment = get(uow, "cloud_deployments", target, active=True)
            if deployment["site_id"] != element["site_id"]:
                raise SomaError("CLOUD_CROSS_SITE", "Cloud Deployment and Network Element Sites differ")
        else:
            get(uow, "network_elements", target, active=True)
            def parent_of(identity):
                get(uow, "network_elements", identity)
                current = get(uow, table, identity, optional=True)
                return None if current is None else current[target_key]
            validate_containment_parent(element["network_element_id"], target, parent_of)
    previous = old[target_key] if old else None
    if previous == target:
        return
    event_kind = "clear" if target is None else "assign" if previous is None else "change"
    if relation == "containment":
        event_kind = {"clear": "clear_parent", "assign": "set_parent", "change": "move_parent"}[event_kind]
    event_id = plan.event(events, event_key, {owner_key: element["network_element_id"],
                         "event_kind": event_kind, prior_key: previous, new_key: target, "reason_code": reason})
    if target is None:
        plan.delete(table, element["network_element_id"])
    else:
        values = {target_key: target, "revision": old["revision"] + 1 if old else 1,
                  "last_event_id": event_id, "last_command_id": plan.command_id}
        if old:
            plan.update(table, element["network_element_id"], values)
        else:
            plan.insert(table, {owner_key: element["network_element_id"], **values})


def primary_fingerprint(uow, element_id):
    return fingerprint(rows(uow, "SELECT network_element_ip_id,revision,is_primary,active,canonical_address FROM network_element_ip_current WHERE network_element_id=? ORDER BY network_element_ip_id", (element_id,)))


def ip_event(plan, old, kind, **changes):
    event_id = plan.event("network_element_ip_events", "ip_event_id", dict(
        network_element_ip_id=old["network_element_ip_id"], event_kind=kind,
        canonical_address=changes.get("canonical_address", old["canonical_address"]),
        ip_family=changes.get("ip_family", old["ip_family"])))
    plan.update("network_element_ip_current", old["network_element_ip_id"],
                {**changes, "revision": old["revision"] + 1, "last_event_id": event_id, "last_command_id": plan.command_id})


def unset_primary(uow, plan, element_id, except_id=None):
    for old in rows(uow, "SELECT * FROM network_element_ip_current WHERE network_element_id=? AND active=1 AND is_primary=1", (element_id,)):
        if old["network_element_ip_id"] != except_id:
            ip_event(plan, old, "unset_primary", is_primary=0)


def require_unique_ip(uow, element_id, canonical, except_id=None):
    if count(uow, "SELECT count(*) FROM network_element_ip_current WHERE network_element_id=? AND canonical_address=? AND active=1 AND network_element_ip_id<>?",
             (element_id, canonical, except_id or "")):
        raise SomaError("IP_DUPLICATE_ON_ELEMENT", "Canonical IP already exists on this Network Element")


def add_ip(uow, plan, element_id, address, primary):
    normalized = normalize_ip(address)
    require_unique_ip(uow, element_id, normalized.canonical_text)
    if count(uow, "SELECT count(*) FROM network_element_ip_current WHERE network_element_id=? AND active=1", (element_id,)) >= 1024:
        raise ValidationError("Network Element exceeds the IP hard limit")
    identity = new_uuid4()
    plan.insert("network_element_ip_identities", dict(network_element_ip_id=identity,
                network_element_id=element_id, created_at_utc=utc_epoch_seconds(), created_command_id=plan.command_id))
    if primary:
        unset_primary(uow, plan, element_id)
    event_id = plan.event("network_element_ip_events", "ip_event_id", dict(network_element_ip_id=identity,
                         event_kind="add", address_text=address, canonical_address=normalized.canonical_text,
                         ip_family=normalized.family))
    plan.insert("network_element_ip_current", dict(network_element_ip_id=identity, network_element_id=element_id,
                canonical_address=normalized.canonical_text, ip_family=normalized.family,
                is_primary=int(primary), active=1, revision=1, last_event_id=event_id, last_command_id=plan.command_id))
    return identity


def prepare(service, uow, command, p, command_id):
    if command in ("CreateCloudType", "CreateCloudDeployment"):
        is_type = command == "CreateCloudType"
        kind, table, key = ("cloud_type", "cloud_types", "cloud_type_id") if is_type else ("cloud_deployment", "cloud_deployments", "cloud_deployment_id")
        identity = new_uuid4()
        plan = MutationPlan(kind, identity, 1, command_id)
        values = {key: identity, "name": p["name"], "name_match_key": match_key(p["name"]),
                  "lifecycle_state": "active", "revision": 1, "created_at_utc": utc_epoch_seconds(),
                  "created_command_id": command_id, "last_command_id": command_id}
        if not is_type:
            get(uow, "sites", p["site_id"], active=True)
            get(uow, "cloud_types", p["cloud_type_id"], active=True)
            values.update(site_id=p["site_id"], cloud_type_id=p["cloud_type_id"])
        plan.insert(table, values)
        return plan
    if command == "ChangeCloudDeploymentLifecycle":
        identity = p["cloud_deployment_id"]
        old = get(uow, "cloud_deployments", identity, revision=p["base_revision"])
        plan = MutationPlan("cloud_deployment", identity, old["revision"], command_id)
        if old["lifecycle_state"] == p["target_state"]:
            return plan
        if p["target_state"] == "archived":
            if count(uow, "SELECT count(*) FROM cloud_assignment_current WHERE cloud_deployment_id=?", (identity,)):
                raise SomaError("INFRA_STALE", "Cloud Deployment has current assignments")
        else:
            get(uow, "sites", old["site_id"], active=True)
            get(uow, "cloud_types", old["cloud_type_id"], active=True)
        plan.revision += 1
        plan.update("cloud_deployments", identity, dict(lifecycle_state=p["target_state"],
                    revision=plan.revision, last_command_id=command_id))
        return plan
    if command in ("SetContainmentParent", "SetCloudDeploymentAssignment", "SetNetworkElementModel"):
        relation = {"SetContainmentParent": "containment", "SetCloudDeploymentAssignment": "cloud",
                    "SetNetworkElementModel": "model"}[command]
        identity = p.get("child_network_element_id", p.get("network_element_id"))
        element = get(uow, "network_elements", identity, active=True)
        table = RELATIONS[relation][0]
        old = get(uow, table, identity, optional=True)
        revision = old["revision"] if old else 0
        if p["base_revision"] != revision:
            raise SomaError("INFRA_STALE", "Relationship revision changed")
        target = p.get({"containment": "parent_network_element_id", "cloud": "cloud_deployment_id", "model": "model_id"}[relation])
        if p.get("preview_fingerprint") is not None and p["preview_fingerprint"] != fingerprint(old):
            raise SomaError("INFRA_STALE", "Containment preview changed")
        plan = MutationPlan("network_element", identity, max(1, revision), command_id)
        set_relation(uow, plan, relation, element, target, old, p.get("reason_code"))
        if not plan.no_change:
            plan.revision = revision + 1
        return plan
    if command == "AddNetworkElementIp":
        identity = p["network_element_id"]
        get(uow, "network_elements", identity, active=True)
        plan = MutationPlan("ip", new_uuid4(), 1, command_id)
        ip_id = add_ip(uow, plan, identity, p["address"], p["make_primary"])
        plan.identity = ip_id
        plan.result_refs = [{"kind": "ip", "id": ip_id}]
        return plan
    identity = p["ip_id"]
    old = get(uow, "network_element_ip_current", identity, revision=p.get("ip_revision", p.get("base_revision")))
    get(uow, "network_elements", old["network_element_id"], active=True)
    plan = MutationPlan("ip", identity, old["revision"], command_id)
    if command == "SetPrimaryNetworkElementIp":
        if old["network_element_id"] != p["network_element_id"] or not old["active"]:
            raise SomaError("IP_PRIMARY_CONFLICT", "Primary target is not an active IP of this element")
        if primary_fingerprint(uow, old["network_element_id"]) != p["primary_set_fingerprint"]:
            raise SomaError("INFRA_STALE", "Primary IP set changed")
        if old["is_primary"]:
            return plan
        unset_primary(uow, plan, old["network_element_id"], identity)
        ip_event(plan, old, "set_primary", is_primary=1)
    else:
        action = p["action"]
        if (action == "address_corrected") != (p.get("new_address") is not None):
            raise ValidationError("Address correction requires exactly one new address")
        if action == "address_corrected":
            address = normalize_ip(p["new_address"])
            require_unique_ip(uow, old["network_element_id"], address.canonical_text, identity)
            if address.canonical_text == old["canonical_address"]:
                return plan
            ip_event(plan, old, action, canonical_address=address.canonical_text, ip_family=address.family)
        elif action == "remove":
            if not old["active"]:
                return plan
            ip_event(plan, old, action, active=0, is_primary=0)
        else:
            if old["active"]:
                return plan
            require_unique_ip(uow, old["network_element_id"], old["canonical_address"], identity)
            if count(uow, "SELECT count(*) FROM network_element_ip_current WHERE network_element_id=? AND active=1", (old["network_element_id"],)) >= 1024:
                raise ValidationError("Network Element exceeds the IP hard limit")
            ip_event(plan, old, action, active=1, is_primary=0)
    plan.revision += 1
    return plan
