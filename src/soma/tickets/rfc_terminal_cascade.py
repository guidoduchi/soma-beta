from __future__ import annotations

from typing import Any

from soma.foundation.persistence.connections import ConnectionFactory

from ._rfc_terminal_cascade_state import *  # noqa: F403
from ._rfc_terminal_cascade_state import (
    RfcTerminalCascadeRefreshService as _RfcTerminalCascadeRefreshEngine,
    _request_uuid,
    _state_response,
    _state_result_from_execution,
)
from .rfc_terminal_review import RfcTerminalCascadeExecutionReview


class RfcTerminalCascadeRefreshService(_RfcTerminalCascadeRefreshEngine):
    """Canonical LLD-03 public owner for RFC terminal-cascade refresh."""


class RfcTerminalCascadeExecutionService:
    """Canonical LLD-03 public owner for reviewed RFC terminal-cascade execution."""

    __slots__ = ("_engine",)

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        task_participant: Any,
        communication_participant: Any,
        deliberate_action_proof_provider: Any,
    ) -> None:
        # Lazy import keeps the private execution engine free to depend on the
        # terminal-cascade preview query, which itself imports this public
        # owner surface for the shared persisted scope types.
        from ._rfc_terminal_cascade_execution import (
            RfcTerminalCascadeExecutionService as _ExecutionEngine,
        )

        self._engine = _ExecutionEngine(
            connection_factory,
            task_participant,
            communication_participant,
            deliberate_action_proof_provider,
        )

    def execute(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        execution_review: RfcTerminalCascadeExecutionReview,
        deliberate_action_proof: object,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcTerminalCascadeStateResult:  # noqa: F405
        return self._engine.execute(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=proposal_revision,
            execution_review=execution_review,
            deliberate_action_proof=deliberate_action_proof,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )
