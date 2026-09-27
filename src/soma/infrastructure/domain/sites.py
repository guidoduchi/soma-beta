from soma.reference.domain.matching import normalize_match_key


def match_key(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_match_key(value, raw_max_utf8_bytes=3200, key_max_utf8_bytes=12800)
