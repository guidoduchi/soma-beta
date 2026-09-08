from __future__ import annotations

import math

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.strict_json import (
    ObjectContract,
    canonical_json_bytes,
    loads_strict,
    sha256_canonical_json,
)


def test_strict_json_rejects_duplicate_keys() -> None:
    with pytest.raises(ValidationError):
        loads_strict('{"a":1,"a":2}')


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_strict_json_rejects_nonfinite(token: str) -> None:
    with pytest.raises(ValidationError):
        loads_strict('{"value":' + token + "}")


def test_canonical_json_is_order_independent_for_hashing() -> None:
    left = {"z": [2, 1], "a": {"x": "é"}}
    right = {"a": {"x": "é"}, "z": [2, 1]}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_canonical_json(left) == sha256_canonical_json(right)


def test_object_contract_rejects_unknown_and_missing_fields() -> None:
    contract = ObjectContract(
        name="ExampleV1",
        version=1,
        required_fields=frozenset({"id"}),
        allowed_fields=frozenset({"id", "label"}),
    )
    with pytest.raises(ValidationError):
        contract.validate({"label": "x"})
    with pytest.raises(ValidationError):
        contract.validate({"id": "x", "surprise": True})
    assert contract.validate({"id": "x", "label": "ok"})["id"] == "x"
