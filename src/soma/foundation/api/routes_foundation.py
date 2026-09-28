from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from soma.foundation.contracts.foundation import MigrationStatus
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.queries.status import FoundationStatusQueries
from soma.foundation.runtime.host import HostRuntime


class RunControlContext(Protocol):
    run_id: str
    data_instance_id: str


class RunControlProvider(Protocol):
    def authenticate_control_request(
        self,
        headers: Any,
        expected_run_id: str,
    ) -> RunControlContext: ...


class SessionSecurityProvider(Protocol):
    def validate_request(self, request: Any, *, mutation: bool) -> Any: ...


class FoundationRoutes:
    """Framework-neutral route handlers. Starlette adapters stay outside owner logic."""

    def __init__(
        self,
        *,
        runtime: HostRuntime,
        status_queries: FoundationStatusQueries,
        run_control: RunControlProvider,
        session_security: SessionSecurityProvider,
    ) -> None:
        self._runtime = runtime
        self._status = status_queries
        self._run_control = run_control
        self._session = session_security

    def _run_context(self, headers: Any) -> RunControlContext:
        health = self._runtime.health()
        context = self._run_control.authenticate_control_request(
            headers,
            health.run_id,
        )
        if (
            context.run_id != health.run_id
            or context.data_instance_id != health.data_instance_id
        ):
            raise SomaError("FORBIDDEN", "run-control identity does not match current host")
        return context

    def get_runtime_health(self, *, headers: Any) -> dict[str, object]:
        self._run_context(headers)
        return asdict(self._status.get_runtime_health())

    def shutdown_host(
        self,
        *,
        headers: Any,
        body: object,
    ) -> dict[str, object]:
        context = self._run_context(headers)
        if not isinstance(body, dict) or set(body) != {
            "run_id",
            "data_instance_id",
            "command_id",
        }:
            raise ValidationError("shutdown request fields are invalid")
        run_id = body["run_id"]
        data_instance_id = body["data_instance_id"]
        command_id = body["command_id"]
        if not all(isinstance(value, str) for value in (run_id, data_instance_id, command_id)):
            raise ValidationError("shutdown request identities must be strings")
        require_uuid4(run_id)
        require_uuid4(data_instance_id)
        require_uuid4(command_id)
        if run_id != context.run_id or data_instance_id != context.data_instance_id:
            raise SomaError("FORBIDDEN", "shutdown request identity is not authenticated")
        return asdict(
            self._runtime.request_shutdown(
                command_id=command_id,
                run_id=run_id,
                data_instance_id=data_instance_id,
            )
        )

    def get_foundation_diagnostics(self, *, request: Any) -> dict[str, object]:
        self._session.validate_request(request, mutation=False)
        return asdict(self._status.get_foundation_diagnostics_state())

    def get_live_migration_status(self, *, request: Any) -> dict[str, object]:
        self._session.validate_request(request, mutation=False)
        health = self._status.get_runtime_health()
        target = self._runtime.target_migration_sequence
        state = "LIVE_CURRENT" if health.migration_sequence == target else "LIVE_MIGRATIONS_PENDING"
        return asdict(
            MigrationStatus(
                state=state,  # type: ignore[arg-type]
                current_sequence=health.migration_sequence,
                current_migration_id=health.migration_id,
                target_sequence=target,
                integrity_state=health.integrity_state,
            )
        )
