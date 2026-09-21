from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.ticket_import.commands.review_competing_attempt import _stored_review_uuid


def test_stored_review_uuid_accepts_canonical_uuid4() -> None:
    identity = new_uuid4()
    assert _stored_review_uuid(identity, label="counterpart Task identity") == identity


@pytest.mark.parametrize("value", ["not-a-uuid", "00000000-0000-0000-0000-000000000000", None, 7])
def test_stored_review_uuid_maps_malformed_persisted_binding_to_import_stale(value: object) -> None:
    with pytest.raises(SomaError) as caught:
        _stored_review_uuid(value, label="activity lineage identity")
    assert caught.value.code == "IMPORT_PROPOSAL_STALE"
