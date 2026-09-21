from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.reference.domain.matching import normalize_match_key, unicode_match_asset_metadata
from soma.reference.domain.validation import validate_email_channel


def test_unicode_match_v1_asset_is_pinned_to_unicode_17() -> None:
    metadata = unicode_match_asset_metadata()
    assert metadata["profile_id"] == "UNICODE_MATCH_V1"
    assert metadata["unicode_version"] == "17.0.0"
    assert metadata["asset_sha256"] == "ec78bcbdf7afa6621dfe342790227e052a55f5913395bc69d92b1bf910a76aca"
    assert len(metadata["casefold_sha256"]) == 64
    assert len(metadata["proplist_sha256"]) == 64


def test_unicode_match_v1_nfkc_whitespace_and_full_casefold() -> None:
    assert normalize_match_key("  ＦＵＳＳ\u00a0Straße  ", raw_max_utf8_bytes=1024) == "fuss strasse"
    assert normalize_match_key("İ", raw_max_utf8_bytes=16) == "i\u0307"


def test_unicode_match_v1_preserves_accents_and_punctuation() -> None:
    assert normalize_match_key("Éxample-Co.", raw_max_utf8_bytes=64) == "éxample-co."
    assert normalize_match_key("Example.Co", raw_max_utf8_bytes=64) != normalize_match_key(
        "Example-Co", raw_max_utf8_bytes=64
    )


def test_email_channel_uses_pinned_trim_without_network_validation() -> None:
    stored, key = validate_email_channel("\u00a0User.Name+tag@Example.COM\u3000")
    assert stored == "User.Name+tag@Example.COM"
    assert key == "user.name+tag@example.com"


@pytest.mark.parametrize(
    "value",
    ["a@example.com\r\nBcc:evil@example.com", "bad address", "\x00a@example.com"],
)
def test_email_channel_rejects_injection_and_invalid_addr_spec(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_email_channel(value)
