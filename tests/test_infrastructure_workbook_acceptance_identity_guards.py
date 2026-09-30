from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from test_infrastructure_workbook_acceptance import (
    _assembled,
    _network_element,
    _seed_staged_run,
    _values,
)


def test_accept_workbook_rejects_duplicate_explicit_ip_identity_rows(
    initialized_database,
) -> None:
    factory, service, site_id, data_instance_id = _assembled(initialized_database)
    network_element_id = _network_element(
        service,
        site_id,
        name="NE-IP-DUPLICATE",
    )
    ip_id = service.execute(
        "AddNetworkElementIp",
        command_id=new_uuid4(),
        payload={
            "network_element_id": network_element_id,
            "address": "192.0.2.10",
            "make_primary": False,
        },
    ).response["target"]["id"]

    run_id, logical, proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [
            (
                "IP Addresses",
                _values(
                    "IP Addresses",
                    SomaIpId=ip_id,
                    SomaNetworkElementId=network_element_id,
                    OperationalName="NE-IP-DUPLICATE",
                    Address="192.0.2.11",
                    Primary=False,
                ),
            ),
            (
                "IP Addresses",
                _values(
                    "IP Addresses",
                    SomaIpId=ip_id,
                    SomaNetworkElementId=network_element_id,
                    OperationalName="NE-IP-DUPLICATE",
                    Address="192.0.2.12",
                    Primary=False,
                ),
            ),
        ],
    )
    assert [item["action"] for item in proposals] == [
        "update_ip_set",
        "update_ip_set",
    ]

    command_id = new_uuid4()
    with pytest.raises(SomaError) as duplicate:
        service.execute(
            "AcceptInfrastructureWorkbookRun",
            command_id=command_id,
            payload={
                "run_id": run_id,
                "run_revision": 2,
                "run_input_fingerprint": logical,
                "dispositions": [
                    {
                        "proposal_id": proposal["proposal_id"],
                        "expected_revision": proposal["revision"],
                        "decision": "accept",
                        "proposal_fingerprint": proposal["fingerprint"],
                    }
                    for proposal in proposals
                ],
            },
        )
    assert duplicate.value.code == "WORKBOOK_RELATION_INVALID"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT canonical_address,revision FROM network_element_ip_current "
            "WHERE network_element_ip_id=?",
            (ip_id,),
        ).fetchone() == ("192.0.2.10", 1)
        assert snapshot.connection.execute(
            "SELECT state,revision FROM infrastructure_workbook_runs "
            "WHERE workbook_run_id=?",
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


def test_accept_workbook_rejects_duplicate_existing_network_element_rows(
    initialized_database,
) -> None:
    factory, service, site_id, data_instance_id = _assembled(initialized_database)
    network_element_id = _network_element(
        service,
        site_id,
        name="NE-ROW-DUPLICATE",
        serial="ROW-DUPLICATE",
    )

    run_id, logical, proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [
            (
                "Network Elements",
                _values(
                    "Network Elements",
                    SomaNetworkElementId=network_element_id,
                    OperationalName="NE-ROW-DUPLICATE",
                    ManufacturerSerial="ROW-DUPLICATE",
                    SomaSiteId=site_id,
                ),
            ),
            (
                "Network Elements",
                _values(
                    "Network Elements",
                    SomaNetworkElementId=network_element_id,
                    OperationalName="NE-ROW-DUPLICATE-CHANGED",
                    ManufacturerSerial="ROW-DUPLICATE",
                    SomaSiteId=site_id,
                ),
            ),
        ],
    )
    assert sorted(item["action"] for item in proposals) == [
        "unchanged",
        "update_network_element",
    ]

    command_id = new_uuid4()
    with pytest.raises(SomaError) as duplicate:
        service.execute(
            "AcceptInfrastructureWorkbookRun",
            command_id=command_id,
            payload={
                "run_id": run_id,
                "run_revision": 2,
                "run_input_fingerprint": logical,
                "dispositions": [
                    {
                        "proposal_id": proposal["proposal_id"],
                        "expected_revision": proposal["revision"],
                        "decision": "accept",
                        "proposal_fingerprint": proposal["fingerprint"],
                    }
                    for proposal in proposals
                ],
            },
        )
    assert duplicate.value.code == "WORKBOOK_RELATION_INVALID"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT operational_name,manufacturer_serial,revision "
            "FROM network_elements WHERE network_element_id=?",
            (network_element_id,),
        ).fetchone() == ("NE-ROW-DUPLICATE", "ROW-DUPLICATE", 1)
        assert snapshot.connection.execute(
            "SELECT state,revision FROM infrastructure_workbook_runs "
            "WHERE workbook_run_id=?",
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
