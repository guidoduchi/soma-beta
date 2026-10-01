from __future__ import annotations

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4


def classify_target_dependency(reader, target_type: str, target_id: str) -> str:
    """One exact indexed predicate for preview and current-writer validation.

    Closed links and disposed proposals still reference surviving protected
    Communications history. Purging content does not make that history disappear.
    """
    require_uuid4(target_id)
    blocked = reader.connection.execute(
        "SELECT EXISTS(SELECT 1 FROM communication_links WHERE target_type=? AND target_id=?) "
        "OR EXISTS(SELECT 1 FROM communication_proposals WHERE target_type=? AND target_id=?) "
        "OR EXISTS(SELECT 1 FROM communication_msg_drafts WHERE origin_target_type=? AND origin_target_id=?) "
        "OR EXISTS(SELECT 1 FROM communication_terminal_summaries WHERE target_type=? AND target_id=?)",
        (target_type, target_id) * 4,
    ).fetchone()[0]
    return "BLOCKED" if blocked else "CLEAR"


class InventoryCommunicationDependencyProvider:
    @staticmethod
    def classify_inventory_hard_delete_dependency(reader, target_type: str, target_id: str) -> str:
        # The accepted Inventory implementation exports its lower-case domain
        # kind; Communications transport uses the corresponding closed enum.
        kinds = {"spare_request": "SPARE_REQUEST", "fault_tag": "FAULT_TAG",
                 "SPARE_REQUEST": "SPARE_REQUEST", "FAULT_TAG": "FAULT_TAG"}
        if not isinstance(target_type, str) or target_type not in kinds:
            raise ValidationError("Inventory Communication dependency target is unsupported")
        return classify_target_dependency(reader, kinds[target_type], target_id)
