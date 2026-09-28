from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.reference.domain import validation


def test_reference_bounds_are_field_specific_and_do_not_truncate() -> None:
    long_but_valid = "x" * 500
    stored, key = validation.validate_customer_name(long_but_valid)
    assert stored == long_but_valid
    assert key == long_but_valid
    assert len(stored) == 500

    multiline = "line one\r\nline two\rline three"
    assert validation.validate_standalone_address(multiline) == (
        "line one\nline two\nline three"
    )


def test_customer_name_overflow_rejects_before_matching_normalization(
    monkeypatch,
) -> None:
    called = False

    def forbidden_normalize(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("normalization must not run after raw bound failure")

    monkeypatch.setattr(validation, "normalize_match_key", forbidden_normalize)
    with pytest.raises(ValidationError, match="UTF-8 byte bound"):
        validation.validate_customer_name("x" * 1_025)
    assert called is False


def test_email_overflow_rejects_before_addr_spec_parser(monkeypatch) -> None:
    called = False

    def forbidden_address(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("email parser must not run after raw bound failure")

    monkeypatch.setattr(validation, "Address", forbidden_address)
    with pytest.raises(ValidationError, match="UTF-8 byte bound"):
        validation.validate_email_channel("x" * 2_049)
    assert called is False


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("x" * 8_193, "UTF-8 byte bound"),
        ("\n".join("x" for _ in range(33)), "32 lines"),
    ],
)
def test_dispatch_address_uses_independent_byte_and_line_bounds(
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        validation.validate_standalone_address(value)
