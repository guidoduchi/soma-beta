CREATE TABLE sr_local_id_allocator (
    singleton_guard INTEGER PRIMARY KEY CHECK(singleton_guard = 1),
    next_value INTEGER NOT NULL CHECK(next_value BETWEEN 1 AND 100000000)
) STRICT;

INSERT INTO sr_local_id_allocator(singleton_guard, next_value) VALUES (1, 1);

CREATE TABLE service_requests (
    service_request_id TEXT PRIMARY KEY,
    official_sr_no TEXT UNIQUE,
    local_sr_no TEXT UNIQUE,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc),
    CHECK(official_sr_no IS NOT NULL OR local_sr_no IS NOT NULL),
    CHECK(official_sr_no IS NULL OR (length(official_sr_no) = 8 AND official_sr_no NOT GLOB '*[^0-9]*')),
    CHECK(local_sr_no IS NULL OR (length(local_sr_no) = 12 AND substr(local_sr_no, 1, 4) = 'LSR-' AND substr(local_sr_no, 5) NOT GLOB '*[^0-9]*'))
) STRICT;

CREATE TABLE rfcs (
    rfc_id TEXT PRIMARY KEY,
    rfc_no TEXT NOT NULL UNIQUE CHECK(length(rfc_no) = 16 AND substr(rfc_no, 1, 2) = 'NC' AND substr(rfc_no, 3) NOT GLOB '*[^0-9]*'),
    customer_org_id TEXT REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    local_archive_state TEXT NOT NULL DEFAULT 'active' CHECK(local_archive_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc)
) STRICT;

CREATE TABLE sr_working_notes (
    working_note_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    created_by_local_user_profile_id TEXT NOT NULL REFERENCES local_user_profiles(local_user_profile_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    body_text TEXT NOT NULL CHECK(length(body_text) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE rfc_working_notes (
    working_note_id TEXT PRIMARY KEY,
    rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    created_by_local_user_profile_id TEXT NOT NULL REFERENCES local_user_profiles(local_user_profile_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    body_text TEXT NOT NULL CHECK(length(body_text) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE device_references (
    device_reference_id TEXT PRIMARY KEY,
    operational_name TEXT NOT NULL CHECK(length(operational_name) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc)
) STRICT;

CREATE TABLE rfc_hierarchy_edges (
    rfc_hierarchy_edge_id TEXT PRIMARY KEY,
    parent_rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    child_rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    edge_state TEXT NOT NULL CHECK(edge_state IN ('active','superseded')),
    opened_at_utc INTEGER NOT NULL CHECK(opened_at_utc >= 0),
    closed_at_utc INTEGER,
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    closed_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK(parent_rfc_id <> child_rfc_id),
    CHECK((edge_state = 'active' AND closed_at_utc IS NULL AND closed_command_id IS NULL) OR (edge_state = 'superseded' AND closed_at_utc IS NOT NULL AND closed_command_id IS NOT NULL))
) STRICT;

CREATE TABLE sr_rfc_links (
    sr_rfc_link_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    link_state TEXT NOT NULL CHECK(link_state IN ('active','unlinked')),
    opened_at_utc INTEGER NOT NULL CHECK(opened_at_utc >= 0),
    closed_at_utc INTEGER,
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    closed_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    reason_category TEXT,
    CHECK((link_state = 'active' AND closed_at_utc IS NULL AND closed_command_id IS NULL) OR (link_state = 'unlinked' AND closed_at_utc IS NOT NULL AND closed_command_id IS NOT NULL))
) STRICT;

CREATE TABLE rfc_device_reference_links (
    rfc_device_reference_link_id TEXT PRIMARY KEY,
    rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    device_reference_id TEXT NOT NULL REFERENCES device_references(device_reference_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    link_state TEXT NOT NULL CHECK(link_state IN ('active','unlinked')),
    opened_at_utc INTEGER NOT NULL CHECK(opened_at_utc >= 0),
    closed_at_utc INTEGER,
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    closed_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK((link_state = 'active' AND closed_at_utc IS NULL AND closed_command_id IS NULL) OR (link_state = 'unlinked' AND closed_at_utc IS NOT NULL AND closed_command_id IS NOT NULL))
) STRICT;

CREATE TABLE sr_device_reference_links (
    sr_device_reference_link_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    device_reference_id TEXT NOT NULL REFERENCES device_references(device_reference_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    link_state TEXT NOT NULL CHECK(link_state IN ('active','unlinked')),
    opened_at_utc INTEGER NOT NULL CHECK(opened_at_utc >= 0),
    closed_at_utc INTEGER,
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    closed_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK((link_state = 'active' AND closed_at_utc IS NULL AND closed_command_id IS NULL) OR (link_state = 'unlinked' AND closed_at_utc IS NOT NULL AND closed_command_id IS NOT NULL))
) STRICT;

CREATE TABLE sr_source_field_observations (
    sr_source_field_observation_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    field_key TEXT NOT NULL CHECK(field_key IN ('problem_summary','report_date','customer_contact_label','customer_severity','current_handler_label','status','customer_org_label','customer_account_code','suspend_planned_end','suspension_duration','last_update')),
    value_state TEXT NOT NULL CHECK(value_state IN ('usable','explicit_clear')),
    value_kind TEXT NOT NULL CHECK(value_kind IN ('text','instant','duration_seconds','controlled')),
    text_value TEXT,
    integer_value INTEGER,
    source_chronology_utc INTEGER CHECK(source_chronology_utc IS NULL OR source_chronology_utc >= 0),
    precedence_basis TEXT NOT NULL CHECK(precedence_basis IN ('source_chronology','reviewed_correction')),
    source_observation_field_id TEXT NOT NULL CHECK(length(source_observation_field_id) > 0),
    accepted_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    CHECK((value_state = 'usable' AND value_kind IN ('text','controlled') AND text_value IS NOT NULL AND integer_value IS NULL) OR (value_state = 'usable' AND value_kind IN ('instant','duration_seconds') AND text_value IS NULL AND integer_value IS NOT NULL) OR (value_state = 'explicit_clear' AND field_key = 'current_handler_label' AND value_kind = 'text' AND text_value IS NULL AND integer_value IS NULL)),
    CHECK((field_key IN ('problem_summary','customer_contact_label','current_handler_label','customer_org_label','customer_account_code') AND value_kind = 'text') OR (field_key IN ('customer_severity','status') AND value_kind = 'controlled') OR (field_key IN ('report_date','suspend_planned_end','last_update') AND value_kind = 'instant') OR (field_key = 'suspension_duration' AND value_kind = 'duration_seconds')),
    CHECK((precedence_basis = 'source_chronology' AND source_chronology_utc IS NOT NULL) OR precedence_basis = 'reviewed_correction')
) STRICT;

CREATE TABLE sr_current_source_projection (
    service_request_id TEXT PRIMARY KEY REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    problem_summary_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    report_date_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    customer_contact_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    customer_severity_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    current_handler_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    status_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    customer_org_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    customer_account_code_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    suspend_planned_end_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    suspension_duration_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    last_update_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0)
) STRICT;

CREATE TABLE sr_customer_relationships (
    sr_customer_relationship_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    customer_org_id TEXT NOT NULL REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    relationship_state TEXT NOT NULL CHECK(relationship_state IN ('active','superseded')),
    origin_kind TEXT NOT NULL CHECK(origin_kind IN ('manual_review','advanced_search_review','correction')),
    reconciliation_proposal_id TEXT CHECK(reconciliation_proposal_id IS NULL OR length(reconciliation_proposal_id) > 0),
    opened_at_utc INTEGER NOT NULL CHECK(opened_at_utc >= 0),
    closed_at_utc INTEGER,
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    closed_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    reason_category TEXT,
    CHECK((relationship_state = 'active' AND closed_at_utc IS NULL AND closed_command_id IS NULL) OR (relationship_state = 'superseded' AND closed_at_utc IS NOT NULL AND closed_command_id IS NOT NULL)),
    CHECK(origin_kind <> 'advanced_search_review' OR reconciliation_proposal_id IS NOT NULL)
) STRICT;

CREATE TABLE sr_contact_relationships (
    sr_contact_relationship_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    reference_role TEXT NOT NULL CHECK(reference_role IN ('customer_contact','current_handler_reference')),
    contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    customer_org_context_id TEXT REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    relationship_state TEXT NOT NULL CHECK(relationship_state IN ('active','superseded')),
    origin_kind TEXT NOT NULL CHECK(origin_kind IN ('manual_review','advanced_search_review','correction')),
    reconciliation_proposal_id TEXT CHECK(reconciliation_proposal_id IS NULL OR length(reconciliation_proposal_id) > 0),
    supporting_sr_source_field_observation_id TEXT REFERENCES sr_source_field_observations(sr_source_field_observation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    opened_at_utc INTEGER NOT NULL CHECK(opened_at_utc >= 0),
    closed_at_utc INTEGER,
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    closed_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    reason_category TEXT,
    CHECK((relationship_state = 'active' AND closed_at_utc IS NULL AND closed_command_id IS NULL) OR (relationship_state = 'superseded' AND closed_at_utc IS NOT NULL AND closed_command_id IS NOT NULL)),
    CHECK(origin_kind <> 'advanced_search_review' OR reconciliation_proposal_id IS NOT NULL),
    CHECK(reference_role <> 'current_handler_reference' OR supporting_sr_source_field_observation_id IS NOT NULL)
) STRICT;

CREATE TABLE rfc_current_source_projection (
    rfc_id TEXT PRIMARY KEY REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    summary_text TEXT,
    summary_evidence_id TEXT,
    external_created_at_utc INTEGER CHECK(external_created_at_utc IS NULL OR external_created_at_utc >= 0),
    external_created_evidence_id TEXT,
    creator_text TEXT,
    creator_evidence_id TEXT,
    customer_account_number_text TEXT,
    customer_account_number_evidence_id TEXT,
    customer_account_name_text TEXT,
    customer_account_name_evidence_id TEXT,
    severity_text TEXT,
    severity_evidence_id TEXT,
    status_text TEXT,
    status_class TEXT NOT NULL DEFAULT 'unknown' CHECK(status_class IN ('unknown','pre_implement','implement_eligible','terminal_closed','terminal_cancelled')),
    status_authority TEXT CHECK(status_authority IS NULL OR status_authority IN ('enhanced_rfc','wfm_provisional')),
    status_evidence_id TEXT,
    terminal_epoch_id TEXT,
    owner_external_id_text TEXT,
    owner_external_id_evidence_id TEXT,
    owner_name_text TEXT,
    owner_name_evidence_id TEXT,
    l1_handler_name_text TEXT,
    l1_handler_name_evidence_id TEXT,
    l2_handler_name_text TEXT,
    l2_handler_name_evidence_id TEXT,
    last_update_utc INTEGER CHECK(last_update_utc IS NULL OR last_update_utc >= 0),
    last_update_evidence_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    CHECK((summary_text IS NULL AND summary_evidence_id IS NULL) OR (summary_text IS NOT NULL AND summary_evidence_id IS NOT NULL)),
    CHECK((external_created_at_utc IS NULL AND external_created_evidence_id IS NULL) OR (external_created_at_utc IS NOT NULL AND external_created_evidence_id IS NOT NULL)),
    CHECK((creator_text IS NULL AND creator_evidence_id IS NULL) OR (creator_text IS NOT NULL AND creator_evidence_id IS NOT NULL)),
    CHECK((customer_account_number_text IS NULL AND customer_account_number_evidence_id IS NULL) OR (customer_account_number_text IS NOT NULL AND customer_account_number_evidence_id IS NOT NULL)),
    CHECK((customer_account_name_text IS NULL AND customer_account_name_evidence_id IS NULL) OR (customer_account_name_text IS NOT NULL AND customer_account_name_evidence_id IS NOT NULL)),
    CHECK((severity_text IS NULL AND severity_evidence_id IS NULL) OR (severity_text IS NOT NULL AND severity_evidence_id IS NOT NULL)),
    CHECK((owner_external_id_text IS NULL AND owner_external_id_evidence_id IS NULL) OR (owner_external_id_text IS NOT NULL AND owner_external_id_evidence_id IS NOT NULL)),
    CHECK((owner_name_text IS NULL AND owner_name_evidence_id IS NULL) OR (owner_name_text IS NOT NULL AND owner_name_evidence_id IS NOT NULL)),
    CHECK((l1_handler_name_text IS NULL AND l1_handler_name_evidence_id IS NULL) OR (l1_handler_name_text IS NOT NULL AND l1_handler_name_evidence_id IS NOT NULL)),
    CHECK((l2_handler_name_text IS NULL AND l2_handler_name_evidence_id IS NULL) OR (l2_handler_name_text IS NOT NULL AND l2_handler_name_evidence_id IS NOT NULL)),
    CHECK((last_update_utc IS NULL AND last_update_evidence_id IS NULL) OR (last_update_utc IS NOT NULL AND last_update_evidence_id IS NOT NULL)),
    CHECK((status_class = 'unknown' AND status_text IS NULL AND status_evidence_id IS NULL AND status_authority IS NULL AND terminal_epoch_id IS NULL) OR (status_class <> 'unknown' AND status_text IS NOT NULL AND status_evidence_id IS NOT NULL AND status_authority IS NOT NULL)),
    CHECK((status_class IN ('terminal_closed','terminal_cancelled') AND terminal_epoch_id IS NOT NULL) OR (status_class NOT IN ('terminal_closed','terminal_cancelled') AND terminal_epoch_id IS NULL))
) STRICT;

CREATE TABLE rfc_terminal_cascade_proposals (
    rfc_terminal_cascade_proposal_id TEXT PRIMARY KEY,
    trigger_rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    terminal_epoch_id TEXT NOT NULL CHECK(length(terminal_epoch_id) > 0),
    terminal_status_class TEXT NOT NULL CHECK(terminal_status_class IN ('terminal_closed','terminal_cancelled')),
    terminal_status_evidence_id TEXT NOT NULL CHECK(length(terminal_status_evidence_id) > 0),
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('exact_rfc','root_branch')),
    scope_fingerprint TEXT NOT NULL CHECK(length(scope_fingerprint) = 64),
    proposal_state TEXT NOT NULL CHECK(proposal_state IN ('pending','executed','superseded')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    executed_at_utc INTEGER,
    executed_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    superseded_at_utc INTEGER,
    superseded_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK((proposal_state = 'pending' AND executed_at_utc IS NULL AND executed_command_id IS NULL AND superseded_at_utc IS NULL AND superseded_command_id IS NULL) OR (proposal_state = 'executed' AND executed_at_utc IS NOT NULL AND executed_command_id IS NOT NULL AND superseded_at_utc IS NULL AND superseded_command_id IS NULL) OR (proposal_state = 'superseded' AND executed_at_utc IS NULL AND executed_command_id IS NULL AND superseded_at_utc IS NOT NULL AND superseded_command_id IS NOT NULL))
) STRICT;

CREATE TABLE rfc_terminal_cascade_rfc_members (
    rfc_terminal_cascade_proposal_id TEXT NOT NULL REFERENCES rfc_terminal_cascade_proposals(rfc_terminal_cascade_proposal_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    captured_rfc_revision INTEGER NOT NULL CHECK(captured_rfc_revision > 0),
    captured_role TEXT NOT NULL CHECK(captured_role IN ('root','subordinate','standalone')),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(rfc_terminal_cascade_proposal_id, rfc_id),
    UNIQUE(rfc_terminal_cascade_proposal_id, ordinal)
) STRICT;

CREATE TABLE rfc_terminal_cascade_wfm_members (
    rfc_terminal_cascade_proposal_id TEXT NOT NULL REFERENCES rfc_terminal_cascade_proposals(rfc_terminal_cascade_proposal_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    task_id TEXT NOT NULL,
    owning_rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    captured_task_revision INTEGER NOT NULL CHECK(captured_task_revision > 0),
    captured_task_no TEXT NOT NULL CHECK(length(captured_task_no) = 16 AND substr(captured_task_no, 1, 2) = 'TK' AND substr(captured_task_no, 3) NOT GLOB '*[^0-9]*'),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(rfc_terminal_cascade_proposal_id, task_id),
    UNIQUE(rfc_terminal_cascade_proposal_id, ordinal)
) STRICT;

CREATE TABLE rfc_archive_operations (
    rfc_archive_operation_id TEXT PRIMARY KEY,
    requested_rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('exact_rfc','reviewed_branch')),
    scope_fingerprint TEXT NOT NULL CHECK(length(scope_fingerprint) = 64),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE TABLE rfc_archive_operation_members (
    rfc_archive_operation_id TEXT NOT NULL REFERENCES rfc_archive_operations(rfc_archive_operation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    pre_archive_revision INTEGER NOT NULL CHECK(pre_archive_revision > 0),
    archived_revision INTEGER NOT NULL CHECK(archived_revision = pre_archive_revision + 1),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(rfc_archive_operation_id, rfc_id),
    UNIQUE(rfc_archive_operation_id, ordinal)
) STRICT;

CREATE TABLE rfc_archive_events (
    rfc_archive_event_id TEXT PRIMARY KEY,
    rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK(event_type IN ('archived','restored')),
    origin_archive_operation_id TEXT NOT NULL REFERENCES rfc_archive_operations(rfc_archive_operation_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    resulting_rfc_revision INTEGER NOT NULL CHECK(resulting_rfc_revision > 1),
    occurred_at_utc INTEGER NOT NULL CHECK(occurred_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    UNIQUE(rfc_id, resulting_rfc_revision)
) STRICT;

CREATE INDEX idx_rfc_customer ON rfcs(customer_org_id, rfc_id);
CREATE INDEX idx_rfc_archive ON rfcs(local_archive_state, rfc_no, rfc_id);
CREATE INDEX idx_sr_notes_target ON sr_working_notes(service_request_id, created_at_utc, working_note_id);
CREATE INDEX idx_sr_notes_creator ON sr_working_notes(created_by_local_user_profile_id, working_note_id);
CREATE INDEX idx_sr_notes_command ON sr_working_notes(created_command_id);
CREATE INDEX idx_rfc_notes_target ON rfc_working_notes(rfc_id, created_at_utc, working_note_id);
CREATE INDEX idx_rfc_notes_creator ON rfc_working_notes(created_by_local_user_profile_id, working_note_id);
CREATE INDEX idx_rfc_notes_command ON rfc_working_notes(created_command_id);
CREATE INDEX idx_device_reference_name ON device_references(operational_name, device_reference_id);
CREATE UNIQUE INDEX uq_rfc_active_parent ON rfc_hierarchy_edges(child_rfc_id) WHERE edge_state = 'active';
CREATE INDEX idx_rfc_active_children ON rfc_hierarchy_edges(parent_rfc_id, child_rfc_id) WHERE edge_state = 'active';
CREATE INDEX idx_rfc_hierarchy_parent_fk ON rfc_hierarchy_edges(parent_rfc_id, rfc_hierarchy_edge_id);
CREATE INDEX idx_rfc_hierarchy_history_child ON rfc_hierarchy_edges(child_rfc_id, opened_at_utc, rfc_hierarchy_edge_id);
CREATE INDEX idx_rfc_hierarchy_open_command ON rfc_hierarchy_edges(opened_command_id, rfc_hierarchy_edge_id);
CREATE INDEX idx_rfc_hierarchy_close_command ON rfc_hierarchy_edges(closed_command_id, rfc_hierarchy_edge_id) WHERE closed_command_id IS NOT NULL;
CREATE UNIQUE INDEX uq_sr_rfc_active_pair ON sr_rfc_links(service_request_id, rfc_id) WHERE link_state = 'active';
CREATE INDEX idx_sr_rfc_active_by_rfc ON sr_rfc_links(rfc_id, service_request_id) WHERE link_state = 'active';
CREATE INDEX idx_sr_rfc_history ON sr_rfc_links(service_request_id, rfc_id, opened_at_utc, sr_rfc_link_id);
CREATE INDEX idx_sr_rfc_rfc_fk ON sr_rfc_links(rfc_id, sr_rfc_link_id);
CREATE INDEX idx_sr_rfc_open_command ON sr_rfc_links(opened_command_id, sr_rfc_link_id);
CREATE INDEX idx_sr_rfc_close_command ON sr_rfc_links(closed_command_id, sr_rfc_link_id) WHERE closed_command_id IS NOT NULL;
CREATE UNIQUE INDEX uq_rfc_device_active_pair ON rfc_device_reference_links(rfc_id, device_reference_id) WHERE link_state = 'active';
CREATE INDEX idx_rfc_device_by_device ON rfc_device_reference_links(device_reference_id, rfc_id) WHERE link_state = 'active';
CREATE INDEX idx_rfc_device_rfc_fk ON rfc_device_reference_links(rfc_id, rfc_device_reference_link_id);
CREATE INDEX idx_rfc_device_device_fk ON rfc_device_reference_links(device_reference_id, rfc_device_reference_link_id);
CREATE INDEX idx_rfc_device_open_command ON rfc_device_reference_links(opened_command_id, rfc_device_reference_link_id);
CREATE INDEX idx_rfc_device_close_command ON rfc_device_reference_links(closed_command_id, rfc_device_reference_link_id) WHERE closed_command_id IS NOT NULL;
CREATE UNIQUE INDEX uq_sr_device_active_pair ON sr_device_reference_links(service_request_id, device_reference_id) WHERE link_state = 'active';
CREATE INDEX idx_sr_device_by_device ON sr_device_reference_links(device_reference_id, service_request_id) WHERE link_state = 'active';
CREATE INDEX idx_sr_device_sr_fk ON sr_device_reference_links(service_request_id, sr_device_reference_link_id);
CREATE INDEX idx_sr_device_device_fk ON sr_device_reference_links(device_reference_id, sr_device_reference_link_id);
CREATE INDEX idx_sr_device_open_command ON sr_device_reference_links(opened_command_id, sr_device_reference_link_id);
CREATE INDEX idx_sr_device_close_command ON sr_device_reference_links(closed_command_id, sr_device_reference_link_id) WHERE closed_command_id IS NOT NULL;
CREATE INDEX idx_sr_source_field_history ON sr_source_field_observations(service_request_id, field_key, source_chronology_utc, sr_source_field_observation_id);
CREATE INDEX idx_sr_source_field_evidence_ref ON sr_source_field_observations(source_observation_field_id, sr_source_field_observation_id);
CREATE INDEX idx_sr_source_accept_command ON sr_source_field_observations(accepted_command_id, sr_source_field_observation_id);
CREATE INDEX idx_sr_projection_problem_obs ON sr_current_source_projection(problem_summary_observation_id);
CREATE INDEX idx_sr_projection_report_obs ON sr_current_source_projection(report_date_observation_id);
CREATE INDEX idx_sr_projection_contact_obs ON sr_current_source_projection(customer_contact_observation_id);
CREATE INDEX idx_sr_projection_severity_obs ON sr_current_source_projection(customer_severity_observation_id);
CREATE INDEX idx_sr_projection_handler_obs ON sr_current_source_projection(current_handler_observation_id);
CREATE INDEX idx_sr_projection_status_obs ON sr_current_source_projection(status_observation_id);
CREATE INDEX idx_sr_projection_customer_obs ON sr_current_source_projection(customer_org_observation_id);
CREATE INDEX idx_sr_projection_account_obs ON sr_current_source_projection(customer_account_code_observation_id);
CREATE INDEX idx_sr_projection_suspend_end_obs ON sr_current_source_projection(suspend_planned_end_observation_id);
CREATE INDEX idx_sr_projection_suspend_duration_obs ON sr_current_source_projection(suspension_duration_observation_id);
CREATE INDEX idx_sr_projection_last_update_obs ON sr_current_source_projection(last_update_observation_id);
CREATE UNIQUE INDEX uq_sr_customer_active ON sr_customer_relationships(service_request_id) WHERE relationship_state = 'active';
CREATE INDEX idx_sr_customer_sr_fk ON sr_customer_relationships(service_request_id, sr_customer_relationship_id);
CREATE INDEX idx_sr_customer_history ON sr_customer_relationships(service_request_id, opened_at_utc DESC, sr_customer_relationship_id);
CREATE INDEX idx_sr_customer_customer_fk ON sr_customer_relationships(customer_org_id, sr_customer_relationship_id);
CREATE INDEX idx_sr_customer_proposal_ref ON sr_customer_relationships(reconciliation_proposal_id, sr_customer_relationship_id);
CREATE INDEX idx_sr_customer_open_command_fk ON sr_customer_relationships(opened_command_id, sr_customer_relationship_id);
CREATE INDEX idx_sr_customer_close_command_fk ON sr_customer_relationships(closed_command_id, sr_customer_relationship_id);
CREATE UNIQUE INDEX uq_sr_contact_active_role ON sr_contact_relationships(service_request_id, reference_role) WHERE relationship_state = 'active';
CREATE INDEX idx_sr_contact_sr_fk ON sr_contact_relationships(service_request_id, sr_contact_relationship_id);
CREATE INDEX idx_sr_contact_history ON sr_contact_relationships(service_request_id, reference_role, opened_at_utc DESC, sr_contact_relationship_id);
CREATE INDEX idx_sr_contact_contact_fk ON sr_contact_relationships(contact_id, sr_contact_relationship_id);
CREATE INDEX idx_sr_contact_customer_context_fk ON sr_contact_relationships(customer_org_context_id, sr_contact_relationship_id);
CREATE INDEX idx_sr_contact_proposal_ref ON sr_contact_relationships(reconciliation_proposal_id, sr_contact_relationship_id);
CREATE INDEX idx_sr_contact_source_obs_fk ON sr_contact_relationships(supporting_sr_source_field_observation_id, sr_contact_relationship_id);
CREATE INDEX idx_sr_contact_open_command_fk ON sr_contact_relationships(opened_command_id, sr_contact_relationship_id);
CREATE INDEX idx_sr_contact_close_command_fk ON sr_contact_relationships(closed_command_id, sr_contact_relationship_id);
CREATE INDEX idx_rfc_source_status ON rfc_current_source_projection(status_class, rfc_id);
CREATE INDEX idx_rfc_terminal_pending ON rfc_terminal_cascade_proposals(trigger_rfc_id, terminal_epoch_id, proposal_state, rfc_terminal_cascade_proposal_id);
CREATE UNIQUE INDEX uq_rfc_terminal_pending_epoch ON rfc_terminal_cascade_proposals(trigger_rfc_id, terminal_epoch_id) WHERE proposal_state = 'pending';
CREATE INDEX idx_rfc_terminal_created_command ON rfc_terminal_cascade_proposals(created_command_id, rfc_terminal_cascade_proposal_id);
CREATE INDEX idx_rfc_terminal_executed_command ON rfc_terminal_cascade_proposals(executed_command_id, rfc_terminal_cascade_proposal_id) WHERE executed_command_id IS NOT NULL;
CREATE INDEX idx_rfc_terminal_superseded_command ON rfc_terminal_cascade_proposals(superseded_command_id, rfc_terminal_cascade_proposal_id) WHERE superseded_command_id IS NOT NULL;
CREATE INDEX idx_rfc_terminal_rfc_member_fk ON rfc_terminal_cascade_rfc_members(rfc_id, rfc_terminal_cascade_proposal_id);
CREATE INDEX idx_rfc_terminal_wfm_owner ON rfc_terminal_cascade_wfm_members(owning_rfc_id, rfc_terminal_cascade_proposal_id, task_id);
CREATE INDEX idx_archive_requested_rfc ON rfc_archive_operations(requested_rfc_id, created_at_utc, rfc_archive_operation_id);
CREATE INDEX idx_archive_created_command ON rfc_archive_operations(created_command_id, rfc_archive_operation_id);
CREATE INDEX idx_archive_member_rfc ON rfc_archive_operation_members(rfc_id, rfc_archive_operation_id);
CREATE INDEX idx_archive_event_latest ON rfc_archive_events(rfc_id, resulting_rfc_revision DESC, rfc_archive_event_id);
CREATE INDEX idx_archive_event_origin ON rfc_archive_events(origin_archive_operation_id, rfc_id, resulting_rfc_revision, rfc_archive_event_id);
CREATE INDEX idx_archive_event_command ON rfc_archive_events(command_id, rfc_archive_event_id);

CREATE TRIGGER rfc_hierarchy_insert_parent_not_subordinate BEFORE INSERT ON rfc_hierarchy_edges WHEN NEW.edge_state = 'active' BEGIN
    SELECT CASE WHEN EXISTS (SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id = NEW.parent_rfc_id AND edge_state = 'active') THEN RAISE(ABORT, 'RFC_HIERARCHY_DEPTH') END;
END;
CREATE TRIGGER rfc_hierarchy_insert_child_not_parent BEFORE INSERT ON rfc_hierarchy_edges WHEN NEW.edge_state = 'active' BEGIN
    SELECT CASE WHEN EXISTS (SELECT 1 FROM rfc_hierarchy_edges WHERE parent_rfc_id = NEW.child_rfc_id AND edge_state = 'active') THEN RAISE(ABORT, 'RFC_HIERARCHY_DEPTH') END;
END;
CREATE TRIGGER rfc_hierarchy_insert_child_without_direct_sr_link BEFORE INSERT ON rfc_hierarchy_edges WHEN NEW.edge_state = 'active' BEGIN
    SELECT CASE WHEN EXISTS (SELECT 1 FROM sr_rfc_links WHERE rfc_id = NEW.child_rfc_id AND link_state = 'active') THEN RAISE(ABORT, 'RFC_DIRECT_SR_LINK_ON_SUBORDINATE') END;
END;
CREATE TRIGGER sr_rfc_insert_root_only BEFORE INSERT ON sr_rfc_links WHEN NEW.link_state = 'active' BEGIN
    SELECT CASE WHEN EXISTS (SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id = NEW.rfc_id AND edge_state = 'active') THEN RAISE(ABORT, 'RFC_DIRECT_SR_LINK_ON_SUBORDINATE') END;
END;
CREATE TRIGGER rfc_hierarchy_update_guard BEFORE UPDATE ON rfc_hierarchy_edges BEGIN
    SELECT CASE WHEN OLD.edge_state <> 'active' OR NEW.rfc_hierarchy_edge_id <> OLD.rfc_hierarchy_edge_id OR NEW.parent_rfc_id <> OLD.parent_rfc_id OR NEW.child_rfc_id <> OLD.child_rfc_id OR NEW.opened_at_utc <> OLD.opened_at_utc OR NEW.opened_command_id <> OLD.opened_command_id OR NEW.edge_state <> 'superseded' OR NEW.closed_at_utc IS NULL OR NEW.closed_command_id IS NULL THEN RAISE(ABORT, 'RFC_HIERARCHY_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER rfc_hierarchy_delete_guard BEFORE DELETE ON rfc_hierarchy_edges BEGIN SELECT RAISE(ABORT, 'RFC_HIERARCHY_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER sr_rfc_link_update_guard BEFORE UPDATE ON sr_rfc_links BEGIN
    SELECT CASE WHEN OLD.link_state <> 'active' OR NEW.sr_rfc_link_id <> OLD.sr_rfc_link_id OR NEW.service_request_id <> OLD.service_request_id OR NEW.rfc_id <> OLD.rfc_id OR NEW.opened_at_utc <> OLD.opened_at_utc OR NEW.opened_command_id <> OLD.opened_command_id OR NEW.reason_category IS NOT OLD.reason_category OR NEW.link_state <> 'unlinked' OR NEW.closed_at_utc IS NULL OR NEW.closed_command_id IS NULL THEN RAISE(ABORT, 'TICKET_RELATIONSHIP_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER sr_rfc_link_delete_guard BEFORE DELETE ON sr_rfc_links BEGIN SELECT RAISE(ABORT, 'TICKET_RELATIONSHIP_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER rfc_device_link_update_guard BEFORE UPDATE ON rfc_device_reference_links BEGIN
    SELECT CASE WHEN OLD.link_state <> 'active' OR NEW.rfc_device_reference_link_id <> OLD.rfc_device_reference_link_id OR NEW.rfc_id <> OLD.rfc_id OR NEW.device_reference_id <> OLD.device_reference_id OR NEW.opened_at_utc <> OLD.opened_at_utc OR NEW.opened_command_id <> OLD.opened_command_id OR NEW.link_state <> 'unlinked' OR NEW.closed_at_utc IS NULL OR NEW.closed_command_id IS NULL THEN RAISE(ABORT, 'TICKET_RELATIONSHIP_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER rfc_device_link_delete_guard BEFORE DELETE ON rfc_device_reference_links BEGIN SELECT RAISE(ABORT, 'TICKET_RELATIONSHIP_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER sr_device_link_update_guard BEFORE UPDATE ON sr_device_reference_links BEGIN
    SELECT CASE WHEN OLD.link_state <> 'active' OR NEW.sr_device_reference_link_id <> OLD.sr_device_reference_link_id OR NEW.service_request_id <> OLD.service_request_id OR NEW.device_reference_id <> OLD.device_reference_id OR NEW.opened_at_utc <> OLD.opened_at_utc OR NEW.opened_command_id <> OLD.opened_command_id OR NEW.link_state <> 'unlinked' OR NEW.closed_at_utc IS NULL OR NEW.closed_command_id IS NULL THEN RAISE(ABORT, 'TICKET_RELATIONSHIP_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER sr_device_link_delete_guard BEFORE DELETE ON sr_device_reference_links BEGIN SELECT RAISE(ABORT, 'TICKET_RELATIONSHIP_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER sr_source_observation_update_guard BEFORE UPDATE ON sr_source_field_observations BEGIN SELECT RAISE(ABORT, 'SR_SOURCE_OBSERVATION_APPEND_ONLY'); END;
CREATE TRIGGER sr_source_observation_delete_guard BEFORE DELETE ON sr_source_field_observations BEGIN SELECT RAISE(ABORT, 'SR_SOURCE_OBSERVATION_APPEND_ONLY'); END;
CREATE TRIGGER sr_customer_relationship_update_guard BEFORE UPDATE ON sr_customer_relationships BEGIN
    SELECT CASE WHEN OLD.relationship_state <> 'active' OR NEW.sr_customer_relationship_id <> OLD.sr_customer_relationship_id OR NEW.service_request_id <> OLD.service_request_id OR NEW.customer_org_id <> OLD.customer_org_id OR NEW.origin_kind <> OLD.origin_kind OR NEW.reconciliation_proposal_id IS NOT OLD.reconciliation_proposal_id OR NEW.opened_at_utc <> OLD.opened_at_utc OR NEW.opened_command_id <> OLD.opened_command_id OR NEW.reason_category IS NOT OLD.reason_category OR NEW.relationship_state <> 'superseded' OR NEW.closed_at_utc IS NULL OR NEW.closed_command_id IS NULL THEN RAISE(ABORT, 'SR_REFERENCE_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER sr_customer_relationship_delete_guard BEFORE DELETE ON sr_customer_relationships BEGIN SELECT RAISE(ABORT, 'SR_REFERENCE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER sr_contact_relationship_update_guard BEFORE UPDATE ON sr_contact_relationships BEGIN
    SELECT CASE WHEN OLD.relationship_state <> 'active' OR NEW.sr_contact_relationship_id <> OLD.sr_contact_relationship_id OR NEW.service_request_id <> OLD.service_request_id OR NEW.reference_role <> OLD.reference_role OR NEW.contact_id <> OLD.contact_id OR NEW.customer_org_context_id IS NOT OLD.customer_org_context_id OR NEW.origin_kind <> OLD.origin_kind OR NEW.reconciliation_proposal_id IS NOT OLD.reconciliation_proposal_id OR NEW.supporting_sr_source_field_observation_id IS NOT OLD.supporting_sr_source_field_observation_id OR NEW.opened_at_utc <> OLD.opened_at_utc OR NEW.opened_command_id <> OLD.opened_command_id OR NEW.reason_category IS NOT OLD.reason_category OR NEW.relationship_state <> 'superseded' OR NEW.closed_at_utc IS NULL OR NEW.closed_command_id IS NULL THEN RAISE(ABORT, 'SR_REFERENCE_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER sr_contact_relationship_delete_guard BEFORE DELETE ON sr_contact_relationships BEGIN SELECT RAISE(ABORT, 'SR_REFERENCE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER sr_contact_current_handler_observation_guard BEFORE INSERT ON sr_contact_relationships WHEN NEW.reference_role = 'current_handler_reference' BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id = NEW.supporting_sr_source_field_observation_id AND service_request_id = NEW.service_request_id AND field_key = 'current_handler_label') THEN RAISE(ABORT, 'SR_HANDLER_REFERENCE_STALE') END;
END;
CREATE TRIGGER sr_contact_customer_contact_observation_guard BEFORE INSERT ON sr_contact_relationships WHEN NEW.reference_role = 'customer_contact' AND NEW.supporting_sr_source_field_observation_id IS NOT NULL BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id = NEW.supporting_sr_source_field_observation_id AND service_request_id = NEW.service_request_id AND field_key = 'customer_contact_label') THEN RAISE(ABORT, 'SR_REFERENCE_TARGET_INVALID') END;
END;
CREATE TRIGGER sr_working_note_update_guard BEFORE UPDATE ON sr_working_notes BEGIN
    SELECT CASE WHEN NEW.working_note_id <> OLD.working_note_id OR NEW.service_request_id <> OLD.service_request_id OR NEW.created_by_local_user_profile_id <> OLD.created_by_local_user_profile_id OR NEW.created_at_utc <> OLD.created_at_utc OR NEW.created_command_id <> OLD.created_command_id OR NEW.revision <> OLD.revision + 1 OR NEW.updated_at_utc < OLD.updated_at_utc THEN RAISE(ABORT, 'WORKING_NOTE_IMMUTABLE_PROVENANCE') END;
END;
CREATE TRIGGER rfc_working_note_update_guard BEFORE UPDATE ON rfc_working_notes BEGIN
    SELECT CASE WHEN NEW.working_note_id <> OLD.working_note_id OR NEW.rfc_id <> OLD.rfc_id OR NEW.created_by_local_user_profile_id <> OLD.created_by_local_user_profile_id OR NEW.created_at_utc <> OLD.created_at_utc OR NEW.created_command_id <> OLD.created_command_id OR NEW.revision <> OLD.revision + 1 OR NEW.updated_at_utc < OLD.updated_at_utc THEN RAISE(ABORT, 'WORKING_NOTE_IMMUTABLE_PROVENANCE') END;
END;
CREATE TRIGGER rfc_cascade_rfc_member_update_guard BEFORE UPDATE ON rfc_terminal_cascade_rfc_members BEGIN SELECT RAISE(ABORT, 'RFC_CASCADE_MEMBERSHIP_IMMUTABLE'); END;
CREATE TRIGGER rfc_cascade_rfc_member_delete_guard BEFORE DELETE ON rfc_terminal_cascade_rfc_members BEGIN SELECT RAISE(ABORT, 'RFC_CASCADE_MEMBERSHIP_IMMUTABLE'); END;
CREATE TRIGGER rfc_cascade_wfm_member_update_guard BEFORE UPDATE ON rfc_terminal_cascade_wfm_members BEGIN SELECT RAISE(ABORT, 'RFC_CASCADE_MEMBERSHIP_IMMUTABLE'); END;
CREATE TRIGGER rfc_cascade_wfm_member_delete_guard BEFORE DELETE ON rfc_terminal_cascade_wfm_members BEGIN SELECT RAISE(ABORT, 'RFC_CASCADE_MEMBERSHIP_IMMUTABLE'); END;
CREATE TRIGGER rfc_cascade_proposal_update_guard BEFORE UPDATE ON rfc_terminal_cascade_proposals BEGIN
    SELECT CASE WHEN OLD.proposal_state <> 'pending' OR NEW.rfc_terminal_cascade_proposal_id <> OLD.rfc_terminal_cascade_proposal_id OR NEW.trigger_rfc_id <> OLD.trigger_rfc_id OR NEW.terminal_epoch_id <> OLD.terminal_epoch_id OR NEW.terminal_status_class <> OLD.terminal_status_class OR NEW.terminal_status_evidence_id <> OLD.terminal_status_evidence_id OR NEW.scope_kind <> OLD.scope_kind OR NEW.scope_fingerprint <> OLD.scope_fingerprint OR NEW.created_at_utc <> OLD.created_at_utc OR NEW.created_command_id <> OLD.created_command_id OR NEW.revision <> OLD.revision + 1 OR NEW.proposal_state NOT IN ('executed','superseded') OR (NEW.proposal_state = 'executed' AND (NEW.executed_at_utc IS NULL OR NEW.executed_command_id IS NULL OR NEW.superseded_at_utc IS NOT NULL OR NEW.superseded_command_id IS NOT NULL)) OR (NEW.proposal_state = 'superseded' AND (NEW.superseded_at_utc IS NULL OR NEW.superseded_command_id IS NULL OR NEW.executed_at_utc IS NOT NULL OR NEW.executed_command_id IS NOT NULL)) THEN RAISE(ABORT, 'RFC_CASCADE_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER rfc_cascade_proposal_delete_guard BEFORE DELETE ON rfc_terminal_cascade_proposals BEGIN SELECT RAISE(ABORT, 'RFC_CASCADE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER rfc_archive_operation_update_guard BEFORE UPDATE ON rfc_archive_operations BEGIN SELECT RAISE(ABORT, 'RFC_ARCHIVE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER rfc_archive_operation_delete_guard BEFORE DELETE ON rfc_archive_operations BEGIN SELECT RAISE(ABORT, 'RFC_ARCHIVE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER rfc_archive_member_update_guard BEFORE UPDATE ON rfc_archive_operation_members BEGIN SELECT RAISE(ABORT, 'RFC_ARCHIVE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER rfc_archive_member_delete_guard BEFORE DELETE ON rfc_archive_operation_members BEGIN SELECT RAISE(ABORT, 'RFC_ARCHIVE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER rfc_archive_event_update_guard BEFORE UPDATE ON rfc_archive_events BEGIN SELECT RAISE(ABORT, 'RFC_ARCHIVE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER rfc_archive_event_delete_guard BEFORE DELETE ON rfc_archive_events BEGIN SELECT RAISE(ABORT, 'RFC_ARCHIVE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER rfc_archive_event_revision_guard BEFORE INSERT ON rfc_archive_events BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM rfcs WHERE rfc_id = NEW.rfc_id AND revision = NEW.resulting_rfc_revision) THEN RAISE(ABORT, 'RFC_ARCHIVE_SCOPE_STALE') END;
END;

CREATE TRIGGER sr_projection_insert_guard BEFORE INSERT ON sr_current_source_projection BEGIN
    SELECT CASE WHEN NEW.problem_summary_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.problem_summary_observation_id AND service_request_id=NEW.service_request_id AND field_key='problem_summary') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.report_date_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.report_date_observation_id AND service_request_id=NEW.service_request_id AND field_key='report_date') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.customer_contact_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.customer_contact_observation_id AND service_request_id=NEW.service_request_id AND field_key='customer_contact_label') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.customer_severity_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.customer_severity_observation_id AND service_request_id=NEW.service_request_id AND field_key='customer_severity') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.current_handler_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.current_handler_observation_id AND service_request_id=NEW.service_request_id AND field_key='current_handler_label') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.status_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.status_observation_id AND service_request_id=NEW.service_request_id AND field_key='status') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.customer_org_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.customer_org_observation_id AND service_request_id=NEW.service_request_id AND field_key='customer_org_label') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.customer_account_code_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.customer_account_code_observation_id AND service_request_id=NEW.service_request_id AND field_key='customer_account_code') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.suspend_planned_end_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.suspend_planned_end_observation_id AND service_request_id=NEW.service_request_id AND field_key='suspend_planned_end') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.suspension_duration_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.suspension_duration_observation_id AND service_request_id=NEW.service_request_id AND field_key='suspension_duration') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.last_update_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.last_update_observation_id AND service_request_id=NEW.service_request_id AND field_key='last_update') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
END;
CREATE TRIGGER sr_projection_update_guard BEFORE UPDATE ON sr_current_source_projection BEGIN
    SELECT CASE WHEN NEW.service_request_id <> OLD.service_request_id OR NEW.revision <> OLD.revision + 1 THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.problem_summary_observation_id IS OLD.problem_summary_observation_id AND NEW.report_date_observation_id IS OLD.report_date_observation_id AND NEW.customer_contact_observation_id IS OLD.customer_contact_observation_id AND NEW.customer_severity_observation_id IS OLD.customer_severity_observation_id AND NEW.current_handler_observation_id IS OLD.current_handler_observation_id AND NEW.status_observation_id IS OLD.status_observation_id AND NEW.customer_org_observation_id IS OLD.customer_org_observation_id AND NEW.customer_account_code_observation_id IS OLD.customer_account_code_observation_id AND NEW.suspend_planned_end_observation_id IS OLD.suspend_planned_end_observation_id AND NEW.suspension_duration_observation_id IS OLD.suspension_duration_observation_id AND NEW.last_update_observation_id IS OLD.last_update_observation_id THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.problem_summary_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.problem_summary_observation_id AND service_request_id=NEW.service_request_id AND field_key='problem_summary') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.report_date_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.report_date_observation_id AND service_request_id=NEW.service_request_id AND field_key='report_date') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.customer_contact_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.customer_contact_observation_id AND service_request_id=NEW.service_request_id AND field_key='customer_contact_label') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.customer_severity_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.customer_severity_observation_id AND service_request_id=NEW.service_request_id AND field_key='customer_severity') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.current_handler_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.current_handler_observation_id AND service_request_id=NEW.service_request_id AND field_key='current_handler_label') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.status_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.status_observation_id AND service_request_id=NEW.service_request_id AND field_key='status') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.customer_org_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.customer_org_observation_id AND service_request_id=NEW.service_request_id AND field_key='customer_org_label') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.customer_account_code_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.customer_account_code_observation_id AND service_request_id=NEW.service_request_id AND field_key='customer_account_code') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.suspend_planned_end_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.suspend_planned_end_observation_id AND service_request_id=NEW.service_request_id AND field_key='suspend_planned_end') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.suspension_duration_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.suspension_duration_observation_id AND service_request_id=NEW.service_request_id AND field_key='suspension_duration') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
    SELECT CASE WHEN NEW.last_update_observation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sr_source_field_observations WHERE sr_source_field_observation_id=NEW.last_update_observation_id AND service_request_id=NEW.service_request_id AND field_key='last_update') THEN RAISE(ABORT,'SR_SOURCE_PROJECTION_INVALID') END;
END;
