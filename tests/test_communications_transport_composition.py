import sqlite3

import pytest

from soma.communications.api.routes_communications import COMMUNICATION_ROUTE_SPECS, CommunicationRouteAdapter
from soma.communications.composition import build_communications_runtime
from soma.communications.queries.previews import CommunicationPreviews
from soma.communications.services.source_config import SourceConfigurationService
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4
from test_communications_identity_providers import providers
from test_objectives_tasks_objectives import _create_single_task_objective
from test_communications_source_config import configure, request
from test_communications_processing_worker import Adapter
from test_communications_identity import message
from test_communications_processing_batches import scalar


def test_complete_transport_registry_enforces_path_identity_size_and_command_before_dispatch():
    seen = []
    adapter = CommunicationRouteAdapter({row["handler"]: lambda body: seen.append(body) or {"ok": True} for row in COMMUNICATION_ROUTE_SPECS})
    identity = new_uuid4()
    path = f"/api/v1/communications/source-scopes/{identity}/process"
    for body in ({"command_id": new_uuid4(), "source_scope_id": new_uuid4()},
                 {"command_id": "invalid"}, {"command_id": new_uuid4(), "huge": "x" * 4096}):
        with pytest.raises(ValidationError):
            adapter.dispatch("POST", path, body)
    assert seen == []
    result = adapter.dispatch("POST", path, {"command_id": new_uuid4(), "source_scope_revision": 1})
    assert result.status == 202 and seen[0]["source_scope_id"] == identity
    assert adapter.dispatch("GET", "/other") is None
    with pytest.raises(IntegrityFailure):
        CommunicationRouteAdapter({})


def test_routes_allow_sensitive_content_only_in_decoded_body_and_require_authenticated_context(communication_database):
    from soma.communications.api.routes_communications import resolve_route
    for suffix in ('?body=PRIVATE_BODY', '?source_location=private.pst', '?recipients=private@example.org',
                   '?destination_path=private.msg'):
        with pytest.raises(ValidationError):
            resolve_route('GET', '/api/v1/communications' + suffix)
    _, factory = communication_database
    runtime = build_communications_runtime(factory, Adapter(factory, []))
    with pytest.raises(ValidationError):
        runtime.routes(actor_kind=None)


def test_static_composition_runs_production_owner_matching_and_returns_same_query_authority(communication_database):
    path, factory = communication_database
    _, objective = _create_single_task_objective(factory, name="Composed Objective", start_utc=100, end_utc=200)
    identities = providers()
    from soma.foundation.persistence.uow import ReadSnapshot
    with ReadSnapshot(factory) as reader:
        target = next(item for item in identities.snapshot(reader) if item.target_id == objective.objective_id)
    adapter = Adapter(factory, [message(subject=target.normalized_value, chronology=target.effective_from)])
    runtime = build_communications_runtime(factory, adapter, clock=lambda: 2_000_000_000)
    configured, _ = configure(SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter), request())
    route = runtime.routes(actor_kind="local_user")
    started = route.dispatch("POST", f"/api/v1/communications/source-scopes/{configured['target_id']}/process",
        {"command_id": new_uuid4(), "source_scope_revision": 1})
    claim = runtime.claim_next(new_uuid4(), 2_000_000_000)
    assert claim.job_id == started.body["job_id"]
    assert runtime.dispatch(claim)["matched"] == 1
    assert scalar(path, "SELECT target_id FROM communication_links") == objective.objective_id
    response = route.dispatch("GET", f"/api/v1/communications/entities/OBJECTIVE/{objective.objective_id}/summary")
    assert response.body["received_count"] == 1
    assert set(runtime.workers) == {row["job_type"] for row in __import__('soma.communications.jobs.communications', fromlist=['_JOBS'])._JOBS}


def test_claim_eligibility_policy_cannot_mutate_and_rolls_back_its_attempt(communication_database):
    from test_communications_historical_processing import setup_history
    path, _, _, claim, jobs, _, _, _, _ = setup_history(communication_database, [])
    # A separate queued job allows the policy guard to execute.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE durable_jobs SET state='queued',claimed_run_id=NULL,claim_started_at_utc=NULL WHERE job_id=?", (claim.job_id,))
    def mutate(writer, *args):
        writer.connection.execute("UPDATE communication_job_counters SET inspected=99")
        return True
    with pytest.raises(IntegrityFailure):
        jobs.claim_next(new_uuid4(), 2_000_000_000, eligible=mutate)
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 0
    assert scalar(path, "SELECT state FROM durable_jobs") == "queued"
