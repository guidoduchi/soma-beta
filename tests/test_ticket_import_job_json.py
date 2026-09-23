from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure
from soma.ticket_import.jobs._json import load_persisted_job_object


def test_persisted_job_object_loader_accepts_exact_canonical_object() -> None:
    assert load_persisted_job_object('{"a":1}', label="probe") == {"a": 1}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"a": 1}', "not canonical JSON"),
        ('[1]', "must be an object"),
        ('{"a":1,"a":2}', "not canonical JSON"),
    ],
)
def test_persisted_job_object_loader_preserves_integrity_errors(
    text: str,
    message: str,
) -> None:
    with pytest.raises(IntegrityFailure, match=message):
        load_persisted_job_object(text, label="probe")
