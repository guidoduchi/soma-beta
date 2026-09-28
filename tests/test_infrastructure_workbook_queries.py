from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.infrastructure.queries.core import InfrastructureQueries
from soma.infrastructure.services.core import InfrastructureService


def test_workbook_replay_and_history_filter_keyset(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    queries = InfrastructureQueries(InfrastructureService(factory))
    run_ids = [new_uuid4() for _ in range(3)]
    digest = "a" * 64
    with UnitOfWork(factory) as uow:
        for index, run_id in enumerate(run_ids):
            uow.connection.execute(
                "INSERT INTO infrastructure_workbook_runs "
                "(workbook_run_id,source_filename,file_sha256,logical_fingerprint,"
                "workbook_version,workbook_mode,source_installation_scope_id,"
                "installation_relation,state,captured_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, f"run-{index}.xlsx", digest, digest, "1", "discovery",
                 "instance", "same_installation", "accepted" if index == 0 else "rejected", 5),
            )
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_replay_index "
            "(logical_fingerprint,accepted_workbook_run_id,accepted_at_utc) VALUES (?,?,?)",
            (digest, run_ids[0], 6),
        )
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_exports "
            "(export_id,mode,installation_scope_id,filter_scope_json,generated_at_utc,"
            "artifact_filename,artifact_sha256,artifact_size_bytes,command_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (new_uuid4(), "discovery", "instance", "{}", 5, "export.xlsx", digest, 1,
             _receipt(uow)),
        )

    assert queries.execute("InfrastructureWorkbookReplayQuery", {"logical_fingerprint": digest}) == {
        "accepted_run_id": run_ids[0], "accepted_at_utc": 6,
    }
    assert queries.execute("InfrastructureWorkbookReplayQuery", {"logical_fingerprint": "b" * 64}) == {
        "accepted_run_id": None, "accepted_at_utc": None,
    }
    empty_run = queries.execute("InfrastructureWorkbookRunQuery", {"run_id": run_ids[0]})
    assert empty_run["proposal_counts"] == dict(pending=0, accepted=0, rejected=0,
                                                superseded=0, ambiguous=0, invalid=0)
    assert empty_run["proposals"] == []
    seen = []
    cursor = None
    while True:
        result = queries.execute("InfrastructureWorkbookHistoryQuery", {
            "mode": "discovery", "limit": 2, **({"cursor": cursor} if cursor else {}),
        })
        seen.extend((item["kind"], item["id"]) for item in result["items"])
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 4
    assert [kind for kind, _ in seen] == ["export", "run", "run", "run"]
    filtered = queries.execute("InfrastructureWorkbookHistoryQuery", {
        "state": "accepted", "limit": 2,
    })
    assert [(item["kind"], item["id"]) for item in filtered["items"]] == [("run", run_ids[0])]


def test_workbook_run_review_groups_and_cursor(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    queries = InfrastructureQueries(InfrastructureService(factory))
    run_id = new_uuid4()
    digest = "c" * 64
    entries = [("ambiguous", "network_elements", 2),
               ("create_network_element", "network_elements", 3),
               ("unchanged", "ip_addresses", 2)]
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_runs "
            "(workbook_run_id,source_filename,file_sha256,logical_fingerprint,"
            "workbook_version,workbook_mode,source_installation_scope_id,"
            "installation_relation,state,captured_at_utc,network_element_row_count,"
            "ip_row_count,warning_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "input.xlsx", digest, digest, "1.0", "round_trip", "instance",
             "same_installation", "reviewed", 5, 2, 1, 1),
        )
        for action, sheet, ordinal in entries:
            staging_id = new_uuid4()
            uow.connection.execute(
                "INSERT INTO infrastructure_workbook_staging_rows "
                "(staging_row_id,workbook_run_id,sheet_kind,row_ordinal,row_fingerprint,"
                "normalized_row_json,validation_state,warning_codes_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (staging_id, run_id, sheet, ordinal, digest, "{}", "warning", '["REVIEW"]'),
            )
            uow.connection.execute(
                "INSERT INTO infrastructure_workbook_proposals "
                "(proposal_id,workbook_run_id,staging_row_id,action,state,input_fingerprint,"
                "impact_json,created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                (new_uuid4(), run_id, staging_id, action, "pending", digest, "{}", 5),
            )
    actions = []
    cursor = None
    first_cursor = None
    while True:
        result = queries.execute("InfrastructureWorkbookRunQuery", {
            "run_id": run_id, "limit": 1, **({"cursor": cursor} if cursor else {}),
        })
        actions.extend(proposal["action"] for proposal in result["proposals"])
        assert result["proposal_counts"] == dict(pending=3, accepted=0, rejected=0,
                                                   superseded=0, ambiguous=1, invalid=0)
        assert result["row_counts"] == dict(network_elements=2, ip_addresses=1, warnings=1)
        assert result["proposals"][0]["warning_codes"] == ["REVIEW"]
        cursor = result["next_cursor"]
        if first_cursor is None:
            first_cursor = cursor
        if cursor is None:
            break
    assert actions == ["create_network_element", "unchanged", "ambiguous"]
    filtered = queries.execute("InfrastructureWorkbookRunQuery", {
        "run_id": run_id, "proposal_state": "rejected",
    })
    assert filtered["proposals"] == []
    assert filtered["next_cursor"] is None
    with pytest.raises(SomaError) as error:
        queries.execute("InfrastructureWorkbookRunQuery", {
            "run_id": run_id, "proposal_state": "rejected", "cursor": first_cursor,
        })
    assert error.value.code == "CURSOR_INVALID"


def _receipt(uow):
    identity = new_uuid4()
    uow.connection.execute(
        "INSERT INTO command_receipts "
        "(command_id,command_type,request_hash,target_type,committed_at_utc) "
        "VALUES (?,?,?,?,?)",
        (identity, "test", "a" * 64, "workbook_export", 5),
    )
    return identity
