from __future__ import annotations

from types import SimpleNamespace

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.infrastructure.services.components import validate_consequence


class DeclaredInventoryConsequenceReader:
    def __init__(self, task_id: str, fingerprint: str) -> None:
        self.task_id = task_id
        self.fingerprint = fingerprint

    def validate_current(self, uow, physical_consequence_id, expected_fingerprint):
        del uow, physical_consequence_id
        return "VALID" if expected_fingerprint == self.fingerprint else "STALE"

    def get_current(self, uow, physical_consequence_id):
        del uow, physical_consequence_id
        return {"task_id": self.task_id}


def test_component_consequence_validation_uses_only_declared_inventory_reader_contract():
    task_id = new_uuid4()
    consequence_id = new_uuid4()
    fingerprint = "a" * 64
    provider = DeclaredInventoryConsequenceReader(task_id, fingerprint)
    service = SimpleNamespace(consequence_reader=provider)

    validate_consequence(
        service,
        object(),
        {
            "physical_consequence_id": consequence_id,
            "physical_consequence_fingerprint": fingerprint,
            "task_id": task_id,
            "action": "installed",
        },
        new_uuid4(),
        required=True,
    )

    with pytest.raises(SomaError) as stale:
        validate_consequence(
            service,
            object(),
            {
                "physical_consequence_id": consequence_id,
                "physical_consequence_fingerprint": fingerprint,
                "task_id": new_uuid4(),
                "action": "installed",
            },
            new_uuid4(),
            required=True,
        )
    assert stale.value.code == "PHYSICAL_CONSEQUENCE_STALE"
