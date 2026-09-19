from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandExecutionResult
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4

_ALLOWED_REF_TYPES = frozenset(
    {
        "device_part_unit",
        "local_need_fulfillment",
        "logistics_event",
        "rma",
        "rma_assignment",
        "spare_need",
        "spare_need_contributor",
        "spare_need_event",
        "spare_part_unit",
        "spare_part_unit_event",
        "task_unit_allocation",
        "task_unit_allocation_event",
    }
)


@dataclass(frozen=True, slots=True)
class InventoryResultRef:
    result_type: str
    result_id: str

    def to_response(self) -> dict[str, str]:
        return {"type": self.result_type, "id": self.result_id}


@dataclass(frozen=True, slots=True)
class InventoryMutationResult:
    outcome: str
    target_refs: tuple[InventoryResultRef, ...]
    revisions: dict[str, int]
    replayed: bool

    @property
    def no_change(self) -> bool:
        return self.outcome == "NO_CHANGE"


def _result_ref(raw: object) -> InventoryResultRef:
    if not isinstance(raw, dict) or set(raw) != {"type", "id"}:
        raise IntegrityFailure("Inventory result ref has the wrong shape")
    result_type = raw.get("type")
    result_id = raw.get("id")
    if result_type not in _ALLOWED_REF_TYPES:
        raise IntegrityFailure("Inventory result ref type is invalid")
    try:
        if not isinstance(result_id, str):
            raise ValidationError("Inventory result identity must be UUID text")
        require_uuid4(result_id)
    except ValidationError as exc:
        raise IntegrityFailure("Inventory result ref identity is invalid") from exc
    return InventoryResultRef(str(result_type), result_id)


def inventory_mutation_result_from_execution(
    result: CommandExecutionResult,
) -> InventoryMutationResult:
    if (
        result.response_schema != "InventoryMutationResultV1"
        or result.response_version != 1
        or not isinstance(result.response, dict)
        or set(result.response) != {"outcome", "target_refs", "revisions"}
    ):
        raise IntegrityFailure("Inventory mutation replay result has the wrong response contract")
    value = result.response
    outcome = value.get("outcome")
    if outcome not in {"APPLIED", "NO_CHANGE"} or bool(result.no_change) != (outcome == "NO_CHANGE"):
        raise IntegrityFailure("Inventory mutation outcome is inconsistent with receipt semantics")
    raw_refs = value.get("target_refs")
    if not isinstance(raw_refs, list) or len(raw_refs) > 32:
        raise IntegrityFailure("Inventory mutation result refs are invalid")
    refs = tuple(_result_ref(raw) for raw in raw_refs)
    identities = [(ref.result_type, ref.result_id) for ref in refs]
    if len(set(identities)) != len(identities):
        raise IntegrityFailure("Inventory mutation result refs contain duplicates")
    revisions = value.get("revisions")
    if not isinstance(revisions, dict) or len(revisions) > 32:
        raise IntegrityFailure("Inventory mutation revisions are invalid")
    normalized_revisions: dict[str, int] = {}
    for key, revision in revisions.items():
        if not isinstance(key, str) or type(revision) is not int or revision <= 0:
            raise IntegrityFailure("Inventory mutation revision entry is invalid")
        if key in normalized_revisions:
            raise IntegrityFailure("Inventory mutation revision entry is duplicated")
        normalized_revisions[key] = revision
    if outcome == "NO_CHANGE":
        if refs or normalized_revisions:
            raise IntegrityFailure("Inventory NO_CHANGE cannot claim material result authority")
        if result.result_type not in {None, "NO_CHANGE"} or result.result_id is not None:
            raise IntegrityFailure("Inventory NO_CHANGE receipt claims material authority")
    else:
        if not isinstance(result.result_type, str) or not isinstance(result.result_id, str):
            raise IntegrityFailure("Inventory material receipt lacks result identity")
        if (result.result_type, result.result_id) not in set(identities):
            raise IntegrityFailure("Inventory response omits the receipt result identity")
    return InventoryMutationResult(
        outcome=str(outcome),
        target_refs=refs,
        revisions=normalized_revisions,
        replayed=result.replayed,
    )
