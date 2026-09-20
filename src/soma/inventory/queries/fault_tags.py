from __future__ import annotations

from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ..repositories.fault_tags import InventoryFaultTagsRepository


class FaultTagQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def get_fault_tag(self, fault_tag_id: str) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        with ReadSnapshot(self._factory) as snapshot:
            return InventoryFaultTagsRepository.response(snapshot.connection, identity)

    def lineage(self, fault_tag_id: str) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        with ReadSnapshot(self._factory) as snapshot:
            authority = InventoryFaultTagsRepository.lineage_authority(
                snapshot.connection,
                identity,
            )
        return {
            "fault_tag_id": identity,
            "state": authority["state"],
            "projection_revision": authority["projection_revision"],
            "lineage_fingerprint": authority["fingerprint"],
            "correction_chain": [
                item
                for item in authority["lineage"]
                if item["relation_type"] == "corrects_replaces"
            ],
            "resend_edges": [
                item
                for item in authority["lineage"]
                if item["relation_type"] == "resend_of"
            ],
        }


__all__ = ["FaultTagQueryService"]
