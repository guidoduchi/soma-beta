import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.queries.core import InfrastructureQueries
from soma.infrastructure.services.placement import placement_fingerprint
from soma.infrastructure.services.relationships import primary_fingerprint
from test_infrastructure_services import infra, command, site


def element(service, site_id, **options):
    return command(service, "CreateNetworkElement", new_element=dict(site_id=site_id, operational_name="Node", **options))["target"]["id"]


def test_create_element_atomic_children_and_occupancy(infra):
    service, factory, customer = infra
    site_id = site(service, customer)
    room = command(service, "CreateRoom", site_id=site_id, name="Room")["target"]["id"]
    rack = command(service, "CreateRack", room_id=room, name="Rack", height_u=42)["target"]["id"]
    first = element(service, site_id, placement=dict(rack_id=rack, u_start=1, u_span=3))
    second = element(service, site_id, placement=dict(rack_id=rack, u_start=4, u_span=3))
    with pytest.raises(SomaError) as error:
        element(service, site_id, placement=dict(rack_id=rack, u_start=3, u_span=2))
    assert error.value.code == "RACK_U_OCCUPIED"
    with ReadSnapshot(factory) as reader:
        assert reader.connection.execute("SELECT count(*) FROM network_elements").fetchone()[0] == 2
    queries = InfrastructureQueries(service)
    occupied = queries.execute("RackOccupancyQuery", dict(rack_id=rack))
    assert not occupied["corrupt_overlap_detected"]
    assert occupied["free_ranges"] == [dict(u_start=7, u_span=36)]
    assert queries.execute("NetworkElementDetailQuery", dict(network_element_id=first))["placement"]["rack_id"] == rack


def test_containment_does_not_move_placement_and_cycles_fail(infra):
    service, factory, customer = infra
    site_id = site(service, customer)
    first, second, third = [element(service, site_id) for _ in range(3)]
    command(service, "SetContainmentParent", child_network_element_id=first, parent_network_element_id=second,
            base_revision=0, reason_code="reviewed")
    command(service, "SetContainmentParent", child_network_element_id=second, parent_network_element_id=third,
            base_revision=0, reason_code="reviewed")
    with pytest.raises(SomaError) as error:
        command(service, "SetContainmentParent", child_network_element_id=third, parent_network_element_id=first,
                base_revision=0, reason_code="reviewed")
    assert error.value.code == "CONTAINMENT_CYCLE"
    result = InfrastructureQueries(service).execute("NetworkElementDetailQuery", dict(network_element_id=first))
    assert result["placement"]["explicit_unracked"]
    assert result["containment_parent"]["id"] == second


def test_ip_primary_correction_replay_and_duplicates(infra):
    service, factory, customer = infra
    first = element(service, site(service, customer))
    ip1 = command(service, "AddNetworkElementIp", network_element_id=first,
                  address="2001:0DB8::1", make_primary=True)["target"]["id"]
    ip2 = command(service, "AddNetworkElementIp", network_element_id=first,
                  address="192.0.2.1", make_primary=False)["target"]["id"]
    with pytest.raises(SomaError) as error:
        command(service, "AddNetworkElementIp", network_element_id=first, address="2001:db8::1", make_primary=False)
    assert error.value.code == "IP_DUPLICATE_ON_ELEMENT"
    with ReadSnapshot(factory) as snapshot:
        token = primary_fingerprint(snapshot, first)
    command(service, "SetPrimaryNetworkElementIp", network_element_id=first, ip_id=ip2, ip_revision=1,
            primary_set_fingerprint=token)
    command(service, "CorrectNetworkElementIp", ip_id=ip2, base_revision=2, action="remove", reason_code="removed")
    detail = InfrastructureQueries(service).execute("NetworkElementDetailQuery", dict(network_element_id=first))
    assert detail["primary_ip"] is None and detail["ip_count"] == 1


def test_components_preserve_replacement_identity_and_slot_history(infra):
    service, factory, customer = infra
    node = element(service, site(service, customer))
    first = command(service, "RegisterInstalledComponent", network_element_id=node, origin="manual",
                    bom_code="BOM-1", slot_label="slot 1")["target"]["id"]
    with pytest.raises(SomaError) as error:
        command(service, "RegisterInstalledComponent", network_element_id=node, origin="manual", slot_label="SLOT 1")
    assert error.value.code == "COMPONENT_SLOT_OCCUPIED"
    command(service, "RecordInstalledComponentLifecycle", installed_component_id=first, base_revision=1,
            action="removed", reason_code="replacement")
    second = command(service, "RegisterInstalledComponent", network_element_id=node, origin="manual",
                     bom_code="BOM-1", slot_label="slot 1")["target"]["id"]
    assert first != second
    with ReadSnapshot(factory) as reader:
        assert reader.connection.execute("SELECT count(*) FROM installed_components").fetchone()[0] == 2
        assert reader.connection.execute("SELECT count(*) FROM installed_component_events").fetchone()[0] == 3


def test_explorer_cursor_is_bound_to_filter(infra):
    service, factory, customer = infra
    first, second = site(service, customer), site(service, customer)
    queries = InfrastructureQueries(service)
    page = queries.execute("InfrastructureExplorerQuery", dict(node_kind="site", limit=1))
    assert page["next_cursor"]
    other = queries.execute("InfrastructureExplorerQuery", dict(node_kind="site", limit=1, cursor=page["next_cursor"]))
    assert page["nodes"][0]["id"] != other["nodes"][0]["id"]
    with pytest.raises(SomaError) as error:
        queries.execute("InfrastructureExplorerQuery", dict(node_kind="room", cursor=page["next_cursor"]))
    assert error.value.code == "CURSOR_INVALID"


def test_cross_element_duplicate_ip_is_allowed_and_warned(infra):
    service, _factory, customer = infra
    site_id = site(service, customer)
    first = element(service, site_id)
    second = element(service, site_id)

    first_ip = command(
        service,
        "AddNetworkElementIp",
        network_element_id=first,
        address="2001:0db8:0:0::42",
        make_primary=False,
    )["target"]["id"]
    second_ip = command(
        service,
        "AddNetworkElementIp",
        network_element_id=second,
        address="2001:db8::42",
        make_primary=False,
    )["target"]["id"]
    assert first_ip != second_ip

    queries = InfrastructureQueries(service)
    candidates = queries.execute(
        "IpCandidateQuery",
        {"canonical_address": "2001:db8::42"},
    )
    assert candidates["exact_count"] == 2
    assert {
        (item["network_element_id"], item["network_element_ip_id"])
        for item in candidates["items"]
    } == {
        (first, first_ip),
        (second, second_ip),
    }

    first_detail = queries.execute(
        "NetworkElementDetailQuery",
        {"network_element_id": first},
    )
    second_detail = queries.execute(
        "NetworkElementDetailQuery",
        {"network_element_id": second},
    )
    assert first_detail["warning_codes"] == [
        "IP_DUPLICATE_ACROSS_NETWORK_ELEMENTS"
    ]
    assert second_detail["warning_codes"] == [
        "IP_DUPLICATE_ACROSS_NETWORK_ELEMENTS"
    ]
