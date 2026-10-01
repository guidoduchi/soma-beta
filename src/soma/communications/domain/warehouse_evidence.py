"""Optional return-batch context, never item identity or final disposition."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from soma.foundation.errors import ValidationError

from soma.communications.contracts.message import TransientMessage
from soma.communications.domain.matching import _blocks_boundary

_REFERENCE = re.compile(r"RT[0-9]{8}")


@dataclass(frozen=True, slots=True)
class WarehouseReceptionContext:
    state: str  # ABSENT, EXACT, AMBIGUOUS, INVALID
    reference: str | None = field(default=None, repr=False)

    @property
    def warning_code(self) -> str | None:
        """Missing batch evidence warns the reviewer; it does not block receipt.

        A batch reference cannot establish which individual items were received
        or accepted. Existing Inventory commands retain item-level authority.
        """
        return "WAREHOUSE_RETURN_BATCH_REFERENCE_MISSING" if self.state == "ABSENT" else None

    def __post_init__(self):
        if self.state not in {"ABSENT", "EXACT", "AMBIGUOUS", "INVALID"}:
            raise ValidationError("Warehouse reception context state is invalid")
        if (self.state == "EXACT") != (self.reference is not None):
            raise ValidationError("Warehouse reception context requires exact reference evidence")
        if self.reference is not None and not _valid_reference(self.reference):
            raise ValidationError("Warehouse reception reference is invalid")


def _valid_reference(value):
    if not isinstance(value, str) or _REFERENCE.fullmatch(value) is None:
        return False
    try:
        # Calendar validity only. Never export this date as event chronology.
        date(2000 + int(value[2:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def warehouse_reception_context(message: TransientMessage) -> WarehouseReceptionContext:
    """Recognize one exact RTYYMMDDxx in subject/body, including thread history.

    Repeated identical references coalesce. Different references make the whole
    message ambiguous; invalid calendar tokens fail closed. Memory holds at most
    one reference. Participant addresses and attachment names grant no context.
    This is optional corroborating input only: the caller must still resolve
    exact SR7/C10/items under Inventory authority. Missing RT context yields a
    warning and never prevents an operator from recording an exact item receipt.
    A reference or CLOSED wording cannot supply an accepted/rejected decision;
    final disposition requires the existing explicit owner confirmation.
    """
    if not isinstance(message, TransientMessage):
        raise ValidationError("Warehouse reception context requires a typed transient message")
    selected = None
    invalid = False
    for content in (message.subject, message.body):
        if not content:
            continue
        for match in _REFERENCE.finditer(content):
            start, end = match.span()
            if ((start and _blocks_boundary(content[start-1]))
                    or (end < len(content) and _blocks_boundary(content[end]))):
                continue
            token = match.group()
            if not _valid_reference(token):
                invalid = True
            elif selected is None:
                selected = token
            elif selected != token:
                return WarehouseReceptionContext("AMBIGUOUS")
    if invalid:
        return WarehouseReceptionContext("INVALID")
    return WarehouseReceptionContext("ABSENT") if selected is None else WarehouseReceptionContext("EXACT", selected)
