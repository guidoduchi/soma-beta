from __future__ import annotations

from soma.ticket_import.reconciliation.engine import (
    LogicalField,
    LogicalFinding,
    LogicalRow,
    classify_replay,
    compute_logical_fingerprint,
    field_logical_sha256,
    row_logical_sha256,
)


def test_golden_empty_advanced_search_fingerprint() -> None:
    result = compute_logical_fingerprint(
        source_family="advanced_search_sr",
        source_profile_id="ADVANCED_SEARCH_SR_V1",
        header_registry_id="ADVANCED_SEARCH_HEADERS_V1",
        vocabulary_registry_id="ADVANCED_SEARCH_VOCAB_V1",
        parser_profile_id="ADVANCED_SEARCH_PARSER_V1",
        rows=(),
    )
    assert result.stream_bytes == 210
    assert result.logical_fingerprint_sha256 == "2a7ed9caf7a2c0a3c6355f7e76186d8436b6a75e98b85b485af67e1fbc34835a"


def test_golden_one_rfc_text_row_field_row_and_run_hashes() -> None:
    field = LogicalField(
        field_key="summary",
        field_class="active",
        value_state="usable",
        value_kind="text",
        normalized_text="Replace fan",
        source_text="Replace fan",
    )
    row = LogicalRow(
        identity_state="valid",
        entity_kind="rfc",
        canonical_primary_id="NC20260908000001",
        canonical_parent_rfc_no=None,
        fields=(field,),
    )
    assert field_logical_sha256(field) == "c7751983c7ba39e95786b3eedbf9f190916d294eb81d88c04b8c506b7ef0c6fa"
    assert row_logical_sha256(row) == "f604428c4027cdec5f9db8a3eb275aba0b9dcc1a71d434cdc173adab61500096"

    result = compute_logical_fingerprint(
        source_family="rfc_enhanced",
        source_profile_id="RFC_ENHANCED_V1",
        header_registry_id="RFC_HEADERS_V1",
        vocabulary_registry_id="RFC_VOCAB_V1",
        parser_profile_id="RFC_PARSER_V1",
        rows=(row,),
    )
    assert result.stream_bytes == 397
    assert result.logical_fingerprint_sha256 == "0752aff5cb09dd68133e02d27abd2f9c3701004c89883f93edf77a5f2efa49c6"
    assert result.variants[0].classification == "UNIQUE"
    assert result.variants[0].duplicate_count == 1
    assert result.variants[0].conflict_variant_count == 1


def test_golden_unknown_controlled_value_uses_deterministic_validation_token() -> None:
    field = LogicalField(
        field_key="status",
        field_class="active",
        value_state="unknown",
        value_kind="controlled",
        vocabulary_id="ADVANCED_SEARCH_STATUS_V1",
        source_text="mystery",
    )
    finding = LogicalFinding(
        finding_code="SOURCE_CONTROLLED_VALUE_UNKNOWN",
        severity="warning",
        scope_kind="field",
        field_key="status",
    )
    row = LogicalRow(
        identity_state="valid",
        entity_kind="service_request",
        canonical_primary_id="12345678",
        canonical_parent_rfc_no=None,
        fields=(field,),
        findings=(finding,),
    )
    assert field_logical_sha256(field) == "1a12565f1896219783aa0dfa2362602a00ab470731c2a8cdb4522083cc9eaf5f"
    assert row_logical_sha256(row) == "4f713d4db5ec2c58896c2307cad8e33a09032845af33dbc772eb1b34c39a7000"

    result = compute_logical_fingerprint(
        source_family="advanced_search_sr",
        source_profile_id="ADVANCED_SEARCH_SR_V1",
        header_registry_id="ADVANCED_SEARCH_HEADERS_V1",
        vocabulary_registry_id="ADVANCED_SEARCH_VOCAB_V1",
        parser_profile_id="ADVANCED_SEARCH_PARSER_V1",
        rows=(row,),
    )
    assert result.stream_bytes == 656
    assert result.logical_fingerprint_sha256 == "6d022861df6309b779ce0540d7ce065f386ad2dbda6c402c3a3c3e6836cae7cb"


def test_physical_row_order_is_irrelevant_and_duplicates_conflicts_are_deterministic() -> None:
    base = LogicalRow(
        identity_state="valid",
        entity_kind="service_request",
        canonical_primary_id="12345678",
        canonical_parent_rfc_no=None,
        fields=(
            LogicalField(
                field_key="problem_summary",
                field_class="active",
                value_state="usable",
                value_kind="text",
                source_text="A",
                normalized_text="A",
            ),
        ),
    )
    other = LogicalRow(
        identity_state="valid",
        entity_kind="service_request",
        canonical_primary_id="87654321",
        canonical_parent_rfc_no=None,
    )
    first = compute_logical_fingerprint(
        source_family="advanced_search_sr",
        source_profile_id="ADVANCED_SEARCH_SR_V1",
        header_registry_id="ADVANCED_SEARCH_HEADERS_V1",
        vocabulary_registry_id="ADVANCED_SEARCH_VOCAB_V1",
        parser_profile_id="ADVANCED_SEARCH_PARSER_V1",
        rows=(base, other),
    )
    reordered = compute_logical_fingerprint(
        source_family="advanced_search_sr",
        source_profile_id="ADVANCED_SEARCH_SR_V1",
        header_registry_id="ADVANCED_SEARCH_HEADERS_V1",
        vocabulary_registry_id="ADVANCED_SEARCH_VOCAB_V1",
        parser_profile_id="ADVANCED_SEARCH_PARSER_V1",
        rows=(other, base),
    )
    assert reordered.logical_fingerprint_sha256 == first.logical_fingerprint_sha256

    duplicate = compute_logical_fingerprint(
        source_family="advanced_search_sr",
        source_profile_id="ADVANCED_SEARCH_SR_V1",
        header_registry_id="ADVANCED_SEARCH_HEADERS_V1",
        vocabulary_registry_id="ADVANCED_SEARCH_VOCAB_V1",
        parser_profile_id="ADVANCED_SEARCH_PARSER_V1",
        rows=(base, base),
    )
    assert len(duplicate.variants) == 1
    assert duplicate.variants[0].classification == "EQUIVALENT_DUPLICATE"
    assert duplicate.variants[0].duplicate_count == 2
    assert duplicate.logical_fingerprint_sha256 != first.logical_fingerprint_sha256

    conflicting = LogicalRow(
        identity_state="valid",
        entity_kind="service_request",
        canonical_primary_id="12345678",
        canonical_parent_rfc_no=None,
        fields=(
            LogicalField(
                field_key="problem_summary",
                field_class="active",
                value_state="usable",
                value_kind="text",
                source_text="B",
                normalized_text="B",
            ),
        ),
    )
    conflict_result = compute_logical_fingerprint(
        source_family="advanced_search_sr",
        source_profile_id="ADVANCED_SEARCH_SR_V1",
        header_registry_id="ADVANCED_SEARCH_HEADERS_V1",
        vocabulary_registry_id="ADVANCED_SEARCH_VOCAB_V1",
        parser_profile_id="ADVANCED_SEARCH_PARSER_V1",
        rows=(conflicting, base),
    )
    assert len(conflict_result.variants) == 2
    assert {variant.classification for variant in conflict_result.variants} == {"CONFLICT_MEMBER"}
    assert {variant.conflict_variant_count for variant in conflict_result.variants} == {2}


def test_replay_classification_matrix() -> None:
    fingerprint = "a" * 64
    other = "b" * 64
    assert classify_replay(
        candidate_chronology=10,
        logical_fingerprint_sha256=fingerprint,
        checkpoint_chronology=None,
        checkpoint_logical_fingerprint_sha256=None,
    ) == "NEW_SOURCE"
    assert classify_replay(
        candidate_chronology=10,
        logical_fingerprint_sha256=fingerprint,
        checkpoint_chronology=10,
        checkpoint_logical_fingerprint_sha256=fingerprint,
    ) == "EXACT_REPLAY_NOOP"
    assert classify_replay(
        candidate_chronology=11,
        logical_fingerprint_sha256=fingerprint,
        checkpoint_chronology=10,
        checkpoint_logical_fingerprint_sha256=fingerprint,
    ) == "NEWER_IDENTICAL_NO_DOMAIN_CHANGE"
    assert classify_replay(
        candidate_chronology=10,
        logical_fingerprint_sha256=other,
        checkpoint_chronology=10,
        checkpoint_logical_fingerprint_sha256=fingerprint,
    ) == "CHRONOLOGY_CONTENT_CONFLICT"
    assert classify_replay(
        candidate_chronology=9,
        logical_fingerprint_sha256=other,
        checkpoint_chronology=10,
        checkpoint_logical_fingerprint_sha256=fingerprint,
    ) == "OLDER_SOURCE_RECOVERY_REQUIRED"
    assert classify_replay(
        candidate_chronology=11,
        logical_fingerprint_sha256=other,
        checkpoint_chronology=10,
        checkpoint_logical_fingerprint_sha256=fingerprint,
    ) == "NEW_SOURCE"
