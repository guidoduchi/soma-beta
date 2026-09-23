from __future__ import annotations

from soma.foundation.persistence.connections import ConnectionFactory
from soma.inventory.services.participants import InventoryReferenceDependencyValidator
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


__all__ = [
    "build_pre_lld08_reference_dependency_registry",
    "build_pre_lld08_reference_lifecycle_service",
]
