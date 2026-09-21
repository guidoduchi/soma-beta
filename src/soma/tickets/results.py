from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandExecutionResult
from soma.foundation.errors import IntegrityFailure


@dataclass(frozen=True, slots=True)
class TicketMutationResult:
    outcome: str
    target_id: str
    revision: int
    replayed: bool

    @property
    def no_change(self) -> bool:
        return self.outcome == "NO_CHANGE"


def ticket_mutation_result_from_execution(result: CommandExecutionResult) -> TicketMutationResult:
    if (
        result.response_schema != "TicketMutationResultV1"
        or result.response_version != 1
        or not isinstance(result.response, dict)
    ):
        raise IntegrityFailure("ticket mutation replay result has the wrong response contract")
    outcome = result.response.get("outcome")
    target_id = result.response.get("target_id")
    revision = result.response.get("revision")
    if outcome not in {"APPLIED", "NO_CHANGE"}:
        raise IntegrityFailure("ticket mutation replay result has invalid outcome")
    if not isinstance(target_id, str) or type(revision) is not int or revision <= 0:
        raise IntegrityFailure("ticket mutation replay result has invalid target metadata")
    return TicketMutationResult(
        outcome=str(outcome),
        target_id=target_id,
        revision=revision,
        replayed=result.replayed,
    )
