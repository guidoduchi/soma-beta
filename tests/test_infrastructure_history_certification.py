from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.infrastructure.queries.core import InfrastructureQueries
from test_infrastructure_regularization_contract import _assembled


def test_history_distinguishes_missing_local_target_from_empty_history(
    initialized_database,
) -> None:
    _factory, service, _provider, device, network_element_id = _assembled(
        initialized_database
    )
    queries = InfrastructureQueries(service)

    element_history = queries.execute(
        "InfrastructureHistoryQuery",
        {
            "target_kind": "network_element",
            "target_id": network_element_id,
        },
    )
    assert element_history["events"]

    with pytest.raises(SomaError) as missing:
        queries.execute(
            "InfrastructureHistoryQuery",
            {
                "target_kind": "network_element",
                "target_id": new_uuid4(),
            },
        )
    assert missing.value.code == "INFRA_NOT_FOUND"

    unresolved = queries.execute(
        "InfrastructureHistoryQuery",
        {
            "target_kind": "device_reference",
            "target_id": device.device_reference_id,
        },
    )
    assert unresolved == {"events": [], "next_cursor": None}

    with pytest.raises(SomaError) as missing_device:
        queries.execute(
            "InfrastructureHistoryQuery",
            {
                "target_kind": "device_reference",
                "target_id": new_uuid4(),
            },
        )
    assert missing_device.value.code == "INFRA_NOT_FOUND"
