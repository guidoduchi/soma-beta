from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.tickets.rfc_terminal_cascade import (
    RfcTerminalCascadeCaptureService,
    RfcTerminalCascadeRfcMember,
    RfcTerminalCascadeWfmMember,
)


@dataclass(frozen=True, slots=True)
class _ConnectionContext:
    """Minimal adapter for the capture owner's read-only scope helpers."""

    connection: Any


def resolve_terminal_cascade_rfc_scope(
    connection: Any,
    *,
    trigger_rfc_id: str,
) -> tuple[str, tuple[RfcTerminalCascadeRfcMember, ...]]:
    """Reuse the capture owner's exact RFC hierarchy/revision scope over any stable reader."""

    return RfcTerminalCascadeCaptureService._capture_rfc_scope(  # noqa: SLF001 - one internal authority
        _ConnectionContext(connection),
        trigger_rfc_id=trigger_rfc_id,
    )


def normalize_terminal_cascade_wfm_members(
    raw_members: object,
    *,
    rfc_ids: tuple[str, ...],
) -> tuple[RfcTerminalCascadeWfmMember, ...]:
    """Reuse the capture owner's exact WFM validation/order contract for snapshot reads."""

    return RfcTerminalCascadeCaptureService._normalize_wfm_members(  # noqa: SLF001 - one internal authority
        raw_members,
        rfc_ids=rfc_ids,
    )
