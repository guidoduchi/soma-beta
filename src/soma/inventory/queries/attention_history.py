from __future__ import annotations

from bisect import insort
from typing import Any

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader


_ATTENTION_KINDS = frozenset(
    {
        "spare_request_response_overdue",
        "partial_rma_authorization",
        "rma_assignment_conflict",
        "receipt_bom_mismatch",
        "task_outcome_consequence_pending",
        "return_obligation_open",
        "warehouse_final_decision_pending",
        "warehouse_rejected_resend_required",
        "proposal_review_required",
        "stock_conflict",
    }
)
_DERIVED_ONLY_KINDS = frozenset(
    {"spare_request_response_overdue", "task_outcome_consequence_pending"}
)
_SEVERITY_RANK = {"high": 3, "action_required": 2, "warning": 1, "info": 0}
_RANK_SEVERITY = {rank: severity for severity, rank in _SEVERITY_RANK.items()}
_CURSOR_FIELDS = {
    "version",
    "query_id",
    "sort_registry_id",
    "last_key_tuple",
    "filter_fingerprint",
    "null_order",
}
_ATTENTION_QUERY_ID = "InventoryAttentionQuery"
_ATTENTION_SORT_ID = "INVENTORY_ATTENTION_CANONICAL_V1"
_ATTENTION_NULL_ORDER = "not applicable"
_RESPONSE_OVERDUE_SECONDS = 86_400
_HISTORY_QUERY_ID = "InventoryHistoryQuery"
_HISTORY_SORT_ID = "INVENTORY_HISTORY_CANONICAL_V1"
_HISTORY_NULL_ORDER = "not applicable"
_HISTORY_CURSOR_FIELDS = _CURSOR_FIELDS


_HISTORY_EVENT_SPECS: dict[
    str, tuple[tuple[str, str, str, str, str, str | None, str | None], ...]
] = {
    "device_part_unit": (
        ("device_part_lifecycle_events", "device_part_unit_id", "device_part_event_id", "event_kind", "domain_lifecycle_event", "evidence_kind", "evidence_id"),
    ),
    "spare_need": (
        ("spare_need_lifecycle_events", "spare_need_id", "need_event_id", "event_kind", "domain_lifecycle_event", None, None),
        ("task_unit_allocation_events", "spare_need_id", "allocation_event_id", "event_kind", "relationship_change", None, None),
        ("local_need_fulfillment_events", "spare_need_id", "local_fulfillment_event_id", "event_kind", "relationship_change", None, None),
    ),
    "spare_request": (
        ("spare_request_lifecycle_events", "spare_request_id", "request_event_id", "event_kind", "domain_lifecycle_event", "evidence_kind", "evidence_id"),
        ("spare_request_identifier_events", "spare_request_id", "identifier_event_id", "event_kind", "relationship_change", None, None),
    ),
    "rma": (
        ("rma_identifier_events", "rma_id", "identifier_event_id", "event_kind", "relationship_change", None, None),
        ("rma_assignment_events", "rma_id", "assignment_event_id", "event_kind", "relationship_change", None, None),
        ("rma_return_selection_events", "rma_id", "return_selection_event_id", "event_kind", "relationship_change", None, None),
    ),
    "spare_part_unit": (
        ("spare_part_lifecycle_events", "spare_part_unit_id", "unit_event_id", "event_kind", "domain_lifecycle_event", "evidence_kind", "evidence_id"),
        ("task_unit_allocation_events", "spare_part_unit_id", "allocation_event_id", "event_kind", "relationship_change", None, None),
        ("local_need_fulfillment_events", "spare_part_unit_id", "local_fulfillment_event_id", "event_kind", "relationship_change", None, None),
    ),
    "physical_consequence": (
        ("physical_consequence_events", "physical_consequence_id", "consequence_event_id", "event_kind", "domain_lifecycle_event", None, None),
    ),
    "fault_tag": (
        ("fault_tag_lifecycle_events", "fault_tag_id", "fault_tag_event_id", "event_kind", "domain_lifecycle_event", "evidence_kind", "evidence_id"),
    ),
    "fault_tag_membership": (
        ("fault_tag_membership_events", "fault_tag_membership_id", "membership_event_id", "event_kind", "domain_lifecycle_event", "evidence_kind", "evidence_id"),
    ),
}


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("limit must be in 1..500")
    return value


def _as_of(value: int | None) -> int:
    if value is None:
        return utc_epoch_seconds()
    if type(value) is not int or value < 0:
        raise ValidationError("as_of_utc must be a nonnegative whole-second UTC instant")
    return value


def _attention_kind(value: str | None) -> str | None:
    if value is not None and value not in _ATTENTION_KINDS:
        raise ValidationError("Inventory attention kind is invalid")
    return value


def _severity(value: str | None) -> str | None:
    if value is not None and value not in _SEVERITY_RANK:
        raise ValidationError("Inventory attention severity is invalid")
    return value


def _attention_id(*, target_kind: str, target_id: str, attention_kind: str) -> str:
    return sha256_canonical_json(
        {
            "schema": "SOMA_INVENTORY_ATTENTION_KEY_V1",
            "target_kind": target_kind,
            "target_id": target_id,
            "attention_kind": attention_kind,
        }
    )


def _attention_item(
    *,
    target_kind: str,
    target_id: str,
    attention_kind: str,
    severity: str,
    condition: dict[str, object],
    reason: str,
    next_governed_action: str,
) -> dict[str, object]:
    identity = _attention_id(
        target_kind=target_kind,
        target_id=target_id,
        attention_kind=attention_kind,
    )
    fingerprint = sha256_canonical_json(
        {
            "schema": "SOMA_INVENTORY_ATTENTION_CONDITION_V1",
            "attention_id": identity,
            "severity": severity,
            "condition": condition,
        }
    )
    return {
        "attention_id": identity,
        "target_kind": target_kind,
        "target_id": target_id,
        "attention_kind": attention_kind,
        "severity": severity,
        "input_fingerprint": fingerprint,
        "reason": reason,
        "derived_context": condition,
        "next_governed_action": next_governed_action,
    }


def _sort_key(item: dict[str, object]) -> tuple[int, str, str, str]:
    severity = str(item["severity"])
    if severity not in _SEVERITY_RANK:
        raise IntegrityFailure("Inventory attention severity is invalid")
    return (
        -_SEVERITY_RANK[severity],
        str(item["attention_kind"]),
        str(item["target_kind"]),
        str(item["target_id"]),
    )


def _cursor_sort_key(raw: object) -> tuple[int, str, str, str]:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or type(raw[0]) is not int
        or raw[0] not in _RANK_SEVERITY
        or any(not isinstance(value, str) or not value for value in raw[1:])
    ):
        raise ValidationError("Inventory attention cursor key is invalid")
    kind = str(raw[1])
    if kind not in _ATTENTION_KINDS:
        raise ValidationError("Inventory attention cursor kind is invalid")
    return (-int(raw[0]), kind, str(raw[2]), str(raw[3]))


def _cursor_key(
    cursor: dict[str, object] | None,
    *,
    filter_fingerprint: str,
) -> tuple[int, str, str, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS:
        raise ValidationError("Inventory attention cursor fields are invalid")
    if (
        cursor["version"] != 1
        or cursor["query_id"] != _ATTENTION_QUERY_ID
        or cursor["sort_registry_id"] != _ATTENTION_SORT_ID
        or cursor["filter_fingerprint"] != filter_fingerprint
        or cursor["null_order"] != _ATTENTION_NULL_ORDER
    ):
        raise ValidationError("Inventory attention cursor contract is invalid")
    return _cursor_sort_key(cursor["last_key_tuple"])


def _cursor(
    *,
    item: dict[str, object],
    filter_fingerprint: str,
) -> dict[str, object]:
    severity = str(item["severity"])
    return {
        "version": 1,
        "query_id": _ATTENTION_QUERY_ID,
        "sort_registry_id": _ATTENTION_SORT_ID,
        "last_key_tuple": [
            _SEVERITY_RANK[severity],
            str(item["attention_kind"]),
            str(item["target_kind"]),
            str(item["target_id"]),
        ],
        "filter_fingerprint": filter_fingerprint,
        "null_order": _ATTENTION_NULL_ORDER,
    }


def _history_filter_fingerprint(*, target_kind: str, target_id: str) -> str:
    return sha256_canonical_json(
        {
            "schema": "SOMA_INVENTORY_HISTORY_FILTER_V1",
            "target_kind": target_kind,
            "target_id": target_id,
        }
    )


def _history_cursor_key(
    cursor: dict[str, object] | None,
    *,
    filter_fingerprint: str,
) -> tuple[int, str, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict) or set(cursor) != _HISTORY_CURSOR_FIELDS:
        raise ValidationError("Inventory history cursor fields are invalid")
    if (
        cursor["version"] != 1
        or cursor["query_id"] != _HISTORY_QUERY_ID
        or cursor["sort_registry_id"] != _HISTORY_SORT_ID
        or cursor["filter_fingerprint"] != filter_fingerprint
        or cursor["null_order"] != _HISTORY_NULL_ORDER
    ):
        raise ValidationError("Inventory history cursor contract is invalid")
    raw = cursor["last_key_tuple"]
    if (
        not isinstance(raw, list)
        or len(raw) != 3
        or type(raw[0]) is not int
        or raw[0] < 0
        or not isinstance(raw[1], str)
        or not raw[1]
        or not isinstance(raw[2], str)
        or not raw[2]
    ):
        raise ValidationError("Inventory history cursor key is invalid")
    return int(raw[0]), str(raw[1]), str(raw[2])


def _history_cursor(
    *,
    row: tuple[object, ...],
    filter_fingerprint: str,
) -> dict[str, object]:
    return {
        "version": 1,
        "query_id": _HISTORY_QUERY_ID,
        "sort_registry_id": _HISTORY_SORT_ID,
        "last_key_tuple": [int(row[0]), str(row[1]), str(row[2])],
        "filter_fingerprint": filter_fingerprint,
        "null_order": _HISTORY_NULL_ORDER,
    }


def _sr_has_customer(connection: Any, service_request_id: str, customer_org_id: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sr_customer_relationships "
            "WHERE service_request_id=? AND relationship_state='active' "
            "AND customer_org_id=? LIMIT 1",
            (service_request_id, customer_org_id),
        ).fetchone()
        is not None
    )


def _task_has_customer(connection: Any, task_id: str, customer_org_id: str) -> bool:
    direct = connection.execute(
        "SELECT 1 FROM task_sr_links ts "
        "JOIN sr_customer_relationships cr "
        "ON cr.service_request_id=ts.service_request_id "
        "WHERE ts.task_id=? AND ts.active=1 "
        "AND cr.relationship_state='active' AND cr.customer_org_id=? LIMIT 1",
        (task_id, customer_org_id),
    ).fetchone()
    if direct is not None:
        return True
    inherited = connection.execute(
        "SELECT 1 FROM wfm_task_identities wi "
        "LEFT JOIN rfc_hierarchy_edges he ON he.child_rfc_id=wi.current_rfc_id "
        "AND he.edge_state='active' "
        "JOIN sr_rfc_links sl ON sl.rfc_id=COALESCE(he.parent_rfc_id,wi.current_rfc_id) "
        "AND sl.link_state='active' "
        "JOIN sr_customer_relationships cr ON cr.service_request_id=sl.service_request_id "
        "WHERE wi.task_id=? AND cr.relationship_state='active' "
        "AND cr.customer_org_id=? LIMIT 1",
        (task_id, customer_org_id),
    ).fetchone()
    return inherited is not None


def _target_has_customer(
    connection: Any,
    *,
    target_kind: str,
    target_id: str,
    customer_org_id: str,
) -> bool:
    if target_kind == "spare_need":
        row = connection.execute(
            "SELECT service_request_id FROM spare_needs WHERE spare_need_id=?",
            (target_id,),
        ).fetchone()
    elif target_kind == "spare_request":
        row = connection.execute(
            "SELECT service_request_id FROM spare_requests WHERE spare_request_id=?",
            (target_id,),
        ).fetchone()
    elif target_kind == "rma":
        row = connection.execute(
            "SELECT r.service_request_id FROM rmas x "
            "JOIN spare_requests r ON r.spare_request_id=x.spare_request_id "
            "WHERE x.rma_id=?",
            (target_id,),
        ).fetchone()
    else:
        row = None
    if row is not None:
        return _sr_has_customer(connection, str(row[0]), customer_org_id)
    if target_kind == "physical_consequence":
        task = connection.execute(
            "SELECT task_id FROM inventory_physical_consequences "
            "WHERE physical_consequence_id=?",
            (target_id,),
        ).fetchone()
        if task is None:
            raise IntegrityFailure("Inventory physical-consequence attention target is missing")
        return _task_has_customer(connection, str(task[0]), customer_org_id)
    if target_kind in {"fault_tag", "fault_tag_membership"}:
        if target_kind == "fault_tag":
            sql = (
                "SELECT DISTINCT r.service_request_id FROM fault_tag_memberships m "
                "JOIN rmas x ON x.rma_id=m.rma_id "
                "JOIN spare_requests r ON r.spare_request_id=x.spare_request_id "
                "WHERE m.fault_tag_id=?"
            )
        else:
            sql = (
                "SELECT r.service_request_id FROM fault_tag_memberships m "
                "JOIN rmas x ON x.rma_id=m.rma_id "
                "JOIN spare_requests r ON r.spare_request_id=x.spare_request_id "
                "WHERE m.fault_tag_membership_id=?"
            )
        rows = connection.execute(sql, (target_id,)).fetchall()
        if not rows:
            raise IntegrityFailure("Inventory Fault Tag attention target authority is missing")
        return any(
            _sr_has_customer(connection, str(item[0]), customer_org_id)
            for item in rows
        )
    raise IntegrityFailure("Inventory attention target kind cannot be customer-scoped")


def _consider(
    *,
    item: dict[str, object],
    after: tuple[int, str, str, str] | None,
    selected: list[tuple[tuple[int, str, str, str], str, dict[str, object]]],
    capacity: int,
) -> None:
    key = _sort_key(item)
    if after is not None and key <= after:
        return
    insort(selected, (key, str(item["attention_id"]), item))
    if len(selected) > capacity:
        selected.pop()


class InventoryAttentionHistoryQuery:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def attention(
        self,
        *,
        customer_org_id: str | None = None,
        attention_kind: str | None = None,
        severity: str | None = None,
        as_of_utc: int | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = _limit(limit)
        customer_id = (
            None if customer_org_id is None else require_uuid4(customer_org_id)
        )
        kind = _attention_kind(attention_kind)
        severity_filter = _severity(severity)
        if cursor is not None and as_of_utc is None:
            raise ValidationError(
                "as_of_utc is required when continuing Inventory attention pagination"
            )
        effective_as_of = _as_of(as_of_utc)
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_INVENTORY_ATTENTION_FILTER_V1",
                "customer_org_id": customer_id,
                "attention_kind": kind,
                "severity": severity_filter,
                "as_of_utc": effective_as_of,
            }
        )
        after = _cursor_key(cursor, filter_fingerprint=filter_fingerprint)
        selected: list[
            tuple[tuple[int, str, str, str], str, dict[str, object]]
        ] = []
        exact_total = 0

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            clauses: list[str] = []
            params: list[object] = []
            if kind is not None:
                clauses.append("attention_kind=?")
                params.append(kind)
            if severity_filter is not None:
                clauses.append("severity=?")
                params.append(severity_filter)
            where = "" if not clauses else " WHERE " + " AND ".join(clauses)
            persisted = connection.execute(
                "SELECT attention_id,target_kind,target_id,attention_kind,severity,"
                "input_fingerprint FROM inventory_attention_projection"
                + where
                + " ORDER BY attention_id",
                tuple(params),
            )
            while True:
                rows = persisted.fetchmany(500)
                if not rows:
                    break
                for row in rows:
                    persisted_kind = str(row[3])
                    if persisted_kind in _DERIVED_ONLY_KINDS:
                        raise IntegrityFailure(
                            "Derived-only Inventory attention was materialized"
                        )
                    target_kind = str(row[1])
                    target_id = str(row[2])
                    expected_id = _attention_id(
                        target_kind=target_kind,
                        target_id=target_id,
                        attention_kind=persisted_kind,
                    )
                    if str(row[0]) != expected_id:
                        raise IntegrityFailure(
                            "Inventory attention cache identity is inconsistent"
                        )
                    if customer_id is not None and not _target_has_customer(
                        connection,
                        target_kind=target_kind,
                        target_id=target_id,
                        customer_org_id=customer_id,
                    ):
                        continue
                    item = {
                        "attention_id": expected_id,
                        "target_kind": target_kind,
                        "target_id": target_id,
                        "attention_kind": persisted_kind,
                        "severity": str(row[4]),
                        "input_fingerprint": str(row[5]),
                        "reason": "current Inventory authority requires governed review",
                        "derived_context": {},
                        "next_governed_action": "review_inventory_attention",
                    }
                    exact_total += 1
                    _consider(
                        item=item,
                        after=after,
                        selected=selected,
                        capacity=page_limit + 1,
                    )

            if kind in {None, "spare_request_response_overdue"} and severity_filter in {
                None,
                "action_required",
            }:
                response_rows = connection.execute(
                    "SELECT r.spare_request_id,r.service_request_id,"
                    "p.response_warning_start_utc,p.lifecycle_state,p.revision "
                    "FROM spare_requests r JOIN spare_request_current_projection p "
                    "ON p.spare_request_id=r.spare_request_id "
                    "WHERE p.lifecycle_state='submitted_awaiting_response' "
                    "AND p.response_warning_start_utc IS NOT NULL "
                    "AND (? - p.response_warning_start_utc)>=? "
                    "ORDER BY r.spare_request_id",
                    (effective_as_of, _RESPONSE_OVERDUE_SECONDS),
                )
                while True:
                    rows = response_rows.fetchmany(500)
                    if not rows:
                        break
                    for row in rows:
                        request_id = str(row[0])
                        sr_id = str(row[1])
                        if customer_id is not None and not _sr_has_customer(
                            connection, sr_id, customer_id
                        ):
                            continue
                        start = int(row[2])
                        item = _attention_item(
                            target_kind="spare_request",
                            target_id=request_id,
                            attention_kind="spare_request_response_overdue",
                            severity="action_required",
                            condition={
                                "as_of_utc": effective_as_of,
                                "response_warning_start_utc": start,
                                "age_seconds": effective_as_of - start,
                                "lifecycle_state": str(row[3]),
                                "revision": int(row[4]),
                            },
                            reason="accepted provider response is overdue by at least 24 hours",
                            next_governed_action="review_spare_request_response",
                        )
                        exact_total += 1
                        _consider(
                            item=item,
                            after=after,
                            selected=selected,
                            capacity=page_limit + 1,
                        )

            if kind in {None, "task_outcome_consequence_pending"} and severity_filter in {
                None,
                "action_required",
            }:
                consequence_rows = connection.execute(
                    "SELECT i.physical_consequence_id,i.task_id,"
                    "c.task_review_fingerprint,c.input_fingerprint,c.revision "
                    "FROM inventory_physical_consequences i "
                    "JOIN physical_consequence_current c "
                    "ON c.physical_consequence_id=i.physical_consequence_id "
                    "ORDER BY i.physical_consequence_id"
                )
                while True:
                    rows = consequence_rows.fetchmany(500)
                    if not rows:
                        break
                    for row in rows:
                        consequence_id = str(row[0])
                        task_id = str(row[1])
                        if customer_id is not None and not _task_has_customer(
                            connection, task_id, customer_id
                        ):
                            continue
                        stored_review = str(row[2])
                        current_review = TaskOperationalEvidenceReader.review_fingerprint(
                            snapshot, task_id
                        )
                        if current_review == stored_review:
                            continue
                        item = _attention_item(
                            target_kind="physical_consequence",
                            target_id=consequence_id,
                            attention_kind="task_outcome_consequence_pending",
                            severity="action_required",
                            condition={
                                "task_id": task_id,
                                "accepted_task_review_fingerprint": stored_review,
                                "current_task_review_fingerprint": current_review,
                                "physical_consequence_input_fingerprint": str(row[3]),
                                "physical_consequence_revision": int(row[4]),
                            },
                            reason="upstream Task operational review changed after Inventory consequence acceptance",
                            next_governed_action="review_inventory_physical_consequence",
                        )
                        exact_total += 1
                        _consider(
                            item=item,
                            after=after,
                            selected=selected,
                            capacity=page_limit + 1,
                        )

        page = [item for _, _, item in selected[:page_limit]]
        continuation = None
        if len(selected) > page_limit and page:
            continuation = _cursor(
                item=page[-1],
                filter_fingerprint=filter_fingerprint,
            )
        return {
            "items": page,
            "continuation": continuation,
            "exact_total": exact_total,
            "as_of_utc": effective_as_of,
        }

    def history(
        self,
        *,
        target_kind: str,
        target_id: str,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        identity = require_uuid4(target_id)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("limit must be in 1..500")
        specs = _HISTORY_EVENT_SPECS.get(target_kind)
        if specs is None:
            raise ValidationError("unsupported Inventory history target kind")
        filter_fingerprint = _history_filter_fingerprint(
            target_kind=target_kind,
            target_id=identity,
        )
        after = _history_cursor_key(cursor, filter_fingerprint=filter_fingerprint)

        branches: list[str] = []
        params: list[object] = []
        for (
            table,
            id_column,
            event_id_column,
            event_kind_column,
            authority_kind,
            evidence_kind_column,
            evidence_id_column,
        ) in specs:
            evidence_kind = "NULL" if evidence_kind_column is None else evidence_kind_column
            evidence_id = "NULL" if evidence_id_column is None else evidence_id_column
            branches.append(
                f"SELECT recorded_at_utc,'{authority_kind}' AS authority_kind,"
                f"{event_id_column} AS immutable_id,{event_kind_column} AS event_kind,"
                f"command_id,{evidence_kind} AS source_kind,{evidence_id} AS source_id "
                f"FROM {table} WHERE {id_column}=?"
            )
            params.append(identity)

        custom: dict[str, tuple[str, ...]] = {
            "device_part_unit": (
                "SELECT e.recorded_at_utc,'relationship_change',e.logistics_event_id,e.event_kind,"
                "e.command_id,e.evidence_kind,e.evidence_id FROM actual_logistics_events e "
                "JOIN logistics_device_part_participants p ON p.logistics_event_id=e.logistics_event_id "
                "WHERE p.device_part_unit_id=?",
            ),
            "spare_need": (
                "SELECT c.opened_at_utc,'relationship_change',c.contributor_relationship_id||':opened',"
                "'contributor_opened',c.opened_command_id,NULL,NULL FROM spare_need_contributors c "
                "WHERE c.spare_need_id=?",
                "SELECT c.closed_at_utc,'relationship_change',c.contributor_relationship_id||':closed',"
                "'contributor_closed',c.closed_command_id,NULL,NULL FROM spare_need_contributors c "
                "WHERE c.spare_need_id=? AND c.closed_at_utc IS NOT NULL",
            ),
            "spare_request": (
                "SELECT b.accepted_at_utc,'relationship_change',b.authorization_batch_id,"
                "'rma_authorization_batch',b.command_id,b.evidence_kind,b.evidence_id "
                "FROM rma_authorization_batches b WHERE b.spare_request_id=?",
            ),
            "rma": (
                "SELECT r.committed_at_utc,'relationship_change',d.direct_inbound_relationship_id,"
                "'direct_inbound_unit',d.opened_command_id,NULL,NULL FROM rma_direct_inbound_units d "
                "JOIN command_receipts r ON r.command_id=d.opened_command_id WHERE d.rma_id=?",
                "SELECT e.recorded_at_utc,'relationship_change',e.logistics_event_id,e.event_kind,"
                "e.command_id,e.evidence_kind,e.evidence_id FROM actual_logistics_events e "
                "JOIN logistics_rma_participants p ON p.logistics_event_id=e.logistics_event_id "
                "WHERE p.rma_id=?",
                "SELECT e.recorded_at_utc,'relationship_change',e.membership_event_id,e.event_kind,"
                "e.command_id,e.evidence_kind,e.evidence_id FROM fault_tag_membership_events e "
                "JOIN fault_tag_memberships m ON m.fault_tag_membership_id=e.fault_tag_membership_id "
                "WHERE m.rma_id=?",
            ),
            "spare_part_unit": (
                "SELECT e.recorded_at_utc,'relationship_change',e.logistics_event_id,e.event_kind,"
                "e.command_id,e.evidence_kind,e.evidence_id FROM actual_logistics_events e "
                "JOIN logistics_spare_unit_participants p ON p.logistics_event_id=e.logistics_event_id "
                "WHERE p.spare_part_unit_id=?",
            ),
            "physical_consequence": (
                "SELECT e.recorded_at_utc,'relationship_change',e.return_selection_event_id,e.event_kind,"
                "e.command_id,NULL,NULL FROM rma_return_selection_events e "
                "WHERE e.physical_consequence_id=?",
            ),
            "fault_tag": (
                "SELECT e.recorded_at_utc,'relationship_change',e.membership_event_id,e.event_kind,"
                "e.command_id,e.evidence_kind,e.evidence_id FROM fault_tag_membership_events e "
                "JOIN fault_tag_memberships m ON m.fault_tag_membership_id=e.fault_tag_membership_id "
                "WHERE m.fault_tag_id=?",
                "SELECT l.recorded_at_utc,'relationship_change',l.fault_tag_lineage_id,l.relation_type,"
                "l.command_id,NULL,NULL FROM fault_tag_lineage l "
                "WHERE l.predecessor_fault_tag_id=? OR l.successor_fault_tag_id=?",
            ),
        }
        for statement in custom.get(target_kind, ()):
            branches.append(statement)
            params.extend((identity, identity) if " OR " in statement else (identity,))

        audit_target_kind = (
            "inventory_physical_consequence"
            if target_kind == "physical_consequence"
            else target_kind
        )
        branches.append(
            "SELECT recorded_at_utc,'application_audit_reference',audit_event_id,"
            "action_type,command_id,NULL,NULL FROM audit_events "
            "WHERE target_type=? AND target_id=?"
        )
        params.extend((audit_target_kind, identity))

        proposal_column = {
            "spare_request": "spare_request_id",
            "rma": "rma_id",
            "spare_part_unit": "spare_part_unit_id",
            "fault_tag": "fault_tag_id",
            "fault_tag_membership": "fault_tag_membership_id",
        }.get(target_kind)
        if proposal_column is not None:
            branches.append(
                "SELECT p.created_at_utc,'source_proposal_reference',"
                "t.inventory_proposal_target_id,p.proposal_kind,p.last_command_id,"
                "p.evidence_kind,p.evidence_id FROM inventory_proposal_targets t "
                "JOIN inventory_proposals p ON p.inventory_proposal_id=t.inventory_proposal_id "
                f"WHERE t.{proposal_column}=?"
            )
            params.append(identity)

        union = " UNION ALL ".join(branches)
        where = ""
        if after is not None:
            where = (
                " WHERE (recorded_at_utc<? OR "
                "(recorded_at_utc=? AND authority_kind>?) OR "
                "(recorded_at_utc=? AND authority_kind=? AND immutable_id<?))"
            )
            params.extend((after[0], after[0], after[1], after[0], after[1], after[2]))
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT recorded_at_utc,authority_kind,immutable_id,event_kind,command_id,"
                "source_kind,source_id FROM (" + union + ")" + where
                + " ORDER BY recorded_at_utc DESC,authority_kind ASC,immutable_id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            page = rows[:limit]
            return {
                "items": [
                    {
                        "recorded_at_utc": int(row[0]),
                        "authority_kind": str(row[1]),
                        "immutable_event_or_relation_id": str(row[2]),
                        "event_kind": str(row[3]),
                        "command_id": None if row[4] is None else str(row[4]),
                        "source_ref": (
                            None
                            if row[5] is None
                            else {"kind": str(row[5]), "id": str(row[6])}
                        ),
                    }
                    for row in page
                ],
                "continuation": (
                    _history_cursor(
                        row=page[-1],
                        filter_fingerprint=filter_fingerprint,
                    )
                    if len(rows) > limit and page
                    else None
                ),
            }


__all__ = ["InventoryAttentionHistoryQuery"]
