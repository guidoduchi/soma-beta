from __future__ import annotations

from ipaddress import ip_address

import pytest

from soma.foundation.errors import SomaError
from soma.infrastructure.domain.placement import (
    RackInterval,
    validate_rack_height,
    validate_rack_placement,
)
from soma.infrastructure.domain.relationships import normalize_ip, validate_containment_parent


@pytest.mark.parametrize(
    ("raw", "family", "canonical"),
    [
        (" 192.0.2.1\t", 4, "192.0.2.1"),
        ("2001:0DB8:0000:0000:0000:0000:0000:0001", 6, "2001:db8::1"),
        ("::ffff:192.0.2.1", 6, ip_address("::ffff:192.0.2.1").compressed),
        ("127.0.0.1", 4, "127.0.0.1"),
        ("fe80::1", 6, "fe80::1"),
    ],
)
def test_ip_host_canonicalization(raw, family, canonical):
    normalized = normalize_ip(raw)
    assert (normalized.family, normalized.canonical_text) == (family, canonical)


@pytest.mark.parametrize(
    "raw",
    ["", " ", "fe80::1%eth0", "fe80::1%1", "192.0.2.1/24", "010.0.0.1",
     "example.com", "192.0.2.999", "2001:::1", 1, True, None, b"192.0.2.1"],
)
def test_invalid_ip_inputs_have_owner_error(raw):
    with pytest.raises(SomaError) as error:
        normalize_ip(raw)
    assert error.value.code == "IP_INVALID"


@pytest.mark.parametrize("height", [1, 42, 120])
def test_rack_height_boundaries(height):
    assert validate_rack_height(height) == height
    RackInterval(height, 1).require_fits(height)


@pytest.mark.parametrize("height", [0, 121, True, 42.0, None])
def test_invalid_rack_heights(height):
    with pytest.raises(SomaError):
        validate_rack_height(height)


@pytest.mark.parametrize(("start", "span"), [(0, 1), (1, 0), (-1, 2), (True, 1), (1, 1.5)])
def test_invalid_u_geometry(start, span):
    with pytest.raises(SomaError) as error:
        RackInterval(start, span)
    assert error.value.code == "RACK_U_OUT_OF_RANGE"


def test_rack_overlap_and_adjacency():
    # LLD-08 A017-A019 geometry; database occupancy remains an integration obligation.
    candidate = RackInterval(4, 3)
    for other, expected in [(RackInterval(1, 3), False), (RackInterval(7, 2), False),
                            (RackInterval(3, 2), True), (RackInterval(6, 2), True),
                            (RackInterval(5, 1), True), (RackInterval(1, 10), True),
                            (RackInterval(4, 3), True)]:
        assert candidate.overlaps(other) is expected
        assert other.overlaps(candidate) is expected


def test_placement_site_and_capacity():
    values = dict(network_element_site_id="site-a", rack_site_id="site-a",
                  height_u=42, u_start=40, u_span=3)
    assert validate_rack_placement(**values) == RackInterval(40, 3)
    with pytest.raises(SomaError) as error:
        validate_rack_placement(**{**values, "rack_site_id": "site-b"})
    assert error.value.code == "PLACEMENT_CROSS_SITE"
    with pytest.raises(SomaError) as error:
        validate_rack_placement(**{**values, "u_span": 4})
    assert error.value.code == "RACK_U_OUT_OF_RANGE"


def test_height_reduction_checks_last_occupied_u():
    placement = RackInterval(40, 3)
    placement.require_fits(42)
    with pytest.raises(SomaError) as error:
        placement.require_fits(41)
    assert error.value.code == "RACK_U_OUT_OF_RANGE"


def test_clearing_parent_requires_no_ancestry_reads():
    def unexpected_read(_):
        pytest.fail("Clearing containment must not read ancestry")
    validate_containment_parent("child", None, unexpected_read)


@pytest.mark.parametrize(
    ("parent", "edges", "code"),
    [
        ("child", {}, "CONTAINMENT_SELF"),
        ("parent", {"parent": "ancestor", "ancestor": "child"}, "CONTAINMENT_CYCLE"),
        ("parent", {"parent": "ancestor", "ancestor": "parent"}, "DEPENDENCY_INDETERMINATE"),
        ("missing", {}, "DEPENDENCY_INDETERMINATE"),
        ("parent", {"parent": 123}, "DEPENDENCY_INDETERMINATE"),
    ],
)
def test_invalid_containment_fails_closed(parent, edges, code):
    with pytest.raises(SomaError) as error:
        validate_containment_parent("child", parent, edges.__getitem__)
    assert error.value.code == code


def test_containment_uses_fresh_reader_each_time():
    edges = {"parent": "root", "root": None}
    validate_containment_parent("child", "parent", edges.__getitem__)
    edges["root"] = "child"
    with pytest.raises(SomaError) as error:
        validate_containment_parent("child", "parent", edges.__getitem__)
    assert error.value.code == "CONTAINMENT_CYCLE"


@pytest.mark.parametrize("depth", [1024, 1025])
def test_containment_depth_is_iterative_and_bounded(depth):
    reads = []
    def read_parent(node):
        reads.append(node)
        index = int(node)
        return str(index + 1) if index + 1 < depth else None
    if depth == 1024:
        validate_containment_parent("child", "0", read_parent)
    else:
        with pytest.raises(SomaError) as error:
            validate_containment_parent("child", "0", read_parent)
        assert error.value.code == "DEPENDENCY_INDETERMINATE"
    assert len(reads) == 1024
