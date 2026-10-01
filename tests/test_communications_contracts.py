from __future__ import annotations

import json

import pytest

from soma.communications.contracts.common import Chronology, TrackableIdentity
from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.contracts.source import ProviderCheckpoint
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4


def test_application_chronology_and_provider_checkpoint_have_separate_precision():
    chronology = Chronology(True, 1_800_000_001, "RECEIVED_TIME")
    checkpoint = ProviderCheckpoint("COMPOSITE", "eA", 1_800_000_001_123)
    assert chronology.to_response()["utc_epoch_seconds"] == 1_800_000_001
    assert checkpoint.to_response()["provider_time_source_epoch_ms"] == 1_800_000_001_123
    with pytest.raises(ValidationError):
        Chronology.from_value({"known": True, "utc_epoch_ms": 1_800_000_001_123, "source_kind": "RECEIVED_TIME"})
    with pytest.raises(ValidationError):
        Chronology(False, 123, "UNKNOWN")
    with pytest.raises(ValidationError):
        TrackableIdentity("CONTACT", new_uuid4(), 1, "name", "somebody", chronology)


def test_registry_accepts_exact_inventory_submission_fields_and_returns_detached_values():
    registry = CommunicationProposalContractRegistry()
    payload = {"schema": "COMM_INVENTORY_SUBMISSION_V1", "facts": {
        "schema": "INVENTORY_PROPOSAL_TARGET_V1", "expected_draft_fingerprint": "a" * 64,
        "effective_submission_at_utc": None,
    }}
    result = registry.validate("COMM_INVENTORY_SUBMISSION_V1", 1, "SPARE_REQUEST", payload)
    payload["facts"]["effective_submission_at_utc"] = 123
    assert result.owner_packet == "LLD-07"
    assert result.to_value()["facts"]["effective_submission_at_utc"] is None
    assert registry.is_link_contract("COMM_LINK_V1", 1)
    assert not registry.is_link_contract("COMM_INVENTORY_SUBMISSION_V1", 1)


@pytest.mark.parametrize("mutation", ["unknown", "wrong_target", "bool_version", "new_version", "message_body", "bool_time", "overflow_time"])
def test_registry_rejects_unowned_or_malformed_domain_fact(mutation):
    registry = CommunicationProposalContractRegistry()
    payload = {"schema": "COMM_INVENTORY_SUBMISSION_V1", "facts": {
        "schema": "INVENTORY_PROPOSAL_TARGET_V1", "expected_draft_fingerprint": "a" * 64,
        "effective_submission_at_utc": None,
    }}
    identity, version, target = "COMM_INVENTORY_SUBMISSION_V1", 1, "SPARE_REQUEST"
    if mutation == "unknown": identity = "invented"
    if mutation == "wrong_target": target = "RFC"
    if mutation == "bool_version": version = True
    if mutation == "new_version": version = 2
    if mutation == "message_body": payload["facts"]["body"] = "sensitive mail"
    if mutation == "bool_time": payload["facts"]["effective_submission_at_utc"] = True
    if mutation == "overflow_time": payload["facts"]["effective_submission_at_utc"] = 1 << 63
    with pytest.raises(ValidationError):
        registry.validate(identity, version, target, payload)


def test_final_decision_requires_reason_and_valid_exact_membership_revision():
    registry = CommunicationProposalContractRegistry()
    payload = {"schema": "COMM_INVENTORY_WAREHOUSE_DECISION_V1", "membership_id": new_uuid4(),
               "membership_revision": 1, "facts": {"schema": "INVENTORY_PROPOSAL_TARGET_V1",
               "decision": "rejected", "reason_code": None, "effective_at_utc": None}}
    with pytest.raises(ValidationError):
        registry.validate("COMM_INVENTORY_WAREHOUSE_DECISION_V1", 1, "FAULT_TAG", payload)
    for invalid in (" unreviewed ", "x\n", "\x00", "\U0001f600" * 100):
        payload["facts"]["reason_code"] = invalid
        with pytest.raises(ValidationError):
            registry.validate("COMM_INVENTORY_WAREHOUSE_DECISION_V1", 1, "FAULT_TAG", payload)
    payload["facts"]["reason_code"] = "DAMAGED"
    assert registry.validate("COMM_INVENTORY_WAREHOUSE_DECISION_V1", 1, "FAULT_TAG", payload)
    payload["membership_revision"] = True
    with pytest.raises(ValidationError):
        registry.validate("COMM_INVENTORY_WAREHOUSE_DECISION_V1", 1, "FAULT_TAG", payload)


def test_unknown_chronology_and_checkpoint_tokens_remain_explicit():
    assert Chronology(False, None, "UNKNOWN").to_response()["utc_epoch_seconds"] is None
    with pytest.raises(ValidationError):
        ProviderCheckpoint("POSITION", "../secret/path", None)


def test_source_authority_registry_has_accepted_overlays():
    from importlib.resources import files
    registry = json.loads(files("soma.communications.contracts").joinpath("registry.json").read_text(encoding="utf-8"))
    assert registry["design_sha"] == "9a0e891127a771251afccca1a281b7ef7dde9e5f"
    assert registry["proposal_contracts"]["status"] == "ACCEPTED_OWNER_CLARIFICATION"
    assert registry["leaves"]["migrations/0012-communications.json"]["sequence"] == 16
    method = next(x for x in registry["leaves"]["interfaces/cross-packet-v2.json"]["provided"] if x["name"] == "RfcTerminalCommunicationParticipant")["methods"][0]
    assert "after_key" in method and "limit<=500" in method


def test_link_match_rules_are_static_and_cannot_mislabel_an_alias_as_official():
    registry = CommunicationProposalContractRegistry()
    payload = {"schema": "COMM_LINK_V1", "matched_identity_kind": "SERVICE_REQUEST_LOCAL_ALIAS", "matched_identity_value": "LOCAL-SR-1",
               "match_rule_id": "COMM_EXACT_ALIAS_V1", "match_rule_version": 1, "confidence_basis": "EXACT_ALIAS"}
    assert registry.validate("COMM_LINK_V1", 1, "SERVICE_REQUEST", payload)
    for changes in ({"match_rule_id": "unregistered"}, {"match_rule_version": True}, {"match_rule_version": 2},
                    {"match_rule_id": "COMM_EXACT_IDENTIFIER_V1", "confidence_basis": "EXACT_IDENTIFIER"},
                    {"matched_identity_kind": "SERVICE_REQUEST_OFFICIAL"}):
        with pytest.raises(ValidationError):
            registry.validate("COMM_LINK_V1", 1, "SERVICE_REQUEST", {**payload, **changes})
