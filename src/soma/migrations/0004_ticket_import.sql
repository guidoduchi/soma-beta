CREATE TABLE import_runs (
    import_run_id TEXT PRIMARY KEY,
    source_family TEXT NOT NULL CHECK(source_family IN ('advanced_search_sr','rfc_enhanced','wfm_service_provider')),
    invocation_kind TEXT NOT NULL CHECK(invocation_kind IN ('automatic','manual','recovery')),
    source_profile_id TEXT NOT NULL,
    header_registry_id TEXT NOT NULL,
    vocabulary_registry_id TEXT NOT NULL,
    parser_profile_id TEXT NOT NULL,
    candidate_filename TEXT NOT NULL CHECK(length(candidate_filename) > 0),
    candidate_file_size_bytes INTEGER NOT NULL CHECK(candidate_file_size_bytes >= 0),
    candidate_stable_mtime_ns INTEGER NOT NULL CHECK(candidate_stable_mtime_ns >= 0),
    candidate_chronology_kind TEXT NOT NULL CHECK(candidate_chronology_kind IN ('filesystem_mtime_ns','embedded_filename_timestamp_utc')),
    candidate_chronology_value INTEGER NOT NULL CHECK(candidate_chronology_value >= 0),
    logical_fingerprint_sha256 TEXT CHECK(logical_fingerprint_sha256 IS NULL OR length(logical_fingerprint_sha256) = 64),
    run_state TEXT NOT NULL CHECK(run_state IN ('discovering','validating','staged','waiting_review','partially_accepted','accepted','rejected','noop_pending_checkpoint','noop','recovery_required','failed')),
    started_at_utc INTEGER NOT NULL CHECK(started_at_utc >= 0),
    staged_at_utc INTEGER CHECK(staged_at_utc IS NULL OR staged_at_utc >= started_at_utc),
    completed_at_utc INTEGER CHECK(completed_at_utc IS NULL OR completed_at_utc >= started_at_utc),
    observed_row_count INTEGER NOT NULL DEFAULT 0 CHECK(observed_row_count >= 0),
    valid_identity_count INTEGER NOT NULL DEFAULT 0 CHECK(valid_identity_count >= 0),
    invalid_row_count INTEGER NOT NULL DEFAULT 0 CHECK(invalid_row_count >= 0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK(warning_count >= 0),
    proposal_count INTEGER NOT NULL DEFAULT 0 CHECK(proposal_count >= 0),
    pending_proposal_count INTEGER NOT NULL DEFAULT 0 CHECK(pending_proposal_count >= 0),
    accepted_proposal_count INTEGER NOT NULL DEFAULT 0 CHECK(accepted_proposal_count >= 0),
    rejected_proposal_count INTEGER NOT NULL DEFAULT 0 CHECK(rejected_proposal_count >= 0),
    deferred_proposal_count INTEGER NOT NULL DEFAULT 0 CHECK(deferred_proposal_count >= 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    CHECK(
        (run_state IN ('staged','waiting_review','partially_accepted','accepted','rejected','noop_pending_checkpoint','noop','recovery_required')
            AND logical_fingerprint_sha256 IS NOT NULL AND staged_at_utc IS NOT NULL)
        OR run_state IN ('discovering','validating','failed')
    ),
    CHECK(
        (run_state IN ('accepted','rejected','partially_accepted','noop','failed') AND completed_at_utc IS NOT NULL)
        OR
        (run_state NOT IN ('accepted','rejected','partially_accepted','noop','failed') AND completed_at_utc IS NULL)
    )
) STRICT;

CREATE TABLE import_source_checkpoints (
    source_family TEXT PRIMARY KEY CHECK(source_family IN ('advanced_search_sr','rfc_enhanced','wfm_service_provider')),
    source_profile_id TEXT NOT NULL,
    accepted_candidate_chronology_kind TEXT NOT NULL CHECK(accepted_candidate_chronology_kind IN ('filesystem_mtime_ns','embedded_filename_timestamp_utc')),
    accepted_candidate_chronology_value INTEGER NOT NULL CHECK(accepted_candidate_chronology_value >= 0),
    accepted_logical_fingerprint_sha256 TEXT NOT NULL CHECK(length(accepted_logical_fingerprint_sha256) = 64),
    accepted_import_run_id TEXT NOT NULL REFERENCES import_runs(import_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    last_checked_at_utc INTEGER NOT NULL CHECK(last_checked_at_utc >= 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0)
) STRICT;

CREATE TABLE import_recovery_reviews (
    import_recovery_review_id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES import_runs(import_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    checkpoint_import_run_id TEXT NOT NULL REFERENCES import_runs(import_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    review_ordinal INTEGER NOT NULL CHECK(review_ordinal > 0),
    run_revision INTEGER NOT NULL CHECK(run_revision > 0),
    checkpoint_revision INTEGER NOT NULL CHECK(checkpoint_revision > 0),
    review_fingerprint_sha256 TEXT NOT NULL CHECK(length(review_fingerprint_sha256) = 64),
    decision TEXT NOT NULL CHECK(decision IN ('authorized','rejected','deferred')),
    reason_category TEXT NOT NULL,
    occurred_at_utc INTEGER NOT NULL CHECK(occurred_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    UNIQUE(import_run_id, review_ordinal)
) STRICT;

CREATE TABLE import_recovery_events (
    import_recovery_event_id TEXT PRIMARY KEY,
    source_family TEXT NOT NULL CHECK(source_family IN ('advanced_search_sr','rfc_enhanced','wfm_service_provider')),
    import_run_id TEXT NOT NULL REFERENCES import_runs(import_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    prior_checkpoint_run_id TEXT NOT NULL REFERENCES import_runs(import_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    recovery_reason_category TEXT NOT NULL,
    review_fingerprint_sha256 TEXT NOT NULL CHECK(length(review_fingerprint_sha256) = 64),
    occurred_at_utc INTEGER NOT NULL CHECK(occurred_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE source_observations (
    source_observation_id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES import_runs(import_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    source_family TEXT NOT NULL CHECK(source_family IN ('advanced_search_sr','rfc_enhanced','wfm_service_provider')),
    entity_kind TEXT NOT NULL CHECK(entity_kind IN ('service_request','rfc','wfm','invalid_row')),
    identity_state TEXT NOT NULL CHECK(identity_state IN ('valid','invalid')),
    canonical_primary_id TEXT,
    canonical_parent_rfc_no TEXT,
    row_ordinal INTEGER NOT NULL CHECK(row_ordinal >= 1),
    sheet_ordinal INTEGER NOT NULL CHECK(sheet_ordinal >= 1),
    row_logical_sha256 TEXT NOT NULL CHECK(length(row_logical_sha256) = 64),
    source_row_chronology_utc INTEGER CHECK(source_row_chronology_utc IS NULL OR source_row_chronology_utc >= 0),
    presence_state TEXT NOT NULL CHECK(presence_state IN ('observed_valid_identity','observed_invalid_identity')),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    CHECK(
        (identity_state = 'valid' AND entity_kind IN ('service_request','rfc','wfm') AND canonical_primary_id IS NOT NULL AND presence_state = 'observed_valid_identity')
        OR
        (identity_state = 'invalid' AND entity_kind = 'invalid_row' AND canonical_primary_id IS NULL AND canonical_parent_rfc_no IS NULL AND presence_state = 'observed_invalid_identity')
    ),
    CHECK(
        (source_family = 'advanced_search_sr' AND entity_kind IN ('service_request','invalid_row'))
        OR (source_family = 'rfc_enhanced' AND entity_kind IN ('rfc','invalid_row'))
        OR (source_family = 'wfm_service_provider' AND entity_kind IN ('wfm','invalid_row'))
    ),
    CHECK((entity_kind = 'wfm' AND canonical_parent_rfc_no IS NOT NULL) OR entity_kind <> 'wfm')
) STRICT;

CREATE TABLE source_observation_fields (
    source_observation_field_id TEXT PRIMARY KEY,
    source_observation_id TEXT NOT NULL REFERENCES source_observations(source_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    field_key TEXT NOT NULL,
    field_class TEXT NOT NULL CHECK(field_class IN ('active','deferred')),
    value_state TEXT NOT NULL CHECK(value_state IN ('usable','blank','unknown','malformed')),
    value_kind TEXT NOT NULL CHECK(value_kind IN ('text','controlled','instant','duration_seconds')),
    source_text TEXT,
    normalized_text TEXT,
    integer_value INTEGER,
    vocabulary_id TEXT,
    field_logical_sha256 TEXT NOT NULL CHECK(length(field_logical_sha256) = 64),
    CHECK(
        (value_state = 'usable' AND value_kind IN ('text','controlled') AND source_text IS NOT NULL AND normalized_text IS NOT NULL AND integer_value IS NULL)
        OR
        (value_state = 'usable' AND value_kind IN ('instant','duration_seconds') AND source_text IS NOT NULL AND normalized_text IS NULL AND integer_value IS NOT NULL)
        OR
        (value_state <> 'usable' AND normalized_text IS NULL AND integer_value IS NULL)
    ),
    CHECK((value_kind = 'controlled' AND vocabulary_id IS NOT NULL) OR (value_kind <> 'controlled' AND vocabulary_id IS NULL))
) STRICT;

CREATE TABLE import_findings (
    import_finding_id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES import_runs(import_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    source_observation_id TEXT REFERENCES source_observations(source_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    field_key TEXT,
    finding_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('info','warning','error','high_risk')),
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('workbook','sheet','row','field','identity','chronology','replay','proposal','population')),
    message_text TEXT NOT NULL CHECK(length(message_text) > 0),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0)
) STRICT;

CREATE TABLE reconciliation_proposals (
    reconciliation_proposal_id TEXT PRIMARY KEY,
    import_run_id TEXT NOT NULL REFERENCES import_runs(import_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    evidence_mode TEXT NOT NULL CHECK(evidence_mode IN ('observed_row','population_absence')),
    source_observation_id TEXT REFERENCES source_observations(source_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    prior_source_observation_id TEXT REFERENCES source_observations(source_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    proposal_kind TEXT NOT NULL CHECK(proposal_kind IN ('sr_create_or_adopt','sr_source_projection','sr_customer_reconciliation','sr_contact_reconciliation','sr_current_handler_reconciliation','sr_source_disappearance_review','sr_terminal_reversal_review','sr_suspension_regression_review','rfc_create_or_adopt','rfc_source_projection','rfc_customer_reconciliation','sr_rfc_link_candidate','wfm_create_or_adopt','wfm_source_projection','wfm_provisional_rfc','wfm_provisional_eligibility','wfm_plan_reconciliation','wfm_competing_attempt_review')),
    target_kind TEXT NOT NULL CHECK(target_kind IN ('service_request','rfc','wfm','customer_organization','contact','source_presence','sr_rfc_relationship','task_plan','activity_lineage')),
    target_internal_id TEXT,
    target_business_id TEXT,
    risk_class TEXT NOT NULL CHECK(risk_class IN ('low','medium','high','blocked')),
    base_state_token_sha256 TEXT NOT NULL CHECK(length(base_state_token_sha256) = 64),
    proposal_fingerprint_sha256 TEXT NOT NULL CHECK(length(proposal_fingerprint_sha256) = 64),
    proposal_state TEXT NOT NULL CHECK(proposal_state IN ('pending','accepted','rejected','deferred','superseded','no_change')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    decided_at_utc INTEGER,
    CHECK((proposal_state = 'pending' AND decided_at_utc IS NULL) OR (proposal_state <> 'pending' AND decided_at_utc IS NOT NULL)),
    CHECK((evidence_mode = 'observed_row' AND source_observation_id IS NOT NULL) OR (evidence_mode = 'population_absence' AND source_observation_id IS NULL AND prior_source_observation_id IS NOT NULL)),
    CHECK(proposal_kind <> 'sr_source_disappearance_review' OR evidence_mode = 'population_absence'),
    CHECK(proposal_kind = 'sr_source_disappearance_review' OR evidence_mode = 'observed_row')
) STRICT;

CREATE TABLE reconciliation_proposal_changes (
    reconciliation_proposal_id TEXT NOT NULL REFERENCES reconciliation_proposals(reconciliation_proposal_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    field_key TEXT NOT NULL,
    change_kind TEXT NOT NULL CHECK(change_kind IN ('create','set','clear','link','unlink','adopt','candidate','conflict','absent','reappear')),
    value_kind TEXT NOT NULL CHECK(value_kind IN ('none','text','controlled','instant','duration_seconds','identity')),
    before_text TEXT,
    after_text TEXT,
    before_integer INTEGER,
    after_integer INTEGER,
    source_observation_field_id TEXT REFERENCES source_observation_fields(source_observation_field_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    PRIMARY KEY(reconciliation_proposal_id, ordinal),
    CHECK((value_kind IN ('none','text','controlled','identity') AND before_integer IS NULL AND after_integer IS NULL) OR value_kind IN ('instant','duration_seconds'))
) STRICT;

CREATE TABLE proposal_dispositions (
    proposal_disposition_id TEXT PRIMARY KEY,
    reconciliation_proposal_id TEXT NOT NULL REFERENCES reconciliation_proposals(reconciliation_proposal_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected','deferred','superseded','no_change')),
    proposal_revision INTEGER NOT NULL CHECK(proposal_revision > 0),
    proposal_fingerprint_sha256 TEXT NOT NULL CHECK(length(proposal_fingerprint_sha256) = 64),
    base_state_token_sha256 TEXT NOT NULL CHECK(length(base_state_token_sha256) = 64),
    reason_category TEXT,
    decision_origin TEXT NOT NULL CHECK(decision_origin IN ('operator','replay_engine','recovery','system_no_change')),
    occurred_at_utc INTEGER NOT NULL CHECK(occurred_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE proposal_equivalence_decisions (
    proposal_equivalence_decision_id TEXT PRIMARY KEY,
    proposal_kind TEXT NOT NULL,
    target_internal_id TEXT,
    target_business_id TEXT,
    material_input_fingerprint_sha256 TEXT NOT NULL CHECK(length(material_input_fingerprint_sha256) = 64),
    decision TEXT NOT NULL CHECK(decision IN ('rejected','deferred')),
    source_proposal_id TEXT NOT NULL REFERENCES reconciliation_proposals(reconciliation_proposal_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX idx_import_runs_family_state ON import_runs(source_family, run_state, started_at_utc, import_run_id);
CREATE INDEX idx_import_runs_family_chronology ON import_runs(source_family, candidate_chronology_value, import_run_id);
CREATE INDEX idx_import_runs_fingerprint ON import_runs(source_family, logical_fingerprint_sha256, import_run_id);
CREATE INDEX idx_import_checkpoint_run_fk ON import_source_checkpoints(accepted_import_run_id, source_family);
CREATE INDEX idx_import_recovery_review_run_fk ON import_recovery_reviews(import_run_id, review_ordinal, import_recovery_review_id);
CREATE INDEX idx_import_recovery_review_checkpoint_fk ON import_recovery_reviews(checkpoint_import_run_id, import_recovery_review_id);
CREATE INDEX idx_import_recovery_review_command_fk ON import_recovery_reviews(command_id, import_recovery_review_id);
CREATE INDEX idx_import_recovery_run_fk ON import_recovery_events(import_run_id, import_recovery_event_id);
CREATE INDEX idx_import_recovery_prior_fk ON import_recovery_events(prior_checkpoint_run_id, import_recovery_event_id);
CREATE INDEX idx_import_recovery_command_fk ON import_recovery_events(command_id, import_recovery_event_id);
CREATE INDEX idx_source_observation_run ON source_observations(import_run_id, sheet_ordinal, row_ordinal, source_observation_id);
CREATE INDEX idx_source_observation_identity ON source_observations(source_family, identity_state, canonical_primary_id, import_run_id, source_observation_id);
CREATE INDEX idx_source_observation_parent ON source_observations(canonical_parent_rfc_no, import_run_id, source_observation_id) WHERE canonical_parent_rfc_no IS NOT NULL;
CREATE UNIQUE INDEX uq_source_observation_field ON source_observation_fields(source_observation_id, field_key);
CREATE INDEX idx_finding_run ON import_findings(import_run_id, severity, import_finding_id);
CREATE INDEX idx_finding_observation_fk ON import_findings(source_observation_id, import_finding_id);
CREATE INDEX idx_proposal_run_state ON reconciliation_proposals(import_run_id, proposal_state, risk_class, reconciliation_proposal_id);
CREATE INDEX idx_proposal_target ON reconciliation_proposals(target_kind, target_internal_id, target_business_id, proposal_state, reconciliation_proposal_id);
CREATE INDEX idx_proposal_observation_fk ON reconciliation_proposals(source_observation_id, reconciliation_proposal_id);
CREATE INDEX idx_proposal_prior_observation_fk ON reconciliation_proposals(prior_source_observation_id, reconciliation_proposal_id);
CREATE INDEX idx_proposal_change_field_fk ON reconciliation_proposal_changes(source_observation_field_id, reconciliation_proposal_id, ordinal);
CREATE INDEX idx_disposition_proposal_fk ON proposal_dispositions(reconciliation_proposal_id, occurred_at_utc, proposal_disposition_id);
CREATE INDEX idx_disposition_command_fk ON proposal_dispositions(command_id, proposal_disposition_id);
CREATE INDEX idx_equivalence_target ON proposal_equivalence_decisions(proposal_kind, target_internal_id, target_business_id, material_input_fingerprint_sha256, proposal_equivalence_decision_id);
CREATE INDEX idx_equivalence_source_fk ON proposal_equivalence_decisions(source_proposal_id, proposal_equivalence_decision_id);
CREATE INDEX idx_equivalence_command_fk ON proposal_equivalence_decisions(command_id, proposal_equivalence_decision_id);

CREATE TRIGGER import_runs_update_guard
BEFORE UPDATE ON import_runs
BEGIN
    SELECT CASE WHEN
        NEW.import_run_id <> OLD.import_run_id
        OR NEW.source_family <> OLD.source_family
        OR NEW.invocation_kind <> OLD.invocation_kind
        OR NEW.source_profile_id <> OLD.source_profile_id
        OR NEW.header_registry_id <> OLD.header_registry_id
        OR NEW.vocabulary_registry_id <> OLD.vocabulary_registry_id
        OR NEW.parser_profile_id <> OLD.parser_profile_id
        OR NEW.candidate_filename <> OLD.candidate_filename
        OR NEW.candidate_file_size_bytes <> OLD.candidate_file_size_bytes
        OR NEW.candidate_stable_mtime_ns <> OLD.candidate_stable_mtime_ns
        OR NEW.candidate_chronology_kind <> OLD.candidate_chronology_kind
        OR NEW.candidate_chronology_value <> OLD.candidate_chronology_value
        OR NEW.started_at_utc <> OLD.started_at_utc
        OR NEW.revision <> OLD.revision + 1
    THEN RAISE(ABORT, 'IMPORT_RUN_IMMUTABLE_PROVENANCE') END;

    SELECT CASE WHEN OLD.run_state NOT IN ('discovering','validating')
        AND (
            NEW.logical_fingerprint_sha256 IS NOT OLD.logical_fingerprint_sha256
            OR NEW.staged_at_utc IS NOT OLD.staged_at_utc
        )
    THEN RAISE(ABORT, 'IMPORT_RUN_IMMUTABLE_PROVENANCE') END;

    SELECT CASE WHEN OLD.run_state IN ('accepted','rejected','partially_accepted','noop','failed')
    THEN RAISE(ABORT, 'IMPORT_RUN_TERMINAL') END;

    SELECT CASE WHEN NOT (
        (OLD.run_state = 'discovering' AND NEW.run_state IN ('validating','failed'))
        OR
        (OLD.run_state = 'validating' AND NEW.run_state IN ('staged','waiting_review','noop_pending_checkpoint','noop','recovery_required','failed'))
        OR
        (OLD.run_state IN ('staged','waiting_review') AND NEW.run_state IN ('waiting_review','accepted','rejected','partially_accepted'))
        OR
        (OLD.run_state = 'noop_pending_checkpoint' AND NEW.run_state = 'noop')
        OR
        (OLD.run_state = 'recovery_required' AND NEW.run_state IN ('recovery_required','accepted','rejected','partially_accepted'))
    ) THEN RAISE(ABORT, 'IMPORT_RUN_TRANSITION_INVALID') END;
END;

CREATE TRIGGER import_runs_delete_guard
BEFORE DELETE ON import_runs
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_RUN_DELETE_FORBIDDEN');
END;

CREATE TRIGGER import_checkpoint_update_guard
BEFORE UPDATE ON import_source_checkpoints
BEGIN
    SELECT CASE WHEN NEW.source_family <> OLD.source_family OR NEW.revision <> OLD.revision + 1
    THEN RAISE(ABORT, 'IMPORT_CHECKPOINT_STALE') END;
END;

CREATE TRIGGER import_checkpoint_delete_guard
BEFORE DELETE ON import_source_checkpoints
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_CHECKPOINT_DELETE_FORBIDDEN');
END;

CREATE TRIGGER import_recovery_review_update_guard
BEFORE UPDATE ON import_recovery_reviews
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_RECOVERY_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER import_recovery_review_delete_guard
BEFORE DELETE ON import_recovery_reviews
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_RECOVERY_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER import_recovery_event_update_guard
BEFORE UPDATE ON import_recovery_events
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_RECOVERY_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER import_recovery_event_delete_guard
BEFORE DELETE ON import_recovery_events
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_RECOVERY_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER source_observation_update_guard
BEFORE UPDATE ON source_observations
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_SOURCE_EVIDENCE_APPEND_ONLY');
END;

CREATE TRIGGER source_observation_delete_guard
BEFORE DELETE ON source_observations
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM import_runs
        WHERE import_run_id = OLD.import_run_id
          AND run_state IN ('discovering','validating','failed')
    ) THEN RAISE(ABORT, 'IMPORT_SOURCE_EVIDENCE_APPEND_ONLY') END;
END;

CREATE TRIGGER source_observation_field_update_guard
BEFORE UPDATE ON source_observation_fields
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_SOURCE_EVIDENCE_APPEND_ONLY');
END;

CREATE TRIGGER source_observation_field_delete_guard
BEFORE DELETE ON source_observation_fields
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM source_observations o
        JOIN import_runs r ON r.import_run_id = o.import_run_id
        WHERE o.source_observation_id = OLD.source_observation_id
          AND r.run_state IN ('discovering','validating','failed')
    ) THEN RAISE(ABORT, 'IMPORT_SOURCE_EVIDENCE_APPEND_ONLY') END;
END;

CREATE TRIGGER import_finding_update_guard
BEFORE UPDATE ON import_findings
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_SOURCE_EVIDENCE_APPEND_ONLY');
END;

CREATE TRIGGER import_finding_delete_guard
BEFORE DELETE ON import_findings
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM import_runs
        WHERE import_run_id = OLD.import_run_id
          AND run_state IN ('discovering','validating','failed')
    ) THEN RAISE(ABORT, 'IMPORT_SOURCE_EVIDENCE_APPEND_ONLY') END;
END;

CREATE TRIGGER reconciliation_proposal_update_guard
BEFORE UPDATE ON reconciliation_proposals
BEGIN
    SELECT CASE WHEN
        OLD.proposal_state <> 'pending'
        OR NEW.reconciliation_proposal_id <> OLD.reconciliation_proposal_id
        OR NEW.import_run_id <> OLD.import_run_id
        OR NEW.evidence_mode <> OLD.evidence_mode
        OR NEW.source_observation_id IS NOT OLD.source_observation_id
        OR NEW.prior_source_observation_id IS NOT OLD.prior_source_observation_id
        OR NEW.proposal_kind <> OLD.proposal_kind
        OR NEW.target_kind <> OLD.target_kind
        OR NEW.target_internal_id IS NOT OLD.target_internal_id
        OR NEW.target_business_id IS NOT OLD.target_business_id
        OR NEW.risk_class <> OLD.risk_class
        OR NEW.base_state_token_sha256 <> OLD.base_state_token_sha256
        OR NEW.proposal_fingerprint_sha256 <> OLD.proposal_fingerprint_sha256
        OR NEW.created_at_utc <> OLD.created_at_utc
        OR NEW.revision <> OLD.revision + 1
        OR NEW.proposal_state NOT IN ('accepted','rejected','deferred','superseded','no_change')
        OR NEW.decided_at_utc IS NULL
    THEN RAISE(ABORT, 'IMPORT_PROPOSAL_HISTORY_APPEND_ONLY') END;

    SELECT CASE WHEN OLD.risk_class = 'blocked' AND NEW.proposal_state = 'accepted'
    THEN RAISE(ABORT, 'IMPORT_PROPOSAL_BLOCKED') END;
END;

CREATE TRIGGER reconciliation_proposal_delete_guard
BEFORE DELETE ON reconciliation_proposals
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_PROPOSAL_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER reconciliation_proposal_change_update_guard
BEFORE UPDATE ON reconciliation_proposal_changes
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_PROPOSAL_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER reconciliation_proposal_change_delete_guard
BEFORE DELETE ON reconciliation_proposal_changes
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_PROPOSAL_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER proposal_disposition_update_guard
BEFORE UPDATE ON proposal_dispositions
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_PROPOSAL_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER proposal_disposition_delete_guard
BEFORE DELETE ON proposal_dispositions
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_PROPOSAL_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER proposal_equivalence_update_guard
BEFORE UPDATE ON proposal_equivalence_decisions
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_PROPOSAL_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER proposal_equivalence_delete_guard
BEFORE DELETE ON proposal_equivalence_decisions
BEGIN
    SELECT RAISE(ABORT, 'IMPORT_PROPOSAL_HISTORY_APPEND_ONLY');
END;
