from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.infrastructure.queries.core import InfrastructureQueries
from test_infrastructure_relationships import element
from test_infrastructure_services import command, infra, site


def test_installed_component_query_uses_slot_nulls_last_keyset_cursor(infra):
    service, _factory, customer = infra
    node = element(service, site(service, customer))

    unslotted_a = command(
        service,
        "RegisterInstalledComponent",
        network_element_id=node,
        origin="manual",
        bom_code="BOM-U-A",
    )["target"]["id"]
    slotted_b = command(
        service,
        "RegisterInstalledComponent",
        network_element_id=node,
        origin="manual",
        bom_code="BOM-S-B",
        slot_label="Slot B",
    )["target"]["id"]
    slotted_a = command(
        service,
        "RegisterInstalledComponent",
        network_element_id=node,
        origin="manual",
        bom_code="BOM-S-A",
        slot_label="Slot A",
    )["target"]["id"]
    unslotted_b = command(
        service,
        "RegisterInstalledComponent",
        network_element_id=node,
        origin="manual",
        bom_code="BOM-U-B",
    )["target"]["id"]

    queries = InfrastructureQueries(service)
    first = queries.execute(
        "InstalledComponentQuery",
        {"network_element_id": node, "limit": 3},
    )
    assert [item["installed_component_id"] for item in first["items"][:2]] == [
        slotted_a,
        slotted_b,
    ]
    assert first["items"][2]["installed_component_id"] in {
        unslotted_a,
        unslotted_b,
    }
    assert first["next_cursor"] is not None
    assert first["next_cursor"]["last_key_tuple"][0] is None

    second = queries.execute(
        "InstalledComponentQuery",
        {
            "network_element_id": node,
            "limit": 3,
            "cursor": first["next_cursor"],
        },
    )
    assert second["next_cursor"] is None
    all_ids = [
        *(item["installed_component_id"] for item in first["items"]),
        *(item["installed_component_id"] for item in second["items"]),
    ]
    assert len(all_ids) == 4
    assert len(set(all_ids)) == 4
    assert set(all_ids) == {
        unslotted_a,
        slotted_a,
        slotted_b,
        unslotted_b,
    }
