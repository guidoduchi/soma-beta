from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.queries.data_instance_identity import DataInstanceIdentityReader
from soma.foundation.strict_json import canonical_json_bytes, loads_canonical_json
from soma.infrastructure.jobs.workbook_proposals import build_workbook_proposal
from soma.infrastructure.repositories.core import MutationPlan, fingerprint, get
from soma.infrastructure.services import network_elements, placement, relationships
from soma.infrastructure.services.workbook_acceptance import (
    PrimaryIpIntent,
    RackPlacementIntent,
    validate_containment_batch,
    validate_primary_ip_batch,
    validate_rack_placement_batch,
)


@dataclass(frozen=True, slots=True)
class WorkbookRowDecision:
    proposal_id: str
    proposal_state: str
    sheet_kind: str
    row_ordinal: int
    row_fingerprint: str
    disposition: str
    target_network_element_id: str | None
    warning_codes_json: str
    result_refs_json: str


@dataclass(frozen=True, slots=True)
class PreparedWorkbookAcceptance:
    run_id: str
    run_revision: int
    logical_fingerprint: str
    mutation_plans: tuple[MutationPlan, ...]
    decisions: tuple[WorkbookRowDecision, ...]
    created: int
    updated: int
    unchanged: int
    result_refs: tuple[dict[str, str], ...]


def _load_json(text: str, *, max_bytes: int, max_items: int):
    return loads_canonical_json(
        text,
        max_bytes=max_bytes,
        max_depth=6,
        max_collection_items=max_items,
    )


def _dedupe_refs(values: list[dict[str, str]], *, limit: int = 64) -> tuple[dict[str, str], ...]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for value in values:
        key = (str(value["kind"]), str(value["id"]))
        if key in seen:
            continue
        seen.add(key)
        if len(result) < limit:
            result.append({"kind": key[0], "id": key[1]})
    return tuple(result)


def accepted_replay_response(reader, logical_fingerprint: str) -> dict | None:
    row = reader.connection.execute(
        "SELECT accepted_workbook_run_id FROM infrastructure_workbook_replay_index "
        "WHERE logical_fingerprint=?",
        (logical_fingerprint,),
    ).fetchone()
    if row is None:
        return None
    run_id = str(row[0])
    run = reader.connection.execute(
        "SELECT state FROM infrastructure_workbook_runs WHERE workbook_run_id=?",
        (run_id,),
    ).fetchone()
    if run is None or str(run[0]) != "accepted":
        raise IntegrityFailure("Infrastructure workbook replay index is corrupt")
    counts = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
    }
    refs: list[dict[str, str]] = []
    rows = reader.connection.execute(
        """
        SELECT disposition,result_refs_json
        FROM infrastructure_workbook_row_decisions
        WHERE workbook_run_id=?
        ORDER BY sheet_kind,row_ordinal
        """,
        (run_id,),
    ).fetchall()
    for disposition, result_refs_json in rows:
        if disposition in counts:
            counts[str(disposition)] += 1
        decoded = _load_json(str(result_refs_json), max_bytes=32_768, max_items=64)
        if not isinstance(decoded, list):
            raise IntegrityFailure("Infrastructure workbook replay result refs are corrupt")
        for value in decoded:
            if (
                not isinstance(value, dict)
                or set(value) != {"kind", "id"}
                or not isinstance(value["kind"], str)
                or not isinstance(value["id"], str)
            ):
                raise IntegrityFailure("Infrastructure workbook replay result refs are corrupt")
            refs.append({"kind": value["kind"], "id": value["id"]})
    return {
        "run_id": run_id,
        "state": "accepted",
        **counts,
        "result_refs": list(_dedupe_refs(refs)),
    }


def _proposal_rows(reader, run_id: str) -> list[dict]:
    cursor = reader.connection.execute(
        """
        SELECT
            p.proposal_id,p.action,p.state,p.target_network_element_id,
            p.expected_target_revision,p.input_fingerprint,p.impact_json,
            p.candidate_ids_json,p.revision,
            s.staging_row_id,s.sheet_kind,s.row_ordinal,s.row_fingerprint,
            s.normalized_row_json,s.warning_codes_json
        FROM infrastructure_workbook_proposals p
        JOIN infrastructure_workbook_staging_rows s
          ON s.staging_row_id=p.staging_row_id
        WHERE p.workbook_run_id=?
        ORDER BY
          CASE s.sheet_kind WHEN 'network_elements' THEN 0 ELSE 1 END,
          s.row_ordinal,p.action,p.proposal_id
        """,
        (run_id,),
    )
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _require_complete_dispositions(proposals: list[dict], dispositions: list[dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for item in dispositions:
        proposal_id = item["proposal_id"]
        if proposal_id in by_id:
            raise SomaError(
                "WORKBOOK_STALE",
                "Workbook acceptance contains a duplicate proposal disposition",
            )
        by_id[proposal_id] = item
    proposal_ids = {row["proposal_id"] for row in proposals}
    if set(by_id) != proposal_ids:
        raise SomaError(
            "WORKBOOK_STALE",
            "Workbook acceptance must disposition the complete proposal set",
        )
    return by_id


def _revalidate_proposal(reader, run: dict, row: dict, normalized: dict) -> dict:
    current = build_workbook_proposal(
        reader,
        workbook_run_id=run["workbook_run_id"],
        sheet_kind=row["sheet_kind"],
        normalized_row=normalized,
        row_fingerprint=row["row_fingerprint"],
        same_installation=run["installation_relation"] == "same_installation",
    )
    stored_candidates = _load_json(
        row["candidate_ids_json"],
        max_bytes=32_768,
        max_items=500,
    )
    stored_impact = _load_json(
        row["impact_json"],
        max_bytes=131_072,
        max_items=256,
    )
    if (
        current["action"] != row["action"]
        or current["target_network_element_id"] != row["target_network_element_id"]
        or current["expected_target_revision"] != row["expected_target_revision"]
        or current["input_fingerprint"] != row["input_fingerprint"]
        or current["candidate_ids"] != stored_candidates
        or current["impact"] != stored_impact
    ):
        raise SomaError(
            "WORKBOOK_STALE",
            "Workbook proposal no longer matches current Infrastructure state",
        )
    return current


def _related_create_inputs(fields: dict) -> dict:
    site_id = fields.get("SomaSiteId")
    name = fields.get("OperationalName")
    if site_id is None or name is None:
        raise SomaError(
            "WORKBOOK_RELATION_INVALID",
            "Workbook Network Element creation lacks Site or operational name",
        )
    rack_id = fields.get("SomaRackId")
    start = fields.get("RackUStart")
    span = fields.get("RackUSpan")
    if rack_id is None:
        if start is not None or span is not None:
            raise SomaError(
                "WORKBOOK_RELATION_INVALID",
                "Workbook Rack interval lacks an exact Rack identity",
            )
        rack_placement = None
    else:
        if start is None or span is None:
            raise SomaError(
                "WORKBOOK_RELATION_INVALID",
                "Workbook Rack placement requires exact U start/span",
            )
        rack_placement = {"rack_id": rack_id, "u_start": start, "u_span": span}
    return {
        "site_id": site_id,
        "operational_name": name,
        "manufacturer_serial": fields.get("ManufacturerSerial"),
        "placement": rack_placement,
        "model_id": fields.get("SomaModelId"),
        "cloud_deployment_id": fields.get("SomaCloudDeploymentId"),
        "ips": [],
    }


def _validate_readable_relationship_context(reader, fields: dict) -> None:
    rack_id = fields.get("SomaRackId")
    room_id = fields.get("SomaRoomId")
    if rack_id is not None and room_id is not None:
        row = reader.connection.execute(
            "SELECT room_id FROM racks WHERE rack_id=?",
            (rack_id,),
        ).fetchone()
        if row is None or str(row[0]) != room_id:
            raise SomaError(
                "WORKBOOK_RELATION_INVALID",
                "Workbook Rack and Room identities disagree",
            )


def _placement_plan(reader, target_id: str, fields: dict, command_id: str):
    rack_id = fields.get("SomaRackId")
    if rack_id is None:
        return None, None
    current = get(reader, "network_element_placement_current", target_id)
    start = fields.get("RackUStart")
    span = fields.get("RackUSpan")
    desired = {
        "rack_id": rack_id,
        "u_start": current["u_start"] if start is None else start,
        "u_span": current["u_span"] if span is None else span,
    }
    if desired["u_start"] is None or desired["u_span"] is None:
        raise SomaError(
            "WORKBOOK_RELATION_INVALID",
            "Workbook Rack placement lacks U coordinates",
        )
    if (current["rack_id"], current["u_start"], current["u_span"]) == (
        desired["rack_id"], desired["u_start"], desired["u_span"]
    ):
        return None, None
    preview = placement.placement_fingerprint(reader, target_id, desired)
    plan = placement.prepare(
        None,
        reader,
        "SetNetworkElementPlacement",
        {
            "network_element_id": target_id,
            "placement_revision": current["revision"],
            "placement": desired,
            "explicit_unracked": False,
            "preview_fingerprint": preview,
            "reason_code": "WORKBOOK_REVIEWED",
        },
        command_id,
    )
    return plan, RackPlacementIntent(
        target_id,
        desired["rack_id"],
        int(desired["u_start"]),
        int(desired["u_span"]),
    )


def _relation_plan(reader, target_id: str, relation: str, target: str | None, command_id: str):
    if target is None:
        return None
    table = relationships.RELATIONS[relation][0]
    old = get(reader, table, target_id, optional=True)
    target_key = relationships.RELATIONS[relation][3]
    if old is not None and old[target_key] == target:
        return None
    base_revision = 0 if old is None else old["revision"]
    if relation == "model":
        command = "SetNetworkElementModel"
        payload = {
            "network_element_id": target_id,
            "model_id": target,
            "base_revision": base_revision,
        }
    elif relation == "cloud":
        command = "SetCloudDeploymentAssignment"
        payload = {
            "network_element_id": target_id,
            "cloud_deployment_id": target,
            "base_revision": base_revision,
        }
    else:
        command = "SetContainmentParent"
        payload = {
            "child_network_element_id": target_id,
            "parent_network_element_id": target,
            "base_revision": base_revision,
            "preview_fingerprint": fingerprint(old),
            "reason_code": "WORKBOOK_REVIEWED",
        }
    return relationships.prepare(None, reader, command, payload, command_id)


def _descriptive_plan(reader, target_id: str, fields: dict, command_id: str):
    current = get(reader, "network_elements", target_id, active=True)
    name = fields.get("OperationalName")
    serial = fields.get("ManufacturerSerial")
    desired_name = current["operational_name"] if name is None else name
    desired_serial = current["manufacturer_serial"] if serial is None else serial
    if (
        desired_name == current["operational_name"]
        and desired_serial == current["manufacturer_serial"]
    ):
        return None
    return network_elements.prepare(
        None,
        reader,
        "UpdateNetworkElementDescriptive",
        {
            "network_element_id": target_id,
            "base_revision": current["revision"],
            "operational_name": desired_name,
            "manufacturer_serial": desired_serial,
            "reason_code": "WORKBOOK_REVIEWED",
        },
        command_id,
    )


def _existing_ip(reader, target_id: str, fields: dict):
    ip_id = fields.get("SomaIpId")
    if ip_id is not None:
        row = reader.connection.execute(
            """
            SELECT network_element_ip_id,network_element_id,canonical_address,
                   ip_family,is_primary,active,revision
            FROM network_element_ip_current
            WHERE network_element_ip_id=?
            """,
            (ip_id,),
        ).fetchone()
        if row is not None and str(row[1]) == target_id and int(row[5]) == 1:
            return dict(zip(
                (
                    "network_element_ip_id","network_element_id","canonical_address",
                    "ip_family","is_primary","active","revision",
                ),
                row,
            ))
        return None
    row = reader.connection.execute(
        """
        SELECT network_element_ip_id,network_element_id,canonical_address,
               ip_family,is_primary,active,revision
        FROM network_element_ip_current
        WHERE network_element_id=? AND canonical_address=? AND active=1
        """,
        (target_id, fields["Address"]),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(
        (
            "network_element_ip_id","network_element_id","canonical_address",
            "ip_family","is_primary","active","revision",
        ),
        row,
    ))


def prepare_workbook_acceptance(service, reader, payload: dict, command_id: str):
    run = get(
        reader,
        "infrastructure_workbook_runs",
        payload["run_id"],
        revision=payload["run_revision"],
    )
    if run["state"] not in ("staged", "reviewed"):
        raise SomaError("WORKBOOK_STALE", "Workbook run is not reviewable")
    if payload["run_input_fingerprint"] != run["logical_fingerprint"]:
        raise SomaError("WORKBOOK_STALE", "Workbook logical input fingerprint changed")

    current_data_instance_id = DataInstanceIdentityReader.get(reader)
    if (
        run["installation_relation"] == "same_installation"
        and run["source_installation_scope_id"] != current_data_instance_id
    ):
        raise SomaError(
            "WORKBOOK_FOREIGN_IDENTITY",
            "Workbook no longer belongs to this SOMA installation",
        )

    replay = accepted_replay_response(reader, run["logical_fingerprint"])
    if replay is not None:
        return replay

    proposals = _proposal_rows(reader, run["workbook_run_id"])
    dispositions = _require_complete_dispositions(proposals, payload["dispositions"])

    prepared_rows: list[tuple[dict, dict, dict, dict]] = []
    for row in proposals:
        disposition = dispositions[row["proposal_id"]]
        if row["state"] != "pending":
            raise SomaError("WORKBOOK_STALE", "Workbook proposal is no longer pending")
        if disposition["expected_revision"] != row["revision"]:
            raise SomaError("WORKBOOK_STALE", "Workbook proposal revision changed")
        if disposition["proposal_fingerprint"] != row["input_fingerprint"]:
            raise SomaError("WORKBOOK_STALE", "Workbook proposal fingerprint changed")
        normalized = _load_json(
            row["normalized_row_json"],
            max_bytes=524_288,
            max_items=128,
        )
        if not isinstance(normalized, dict):
            raise IntegrityFailure("Workbook normalized row is corrupt")
        current = None
        if disposition["decision"] == "accept":
            current = _revalidate_proposal(reader, run, row, normalized)
            action = row["action"]
            if action == "ambiguous":
                raise SomaError(
                    "WORKBOOK_AMBIGUOUS_IDENTITY",
                    "Ambiguous workbook proposal cannot be accepted",
                )
            if action in ("unknown_reference", "create_related_reference", "skip_invalid"):
                raise SomaError(
                    "WORKBOOK_RELATION_INVALID",
                    "Unresolved or invalid workbook proposal cannot be accepted",
                )
            if (
                run["installation_relation"] == "foreign_installation"
                and row["target_network_element_id"] is not None
            ):
                raise SomaError(
                    "WORKBOOK_FOREIGN_IDENTITY",
                    "Foreign workbook identity cannot directly target local state",
                )
        prepared_rows.append((row, disposition, normalized, current or {}))

    mutation_plans: list[MutationPlan] = []
    per_proposal_refs: dict[str, list[dict[str, str]]] = {}
    created_targets: dict[str, tuple[str, MutationPlan]] = {}
    provisional_sites: dict[str, str] = {}
    rack_intents: list[RackPlacementIntent] = []
    containment_intents: dict[str, str | None] = {}
    primary_intents: list[PrimaryIpIntent] = []
    existing_network_targets: set[str] = set()

    # Create Network Elements first so dependent workbook IP rows can bind to
    # deterministic in-UoW identities without inventing a second mutation path.
    for row, disposition, normalized, _current in prepared_rows:
        if disposition["decision"] != "accept" or row["action"] != "create_network_element":
            continue
        fields = normalized["fields"]
        _validate_readable_relationship_context(reader, fields)
        values = _related_create_inputs(fields)
        plan = network_elements.create_plan(reader, values, command_id)
        parent_id = fields.get("SomaParentNetworkElementId")
        if parent_id is not None:
            element = {
                "network_element_id": plan.identity,
                "site_id": values["site_id"],
            }
            relationships.set_relation(
                reader,
                plan,
                "containment",
                element,
                parent_id,
                None,
                "WORKBOOK_REVIEWED",
            )
        mutation_plans.append(plan)
        per_proposal_refs[row["proposal_id"]] = list(plan.result_refs)
        created_targets[row["row_fingerprint"]] = (plan.identity, plan)
        provisional_sites[plan.identity] = values["site_id"]
        if values["placement"] is not None:
            rack_intents.append(
                RackPlacementIntent(
                    plan.identity,
                    values["placement"]["rack_id"],
                    int(values["placement"]["u_start"]),
                    int(values["placement"]["u_span"]),
                )
            )

    accepted_ip_targets: set[tuple[str, str]] = set()
    pending_ip_rows: list[tuple[dict, dict, str, MutationPlan]] = []

    for row, disposition, normalized, _current in prepared_rows:
        if disposition["decision"] != "accept":
            continue
        action = row["action"]
        fields = normalized["fields"]
        if row["sheet_kind"] == "network_elements":
            if action == "create_network_element":
                continue
            if action == "unchanged":
                if row["target_network_element_id"] is not None:
                    per_proposal_refs[row["proposal_id"]] = [{
                        "kind": "network_element",
                        "id": row["target_network_element_id"],
                    }]
                continue

            target_id = row["target_network_element_id"]
            if target_id is None:
                raise SomaError(
                    "WORKBOOK_RELATION_INVALID",
                    "Workbook update lacks an exact Network Element target",
                )
            if target_id in existing_network_targets:
                raise SomaError(
                    "WORKBOOK_RELATION_INVALID",
                    "Workbook acceptance selects duplicate Network Element rows",
                )
            existing_network_targets.add(target_id)
            _validate_readable_relationship_context(reader, fields)
            target = get(
                reader,
                "network_elements",
                target_id,
                active=True,
                revision=row["expected_target_revision"],
            )
            row_plans: list[MutationPlan] = []

            descriptive = _descriptive_plan(reader, target_id, fields, command_id)
            if descriptive is not None and not descriptive.no_change:
                row_plans.append(descriptive)

            placement_plan, placement_intent = _placement_plan(
                reader, target_id, fields, command_id
            )
            if placement_plan is not None and not placement_plan.no_change:
                row_plans.append(placement_plan)
            if placement_intent is not None:
                rack_intents.append(placement_intent)

            for relation, field in (
                ("model", "SomaModelId"),
                ("cloud", "SomaCloudDeploymentId"),
                ("containment", "SomaParentNetworkElementId"),
            ):
                relation_plan = _relation_plan(
                    reader,
                    target_id,
                    relation,
                    fields.get(field),
                    command_id,
                )
                if relation_plan is not None and not relation_plan.no_change:
                    row_plans.append(relation_plan)
                    if relation == "containment":
                        containment_intents[target_id] = fields.get(field)

            if not row_plans:
                raise SomaError(
                    "WORKBOOK_STALE",
                    "Workbook update no longer contains a material change",
                )
            mutation_plans.extend(row_plans)
            per_proposal_refs[row["proposal_id"]] = [{
                "kind": "network_element",
                "id": target["network_element_id"],
            }]
            continue

        # IP row.
        if action == "unchanged":
            ip = _existing_ip(reader, row["target_network_element_id"], fields)
            refs = []
            if ip is not None:
                refs.append({"kind": "ip", "id": str(ip["network_element_ip_id"])})
            per_proposal_refs[row["proposal_id"]] = refs
            continue

        target_id = row["target_network_element_id"]
        target_key: str
        create_plan: MutationPlan | None = None
        if target_id is None:
            name = fields.get("OperationalName")
            matches = [] if not name else reader.connection.execute(
                """
                SELECT row_fingerprint
                FROM infrastructure_workbook_staging_rows
                WHERE workbook_run_id=? AND sheet_kind='network_elements'
                  AND json_extract(normalized_row_json,'$.fields.OperationalName')=?
                ORDER BY row_ordinal LIMIT 2
                """,
                (run["workbook_run_id"], name),
            ).fetchall()
            if len(matches) != 1:
                raise SomaError(
                    "WORKBOOK_AMBIGUOUS_IDENTITY",
                    "Workbook IP row does not resolve to one pending create row",
                )
            create = created_targets.get(str(matches[0][0]))
            if create is None:
                raise SomaError(
                    "WORKBOOK_RELATION_INVALID",
                    "Workbook IP row targets a Network Element row not selected for creation",
                )
            target_id, create_plan = create
            target_key = f"create:{matches[0][0]}"
        else:
            get(
                reader,
                "network_elements",
                target_id,
                active=True,
                revision=row["expected_target_revision"],
            )
            target_key = target_id

        current_ip = None if create_plan is not None else _existing_ip(reader, target_id, fields)
        primary_intents.append(
            PrimaryIpIntent(
                target_key,
                bool(current_ip["is_primary"]) if current_ip is not None else False,
                fields.get("Primary"),
            )
        )
        address_key = (target_key, fields["Address"])
        if address_key in accepted_ip_targets and current_ip is None:
            raise SomaError(
                "IP_DUPLICATE_ON_ELEMENT",
                "Workbook acceptance selects duplicate canonical IP rows",
            )
        accepted_ip_targets.add(address_key)

        if create_plan is not None:
            pending_ip_rows.append((row, fields, target_id, create_plan))
            continue

        row_plans: list[MutationPlan] = []
        if current_ip is None:
            plan = relationships.prepare(
                None,
                reader,
                "AddNetworkElementIp",
                {
                    "network_element_id": target_id,
                    "address": fields["Address"],
                    "make_primary": bool(fields.get("Primary")),
                },
                command_id,
            )
            row_plans.append(plan)
        else:
            address_changed = fields["Address"] != current_ip["canonical_address"]
            requested_primary = fields.get("Primary")
            make_primary = requested_primary is True and not bool(current_ip["is_primary"])
            if address_changed:
                correction = relationships.prepare(
                    None,
                    reader,
                    "CorrectNetworkElementIp",
                    {
                        "ip_id": current_ip["network_element_ip_id"],
                        "ip_revision": current_ip["revision"],
                        "action": "address_corrected",
                        "new_address": fields["Address"],
                    },
                    command_id,
                )
                row_plans.append(correction)
                if make_primary:
                    raise SomaError(
                        "WORKBOOK_RELATION_INVALID",
                        "Workbook IP row combines address correction and primary replacement",
                    )
            elif make_primary:
                primary = relationships.prepare(
                    None,
                    reader,
                    "SetPrimaryNetworkElementIp",
                    {
                        "network_element_id": target_id,
                        "ip_id": current_ip["network_element_ip_id"],
                        "ip_revision": current_ip["revision"],
                        "primary_set_fingerprint": relationships.primary_fingerprint(
                            reader, target_id
                        ),
                    },
                    command_id,
                )
                row_plans.append(primary)
            elif requested_primary is False and bool(current_ip["is_primary"]):
                # Another selected row must become primary; the batch guard below
                # proves that replacement before receipt insertion.
                pass
            else:
                raise SomaError(
                    "WORKBOOK_STALE",
                    "Workbook IP update no longer contains a material change",
                )

        mutation_plans.extend(row_plans)
        per_proposal_refs[row["proposal_id"]] = (
            [{"kind": "ip", "id": str(current_ip["network_element_ip_id"])}]
            if current_ip is not None
            else list(row_plans[0].result_refs)
        )

    validate_primary_ip_batch(tuple(primary_intents))
    validate_rack_placement_batch(
        reader,
        tuple(rack_intents),
        provisional_sites=provisional_sites,
    )
    validate_containment_batch(reader, containment_intents)

    # Append IP rows that target newly-created workbook elements only after the
    # whole batch's primary/duplicate guards have passed.
    pending_by_target: dict[str, set[str]] = {}
    for row, fields, target_id, plan in pending_ip_rows:
        seen = pending_by_target.setdefault(target_id, set())
        if fields["Address"] in seen:
            raise SomaError(
                "IP_DUPLICATE_ON_ELEMENT",
                "Workbook new Network Element contains duplicate canonical IPs",
            )
        if len(seen) >= 1024:
            raise SomaError(
                "WORKBOOK_RELATION_INVALID",
                "Workbook new Network Element exceeds the IP hard limit",
            )
        seen.add(fields["Address"])
        ip_id = relationships.add_ip(
            reader,
            plan,
            target_id,
            fields["Address"],
            bool(fields.get("Primary")),
        )
        ref = {"kind": "ip", "id": ip_id}
        plan.result_refs.append(ref)
        per_proposal_refs[row["proposal_id"]] = [
            {"kind": "network_element", "id": target_id},
            ref,
        ]

    decisions: list[WorkbookRowDecision] = []
    created = updated = unchanged = 0
    all_refs: list[dict[str, str]] = []
    for row, disposition, _normalized, _current in prepared_rows:
        accepted = disposition["decision"] == "accept"
        refs = per_proposal_refs.get(row["proposal_id"], []) if accepted else []
        all_refs.extend(refs)
        if not accepted:
            terminal = "rejected"
            proposal_state = "rejected"
        elif row["action"] == "create_network_element":
            terminal = "created"
            proposal_state = "accepted"
            created += 1
        elif row["action"] == "unchanged":
            terminal = "unchanged"
            proposal_state = "accepted"
            unchanged += 1
        else:
            terminal = "updated"
            proposal_state = "accepted"
            updated += 1
        decisions.append(
            WorkbookRowDecision(
                proposal_id=row["proposal_id"],
                proposal_state=proposal_state,
                sheet_kind=row["sheet_kind"],
                row_ordinal=int(row["row_ordinal"]),
                row_fingerprint=row["row_fingerprint"],
                disposition=terminal,
                target_network_element_id=(
                    row["target_network_element_id"]
                    if row["target_network_element_id"] is not None
                    else next(
                        (
                            ref["id"] for ref in refs
                            if ref["kind"] == "network_element"
                        ),
                        None,
                    )
                ),
                warning_codes_json=row["warning_codes_json"],
                result_refs_json=canonical_json_bytes(refs[:64]).decode("utf-8"),
            )
        )

    return PreparedWorkbookAcceptance(
        run_id=run["workbook_run_id"],
        run_revision=run["revision"],
        logical_fingerprint=run["logical_fingerprint"],
        mutation_plans=tuple(mutation_plans),
        decisions=tuple(decisions),
        created=created,
        updated=updated,
        unchanged=unchanged,
        result_refs=_dedupe_refs(all_refs),
    )


__all__ = [
    "PreparedWorkbookAcceptance",
    "WorkbookRowDecision",
    "accepted_replay_response",
    "prepare_workbook_acceptance",
]
