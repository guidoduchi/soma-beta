from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.strict_json import ObjectContract
from soma.product_line_sla.report_sections import (
    ReportSectionDescriptor,
    ReportSectionRow,
)

_SECTION_FIELDS = frozenset(
    {
        "service_request_id",
        "customer_org_id",
        "active_need_count",
        "spare_request_count",
        "rma_count",
        "open_return_obligation_count",
        "fault_tag_count",
        "unresolved_attention_count",
    }
)


class InventoryReportSectionContributor:
    """Minimized read-only LLD-07 constituent summary for LLD-06 reports."""

    def section_descriptor(self) -> ReportSectionDescriptor:
        return ReportSectionDescriptor(
            section_kind="inventory_constituent_summary",
            schema_name="InventoryConstituentSummaryV1",
            schema_version=1,
            ordinal=70,
            payload_contract=ObjectContract(
                name="InventoryConstituentSummaryV1",
                version=1,
                required_fields=_SECTION_FIELDS,
                allowed_fields=_SECTION_FIELDS,
                max_depth=2,
                max_collection_items=8,
                max_utf8_bytes=4096,
            ),
        )

    @staticmethod
    def _validate_payload(payload: dict[str, object]) -> None:
        service_request_id = payload["service_request_id"]
        if not isinstance(service_request_id, str) or not service_request_id:
            raise IntegrityFailure("Inventory report SR identity is invalid")
        customer_org_id = payload["customer_org_id"]
        if customer_org_id is not None and (
            not isinstance(customer_org_id, str) or not customer_org_id
        ):
            raise IntegrityFailure("Inventory report Customer identity is invalid")
        for field in (
            "active_need_count",
            "spare_request_count",
            "rma_count",
            "open_return_obligation_count",
            "fault_tag_count",
            "unresolved_attention_count",
        ):
            value = payload[field]
            if type(value) is not int or value < 0:
                raise IntegrityFailure(f"Inventory report {field} is invalid")

    def stream_snapshot_rows(
        self,
        snapshot: Any,
        report_request: dict[str, object],
        as_of_utc: int,
    ) -> tuple[ReportSectionRow, ...]:
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("Inventory report as_of_utc must be nonnegative")
        connection = getattr(snapshot, "connection", None)
        if connection is None or not hasattr(connection, "execute"):
            raise ValidationError("Inventory report contributor requires a stable Snapshot")

        customer_filter = report_request.get("customer_org_id")
        if customer_filter is not None and (
            not isinstance(customer_filter, str) or not customer_filter
        ):
            raise ValidationError("Inventory report customer_org_id is invalid")

        rows = connection.execute(
            "SELECT sr.service_request_id,c.customer_org_id,"
            "(SELECT COUNT(*) FROM spare_needs n "
            " JOIN spare_need_current_projection np ON np.spare_need_id=n.spare_need_id "
            " WHERE n.service_request_id=sr.service_request_id "
            " AND np.lifecycle_state='active') AS active_need_count,"
            "(SELECT COUNT(*) FROM spare_requests rq "
            " WHERE rq.service_request_id=sr.service_request_id) AS request_count,"
            "(SELECT COUNT(*) FROM rmas rm JOIN spare_requests rq "
            " ON rq.spare_request_id=rm.spare_request_id "
            " WHERE rq.service_request_id=sr.service_request_id) AS rma_count,"
            "(SELECT COUNT(*) FROM rma_return_obligation_current ro "
            " JOIN rmas rm ON rm.rma_id=ro.rma_id "
            " JOIN spare_requests rq ON rq.spare_request_id=rm.spare_request_id "
            " WHERE rq.service_request_id=sr.service_request_id "
            " AND ro.obligation_state='open') AS open_return_count,"
            "(SELECT COUNT(DISTINCT fm.fault_tag_id) FROM fault_tag_memberships fm "
            " JOIN rmas rm ON rm.rma_id=fm.rma_id "
            " JOIN spare_requests rq ON rq.spare_request_id=rm.spare_request_id "
            " WHERE rq.service_request_id=sr.service_request_id) AS fault_tag_count,"
            "(SELECT COUNT(*) FROM inventory_attention_projection a "
            " WHERE (a.target_kind='spare_request' AND a.target_id IN "
            "   (SELECT rq.spare_request_id FROM spare_requests rq "
            "    WHERE rq.service_request_id=sr.service_request_id)) "
            " OR (a.target_kind='rma' AND a.target_id IN "
            "   (SELECT rm.rma_id FROM rmas rm JOIN spare_requests rq "
            "    ON rq.spare_request_id=rm.spare_request_id "
            "    WHERE rq.service_request_id=sr.service_request_id))) "
            " AS attention_count "
            "FROM service_requests sr "
            "LEFT JOIN sr_customer_relationships c "
            " ON c.service_request_id=sr.service_request_id "
            " AND c.relationship_state='active' "
            "WHERE EXISTS(SELECT 1 FROM spare_needs n "
            "             WHERE n.service_request_id=sr.service_request_id) "
            "   OR EXISTS(SELECT 1 FROM spare_requests rq "
            "             WHERE rq.service_request_id=sr.service_request_id) "
            "ORDER BY sr.service_request_id"
        ).fetchall()

        emitted: list[ReportSectionRow] = []
        descriptor = self.section_descriptor()
        for row in rows:
            sr_id = str(row[0])
            customer_id = None if row[1] is None else str(row[1])
            if customer_filter is not None and customer_id != customer_filter:
                continue
            payload = {
                "service_request_id": sr_id,
                "customer_org_id": customer_id,
                "active_need_count": int(row[2]),
                "spare_request_count": int(row[3]),
                "rma_count": int(row[4]),
                "open_return_obligation_count": int(row[5]),
                "fault_tag_count": int(row[6]),
                "unresolved_attention_count": int(row[7]),
            }
            self._validate_payload(payload)
            normalized = descriptor.payload_contract.validate(payload)
            emitted.append(
                ReportSectionRow(
                    canonical_row_key=sr_id,
                    payload=normalized,
                )
            )
        return tuple(emitted)


__all__ = ["InventoryReportSectionContributor"]
