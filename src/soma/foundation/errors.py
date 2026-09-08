from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SomaError(Exception):
    """Stable application error with a transport-safe code."""

    code: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ValidationError(SomaError):
    def __init__(self, message: str) -> None:
        super().__init__("VALIDATION_FAILED", message)


class IdempotencyConflict(SomaError):
    def __init__(self, message: str = "command replay does not match committed receipt") -> None:
        super().__init__("IDEMPOTENCY_CONFLICT", message)


class IdempotencyResultUnavailable(SomaError):
    def __init__(
        self,
        message: str = "exact result for the committed legacy command is unavailable",
    ) -> None:
        super().__init__("IDEMPOTENCY_RESULT_UNAVAILABLE", message)


class IntegrityFailure(SomaError):
    def __init__(self, message: str = "authoritative integrity verification failed") -> None:
        super().__init__("INTEGRITY_FAILURE", message)


class PersistenceBusy(SomaError):
    def __init__(self, message: str = "authoritative writer is busy") -> None:
        super().__init__("PERSISTENCE_BUSY", message, retryable=True)


class PersistenceFailure(SomaError):
    def __init__(self, message: str) -> None:
        super().__init__("PERSISTENCE_FAILURE", message)


class PersistenceRollbackFailure(SomaError):
    def __init__(self, message: str) -> None:
        super().__init__("PERSISTENCE_ROLLBACK_FAILURE", message)


class PersistenceConnectionUnsafe(SomaError):
    def __init__(self, message: str) -> None:
        super().__init__("PERSISTENCE_CONNECTION_UNSAFE", message)


class SecurityNotReady(SomaError):
    def __init__(self, message: str) -> None:
        super().__init__("SECURITY_NOT_READY", message)


class MigrationError(SomaError):
    pass
