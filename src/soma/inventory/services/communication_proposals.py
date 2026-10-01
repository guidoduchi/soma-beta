"""Inventory consumes Communications evidence through injected owner interfaces."""
from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes

from soma.inventory.domain.proposals import validate_fingerprint, validate_positive_revision


def normalize_communication_proposal(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"proposal_id", "proposal_revision", "proposal_fingerprint"}:
        raise ValidationError("Communication proposal reference has missing or unknown fields")
    return {"proposal_id": require_uuid4(value["proposal_id"]),
            "proposal_revision": validate_positive_revision(value["proposal_revision"]),
            "proposal_fingerprint": validate_fingerprint(value["proposal_fingerprint"])}


class InventoryCommunicationProposalBridge:
    def __init__(self, evidence_provider=None, disposition_participant=None):
        self._evidence = evidence_provider
        self._disposition = disposition_participant

    def validate(self, uow, reference, *, contract_id, target_type, target_id=None, facts, membership=None,
                 evidence_kind, evidence_id):
        if reference is None:
            return None
        if self._evidence is None or self._disposition is None:
            raise SomaError("DEPENDENCY_INDETERMINATE", "Communication proposal providers are unavailable")
        result = self._evidence.get_for_owner_command(uow, reference["proposal_id"], reference["proposal_revision"], reference["proposal_fingerprint"])
        if isinstance(result, str):
            if result == "STALE":
                raise SomaError("COMM_PROPOSAL_STALE", "Communication proposal evidence changed")
            if result == "INDETERMINATE":
                raise SomaError("DEPENDENCY_INDETERMINATE", "Communication proposal evidence is indeterminate")
            raise IntegrityFailure("Communication evidence provider returned an invalid status")
        if not isinstance(result, dict):
            raise IntegrityFailure("Communication evidence provider returned an invalid object")
        fields = {"proposal_id", "proposal_revision", "communication_id", "source_scope_id", "target_type", "target_id",
                  "target_revision", "proposal_contract_id", "proposal_contract_version", "payload", "source_fingerprint", "proposal_fingerprint"}
        try:
            if set(result) != fields or type(result["proposal_contract_version"]) is not int:
                raise ValidationError("Communication evidence has missing, unknown or mistyped fields")
            for name in ("proposal_id", "communication_id", "source_scope_id", "target_id"):
                require_uuid4(result[name])
            for name in ("proposal_revision", "target_revision", "proposal_contract_version"):
                validate_positive_revision(result[name])
            for name in ("source_fingerprint", "proposal_fingerprint"):
                validate_fingerprint(result[name])
        except ValidationError:
            raise IntegrityFailure("Communication evidence provider violated its closed contract") from None
        if (result.get("proposal_id") != reference["proposal_id"] or result.get("proposal_revision") != reference["proposal_revision"]
                or result.get("proposal_fingerprint") != reference["proposal_fingerprint"]):
            raise IntegrityFailure("Communication evidence provider changed the requested identity")
        expected = {"schema": contract_id, "facts": facts}
        if membership is not None:
            expected.update(membership_id=membership[0], membership_revision=membership[1])
        if (result.get("proposal_contract_id") != contract_id or result.get("proposal_contract_version") != 1
                or result.get("target_type") != target_type or (target_id is not None and result.get("target_id") != target_id)
                or canonical_json_bytes(result.get("payload")) != canonical_json_bytes(expected) or evidence_kind != ("indexed_sent" if target_type == "SPARE_REQUEST" else "indexed_received")
                or evidence_id != result.get("communication_id")):
            raise SomaError("COMM_PROPOSAL_STALE", "Owner command inputs differ from reviewed Communication facts")
        return result

    def record_accepted(self, uow, evidence, refs, command_id, actor_kind, actor_id):
        if evidence is None:
            return ()
        return self._disposition.record_accepted(uow, evidence["proposal_id"], evidence["proposal_revision"], refs,
                                                 {"command_id": command_id, "actor_kind": actor_kind, "actor_id": actor_id})
