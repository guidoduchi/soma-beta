from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.infrastructure.queries.core import InfrastructureQueries
from soma.infrastructure.services.core import InfrastructureService
from soma.reference.application.customer_service import CustomerReferenceService
from test_infrastructure_relationships import element
from test_infrastructure_services import command, site


def _infra(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    service = InfrastructureService(factory)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Infrastructure certification customer",
    ).customer_org_id
    return service, factory, customer


def test_cloud_type_reuse_assignment_is_site_scoped_and_lifecycle_guarded(
    initialized_database,
):
    service, _factory, customer = _infra(initialized_database)
    first_site = site(service, customer)
    second_site = site(service, customer)
    cloud_type = command(
        service,
        "CreateCloudType",
        name="Private Cloud",
    )["target"]["id"]
    first_deployment = command(
        service,
        "CreateCloudDeployment",
        site_id=first_site,
        cloud_type_id=cloud_type,
        name="Cloud A",
    )["target"]["id"]
    second_deployment = command(
        service,
        "CreateCloudDeployment",
        site_id=second_site,
        cloud_type_id=cloud_type,
        name="Cloud B",
    )["target"]["id"]
    node = element(service, first_site)

    assigned = command(
        service,
        "SetCloudDeploymentAssignment",
        network_element_id=node,
        base_revision=0,
        cloud_deployment_id=first_deployment,
        reason_code="reviewed_assignment",
    )
    assert assigned["revision"] == 1
    detail = InfrastructureQueries(service).execute(
        "NetworkElementDetailQuery",
        {"network_element_id": node},
    )
    assert detail["cloud_deployment"] == {
        "kind": "cloud_deployment",
        "id": first_deployment,
    }
    assert detail["placement"]["explicit_unracked"]

    with pytest.raises(SomaError) as cross_site:
        command(
            service,
            "SetCloudDeploymentAssignment",
            network_element_id=node,
            base_revision=1,
            cloud_deployment_id=second_deployment,
            reason_code="wrong_site",
        )
    assert cross_site.value.code == "CLOUD_CROSS_SITE"

    with pytest.raises(SomaError) as assigned_archive:
        command(
            service,
            "ChangeCloudDeploymentLifecycle",
            cloud_deployment_id=first_deployment,
            base_revision=1,
            target_state="archived",
            reason_code="retire",
        )
    assert assigned_archive.value.code == "INFRA_STALE"

    cleared = command(
        service,
        "SetCloudDeploymentAssignment",
        network_element_id=node,
        base_revision=1,
        reason_code="reviewed_clear",
    )
    assert cleared["revision"] == 2
    archived = command(
        service,
        "ChangeCloudDeploymentLifecycle",
        cloud_deployment_id=first_deployment,
        base_revision=1,
        target_state="archived",
        reason_code="retire",
    )
    assert archived["revision"] == 2

    with pytest.raises(SomaError) as archived_target:
        command(
            service,
            "SetCloudDeploymentAssignment",
            network_element_id=node,
            base_revision=0,
            cloud_deployment_id=first_deployment,
            reason_code="must_fail",
        )
    assert archived_target.value.code == "INFRA_STALE"


def test_model_archive_preserves_existing_relations_but_blocks_new_active_use(
    initialized_database,
):
    service, _factory, customer = _infra(initialized_database)
    site_id = site(service, customer)
    first = element(service, site_id)
    second = element(service, site_id)
    model = command(
        service,
        "CreateNetworkElementModel",
        name="Model X",
        manufacturer="Vendor",
    )["target"]["id"]
    relation_id = new_uuid4()

    assignment = command(
        service,
        "SetNetworkElementModel",
        network_element_id=first,
        base_revision=0,
        model_id=model,
        reason_code="reviewed_assignment",
    )
    assert assignment["revision"] == 1
    compatibility = command(
        service,
        "ChangeModelBomCompatibility",
        model_id=model,
        relation_id=relation_id,
        base_revision=0,
        action="add",
        bom_code="BOM-X",
        component_role="controller",
        reason_code="reviewed_add",
    )
    assert compatibility["revision"] == 1

    before = InfrastructureQueries(service).execute(
        "ModelDetailQuery",
        {"model_id": model},
    )
    assert before["compatibility_count"] == 1
    assert before["assigned_network_element_count"] == 1

    archived = command(
        service,
        "ChangeNetworkElementModelLifecycle",
        model_id=model,
        base_revision=1,
        target_state="archived",
        reason_code="retired_model",
    )
    assert archived["revision"] == 2

    after = InfrastructureQueries(service).execute(
        "ModelDetailQuery",
        {"model_id": model},
    )
    assert after["lifecycle"] == "archived"
    assert after["compatibility_count"] == 1
    assert after["assigned_network_element_count"] == 1
    first_detail = InfrastructureQueries(service).execute(
        "NetworkElementDetailQuery",
        {"network_element_id": first},
    )
    assert first_detail["model"] == {"kind": "model", "id": model}

    with pytest.raises(SomaError) as archived_assignment:
        command(
            service,
            "SetNetworkElementModel",
            network_element_id=second,
            base_revision=0,
            model_id=model,
            reason_code="must_fail",
        )
    assert archived_assignment.value.code == "MODEL_ARCHIVED"

    with pytest.raises(SomaError) as archived_add:
        command(
            service,
            "ChangeModelBomCompatibility",
            model_id=model,
            relation_id=new_uuid4(),
            base_revision=0,
            action="add",
            bom_code="BOM-Y",
            reason_code="must_fail",
        )
    assert archived_add.value.code == "MODEL_ARCHIVED"

    removed = command(
        service,
        "ChangeModelBomCompatibility",
        model_id=model,
        relation_id=relation_id,
        base_revision=1,
        action="remove",
        bom_code="BOM-X",
        component_role="controller",
        reason_code="retired_relation",
    )
    assert removed["revision"] == 2
    final = InfrastructureQueries(service).execute(
        "ModelDetailQuery",
        {"model_id": model},
    )
    assert final["compatibility_count"] == 0
    assert final["assigned_network_element_count"] == 1
