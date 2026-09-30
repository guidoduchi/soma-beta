from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.infrastructure.domain.sites import match_key
from soma.infrastructure.repositories.core import MutationPlan, count, fingerprint, get, one, rows
from soma.reference.application.dispatch_service import DispatchLocationService

COMMAND_NAMES = frozenset({"CreateSite", "UpdateSiteDescriptive", "CorrectSiteCustomerOwnership", "ChangeSiteLifecycle"})


def require_customer(uow, identity):
    row = one(uow, "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?", (identity,))
    if row is None or row["lifecycle_state"] != "active":
        raise SomaError("INFRA_STALE", "Site requires an active Customer")


def dependency_state(service, uow, site_id):
    if len(service.site_dependencies) != 3:
        raise SomaError("DEPENDENCY_INDETERMINATE", "All three Site dependency owners must be installed")
    states = []
    for provider in service.site_dependencies:
        try:
            state = provider.guard_archive(uow, site_id)
        except Exception as exc:
            raise SomaError("DEPENDENCY_INDETERMINATE", "Site dependency owner is unavailable") from exc
        if state not in ("CLEAR", "BLOCKED"):
            raise SomaError("DEPENDENCY_INDETERMINATE", "Site dependency cannot be proven")
        states.append(state)
    return states


def physical_counts(uow, site_id, *, active_only):
    suffix = " AND lifecycle_state='active'" if active_only else ""
    return {table: count(uow, f"SELECT count(*) FROM {table} WHERE site_id=?{suffix}", (site_id,))
            for table in ("rooms", "network_elements", "cloud_deployments")}


def dependency_snapshot(service, uow, site_id, site):
    physical = physical_counts(uow, site_id, active_only=False)
    owners = dependency_state(service, uow, site_id)
    return fingerprint({"site": site, "physical": physical, "owners": owners}), physical, owners


def duplicate_fingerprint(uow, address_key):
    return fingerprint(rows(uow, "SELECT site_id,revision FROM sites WHERE address_match_key=? ORDER BY site_id",
                            (address_key,)))


def prepare(service, uow, command, p, command_id):
    if command == "CreateSite":
        require_customer(uow, p["customer_org_id"])
        key = match_key(p["address_text"])
        if p.get("duplicate_review_fingerprint") is not None and p["duplicate_review_fingerprint"] != duplicate_fingerprint(uow, key):
            raise SomaError("INFRA_STALE", "Site duplicate preview changed")
        identity = new_uuid4()
        plan = MutationPlan("site", identity, 1, command_id)
        plan.insert("sites", dict(site_id=identity, customer_org_id=p["customer_org_id"],
                    name=p["name"], name_match_key=match_key(p["name"]),
                    address_text=p["address_text"], address_match_key=key,
                    lifecycle_state="active", revision=1, created_at_utc=utc_epoch_seconds(),
                    created_command_id=command_id, last_command_id=command_id))
        def create_dispatch(inner):
            dispatch_id = DispatchLocationService.create_dedicated_for_site(
                inner, parent_command_id=command_id, name=p["name"], precomputed_match_key=match_key(p["name"]))
            inner.connection.execute(
                "INSERT INTO site_dispatch_locations(site_id,dispatch_location_id,created_command_id) VALUES (?,?,?)",
                (identity, dispatch_id, command_id))
        plan.writes.append(create_dispatch)
        plan.event("site_lifecycle_events", "site_event_id", dict(
            site_id=identity, event_kind="created", new_customer_org_id=p["customer_org_id"],
            new_name=p["name"], new_address_text=p["address_text"]))
        return plan
    identity = p["site_id"]
    old = get(uow, "sites", identity, revision=p["base_revision"])
    plan = MutationPlan("site", identity, old["revision"], command_id)
    changes = {}
    event = {"site_id": identity, "reason_code": p.get("reason_code")}
    if command == "UpdateSiteDescriptive":
        changes = dict(name=p["name"], name_match_key=match_key(p["name"]),
                       address_text=p["address_text"], address_match_key=match_key(p["address_text"]))
        event.update(event_kind="descriptive_corrected", prior_name=old["name"], new_name=p["name"],
                     prior_address_text=old["address_text"], new_address_text=p["address_text"])
    elif command == "CorrectSiteCustomerOwnership":
        if old["customer_org_id"] == p["new_customer_org_id"]:
            return plan
        require_customer(uow, p["new_customer_org_id"])
        current_fingerprint, physical, owners = dependency_snapshot(service, uow, identity, old)
        if current_fingerprint != p["dependency_preview_fingerprint"]:
            raise SomaError("INFRA_STALE", "Site dependency preview changed")
        if any(physical.values()) or "BLOCKED" in owners:
            raise SomaError("SITE_CUSTOMER_CORRECTION_BLOCKED", "Site has physical or operational history")
        changes = {"customer_org_id": p["new_customer_org_id"]}
        event.update(event_kind="customer_ownership_corrected", prior_customer_org_id=old["customer_org_id"],
                     new_customer_org_id=p["new_customer_org_id"])
    elif command == "ChangeSiteLifecycle":
        if p["target_state"] == old["lifecycle_state"]:
            return plan
        if p["target_state"] == "archived":
            if p.get("blocker_preview_fingerprint") is not None:
                current_fingerprint, _, owners = dependency_snapshot(service, uow, identity, old)
                if current_fingerprint != p["blocker_preview_fingerprint"]:
                    raise SomaError("INFRA_STALE", "Site blocker preview changed")
            else:
                owners = dependency_state(service, uow, identity)
            if any(physical_counts(uow, identity, active_only=True).values()) or "BLOCKED" in owners:
                raise SomaError("SITE_ARCHIVE_BLOCKED", "Site has active dependencies")
        else:
            require_customer(uow, old["customer_org_id"])
        changes = {"lifecycle_state": p["target_state"]}
        event["event_kind"] = "archived" if p["target_state"] == "archived" else "reactivated"
    if all(old[key] == value for key, value in changes.items()):
        return plan
    plan.revision += 1
    plan.update("sites", identity, {**changes, "revision": plan.revision, "last_command_id": command_id})
    plan.event("site_lifecycle_events", "site_event_id", event)
    return plan
