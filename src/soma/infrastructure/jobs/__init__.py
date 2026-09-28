"""Infrastructure durable-job contracts; filesystem workers are separate."""

from __future__ import annotations

import re
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.jobs import JobTypeContract, StaleRecoveryDisposition
from soma.infrastructure.contracts.infrastructure import validate_value
from soma.infrastructure.settings import validate_import_directory


EXPORT_JOB_TYPE = "INFRA_WORKBOOK_EXPORT_V1"
STAGE_JOB_TYPE = "INFRA_WORKBOOK_STAGE_V1"
_ACTIVE = frozenset({"queued", "running", "waiting_review", "retry_wait"})
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ERROR = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_RETRY_DELAYS = {1: 5, 2: 30, 3: 120}
_RETRYABLE = frozenset({"JOB_INTERRUPTED", "PERSISTENCE_BUSY", "WORKBOOK_IO_TRANSIENT"})


def _object(value: Any, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(f"{label} has missing or unknown fields")
    return value


def _uuid(value: Any) -> None:
    require_uuid4(value)


def _nonnegative(value: Any) -> None:
    if type(value) is not int or value < 0:
        raise ValidationError("Workbook job integer must be nonnegative")


def _sha(value: Any) -> None:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValidationError("Workbook job fingerprint must be lowercase SHA-256")


def _filename(value: Any) -> None:
    if not isinstance(value, str):
        raise ValidationError("Workbook job checkpoint requires a filename-only identity")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise ValidationError("Workbook job filename is not valid UTF-8") from exc
    if (not value or size > 1024
            or value in (".", "..") or any(c in value for c in ("/", "\\", ":", "\x00"))):
        raise ValidationError("Workbook job checkpoint requires a filename-only identity")


def _scope(value: Any) -> None:
    scope = validate_value("INFRA_EXPORT_SCOPE_V1", value)
    field = {
        "all": None, "customer": "customer_org_id", "site": "site_id",
        "network_elements": "network_element_ids",
    }[scope["scope_kind"]]
    present = {key for key, item in scope.items() if key != "scope_kind" and item is not None}
    if present != ({field} if field else set()):
        raise ValidationError("Workbook export scope fields disagree with scope kind")
    if field == "network_element_ids" and not scope[field]:
        raise ValidationError("Workbook explicit Network Element scope cannot be empty")


def validate_export_payload(value: Any) -> None:
    p = _object(value, {
        "export_request_id", "mode", "scope", "destination_directory", "data_instance_id",
    }, "Infrastructure export job payload")
    _uuid(p["export_request_id"])
    _uuid(p["data_instance_id"])
    if p["mode"] not in ("registration_template", "discovery", "round_trip"):
        raise ValidationError("Infrastructure export mode is invalid")
    _scope(p["scope"])
    validate_import_directory({"path": p["destination_directory"]})


def validate_stage_payload(value: Any) -> None:
    p = _object(value, {
        "run_request_id", "import_directory", "setting_revision", "data_instance_id",
    }, "Infrastructure stage job payload")
    _uuid(p["run_request_id"])
    _uuid(p["data_instance_id"])
    validate_import_directory({"path": p["import_directory"]})
    if type(p["setting_revision"]) is not int or p["setting_revision"] < 1:
        raise ValidationError("Infrastructure import setting revision must be positive")


def validate_export_checkpoint(value: Any) -> None:
    p = _object(value, {
        "phase", "export_id", "temp_filename", "verified_sha256",
        "verified_size_bytes", "final_filename",
    }, "Infrastructure export checkpoint")
    phase = p["phase"]
    phases = ("queued", "writing", "verifying", "verified", "published", "evidence_recorded")
    if phase not in phases:
        raise ValidationError("Infrastructure export checkpoint phase is invalid")
    if p["export_id"] is not None:
        _uuid(p["export_id"])
    if p["temp_filename"] is not None:
        _filename(p["temp_filename"])
    if p["final_filename"] is not None:
        _filename(p["final_filename"])
    if p["verified_sha256"] is not None:
        _sha(p["verified_sha256"])
    if p["verified_size_bytes"] is not None:
        _nonnegative(p["verified_size_bytes"])
        if p["verified_size_bytes"] == 0:
            raise ValidationError("Verified workbook size must be positive")
    if (p["verified_sha256"] is None) != (p["verified_size_bytes"] is None):
        raise ValidationError("Workbook verification digest and size must be paired")
    if phase != "queued" and p["export_id"] is None:
        raise ValidationError("Workbook export identity must precede filesystem work")
    if phase in ("writing", "verifying", "verified") and p["temp_filename"] is None:
        raise ValidationError("Unpublished export phase requires owned temp identity")
    if phase in ("verified", "published", "evidence_recorded") and p["verified_sha256"] is None:
        raise ValidationError("Published export phase requires verification evidence")
    if phase in ("published", "evidence_recorded") and p["final_filename"] is None:
        raise ValidationError("Published export phase requires final filename")


def validate_stage_checkpoint(value: Any) -> None:
    p = _object(value, {
        "phase", "candidate_manifest_sha256", "candidate_count", "candidate_index",
        "current_filename", "current_file_size_bytes", "current_file_mtime_ns",
        "current_file_sha256", "current_workbook_run_id",
        "last_committed_network_element_row", "last_committed_ip_row",
        "published_run_ids",
    }, "Infrastructure stage checkpoint")
    if p["phase"] not in (
        "discovering", "parsing", "staging", "publishing", "waiting_review", "completed",
    ):
        raise ValidationError("Infrastructure stage checkpoint phase is invalid")
    for key in ("candidate_manifest_sha256", "current_file_sha256"):
        if p[key] is not None:
            _sha(p[key])
    for key in ("candidate_count", "current_file_size_bytes", "current_file_mtime_ns"):
        if p[key] is not None:
            _nonnegative(p[key])
    _nonnegative(p["candidate_index"])
    if p["candidate_count"] is not None and p["candidate_index"] > p["candidate_count"]:
        raise ValidationError("Infrastructure stage cursor exceeds candidate count")
    if (p["candidate_manifest_sha256"] is None) != (p["candidate_count"] is None):
        raise ValidationError("Infrastructure candidate manifest and count must be paired")
    if p["candidate_index"] and p["candidate_manifest_sha256"] is None:
        raise ValidationError("Infrastructure candidate cursor requires a manifest")
    if p["current_filename"] is not None:
        _filename(p["current_filename"])
    current = ("current_filename", "current_file_size_bytes", "current_file_mtime_ns", "current_file_sha256")
    if any(p[key] is None for key in current) and any(p[key] is not None for key in current):
        raise ValidationError("Infrastructure candidate file identity must be complete")
    if p["current_workbook_run_id"] is not None:
        _uuid(p["current_workbook_run_id"])
        if p["current_filename"] is None:
            raise ValidationError("Infrastructure validating run requires source identity")
    for key in ("last_committed_network_element_row", "last_committed_ip_row"):
        if p[key] is not None and (type(p[key]) is not int or p[key] < 1):
            raise ValidationError("Infrastructure staged row cursor must be positive")
        if p[key] is not None and p["current_workbook_run_id"] is None:
            raise ValidationError("Infrastructure staged row cursor requires a run")
    if not isinstance(p["published_run_ids"], list) or len(p["published_run_ids"]) > 512:
        raise ValidationError("Infrastructure published run cache exceeds its bound")
    for identity in p["published_run_ids"]:
        _uuid(identity)
    if len(p["published_run_ids"]) != len(set(p["published_run_ids"])):
        raise ValidationError("Infrastructure published run cache contains duplicates")
    if p["phase"] in ("parsing", "staging", "publishing"):
        if p["candidate_manifest_sha256"] is None or p["current_filename"] is None:
            raise ValidationError("Infrastructure stage phase lacks committed source identity")


def _validate_failure(error_code: str, attempt_ordinal: int, now: int,
                      retry_at: int | None) -> None:
    if not isinstance(error_code, str) or _ERROR.fullmatch(error_code) is None:
        raise ValidationError("Infrastructure job failure code is invalid")
    if type(attempt_ordinal) is not int or attempt_ordinal < 1:
        raise ValidationError("Infrastructure job attempt ordinal is invalid")
    _nonnegative(now)
    if retry_at is not None:
        if (error_code not in _RETRYABLE or attempt_ordinal not in _RETRY_DELAYS
                or retry_at != now + _RETRY_DELAYS[attempt_ordinal]):
            raise ValidationError("Infrastructure job retry timing is invalid")


def _validate_cancellation(context: Any, state: str) -> None:
    if not isinstance(context, dict) or set(context) != {"command_id"}:
        raise ValidationError("Infrastructure cancellation requires a command identity")
    _uuid(context["command_id"])
    if state not in _ACTIVE:
        raise ValidationError("Infrastructure job is not cancellable from this state")


def _recover_stale(payload: Any, checkpoint: Any | None,
                   attempt_ordinal: int, now: int) -> StaleRecoveryDisposition:
    _nonnegative(now)
    if type(attempt_ordinal) is not int or attempt_ordinal < 1:
        raise ValidationError("Infrastructure recovery attempt ordinal is invalid")
    if checkpoint is not None:
        if "export_request_id" in payload:
            validate_export_checkpoint(checkpoint)
        else:
            validate_stage_checkpoint(checkpoint)
    # The worker must reconcile checkpoint, current setting/installation identity,
    # source bytes or published artifact before resuming; Foundation does not do IO.
    return StaleRecoveryDisposition(
        state="retry_wait", next_attempt_at_utc=now, error_code="JOB_INTERRUPTED",
    )


EXPORT_JOB_CONTRACT = JobTypeContract(
    job_type=EXPORT_JOB_TYPE, contract_version=1,
    validate_payload=validate_export_payload,
    validate_checkpoint=validate_export_checkpoint,
    derive_dedupe_key=lambda payload: str(payload["export_request_id"]),
    coalesce_states=_ACTIVE,
    validate_failure=_validate_failure,
    validate_cancellation=_validate_cancellation,
    recover_stale=_recover_stale,
)

STAGE_JOB_CONTRACT = JobTypeContract(
    job_type=STAGE_JOB_TYPE, contract_version=1,
    validate_payload=validate_stage_payload,
    validate_checkpoint=validate_stage_checkpoint,
    derive_dedupe_key=lambda payload: str(payload["setting_revision"]),
    coalesce_states=_ACTIVE,
    validate_failure=_validate_failure,
    validate_cancellation=_validate_cancellation,
    recover_stale=_recover_stale,
)

INFRASTRUCTURE_JOB_CONTRACTS = (EXPORT_JOB_CONTRACT, STAGE_JOB_CONTRACT)
