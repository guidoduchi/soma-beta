from __future__ import annotations

import uuid

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.jobs import (
    SOURCE_CHECK_JOB_CONTRACT,
    SOURCE_CHECK_JOB_TYPE,
    SR_REAPPEARANCE_JOB_CONTRACT,
    SR_REAPPEARANCE_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    derive_reappearance_dedupe_key,
    derive_source_check_dedupe_key,
    validate_reappearance_checkpoint,
    validate_reappearance_payload,
    validate_source_check_checkpoint,
    validate_source_check_payload,
)


def _uuid() -> str:
    return str(uuid.uuid4())


class Clock:
    def __init__(self, value: int = 100) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def _profiles(*, parser: str = "ADVANCED_SEARCH_PARSER_V1") -> dict[str, object]:
    return {
        "source_profile_id": "ADVANCED_SEARCH_SR_V1",
        "header_registry_id": "ADVANCED_SEARCH_HEADERS_V1",
        "vocabulary_registry_id": "ADVANCED_SEARCH_VOCABULARIES_V1",
        "parser_profile_id": parser,
    }


def _source_payload(
    *,
    family: str = "advanced_search_sr",
    invocation: str = "automatic",
    command_id: str | None = None,
    setting_revision: int = 1,
    selected_path: str = r"C:\Imports\candidate.xlsx",
    parser: str = "ADVANCED_SEARCH_PARSER_V1",
) -> dict[str, object]:
    if invocation == "automatic":
        setting_key = (
            "advanced_search_import_directory"
            if family == "advanced_search_sr"
            else "rfc_wfm_import_directory"
        )
        locator: dict[str, object] = {
            "kind": "setting_revision",
            "setting_key": setting_key,
            "setting_revision": setting_revision,
        }
    else:
        locator = {"kind": "manual_path", "selected_path": selected_path}
    return {
        "source_family": family,
        "invocation_kind": invocation,
        "profile_ids": _profiles(parser=parser),
        "source_locator": locator,
        "requested_by_command_id": command_id or _uuid(),
    }


def _candidate_identity() -> dict[str, object]:
    return {
        "filename": "Advanced Search(Service Request)20260914183000.xlsx",
        "stable_size_bytes": 12345,
        "stable_mtime_ns": 1_700_000_000_000_000_000,
        "source_chronology_kind": "embedded_filename_timestamp_utc",
        "source_chronology_value": 1_789_412_600,
        "locator_fingerprint": "a" * 64,
    }


def _reappearance_payload(
    *,
    import_run_id: str | None = None,
    command_id: str | None = None,
    revision: int = 1,
) -> dict[str, object]:
    return {
        "import_run_id": import_run_id or _uuid(),
        "source_family": "advanced_search_sr",
        "published_run_revision": revision,
        "requested_by_command_id": command_id or _uuid(),
    }


def _coordinator(initialized_database):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    clock = Clock()
    coordinator = DurableJobCoordinator(
        factory,
        JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
        clock=clock,
    )
    return factory, clock, coordinator


def test_registry_exposes_exact_packet_owned_job_contracts() -> None:
    registry = JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS)
    source = registry.require(SOURCE_CHECK_JOB_TYPE, 1)
    reappearance = registry.require(SR_REAPPEARANCE_JOB_TYPE, 1)

    assert source is SOURCE_CHECK_JOB_CONTRACT
    assert reappearance is SR_REAPPEARANCE_JOB_CONTRACT
    assert source.coalesce_states == frozenset(
        {"queued", "running", "waiting_review", "retry_wait"}
    )
    assert reappearance.coalesce_states == frozenset(
        {"queued", "running", "waiting_review", "retry_wait", "completed"}
    )


def test_source_check_payload_closes_locator_variants_and_family_mapping() -> None:
    advanced = _source_payload()
    validate_source_check_payload(advanced)

    rfc = _source_payload(family="rfc_enhanced")
    validate_source_check_payload(rfc)
    assert rfc["source_locator"] == {
        "kind": "setting_revision",
        "setting_key": "rfc_wfm_import_directory",
        "setting_revision": 1,
    }

    manual = _source_payload(invocation="manual")
    validate_source_check_payload(manual)

    wrong_inbox = _source_payload()
    wrong_inbox["source_locator"] = {
        "kind": "setting_revision",
        "setting_key": "rfc_wfm_import_directory",
        "setting_revision": 1,
    }
    with pytest.raises(ValidationError):
        validate_source_check_payload(wrong_inbox)

    wrong_kind = _source_payload(invocation="manual")
    wrong_kind["source_locator"] = {
        "kind": "setting_revision",
        "setting_key": "advanced_search_import_directory",
        "setting_revision": 1,
    }
    with pytest.raises(ValidationError):
        validate_source_check_payload(wrong_kind)

    extra = _source_payload()
    extra["unexpected"] = True
    with pytest.raises(ValidationError):
        validate_source_check_payload(extra)


@pytest.mark.parametrize(
    "path",
    [
        r"relative\candidate.xlsx",
        r"\\server\share\candidate.xlsx",
        r"\\?\C:\Imports\candidate.xlsx",
        r"C:\Imports\..\candidate.xlsx",
        r"C:\CON.txt",
        "C:\\Imports\\bad\x00name.xlsx",
        r"C:\Imports\bad?.xlsx",
    ],
)
def test_source_check_manual_locator_rejects_unsafe_windows_path(path: str) -> None:
    with pytest.raises(ValidationError):
        validate_source_check_payload(
            _source_payload(invocation="manual", selected_path=path)
        )


def test_source_check_checkpoint_phase_and_candidate_contract() -> None:
    discovering = {
        "phase": "discovering",
        "import_run_id": None,
        "run_revision": None,
        "parser_profile_id": "ADVANCED_SEARCH_PARSER_V1",
        "candidate_identity": None,
        "last_committed_batch": None,
    }
    validate_source_check_checkpoint(discovering)

    validating = {
        "phase": "validating",
        "import_run_id": _uuid(),
        "run_revision": 1,
        "parser_profile_id": "ADVANCED_SEARCH_PARSER_V1",
        "candidate_identity": _candidate_identity(),
        "last_committed_batch": {"sheet": 1, "row": 200},
    }
    validate_source_check_checkpoint(validating)

    bad_discovering = dict(discovering)
    bad_discovering["candidate_identity"] = _candidate_identity()
    with pytest.raises(ValidationError):
        validate_source_check_checkpoint(bad_discovering)

    missing_candidate = dict(validating)
    missing_candidate["candidate_identity"] = None
    with pytest.raises(ValidationError):
        validate_source_check_checkpoint(missing_candidate)

    malformed_hash = dict(validating)
    malformed_hash["candidate_identity"] = {
        **_candidate_identity(),
        "locator_fingerprint": "A" * 64,
    }
    with pytest.raises(ValidationError):
        validate_source_check_checkpoint(malformed_hash)

    overflow = dict(validating)
    overflow["candidate_identity"] = {
        **_candidate_identity(),
        "stable_mtime_ns": 1 << 63,
    }
    with pytest.raises(ValidationError):
        validate_source_check_checkpoint(overflow)

    bad_batch = dict(validating)
    bad_batch["last_committed_batch"] = [1, 2, 3]
    with pytest.raises(ValidationError):
        validate_source_check_checkpoint(bad_batch)


def test_source_check_dedupe_uses_only_family_and_semantic_locator() -> None:
    first = _source_payload(command_id=_uuid())
    second = _source_payload(command_id=_uuid(), parser="OTHER_REGISTERED_PARSER_V1")
    assert derive_source_check_dedupe_key(first) == derive_source_check_dedupe_key(second)

    newer_setting = _source_payload(setting_revision=2)
    assert derive_source_check_dedupe_key(first) != derive_source_check_dedupe_key(newer_setting)

    manual_a = _source_payload(invocation="manual", selected_path=r"C:\Imports\a.xlsx")
    manual_b = _source_payload(invocation="manual", selected_path=r"C:\Imports\b.xlsx")
    assert derive_source_check_dedupe_key(manual_a) != derive_source_check_dedupe_key(manual_b)


def test_reappearance_payload_checkpoint_and_dedupe_are_closed() -> None:
    import_run_id = _uuid()
    payload = _reappearance_payload(import_run_id=import_run_id)
    validate_reappearance_payload(payload)
    assert derive_reappearance_dedupe_key(payload) == import_run_id

    initial = {
        "import_run_id": import_run_id,
        "last_canonical_sr_no": None,
        "last_source_observation_id": None,
        "processed_exact_count": 0,
    }
    validate_reappearance_checkpoint(initial)

    resumed = {
        "import_run_id": import_run_id,
        "last_canonical_sr_no": "12345678",
        "last_source_observation_id": _uuid(),
        "processed_exact_count": 500,
    }
    validate_reappearance_checkpoint(resumed)

    bad_family = {**payload, "source_family": "rfc_enhanced"}
    with pytest.raises(ValidationError):
        validate_reappearance_payload(bad_family)

    mixed_cursor = {**initial, "last_canonical_sr_no": "12345678"}
    with pytest.raises(ValidationError):
        validate_reappearance_checkpoint(mixed_cursor)

    non_ascii_digits = {
        **resumed,
        "last_canonical_sr_no": "１２３４５６７８",
    }
    with pytest.raises(ValidationError):
        validate_reappearance_checkpoint(non_ascii_digits)


def test_retry_and_crash_recovery_policies_are_exact() -> None:
    SOURCE_CHECK_JOB_CONTRACT.validate_failure("IMPORT_FILE_UNSTABLE", 1, 100, 105)
    SOURCE_CHECK_JOB_CONTRACT.validate_failure("PERSISTENCE_BUSY", 2, 100, 130)
    SOURCE_CHECK_JOB_CONTRACT.validate_failure("IMPORT_FILE_UNSTABLE", 3, 100, None)
    SOURCE_CHECK_JOB_CONTRACT.validate_failure("XLSX_UNSAFE_CONTAINER", 1, 100, None)

    with pytest.raises(ValidationError):
        SOURCE_CHECK_JOB_CONTRACT.validate_failure("IMPORT_FILE_UNSTABLE", 1, 100, 106)
    with pytest.raises(ValidationError):
        SOURCE_CHECK_JOB_CONTRACT.validate_failure("XLSX_UNSAFE_CONTAINER", 1, 100, 105)
    with pytest.raises(ValidationError):
        SOURCE_CHECK_JOB_CONTRACT.validate_failure("PERSISTENCE_BUSY", 3, 100, 130)

    SR_REAPPEARANCE_JOB_CONTRACT.validate_failure("IMPORT_PROPOSAL_STALE", 1, 200, 205)
    SR_REAPPEARANCE_JOB_CONTRACT.validate_failure("JOB_INTERRUPTED", 2, 200, 230)
    SR_REAPPEARANCE_JOB_CONTRACT.validate_failure("IMPORT_PROPOSAL_STALE", 3, 200, None)

    first = SOURCE_CHECK_JOB_CONTRACT.recover_stale({}, None, 1, 300)
    second = SOURCE_CHECK_JOB_CONTRACT.recover_stale({}, None, 2, 300)
    third = SOURCE_CHECK_JOB_CONTRACT.recover_stale({}, None, 3, 300)
    assert (first.state, first.next_attempt_at_utc, first.error_code) == (
        "retry_wait",
        305,
        "JOB_INTERRUPTED",
    )
    assert (second.state, second.next_attempt_at_utc, second.error_code) == (
        "retry_wait",
        330,
        "JOB_INTERRUPTED",
    )
    assert (third.state, third.next_attempt_at_utc, third.error_code) == (
        "failed",
        None,
        "JOB_INTERRUPTED",
    )


@pytest.mark.parametrize(
    "contract",
    [SOURCE_CHECK_JOB_CONTRACT, SR_REAPPEARANCE_JOB_CONTRACT],
)
def test_packet_cancellation_is_rejected_for_both_v1_jobs(contract: object) -> None:
    callback = contract.validate_cancellation  # type: ignore[attr-defined]
    for state in ("queued", "running", "waiting_review", "retry_wait"):
        with pytest.raises(ValidationError):
            callback({"command": "anything"}, state)


def test_source_check_completed_job_does_not_coalesce(initialized_database) -> None:
    factory, clock, coordinator = _coordinator(initialized_database)
    payload = _source_payload()
    key = derive_source_check_dedupe_key(payload)
    with UnitOfWork(factory) as uow:
        first = coordinator.enqueue_or_coalesce(
            uow, SOURCE_CHECK_JOB_TYPE, 1, payload, key
        )
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None and claim.job_id == first
    clock.value = 102
    coordinator.complete(claim)

    duplicate = {**payload, "requested_by_command_id": _uuid()}
    duplicate_key = derive_source_check_dedupe_key(duplicate)
    with UnitOfWork(factory) as uow:
        second = coordinator.enqueue_or_coalesce(
            uow, SOURCE_CHECK_JOB_TYPE, 1, duplicate, duplicate_key
        )
    assert second != first


def test_reappearance_completed_job_remains_logically_coalesced(initialized_database) -> None:
    factory, clock, coordinator = _coordinator(initialized_database)
    import_run_id = _uuid()
    payload = _reappearance_payload(import_run_id=import_run_id)
    key = derive_reappearance_dedupe_key(payload)
    with UnitOfWork(factory) as uow:
        first = coordinator.enqueue_or_coalesce(
            uow, SR_REAPPEARANCE_JOB_TYPE, 1, payload, key
        )
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None and claim.job_id == first
    clock.value = 102
    coordinator.complete(claim)

    duplicate = _reappearance_payload(import_run_id=import_run_id)
    duplicate_key = derive_reappearance_dedupe_key(duplicate)
    with UnitOfWork(factory) as uow:
        second = coordinator.enqueue_or_coalesce(
            uow, SR_REAPPEARANCE_JOB_TYPE, 1, duplicate, duplicate_key
        )
    assert second == first
