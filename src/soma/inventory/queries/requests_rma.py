from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import loads_canonical_json, sha256_canonical_json

from ..repositories.requests import InventoryRequestsRepository


def _transport_state(value: str) -> str:
    mapping = {
        "draft": "draft",
        "submitted_awaiting_response": "submitted",
        "acknowledged": "submitted",
        "partially_authorized": "authorizing",
        "authorized": "authorized",
        "cancelled": "terminal",
        "rejected": "terminal",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise IntegrityFailure("Spare Request projection state is invalid") from exc


@dataclass(frozen=True, slots=True)
class SpareRequestDraftPayload:
    payload: dict[str, object]
    input_fingerprint: str


class InventoryRequestsQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = InventoryRequestsRepository()

    def get_spare_request(self, spare_request_id: str) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        with ReadSnapshot(self._factory) as snapshot:
            material = self._repository.draft_material(
                snapshot.connection,
                request_id,
            )
            requester = loads_canonical_json(
                str(material["requester_context_json"]),
                max_bytes=4096,
                max_depth=3,
                max_collection_items=16,
            )
            if not isinstance(requester, dict):
                raise IntegrityFailure("Persisted requester context is invalid")
            return {
                "spare_request_id": request_id,
                "local_handle": str(material["tracking_id"]),
                "official_sr7": material["current_sr7"],
                "requester": requester,
                "state": _transport_state(str(material["lifecycle_state"])),
                "revision": int(material["revision"]),
                "input_fingerprint": str(material["input_fingerprint"]),
                "draft": {
                    "allocations": [
                        {
                            "request_need_allocation_id": str(item["request_need_allocation_id"]),
                            "spare_need_id": str(item["spare_need_id"]),
                            "quantity": int(item["quantity"]),
                            "bom_code": str(item["bom_code"]),
                        }
                        for item in material["allocations"]
                    ],
                    "mode": str(material["mode"]),
                    "receiver_contact_id": str(material["receiver_contact_id"]),
                    "dispatch_location_id": str(material["dispatch_location_id"]),
                    "logistics_revision": int(material["logistics_revision"]),
                },
                "current_submission_snapshot_id": material[
                    "current_submission_snapshot_id"
                ],
                "submitted_quantity": int(material["submitted_quantity"]),
                "response_warning_start_utc": material["response_warning_start_utc"],
            }

    def spare_request_draft_payload(
        self,
        spare_request_id: str,
    ) -> SpareRequestDraftPayload:
        request_id = require_uuid4(spare_request_id)
        with ReadSnapshot(self._factory) as snapshot:
            material = self._repository.draft_material(
                snapshot.connection,
                request_id,
            )
            if str(material["lifecycle_state"]) != "draft":
                raise SomaError("REQUEST_NOT_DRAFT", "MSG draft payload requires current Draft state")
            reference = self._repository.submission_reference_context(
                snapshot.connection,
                receiver_contact_id=str(material["receiver_contact_id"]),
                dispatch_location_id=str(material["dispatch_location_id"]),
            )
            allocations = sorted(
                material["allocations"],
                key=lambda item: (
                    str(item["spare_need_id"]),
                    str(item["request_need_allocation_id"]),
                ),
            )
            payload: dict[str, object] = {
                "schema": "INVENTORY_SPARE_REQUEST_DRAFT_V1",
                "spare_request_id": request_id,
                "temporary_tracking_id": str(material["tracking_id"]),
                "service_request_id": str(material["service_request_id"]),
                "request_revision": int(material["revision"]),
                "request_input_fingerprint": str(material["input_fingerprint"]),
                "mode": str(material["mode"]),
                "receiver": {
                    "contact_id": str(reference["receiver_contact_id"]),
                    "display_name": str(reference["receiver_display_name_snapshot"]),
                    "contact_revision": int(
                        reference["receiver_contact_revision_at_submission"]
                    ),
                },
                "dispatch_location": {
                    "dispatch_location_id": str(reference["dispatch_location_id"]),
                    "name": str(reference["location_name_snapshot"]),
                    "address": str(reference["location_address_snapshot"]),
                    "revision": int(
                        reference["dispatch_location_revision_at_submission"]
                    ),
                },
                "allocations": [
                    {
                        "request_need_allocation_id": str(
                            item["request_need_allocation_id"]
                        ),
                        "spare_need_id": str(item["spare_need_id"]),
                        "quantity": int(item["quantity"]),
                        "requested_bom_code": str(item["bom_code"]),
                        "requested_bom_key": str(item["bom_key"]),
                    }
                    for item in allocations
                ],
            }
            return SpareRequestDraftPayload(
                payload=payload,
                input_fingerprint=sha256_canonical_json(payload),
            )


__all__ = ["InventoryRequestsQueryService", "SpareRequestDraftPayload"]
