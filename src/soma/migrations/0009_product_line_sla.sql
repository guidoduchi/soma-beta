CREATE TABLE product_lines (
    product_line_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name)>0),
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE contracts (
    contract_id TEXT PRIMARY KEY,
    customer_org_id TEXT NOT NULL REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK(length(name)>0),
    contract_reference TEXT NOT NULL CHECK(length(contract_reference)>0),
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE contract_product_lines (
    contract_product_line_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL REFERENCES contracts(contract_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    product_line_id TEXT NOT NULL REFERENCES product_lines(product_line_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    current_policy_revision_id TEXT NULL REFERENCES sla_policy_revisions(policy_revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE sla_classification_mappings (
    mapping_id TEXT PRIMARY KEY,
    mapping_key_type TEXT NOT NULL CHECK(mapping_key_type='customer_account_code'),
    normalized_key TEXT NOT NULL CHECK(length(normalized_key)>0),
    customer_org_id TEXT NOT NULL REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    contract_product_line_id TEXT NOT NULL REFERENCES contract_product_lines(contract_product_line_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    closed_command_id TEXT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK((active=1 AND closed_command_id IS NULL) OR (active=0 AND closed_command_id IS NOT NULL))
) STRICT;

CREATE TABLE sr_classification_events (
    classification_event_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('assign','reclassify','invalidate_customer','clear')),
    prior_contract_product_line_id TEXT NULL REFERENCES contract_product_lines(contract_product_line_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    new_contract_product_line_id TEXT NULL REFERENCES contract_product_lines(contract_product_line_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    origin TEXT NOT NULL CHECK(origin IN ('manual_review','automatic_mapping','batch_review','customer_correction')),
    mapping_id TEXT NULL REFERENCES sla_classification_mappings(mapping_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK((event_kind IN ('invalidate_customer','clear') AND new_contract_product_line_id IS NULL) OR event_kind IN ('assign','reclassify')),
    CHECK((origin='automatic_mapping' AND mapping_id IS NOT NULL) OR (origin<>'automatic_mapping' AND mapping_id IS NULL))
) STRICT;

CREATE TABLE sr_classification_current (
    service_request_id TEXT PRIMARY KEY REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    contract_product_line_id TEXT NOT NULL REFERENCES contract_product_lines(contract_product_line_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    classification_event_id TEXT NOT NULL UNIQUE REFERENCES sr_classification_events(classification_event_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE sla_policy_revisions (
    policy_revision_id TEXT PRIMARY KEY,
    contract_product_line_id TEXT NOT NULL REFERENCES contract_product_lines(contract_product_line_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    revision_ordinal INTEGER NOT NULL CHECK(revision_ordinal>0),
    policy_name TEXT NOT NULL CHECK(length(policy_name)>0),
    template_source TEXT NULL CHECK(template_source IS NULL OR template_source IN ('IT_DEFAULT_V1','NFV_DEFAULT_V1')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    UNIQUE(contract_product_line_id,revision_ordinal)
) STRICT;

CREATE TABLE sla_policy_tiers (
    policy_tier_id TEXT PRIMARY KEY,
    policy_revision_id TEXT NOT NULL REFERENCES sla_policy_revisions(policy_revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    severity TEXT NOT NULL CHECK(severity IN ('critical','major','minor','non_fault_inquiry')),
    tier_ordinal INTEGER NOT NULL CHECK(tier_ordinal>0),
    required_percentage_millionths INTEGER NOT NULL CHECK(required_percentage_millionths BETWEEN 1 AND 100000000),
    maximum_duration_numerator_seconds INTEGER NOT NULL CHECK(maximum_duration_numerator_seconds>0),
    maximum_duration_denominator INTEGER NOT NULL CHECK(maximum_duration_denominator BETWEEN 1 AND 1000000000),
    derived_from_tier_id TEXT NULL REFERENCES sla_policy_tiers(policy_tier_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    derivation_num INTEGER NULL CHECK(derivation_num IS NULL OR derivation_num>0),
    derivation_den INTEGER NULL CHECK(derivation_den IS NULL OR derivation_den>0),
    CHECK((severity='non_fault_inquiry' AND derived_from_tier_id IS NOT NULL AND derivation_num=3 AND derivation_den=2)
       OR (severity<>'non_fault_inquiry' AND derived_from_tier_id IS NULL AND derivation_num IS NULL AND derivation_den IS NULL)),
    UNIQUE(policy_revision_id,severity,tier_ordinal)
) STRICT;

CREATE TABLE sla_report_attempts (
    report_attempt_id TEXT PRIMARY KEY,
    period_type TEXT NOT NULL CHECK(period_type IN ('daily','weekly','monthly','selected_range')),
    period_start_utc INTEGER NOT NULL CHECK(period_start_utc>=0),
    period_end_utc INTEGER NOT NULL CHECK(period_end_utc>period_start_utc),
    period_timezone TEXT NOT NULL CHECK(period_timezone='America/Guayaquil'),
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('all_customers','customer')),
    customer_org_id TEXT NULL REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    as_of_utc INTEGER NOT NULL CHECK(as_of_utc>=0),
    state TEXT NOT NULL CHECK(state IN ('staging','ready_to_generate','generating','verifying','completed','failed','cancelled')),
    snapshot_hash TEXT NULL CHECK(snapshot_hash IS NULL OR length(snapshot_hash)=64),
    snapshot_member_count INTEGER NOT NULL DEFAULT 0 CHECK(snapshot_member_count>=0),
    snapshot_cohort_count INTEGER NOT NULL DEFAULT 0 CHECK(snapshot_cohort_count>=0),
    snapshot_section_row_count INTEGER NOT NULL DEFAULT 0 CHECK(snapshot_section_row_count>=0),
    artifact_filename TEXT NULL,
    artifact_sha256 TEXT NULL CHECK(artifact_sha256 IS NULL OR length(artifact_sha256)=64),
    artifact_size_bytes INTEGER NULL CHECK(artifact_size_bytes IS NULL OR artifact_size_bytes>=0),
    verified_at_utc INTEGER NULL CHECK(verified_at_utc IS NULL OR verified_at_utc>=0),
    failure_code TEXT NULL,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    completed_at_utc INTEGER NULL CHECK(completed_at_utc IS NULL OR completed_at_utc>=0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK((scope_kind='all_customers' AND customer_org_id IS NULL) OR (scope_kind='customer' AND customer_org_id IS NOT NULL)),
    CHECK(state<>'completed' OR (snapshot_hash IS NOT NULL AND artifact_filename IS NOT NULL AND length(artifact_filename)>0 AND artifact_sha256 IS NOT NULL AND artifact_size_bytes IS NOT NULL AND artifact_size_bytes>0 AND verified_at_utc IS NOT NULL AND completed_at_utc IS NOT NULL AND failure_code IS NULL)),
    CHECK(state<>'failed' OR (snapshot_hash IS NULL AND snapshot_member_count=0 AND snapshot_cohort_count=0 AND snapshot_section_row_count=0 AND artifact_filename IS NULL AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL AND verified_at_utc IS NULL AND failure_code IS NOT NULL AND completed_at_utc IS NOT NULL)),
    CHECK(state<>'cancelled' OR (snapshot_hash IS NULL AND snapshot_member_count=0 AND snapshot_cohort_count=0 AND snapshot_section_row_count=0 AND artifact_filename IS NULL AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL AND verified_at_utc IS NULL AND failure_code IS NULL AND completed_at_utc IS NOT NULL))
) STRICT;

CREATE TABLE sla_report_member_snapshots (
    report_member_snapshot_id TEXT PRIMARY KEY,
    report_attempt_id TEXT NOT NULL REFERENCES sla_report_attempts(report_attempt_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    member_ordinal INTEGER NOT NULL CHECK(member_ordinal>0),
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    customer_org_id TEXT NULL REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    contract_id TEXT NULL REFERENCES contracts(contract_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    contract_product_line_id TEXT NULL REFERENCES contract_product_lines(contract_product_line_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    policy_revision_id TEXT NULL REFERENCES sla_policy_revisions(policy_revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    classification_event_id TEXT NULL REFERENCES sr_classification_events(classification_event_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    severity TEXT NULL,
    report_date_utc INTEGER NULL CHECK(report_date_utc IS NULL OR report_date_utc>=0),
    status_class TEXT NOT NULL CHECK(status_class IN ('active','resolved','closed','cancelled','unknown')),
    endpoint_utc INTEGER NULL CHECK(endpoint_utc IS NULL OR endpoint_utc>=0),
    suspension_num INTEGER NOT NULL CHECK(suspension_num>=0),
    suspension_den INTEGER NOT NULL CHECK(suspension_den>0),
    elapsed_num INTEGER NULL CHECK(elapsed_num IS NULL OR elapsed_num>=0),
    elapsed_den INTEGER NULL CHECK(elapsed_den IS NULL OR elapsed_den>0),
    calculation_state TEXT NOT NULL,
    sla_input_token TEXT NOT NULL CHECK(length(sla_input_token)=64),
    source_report_date_evidence_id TEXT NULL,
    source_status_evidence_id TEXT NULL,
    source_suspension_evidence_id TEXT NULL,
    display_values_json TEXT NULL CHECK(display_values_json IS NULL OR json_valid(display_values_json)),
    UNIQUE(report_attempt_id,member_ordinal),
    UNIQUE(report_attempt_id,service_request_id)
) STRICT;

CREATE TABLE sla_report_member_tier_results (
    report_member_tier_result_id TEXT PRIMARY KEY,
    report_attempt_id TEXT NOT NULL REFERENCES sla_report_attempts(report_attempt_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    report_member_snapshot_id TEXT NOT NULL REFERENCES sla_report_member_snapshots(report_member_snapshot_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    policy_tier_id TEXT NOT NULL REFERENCES sla_policy_tiers(policy_tier_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    individual_state TEXT NOT NULL CHECK(individual_state IN ('active_within','active_exceeded','terminal_met','terminal_exceeded')),
    inclusive_boundary_met INTEGER NOT NULL CHECK(inclusive_boundary_met IN (0,1)),
    UNIQUE(report_member_snapshot_id,policy_tier_id)
) STRICT;

CREATE TABLE sla_report_cohort_snapshots (
    report_cohort_snapshot_id TEXT PRIMARY KEY,
    report_attempt_id TEXT NOT NULL REFERENCES sla_report_attempts(report_attempt_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    cohort_ordinal INTEGER NOT NULL CHECK(cohort_ordinal>0),
    calendar_month TEXT NOT NULL,
    customer_org_id TEXT NOT NULL REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    contract_id TEXT NOT NULL REFERENCES contracts(contract_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    contract_product_line_id TEXT NOT NULL REFERENCES contract_product_lines(contract_product_line_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    policy_revision_id TEXT NOT NULL REFERENCES sla_policy_revisions(policy_revision_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    policy_tier_id TEXT NOT NULL REFERENCES sla_policy_tiers(policy_tier_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    severity TEXT NOT NULL CHECK(severity IN ('critical','major','minor','non_fault_inquiry')),
    denominator INTEGER NOT NULL CHECK(denominator>=0),
    terminal_met_count INTEGER NOT NULL CHECK(terminal_met_count>=0),
    terminal_exceeded_count INTEGER NOT NULL CHECK(terminal_exceeded_count>=0),
    active_within_count INTEGER NOT NULL CHECK(active_within_count>=0),
    active_exceeded_count INTEGER NOT NULL CHECK(active_exceeded_count>=0),
    state TEXT NOT NULL CHECK(state IN ('pending','currently_met','at_risk','breached','final_met')),
    is_final INTEGER NOT NULL CHECK(is_final IN (0,1)),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    CHECK(denominator=terminal_met_count+terminal_exceeded_count+active_within_count+active_exceeded_count),
    UNIQUE(report_attempt_id,cohort_ordinal)
) STRICT;

CREATE TABLE report_section_snapshots (
    report_section_snapshot_id TEXT PRIMARY KEY,
    report_attempt_id TEXT NOT NULL REFERENCES sla_report_attempts(report_attempt_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    section_kind TEXT NOT NULL,
    schema_name TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK(schema_version>0),
    section_ordinal INTEGER NOT NULL CHECK(section_ordinal>0),
    row_ordinal INTEGER NOT NULL CHECK(row_ordinal>0),
    canonical_row_key TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    UNIQUE(report_attempt_id,section_ordinal,row_ordinal),
    UNIQUE(report_attempt_id,section_kind,canonical_row_key)
) STRICT;

CREATE TABLE sla_report_job_refs (
    report_attempt_id TEXT PRIMARY KEY REFERENCES sla_report_attempts(report_attempt_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    job_id TEXT NOT NULL UNIQUE,
    destination_request_token TEXT NOT NULL CHECK(length(destination_request_token)=64),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX idx_contracts_customer_state ON contracts(customer_org_id,lifecycle_state,contract_id);
CREATE INDEX idx_contracts_created_command_fk ON contracts(created_command_id,contract_id);
CREATE INDEX idx_contracts_last_command_fk ON contracts(last_command_id,contract_id);
CREATE INDEX idx_product_lines_created_command_fk ON product_lines(created_command_id,product_line_id);
CREATE INDEX idx_product_lines_last_command_fk ON product_lines(last_command_id,product_line_id);
CREATE INDEX idx_cpl_contract_state ON contract_product_lines(contract_id,lifecycle_state,contract_product_line_id);
CREATE INDEX idx_cpl_product_line ON contract_product_lines(product_line_id,contract_product_line_id);
CREATE INDEX idx_cpl_current_policy ON contract_product_lines(current_policy_revision_id,contract_product_line_id);
CREATE INDEX idx_cpl_created_command_fk ON contract_product_lines(created_command_id,contract_product_line_id);
CREATE INDEX idx_cpl_last_command_fk ON contract_product_lines(last_command_id,contract_product_line_id);
CREATE INDEX idx_mapping_lookup ON sla_classification_mappings(mapping_key_type,normalized_key,customer_org_id,active,mapping_id);
CREATE INDEX idx_mapping_cpl_active ON sla_classification_mappings(contract_product_line_id,active,mapping_id);
CREATE INDEX idx_mapping_customer_fk ON sla_classification_mappings(customer_org_id,mapping_id);
CREATE INDEX idx_mapping_opened_command_fk ON sla_classification_mappings(opened_command_id,mapping_id);
CREATE INDEX idx_mapping_closed_command_fk ON sla_classification_mappings(closed_command_id,mapping_id);
CREATE INDEX idx_class_event_sr_time ON sr_classification_events(service_request_id,recorded_at_utc,classification_event_id);
CREATE INDEX idx_class_event_prior_cpl_fk ON sr_classification_events(prior_contract_product_line_id,classification_event_id);
CREATE INDEX idx_class_event_new_cpl_fk ON sr_classification_events(new_contract_product_line_id,classification_event_id);
CREATE INDEX idx_class_event_mapping_fk ON sr_classification_events(mapping_id,classification_event_id);
CREATE INDEX idx_class_event_command_fk ON sr_classification_events(command_id,classification_event_id);
CREATE INDEX idx_class_current_cpl ON sr_classification_current(contract_product_line_id,service_request_id);
CREATE INDEX idx_class_current_event_fk ON sr_classification_current(classification_event_id,service_request_id);
CREATE INDEX idx_class_current_command_fk ON sr_classification_current(last_command_id,service_request_id);
CREATE INDEX idx_policy_created_command_fk ON sla_policy_revisions(created_command_id,policy_revision_id);
CREATE INDEX idx_policy_tier_percentage ON sla_policy_tiers(policy_revision_id,severity,required_percentage_millionths,policy_tier_id);
CREATE INDEX idx_policy_tier_derived_fk ON sla_policy_tiers(derived_from_tier_id,policy_tier_id);
CREATE INDEX idx_report_attempt_state_created ON sla_report_attempts(state,created_at_utc,report_attempt_id);
CREATE INDEX idx_report_attempt_customer_period ON sla_report_attempts(customer_org_id,period_start_utc,report_attempt_id);
CREATE INDEX idx_report_attempt_created_command_fk ON sla_report_attempts(created_command_id,report_attempt_id);
CREATE INDEX idx_report_attempt_last_command_fk ON sla_report_attempts(last_command_id,report_attempt_id);
CREATE INDEX idx_report_member_customer_fk ON sla_report_member_snapshots(customer_org_id,report_member_snapshot_id);
CREATE INDEX idx_report_member_contract_fk ON sla_report_member_snapshots(contract_id,report_member_snapshot_id);
CREATE INDEX idx_report_member_cpl_fk ON sla_report_member_snapshots(contract_product_line_id,report_member_snapshot_id);
CREATE INDEX idx_report_member_policy_fk ON sla_report_member_snapshots(policy_revision_id,report_member_snapshot_id);
CREATE INDEX idx_report_member_class_event_fk ON sla_report_member_snapshots(classification_event_id,report_member_snapshot_id);
CREATE INDEX idx_report_tier_attempt_fk ON sla_report_member_tier_results(report_attempt_id,report_member_tier_result_id);
CREATE INDEX idx_report_tier_policy_fk ON sla_report_member_tier_results(policy_tier_id,report_member_tier_result_id);
CREATE INDEX idx_report_cohort_key ON sla_report_cohort_snapshots(report_attempt_id,calendar_month,customer_org_id,contract_product_line_id,severity,policy_tier_id);
CREATE INDEX idx_report_cohort_contract_fk ON sla_report_cohort_snapshots(contract_id,report_cohort_snapshot_id);
CREATE INDEX idx_report_cohort_policy_revision_fk ON sla_report_cohort_snapshots(policy_revision_id,report_cohort_snapshot_id);
CREATE INDEX idx_report_cohort_policy_tier_fk ON sla_report_cohort_snapshots(policy_tier_id,report_cohort_snapshot_id);
CREATE INDEX idx_report_job_last_command_fk ON sla_report_job_refs(last_command_id,report_attempt_id);

CREATE TRIGGER cpl_policy_owner_update_guard
BEFORE UPDATE OF current_policy_revision_id ON contract_product_lines
WHEN NEW.current_policy_revision_id IS NOT NULL BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM sla_policy_revisions p
        WHERE p.policy_revision_id=NEW.current_policy_revision_id
          AND p.contract_product_line_id=NEW.contract_product_line_id
    ) THEN RAISE(ABORT,'SLA_POLICY_OWNER_MISMATCH') END;
END;

CREATE TRIGGER sla_policy_revision_update_guard
BEFORE UPDATE ON sla_policy_revisions BEGIN
    SELECT RAISE(ABORT,'SLA_POLICY_REVISION_IMMUTABLE');
END;
CREATE TRIGGER sla_policy_revision_delete_guard
BEFORE DELETE ON sla_policy_revisions BEGIN
    SELECT RAISE(ABORT,'SLA_POLICY_REVISION_IMMUTABLE');
END;
CREATE TRIGGER sla_policy_tier_update_guard
BEFORE UPDATE ON sla_policy_tiers BEGIN
    SELECT RAISE(ABORT,'SLA_POLICY_TIER_IMMUTABLE');
END;
CREATE TRIGGER sla_policy_tier_delete_guard
BEFORE DELETE ON sla_policy_tiers BEGIN
    SELECT RAISE(ABORT,'SLA_POLICY_TIER_IMMUTABLE');
END;
CREATE TRIGGER sr_classification_event_update_guard
BEFORE UPDATE ON sr_classification_events BEGIN
    SELECT RAISE(ABORT,'SLA_CLASSIFICATION_EVENT_APPEND_ONLY');
END;
CREATE TRIGGER sr_classification_event_delete_guard
BEFORE DELETE ON sr_classification_events BEGIN
    SELECT RAISE(ABORT,'SLA_CLASSIFICATION_EVENT_APPEND_ONLY');
END;

CREATE TRIGGER sla_report_terminal_update_guard
BEFORE UPDATE ON sla_report_attempts
WHEN OLD.state IN ('completed','failed','cancelled') BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_TERMINAL_IMMUTABLE');
END;
CREATE TRIGGER sla_report_delete_guard
BEFORE DELETE ON sla_report_attempts BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_ATTEMPT_DELETE_FORBIDDEN');
END;
CREATE TRIGGER sla_report_terminal_children_guard
BEFORE UPDATE OF state ON sla_report_attempts
WHEN NEW.state IN ('failed','cancelled') AND (
    EXISTS(SELECT 1 FROM sla_report_member_tier_results WHERE report_attempt_id=NEW.report_attempt_id)
    OR EXISTS(SELECT 1 FROM sla_report_member_snapshots WHERE report_attempt_id=NEW.report_attempt_id)
    OR EXISTS(SELECT 1 FROM sla_report_cohort_snapshots WHERE report_attempt_id=NEW.report_attempt_id)
    OR EXISTS(SELECT 1 FROM report_section_snapshots WHERE report_attempt_id=NEW.report_attempt_id)
) BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_STAGING_NOT_CLEAN');
END;
CREATE TRIGGER sla_report_complete_counts_guard
BEFORE UPDATE OF state ON sla_report_attempts
WHEN NEW.state='completed' BEGIN
    SELECT CASE WHEN NEW.snapshot_member_count<>(SELECT COUNT(*) FROM sla_report_member_snapshots WHERE report_attempt_id=NEW.report_attempt_id) THEN RAISE(ABORT,'SLA_REPORT_MEMBER_COUNT_MISMATCH') END;
    SELECT CASE WHEN NEW.snapshot_cohort_count<>(SELECT COUNT(*) FROM sla_report_cohort_snapshots WHERE report_attempt_id=NEW.report_attempt_id) THEN RAISE(ABORT,'SLA_REPORT_COHORT_COUNT_MISMATCH') END;
    SELECT CASE WHEN NEW.snapshot_section_row_count<>(SELECT COUNT(*) FROM report_section_snapshots WHERE report_attempt_id=NEW.report_attempt_id) THEN RAISE(ABORT,'SLA_REPORT_SECTION_COUNT_MISMATCH') END;
END;

CREATE TRIGGER sla_report_member_insert_guard
BEFORE INSERT ON sla_report_member_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=NEW.report_attempt_id)<>'staging' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_MEMBER_STAGE_CLOSED');
END;
CREATE TRIGGER sla_report_member_update_guard
BEFORE UPDATE ON sla_report_member_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=OLD.report_attempt_id)='completed' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COMPLETED_EVIDENCE_IMMUTABLE');
END;
CREATE TRIGGER sla_report_member_delete_guard
BEFORE DELETE ON sla_report_member_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=OLD.report_attempt_id)='completed' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COMPLETED_EVIDENCE_IMMUTABLE');
END;

CREATE TRIGGER sla_report_tier_insert_guard
BEFORE INSERT ON sla_report_member_tier_results
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=NEW.report_attempt_id)<>'staging' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_TIER_STAGE_CLOSED');
END;
CREATE TRIGGER sla_report_tier_update_guard
BEFORE UPDATE ON sla_report_member_tier_results
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=OLD.report_attempt_id)='completed' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COMPLETED_EVIDENCE_IMMUTABLE');
END;
CREATE TRIGGER sla_report_tier_delete_guard
BEFORE DELETE ON sla_report_member_tier_results
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=OLD.report_attempt_id)='completed' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COMPLETED_EVIDENCE_IMMUTABLE');
END;

CREATE TRIGGER sla_report_cohort_insert_guard
BEFORE INSERT ON sla_report_cohort_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=NEW.report_attempt_id)<>'staging' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COHORT_STAGE_CLOSED');
END;
CREATE TRIGGER sla_report_cohort_update_guard
BEFORE UPDATE ON sla_report_cohort_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=OLD.report_attempt_id)='completed' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COMPLETED_EVIDENCE_IMMUTABLE');
END;
CREATE TRIGGER sla_report_cohort_delete_guard
BEFORE DELETE ON sla_report_cohort_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=OLD.report_attempt_id)='completed' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COMPLETED_EVIDENCE_IMMUTABLE');
END;

CREATE TRIGGER report_section_insert_guard
BEFORE INSERT ON report_section_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=NEW.report_attempt_id)<>'staging' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_SECTION_STAGE_CLOSED');
END;
CREATE TRIGGER report_section_update_guard
BEFORE UPDATE ON report_section_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=OLD.report_attempt_id)='completed' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COMPLETED_EVIDENCE_IMMUTABLE');
END;
CREATE TRIGGER report_section_delete_guard
BEFORE DELETE ON report_section_snapshots
WHEN (SELECT state FROM sla_report_attempts WHERE report_attempt_id=OLD.report_attempt_id)='completed' BEGIN
    SELECT RAISE(ABORT,'SLA_REPORT_COMPLETED_EVIDENCE_IMMUTABLE');
END;
