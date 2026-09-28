from __future__ import annotations

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.audit.writer import AuditEventInput
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.infrastructure.repositories.core import get, one


COMMAND_NAMES = frozenset({"RejectInfrastructureWorkbookRun"})


def _prepare_reject(service, uow, payload, command_id, *, actor_kind, actor_id):
    run_id = payload["run_id"]
    run = get(uow, "infrastructure_workbook_runs", run_id,
              revision=payload["run_revision"])
    if run["state"] not in ("staged", "reviewed"):
        raise SomaError("WORKBOOK_STALE", "Workbook run is not reviewable")
    if one(uow, "SELECT 1 FROM infrastructure_workbook_row_decisions "
           "WHERE workbook_run_id=? LIMIT 1", (run_id,)) is not None:
        raise SomaError("WORKBOOK_STALE", "Reviewable run already has terminal decisions")
    staged_counts = one(
        uow,
        "SELECT coalesce(sum(sheet_kind='network_elements'),0) network_elements,"
        "coalesce(sum(sheet_kind='ip_addresses'),0) ip_addresses "
        "FROM infrastructure_workbook_staging_rows WHERE workbook_run_id=?",
        (run_id,),
    )
    if (staged_counts["network_elements"] != run["network_element_row_count"]
            or staged_counts["ip_addresses"] != run["ip_row_count"]):
        raise SomaError("WORKBOOK_STALE", "Workbook staging row counts changed")

    def apply(inner):
        # The receipt is inserted by CommandBoundary before this callback, so
        # all terminal evidence remains in the same authoritative UoW.
        inner.connection.execute(
            "UPDATE infrastructure_workbook_proposals SET state='rejected',"
            "last_command_id=?,revision=revision+1 "
            "WHERE workbook_run_id=? AND state='pending'",
            (command_id, run_id),
        )
        recorded = utc_epoch_seconds()
        cursor = inner.connection.execute(
            "SELECT sheet_kind,row_ordinal,row_fingerprint,warning_codes_json "
            "FROM infrastructure_workbook_staging_rows WHERE workbook_run_id=? "
            "ORDER BY sheet_kind,row_ordinal", (run_id,),
        )
        for sheet_kind, row_ordinal, row_fingerprint, warning_codes_json in cursor:
            inner.connection.execute(
                "INSERT INTO infrastructure_workbook_row_decisions "
                "(row_decision_id,workbook_run_id,sheet_kind,row_ordinal,"
                "row_fingerprint,disposition,target_network_element_id,"
                "warning_codes_json,result_refs_json,recorded_at_utc,command_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_uuid4(), run_id, sheet_kind, row_ordinal,
                    row_fingerprint, "rejected", None,
                    warning_codes_json,
                    "[]", recorded, command_id,
                ),
            )
        inner.connection.execute(
            "UPDATE infrastructure_workbook_runs SET state='rejected',"
            "last_command_id=?,revision=revision+1 WHERE workbook_run_id=?",
            (command_id, run_id),
        )
        return AuditEventInput(
            audit_event_id=new_uuid4(), action_type="infrastructure.workbook.reject",
            action_version=1, actor_kind=actor_kind, actor_id=actor_id,
            target_type="workbook_run", target_id=run_id, command_id=command_id,
            payload_schema="INFRA_AUDIT_PAYLOAD_V1", payload_version=1,
            payload={
                "operation": "RejectInfrastructureWorkbookRun",
                "target_refs": [{"kind": "workbook_run", "id": run_id}],
                "base_revisions": {"run_revision": payload["run_revision"]},
                "result_refs": [], "reason_code": payload["reason_code"],
                "workbook_run_id": run_id,
            },
            resulting_event_refs=(),
        )

    def response(inner):
        current = get(inner, "infrastructure_workbook_runs", run_id)
        return {
            "command_id": command_id,
            "run_id": run_id,
            "state": current["state"],
            "revision": current["revision"],
        }

    return PreparedMutation(
        no_change=False, result_type="workbook_run", result_id=run_id,
        apply=apply, response_schema="INFRA_WORKBOOK_RUN_RESULT_V1",
        response_factory=response,
    )


def prepare(service, uow, command, payload, command_id, *, actor_kind="local_user", actor_id=None):
    if command == "RejectInfrastructureWorkbookRun":
        return _prepare_reject(service, uow, payload, command_id,
                               actor_kind=actor_kind, actor_id=actor_id)
    raise SomaError("INFRA_NOT_FOUND", "Infrastructure workbook command is not installed")
