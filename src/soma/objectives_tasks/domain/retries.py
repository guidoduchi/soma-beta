from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4


@dataclass(frozen=True, slots=True)
class InventoryRetryCloneCommandContextV1:
    command_id: str
    actor_kind: str
    actor_id: str | None = None

    def normalized(self) -> dict[str, object]:
        command_id = require_uuid4(self.command_id)
        if not isinstance(self.actor_kind, str) or not self.actor_kind:
            raise ValidationError("actor_kind is required")
        if self.actor_id is not None and not isinstance(self.actor_id, str):
            raise ValidationError("actor_id must be text or null")
        return {
            "command_id": command_id,
            "actor_kind": self.actor_kind,
            "actor_id": self.actor_id,
        }


__all__ = ["InventoryRetryCloneCommandContextV1"]
