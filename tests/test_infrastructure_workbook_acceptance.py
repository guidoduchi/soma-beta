from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes
from soma.infrastructure.domain.workbook_normalization import (
    normalize_workbook_row,
    workbook_logical_fingerprint,
)
from soma.infrastructure.domain.workbooks import HEADERS
from soma.infrastructure.jobs.workbook_proposals import build_workbook_proposal
from soma.infrastructure.services.core import InfrastructureService
from soma.reference.application.customer_service import CustomerReferenceService


def _values(sheet: str, **fields):
    return tuple(fields.get(name) for name in HEADERS[sheet])


def _assembled(initialized_database):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    service = InfrastructureService(factory)
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Workbook acceptance customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Workbook Acceptance Site",
            "address_text": "1 Acceptance Street",
        },
    ).response["target"]["id"]
    with ReadSnapshot(factory) as snapshot:
        data_instance_id = str(
            snapshot.connection.execute(
                "SELECT data_instance_id FROM instance_metadata"
            ).fetchone()[0]
        )
    return factory, service, site_id, data_instance_id


def _network_element(service, site_id: str, *, name: str, serial: str | None = None):
    return service.execute(
        "CreateNetworkElement",
        command_id=new_uuid4(),
        payload={
            "new_element": {
                "site_id": site_id,
                "operational_name": name,
                "manufacturer_serial": serial,
            },
        },
    ).response["target"]["id"]


def _seed_staged_run(factory, data_instance_id: str, rows):
    normalized_rows = []
    network_fingerprints = []
    ip_fingerprints = []
    for sheet_name, values in rows:
        normalized, row_fingerprint = normalize_workbook_row(
            sheet_name,
            values,
            same_installation=True,
        )
        sheet_kind = (
            "network_elements" if sheet_name == "Network Elements" else "ip_addresses"
        )
        normalized_rows.append((sheet_kind, normalized, row_fingerprint))
        if sheet_kind == "network_elements":
            network_fingerprints.append(row_fingerprint)
        else:
            ip_fingerprints.append(row_fingerprint)

    logical = workbook_logical_fingerprint(
        mode="round_trip",
        source_installation_scope_id=data_instance_id,
        export_scope={"scope_kind": "all"},
        network_rows=network_fingerprints,
        ip_rows=ip_fingerprints,
    )
    run_id = new_uuid4()
    now = utc_epoch_seconds()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            """
            INSERT INTO infrastructure_workbook_runs(
                workbook_run_id,source_filename,file_sha256,logical_fingerprint,
                workbook_version,workbook_mode,source_installation_scope_id,
                installation_relation,state,network_element_row_count,ip_row_count,
                warning_count,captured_at_utc,published_at_utc,last_command_id,revision
            ) VALUES (?,?,?,?,?,?,?,'same_installation','staged',?,?,0,?,?,NULL,2)
            """,
            (
                run_id,
                "acceptance-fixture.xlsx",
                "f" * 64,
                logical,
                "1.0",
                "round_trip",
                data_instance_id,
                len(network_fingerprints),
                len(ip_fingerprints),
                now,
                now,
            ),
        )
        staged = []
        ordinals = {"network_elements": 1, "ip_addresses": 1}
        for sheet_kind, normalized, row_fingerprint in normalized_rows:
            ordinals[sheet_kind] += 1
            staging_id = new_uuid4()
            normalized_json = canonical_json_bytes(normalized).decode("utf-8")
            uow.connection.execute(
                """
                INSERT INTO infrastructure_workbook_staging_rows(
                    staging_row_id,workbook_run_id,sheet_kind,row_ordinal,
                    row_fingerprint,normalized_row_json,validation_state,
                    warning_codes_json
                ) VALUES (?,?,?,?,?,?,'valid','[]')
                """,
                (
                    staging_id,
                    run_id,
                    sheet_kind,
                    ordinals[sheet_kind],
                    row_fingerprint,
                    normalized_json,
                ),
            )
            staged.append(
                (
                    staging_id,
                    sheet_kind,
                    ordinals[sheet_kind],
                    normalized,
                    row_fingerprint,
                )
            )

        proposals = []
        for staging_id, sheet_kind, ordinal, normalized, row_fingerprint in staged:
            proposal = build_workbook_proposal(
                uow,
                workbook_run_id=run_id,
                sheet_kind=sheet_kind,
                normalized_row=normalized,
                row_fingerprint=row_fingerprint,
                same_installation=True,
            )
            proposal_id = new_uuid4()
            uow.connection.execute(
                """
                INSERT INTO infrastructure_workbook_proposals(
                    proposal_id,workbook_run_id,staging_row_id,action,state,
                    target_network_element_id,expected_target_revision,
                    input_fingerprint,impact_json,created_at_utc,last_command_id,
                    revision,candidate_ids_json
                ) VALUES (?,?,?,?,'pending',?,?,?,?,?,NULL,1,?)
                """,
                (
                    proposal_id,
                    run_id,
                    staging_id,
                    proposal["action"],
                    proposal["target_network_element_id"],
                    proposal["expected_target_revision"],
                    proposal["input_fingerprint"],
                    canonical_json_bytes(proposal["impact"]).decode("utf-8"),
                    now,
                    canonical_json_bytes(proposal["candidate_ids"]).decode("utf-8"),
                ),
            )
            warning_json = canonical_json_bytes(
                proposal["warning_codes"]
            ).decode("utf-8")
            validation_state = (
                "invalid"
                if proposal["action"] == "skip_invalid"
                else "warning"
                if proposal["warning_codes"]
                else "valid"
            )
            uow.connection.execute(
                "UPDATE infrastructure_workbook_staging_rows "
                "SET validation_state=?,warning_codes_json=? "
                "WHERE staging_row_id=?",
                (validation_state, warning_json, staging_id),
            )
            proposals.append(
                {
                    "proposal_id": proposal_id,
                    "action": proposal["action"],
                    "fingerprint": proposal["input_fingerprint"],
                    "revision": 1,
                    "sheet_kind": sheet_kind,
                    "row_ordinal": ordinal,
                }
            )
    return run_id, logical, proposals


def _accept(service, run_id: str, logical: str, proposals, *, decisions=None):
    command_id = new_uuid4()
    disposition_values = []
    decisions = decisions or {}
    for proposal in proposals:
        disposition_values.append(
            {
                "proposal_id": proposal["proposal_id"],
                "expected_revision": proposal["revision"],
                "decision": decisions.get(proposal["proposal_id"], "accept"),
                "proposal_fingerprint": proposal["fingerprint"],
            }
        )
    return command_id, service.execute(
        "AcceptInfrastructureWorkbookRun",
        command_id=command_id,
        payload={
            "run_id": run_id,
            "run_revision": 2,
            "run_input_fingerprint": logical,
            "dispositions": disposition_values,
        },
    )


def test_accept_workbook_updates_descriptive_and_persists_terminal_evidence(
    initialized_database,
) -> None:
    factory, service, site_id, data_instance_id = _assembled(initialized_database)
    ne_id = _network_element(service, site_id, name="NE-OLD", serial="SERIAL-1")
    run_id, logical, proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [
            (
                "Network Elements",
                _values(
                    "Network Elements",
                    SomaNetworkElementId=ne_id,
                    OperationalName="NE-NEW",
                    SomaSiteId=site_id,
                ),
            )
        ],
    )
    assert proposals[0]["action"] == "update_network_element"

    command_id, execution = _accept(service, run_id, logical, proposals)

    assert execution.response["state"] == "accepted"
    assert execution.response["created"] == 0
    assert execution.response["updated"] == 1
    assert execution.response["unchanged"] == 0
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT operational_name,manufacturer_serial,revision "
            "FROM network_elements WHERE network_element_id=?",
            (ne_id,),
        ).fetchone() == ("NE-NEW", "SERIAL-1", 2)
        assert snapshot.connection.execute(
            "SELECT state,revision,last_command_id FROM infrastructure_workbook_runs "
            "WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == ("accepted", 3, command_id)
        assert snapshot.connection.execute(
            "SELECT disposition,target_network_element_id,command_id "
            "FROM infrastructure_workbook_row_decisions WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == ("updated", ne_id, command_id)
        assert snapshot.connection.execute(
            "SELECT accepted_workbook_run_id FROM infrastructure_workbook_replay_index "
            "WHERE logical_fingerprint=?",
            (logical,),
        ).fetchone() == (run_id,)
        assert snapshot.connection.execute(
            "SELECT action_type FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone() == ("infrastructure.workbook.accept",)


def test_accept_workbook_revalidates_target_drift_before_receipt(
    initialized_database,
) -> None:
    factory, service, site_id, data_instance_id = _assembled(initialized_database)
    ne_id = _network_element(service, site_id, name="NE-STALE", serial="SERIAL-S")
    run_id, logical, proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [
            (
                "Network Elements",
                _values(
                    "Network Elements",
                    SomaNetworkElementId=ne_id,
                    OperationalName="NE-REVIEWED",
                    SomaSiteId=site_id,
                ),
            )
        ],
    )
    service.execute(
        "UpdateNetworkElementDescriptive",
        command_id=new_uuid4(),
        payload={
            "network_element_id": ne_id,
            "base_revision": 1,
            "operational_name": "NE-CHANGED-ELSEWHERE",
            "manufacturer_serial": "SERIAL-S",
            "reason_code": "correction",
        },
    )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as error:
        service.execute(
            "AcceptInfrastructureWorkbookRun",
            command_id=command_id,
            payload={
                "run_id": run_id,
                "run_revision": 2,
                "run_input_fingerprint": logical,
                "dispositions": [
                    {
                        "proposal_id": proposals[0]["proposal_id"],
                        "expected_revision": 1,
                        "decision": "accept",
                        "proposal_fingerprint": proposals[0]["fingerprint"],
                    }
                ],
            },
        )
    assert error.value.code == "WORKBOOK_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,revision FROM infrastructure_workbook_runs WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == ("staged", 2)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_row_decisions "
            "WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (0,)


def test_accept_workbook_rejects_ambiguous_selected_identity(
    initialized_database,
) -> None:
    factory, service, site_id, data_instance_id = _assembled(initialized_database)
    _network_element(service, site_id, name="NE-DUPLICATE", serial="DUP-1")
    run_id, logical, proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [
            (
                "Network Elements",
                _values(
                    "Network Elements",
                    OperationalName="NE-DUPLICATE",
                    SomaSiteId=site_id,
                ),
            )
        ],
    )
    assert proposals[0]["action"] == "ambiguous"
    with pytest.raises(SomaError) as error:
        _accept(service, run_id, logical, proposals)
    assert error.value.code == "WORKBOOK_AMBIGUOUS_IDENTITY"


def test_accept_workbook_creates_element_and_binds_pending_ip_row(
    initialized_database,
) -> None:
    factory, service, site_id, data_instance_id = _assembled(initialized_database)
    network_values = _values(
        "Network Elements",
        OperationalName="NE-WORKBOOK-NEW",
        ManufacturerSerial="WB-NEW-1",
        SomaSiteId=site_id,
    )
    ip_values = _values(
        "IP Addresses",
        OperationalName="NE-WORKBOOK-NEW",
        Address="203.0.113.25",
        Primary=True,
    )
    run_id, logical, proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [
            ("Network Elements", network_values),
            ("IP Addresses", ip_values),
        ],
    )
    assert [item["action"] for item in proposals] == [
        "create_network_element",
        "update_ip_set",
    ]

    _command_id, execution = _accept(service, run_id, logical, proposals)

    assert execution.response["created"] == 1
    assert execution.response["updated"] == 1
    with ReadSnapshot(factory) as snapshot:
        element = snapshot.connection.execute(
            "SELECT network_element_id,revision FROM network_elements "
            "WHERE operational_name='NE-WORKBOOK-NEW'"
        ).fetchone()
        assert element is not None
        assert element[1] == 1
        ip = snapshot.connection.execute(
            "SELECT network_element_id,canonical_address,is_primary,revision "
            "FROM network_element_ip_current WHERE network_element_id=?",
            (element[0],),
        ).fetchone()
        assert ip == (element[0], "203.0.113.25", 1, 1)
        decisions = snapshot.connection.execute(
            "SELECT sheet_kind,disposition,target_network_element_id "
            "FROM infrastructure_workbook_row_decisions "
            "WHERE workbook_run_id=? ORDER BY sheet_kind",
            (run_id,),
        ).fetchall()
        assert decisions == [
            ("ip_addresses", "updated", element[0]),
            ("network_elements", "created", element[0]),
        ]


def test_identical_accepted_logical_content_replays_without_second_domain_mutation(
    initialized_database,
) -> None:
    factory, service, site_id, data_instance_id = _assembled(initialized_database)
    values = _values(
        "Network Elements",
        OperationalName="NE-LOGICAL-REPLAY",
        SomaSiteId=site_id,
    )
    first_run, logical, first_proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [("Network Elements", values)],
    )
    _first_command, first = _accept(service, first_run, logical, first_proposals)
    assert first.response["created"] == 1

    second_run, second_logical, second_proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [("Network Elements", values)],
    )
    assert second_logical == logical
    second_command, second = _accept(
        service,
        second_run,
        second_logical,
        second_proposals,
    )

    assert second.no_change
    assert second.response["command_id"] == second_command
    assert second.response["run_id"] == first_run
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM network_elements "
            "WHERE operational_name='NE-LOGICAL-REPLAY'"
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT state FROM infrastructure_workbook_runs WHERE workbook_run_id=?",
            (second_run,),
        ).fetchone() == ("staged",)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (second_command,),
        ).fetchone() == (0,)
