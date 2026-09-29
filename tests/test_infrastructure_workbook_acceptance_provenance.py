from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from test_infrastructure_workbook_acceptance import (
    _accept,
    _assembled,
    _network_element,
    _seed_staged_run,
    _values,
)


def test_workbook_relationship_changes_record_reviewed_reason(
    initialized_database,
) -> None:
    factory, service, site_id, data_instance_id = _assembled(initialized_database)
    network_element_id = _network_element(
        service,
        site_id,
        name="NE-RELATION-REVIEW",
    )
    model_id = service.execute(
        "CreateNetworkElementModel",
        command_id=new_uuid4(),
        payload={"name": "Workbook model"},
    ).response["target"]["id"]
    cloud_type_id = service.execute(
        "CreateCloudType",
        command_id=new_uuid4(),
        payload={"name": "Workbook cloud type"},
    ).response["target"]["id"]
    cloud_deployment_id = service.execute(
        "CreateCloudDeployment",
        command_id=new_uuid4(),
        payload={
            "site_id": site_id,
            "cloud_type_id": cloud_type_id,
            "name": "Workbook cloud",
        },
    ).response["target"]["id"]

    run_id, logical, proposals = _seed_staged_run(
        factory,
        data_instance_id,
        [
            (
                "Network Elements",
                _values(
                    "Network Elements",
                    SomaNetworkElementId=network_element_id,
                    OperationalName="NE-RELATION-REVIEW",
                    SomaSiteId=site_id,
                    SomaModelId=model_id,
                    SomaCloudDeploymentId=cloud_deployment_id,
                ),
            ),
        ],
    )
    assert proposals[0]["action"] == "relationship_change"

    _command_id, execution = _accept(service, run_id, logical, proposals)
    assert execution.response["state"] == "accepted"
    assert execution.response["updated"] == 1

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT reason_code FROM network_element_model_assignment_events "
            "WHERE network_element_id=? ORDER BY recorded_at_utc DESC LIMIT 1",
            (network_element_id,),
        ).fetchone() == ("WORKBOOK_REVIEWED",)
        assert snapshot.connection.execute(
            "SELECT reason_code FROM cloud_assignment_events "
            "WHERE network_element_id=? ORDER BY recorded_at_utc DESC LIMIT 1",
            (network_element_id,),
        ).fetchone() == ("WORKBOOK_REVIEWED",)
