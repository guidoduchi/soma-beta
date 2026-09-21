from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ..repositories.objectives import ObjectiveProjectionRepository


_MAX_PREVIEW_MEMBERS = 99


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("limit must be an integer from 1 through 500")
    return value


class ObjectiveQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def list_objectives(
        self,
        *,
        execution_state: str | None = None,
        archived: bool | None = None,
        after_start_utc: int | None = None,
        after_objective_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = _limit(limit)
        if after_start_utc is not None and (type(after_start_utc) is not int or after_start_utc < 0):
            raise ValidationError("after_start_utc is invalid")
        after_id = None if after_objective_id is None else require_uuid4(after_objective_id)
        if (after_start_utc is None) != (after_id is None):
            raise ValidationError("Objective continuation requires both key fields")
        params: list[object] = []
        clauses = ["o.superseded_by_objective_id IS NULL"]
        if execution_state is not None:
            clauses.append("a.execution_state=?")
            params.append(execution_state)
        if archived is not None:
            clauses.append("COALESCE(ar.archived,0)=?")
            params.append(1 if archived else 0)
        where = " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            total = int(
                snapshot.connection.execute(
                    "SELECT COUNT(*) FROM objectives o "
                    "JOIN objective_envelope_projection e ON e.objective_id=o.objective_id "
                    "JOIN objective_aggregate_projection a ON a.objective_id=o.objective_id "
                    "LEFT JOIN objective_archive_projection ar ON ar.objective_id=o.objective_id"
                    + where,
                    tuple(params),
                ).fetchone()[0]
            )
            page_clauses = list(clauses)
            page_params = list(params)
            if after_start_utc is not None and after_id is not None:
                page_clauses.append(
                    "(COALESCE(a.actual_start_utc,e.start_utc)>? OR "
                    "(COALESCE(a.actual_start_utc,e.start_utc)=? AND o.objective_id>?))"
                )
                page_params.extend([after_start_utc, after_start_utc, after_id])
            page_where = " WHERE " + " AND ".join(page_clauses)
            rows = snapshot.connection.execute(
                "SELECT o.objective_id,o.tracking_id,o.creation_origin,o.revision,"
                "e.start_utc,e.end_utc,e.member_count,e.revision,"
                "a.execution_state,a.aggregate_outcome,a.actual_start_utc,a.actual_end_utc,"
                "a.attention_reason,a.included_task_count,a.excluded_task_count,a.revision,"
                "COALESCE(ar.archived,0),COALESCE(ar.revision,0),"
                "COALESCE(a.actual_start_utc,e.start_utc) AS effective_start "
                "FROM objectives o "
                "JOIN objective_envelope_projection e ON e.objective_id=o.objective_id "
                "JOIN objective_aggregate_projection a ON a.objective_id=o.objective_id "
                "LEFT JOIN objective_archive_projection ar ON ar.objective_id=o.objective_id"
                + page_where
                + " ORDER BY effective_start,o.objective_id LIMIT ?",
                (*page_params, page_limit + 1),
            ).fetchall()
            page = rows[:page_limit]
            items = [
                {
                    "objective_id": str(row[0]),
                    "tracking_handle": str(row[1]),
                    "creation_origin": str(row[2]),
                    "revision": int(row[3]),
                    "derived_envelope": {
                        "start_utc": int(row[4]),
                        "end_utc": int(row[5]),
                        "member_count": int(row[6]),
                        "revision": int(row[7]),
                    },
                    "aggregate_state": {
                        "execution_state": str(row[8]),
                        "aggregate_outcome": None if row[9] is None else str(row[9]),
                        "actual_start_utc": None if row[10] is None else int(row[10]),
                        "actual_end_utc": None if row[11] is None else int(row[11]),
                        "attention_reason": None if row[12] is None else str(row[12]),
                        "included_task_count": int(row[13]),
                        "excluded_task_count": int(row[14]),
                        "revision": int(row[15]),
                    },
                    "archived": bool(row[16]),
                    "archive_revision": int(row[17]),
                }
                for row in page
            ]
            continuation = None
            if len(rows) > page_limit and page:
                last = page[-1]
                continuation = {
                    "effective_start_utc": int(last[18]),
                    "objective_id": str(last[0]),
                }
            return {"items": items, "continuation": continuation, "exact_total": total}

    def workbench(
        self,
        objective_id: str,
        *,
        member_after_task_id: str | None = None,
        member_limit: int = 100,
    ) -> dict[str, object]:
        identity = require_uuid4(objective_id)
        after = None if member_after_task_id is None else require_uuid4(member_after_task_id)
        page_limit = _limit(member_limit)
        with ReadSnapshot(self._factory) as snapshot:
            objective = snapshot.connection.execute(
                "SELECT objective_id,tracking_id,creation_origin,superseded_by_objective_id,"
                "revision,created_at_utc FROM objectives WHERE objective_id=?",
                (identity,),
            ).fetchone()
            if objective is None:
                raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")
            envelope = snapshot.connection.execute(
                "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision "
                "FROM objective_envelope_projection WHERE objective_id=?",
                (identity,),
            ).fetchone()
            aggregate = ObjectiveProjectionRepository.aggregate(snapshot.connection, identity)
            archive = snapshot.connection.execute(
                "SELECT archived,revision,last_event_id FROM objective_archive_projection "
                "WHERE objective_id=?",
                (identity,),
            ).fetchone()
            total = int(
                snapshot.connection.execute(
                    "SELECT COUNT(*) FROM objective_task_membership_current WHERE objective_id=?",
                    (identity,),
                ).fetchone()[0]
            )
            params: list[object] = [identity]
            clause = ""
            if after is not None:
                clause = " AND m.task_id>?"
                params.append(after)
            rows = snapshot.connection.execute(
                "SELECT m.task_id,m.accepted_plan_revision_id,m.membership_revision,"
                "p.start_utc,p.end_utc,pc.plan_revision_id,pc.revision,t.task_kind,"
                "t.local_task_name,w.task_no "
                "FROM objective_task_membership_current m "
                "JOIN task_plan_revisions p ON p.plan_revision_id=m.accepted_plan_revision_id "
                "JOIN task_plan_current pc ON pc.task_id=m.task_id "
                "JOIN tasks t ON t.task_id=m.task_id "
                "LEFT JOIN wfm_task_identities w ON w.task_id=m.task_id "
                "WHERE m.objective_id=?"
                + clause
                + " ORDER BY m.task_id LIMIT ?",
                (*params, page_limit + 1),
            ).fetchall()
            page = rows[:page_limit]
            membership = [
                {
                    "task_id": str(row[0]),
                    "accepted_plan_revision_id": str(row[1]),
                    "membership_revision": int(row[2]),
                    "accepted_plan": {"start_utc": int(row[3]), "end_utc": int(row[4])},
                    "current_plan_revision_id": str(row[5]),
                    "current_plan_revision": int(row[6]),
                    "plan_membership_mismatch": str(row[1]) != str(row[5]),
                    "task_kind": str(row[7]),
                    "display_name": str(row[8]) if row[8] is not None else str(row[9]),
                }
                for row in page
            ]
            members = ObjectiveProjectionRepository._load_members(snapshot.connection, identity)
            review_fingerprint = ObjectiveProjectionRepository._review_fingerprint(
                objective_id=identity,
                objective_revision=int(objective[4]),
                superseded_by=None if objective[3] is None else str(objective[3]),
                members=members,
            )
            current_review = ObjectiveProjectionRepository._current_review(
                snapshot.connection, identity, review_fingerprint
            )
            latest_review = snapshot.connection.execute(
                "SELECT objective_review_event_id,review_fingerprint,derived_outcome,"
                "reviewed_at_utc,reason_code FROM objective_review_events "
                "WHERE objective_id=? ORDER BY reviewed_at_utc DESC,objective_review_event_id DESC LIMIT 1",
                (identity,),
            ).fetchone()
            return {
                "objective_id": identity,
                "tracking_handle": str(objective[1]),
                "creation_origin": str(objective[2]),
                "superseded_by_objective_id": None if objective[3] is None else str(objective[3]),
                "revision": int(objective[4]),
                "created_at_utc": int(objective[5]),
                "membership": membership,
                "member_exact_count": total,
                "member_continuation": str(page[-1][0]) if len(rows) > page_limit and page else None,
                "derived_envelope": None
                if envelope is None
                else {
                    "start_utc": int(envelope[0]),
                    "end_utc": int(envelope[1]),
                    "member_count": int(envelope[2]),
                    "membership_input_fingerprint": str(envelope[3]),
                    "revision": int(envelope[4]),
                },
                "aggregate_state": None
                if aggregate is None
                else {
                    "execution_state": aggregate.execution_state,
                    "aggregate_outcome": aggregate.aggregate_outcome,
                    "actual_start_utc": aggregate.actual_start_utc,
                    "actual_end_utc": aggregate.actual_end_utc,
                    "attention_reason": aggregate.attention_reason,
                    "included_task_count": aggregate.included_task_count,
                    "excluded_task_count": aggregate.excluded_task_count,
                    "revision": aggregate.revision,
                    "aggregate_input_fingerprint": aggregate.aggregate_input_fingerprint,
                },
                "archive": {
                    "archived": False if archive is None else bool(archive[0]),
                    "revision": 0 if archive is None else int(archive[1]),
                    "last_event_id": None if archive is None or archive[2] is None else str(archive[2]),
                },
                "review": {
                    "review_fingerprint": review_fingerprint,
                    "current": current_review,
                    "latest": None
                    if latest_review is None
                    else {
                        "objective_review_event_id": str(latest_review[0]),
                        "review_fingerprint": str(latest_review[1]),
                        "derived_outcome": str(latest_review[2]),
                        "reviewed_at_utc": int(latest_review[3]),
                        "reason_code": None if latest_review[4] is None else str(latest_review[4]),
                        "stale": str(latest_review[1]) != review_fingerprint,
                    },
                },
            }



    def context_by_task_relationships(
        self,
        objective_id: str,
        *,
        after_key: tuple[str, str, str] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        identity = require_uuid4(objective_id)
        page_limit = _limit(limit)
        with ReadSnapshot(self._factory) as snapshot:
            if snapshot.connection.execute(
                "SELECT 1 FROM objectives WHERE objective_id=?",
                (identity,),
            ).fetchone() is None:
                raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")
            task_ids = [
                str(row[0])
                for row in snapshot.connection.execute(
                    "SELECT task_id FROM objective_task_membership_current "
                    "WHERE objective_id=? ORDER BY task_id",
                    (identity,),
                ).fetchall()
            ]
            rows: list[dict[str, object]] = []
            for task_id in task_ids:
                kind_row = snapshot.connection.execute(
                    "SELECT task_kind FROM tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if kind_row is None:
                    raise IntegrityFailure("Objective member Task is missing")
                kind = str(kind_row[0])
                local_customer_contexts: set[str | None] = set()
                for context_type, table, column in (
                    ("sr", "task_sr_links", "service_request_id"),
                    ("rfc", "task_rfc_links", "rfc_id"),
                    ("device", "task_device_links", "device_reference_id"),
                ):
                    for rel in snapshot.connection.execute(
                        f"SELECT {column},link_id FROM {table} "
                        "WHERE task_id=? AND active=1 ORDER BY "
                        f"{column},link_id",
                        (task_id,),
                    ).fetchall():
                        related_id = str(rel[0])
                        rows.append(
                            {
                                "context_type": context_type,
                                "related_id": related_id,
                                "source_task_id": task_id,
                                "provenance": f"direct_task_{context_type}_relationship",
                                "resolution_state": "resolved",
                            }
                        )
                        if kind == "local" and context_type == "sr":
                            customer = snapshot.connection.execute(
                                "SELECT customer_org_id FROM sr_customer_relationships "
                                "WHERE service_request_id=? AND relationship_state='active'",
                                (related_id,),
                            ).fetchone()
                            local_customer_contexts.add(
                                None if customer is None else str(customer[0])
                            )
                        elif kind == "local" and context_type == "rfc":
                            customer = snapshot.connection.execute(
                                "SELECT customer_org_id FROM rfcs WHERE rfc_id=?",
                                (related_id,),
                            ).fetchone()
                            local_customer_contexts.add(
                                None
                                if customer is None or customer[0] is None
                                else str(customer[0])
                            )
                if kind == "local":
                    for customer_org_id in sorted(
                        local_customer_contexts,
                        key=lambda value: "" if value is None else value,
                    ):
                        rows.append(
                            {
                                "context_type": "customer",
                                "related_id": customer_org_id,
                                "source_task_id": task_id,
                                "provenance": "derived_from_direct_task_ticket_relationship",
                                "resolution_state": (
                                    "unresolved" if customer_org_id is None else "resolved"
                                ),
                            }
                        )
                if kind == "wfm":
                    wfm = snapshot.connection.execute(
                        "SELECT current_rfc_id FROM wfm_task_identities WHERE task_id=?",
                        (task_id,),
                    ).fetchone()
                    if wfm is None:
                        raise IntegrityFailure("WFM Objective member lacks owning RFC")
                    owning = str(wfm[0])
                    parent = snapshot.connection.execute(
                        "SELECT parent_rfc_id FROM rfc_hierarchy_edges "
                        "WHERE child_rfc_id=? AND edge_state='active'",
                        (owning,),
                    ).fetchone()
                    root = owning if parent is None else str(parent[0])
                    rows.append(
                        {
                            "context_type": "rfc",
                            "related_id": owning,
                            "source_task_id": task_id,
                            "provenance": "wfm_owning_rfc",
                            "resolution_state": "resolved",
                        }
                    )
                    for sr in snapshot.connection.execute(
                        "SELECT service_request_id FROM sr_rfc_links "
                        "WHERE rfc_id=? AND link_state='active' ORDER BY service_request_id",
                        (root,),
                    ).fetchall():
                        rows.append(
                            {
                                "context_type": "sr",
                                "related_id": str(sr[0]),
                                "source_task_id": task_id,
                                "provenance": "wfm_governing_root_sr",
                                "resolution_state": "resolved",
                            }
                        )
                    customer = snapshot.connection.execute(
                        "SELECT customer_org_id FROM rfcs WHERE rfc_id=?",
                        (root,),
                    ).fetchone()
                    rows.append(
                        {
                            "context_type": "customer",
                            "related_id": None
                            if customer is None or customer[0] is None
                            else str(customer[0]),
                            "source_task_id": task_id,
                            "provenance": "wfm_governing_root_customer",
                            "resolution_state": (
                                "unresolved"
                                if customer is None or customer[0] is None
                                else "resolved"
                            ),
                        }
                    )
            rows.sort(
                key=lambda item: (
                    str(item["context_type"]),
                    "" if item["related_id"] is None else str(item["related_id"]),
                    str(item["source_task_id"]),
                )
            )
            totals: dict[str, int] = {}
            for item in rows:
                key = str(item["context_type"])
                totals[key] = totals.get(key, 0) + 1
            start = 0
            if after_key is not None:
                if len(after_key) != 3:
                    raise ValidationError("Objective context cursor is invalid")
                needle = tuple(str(value) for value in after_key)
                keys = [
                    (
                        str(item["context_type"]),
                        "" if item["related_id"] is None else str(item["related_id"]),
                        str(item["source_task_id"]),
                    )
                    for item in rows
                ]
                try:
                    start = keys.index(needle) + 1
                except ValueError as exc:
                    raise ValidationError("Objective context cursor is stale") from exc
            page = rows[start : start + page_limit]
            continuation = None
            if start + len(page) < len(rows) and page:
                last = page[-1]
                continuation = (
                    str(last["context_type"]),
                    "" if last["related_id"] is None else str(last["related_id"]),
                    str(last["source_task_id"]),
                )
            return {
                "items": page,
                "continuation": continuation,
                "exact_totals_by_context_type": totals,
            }

    def monthly_ordinal(
        self,
        objective_id: str,
        *,
        timezone_iana: str,
    ) -> dict[str, object]:
        identity = require_uuid4(objective_id)
        if not isinstance(timezone_iana, str) or not timezone_iana:
            raise ValidationError("Objective timezone is required")
        try:
            tz = ZoneInfo(timezone_iana)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError("Objective timezone is unknown") from exc
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT o.objective_id,e.start_utc,a.actual_start_utc "
                "FROM objectives o "
                "JOIN objective_envelope_projection e ON e.objective_id=o.objective_id "
                "JOIN objective_aggregate_projection a ON a.objective_id=o.objective_id "
                "WHERE o.superseded_by_objective_id IS NULL "
                "ORDER BY COALESCE(a.actual_start_utc,e.start_utc),o.objective_id"
            ).fetchall()
            entries = []
            target = None
            for row in rows:
                effective = int(row[2]) if row[2] is not None else int(row[1])
                local = datetime.fromtimestamp(effective, tz=timezone.utc).astimezone(tz)
                item = {
                    "objective_id": str(row[0]),
                    "effective_start_utc": effective,
                    "basis": "actual_start" if row[2] is not None else "planned_start",
                    "year_month": f"{local.year:04d}-{local.month:02d}",
                }
                entries.append(item)
                if str(row[0]) == identity:
                    target = item
            if target is None:
                raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")
            bucket = [
                item
                for item in entries
                if item["year_month"] == target["year_month"]
            ]
            bucket.sort(
                key=lambda item: (
                    int(item["effective_start_utc"]),
                    str(item["objective_id"]),
                )
            )
            ordinal = next(
                index
                for index, item in enumerate(bucket, start=1)
                if item["objective_id"] == identity
            )
            return {
                "objective_id": identity,
                "year_month": target["year_month"],
                "ordinal": ordinal,
                "effective_start_utc": target["effective_start_utc"],
                "basis": target["basis"],
                "timezone": timezone_iana,
            }


__all__ = ["ObjectiveQueryService"]
