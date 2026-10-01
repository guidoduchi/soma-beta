from __future__ import annotations

from collections.abc import Iterator

import unicodedata2

from soma.foundation.errors import ValidationError


def _blocks_boundary(character: str) -> bool:
    category = unicodedata2.category(character)
    return category[0] in "LMN" or category == "Pc"


def exact_identifier_occurrences(content: str, identifier: str) -> Iterator[int]:
    """Version-1 occurrence verification for an owner-registered candidate.

    This is the final boundary check after indexed candidate discovery, not a
    registry-by-message scan. No Unicode folding changes operational identity.
    """
    if not isinstance(content, str) or not isinstance(identifier, str) or not identifier:
        raise ValidationError("Exact matching requires source text and an accepted identifier")
    position = 0
    while (found := content.find(identifier, position)) != -1:
        end = found + len(identifier)
        if (found == 0 or not _blocks_boundary(content[found - 1])) and (end == len(content) or not _blocks_boundary(content[end])):
            yield found
        position = found + 1
