from __future__ import annotations

import hashlib

from soma.foundation.strict_json import canonical_json_bytes
from soma.infrastructure.contracts.infrastructure import validate_value
from soma.infrastructure.domain.sites import match_key


def _entity(kind: str, identity: str) -> dict[str, str]:
    return {"kind": kind, "id": identity}


def _impact(
    *,
    creates=(),
    updates=(),
    relationship_changes=(),
    warning_codes=(),
) -> dict:
    return validate_value(
        "INFRA_WORKBOOK_IMPACT_V1",
        {
            "creates": list(creates),
            "updates": list(updates),
            "relationship_changes": list(relationship_changes),
            "warning_codes": list(warning_codes),
            "destructive_change": False,
        },
    )


def _proposal_fingerprint(
    *,
    row_fingerprint: str,
    action: str,
    target_network_element_id: str | None,
    expected_revision: int | None,
    current_tokens: dict[str, object],
    candidate_ids: list[str],
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "schema": "INFRA_WORKBOOK_PROPOSAL_INPUT_V1",
                "row_fingerprint": row_fingerprint,
                "action": action,
                "target_network_element_id": target_network_element_id,
                "expected_revision": expected_revision,
                "current_tokens": current_tokens,
                "candidate_ids": candidate_ids,
            }
        )
    ).hexdigest()


def _network_element_candidates(reader, fields: dict) -> list[str]:
    predicates: list[str] = []
    values: list[object] = []
    name = fields.get("OperationalName")
    serial = fields.get("ManufacturerSerial")
    if name:
        predicates.append("name_match_key=?")
        values.append(match_key(name))
    if serial:
        predicates.append("serial_match_key=?")
        values.append(match_key(serial))
    if not predicates:
        return []
    rows = reader.connection.execute(
        "SELECT network_element_id FROM network_elements WHERE "
        + " OR ".join(predicates)
        + " ORDER BY network_element_id LIMIT 501",
        tuple(values),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _name_candidates(reader, operational_name: str | None) -> list[str]:
    if not operational_name:
        return []
    rows = reader.connection.execute(
        "SELECT network_element_id FROM network_elements "
        "WHERE name_match_key=? ORDER BY network_element_id LIMIT 501",
        (match_key(operational_name),),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _bounded_candidates(values: list[str], warnings: list[str]) -> list[str]:
    unique = sorted(set(values))
    if len(unique) > 500:
        warnings.append("WORKBOOK_CANDIDATES_TRUNCATED")
    return unique[:500]


def _network_element_proposal(
    reader,
    *,
    fields: dict,
    row_fingerprint: str,
    same_installation: bool,
) -> dict:
    warnings: list[str] = []
    target_id = fields.get("SomaNetworkElementId") if same_installation else None
    expected_revision: int | None = None
    current_tokens: dict[str, object] = {}

    if target_id is None:
        candidates = _bounded_candidates(
            _network_element_candidates(reader, fields),
            warnings,
        )
        if candidates:
            action = "ambiguous"
            warnings.append("WORKBOOK_AMBIGUOUS_IDENTITY")
            impact = _impact(warning_codes=warnings)
        else:
            site_id = fields.get("SomaSiteId") if same_installation else None
            site = None
            if site_id is not None:
                site = reader.connection.execute(
                    "SELECT site_id,lifecycle_state FROM sites WHERE site_id=?",
                    (site_id,),
                ).fetchone()
            if not fields.get("OperationalName"):
                action = "skip_invalid"
                warnings.append("WORKBOOK_REQUIRED_FIELD_MISSING")
                impact = _impact(warning_codes=warnings)
            elif site is None or str(site[1]) != "active":
                action = "create_related_reference"
                warnings.append("WORKBOOK_SITE_REVIEW_REQUIRED")
                impact = _impact(
                    relationship_changes=["site_resolution_required"],
                    warning_codes=warnings,
                )
            else:
                action = "create_network_element"
                impact = _impact(
                    relationship_changes=["create_network_element"],
                    warning_codes=warnings,
                )
        fingerprint = _proposal_fingerprint(
            row_fingerprint=row_fingerprint,
            action=action,
            target_network_element_id=None,
            expected_revision=None,
            current_tokens={},
            candidate_ids=candidates,
        )
        return {
            "action": action,
            "target_network_element_id": None,
            "expected_target_revision": None,
            "input_fingerprint": fingerprint,
            "impact": impact,
            "candidate_ids": candidates,
            "warning_codes": warnings,
        }

    target = reader.connection.execute(
        "SELECT network_element_id,site_id,operational_name,manufacturer_serial,"
        "lifecycle_state,revision FROM network_elements WHERE network_element_id=?",
        (target_id,),
    ).fetchone()
    if target is None:
        warnings.append("WORKBOOK_UNKNOWN_TARGET")
        action = "unknown_reference"
        impact = _impact(warning_codes=warnings)
        fingerprint = _proposal_fingerprint(
            row_fingerprint=row_fingerprint,
            action=action,
            target_network_element_id=None,
            expected_revision=None,
            current_tokens={},
            candidate_ids=[],
        )
        return {
            "action": action,
            "target_network_element_id": None,
            "expected_target_revision": None,
            "input_fingerprint": fingerprint,
            "impact": impact,
            "candidate_ids": [],
            "warning_codes": warnings,
        }
    target = tuple(target)
    target_site_id = str(target[1])
    expected_revision = int(target[5])
    current_tokens.update(
        {
            "target_revision": expected_revision,
            "target_site_id": target_site_id,
            "target_lifecycle": str(target[4]),
        }
    )
    if str(target[4]) != "active":
        warnings.append("WORKBOOK_TARGET_ARCHIVED")
        action = "skip_invalid"
        impact = _impact(
            updates=[_entity("network_element", str(target_id))],
            warning_codes=warnings,
        )
    elif fields.get("SomaSiteId") not in (None, target_site_id):
        warnings.append("WORKBOOK_RELATION_INVALID")
        action = "skip_invalid"
        impact = _impact(
            updates=[_entity("network_element", str(target_id))],
            relationship_changes=["site_id_mismatch"],
            warning_codes=warnings,
        )
    else:
        descriptive_change = any(
            fields.get(name) is not None and fields.get(name) != current
            for name, current in (
                ("OperationalName", target[2]),
                ("ManufacturerSerial", target[3]),
            )
        )
        relationship_changes: list[str] = []

        placement = reader.connection.execute(
            "SELECT rack_id,u_start,u_span,revision FROM network_element_placement_current "
            "WHERE network_element_id=?",
            (target_id,),
        ).fetchone()
        if placement is None:
            warnings.append("WORKBOOK_RELATION_INVALID")
            action = "skip_invalid"
            impact = _impact(
                updates=[_entity("network_element", str(target_id))],
                warning_codes=warnings,
            )
        else:
            placement = tuple(placement)
            current_tokens["placement_revision"] = int(placement[3])
            rack_id = fields.get("SomaRackId")
            if rack_id is not None:
                rack = reader.connection.execute(
                    "SELECT r.rack_id,r.lifecycle_state,m.site_id "
                    "FROM racks r JOIN rooms m ON m.room_id=r.room_id WHERE r.rack_id=?",
                    (rack_id,),
                ).fetchone()
                if rack is None:
                    warnings.append("WORKBOOK_UNKNOWN_REFERENCE")
                elif str(rack[1]) != "active" or str(rack[2]) != target_site_id:
                    warnings.append("WORKBOOK_RELATION_INVALID")
                else:
                    desired = (
                        rack_id,
                        fields.get("RackUStart") if fields.get("RackUStart") is not None else placement[1],
                        fields.get("RackUSpan") if fields.get("RackUSpan") is not None else placement[2],
                    )
                    if desired != (placement[0], placement[1], placement[2]):
                        relationship_changes.append("rack_placement")

            model = reader.connection.execute(
                "SELECT network_element_model_id,revision FROM network_element_model_current "
                "WHERE network_element_id=?",
                (target_id,),
            ).fetchone()
            current_tokens["model_revision"] = None if model is None else int(model[1])
            model_id = fields.get("SomaModelId")
            if model_id is not None:
                valid_model = reader.connection.execute(
                    "SELECT lifecycle_state FROM network_element_models "
                    "WHERE network_element_model_id=?",
                    (model_id,),
                ).fetchone()
                if valid_model is None:
                    warnings.append("WORKBOOK_UNKNOWN_REFERENCE")
                elif str(valid_model[0]) != "active":
                    warnings.append("WORKBOOK_RELATION_INVALID")
                elif model is None or str(model[0]) != model_id:
                    relationship_changes.append("model_assignment")

            cloud = reader.connection.execute(
                "SELECT cloud_deployment_id,revision FROM cloud_assignment_current "
                "WHERE network_element_id=?",
                (target_id,),
            ).fetchone()
            current_tokens["cloud_revision"] = None if cloud is None else int(cloud[1])
            cloud_id = fields.get("SomaCloudDeploymentId")
            if cloud_id is not None:
                valid_cloud = reader.connection.execute(
                    "SELECT lifecycle_state,site_id FROM cloud_deployments "
                    "WHERE cloud_deployment_id=?",
                    (cloud_id,),
                ).fetchone()
                if valid_cloud is None:
                    warnings.append("WORKBOOK_UNKNOWN_REFERENCE")
                elif str(valid_cloud[0]) != "active" or str(valid_cloud[1]) != target_site_id:
                    warnings.append("WORKBOOK_RELATION_INVALID")
                elif cloud is None or str(cloud[0]) != cloud_id:
                    relationship_changes.append("cloud_assignment")

            parent = reader.connection.execute(
                "SELECT parent_network_element_id,revision "
                "FROM network_element_containment_current "
                "WHERE child_network_element_id=?",
                (target_id,),
            ).fetchone()
            current_tokens["containment_revision"] = None if parent is None else int(parent[1])
            parent_id = fields.get("SomaParentNetworkElementId")
            if parent_id is not None:
                valid_parent = reader.connection.execute(
                    "SELECT lifecycle_state FROM network_elements WHERE network_element_id=?",
                    (parent_id,),
                ).fetchone()
                if valid_parent is None:
                    warnings.append("WORKBOOK_UNKNOWN_REFERENCE")
                elif str(valid_parent[0]) != "active" or parent_id == target_id:
                    warnings.append("WORKBOOK_RELATION_INVALID")
                elif parent is None or str(parent[0]) != parent_id:
                    relationship_changes.append("containment_parent")

            if "WORKBOOK_RELATION_INVALID" in warnings:
                action = "skip_invalid"
            elif "WORKBOOK_UNKNOWN_REFERENCE" in warnings:
                action = "unknown_reference"
            elif relationship_changes:
                action = "relationship_change"
            elif descriptive_change:
                action = "update_network_element"
            else:
                action = "unchanged"
            impact = _impact(
                updates=[_entity("network_element", str(target_id))]
                if action in {"update_network_element", "relationship_change"}
                else [],
                relationship_changes=relationship_changes,
                warning_codes=warnings,
            )

    candidates: list[str] = []
    fingerprint = _proposal_fingerprint(
        row_fingerprint=row_fingerprint,
        action=action,
        target_network_element_id=str(target_id),
        expected_revision=expected_revision,
        current_tokens=current_tokens,
        candidate_ids=candidates,
    )
    return {
        "action": action,
        "target_network_element_id": str(target_id),
        "expected_target_revision": expected_revision,
        "input_fingerprint": fingerprint,
        "impact": impact,
        "candidate_ids": candidates,
        "warning_codes": warnings,
    }


def _ip_proposal(
    reader,
    *,
    fields: dict,
    row_fingerprint: str,
    same_installation: bool,
) -> dict:
    warnings: list[str] = []
    target_id = fields.get("SomaNetworkElementId") if same_installation else None
    if target_id is None:
        candidates = _bounded_candidates(
            _name_candidates(reader, fields.get("OperationalName")),
            warnings,
        )
        if candidates:
            action = "ambiguous"
            warnings.append("WORKBOOK_AMBIGUOUS_IDENTITY")
        else:
            action = "unknown_reference"
            warnings.append("WORKBOOK_UNKNOWN_TARGET")
        impact = _impact(warning_codes=warnings)
        fingerprint = _proposal_fingerprint(
            row_fingerprint=row_fingerprint,
            action=action,
            target_network_element_id=None,
            expected_revision=None,
            current_tokens={},
            candidate_ids=candidates,
        )
        return {
            "action": action,
            "target_network_element_id": None,
            "expected_target_revision": None,
            "input_fingerprint": fingerprint,
            "impact": impact,
            "candidate_ids": candidates,
            "warning_codes": warnings,
        }

    target = reader.connection.execute(
        "SELECT lifecycle_state,revision FROM network_elements WHERE network_element_id=?",
        (target_id,),
    ).fetchone()
    if target is None or str(target[0]) != "active":
        action = "unknown_reference" if target is None else "skip_invalid"
        warnings.append("WORKBOOK_UNKNOWN_TARGET" if target is None else "WORKBOOK_TARGET_ARCHIVED")
        expected_revision = None if target is None else int(target[1])
        impact = _impact(warning_codes=warnings)
        fingerprint = _proposal_fingerprint(
            row_fingerprint=row_fingerprint,
            action=action,
            target_network_element_id=str(target_id) if target is not None else None,
            expected_revision=expected_revision,
            current_tokens={},
            candidate_ids=[],
        )
        return {
            "action": action,
            "target_network_element_id": str(target_id) if target is not None else None,
            "expected_target_revision": expected_revision,
            "input_fingerprint": fingerprint,
            "impact": impact,
            "candidate_ids": [],
            "warning_codes": warnings,
        }

    expected_revision = int(target[1])
    ip_id = fields.get("SomaIpId") if same_installation else None
    current = None
    if ip_id is not None:
        current = reader.connection.execute(
            "SELECT network_element_ip_id,network_element_id,canonical_address,"
            "is_primary,active,revision FROM network_element_ip_current "
            "WHERE network_element_ip_id=?",
            (ip_id,),
        ).fetchone()
        if current is None or str(current[1]) != target_id or int(current[4]) != 1:
            warnings.append("WORKBOOK_UNKNOWN_REFERENCE")
            current = None
    else:
        current = reader.connection.execute(
            "SELECT network_element_ip_id,network_element_id,canonical_address,"
            "is_primary,active,revision FROM network_element_ip_current "
            "WHERE network_element_id=? AND canonical_address=? AND active=1",
            (target_id, fields["Address"]),
        ).fetchone()

    current_tokens = {"target_revision": expected_revision}
    if current is not None:
        current_tokens["ip_revision"] = int(current[5])
        same = (
            str(current[2]) == fields["Address"]
            and (fields.get("Primary") is None or bool(current[3]) == fields["Primary"])
        )
        action = "unchanged" if same else "update_ip_set"
        impact = _impact(
            updates=[] if same else [_entity("ip", str(current[0]))],
            relationship_changes=[] if same else ["ip_set"],
            warning_codes=warnings,
        )
    elif "WORKBOOK_UNKNOWN_REFERENCE" in warnings:
        action = "unknown_reference"
        impact = _impact(warning_codes=warnings)
    else:
        action = "update_ip_set"
        impact = _impact(
            relationship_changes=["add_ip"],
            warning_codes=warnings,
        )

    fingerprint = _proposal_fingerprint(
        row_fingerprint=row_fingerprint,
        action=action,
        target_network_element_id=str(target_id),
        expected_revision=expected_revision,
        current_tokens=current_tokens,
        candidate_ids=[],
    )
    return {
        "action": action,
        "target_network_element_id": str(target_id),
        "expected_target_revision": expected_revision,
        "input_fingerprint": fingerprint,
        "impact": impact,
        "candidate_ids": [],
        "warning_codes": warnings,
    }


def build_workbook_proposal(
    reader,
    *,
    sheet_kind: str,
    normalized_row: dict,
    row_fingerprint: str,
    same_installation: bool,
) -> dict:
    fields = normalized_row["fields"]
    if sheet_kind == "network_elements":
        return _network_element_proposal(
            reader,
            fields=fields,
            row_fingerprint=row_fingerprint,
            same_installation=same_installation,
        )
    if sheet_kind == "ip_addresses":
        return _ip_proposal(
            reader,
            fields=fields,
            row_fingerprint=row_fingerprint,
            same_installation=same_installation,
        )
    raise ValueError("unsupported Infrastructure workbook staging sheet")
