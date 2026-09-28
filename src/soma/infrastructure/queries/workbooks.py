from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.strict_json import loads_strict
from soma.infrastructure.contracts.infrastructure import validate_value
from soma.infrastructure.repositories.core import get, one

from .core import page


QUERY_NAMES = frozenset({"InfrastructureWorkbookReplayQuery", "InfrastructureWorkbookHistoryQuery",
                         "InfrastructureWorkbookRunQuery", "InfrastructureWorkbookProposalQuery"})


def _proposal(row):
    try:
        warnings = loads_strict(row["warning_codes_json"], max_bytes=32_768)
        warnings = validate_value("array<string<=128bytes>,max32", warnings)
    except (ValueError, TypeError, ValidationError) as exc:
        raise IntegrityFailure("Workbook proposal warnings are corrupt") from exc
    return dict(proposal_id=row["proposal_id"], sheet_kind=row["sheet_kind"],
                row_ordinal=row["row_ordinal"], action=row["action"], state=row["state"],
                target_network_element_id=row["target_network_element_id"],
                expected_revision=row["expected_target_revision"],
                input_fingerprint=row["input_fingerprint"], warning_codes=warnings)


def _run(reader, query, p):
    run = get(reader, "infrastructure_workbook_runs", p["run_id"])
    counts = one(
        reader,
        "SELECT coalesce(sum(state='pending'),0) pending,"
        "coalesce(sum(state='accepted'),0) accepted,"
        "coalesce(sum(state='rejected'),0) rejected,"
        "coalesce(sum(state='superseded'),0) superseded,"
        "coalesce(sum(action='ambiguous'),0) ambiguous,"
        "coalesce(sum(action='skip_invalid'),0) invalid "
        "FROM infrastructure_workbook_proposals WHERE workbook_run_id=?",
        (p["run_id"],),
    )


    sql = (
        "SELECT p.proposal_id,p.action,p.state,p.target_network_element_id,"
        "p.expected_target_revision,p.input_fingerprint,s.sheet_kind,s.row_ordinal,"
        "s.warning_codes_json,CASE p.action "
        "WHEN 'create_network_element' THEN 0 WHEN 'create_related_reference' THEN 0 "
        "WHEN 'update_network_element' THEN 1 WHEN 'update_ip_set' THEN 2 "
        "WHEN 'relationship_change' THEN 2 WHEN 'unchanged' THEN 3 "
        "WHEN 'ambiguous' THEN 4 WHEN 'unknown_reference' THEN 5 "
        "WHEN 'skip_invalid' THEN 6 END proposal_group_order "
        "FROM infrastructure_workbook_proposals p "
        "JOIN infrastructure_workbook_staging_rows s USING(staging_row_id) "
        "WHERE p.workbook_run_id=?"
    )
    params = [p["run_id"]]
    if p.get("proposal_state") is not None:
        sql += " AND p.state=?"
        params.append(p["proposal_state"])
    proposals, continuation = page(
        reader, query, p, sql, params,
        ["proposal_group_order", "sheet_kind", "row_ordinal", "proposal_id"],
    )
    return dict(
        run_id=p["run_id"], state=run["state"], revision=run["revision"],
        workbook_version=run["workbook_version"], mode=run["workbook_mode"],
        installation_relation=run["installation_relation"], file_sha256=run["file_sha256"],
        logical_fingerprint=run["logical_fingerprint"],
        row_counts=dict(network_elements=run["network_element_row_count"],
                        ip_addresses=run["ip_row_count"], warnings=run["warning_count"]),
        proposal_counts={key: counts[key] for key in
                         ("pending", "accepted", "rejected", "superseded", "ambiguous", "invalid")},
        proposals=[_proposal(row) for row in proposals], next_cursor=continuation,
    )


def _proposal_detail(reader, p):
    row = one(
        reader,
        "SELECT p.proposal_id,p.action,p.state,p.target_network_element_id,"
        "p.expected_target_revision,p.input_fingerprint,p.impact_json,p.candidate_ids_json,"
        "s.sheet_kind,s.row_ordinal,s.warning_codes_json "
        "FROM infrastructure_workbook_proposals p "
        "JOIN infrastructure_workbook_staging_rows s ON s.staging_row_id=p.staging_row_id "
        "WHERE p.proposal_id=?",
        (p["proposal_id"],),
    )
    if row is None:
        raise SomaError("INFRA_NOT_FOUND", "Infrastructure workbook proposal does not exist")
    try:
        impact = validate_value(
            "INFRA_WORKBOOK_IMPACT_V1", loads_strict(row["impact_json"], max_bytes=131_072),
        )
        candidate_ids = validate_value(
            "array<uuid>,max500", loads_strict(row["candidate_ids_json"], max_bytes=32_768),
        )
        if candidate_ids != sorted(set(candidate_ids)):
            raise IntegrityFailure("Workbook candidate IDs are not sorted and unique")
    except (ValueError, TypeError, ValidationError) as exc:
        raise IntegrityFailure("Workbook proposal detail is corrupt") from exc
    return {"proposal": _proposal(row), "impact": impact, "candidate_ids": candidate_ids}


def execute(service, reader, query, p):
    if query == "InfrastructureWorkbookRunQuery":
        return _run(reader, query, p)
    if query == "InfrastructureWorkbookProposalQuery":
        return _proposal_detail(reader, p)
    if query == "InfrastructureWorkbookReplayQuery":
        result = one(
            reader,
            "SELECT accepted_workbook_run_id accepted_run_id,accepted_at_utc "
            "FROM infrastructure_workbook_replay_index WHERE logical_fingerprint=?",
            (p["logical_fingerprint"],),
        )
        return result or {"accepted_run_id": None, "accepted_at_utc": None}

    run_filters = []
    run_values = []
    export_filters = []
    export_values = []
    if p.get("state") is not None:
        run_filters.append("state=?")
        run_values.append(p["state"])
    if p.get("mode") is not None:
        run_filters.append("workbook_mode=?")
        run_values.append(p["mode"])
        export_filters.append("mode=?")
        export_values.append(p["mode"])
    run_sql = (
        "SELECT 'run' kind,workbook_run_id id,captured_at_utc timestamp_utc,"
        "state state_or_mode,source_filename filename,file_sha256 sha256 "
        "FROM infrastructure_workbook_runs"
        + (" WHERE " + " AND ".join(run_filters) if run_filters else "")
    )
    if p.get("state") is None:
        export_sql = (
            "SELECT 'export' kind,export_id id,generated_at_utc timestamp_utc,"
            "mode state_or_mode,artifact_filename filename,artifact_sha256 sha256 "
            "FROM infrastructure_workbook_exports"
            + (" WHERE " + " AND ".join(export_filters) if export_filters else "")
        )
        run_sql += " UNION ALL " + export_sql
        run_values.extend(export_values)
    items, continuation = page(
        reader, query, p, run_sql, run_values,
        ["timestamp_utc", "kind", "id"], ["DESC", "ASC", "DESC"],
    )
    return {"items": items, "next_cursor": continuation}
