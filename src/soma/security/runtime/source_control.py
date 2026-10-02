"""Private source adapter gate, not an implementation of RunControlProvider.

Do not consume Foundation V1 registry as LLD-12 V2 or substitute test security.
This module deliberately performs no process, filesystem, network or browser I/O.
"""
from dataclasses import dataclass
from enum import Enum


class SourceOutcome(str, Enum):
    DEPENDENCY_PENDING = "dependency_pending"


@dataclass(frozen=True, slots=True)
class SourceControlResult:
    outcome: SourceOutcome
    exit_code: int
    message: str


def source_action(action: str) -> SourceControlResult:
    if action not in {"run", "console", "stop"}:
        raise ValueError("unknown source runtime action")
    return SourceControlResult(
        SourceOutcome.DEPENDENCY_PENDING,
        20,
        f"SOMA source {action}: dependency_pending. No host was started, opened or stopped. "
        "Trusted runtime requires accepted Foundation Registry V1 / LLD-12 V2 reconciliation, "
        "Windows owner-only DPAPI/process verification, and real application/security composition. "
        "See docs/implementation/lld12_source_launchers.md. Do not delete runtime.json or kill Python processes.",
    )
