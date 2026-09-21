from __future__ import annotations

import sqlite3

import pytest

from soma.foundation.identifiers import new_uuid4


LLD03_TABLES = {
    "sr_local_id_allocator",
    "service_requests",
    "rfcs",
    "sr_working_notes",
    "rfc_working_notes",
    "device_references",
    "rfc_hierarchy_edges",
    "sr_rfc_links",
    "rfc_device_reference_links",
    "sr_device_reference_links",
    "sr_source_field_observations",
    "sr_current_source_projection",
    "sr_customer_relationships",
    "sr_contact_relationships",
    "rfc_current_source_projection",
    "rfc_terminal_cascade_proposals",
    "rfc_terminal_cascade_rfc_members",
    "rfc_terminal_cascade_wfm_members",
    "rfc_archive_operations",
    "rfc_archive_operation_members",
    "rfc_archive_events",
}


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _rw(initialized_database):
    return _factory(initialized_database).open_authoritative(read_only=False, require_wal=True)


def _receipt(connection, command_id: str | None = None) -> str:
    command_id = command_id or new_uuid4()
    connection.execute(
        "INSERT INTO command_receipts("
        "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
        ") VALUES (?, 'SchemaTest', ?, 'schema_test', NULL, 1, NULL, NULL)",
        (command_id, "0" * 64),
    )
    return command_id


def _rfc(connection, rfc_no: str) -> str:
    rfc_id = new_uuid4()
    connection.execute(
        "INSERT INTO rfcs(rfc_id,rfc_no,revision,created_at_utc,updated_at_utc) VALUES (?, ?, 1, 1, 1)",
        (rfc_id, rfc_no),
    )
    return rfc_id


def _sr(connection, local_no: str) -> str:
    sr_id = new_uuid4()
    connection.execute(
        "INSERT INTO service_requests(service_request_id,local_sr_no,revision,created_at_utc,updated_at_utc) "
        "VALUES (?, ?, 1, 1, 1)",
        (sr_id, local_no),
    )
    return sr_id


def test_lld03_migration_is_current_strict_and_fk_clean(initialized_database) -> None:
    factory = _factory(initialized_database)
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        migration = connection.execute(
            "SELECT migration_id FROM schema_migrations WHERE sequence=3"
        ).fetchone()
        assert migration is not None
        assert migration[0] == "beta_0003_tickets_core"
        strict_by_name = {
            str(row[1]): int(row[5])
            for row in connection.execute("PRAGMA table_list").fetchall()
            if len(row) >= 6
        }
        assert all(strict_by_name.get(name) == 1 for name in LLD03_TABLES)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT next_value FROM sr_local_id_allocator WHERE singleton_guard=1"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_ticket_business_identifiers_are_whole_value_strict(initialized_database) -> None:
    connection = _rw(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO service_requests(service_request_id,official_sr_no,revision,created_at_utc,updated_at_utc) "
                "VALUES (?, 'SR12345678', 1, 1, 1)",
                (new_uuid4(),),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO service_requests(service_request_id,local_sr_no,revision,created_at_utc,updated_at_utc) "
                "VALUES (?, 'LSR-123', 1, 1, 1)",
                (new_uuid4(),),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO rfcs(rfc_id,rfc_no,revision,created_at_utc,updated_at_utc) "
                "VALUES (?, 'prefix-NC20260804000241', 1, 1, 1)",
                (new_uuid4(),),
            )
        connection.execute("ROLLBACK")
    finally:
        connection.close()


def test_rfc_forest_and_root_only_sr_link_are_database_invariants(initialized_database) -> None:
    connection = _rw(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        root = _rfc(connection, "NC20260804000241")
        child = _rfc(connection, "NC20260804000242")
        third = _rfc(connection, "NC20260804000243")
        other_root = _rfc(connection, "NC20260804000244")
        sr_id = _sr(connection, "LSR-00000001")
        open_command = _receipt(connection)
        connection.execute(
            "INSERT INTO rfc_hierarchy_edges("
            "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
            ") VALUES (?, ?, ?, 'active', 1, ?)",
            (new_uuid4(), root, child, open_command),
        )

        with pytest.raises(sqlite3.IntegrityError, match="RFC_HIERARCHY_DEPTH"):
            connection.execute(
                "INSERT INTO rfc_hierarchy_edges("
                "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
                ") VALUES (?, ?, ?, 'active', 1, ?)",
                (new_uuid4(), child, third, open_command),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO rfc_hierarchy_edges("
                "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
                ") VALUES (?, ?, ?, 'active', 1, ?)",
                (new_uuid4(), other_root, child, open_command),
            )
        with pytest.raises(sqlite3.IntegrityError, match="RFC_DIRECT_SR_LINK_ON_SUBORDINATE"):
            connection.execute(
                "INSERT INTO sr_rfc_links("
                "sr_rfc_link_id,service_request_id,rfc_id,link_state,opened_at_utc,opened_command_id"
                ") VALUES (?, ?, ?, 'active', 1, ?)",
                (new_uuid4(), sr_id, child, open_command),
            )

        direct_root = _rfc(connection, "NC20260804000245")
        connection.execute(
            "INSERT INTO sr_rfc_links("
            "sr_rfc_link_id,service_request_id,rfc_id,link_state,opened_at_utc,opened_command_id"
            ") VALUES (?, ?, ?, 'active', 1, ?)",
            (new_uuid4(), sr_id, direct_root, open_command),
        )
        with pytest.raises(sqlite3.IntegrityError, match="RFC_DIRECT_SR_LINK_ON_SUBORDINATE"):
            connection.execute(
                "INSERT INTO rfc_hierarchy_edges("
                "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
                ") VALUES (?, ?, ?, 'active', 1, ?)",
                (new_uuid4(), other_root, direct_root, open_command),
            )
        connection.execute("ROLLBACK")
    finally:
        connection.close()


def test_relationship_history_is_terminal_and_not_deletable(initialized_database) -> None:
    connection = _rw(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        root = _rfc(connection, "NC20260804000301")
        child = _rfc(connection, "NC20260804000302")
        opened = _receipt(connection)
        closed = _receipt(connection)
        edge_id = new_uuid4()
        connection.execute(
            "INSERT INTO rfc_hierarchy_edges("
            "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
            ") VALUES (?, ?, ?, 'active', 1, ?)",
            (edge_id, root, child, opened),
        )
        connection.execute(
            "UPDATE rfc_hierarchy_edges SET edge_state='superseded',closed_at_utc=2,closed_command_id=? "
            "WHERE rfc_hierarchy_edge_id=?",
            (closed, edge_id),
        )
        with pytest.raises(sqlite3.IntegrityError, match="RFC_HIERARCHY_HISTORY_APPEND_ONLY"):
            connection.execute(
                "UPDATE rfc_hierarchy_edges SET closed_at_utc=3 WHERE rfc_hierarchy_edge_id=?",
                (edge_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="RFC_HIERARCHY_HISTORY_APPEND_ONLY"):
            connection.execute(
                "DELETE FROM rfc_hierarchy_edges WHERE rfc_hierarchy_edge_id=?",
                (edge_id,),
            )
        connection.execute("ROLLBACK")
    finally:
        connection.close()


def test_device_reference_stays_infrastructure_neutral_and_duplicate_names_are_valid(initialized_database) -> None:
    connection = _rw(initialized_database)
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(device_references)").fetchall()
        }
        assert "network_element_id" not in columns
        assert "customer_org_id" not in columns
        assert "site_id" not in columns
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO device_references(device_reference_id,operational_name,revision,created_at_utc,updated_at_utc) "
            "VALUES (?, 'shared-hostname', 1, 1, 1)",
            (new_uuid4(),),
        )
        connection.execute(
            "INSERT INTO device_references(device_reference_id,operational_name,revision,created_at_utc,updated_at_utc) "
            "VALUES (?, 'shared-hostname', 1, 1, 1)",
            (new_uuid4(),),
        )
        assert connection.execute(
            "SELECT count(*) FROM device_references WHERE operational_name='shared-hostname'"
        ).fetchone()[0] == 2
        connection.execute("ROLLBACK")
    finally:
        connection.close()


def test_sr_source_projection_cannot_cross_sr_or_field_boundaries(initialized_database) -> None:
    connection = _rw(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        sr_a = _sr(connection, "LSR-00000011")
        sr_b = _sr(connection, "LSR-00000012")
        command = _receipt(connection)
        problem_obs = new_uuid4()
        status_obs = new_uuid4()
        other_sr_problem_obs = new_uuid4()
        connection.execute(
            "INSERT INTO sr_source_field_observations("
            "sr_source_field_observation_id,service_request_id,field_key,value_state,value_kind,text_value,"
            "source_chronology_utc,precedence_basis,source_observation_field_id,accepted_command_id,recorded_at_utc"
            ") VALUES (?, ?, 'problem_summary', 'usable', 'text', 'summary', 10, 'source_chronology', 'evidence-a', ?, 10)",
            (problem_obs, sr_a, command),
        )
        connection.execute(
            "INSERT INTO sr_source_field_observations("
            "sr_source_field_observation_id,service_request_id,field_key,value_state,value_kind,text_value,"
            "source_chronology_utc,precedence_basis,source_observation_field_id,accepted_command_id,recorded_at_utc"
            ") VALUES (?, ?, 'status', 'usable', 'controlled', 'Open', 10, 'source_chronology', 'evidence-b', ?, 10)",
            (status_obs, sr_a, command),
        )
        connection.execute(
            "INSERT INTO sr_source_field_observations("
            "sr_source_field_observation_id,service_request_id,field_key,value_state,value_kind,text_value,"
            "source_chronology_utc,precedence_basis,source_observation_field_id,accepted_command_id,recorded_at_utc"
            ") VALUES (?, ?, 'problem_summary', 'usable', 'text', 'other', 10, 'source_chronology', 'evidence-c', ?, 10)",
            (other_sr_problem_obs, sr_b, command),
        )
        with pytest.raises(sqlite3.IntegrityError, match="SR_SOURCE_PROJECTION_INVALID"):
            connection.execute(
                "INSERT INTO sr_current_source_projection(service_request_id,problem_summary_observation_id) VALUES (?, ?)",
                (sr_a, status_obs),
            )
        with pytest.raises(sqlite3.IntegrityError, match="SR_SOURCE_PROJECTION_INVALID"):
            connection.execute(
                "INSERT INTO sr_current_source_projection(service_request_id,problem_summary_observation_id) VALUES (?, ?)",
                (sr_a, other_sr_problem_obs),
            )
        connection.execute(
            "INSERT INTO sr_current_source_projection(service_request_id,problem_summary_observation_id) VALUES (?, ?)",
            (sr_a, problem_obs),
        )
        with pytest.raises(sqlite3.IntegrityError, match="SR_SOURCE_PROJECTION_INVALID"):
            connection.execute(
                "UPDATE sr_current_source_projection SET revision=2 WHERE service_request_id=?",
                (sr_a,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="SR_SOURCE_OBSERVATION_APPEND_ONLY"):
            connection.execute(
                "UPDATE sr_source_field_observations SET text_value='changed' WHERE sr_source_field_observation_id=?",
                (problem_obs,),
            )
        connection.execute("ROLLBACK")
    finally:
        connection.close()


def test_current_handler_reference_binds_same_sr_handler_evidence(initialized_database) -> None:
    connection = _rw(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        sr_a = _sr(connection, "LSR-00000021")
        sr_b = _sr(connection, "LSR-00000022")
        command = _receipt(connection)
        contact_id = new_uuid4()
        connection.execute(
            "INSERT INTO contacts(contact_id,name,name_match_key,lifecycle_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?, 'Handler', 'handler', 'active', 1, 1, 1)",
            (contact_id,),
        )
        handler_obs = new_uuid4()
        connection.execute(
            "INSERT INTO sr_source_field_observations("
            "sr_source_field_observation_id,service_request_id,field_key,value_state,value_kind,text_value,"
            "source_chronology_utc,precedence_basis,source_observation_field_id,accepted_command_id,recorded_at_utc"
            ") VALUES (?, ?, 'current_handler_label', 'usable', 'text', 'Handler', 10, 'source_chronology', 'handler-evidence', ?, 10)",
            (handler_obs, sr_b, command),
        )
        with pytest.raises(sqlite3.IntegrityError, match="SR_HANDLER_REFERENCE_STALE"):
            connection.execute(
                "INSERT INTO sr_contact_relationships("
                "sr_contact_relationship_id,service_request_id,reference_role,contact_id,relationship_state,origin_kind,"
                "supporting_sr_source_field_observation_id,opened_at_utc,opened_command_id"
                ") VALUES (?, ?, 'current_handler_reference', ?, 'active', 'manual_review', ?, 10, ?)",
                (new_uuid4(), sr_a, contact_id, handler_obs, command),
            )
        connection.execute("ROLLBACK")
    finally:
        connection.close()


def test_cascade_and_archive_evidence_are_append_only(initialized_database) -> None:
    connection = _rw(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        rfc_id = _rfc(connection, "NC20260804000401")
        command = _receipt(connection)
        proposal_id = new_uuid4()
        connection.execute(
            "INSERT INTO rfc_terminal_cascade_proposals("
            "rfc_terminal_cascade_proposal_id,trigger_rfc_id,terminal_epoch_id,terminal_status_class,"
            "terminal_status_evidence_id,scope_kind,scope_fingerprint,proposal_state,revision,created_at_utc,created_command_id"
            ") VALUES (?, ?, 'epoch-1', 'terminal_closed', 'status-evidence', 'exact_rfc', ?, 'pending', 1, 10, ?)",
            (proposal_id, rfc_id, "a" * 64, command),
        )
        connection.execute(
            "INSERT INTO rfc_terminal_cascade_rfc_members("
            "rfc_terminal_cascade_proposal_id,rfc_id,captured_rfc_revision,captured_role,ordinal"
            ") VALUES (?, ?, 1, 'standalone', 0)",
            (proposal_id, rfc_id),
        )
        with pytest.raises(sqlite3.IntegrityError, match="RFC_CASCADE_MEMBERSHIP_IMMUTABLE"):
            connection.execute(
                "DELETE FROM rfc_terminal_cascade_rfc_members WHERE rfc_terminal_cascade_proposal_id=?",
                (proposal_id,),
            )

        operation_id = new_uuid4()
        connection.execute(
            "INSERT INTO rfc_archive_operations("
            "rfc_archive_operation_id,requested_rfc_id,scope_kind,scope_fingerprint,created_at_utc,created_command_id"
            ") VALUES (?, ?, 'exact_rfc', ?, 10, ?)",
            (operation_id, rfc_id, "b" * 64, command),
        )
        with pytest.raises(sqlite3.IntegrityError, match="RFC_ARCHIVE_SCOPE_STALE"):
            connection.execute(
                "INSERT INTO rfc_archive_events("
                "rfc_archive_event_id,rfc_id,event_type,origin_archive_operation_id,resulting_rfc_revision,occurred_at_utc,command_id"
                ") VALUES (?, ?, 'archived', ?, 2, 11, ?)",
                (new_uuid4(), rfc_id, operation_id, command),
            )
        connection.execute("UPDATE rfcs SET revision=2,updated_at_utc=11 WHERE rfc_id=?", (rfc_id,))
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO rfc_archive_events("
            "rfc_archive_event_id,rfc_id,event_type,origin_archive_operation_id,resulting_rfc_revision,occurred_at_utc,command_id"
            ") VALUES (?, ?, 'archived', ?, 2, 11, ?)",
            (event_id, rfc_id, operation_id, command),
        )
        with pytest.raises(sqlite3.IntegrityError, match="RFC_ARCHIVE_HISTORY_APPEND_ONLY"):
            connection.execute("DELETE FROM rfc_archive_events WHERE rfc_archive_event_id=?", (event_id,))
        connection.execute("ROLLBACK")
    finally:
        connection.close()
