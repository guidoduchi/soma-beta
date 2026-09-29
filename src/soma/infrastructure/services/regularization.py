from collections.abc import Mapping

from soma.foundation.errors import SomaError, ValidationError
from soma.infrastructure.repositories.core import MutationPlan, count, fingerprint, get
from .network_elements import create_plan

COMMAND_NAMES = frozenset({"RegularizeDeviceReference", "ResolveDevicePartToInstalledComponent"})


def regularization_fingerprint(service, reader, p):
    if service.device_reader is None:
        raise SomaError("DEPENDENCY_INDETERMINATE", "Device Reference reader is unavailable")
    device = service.device_reader.get(reader, p["device_reference_id"])
    if device is None:
        raise SomaError("INFRA_NOT_FOUND", "Device Reference does not exist")
    current = get(reader, "device_reference_resolution_current", p["device_reference_id"], optional=True)
    target = get(reader, "network_elements", p["target_network_element_id"], active=True) if p.get("target_network_element_id") else None
    return fingerprint({"device": device, "current": current, "target": target,
                        "action": p["action"], "new_network_element": p.get("new_network_element")})


def _validated_deliberate_action_matches(
    value,
    *,
    action: str,
    target: dict,
    base_revision: int,
    preview_fingerprint: str,
) -> bool:
    required = {"action_code", "target", "base_revision", "preview_fingerprint"}
    if isinstance(value, Mapping):
        if set(value) != required:
            return False
        action_code = value["action_code"]
        actual_target = value["target"]
        actual_base_revision = value["base_revision"]
        actual_preview = value["preview_fingerprint"]
    else:
        missing = object()
        action_code = getattr(value, "action_code", missing)
        actual_target = getattr(value, "target", missing)
        actual_base_revision = getattr(value, "base_revision", missing)
        actual_preview = getattr(value, "preview_fingerprint", missing)
        if missing in (action_code, actual_target, actual_base_revision, actual_preview):
            return False

    if isinstance(actual_target, Mapping):
        if set(actual_target) != {"target_type", "target_id"}:
            return False
        normalized_target = {
            "target_type": actual_target["target_type"],
            "target_id": actual_target["target_id"],
        }
    else:
        target_type = getattr(actual_target, "target_type", None)
        target_id = getattr(actual_target, "target_id", None)
        if target_type is None or target_id is None:
            return False
        normalized_target = {"target_type": target_type, "target_id": target_id}

    return (
        action_code == action
        and normalized_target == target
        and actual_base_revision == base_revision
        and actual_preview == preview_fingerprint
    )


def validate_component_target(service, reader, unit_id, component_id):
    if service.device_part_reader is None:
        return "INDETERMINATE"
    try:
        unit = service.device_part_reader.get_reference_context(reader, unit_id)
        component = get(reader, "installed_component_current", component_id)
        if unit is None:
            return "INVALID"
        resolution = get(reader, "device_reference_resolution_current", unit["device_reference_id"], optional=True)
        if resolution is None or resolution["network_element_id"] != component["network_element_id"]:
            return "INVALID"
        if count(reader, "SELECT count(*) FROM device_part_component_resolution_current WHERE installed_component_id=? AND device_part_unit_id<>?", (component_id, unit_id)):
            return "INVALID"
        return "VALID"
    except Exception:
        return "INDETERMINATE"


def prepare(service, uow, command, p, command_id):
    device = command == "RegularizeDeviceReference"
    if device:
        identity = p["device_reference_id"]
        table, events, owner_key, new_key = ("device_reference_resolution_current",
            "device_reference_resolution_events", "device_reference_id", "network_element_id")
        if service.device_reader is None:
            raise SomaError("DEPENDENCY_INDETERMINATE", "Device Reference owner is unavailable")
        operational = service.device_reader.get(uow, identity)
        if operational is None or operational["revision"] != p["device_reference_revision"]:
            raise SomaError("INFRA_STALE", "Device Reference revision changed")
        action = p["action"]
        target, new = p.get("target_network_element_id"), p.get("new_network_element")
        if (action in ("link_existing", "correct_link")) != (target is not None) or (action == "create_and_link") != (new is not None):
            raise ValidationError("Device regularization action has conflicting target fields")
        expected = regularization_fingerprint(service, uow, p)
        if expected != p["preview_fingerprint"]:
            raise SomaError("INFRA_STALE", "Device regularization preview changed")
        base_revision = p.get("resolution_revision", 0)
        kind = "device_reference"
    else:
        identity = p["device_part_unit_id"]
        table, events, owner_key, new_key = ("device_part_component_resolution_current",
            "device_part_component_resolution_events", "device_part_unit_id", "installed_component_id")
        target = p.get("installed_component_id")
        if service.device_part_reader is None:
            raise SomaError("DEPENDENCY_INDETERMINATE", "Device Part owner is unavailable")
        if service.device_part_reader.get_reference_context(uow, identity) is None:
            raise SomaError("DEVICE_PART_COMPONENT_INVALID", "Device Part does not exist")
        if target:
            state = validate_component_target(service, uow, identity, target)
            if state != "VALID":
                raise SomaError("DEPENDENCY_INDETERMINATE" if state == "INDETERMINATE" else "DEVICE_PART_COMPONENT_INVALID",
                                "Device Part and Installed Component context is not compatible")
        base_revision = p["base_revision"]
        kind = "device_part_unit"
    old = get(uow, table, identity, optional=True)
    revision = old["revision"] if old else 0
    if revision != base_revision:
        raise SomaError("INFRA_STALE", "Resolution revision changed")
    plan = MutationPlan(kind, identity, max(1, revision), command_id)
    if device and action == "link_existing" and old is not None:
        raise SomaError("INFRA_STALE", "Existing resolution requires an explicit correction")
    if device and action == "correct_link" and old is None:
        raise SomaError("INFRA_STALE", "Correction requires an existing resolution")
    if device and new is not None:
        if old is not None:
            raise SomaError("INFRA_STALE", "Create-and-link requires an unresolved Device Reference")
        child = create_plan(uow, new, command_id)
        target = child.identity
    previous = old[new_key] if old else None
    if previous == target and not (device and new is not None):
        return plan
    if device:
        if service.proof_provider is None or not p.get("deliberate_action_proof"):
            raise SomaError("DEVICE_RESOLUTION_PROOF_REQUIRED", "Deliberate-action proof is required")
        # LLD-08 consumes the session-bound proof after all authoritative
        # freshness checks but before the command receipt, inside the same
        # outer UnitOfWork. LLD-12 keeps the proof single-use even if a later
        # receipt/domain/audit failure rolls the database transaction back.
        proof_target = {"target_type": "device_reference", "target_id": identity}
        validated = service.proof_provider.validate_and_consume(
            uow, p["deliberate_action_proof"], "RegularizeDeviceReference",
            proof_target, p["device_reference_revision"], expected)
        if not _validated_deliberate_action_matches(
            validated,
            action="RegularizeDeviceReference",
            target=proof_target,
            base_revision=p["device_reference_revision"],
            preview_fingerprint=expected,
        ):
            raise SomaError("DEVICE_RESOLUTION_PROOF_REQUIRED", "Deliberate-action proof was not validated")
        if new is not None:
            plan.writes.extend(child.writes)
        if target:
            plan.result_refs.append({"kind": "network_element", "id": target})
    event_id = plan.event(events, "resolution_event_id", {
        owner_key: identity, "event_kind": "clear" if target is None else "link" if previous is None else "correct",
        "prior_" + new_key: previous, "new_" + new_key: target, "reason_code": p.get("reason_code")})
    plan.revision = revision + 1
    if target is None:
        plan.delete(table, identity)
    else:
        values = {new_key: target, "revision": plan.revision, "last_event_id": event_id, "last_command_id": command_id}
        if old:
            plan.update(table, identity, values)
        else:
            plan.insert(table, {owner_key: identity, **values})
    return plan
