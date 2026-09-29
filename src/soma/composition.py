from __future__ import annotations

from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.services.participants import InventoryReferenceDependencyValidator
from soma.objectives_tasks.startup_integrity import verify_objectives_tasks_startup_integrity
from soma.reference.application.lifecycle_service import ReferenceLifecycleService
from soma.reference.domain.dependencies import ReferenceDependencyRegistry

_PRE_LLD08_REFERENCE_DEPENDENCY_VALIDATORS = ("inventory",)


def build_pre_lld08_reference_dependency_registry() -> ReferenceDependencyRegistry:
    """Assemble the complete LLD-01..07 Reference dependency set.

    This composition deliberately stops before LLD-08. Test-only callers that
    need no owner dependencies may still use ReferenceDependencyRegistry's
    isolated_for_tests seam, but application assembly must declare the required
    owner providers explicitly.
    """

    registry = ReferenceDependencyRegistry()
    registry.register(InventoryReferenceDependencyValidator())
    registry.finalize(
        required_validator_ids=_PRE_LLD08_REFERENCE_DEPENDENCY_VALIDATORS,
    )
    return registry


def build_pre_lld08_reference_lifecycle_service(
    connection_factory: ConnectionFactory,
) -> ReferenceLifecycleService:
    return ReferenceLifecycleService(
        connection_factory,
        build_pre_lld08_reference_dependency_registry(),
    )


def build_pre_lld08_startup_reconciler(
    connection_factory: ConnectionFactory,
):
    """Compose read-only LLD-01..07 startup integrity validation.

    Foundation owns schema/foreign-key/append-only verification. Owner-domain
    checks that need live authoritative data remain here so the generic host
    does not acquire packet-specific semantics.
    """

    def reconcile(_run_id: str, _now_utc: int) -> None:
        with ReadSnapshot(connection_factory) as snapshot:
            verify_objectives_tasks_startup_integrity(snapshot.connection)

    return reconcile


__all__ = [
    "build_pre_lld08_reference_dependency_registry",
    "build_pre_lld08_reference_lifecycle_service",
    "build_pre_lld08_startup_reconciler",
]
