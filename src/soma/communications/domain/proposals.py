from __future__ import annotations

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json

from soma.communications.contracts.common import Chronology, fingerprint, integer
from soma.communications.contracts.proposal import ValidatedProposalPayload


def source_fingerprint(message: dict, source_revision: int) -> str:
    provider = message["provider_identity_digest"]
    selected = provider if provider is not None else message["fallback_digest"]
    if selected is None:
        raise IntegrityFailure("Communication proposal has no immutable identity evidence")
    version = message["fallback_version"]
    if version is None:
        raise IntegrityFailure("Communication proposal has no canonicalization version")
    return sha256_canonical_json({
        "schema": "SOMA_COMM_PROPOSAL_SOURCE_V1", "communication_id": require_uuid4(message["communication_id"]),
        "source_scope_id": require_uuid4(message["source_scope_id"]), "source_revision": integer(source_revision, minimum=1),
        "identity_state": message["identity_state"], "canonicalization_version": integer(version, minimum=1),
        "identity_digest": fingerprint(selected), "content_revision": integer(message["content_revision"], minimum=1),
        "direction": message["direction"],
        "chronology": Chronology(bool(message["chronology_known"]), message["chronology_utc"], message["chronology_source_kind"]).to_response(),
    })


def proposal_fingerprint(source: str, target_id: str, target_revision: int, payload: ValidatedProposalPayload) -> str:
    return sha256_canonical_json({
        "schema": "SOMA_COMM_PROPOSAL_V1", "source_fingerprint": fingerprint(source),
        "target_type": payload.target_type, "target_id": require_uuid4(target_id), "target_revision": integer(target_revision, minimum=1),
        "proposal_contract_id": payload.contract_id, "proposal_contract_version": payload.contract_version,
        "payload": payload.to_value(),
    })
