from soma.infrastructure.repositories.core import count, get, rows

QUERY_NAMES = frozenset({"SiteDetailQuery", "NetworkElementDetailQuery", "RackOccupancyQuery",
                         "ModelDetailQuery", "InstalledComponentQuery", "DeviceReferenceResolutionQuery"})


def ref(kind, identity):
    return None if identity is None else {"kind": kind, "id": identity}


def execute(service, reader, query, p):
    if query == "SiteDetailQuery":
        from .candidates import site_blockers
        site = get(reader, "sites", p["site_id"])
        link = get(reader, "site_dispatch_locations", site["site_id"])
        blockers = site_blockers(service, reader, {"site_id": site["site_id"], "limit": 1})
        if blockers["indeterminate"]:
            from soma.foundation.errors import SomaError
            raise SomaError("DEPENDENCY_INDETERMINATE", "Site blocker count cannot be proven")
        return dict(site_id=site["site_id"], revision=site["revision"], customer_org_id=site["customer_org_id"],
                    name=site["name"], address_text=site["address_text"], lifecycle=site["lifecycle_state"],
                    dispatch_location_id=link["dispatch_location_id"],
                    room_count=count(reader, "SELECT count(*) FROM rooms WHERE site_id=?", (site["site_id"],)),
                    rack_count=count(reader, "SELECT count(*) FROM racks r JOIN rooms m USING(room_id) WHERE m.site_id=?", (site["site_id"],)),
                    network_element_count=count(reader, "SELECT count(*) FROM network_elements WHERE site_id=?", (site["site_id"],)),
                    cloud_deployment_count=count(reader, "SELECT count(*) FROM cloud_deployments WHERE site_id=?", (site["site_id"],)),
                    archive_blocker_count=blockers["exact_count"],
                    duplicate_candidate_count=count(reader, "SELECT count(*) FROM sites WHERE address_match_key=? AND site_id<>?",
                                                    (site["address_match_key"], site["site_id"])))
    if query == "NetworkElementDetailQuery":
        identity = p["network_element_id"]
        element = get(reader, "network_elements", identity)
        site = get(reader, "sites", element["site_id"])
        placement = get(reader, "network_element_placement_current", identity)
        model = get(reader, "network_element_model_current", identity, optional=True)
        cloud = get(reader, "cloud_assignment_current", identity, optional=True)
        parent = get(reader, "network_element_containment_current", identity, optional=True)
        primary = rows(reader, "SELECT canonical_address FROM network_element_ip_current WHERE network_element_id=? AND active=1 AND is_primary=1", (identity,))
        duplicate_ip = reader.connection.execute(
            """
            SELECT 1
            FROM network_element_ip_current own
            JOIN network_element_ip_current other
              ON other.canonical_address=own.canonical_address
             AND other.active=1
             AND other.network_element_id<>own.network_element_id
            WHERE own.network_element_id=? AND own.active=1
            LIMIT 1
            """,
            (identity,),
        ).fetchone() is not None
        return dict(network_element_id=identity, revision=element["revision"], lifecycle=element["lifecycle_state"],
            operational_name=element["operational_name"], site=ref("site", element["site_id"]), customer_org_id=site["customer_org_id"],
            placement=dict(rack_id=placement["rack_id"], u_start=placement["u_start"], u_span=placement["u_span"],
                           revision=placement["revision"], explicit_unracked=placement["rack_id"] is None),
            model=ref("model", model["network_element_model_id"]) if model else None,
            cloud_deployment=ref("cloud_deployment", cloud["cloud_deployment_id"]) if cloud else None,
            primary_ip=primary[0]["canonical_address"] if primary else None,
            ip_count=count(reader, "SELECT count(*) FROM network_element_ip_current WHERE network_element_id=? AND active=1", (identity,)),
            containment_parent=ref("network_element", parent["parent_network_element_id"]) if parent else None,
            containment_child_count=count(reader, "SELECT count(*) FROM network_element_containment_current WHERE parent_network_element_id=?", (identity,)),
            device_reference_count=count(reader, "SELECT count(*) FROM device_reference_resolution_current WHERE network_element_id=?", (identity,)),
            installed_component_count=count(reader, "SELECT count(*) FROM installed_components WHERE network_element_id=?", (identity,)),
            warning_codes=["IP_DUPLICATE_ACROSS_NETWORK_ELEMENTS"] if duplicate_ip else [])
    if query == "RackOccupancyQuery":
        rack = get(reader, "racks", p["rack_id"])
        occupants = rows(reader, "SELECT p.network_element_id,n.operational_name,p.u_start,p.u_span FROM network_element_placement_current p JOIN network_elements n USING(network_element_id) WHERE rack_id=? ORDER BY u_start,network_element_id LIMIT 4097", (p["rack_id"],))
        corrupt = len(occupants) > 4096
        occupied = set()
        for row in occupants:
            interval = set(range(row["u_start"], row["u_start"] + row["u_span"]))
            corrupt |= bool(occupied & interval) or min(interval) < 1 or max(interval) > rack["height_u"]
            occupied.update(interval)
        free, start = [], None
        for unit in range(1, rack["height_u"] + 2):
            if unit <= rack["height_u"] and unit not in occupied:
                if start is None:
                    start = unit
            elif start is not None:
                free.append({"u_start": start, "u_span": unit - start})
                start = None
        return dict(rack_id=p["rack_id"], height_u=rack["height_u"], row_label=rack["row_label"],
                    column_label=rack["column_label"], occupants=occupants[:4096], free_ranges=free,
                    corrupt_overlap_detected=corrupt)
    if query == "ModelDetailQuery":
        model = get(reader, "network_element_models", p["model_id"])
        return dict(model_id=p["model_id"], revision=model["revision"], name=model["name"],
                    manufacturer=model["manufacturer"], lifecycle=model["lifecycle_state"],
                    compatibility_count=count(reader, "SELECT count(*) FROM model_bom_compatibility_current WHERE network_element_model_id=?", (p["model_id"],)),
                    assigned_network_element_count=count(reader, "SELECT count(*) FROM network_element_model_current WHERE network_element_model_id=?", (p["model_id"],)))
    if query == "InstalledComponentQuery":
        from .core import page
        get(reader, "network_elements", p["network_element_id"])
        where, values = ["c.network_element_id=?"], [p["network_element_id"]]
        for key in ("state", "bom_key", "slot_match_key"):
            if p.get(key) is not None:
                where.append("c." + key + "=?")
                values.append(p[key])
        sql = ("SELECT c.installed_component_id,c.state,c.bom_code,c.manufacturer_serial,c.slot_label,"
               "c.condition_token AS condition,r.device_part_unit_id,e.inventory_physical_consequence_id AS physical_consequence_id "
               "FROM installed_component_current c LEFT JOIN device_part_component_resolution_current r USING(installed_component_id) "
               "JOIN installed_component_events e ON e.installed_component_event_id=c.last_event_id WHERE " + " AND ".join(where))
        items, continuation = page(reader, query, p, sql, values, ["installed_component_id"])
        return dict(items=items, next_cursor=continuation)
    if service.device_reader is None:
        from soma.foundation.errors import SomaError
        raise SomaError("DEPENDENCY_INDETERMINATE", "Device Reference reader is unavailable")
    device = service.device_reader.get(reader, p["device_reference_id"])
    if device is None:
        from soma.foundation.errors import SomaError
        raise SomaError("INFRA_NOT_FOUND", "Device Reference does not exist")
    current = get(reader, "device_reference_resolution_current", p["device_reference_id"], optional=True)
    return dict(device_reference_id=p["device_reference_id"], device_reference_revision=device["revision"],
                current_network_element_id=current["network_element_id"] if current else None,
                resolution_revision=current["revision"] if current else 0,
                history_count=count(reader, "SELECT count(*) FROM device_reference_resolution_events WHERE device_reference_id=?", (p["device_reference_id"],)))
