from __future__ import annotations

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.audit.writer import AuditEventInput
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.queries.data_instance_identity import DataInstanceIdentityReader
from soma.infrastructure.jobs import EXPORT_JOB_TYPE, STAGE_JOB_TYPE
from soma.infrastructure.repositories.core import get, one
from soma.infrastructure.settings import IMPORT_DIRECTORY_KEY, require_saved_import_directory


COMMAND_NAMES = frozenset({
    "GenerateInfrastructureWorkbook",
    "StageInfrastructureWorkbookCheck",
    "RejectInfrastructureWorkbookRun",
})


def _job_response(uow, command_id: str, job_id: str, expected_job_type: str) -> dict:
    row = one(
        uow,
        "SELECT job_type,state FROM durable_jobs WHERE job_id=?",
        (job_id,),
    )
    if row is None or row["job_type"] != expected_job_type:
        raise SomaError("INFRA_STALE", "Infrastructure workbook job identity is unavailable")
    return {
        "command_id": command_id,
        "job_id": job_id,
        "job_type": expected_job_type,
        "state": row["state"],
    }


def _validate_export_scope_targets(service, uow, scope: dict) -> None:
    kind = scope["scope_kind"]
    if kind == "all":
        return
    if kind == "customer":
        try:
            service.reference_queries.get_reference_by_id_in_reader(
                uow,
                reference_type="customer_organization",
                reference_id=scope["customer_org_id"],
            )
        except SomaError as exc:
            if exc.code == "NOT_FOUND":
                raise SomaError(
                    "INFRA_STALE",
                    "Infrastructure workbook export customer scope no longer exists",
                ) from exc
            raise
        return
    if kind == "site":
        exists = one(
            uow,
            "SELECT site_id FROM sites WHERE site_id=?",
            (scope["site_id"],),
        )
        if exists is None:
            raise SomaError(
                "INFRA_STALE",
                "Infrastructure workbook export Site scope no longer exists",
            )
        return
    if kind == "network_elements":
        requested = scope["network_element_ids"]
        if not requested:
            raise SomaError("INFRA_STALE", "Infrastructure workbook export scope is empty")
        placeholders = ",".join("?" for _ in requested)
        rows = uow.connection.execute(
            f"SELECT network_element_id FROM network_elements "
            f"WHERE network_element_id IN ({placeholders})",
            tuple(requested),
        ).fetchall()
        if {str(row[0]) for row in rows} != set(requested):
            raise SomaError(
                "INFRA_STALE",
                "Infrastructure workbook export Network Element scope changed",
            )
        return
    raise SomaError("INFRA_STALE", "Infrastructure workbook export scope is unsupported")


def _prepare_generate(service, uow, payload, command_id, *, actor_kind, actor_id):
    _validate_export_scope_targets(service, uow, payload["scope"])
    data_instance_id = DataInstanceIdentityReader.get(uow)
    job_payload = {
        "export_request_id": command_id,
        "mode": payload["mode"],
        "scope": payload["scope"],
        "destination_directory": payload["destination_directory"],
        "data_instance_id": data_instance_id,
    }
    state: dict[str, str] = {}

    def apply(inner):
        job_id = service.job_coordinator.enqueue_or_coalesce(
            inner,
            EXPORT_JOB_TYPE,
            1,
            job_payload,
            command_id,
        )
        state["job_id"] = job_id
        return AuditEventInput(
            audit_event_id=new_uuid4(),
            action_type="infrastructure.workbook.export_request",
            action_version=1,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type="workbook_export",
            target_id=command_id,
            command_id=command_id,
            payload_schema="INFRA_AUDIT_PAYLOAD_V1",
            payload_version=1,
            payload={
                "operation": "GenerateInfrastructureWorkbook",
                "target_refs": [],
                "base_revisions": {},
                "result_refs": [],
            },
            resulting_event_refs=(),
        )

    def response(inner):
        job_id = state.get("job_id")
        if job_id is None:
            raise SomaError("INFRA_STALE", "Infrastructure workbook export job was not enqueued")
        return _job_response(inner, command_id, job_id, EXPORT_JOB_TYPE)

    return PreparedMutation(
        no_change=False,
        result_type="durable_job",
        result_id=None,
        apply=apply,
        response_schema="INFRA_JOB_ACCEPTED_V1",
        response_factory=response,
    )


def _prepare_stage(service, uow, payload, command_id, *, actor_kind, actor_id):
    if service.setting_service is None:
        raise SomaError(
            "INFRA_STALE",
            "Infrastructure import directory setting provider is unavailable",
        )
    setting = service.setting_service.get_in_reader(uow, IMPORT_DIRECTORY_KEY)
    directory = require_saved_import_directory(setting, payload["setting_revision"])
    data_instance_id = DataInstanceIdentityReader.get(uow)
    job_payload = {
        "run_request_id": command_id,
        "import_directory": directory["path"],
        "setting_revision": payload["setting_revision"],
        "data_instance_id": data_instance_id,
    }
    state: dict[str, str] = {}

    def apply(inner):
        job_id = service.job_coordinator.enqueue_or_coalesce(
            inner,
            STAGE_JOB_TYPE,
            1,
            job_payload,
            str(payload["setting_revision"]),
        )
        state["job_id"] = job_id
        return AuditEventInput(
            audit_event_id=new_uuid4(),
            action_type="infrastructure.workbook.check_request",
            action_version=1,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type="workbook_run",
            target_id=command_id,
            command_id=command_id,
            payload_schema="INFRA_AUDIT_PAYLOAD_V1",
            payload_version=1,
            payload={
                "operation": "StageInfrastructureWorkbookCheck",
                "target_refs": [],
                "base_revisions": {
                    "setting_revision": payload["setting_revision"],
                },
                "result_refs": [],
            },
            resulting_event_refs=(),
        )

    def response(inner):
        job_id = state.get("job_id")
        if job_id is None:
            raise SomaError("INFRA_STALE", "Infrastructure workbook stage job was not enqueued")
        return _job_response(inner, command_id, job_id, STAGE_JOB_TYPE)

    return PreparedMutation(
        no_change=False,
        result_type="durable_job",
        result_id=None,
        apply=apply,
        response_schema="INFRA_JOB_ACCEPTED_V1",
        response_factory=response,
    )

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
    if command == "GenerateInfrastructureWorkbook":
        return _prepare_generate(
            service, uow, payload, command_id,
            actor_kind=actor_kind, actor_id=actor_id,
        )
    if command == "StageInfrastructureWorkbookCheck":
        return _prepare_stage(
            service, uow, payload, command_id,
            actor_kind=actor_kind, actor_id=actor_id,
        )
    if command == "RejectInfrastructureWorkbookRun":
        return _prepare_reject(service, uow, payload, command_id,
                               actor_kind=actor_kind, actor_id=actor_id)
    raise SomaError("INFRA_NOT_FOUND", "Infrastructure workbook command is not installed")
