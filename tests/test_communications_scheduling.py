import sqlite3

from soma.communications.composition import build_communications_runtime
from soma.communications.services.source_config import SourceConfigurationService
from soma.communications.queries.previews import CommunicationPreviews
from soma.foundation.identifiers import new_uuid4
from test_communications_source_config import configure, request
from test_communications_processing_worker import Adapter
from test_communications_processing_batches import scalar
from test_communications_identity_providers import providers
from test_objectives_tasks_objectives import _create_single_task_objective


def setup(database):
    path, factory = database
    _create_single_task_objective(factory, name="Scheduled Objective", start_utc=100, end_utc=200)
    clock = [2_000_000_000]
    adapter = Adapter(factory, [])
    runtime = build_communications_runtime(factory, adapter, clock=lambda: clock[0])
    source, _ = configure(SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter), request())
    return path, runtime, runtime.schedule(), clock, source['target_id'], adapter


def test_disabled_fetch_still_schedules_housekeeping_and_rechecks_disabled_in_writer(communication_database):
    path, runtime, schedule, clock, source, adapter = setup(communication_database)
    settings = runtime.providers['settings']
    settings.set_processing_schedule(settings.schedule_state() | {'command_id': new_uuid4(), 'enabled': False})
    result = schedule.tick(clock[0])
    assert result['ordinary_requests'] == 0
    assert scalar(path, "SELECT job_kind FROM communication_job_scopes") == 'ORPHAN_HOUSEKEEPING'
    assert schedule.tick(clock[0])['housekeeping_job_id'] == result['housekeeping_job_id']
    assert runtime.providers['processing'].request_scheduled_processing({'command_id': new_uuid4(),
        'source_scope_id': source, 'source_scope_revision': 1})['job_id'] is None
    assert adapter.opened == 0


def test_current_interval_changes_and_manual_trigger_coalesce_without_implicit_history(communication_database):
    path, runtime, schedule, clock, source, _ = setup(communication_database)
    first = schedule.tick(clock[0])
    assert first['ordinary_requests'] == 1
    job = scalar(path, "SELECT job_id FROM communication_job_scopes WHERE job_kind='ORDINARY'")
    manual = runtime.providers['processing'].start_processing({'command_id': new_uuid4(), 'source_scope_id': source, 'source_scope_revision': 1})
    assert manual['job_id'] == job and manual['coalesced']
    clock[0] += 60
    assert schedule.tick(clock[0])['ordinary_requests'] == 0
    settings = runtime.providers['settings']
    settings.set_processing_schedule(settings.schedule_state() | {'command_id': new_uuid4(), 'interval_minutes': 1})
    assert schedule.tick(clock[0])['ordinary_requests'] == 1
    assert scalar(path, "SELECT count(*) FROM communication_job_scopes WHERE job_kind='ORDINARY'") == 1
    assert scalar(path, "SELECT count(*) FROM communication_job_scopes WHERE job_kind IN ('DEEP_SCAN','TARGETED_BACKFILL')") == 0
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_source_scopes SET processing_enabled=0")
    clock[0] += 60
    assert schedule.tick(clock[0])['ordinary_requests'] == 0


def test_claim_policy_serializes_source_readers_while_housekeeping_can_run(communication_database):
    path, runtime, schedule, clock, source, _ = setup(communication_database)
    schedule.tick(clock[0])
    claim = runtime.claim_next(new_uuid4(), clock[0])
    assert claim is not None
    other = runtime.claim_next(new_uuid4(), clock[0])
    assert other is not None
    assert {claim.job_type, other.job_type} == {'communications.processing.ordinary', 'communications.orphan_housekeeping'}
    assert runtime.claim_next(new_uuid4(), clock[0]) is None


def test_different_scan_kinds_for_one_source_queue_until_running_reader_finishes(communication_database):
    from test_communications_historical_processing import setup_history
    path, factory, owners, historical, _, clock, adapter, worker, _ = setup_history(communication_database, [])
    runtime = build_communications_runtime(factory, adapter, identity_providers=owners, clock=lambda: clock[0])
    source = scalar(path, "SELECT source_scope_id FROM communication_source_scopes")
    ordinary = runtime.providers['processing'].start_processing({'command_id': new_uuid4(), 'source_scope_id': source,
        'source_scope_revision': 1})
    assert runtime.claim_next(new_uuid4(), clock[0]) is None
    housekeeping = runtime.schedule().enqueue_housekeeping(clock[0])
    assert runtime.claim_next(new_uuid4(), clock[0]).job_id == housekeeping
    worker.run(historical)
    assert runtime.claim_next(new_uuid4(), clock[0]).job_id == ordinary['job_id']
