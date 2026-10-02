from copy import deepcopy
import sqlite3

import pytest

from soma.communications.api.routes_communications import resolve_route
from soma.communications.composition import build_communications_runtime
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from test_communications_housekeeping import seed
from test_communications_processing_worker import Adapter
from test_communications_queries import add_link
from test_communications_summaries import Owners


@pytest.fixture
def panel_route(communication_database):
    path, factory = communication_database
    target = new_uuid4()
    messages = [seed(path, pending=False) for _ in range(7)]
    with sqlite3.connect(path) as db:
        for message, instant in zip(messages, (200, 200, 100, 100, None, None, None)):
            if instant is not None:
                db.execute("UPDATE communications SET chronology_known=1,chronology_utc=?,chronology_source_kind='RECEIVED_TIME' WHERE communication_id=?", (instant, message))
            add_link(db, message, target)
    runtime = build_communications_runtime(factory, Adapter(factory, []), identity_providers=Owners())
    return path, factory, runtime, runtime.routes(actor_kind="local_user"), target


def test_panel_http_dispatches_exact_provider_and_preserves_canonical_keyset(panel_route, monkeypatch):
    path, factory, runtime, route, target = panel_route
    endpoint = f"/api/v1/communications/entities/OBJECTIVE/{target}/panel"
    spec, parameters = resolve_route("GET", endpoint)
    assert spec["request_type"] == "CommunicationPanelQueryV1"
    assert spec["auth_policy"] == "LLD12_BROWSER_QUERY_V1"
    assert spec["input_ownership"]["path_fields"] == ["target_type", "target_id"]
    original = runtime.providers["panel"].panel
    seen = []
    def observed(snapshot, *args):
        seen.append(args)
        return original(snapshot, *args)
    monkeypatch.setattr(runtime.providers["panel"], "panel", observed)
    found, cursor = [], None
    while True:
        response = route.dispatch("GET", endpoint, {"cursor": cursor, "limit": 2})
        assert response.status == 200 and response.response_type == "CommunicationPanelProjectionV1"
        with ReadSnapshot(factory) as reader:
            assert dict(response.body) == original(reader, "OBJECTIVE", target, cursor, 2)
        assert response.body["summary"]["received_count"] == 7
        found.extend(item["communication_id"] for item in response.body["recent_messages"]["items"])
        cursor = response.body["recent_messages"]["next_cursor"]
        if cursor is None:
            break
        assert cursor["query_id"] == "ListCommunications" and len(cursor["last_key_tuple"]) == 3
    assert len(found) == len(set(found)) == 7 and len(seen) == 4
    assert seen[0] == ("OBJECTIVE", target, None, 2)
    response = route.dispatch("GET", endpoint)
    assert len(response.body["recent_messages"]["items"]) == 7
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0


@pytest.mark.parametrize("body", [{"limit": 0}, {"limit": 51}, {"limit": True}, {"limit": "50"},
                                  {"search": "forbidden"}, {"target_id": "invalid"}, {"cursor": {}},
                                  {"cursor": "x" * 4096}])
def test_panel_http_rejects_unknown_fields_path_conflicts_and_bad_bounds(panel_route, body):
    _, _, _, route, target = panel_route
    with pytest.raises(ValidationError):
        route.dispatch("GET", f"/api/v1/communications/entities/OBJECTIVE/{target}/panel", body)


def test_panel_cursor_is_fenced_to_target_and_retains_null_chronology(panel_route):
    _, _, _, route, target = panel_route
    endpoint = f"/api/v1/communications/entities/OBJECTIVE/{target}/panel"
    cursor = route.dispatch("GET", endpoint, {"limit": 1}).body["recent_messages"]["next_cursor"]
    with pytest.raises(ValidationError):
        route.dispatch("GET", f"/api/v1/communications/entities/OBJECTIVE/{new_uuid4()}/panel", {"cursor": cursor})
    truncated = deepcopy(cursor)
    truncated["last_key_tuple"] = truncated["last_key_tuple"][:2]
    with pytest.raises(ValidationError):
        route.dispatch("GET", endpoint, {"cursor": truncated})
    with pytest.raises(ValidationError):
        route.dispatch("GET", endpoint.replace("OBJECTIVE", "UNKNOWN"))
