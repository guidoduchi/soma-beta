from __future__ import annotations

import hashlib

from soma.foundation.errors import IntegrityFailure
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.contracts.common import TrackableIdentity


def identity_evidence(identities):
    """Stream the same owner export order used by immutable matching runs."""
    digest = hashlib.sha256(b"SOMA_COMM_TARGET_COVERAGE_IDENTITIES_V1\x00")
    count, earliest, unknown = 0, None, False
    for identity in identities:
        if not isinstance(identity, TrackableIdentity):
            raise IntegrityFailure("Summary coverage requires typed owner identity evidence")
        encoded = canonical_json_bytes([identity.target_type, identity.target_id, identity.target_revision,
            identity.identity_kind, identity.normalized_value, identity.effective_from.to_response()])
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
        if not identity.effective_from.known:
            unknown = True
        elif earliest is None or identity.effective_from.utc_epoch_seconds < earliest:
            earliest = identity.effective_from.utc_epoch_seconds
    return digest.hexdigest(), count, None if unknown else earliest


def summary_direction(received, sent, unknown):
    if received and sent:
        return "MIXED"
    if unknown:
        return "UNKNOWN"
    return "RECEIVED" if received else "SENT" if sent else "UNKNOWN"
