from __future__ import annotations

import pytest

from soma.communications.contracts.common import Chronology
from soma.communications.contracts.jobs import CommunicationJobCheckpoint, CommunicationJobCounters, CommunicationJobScope
from soma.communications.contracts.source import ProviderCheckpoint
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import UnitOfWork
from soma.communications.jobs.communications import COMMUNICATION_JOB_CONTRACTS, JOB_TYPES, dedupe_key, retry_at


def test_global_housekeeping_requires_no_mail_source_or_provider_position():
    scope = CommunicationJobScope(None, (), "ORPHAN_HOUSEKEEPING", None, None, (), None)
    checkpoint = CommunicationJobCheckpoint(scope, None, CommunicationJobCounters(inspected=1), ())
    assert CommunicationJobCheckpoint.from_value(checkpoint.to_response()) == checkpoint
    value = scope.to_response()
    for name, bad in (("source_scope_id", new_uuid4()), ("config_revision", 1), ("folder_keys", ["inbox"]),
                      ("target_identity_ids", ["MW-00000001"]), ("lower_bound", Chronology(True, 1, "SENT_TIME").to_response())):
        with pytest.raises(ValidationError):
            CommunicationJobScope.from_value({**value, name: bad})
    with pytest.raises(ValidationError):
        CommunicationJobCheckpoint(scope, ProviderCheckpoint("POSITION", "token", None), CommunicationJobCounters(), ())


def test_job_contract_preserves_checkpoint_milliseconds_and_exact_closed_types():
    scope = CommunicationJobScope(new_uuid4(), ("inbox",), "ORDINARY", Chronology(True, 1, "SENT_TIME"), None, (), 1)
    provider = ProviderCheckpoint("COMPOSITE", "opaque_token", 1234567890123)
    checkpoint = CommunicationJobCheckpoint(scope, provider, CommunicationJobCounters(inspected=2, estimated_total=4), ())
    assert CommunicationJobCheckpoint.from_value(checkpoint.to_response()) == checkpoint
    assert checkpoint.counters.percentage == 50
    assert CommunicationJobCounters(inspected=50).percentage is None
    assert CommunicationJobCounters(inspected=50, estimated_total=0).percentage is None
    for bad in (True, -1, 1.0):
        with pytest.raises(ValidationError):
            CommunicationJobCounters(inspected=bad)
    with pytest.raises(ValidationError):
        CommunicationJobScope.from_value({**scope.to_response(), "config_revision": True})
    with pytest.raises(ValidationError):
        CommunicationJobCheckpoint.from_value({**checkpoint.to_response(), "subject": "Forbidden"})
    with pytest.raises(ValidationError):
        CommunicationJobScope.from_value({**scope.to_response(), "source_scope_id": None})


def test_job_contract_rejects_oversize_scope_without_truncation_or_global_limit_change():
    value = CommunicationJobScope(new_uuid4(), ("inbox",), "TARGETED_BACKFILL", None, None, (), 1).to_response()
    with pytest.raises(ValidationError):
        CommunicationJobScope.from_value({**value, "target_identity_ids": ["x" * 65_536]})
    with pytest.raises(ValidationError):
        CommunicationJobScope.from_value({**value, "target_identity_ids": [str(i) for i in range(513)]})


def test_lld09_a054_a057_global_job_coalesces_and_recovery_preserves_committed_work(communication_database):
    _, factory = communication_database
    coordinator = DurableJobCoordinator(factory, JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS), clock=lambda: 100)
    scope = CommunicationJobScope(None, (), "ORPHAN_HOUSEKEEPING", None, None, (), None)
    value = scope.to_response()
    with UnitOfWork(factory) as uow:
        first = coordinator.enqueue_or_coalesce(uow, JOB_TYPES[scope.job_kind], 1, value, dedupe_key(value))
        second = coordinator.enqueue_or_coalesce(uow, JOB_TYPES[scope.job_kind], 1, value, dedupe_key(value))
    assert first == second
    claim = coordinator.claim_next(new_uuid4(), 100)
    assert claim.job_id == first
    committed = CommunicationJobCheckpoint(scope, None, CommunicationJobCounters(inspected=2), ())
    coordinator.checkpoint(claim, committed.to_response())
    coordinator.recover_stale_claims(new_uuid4(), 100)
    resumed = coordinator.claim_next(new_uuid4(), 100)
    assert resumed.job_id == first and resumed.attempt_ordinal == 2
    import json
    assert CommunicationJobCheckpoint.from_value(json.loads(resumed.checkpoint_json)) == committed
    coordinator.complete(resumed)
    with UnitOfWork(factory) as uow:
        later = coordinator.enqueue_or_coalesce(uow, JOB_TYPES[scope.job_kind], 1, value, dedupe_key(value))
    assert later != first


def test_retry_rules_enforce_exact_backoff_and_total_attempt_limit():
    assert retry_at("ORPHAN_HOUSEKEEPING", error_code="PERSISTENCE_BUSY", attempt_ordinal=1, now=100) == 160
    assert retry_at("ORPHAN_HOUSEKEEPING", error_code="PERSISTENCE_BUSY", attempt_ordinal=2, now=100) == 400
    assert retry_at("ORPHAN_HOUSEKEEPING", error_code="PERSISTENCE_BUSY", attempt_ordinal=3, now=100) is None
    assert retry_at("ORPHAN_HOUSEKEEPING", error_code="IO_TRANSIENT", attempt_ordinal=1, now=100) is None
    assert retry_at("IDENTITY_RECONCILIATION", error_code="SOURCE_LOCKED", attempt_ordinal=1, now=100) == 130
    assert retry_at("IDENTITY_RECONCILIATION", error_code="SOURCE_LOCKED", attempt_ordinal=2, now=100) is None
    contract = JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS).require(JOB_TYPES["ORPHAN_HOUSEKEEPING"], 1)
    for code, ordinal, when in (("IO_TRANSIENT", 1, 160), ("PERSISTENCE_BUSY", 3, 1000), ("PERSISTENCE_BUSY", 1, 161), ("PERSISTENCE_BUSY", 1, True)):
        with pytest.raises(ValidationError):
            contract.validate_failure(code, ordinal, 100, when)
