import pytest

from soma.communications.domain.matching import exact_identifier_occurrences


@pytest.mark.parametrize('identifier', ['12345678', 'NC20260101000000', 'TK20260101000000', 'MW-00000001', 'SPR-00000001', 'SR1234567', 'C1234567890', 'FT-00000001'])
def test_registered_identifier_boundaries_are_exact_and_case_sensitive(identifier):
    assert list(exact_identifier_occurrences('(' + identifier + ') ' + identifier, identifier)) == [1, len(identifier) + 3]
    for adjacent in ('a', 'Z', '0', '_', 'é', '\u0301', '\u203f', '\U0001e4d0'):
        assert list(exact_identifier_occurrences(adjacent + identifier, identifier)) == []
        assert list(exact_identifier_occurrences(identifier + adjacent, identifier)) == []
    if identifier.lower() != identifier:
        assert list(exact_identifier_occurrences(identifier.lower(), identifier)) == []
