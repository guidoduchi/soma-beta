from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.contracts.common import Chronology, TrackableIdentity, UNKNOWN_CHRONOLOGY


@dataclass(frozen=True, slots=True)
class InitialBoundary:
    chronology: Chronology
    evidence_fingerprint: str
    identity_count: int
    unknown_identity_count: int


def initial_boundary(identities: Iterable[TrackableIdentity]) -> InitialBoundary:
    """Consume the owners' deterministic iterator without collecting its contents.

    Unknown chronology cannot be replaced with a discovery or command timestamp.
    The caller invokes this before any source-content operation.
    """
    digest = hashlib.sha256(b"SOMA_COMM_INITIAL_BOUNDARY_V1\x00")
    earliest: Chronology | None = None
    count = unknown = 0
    for identity in identities:
        if not isinstance(identity, TrackableIdentity):
            raise ValidationError("Initial boundary requires accepted typed owner identities")
        encoded = canonical_json_bytes({"target_type": identity.target_type, "target_id": identity.target_id,
                                        "target_revision": identity.target_revision, "identity_kind": identity.identity_kind,
                                        "normalized_value": identity.normalized_value,
                                        "effective_from": identity.effective_from.to_response()})
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
        if not identity.effective_from.known:
            unknown += 1
        elif earliest is None or identity.effective_from.utc_epoch_seconds < earliest.utc_epoch_seconds:
            earliest = identity.effective_from
    if not count:
        raise SomaError("COMM_NO_TRACKABLE_TARGETS", "No accepted operational identities are available")
    return InitialBoundary(UNKNOWN_CHRONOLOGY if unknown else earliest, digest.hexdigest(), count, unknown)
