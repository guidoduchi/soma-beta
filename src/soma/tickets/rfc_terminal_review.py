from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import ValidationError

_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeExecutionReview:
    """Bounded reviewed authority carried from READY preview into execution."""

    preview_fingerprint: str
    task_objective_exact_count: int
    task_objective_provider_fingerprint: str
    communication_exact_count: int
    communication_provider_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.preview_fingerprint, str) or _SHA256_HEX_RE.fullmatch(self.preview_fingerprint) is None:
            raise ValidationError("terminal cascade execution review preview fingerprint must be lowercase SHA-256")
        if type(self.task_objective_exact_count) is not int or self.task_objective_exact_count < 0:
            raise ValidationError("terminal cascade execution review Task/Objective count must be a non-negative integer")
        if (
            not isinstance(self.task_objective_provider_fingerprint, str)
            or _SHA256_HEX_RE.fullmatch(self.task_objective_provider_fingerprint) is None
        ):
            raise ValidationError("terminal cascade execution review Task/Objective fingerprint must be lowercase SHA-256")
        if type(self.communication_exact_count) is not int or self.communication_exact_count < 0:
            raise ValidationError("terminal cascade execution review Communication count must be a non-negative integer")
        if (
            not isinstance(self.communication_provider_fingerprint, str)
            or _SHA256_HEX_RE.fullmatch(self.communication_provider_fingerprint) is None
        ):
            raise ValidationError("terminal cascade execution review Communication fingerprint must be lowercase SHA-256")

    def to_response(self) -> dict[str, Any]:
        return {
            "preview_fingerprint": self.preview_fingerprint,
            "task_objective_exact_count": self.task_objective_exact_count,
            "task_objective_provider_fingerprint": self.task_objective_provider_fingerprint,
            "communication_exact_count": self.communication_exact_count,
            "communication_provider_fingerprint": self.communication_provider_fingerprint,
        }
