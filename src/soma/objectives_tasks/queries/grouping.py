from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..domain.objectives import ObjectiveDraftLocalTaskIntent, ObjectiveExistingTaskIntent


_MAX_PREVIEW_MEMBERS = 99


class ObjectiveGroupingQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _require_relationship_targets(connection: Any, draft: ObjectiveDraftLocalTaskIntent) -> None:
        for values, table, column, field in (
            (draft.service_request_ids, "service_requests", "service_request_id", "service_request_ids"),
            (draft.rfc_ids, "rfcs", "rfc_id", "rfc_ids"),
            (draft.device_reference_ids, "device_references", "device_reference_id", "device_reference_ids"),
        ):
            if not values:
                continue
            placeholders = ",".join("?" for _ in values)
            rows = connection.execute(
                f"SELECT {column} FROM {table} WHERE {column} IN ({placeholders})",
                values,
            ).fetchall()
            if {str(row[0]) for row in rows} != set(values):
                raise SomaError("TASK_STALE", f"{field} contains a missing relationship target")

    @classmethod
    def evaluate_creation(
        cls,
        connection: Any,
        *,
        existing_tasks: Sequence[ObjectiveExistingTaskIntent] = (),
        draft_tasks: Sequence[ObjectiveDraftLocalTaskIntent] = (),
    ) -> dict[str, object]:
        if isinstance(existing_tasks, (str, bytes)) or isinstance(draft_tasks, (str, bytes)):
            raise ValidationError("Objective preview inputs must be sequences")
        existing = tuple(item.validate() for item in existing_tasks)
        drafts = tuple(item.validate() for item in draft_tasks)
        if not existing and not drafts:
            raise SomaError("OBJECTIVE_EMPTY", "Objective requires at least one Task")
        if len(existing) + len(drafts) > _MAX_PREVIEW_MEMBERS:
            raise SomaError(
                "GROUPING_INDETERMINATE",
                "Objective creation exceeds the bounded interactive preview scope",
            )
        if len({item.task_id for item in existing}) != len(existing):
            raise ValidationError("Objective preview contains duplicate existing Tasks")

        prospective: list[dict[str, object]] = []
        current_memberships: list[dict[str, object]] = []
        for item in sorted(existing, key=lambda value: value.task_id):
            row = connection.execute(
                "SELECT t.revision,pc.revision,pc.plan_revision_id,p.start_utc,p.end_utc,"
                "COALESCE(l.revision,0),COALESCE(l.explicit_membership_lock,0),"
                "m.objective_id,m.membership_revision "
                "FROM tasks t "
                "LEFT JOIN task_plan_current pc ON pc.task_id=t.task_id "
                "LEFT JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id "
                "LEFT JOIN task_lock_projection l ON l.task_id=t.task_id "
                "LEFT JOIN objective_task_membership_current m ON m.task_id=t.task_id "
                "WHERE t.task_id=?",
                (item.task_id,),
            ).fetchone()
            if row is None:
                raise SomaError("TASK_NOT_FOUND", "Objective member Task does not exist")
            if (
                int(row[0]) != item.expected_task_revision
                or row[1] is None
                or int(row[1]) != item.expected_plan_revision
                or row[2] is None
                or str(row[2]) != item.expected_plan_revision_id
            ):
                raise SomaError("TASK_STALE", "Objective member Task or current plan changed")
            if row[3] is None or row[4] is None or int(row[4]) <= int(row[3]):
                raise SomaError("TASK_PLAN_INCOMPLETE", "Objective member lacks a complete accepted plan")
            if int(row[6]) == 1:
                raise SomaError("GROUPING_INDETERMINATE", "Objective member has an explicit membership lock")
            current_objective_id = None if row[7] is None else str(row[7])
            current_membership_revision = None if row[8] is None else int(row[8])
            if current_objective_id is not None:
                current_memberships.append(
                    {
                        "task_id": item.task_id,
                        "objective_id": current_objective_id,
                        "membership_revision": current_membership_revision,
                    }
                )
            prospective.append(
                {
                    "kind": "existing",
                    "task_id": item.task_id,
                    "task_revision": item.expected_task_revision,
                    "plan_revision": item.expected_plan_revision,
                    "plan_revision_id": item.expected_plan_revision_id,
                    "start_utc": int(row[3]),
                    "end_utc": int(row[4]),
                    "lock_revision": int(row[5]),
                    "current_objective_id": current_objective_id,
                    "current_membership_revision": current_membership_revision,
                }
            )

        for ordinal, draft in enumerate(drafts, start=1):
            cls._require_relationship_targets(connection, draft)
            prospective.append(
                {
                    "kind": "draft_local",
                    "draft_ordinal": ordinal,
                    "definition": draft.semantic_value(),
                    "start_utc": draft.schedule.start_utc,
                    "end_utc": draft.schedule.end_utc,
                }
            )

        prospective.sort(
            key=lambda item: (
                0 if item["kind"] == "existing" else 1,
                str(item.get("task_id", "")),
                int(item.get("draft_ordinal", 0)),
            )
        )
        start_utc = min(int(item["start_utc"]) for item in prospective)
        end_utc = max(int(item["end_utc"]) for item in prospective)

        overlap_rows = connection.execute(
            "SELECT e.objective_id,e.start_utc,e.end_utc,e.revision,o.revision "
            "FROM objective_envelope_projection e "
            "JOIN objectives o ON o.objective_id=e.objective_id "
            "WHERE o.superseded_by_objective_id IS NULL "
            "AND e.start_utc<? AND e.end_utc>? "
            "ORDER BY e.start_utc,e.objective_id",
            (end_utc, start_utc),
        ).fetchall()
        overlaps = [
            {
                "objective_id": str(row[0]),
                "start_utc": int(row[1]),
                "end_utc": int(row[2]),
                "envelope_revision": int(row[3]),
                "objective_revision": int(row[4]),
            }
            for row in overlap_rows
        ]
        mode = "REGROUP_REQUIRED" if overlaps or current_memberships else "CREATE"
        material = {
            "schema": "OBJECTIVE_CREATION_PREVIEW_V1",
            "prospective_members": prospective,
            "derived_envelope": {"start_utc": start_utc, "end_utc": end_utc},
            "current_memberships": sorted(
                current_memberships, key=lambda item: str(item["task_id"])
            ),
            "overlap_neighbors": overlaps,
        }
        return {
            "mode": mode,
            "fingerprint": sha256_canonical_json(material),
            "prospective_members": prospective,
            "derived_envelope": {"start_utc": start_utc, "end_utc": end_utc},
            "current_memberships": material["current_memberships"],
            "overlap_neighbors": overlaps,
        }

    def creation_preview(
        self,
        *,
        existing_tasks: Sequence[ObjectiveExistingTaskIntent] = (),
        draft_tasks: Sequence[ObjectiveDraftLocalTaskIntent] = (),
    ) -> dict[str, object]:
        with ReadSnapshot(self._factory) as snapshot:
            return self.evaluate_creation(
                snapshot.connection,
                existing_tasks=existing_tasks,
                draft_tasks=draft_tasks,
            )



__all__ = ["ObjectiveGroupingQueryService"]
