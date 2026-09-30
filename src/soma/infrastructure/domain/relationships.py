from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import ip_address

from soma.foundation.errors import SomaError

CONTAINMENT_HARD_DEPTH = 1024


@dataclass(frozen=True, slots=True)
class NormalizedIp:
    family: int
    canonical_text: str


def normalize_ip(value: str) -> NormalizedIp:
    """Normalize host text without inferring identity, topology or reachability."""
    if not isinstance(value, str):
        raise SomaError("IP_INVALID", "IP address must be text")
    value = value.strip()
    if not value or "%" in value:
        raise SomaError("IP_INVALID", "Empty or scoped IP addresses are unsupported")
    try:
        parsed = ip_address(value)
    except ValueError as exc:
        raise SomaError("IP_INVALID", "Invalid IPv4 or IPv6 host address") from exc
    return NormalizedIp(parsed.version, parsed.compressed.lower())


def validate_containment_parent(
    child_id: str,
    proposed_parent_id: str | None,
    read_current_parent: Callable[[str], str | None],
) -> None:
    """Walk current ancestry; callers must re-run inside the writer transaction.

    The reader must distinguish a proven root (None) from an unavailable/missing
    node (exception). It must use indexed point reads in the caller's snapshot.
    Entity eligibility and revision checks belong to the owning service.
    """
    if proposed_parent_id is None:
        return
    if proposed_parent_id == child_id:
        raise SomaError("CONTAINMENT_SELF", "Network Element cannot contain itself")
    visited: set[str] = set()
    current = proposed_parent_id
    while current is not None:
        if current == child_id:
            raise SomaError("CONTAINMENT_CYCLE", "Proposed parent creates a containment cycle")
        if current in visited or len(visited) >= CONTAINMENT_HARD_DEPTH:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE", "Containment ancestry is corrupt or exceeds its bound"
            )
        visited.add(current)
        try:
            parent = read_current_parent(current)
        except Exception as exc:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE", "Current containment ancestry is unavailable"
            ) from exc
        if parent is not None and (not isinstance(parent, str) or not parent):
            raise SomaError("DEPENDENCY_INDETERMINATE", "Current containment parent is invalid")
        current = parent
