from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandExecutionResult
from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4


@dataclass(frozen=True, slots=True)
class InventoryRef:
    type: str
    id: str


@dataclass(frozen=True, slots=True)
class InventoryMutationResult:
    outcome: str
    target_refs: tuple[InventoryRef, ...]
    revisions: dict[str, int]
    replayed: bool
    no_change: bool


def inventory_result_from_execution(result: CommandExecutionResult) -> InventoryMutationResult:
    if (
        result.response_schema != "InventoryMutationResultV1"
        or result.response_version != 1
        or not isinstance(result.response, dict)
        or set(result.response) != {"outcome", "target_refs", "revisions"}
    ):
        raise IntegrityFailure("Inventory mutation result contract is invalid")
    outcome = result.response["outcome"]
    raw_refs = result.response["target_refs"]
    raw_revisions = result.response["revisions"]
    if outcome not in {"APPLIED", "NO_CHANGE"}:
        raise IntegrityFailure("Inventory mutation outcome is invalid")
    if not isinstance(raw_refs, list) or len(raw_refs) > 512:
        raise IntegrityFailure("Inventory target refs are invalid")
    refs: list[InventoryRef] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_refs:
        if not isinstance(item, dict) or set(item) != {"type", "id"}:
            raise IntegrityFailure("Inventory target ref shape is invalid")
        ref_type = item["type"]
        ref_id = item["id"]
        if not isinstance(ref_type, str) or not ref_type:
            raise IntegrityFailure("Inventory target ref type is invalid")
        if not isinstance(ref_id, str):
            raise IntegrityFailure("Inventory target ref id is invalid")
        require_uuid4(ref_id)
        key = (ref_type, ref_id)
        if key in seen:
            raise IntegrityFailure("Inventory target refs contain duplicates")
        seen.add(key)
        refs.append(InventoryRef(ref_type, ref_id))
    if not isinstance(raw_revisions, dict) or len(raw_revisions) > 512:
        raise IntegrityFailure("Inventory revision map is invalid")
    revisions: dict[str, int] = {}
    for key, value in raw_revisions.items():
        if not isinstance(key, str) or not key or type(value) is not int or value <= 0:
            raise IntegrityFailure("Inventory revision entry is invalid")
        revisions[key] = value
    return InventoryMutationResult(
        outcome=outcome,
        target_refs=tuple(refs),
        revisions=revisions,
        replayed=result.replayed,
        no_change=result.no_change,
    )


__all__ = ["InventoryMutationResult", "InventoryRef", "inventory_result_from_execution"]
