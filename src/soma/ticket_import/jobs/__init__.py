from __future__ import annotations

import re
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.jobs import JobTypeContract, StaleRecoveryDisposition
from soma.foundation.strict_json import canonical_json_bytes_bounded

SOURCE_CHECK_JOB_TYPE = "ticket_import.source_check"
SR_REAPPEARANCE_JOB_TYPE = "ticket_import.sr_reappearance_reconcile"

_SOURCE_FAMILIES = frozenset(
    {"advanced_search_sr", "rfc_enhanced", "wfm_service_provider"}
)
_PROFILE_KEYS = frozenset(
    {
        "source_profile_id",
        "header_registry_id",
        "vocabulary_registry_id",
        "parser_profile_id",
    }
)
_SOURCE_CHECK_PAYLOAD_KEYS = frozenset(
    {
        "source_family",
        "invocation_kind",
        "profile_ids",
        "source_locator",
        "requested_by_command_id",
    }
)
_SOURCE_CHECK_CHECKPOINT_KEYS = frozenset(
    {
        "phase",
        "import_run_id",
        "run_revision",
        "parser_profile_id",
        "candidate_identity",
        "last_committed_batch",
    }
)
_CANDIDATE_IDENTITY_KEYS = frozenset(
    {
        "filename",
        "stable_size_bytes",
        "stable_mtime_ns",
        "source_chronology_kind",
        "source_chronology_value",
        "locator_fingerprint",
    }
)
_REAPPEARANCE_PAYLOAD_KEYS = frozenset(
    {
        "import_run_id",
        "source_family",
        "published_run_revision",
        "requested_by_command_id",
    }
)
_REAPPEARANCE_CHECKPOINT_KEYS = frozenset(
    {
        "import_run_id",
        "last_canonical_sr_no",
        "last_source_observation_id",
        "processed_exact_count",
    }
)
_ACTIVE_COALESCE_STATES = frozenset(
    {"queued", "running", "waiting_review", "retry_wait"}
)
_SOURCE_CHECK_RETRYABLE = frozenset(
    {
        "JOB_INTERRUPTED",
        "IMPORT_SOURCE_UNAVAILABLE",
        "IMPORT_FILE_UNSTABLE",
        "IMPORT_PARSER_RESTARTABLE",
        "PERSISTENCE_BUSY",
    }
)
_REAPPEARANCE_RETRYABLE = frozenset(
    {"JOB_INTERRUPTED", "PERSISTENCE_BUSY", "IMPORT_PROPOSAL_STALE"}
)
_RETRY_DELAY_BY_ATTEMPT = {1: 5, 2: 30}
_PHASES = frozenset(
    {"discovering", "validating", "staging", "publishing", "noop_checkpoint"}
)
_CHRONOLOGY_KINDS = frozenset(
    {"filesystem_mtime_ns", "embedded_filename_timestamp_utc"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_LOCAL_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/].+")
_SR_NO = re.compile(r"^[0-9]{8}$", re.ASCII)
_MAX_INT64 = (1 << 63) - 1
_MAX_PATH_BYTES = 4096
_MAX_FILENAME_BYTES = 4096
_MAX_DEDUPE_JSON_BYTES = 65536
_WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)


def _require_exact_dict(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValidationError(f"{label} must contain exactly the registered fields")
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{label} must be a nonempty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValidationError(f"{label} must be valid UTF-8") from exc
    return value


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValidationError(f"{label} must be int>=1")
    return value


def _require_nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{label} must be int>=0")
    return value


def _require_nonnegative_int64(value: Any, label: str) -> int:
    resolved = _require_nonnegative_int(value, label)
    if resolved > _MAX_INT64:
        raise ValidationError(f"{label} exceeds signed int64 range")
    return resolved


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _require_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be canonical UUIDv4 text")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{label} must be canonical UUIDv4 text") from exc


def _require_windows_local_file_path(value: Any) -> str:
    path = _require_nonempty_string(value, "source_locator.selected_path")
    if len(path.encode("utf-8")) > _MAX_PATH_BYTES:
        raise ValidationError("source_locator.selected_path exceeds UTF-8 bound")
    if "\x00" in path or path.startswith(("\\\\", "//")):
        raise ValidationError("source_locator.selected_path is not a local Windows path")
    if _WINDOWS_LOCAL_ABSOLUTE.fullmatch(path) is None:
        raise ValidationError("source_locator.selected_path must be drive-absolute")
    tail = path[3:].replace("/", "\\")
    parts = tail.split("\\")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise ValidationError("source_locator.selected_path contains unsafe path segments")
    for part in parts:
        if part.endswith((" ", ".")):
            raise ValidationError("source_locator.selected_path contains unsafe path segments")
        if any(ord(ch) < 32 or ch in _WINDOWS_FORBIDDEN for ch in part):
            raise ValidationError("source_locator.selected_path contains invalid Windows characters")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise ValidationError("source_locator.selected_path targets a reserved Windows device name")
    return path


def _validate_profiles(value: Any) -> None:
    profiles = _require_exact_dict(value, _PROFILE_KEYS, "profile_ids")
    for key in sorted(_PROFILE_KEYS):
        _require_nonempty_string(profiles[key], f"profile_ids.{key}")


def _validate_source_locator(
    source_family: str,
    invocation_kind: str,
    value: Any,
) -> None:
    if not isinstance(value, dict):
        raise ValidationError("source_locator must be an object")
    kind = value.get("kind")
    if invocation_kind == "automatic":
        locator = _require_exact_dict(
            value,
            frozenset({"kind", "setting_key", "setting_revision"}),
            "automatic source_locator",
        )
        if kind != "setting_revision":
            raise ValidationError("automatic source_locator kind must be setting_revision")
        expected_key = (
            "advanced_search_import_directory"
            if source_family == "advanced_search_sr"
            else "rfc_wfm_import_directory"
        )
        if locator["setting_key"] != expected_key:
            raise ValidationError("automatic source_locator setting_key disagrees with source_family")
        _require_positive_int(locator["setting_revision"], "source_locator.setting_revision")
        return
    if invocation_kind == "manual":
        locator = _require_exact_dict(
            value,
            frozenset({"kind", "selected_path"}),
            "manual source_locator",
        )
        if kind != "manual_path":
            raise ValidationError("manual source_locator kind must be manual_path")
        _require_windows_local_file_path(locator["selected_path"])
        return
    raise ValidationError("source_check invocation_kind is invalid")


def validate_source_check_payload(value: Any) -> None:
    payload = _require_exact_dict(
        value, _SOURCE_CHECK_PAYLOAD_KEYS, "source_check payload"
    )
    source_family = payload["source_family"]
    if source_family not in _SOURCE_FAMILIES:
        raise ValidationError("source_check source_family is invalid")
    invocation_kind = payload["invocation_kind"]
    if invocation_kind not in {"automatic", "manual"}:
        raise ValidationError("source_check invocation_kind is invalid")
    _validate_profiles(payload["profile_ids"])
    _validate_source_locator(source_family, invocation_kind, payload["source_locator"])
    _require_uuid(payload["requested_by_command_id"], "requested_by_command_id")


def _validate_candidate_identity(value: Any) -> None:
    candidate = _require_exact_dict(
        value, _CANDIDATE_IDENTITY_KEYS, "candidate_identity"
    )
    filename = _require_nonempty_string(candidate["filename"], "candidate_identity.filename")
    if len(filename.encode("utf-8")) > _MAX_FILENAME_BYTES or any(
        ch in filename for ch in ("/", "\\", "\x00")
    ):
        raise ValidationError("candidate_identity.filename is invalid")
    _require_nonnegative_int64(candidate["stable_size_bytes"], "candidate_identity.stable_size_bytes")
    _require_nonnegative_int64(candidate["stable_mtime_ns"], "candidate_identity.stable_mtime_ns")
    if candidate["source_chronology_kind"] not in _CHRONOLOGY_KINDS:
        raise ValidationError("candidate_identity.source_chronology_kind is invalid")
    _require_nonnegative_int64(
        candidate["source_chronology_value"],
        "candidate_identity.source_chronology_value",
    )
    _require_sha256(candidate["locator_fingerprint"], "candidate_identity.locator_fingerprint")


def validate_source_check_checkpoint(value: Any) -> None:
    checkpoint = _require_exact_dict(
        value, _SOURCE_CHECK_CHECKPOINT_KEYS, "source_check checkpoint"
    )
    phase = checkpoint["phase"]
    if phase not in _PHASES:
        raise ValidationError("source_check checkpoint phase is invalid")
    _require_nonempty_string(checkpoint["parser_profile_id"], "checkpoint.parser_profile_id")
    batch = checkpoint["last_committed_batch"]
    if batch is not None and not isinstance(batch, dict):
        raise ValidationError("checkpoint.last_committed_batch must be an object or null")
    if phase == "discovering":
        if any(
            checkpoint[key] is not None
            for key in (
                "import_run_id",
                "run_revision",
                "candidate_identity",
                "last_committed_batch",
            )
        ):
            raise ValidationError("discovering checkpoint cannot carry run/candidate/batch state")
        return
    _require_uuid(checkpoint["import_run_id"], "checkpoint.import_run_id")
    _require_positive_int(checkpoint["run_revision"], "checkpoint.run_revision")
    if checkpoint["candidate_identity"] is None:
        raise ValidationError("post-discovery checkpoint requires candidate_identity")
    _validate_candidate_identity(checkpoint["candidate_identity"])


def derive_source_check_dedupe_key(payload: Any) -> str:
    validate_source_check_payload(payload)
    encoded = canonical_json_bytes_bounded(
        {
            "source_family": payload["source_family"],
            "source_locator": payload["source_locator"],
        },
        max_bytes=_MAX_DEDUPE_JSON_BYTES,
        max_depth=4,
        max_collection_items=16,
    )
    return encoded.decode("utf-8")


def validate_reappearance_payload(value: Any) -> None:
    payload = _require_exact_dict(
        value, _REAPPEARANCE_PAYLOAD_KEYS, "sr_reappearance payload"
    )
    _require_uuid(payload["import_run_id"], "import_run_id")
    if payload["source_family"] != "advanced_search_sr":
        raise ValidationError("sr_reappearance source_family must be advanced_search_sr")
    _require_positive_int(payload["published_run_revision"], "published_run_revision")
    _require_uuid(payload["requested_by_command_id"], "requested_by_command_id")


def validate_reappearance_checkpoint(value: Any) -> None:
    checkpoint = _require_exact_dict(
        value, _REAPPEARANCE_CHECKPOINT_KEYS, "sr_reappearance checkpoint"
    )
    _require_uuid(checkpoint["import_run_id"], "checkpoint.import_run_id")
    sr_no = checkpoint["last_canonical_sr_no"]
    observation_id = checkpoint["last_source_observation_id"]
    if (sr_no is None) != (observation_id is None):
        raise ValidationError("sr_reappearance checkpoint cursor must be both null or both present")
    if sr_no is not None:
        if not isinstance(sr_no, str) or _SR_NO.fullmatch(sr_no) is None:
            raise ValidationError("checkpoint.last_canonical_sr_no must be eight ASCII digits")
        _require_uuid(observation_id, "checkpoint.last_source_observation_id")
    _require_nonnegative_int(checkpoint["processed_exact_count"], "processed_exact_count")


def derive_reappearance_dedupe_key(payload: Any) -> str:
    validate_reappearance_payload(payload)
    return str(payload["import_run_id"])


def _validate_failure_policy(
    retryable: frozenset[str],
    error_code: str,
    attempt_ordinal: int,
    now: int,
    retry_at: int | None,
) -> None:
    if type(attempt_ordinal) is not int or attempt_ordinal < 1:
        raise ValidationError("durable-job attempt_ordinal must be int>=1")
    if type(now) is not int or now < 0:
        raise ValidationError("durable-job failure time must be nonnegative whole-second UTC")
    delay = _RETRY_DELAY_BY_ATTEMPT.get(attempt_ordinal)
    if error_code in retryable and delay is not None:
        if retry_at != now + delay:
            raise ValidationError("retryable Ticket Import job failure uses wrong retry_at")
        return
    if retry_at is not None:
        raise ValidationError("terminal Ticket Import job failure requires retry_at=null")


def _reject_packet_cancellation(_command_context: Any, _state: str) -> None:
    raise ValidationError("Ticket Import durable job is not packet-cancellable in Beta 1.0")


def _recover_stale(
    _payload: Any,
    _checkpoint: Any | None,
    attempt_ordinal: int,
    now: int,
) -> StaleRecoveryDisposition:
    delay = _RETRY_DELAY_BY_ATTEMPT.get(attempt_ordinal)
    if delay is None:
        return StaleRecoveryDisposition(
            state="failed",
            next_attempt_at_utc=None,
            error_code="JOB_INTERRUPTED",
        )
    return StaleRecoveryDisposition(
        state="retry_wait",
        next_attempt_at_utc=now + delay,
        error_code="JOB_INTERRUPTED",
    )


def _validate_source_check_failure(
    error_code: str,
    attempt_ordinal: int,
    now: int,
    retry_at: int | None,
) -> None:
    _validate_failure_policy(
        _SOURCE_CHECK_RETRYABLE,
        error_code,
        attempt_ordinal,
        now,
        retry_at,
    )


def _validate_reappearance_failure(
    error_code: str,
    attempt_ordinal: int,
    now: int,
    retry_at: int | None,
) -> None:
    _validate_failure_policy(
        _REAPPEARANCE_RETRYABLE,
        error_code,
        attempt_ordinal,
        now,
        retry_at,
    )


SOURCE_CHECK_JOB_CONTRACT = JobTypeContract(
    job_type=SOURCE_CHECK_JOB_TYPE,
    contract_version=1,
    validate_payload=validate_source_check_payload,
    validate_checkpoint=validate_source_check_checkpoint,
    derive_dedupe_key=derive_source_check_dedupe_key,
    coalesce_states=_ACTIVE_COALESCE_STATES,
    validate_failure=_validate_source_check_failure,
    validate_cancellation=_reject_packet_cancellation,
    recover_stale=_recover_stale,
)

SR_REAPPEARANCE_JOB_CONTRACT = JobTypeContract(
    job_type=SR_REAPPEARANCE_JOB_TYPE,
    contract_version=1,
    validate_payload=validate_reappearance_payload,
    validate_checkpoint=validate_reappearance_checkpoint,
    derive_dedupe_key=derive_reappearance_dedupe_key,
    coalesce_states=frozenset({*_ACTIVE_COALESCE_STATES, "completed"}),
    validate_failure=_validate_reappearance_failure,
    validate_cancellation=_reject_packet_cancellation,
    recover_stale=_recover_stale,
)

TICKET_IMPORT_JOB_CONTRACTS = (
    SOURCE_CHECK_JOB_CONTRACT,
    SR_REAPPEARANCE_JOB_CONTRACT,
)

__all__ = [
    "SOURCE_CHECK_JOB_TYPE",
    "SR_REAPPEARANCE_JOB_TYPE",
    "SOURCE_CHECK_JOB_CONTRACT",
    "SR_REAPPEARANCE_JOB_CONTRACT",
    "TICKET_IMPORT_JOB_CONTRACTS",
    "validate_source_check_payload",
    "validate_source_check_checkpoint",
    "derive_source_check_dedupe_key",
    "validate_reappearance_payload",
    "validate_reappearance_checkpoint",
    "derive_reappearance_dedupe_key",
]
