from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.infrastructure.domain.workbook_normalization import (
    normalize_workbook_row, workbook_logical_fingerprint,
)


def test_logical_fingerprint_ignores_row_order_but_preserves_multiplicity():
    a = normalize_workbook_row("Network Elements", (None, "  Alpha  "), same_installation=True)
    b = normalize_workbook_row("Network Elements", (None, "Beta"), same_installation=True)
    kwargs = dict(mode="round_trip", source_installation_scope_id="12345678-1234-4234-8234-123456789abc",
                  export_scope={"scope_kind": "all"}, ip_rows=[])
    first = workbook_logical_fingerprint(network_rows=[a[1], b[1]], **kwargs)
    assert first == workbook_logical_fingerprint(network_rows=[b[1], a[1]], **kwargs)
    assert first != workbook_logical_fingerprint(network_rows=[a[1], a[1], b[1]], **kwargs)


def test_normalized_ip_and_foreign_id_are_provenance_not_local_identity():
    row, fingerprint = normalize_workbook_row(
        "IP Addresses", (" foreign-7 ", None, "  Name ", "2001:0DB8::1", True),
        same_installation=False,
    )
    assert len(fingerprint) == 64
    assert row["fields"]["SomaIpId"] == "foreign-7"
    assert row["fields"]["Address"] == "2001:db8::1"
    with pytest.raises(ValidationError):
        normalize_workbook_row(
            "IP Addresses", ("foreign-7", None, "Name", "192.0.2.1", False),
            same_installation=True,
        )


def test_normalized_rack_values_never_round_spreadsheet_text():
    with pytest.raises(ValidationError):
        normalize_workbook_row(
            "Network Elements", (None,) * 15 + ("1.5",), same_installation=True,
        )
