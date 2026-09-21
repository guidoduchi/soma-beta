from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandExecutionResult
from soma.foundation.errors import IntegrityFailure


@dataclass(frozen=True, slots=True)
class ReferenceMutationResult:
    outcome: str
    target_id: str
    revision: int
    result_refs: tuple[tuple[str, str], ...]
    replayed: bool

    @property
    def no_change(self) -> bool:
        return self.outcome == "NO_CHANGE"

    @property
    def result_id(self) -> str:
        return self.target_id


def reference_mutation_result_from_execution(execution: CommandExecutionResult) -> ReferenceMutationResult:
    if execution.response_schema != "ReferenceMutationResultV1" or execution.response_version != 1:
        raise IntegrityFailure("reference mutation replay result schema/version is invalid")
    payload = execution.response
    if not isinstance(payload, dict) or set(payload) - {"outcome", "target_id", "revision", "result_refs"}:
        raise IntegrityFailure("reference mutation replay result payload is invalid")
    outcome = payload.get("outcome")
    target_id = payload.get("target_id")
    revision = payload.get("revision")
    raw_refs = payload.get("result_refs", [])
    if outcome not in {"APPLIED", "NO_CHANGE"}:
        raise IntegrityFailure("reference mutation replay result outcome is invalid")
    if not isinstance(target_id, str) or not target_id:
        raise IntegrityFailure("reference mutation replay result target_id is invalid")
    if type(revision) is not int or revision <= 0:
        raise IntegrityFailure("reference mutation replay result revision is invalid")
    if not isinstance(raw_refs, list):
        raise IntegrityFailure("reference mutation replay result refs are invalid")
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_refs:
        if not isinstance(item, dict) or set(item) != {"type", "id"}:
            raise IntegrityFailure("reference mutation replay result ref is invalid")
        result_type = item.get("type")
        result_id = item.get("id")
        if not isinstance(result_type, str) or not result_type or not isinstance(result_id, str) or not result_id:
            raise IntegrityFailure("reference mutation replay result ref identity is invalid")
        ref = (result_type, result_id)
        if ref in seen:
            raise IntegrityFailure("reference mutation replay result contains duplicate refs")
        seen.add(ref)
        refs.append(ref)
    return ReferenceMutationResult(
        outcome=outcome,
        target_id=target_id,
        revision=revision,
        result_refs=tuple(refs),
        replayed=execution.replayed,
    )
