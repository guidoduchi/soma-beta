from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from soma.foundation.errors import IntegrityFailure

_STRONG_RE = re.compile(r"(?<![A-Za-z0-9])(?:SR|TT)[ \t]*([0-9]{8})(?![A-Za-z0-9])", re.IGNORECASE)
_WEAK_RE = re.compile(r"(?<![A-Za-z0-9])([0-9]{8})(?![A-Za-z0-9])")


@dataclass(frozen=True, slots=True)
class SrCandidateMention:
    official_sr_no: str
    strength: str
    mention_count: int


def _valid_date_token(token: str) -> bool:
    if len(token) != 8 or not token.isascii() or not token.isdigit():
        return False
    candidates = (
        (int(token[0:4]), int(token[4:6]), int(token[6:8])),
        (int(token[4:8]), int(token[2:4]), int(token[0:2])),
        (int(token[4:8]), int(token[0:2]), int(token[2:4])),
    )
    for year, month, day in candidates:
        try:
            date(year, month, day)
        except ValueError:
            continue
        return True
    return False


def extract_sr_candidates(text: str) -> tuple[SrCandidateMention, ...]:
    if not isinstance(text, str) or "\x00" in text:
        raise IntegrityFailure("RFC Summary candidate source is invalid text")
    counts: dict[str, int] = {}
    strengths: dict[str, str] = {}
    strong_digit_spans: list[tuple[int, int]] = []
    for match in _STRONG_RE.finditer(text):
        token = match.group(1)
        strong_digit_spans.append(match.span(1))
        counts[token] = counts.get(token, 0) + 1
        strengths[token] = "strong"
    for match in _WEAK_RE.finditer(text):
        span = match.span(1)
        if any(span[0] < strong_end and strong_start < span[1] for strong_start, strong_end in strong_digit_spans):
            continue
        token = match.group(1)
        if _valid_date_token(token):
            continue
        counts[token] = counts.get(token, 0) + 1
        strengths.setdefault(token, "weak")
    return tuple(
        SrCandidateMention(
            official_sr_no=token,
            strength=strengths[token],
            mention_count=counts[token],
        )
        for token in sorted(counts)
    )
