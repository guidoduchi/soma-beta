from __future__ import annotations

from soma.foundation.errors import IntegrityFailure
from soma.foundation.strict_json import loads_canonical_json

from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.contracts.common import fingerprint, integer
from soma.communications.domain.proposals import proposal_fingerprint, source_fingerprint
from soma.communications.repositories.sources import one, scope
from soma.communications.services.proposals import proposal

_INVENTORY = {
    "COMM_INVENTORY_SUBMISSION_V1": ("spare_request_submission", "spare_request", "indexed_sent", "normal"),
    "COMM_INVENTORY_WAREHOUSE_RECEIPT_V1": ("warehouse_received", "fault_tag_membership", "indexed_received", "normal"),
    "COMM_INVENTORY_WAREHOUSE_DECISION_V1": ("warehouse_final_decision", "fault_tag_membership", "indexed_received", "material_final"),
}


def inventory_proposal_inputs(evidence):
    kind, target_kind, evidence_kind, risk = _INVENTORY[evidence["proposal_contract_id"]]
    payload = evidence["payload"]
    membership = target_kind == "fault_tag_membership"
    return {
        "proposal_kind": kind,
        "target_refs": [{"proposal_target_id": evidence["proposal_id"], "target_kind": target_kind,
                         "target_id": payload["membership_id"] if membership else evidence["target_id"],
                         "expected_revision": payload["membership_revision"] if membership else evidence["target_revision"],
                         "proposed_action": kind, "payload": payload["facts"]}],
        "evidence_ref": {"evidence_kind": evidence_kind, "evidence_id": evidence["communication_id"], "risk_tier": risk},
    }


class CommunicationProposalEvidenceProvider:
    def __init__(self, identity_providers, inventory_target_provider=None):
        self._identities = identity_providers
        self._inventory = inventory_target_provider
        self._contracts = CommunicationProposalContractRegistry()

    def get_for_owner_command(self, uow, proposal_id, proposal_revision, expected_fingerprint):
        integer(proposal_revision, minimum=1)
        fingerprint(expected_fingerprint)
        row = proposal(uow, proposal_id)
        if (row is None or row["revision"] != proposal_revision or row["proposal_fingerprint"] != expected_fingerprint
                or row["state"] not in {"PENDING", "DEFERRED"}):
            return "STALE"
        message = one(uow,
                      "SELECT communication_id,source_scope_id,identity_state,provider_identity_digest,fallback_digest,"
                      "fallback_version,content_revision,direction,chronology_known,chronology_utc,chronology_source_kind,content_state "
                      "FROM communications WHERE communication_id=?", (row["communication_id"],))
        source = None if message is None else scope(uow, message["source_scope_id"])
        if message is None or source is None:
            raise IntegrityFailure("Communication proposal lost its source authority")
        if message["content_state"] != "RETAINED" or source_fingerprint(message, source["revision"]) != row["source_fingerprint"]:
            return "STALE"
        payload = self._contracts.validate(
            row["proposal_contract_id"], row["proposal_contract_version"], row["target_type"],
            loads_canonical_json(row["payload_json"], max_bytes=4096, max_depth=4, max_collection_items=32),
        )
        if proposal_fingerprint(row["source_fingerprint"], row["target_id"], row["target_revision"], payload) != row["proposal_fingerprint"]:
            raise IntegrityFailure("Communication proposal fingerprint disagrees with its immutable evidence")
        state = self._identities.validate_revision(uow, row["target_type"], row["target_id"], row["target_revision"])
        if state != "VALID":
            return "STALE" if state == "INVALID" else "INDETERMINATE"
        evidence = {
            "proposal_id": row["communication_proposal_id"], "proposal_revision": row["revision"],
            "communication_id": row["communication_id"], "source_scope_id": message["source_scope_id"],
            "target_type": row["target_type"], "target_id": row["target_id"], "target_revision": row["target_revision"],
            "proposal_contract_id": payload.contract_id, "proposal_contract_version": payload.contract_version,
            "payload": payload.to_value(), "source_fingerprint": row["source_fingerprint"], "proposal_fingerprint": row["proposal_fingerprint"],
        }
        if payload.contract_id in _INVENTORY:
            if payload.contract_id == "COMM_INVENTORY_SUBMISSION_V1" and message["direction"] != "SENT":
                return "STALE"
            if self._inventory is None:
                return "INDETERMINATE"
            impact = self._inventory.preview(uow, **inventory_proposal_inputs(evidence))
            if impact.get("status") != "READY":
                return "STALE" if impact.get("reason_code") in {"PROPOSAL_STALE", "INV_STALE", "WAREHOUSE_RECEIPT_REQUIRED", "BULK_INCOMPATIBLE"} else "INDETERMINATE"
            if payload.target_type == "FAULT_TAG" and impact["targets"][0].get("fault_tag_id") != row["target_id"]:
                return "STALE"
        return evidence
