from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import UnitOfWork
from soma.infrastructure.jobs import (
    EXPORT_JOB_CONTRACT, EXPORT_JOB_TYPE, INFRASTRUCTURE_JOB_CONTRACTS, STAGE_JOB_TYPE,
    validate_export_checkpoint, validate_export_payload, validate_stage_checkpoint,
)


def test_export_job_payload_and_checkpoint_fail_closed():
    payload = dict(
        export_request_id=new_uuid4(), mode="registration_template",
        scope={"scope_kind": "all"}, destination_directory=r"D:\Exports",
        data_instance_id=new_uuid4(),
    )
    validate_export_payload(payload)
    with pytest.raises(ValidationError):
        validate_export_payload({**payload, "destination_directory": "relative"})
    with pytest.raises(ValidationError):
        validate_export_payload({**payload, "scope": {
            "scope_kind": "all", "site_id": new_uuid4(),
        }})
    checkpoint = dict(
        phase="queued", export_id=None, temp_filename=None,
        verified_sha256=None, verified_size_bytes=None, final_filename=None,
    )
    validate_export_checkpoint(checkpoint)
    with pytest.raises(ValidationError):
        validate_export_checkpoint({**checkpoint, "phase": "writing"})
    with pytest.raises(ValidationError):
        validate_export_checkpoint({**checkpoint, "phase": "published", "export_id": new_uuid4()})


def test_stage_checkpoint_requires_complete_source_and_bounded_cache():
    checkpoint = dict(
        phase="discovering", candidate_manifest_sha256=None, candidate_count=None,
        candidate_index=0, current_filename=None, current_file_size_bytes=None,
        current_file_mtime_ns=None, current_file_sha256=None,
        current_workbook_run_id=None, last_committed_network_element_row=None,
        last_committed_ip_row=None, published_run_ids=[],
    )
    validate_stage_checkpoint(checkpoint)
    with pytest.raises(ValidationError):
        validate_stage_checkpoint({**checkpoint, "phase": "parsing"})
    with pytest.raises(ValidationError):
        validate_stage_checkpoint({**checkpoint, "current_filename": "source.xlsx"})
    with pytest.raises(ValidationError):
        validate_stage_checkpoint({**checkpoint, "published_run_ids": [new_uuid4()] * 513})
    with pytest.raises(ValidationError):
        validate_stage_checkpoint({**checkpoint, "candidate_index": 1})


def test_export_job_retries_only_transient_failures_and_recovery_is_reconciliation():
    EXPORT_JOB_CONTRACT.validate_failure("WORKBOOK_IO_TRANSIENT", 1, 100, 105)
    with pytest.raises(ValidationError):
        EXPORT_JOB_CONTRACT.validate_failure("WORKBOOK_UNSAFE", 1, 100, 105)
    with pytest.raises(ValidationError):
        EXPORT_JOB_CONTRACT.validate_failure("WORKBOOK_IO_TRANSIENT", 4, 100, 220)
    recovery = EXPORT_JOB_CONTRACT.recover_stale(
        {"export_request_id": new_uuid4()}, None, 1, 100,
    )
    assert recovery.state == "retry_wait" and recovery.next_attempt_at_utc == 100


def test_coordinator_enqueues_and_coalesces_stage_job(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    registry = JobTypeRegistry(INFRASTRUCTURE_JOB_CONTRACTS)
    coordinator = DurableJobCoordinator(factory, registry)
    payload = dict(
        run_request_id=new_uuid4(), import_directory=r"D:\SOMA\Infrastructure Import",
        setting_revision=3, data_instance_id=new_uuid4(),
    )
    with UnitOfWork(factory) as uow:
        first = coordinator.enqueue_or_coalesce(uow, STAGE_JOB_TYPE, 1, payload, "3")
        second = coordinator.enqueue_or_coalesce(uow, STAGE_JOB_TYPE, 1, payload, "3")
        assert first == second
    export = dict(
        export_request_id=new_uuid4(), mode="registration_template",
        scope={"scope_kind": "all"}, destination_directory=r"D:\Exports",
        data_instance_id=payload["data_instance_id"],
    )
    with UnitOfWork(factory) as uow:
        job_id = coordinator.enqueue_or_coalesce(
            uow, EXPORT_JOB_TYPE, 1, export, export["export_request_id"],
        )
        assert job_id != first
