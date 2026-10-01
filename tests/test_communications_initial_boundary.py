import pytest

from soma.communications.contracts.common import Chronology, TrackableIdentity, UNKNOWN_CHRONOLOGY
from soma.communications.domain.initial_boundary import initial_boundary
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4


def target(instant):
    return TrackableIdentity("SERVICE_REQUEST", new_uuid4(), 1, "OFFICIAL_SR", "123456789",
                             UNKNOWN_CHRONOLOGY if instant is None else Chronology(True, instant, "OTHER_PROVIDER_TIME"))


def test_lld09_a004_no_targets_stops_without_source_io():
    with pytest.raises(SomaError) as raised:
        initial_boundary(iter(()))
    assert raised.value.code == "COMM_NO_TRACKABLE_TARGETS"


def test_lld09_a008_known_initial_boundary_uses_oldest_supported_time():
    identities = (target(400), target(100), target(200))
    result = initial_boundary(iter(identities))
    assert result.chronology.utc_epoch_seconds == 100
    assert result.identity_count == 3 and result.unknown_identity_count == 0
    assert result.evidence_fingerprint == initial_boundary(iter(identities)).evidence_fingerprint
    changed = identities[:1] + (target(50),) + identities[2:]
    assert result.evidence_fingerprint != initial_boundary(iter(changed)).evidence_fingerprint


def test_lld09_a009_a010_unknown_boundary_remains_unknown():
    result = initial_boundary(iter((target(100), target(None))))
    assert result.chronology == UNKNOWN_CHRONOLOGY
    assert result.unknown_identity_count == 1
    with pytest.raises(ValidationError):
        initial_boundary(iter(({"target_type": "CONTACT"},)))
