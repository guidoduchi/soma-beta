CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    task_kind TEXT NOT NULL CHECK(task_kind IN ('local','wfm')),
    local_task_name TEXT NULL,
    creation_origin TEXT NOT NULL CHECK(creation_origin IN ('manual','retry','wfm_manual','wfm_source_adoption','historical_source')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK((task_kind='local' AND local_task_name IS NOT NULL AND length(local_task_name)>0) OR (task_kind='wfm' AND local_task_name IS NULL))
) STRICT;

CREATE TABLE wfm_task_identities (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    task_no TEXT NOT NULL UNIQUE CHECK(length(task_no)=16 AND substr(task_no,1,2)='TK' AND substr(task_no,3) NOT GLOB '*[^0-9]*'),
    current_rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    assignment_revision INTEGER NOT NULL DEFAULT 1 CHECK(assignment_revision > 0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE wfm_rfc_assignment_events (
    assignment_event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES wfm_task_identities(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    prior_rfc_id TEXT NULL REFERENCES rfcs(rfc_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    new_rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    reason_code TEXT NOT NULL,
    review_risk TEXT NOT NULL CHECK(review_risk IN ('low','high')),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE wfm_source_projection_cache (
    task_id TEXT PRIMARY KEY REFERENCES wfm_task_identities(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    provider_status_token TEXT NULL,
    provider_lifecycle_class TEXT NOT NULL CHECK(provider_lifecycle_class IN ('unknown','active','complete','plan_cancel')),
    source_plan_start_utc INTEGER NULL CHECK(source_plan_start_utc IS NULL OR source_plan_start_utc >= 0),
    source_plan_end_utc INTEGER NULL CHECK(source_plan_end_utc IS NULL OR source_plan_end_utc >= 0),
    accepted_source_observation_id TEXT NULL,
    source_projection_revision INTEGER NOT NULL CHECK(source_projection_revision > 0),
    source_base_token TEXT NOT NULL CHECK(length(source_base_token)=64),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK((source_plan_start_utc IS NULL AND source_plan_end_utc IS NULL) OR
          (source_plan_start_utc IS NOT NULL AND source_plan_end_utc IS NOT NULL AND source_plan_end_utc > source_plan_start_utc))
) STRICT;

CREATE TABLE task_plan_revisions (
    plan_revision_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    start_utc INTEGER NOT NULL CHECK(start_utc >= 0),
    end_utc INTEGER NOT NULL CHECK(end_utc > start_utc),
    origin TEXT NOT NULL CHECK(origin IN ('manual','objective_initialization','wfm_source_adoption','retry_clone','correction','historical_source_structure')),
    scheduling_timezone_iana TEXT NOT NULL,
    source_observation_id TEXT NULL,
    predecessor_plan_revision_id TEXT NULL REFERENCES task_plan_revisions(plan_revision_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    reason_code TEXT NULL,
    accepted_at_utc INTEGER NOT NULL CHECK(accepted_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE task_plan_current (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    plan_revision_id TEXT NOT NULL UNIQUE REFERENCES task_plan_revisions(plan_revision_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE task_execution_events (
    execution_event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    execution_revision INTEGER NOT NULL CHECK(execution_revision > 0),
    event_kind TEXT NOT NULL CHECK(event_kind IN ('start','end','manual_cancel','rfc_terminal_terminate','source_terminal_consequence','correction')),
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc >= 0),
    target_event_id TEXT NULL REFERENCES task_execution_events(execution_event_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    correction_action TEXT NULL CHECK(correction_action IS NULL OR correction_action IN ('replace_time','withdraw')),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(task_id,execution_revision)
) STRICT;

CREATE TABLE task_execution_projection (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    execution_state TEXT NOT NULL CHECK(execution_state IN ('not_started','in_progress','ended','terminated')),
    actual_start_utc INTEGER NULL CHECK(actual_start_utc IS NULL OR actual_start_utc >= 0),
    actual_end_utc INTEGER NULL CHECK(actual_end_utc IS NULL OR actual_end_utc >= 0),
    effective_termination_utc INTEGER NULL CHECK(effective_termination_utc IS NULL OR effective_termination_utc >= 0),
    termination_reason TEXT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_event_id TEXT NOT NULL REFERENCES task_execution_events(execution_event_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE task_outcome_events (
    outcome_event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    accepted_outcome TEXT NOT NULL CHECK(accepted_outcome IN ('completed','incomplete','cancelled_without_execution')),
    correction_of_event_id TEXT NULL REFERENCES task_outcome_events(outcome_event_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    reason_code TEXT NULL,
    reviewed_at_utc INTEGER NOT NULL CHECK(reviewed_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE task_outcome_current (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    outcome_event_id TEXT NOT NULL UNIQUE REFERENCES task_outcome_events(outcome_event_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    accepted_outcome TEXT NOT NULL CHECK(accepted_outcome IN ('completed','incomplete','cancelled_without_execution')),
    reviewed_at_utc INTEGER NOT NULL CHECK(reviewed_at_utc >= 0),
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE task_lock_events (
    lock_event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    lock_kind TEXT NOT NULL CHECK(lock_kind IN ('plan','membership')),
    action TEXT NOT NULL CHECK(action IN ('lock','unlock')),
    reason_code TEXT NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE task_lock_projection (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    explicit_plan_lock INTEGER NOT NULL CHECK(explicit_plan_lock IN (0,1)),
    explicit_membership_lock INTEGER NOT NULL CHECK(explicit_membership_lock IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_event_id TEXT NULL REFERENCES task_lock_events(lock_event_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE task_sr_links (
    link_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    closed_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((active=1 AND closed_command_id IS NULL) OR (active=0 AND closed_command_id IS NOT NULL))
) STRICT;

CREATE TABLE task_rfc_links (
    link_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    rfc_id TEXT NOT NULL REFERENCES rfcs(rfc_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    closed_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((active=1 AND closed_command_id IS NULL) OR (active=0 AND closed_command_id IS NOT NULL))
) STRICT;

CREATE TABLE task_device_links (
    link_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    device_reference_id TEXT NOT NULL REFERENCES device_references(device_reference_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    closed_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((active=1 AND closed_command_id IS NULL) OR (active=0 AND closed_command_id IS NOT NULL))
) STRICT;

CREATE TABLE task_retry_relations (
    retry_relation_id TEXT PRIMARY KEY,
    predecessor_task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    successor_task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK(predecessor_task_id <> successor_task_id)
) STRICT;

CREATE TABLE task_activity_lineages (
    activity_lineage_id TEXT PRIMARY KEY,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE task_activity_lineage_events (
    lineage_event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    prior_lineage_id TEXT NULL REFERENCES task_activity_lineages(activity_lineage_id) ON DELETE RESTRICT,
    new_lineage_id TEXT NULL REFERENCES task_activity_lineages(activity_lineage_id) ON DELETE RESTRICT,
    reason_code TEXT NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE task_activity_lineage_current (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT,
    activity_lineage_id TEXT NOT NULL REFERENCES task_activity_lineages(activity_lineage_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_event_id TEXT NOT NULL REFERENCES task_activity_lineage_events(lineage_event_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE task_operational_count_events (
    inclusion_event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    included INTEGER NOT NULL CHECK(included IN (0,1)),
    reason_code TEXT NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE task_operational_count_current (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT,
    included INTEGER NOT NULL CHECK(included IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_event_id TEXT NOT NULL REFERENCES task_operational_count_events(inclusion_event_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE objective_tracking_allocator (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
    next_sequence INTEGER NOT NULL CHECK(next_sequence BETWEEN 1 AND 100000000),
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

INSERT INTO objective_tracking_allocator(singleton_id,next_sequence,revision,last_command_id)
VALUES (1,1,1,NULL);

CREATE TABLE objectives (
    objective_id TEXT PRIMARY KEY,
    tracking_sequence INTEGER NOT NULL UNIQUE CHECK(tracking_sequence BETWEEN 1 AND 99999999),
    tracking_id TEXT NOT NULL UNIQUE CHECK(length(tracking_id)=11 AND substr(tracking_id,1,3)='MW-' AND substr(tracking_id,4) NOT GLOB '*[^0-9]*'),
    creation_origin TEXT NOT NULL CHECK(creation_origin IN ('manual','automatic_grouping','historical_provider_complete')),
    superseded_by_objective_id TEXT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK(superseded_by_objective_id IS NULL OR superseded_by_objective_id <> objective_id)
) STRICT;

CREATE TABLE objective_membership_events (
    membership_event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('add','move','remove','repin_plan','historical_add')),
    from_objective_id TEXT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    to_objective_id TEXT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    accepted_plan_revision_id TEXT NOT NULL REFERENCES task_plan_revisions(plan_revision_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    grouping_proposal_id TEXT NULL,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK(from_objective_id IS NOT NULL OR to_objective_id IS NOT NULL)
) STRICT;

CREATE TABLE objective_task_membership_current (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    objective_id TEXT NOT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    accepted_plan_revision_id TEXT NOT NULL REFERENCES task_plan_revisions(plan_revision_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    membership_revision INTEGER NOT NULL CHECK(membership_revision > 0),
    last_event_id TEXT NOT NULL REFERENCES objective_membership_events(membership_event_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE objective_envelope_projection (
    objective_id TEXT PRIMARY KEY REFERENCES objectives(objective_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    start_utc INTEGER NOT NULL CHECK(start_utc >= 0),
    end_utc INTEGER NOT NULL CHECK(end_utc > start_utc),
    member_count INTEGER NOT NULL CHECK(member_count > 0),
    membership_input_fingerprint TEXT NOT NULL CHECK(length(membership_input_fingerprint)=64),
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE objective_aggregate_projection (
    objective_id TEXT PRIMARY KEY REFERENCES objectives(objective_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    execution_state TEXT NOT NULL CHECK(execution_state IN ('planned','historical_structure','in_progress','awaiting_review','reviewed','superseded')),
    aggregate_outcome TEXT NULL CHECK(aggregate_outcome IS NULL OR aggregate_outcome IN ('completed','incomplete','cancelled','mixed','excluded_from_operational_counts')),
    actual_start_utc INTEGER NULL CHECK(actual_start_utc IS NULL OR actual_start_utc >= 0),
    actual_end_utc INTEGER NULL CHECK(actual_end_utc IS NULL OR actual_end_utc >= 0),
    attention_reason TEXT NULL CHECK(attention_reason IS NULL OR attention_reason IN ('due_unreviewed','lost_last_executable','mixed_outcomes','plan_membership_mismatch','source_terminal_conflict')),
    included_task_count INTEGER NOT NULL CHECK(included_task_count >= 0),
    excluded_task_count INTEGER NOT NULL CHECK(excluded_task_count >= 0),
    aggregate_input_fingerprint TEXT NOT NULL CHECK(length(aggregate_input_fingerprint)=64),
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE objective_review_events (
    objective_review_event_id TEXT PRIMARY KEY,
    objective_id TEXT NOT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    review_fingerprint TEXT NOT NULL CHECK(length(review_fingerprint)=64),
    derived_outcome TEXT NOT NULL CHECK(derived_outcome IN ('completed','incomplete','cancelled','mixed','excluded_from_operational_counts')),
    reviewed_at_utc INTEGER NOT NULL CHECK(reviewed_at_utc >= 0),
    reason_code TEXT NULL,
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE TABLE objective_archive_events (
    archive_event_id TEXT PRIMARY KEY,
    objective_id TEXT NOT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK(action IN ('archive','restore')),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE objective_archive_projection (
    objective_id TEXT PRIMARY KEY REFERENCES objectives(objective_id) ON DELETE RESTRICT,
    archived INTEGER NOT NULL CHECK(archived IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision > 0),
    last_event_id TEXT NULL REFERENCES objective_archive_events(archive_event_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE regroup_proposals (
    regroup_proposal_id TEXT PRIMARY KEY,
    proposal_kind TEXT NOT NULL CHECK(proposal_kind IN ('create','join','move','repin','consolidate','manual_merge','manual_split')),
    origin TEXT NOT NULL CHECK(origin IN ('task_created','task_plan_changed','source_plan_adopted','manual_request','retry_created','objective_edit')),
    risk_tier TEXT NOT NULL CHECK(risk_tier IN ('normal','high')),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    state TEXT NOT NULL CHECK(state IN ('pending','accepted','rejected','superseded')),
    survivor_objective_id TEXT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    last_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE regroup_proposal_task_changes (
    proposal_task_change_id TEXT PRIMARY KEY,
    regroup_proposal_id TEXT NOT NULL REFERENCES regroup_proposals(regroup_proposal_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    from_objective_id TEXT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT,
    to_objective_id TEXT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT,
    expected_task_revision INTEGER NOT NULL CHECK(expected_task_revision > 0),
    expected_current_plan_revision_id TEXT NOT NULL REFERENCES task_plan_revisions(plan_revision_id) ON DELETE RESTRICT,
    expected_membership_revision INTEGER NULL CHECK(expected_membership_revision IS NULL OR expected_membership_revision > 0),
    change_kind TEXT NOT NULL CHECK(change_kind IN ('add','move','remove','repin','unchanged_context'))
) STRICT;

CREATE TABLE regroup_proposal_objective_changes (
    proposal_objective_change_id TEXT PRIMARY KEY,
    regroup_proposal_id TEXT NOT NULL REFERENCES regroup_proposals(regroup_proposal_id) ON DELETE CASCADE,
    objective_id TEXT NULL REFERENCES objectives(objective_id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK(action IN ('create','retain','supersede','envelope_change')),
    expected_objective_revision INTEGER NULL CHECK(expected_objective_revision IS NULL OR expected_objective_revision > 0),
    expected_envelope_revision INTEGER NULL CHECK(expected_envelope_revision IS NULL OR expected_envelope_revision > 0)
) STRICT;

CREATE TABLE regroup_rejection_events (
    rejection_event_id TEXT PRIMARY KEY,
    regroup_proposal_id TEXT NOT NULL REFERENCES regroup_proposals(regroup_proposal_id) ON DELETE RESTRICT,
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    reason_code TEXT NOT NULL,
    reconsidered_at_utc INTEGER NULL CHECK(reconsidered_at_utc IS NULL OR reconsidered_at_utc >= 0),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE historical_objective_proposals (
    historical_proposal_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES wfm_task_identities(task_id) ON DELETE RESTRICT,
    expected_wfm_source_projection_revision INTEGER NOT NULL CHECK(expected_wfm_source_projection_revision > 0),
    expected_source_plan_start_utc INTEGER NOT NULL CHECK(expected_source_plan_start_utc >= 0),
    expected_source_plan_end_utc INTEGER NOT NULL CHECK(expected_source_plan_end_utc > expected_source_plan_start_utc),
    expected_source_observation_id TEXT NOT NULL,
    expected_matching_operational_plan_revision_id TEXT NULL REFERENCES task_plan_revisions(plan_revision_id) ON DELETE RESTRICT,
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    state TEXT NOT NULL CHECK(state IN ('pending','accepted','rejected','superseded')),
    revision INTEGER NOT NULL CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    last_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE wfm_source_terminal_reviews (
    source_terminal_review_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES wfm_task_identities(task_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    source_projection_revision INTEGER NOT NULL CHECK(source_projection_revision > 0),
    provider_lifecycle_class TEXT NOT NULL CHECK(provider_lifecycle_class IN ('complete','plan_cancel')),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    state TEXT NOT NULL CHECK(state IN ('pending','retain_local_work','terminate_local_work','superseded')),
    local_consequence_event_id TEXT NULL REFERENCES task_execution_events(execution_event_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    decided_at_utc INTEGER NULL CHECK(decided_at_utc IS NULL OR decided_at_utc >= 0),
    last_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE INDEX idx_tasks_created_command_fk ON tasks(created_command_id);
CREATE INDEX idx_wfm_identity_rfc_task ON wfm_task_identities(current_rfc_id,task_id);
CREATE INDEX idx_wfm_identity_created_command_fk ON wfm_task_identities(created_command_id);
CREATE INDEX idx_wfm_assignment_task_recorded ON wfm_rfc_assignment_events(task_id,recorded_at_utc,assignment_event_id);
CREATE INDEX idx_wfm_assignment_prior_rfc_fk ON wfm_rfc_assignment_events(prior_rfc_id);
CREATE INDEX idx_wfm_assignment_new_rfc_fk ON wfm_rfc_assignment_events(new_rfc_id);
CREATE INDEX idx_wfm_assignment_command_fk ON wfm_rfc_assignment_events(command_id);
CREATE INDEX idx_wfm_source_last_command_fk ON wfm_source_projection_cache(last_command_id);
CREATE INDEX idx_task_plan_task_accepted ON task_plan_revisions(task_id,accepted_at_utc,plan_revision_id);
CREATE INDEX idx_task_plan_predecessor_fk ON task_plan_revisions(predecessor_plan_revision_id);
CREATE INDEX idx_task_plan_command_fk ON task_plan_revisions(command_id);
CREATE INDEX idx_task_plan_current_last_command_fk ON task_plan_current(last_command_id);
CREATE INDEX idx_task_execution_task_revision ON task_execution_events(task_id,execution_revision);
CREATE INDEX idx_task_execution_task_recorded ON task_execution_events(task_id,recorded_at_utc,execution_event_id);
CREATE INDEX idx_task_execution_target_fk ON task_execution_events(target_event_id);
CREATE INDEX idx_task_execution_command_fk ON task_execution_events(command_id);
CREATE INDEX idx_task_execution_projection_event_fk ON task_execution_projection(last_event_id);
CREATE INDEX idx_task_outcome_task_reviewed ON task_outcome_events(task_id,reviewed_at_utc,outcome_event_id);
CREATE INDEX idx_task_outcome_correction_fk ON task_outcome_events(correction_of_event_id);
CREATE INDEX idx_task_outcome_command_fk ON task_outcome_events(command_id);
CREATE INDEX idx_task_outcome_current_last_command_fk ON task_outcome_current(last_command_id);
CREATE INDEX idx_task_lock_task_recorded ON task_lock_events(task_id,recorded_at_utc,lock_event_id);
CREATE INDEX idx_task_lock_command_fk ON task_lock_events(command_id);
CREATE INDEX idx_task_lock_projection_event_fk ON task_lock_projection(last_event_id);
CREATE INDEX idx_task_sr_links_task_active_target ON task_sr_links(task_id,active,service_request_id);
CREATE UNIQUE INDEX uq_task_sr_links_active ON task_sr_links(task_id,service_request_id) WHERE active=1;
CREATE INDEX idx_task_sr_links_service_request_fk ON task_sr_links(service_request_id);
CREATE INDEX idx_task_sr_links_opened_command_fk ON task_sr_links(opened_command_id);
CREATE INDEX idx_task_sr_links_closed_command_fk ON task_sr_links(closed_command_id);
CREATE INDEX idx_task_rfc_links_task_active_target ON task_rfc_links(task_id,active,rfc_id);
CREATE UNIQUE INDEX uq_task_rfc_links_active ON task_rfc_links(task_id,rfc_id) WHERE active=1;
CREATE INDEX idx_task_rfc_links_rfc_fk ON task_rfc_links(rfc_id);
CREATE INDEX idx_task_rfc_links_opened_command_fk ON task_rfc_links(opened_command_id);
CREATE INDEX idx_task_rfc_links_closed_command_fk ON task_rfc_links(closed_command_id);
CREATE INDEX idx_task_device_links_task_active_target ON task_device_links(task_id,active,device_reference_id);
CREATE UNIQUE INDEX uq_task_device_links_active ON task_device_links(task_id,device_reference_id) WHERE active=1;
CREATE INDEX idx_task_device_links_device_fk ON task_device_links(device_reference_id);
CREATE INDEX idx_task_device_links_opened_command_fk ON task_device_links(opened_command_id);
CREATE INDEX idx_task_device_links_closed_command_fk ON task_device_links(closed_command_id);
CREATE INDEX idx_task_retry_command_fk ON task_retry_relations(command_id);
CREATE INDEX idx_task_activity_lineage_created_command_fk ON task_activity_lineages(created_command_id);
CREATE INDEX idx_task_activity_lineage_event_task_fk ON task_activity_lineage_events(task_id);
CREATE INDEX idx_task_activity_lineage_event_prior_fk ON task_activity_lineage_events(prior_lineage_id);
CREATE INDEX idx_task_activity_lineage_event_new_fk ON task_activity_lineage_events(new_lineage_id);
CREATE INDEX idx_task_activity_lineage_event_command_fk ON task_activity_lineage_events(command_id);
CREATE INDEX idx_task_activity_lineage_current_lineage_task ON task_activity_lineage_current(activity_lineage_id,task_id);
CREATE INDEX idx_task_activity_lineage_current_event_fk ON task_activity_lineage_current(last_event_id);
CREATE INDEX idx_task_operational_count_event_task_fk ON task_operational_count_events(task_id);
CREATE INDEX idx_task_operational_count_event_command_fk ON task_operational_count_events(command_id);
CREATE INDEX idx_task_operational_count_current_event_fk ON task_operational_count_current(last_event_id);
CREATE INDEX idx_objective_allocator_last_command_fk ON objective_tracking_allocator(last_command_id);
CREATE INDEX idx_objectives_superseded_by_fk ON objectives(superseded_by_objective_id);
CREATE INDEX idx_objectives_created_command_fk ON objectives(created_command_id);
CREATE INDEX idx_objective_membership_event_task_recorded ON objective_membership_events(task_id,recorded_at_utc,membership_event_id);
CREATE INDEX idx_objective_membership_event_from_fk ON objective_membership_events(from_objective_id);
CREATE INDEX idx_objective_membership_event_to_recorded ON objective_membership_events(to_objective_id,recorded_at_utc,membership_event_id);
CREATE INDEX idx_objective_membership_event_plan_fk ON objective_membership_events(accepted_plan_revision_id);
CREATE INDEX idx_objective_membership_event_command_fk ON objective_membership_events(command_id);
CREATE INDEX idx_objective_membership_current_objective_task ON objective_task_membership_current(objective_id,task_id);
CREATE INDEX idx_objective_membership_current_plan_fk ON objective_task_membership_current(accepted_plan_revision_id);
CREATE INDEX idx_objective_membership_current_event_fk ON objective_task_membership_current(last_event_id);
CREATE INDEX idx_objective_membership_current_command_fk ON objective_task_membership_current(last_command_id);
CREATE INDEX idx_objective_envelope_interval ON objective_envelope_projection(start_utc,end_utc,objective_id);
CREATE INDEX idx_objective_envelope_command_fk ON objective_envelope_projection(last_command_id);
CREATE INDEX idx_objective_aggregate_state_attention ON objective_aggregate_projection(execution_state,attention_reason,objective_id);
CREATE INDEX idx_objective_aggregate_command_fk ON objective_aggregate_projection(last_command_id);
CREATE INDEX idx_objective_review_objective_reviewed ON objective_review_events(objective_id,reviewed_at_utc,objective_review_event_id);
CREATE INDEX idx_objective_review_command_fk ON objective_review_events(command_id);
CREATE INDEX idx_objective_archive_event_objective_fk ON objective_archive_events(objective_id);
CREATE INDEX idx_objective_archive_event_command_fk ON objective_archive_events(command_id);
CREATE INDEX idx_objective_archive_projection_event_fk ON objective_archive_projection(last_event_id);
CREATE INDEX idx_regroup_proposals_state_created ON regroup_proposals(state,created_at_utc,regroup_proposal_id);
CREATE INDEX idx_regroup_proposals_survivor_fk ON regroup_proposals(survivor_objective_id);
CREATE INDEX idx_regroup_proposals_last_command_fk ON regroup_proposals(last_command_id);
CREATE UNIQUE INDEX uq_regroup_task_change_proposal_task ON regroup_proposal_task_changes(regroup_proposal_id,task_id);
CREATE INDEX idx_regroup_task_change_task_proposal ON regroup_proposal_task_changes(task_id,regroup_proposal_id);
CREATE INDEX idx_regroup_task_change_from_objective_fk ON regroup_proposal_task_changes(from_objective_id);
CREATE INDEX idx_regroup_task_change_to_objective_fk ON regroup_proposal_task_changes(to_objective_id);
CREATE INDEX idx_regroup_task_change_plan_fk ON regroup_proposal_task_changes(expected_current_plan_revision_id);
CREATE INDEX idx_regroup_objective_change_proposal_fk ON regroup_proposal_objective_changes(regroup_proposal_id);
CREATE INDEX idx_regroup_objective_change_objective_fk ON regroup_proposal_objective_changes(objective_id);
CREATE INDEX idx_regroup_rejection_fingerprint_recorded ON regroup_rejection_events(input_fingerprint,recorded_at_utc,rejection_event_id);
CREATE INDEX idx_regroup_rejection_proposal_fk ON regroup_rejection_events(regroup_proposal_id);
CREATE INDEX idx_regroup_rejection_command_fk ON regroup_rejection_events(command_id);
CREATE INDEX idx_historical_proposal_task_state ON historical_objective_proposals(task_id,state,historical_proposal_id);
CREATE INDEX idx_historical_proposal_plan_fk ON historical_objective_proposals(expected_matching_operational_plan_revision_id);
CREATE INDEX idx_historical_proposal_last_command_fk ON historical_objective_proposals(last_command_id);
CREATE INDEX idx_wfm_terminal_review_task_state_created ON wfm_source_terminal_reviews(task_id,state,created_at_utc,source_terminal_review_id);
CREATE INDEX idx_wfm_terminal_review_fingerprint_state ON wfm_source_terminal_reviews(input_fingerprint,state,source_terminal_review_id);
CREATE INDEX idx_wfm_terminal_review_source_revision_task ON wfm_source_terminal_reviews(source_projection_revision,task_id);
CREATE INDEX idx_wfm_terminal_review_consequence_fk ON wfm_source_terminal_reviews(local_consequence_event_id);
CREATE INDEX idx_wfm_terminal_review_last_command_fk ON wfm_source_terminal_reviews(last_command_id);

CREATE TRIGGER tasks_update_guard BEFORE UPDATE ON tasks BEGIN
    SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.task_kind<>OLD.task_kind OR NEW.local_task_name IS NOT OLD.local_task_name OR NEW.creation_origin<>OLD.creation_origin OR NEW.created_at_utc<>OLD.created_at_utc OR NEW.created_command_id<>OLD.created_command_id OR NEW.revision<>OLD.revision+1 THEN RAISE(ABORT,'TASK_IDENTITY_IMMUTABLE') END;
END;
CREATE TRIGGER tasks_delete_guard BEFORE DELETE ON tasks BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id) THEN RAISE(ABORT,'TASK_HARD_DELETE_REQUIRED') END;
END;
CREATE TRIGGER wfm_identity_insert_guard BEFORE INSERT ON wfm_task_identities BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM tasks WHERE task_id=NEW.task_id AND task_kind='wfm') THEN RAISE(ABORT,'WFM_TASK_KIND_INVALID') END;
END;
CREATE TRIGGER wfm_identity_update_guard BEFORE UPDATE ON wfm_task_identities BEGIN
    SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.task_no<>OLD.task_no OR NEW.created_command_id<>OLD.created_command_id OR NEW.assignment_revision<>OLD.assignment_revision+1 OR NEW.current_rfc_id=OLD.current_rfc_id THEN RAISE(ABORT,'WFM_IDENTITY_IMMUTABLE') END;
END;
CREATE TRIGGER wfm_assignment_update_guard BEFORE UPDATE ON wfm_rfc_assignment_events BEGIN SELECT RAISE(ABORT,'WFM_ASSIGNMENT_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER wfm_assignment_delete_guard BEFORE DELETE ON wfm_rfc_assignment_events BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id)
      OR NOT EXISTS (SELECT 1 FROM tasks t JOIN wfm_task_identities w ON w.task_id=t.task_id WHERE t.task_id=OLD.task_id AND t.task_kind='wfm' AND t.creation_origin='wfm_manual' AND OLD.prior_rfc_id IS NULL AND OLD.new_rfc_id=w.current_rfc_id AND OLD.command_id=w.created_command_id)
      OR (SELECT count(*) FROM wfm_rfc_assignment_events WHERE task_id=OLD.task_id)<>1
      OR EXISTS (SELECT 1 FROM wfm_source_projection_cache WHERE task_id=OLD.task_id)
      THEN RAISE(ABORT,'WFM_ASSIGNMENT_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER wfm_identity_delete_guard BEFORE DELETE ON wfm_task_identities BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id)
      OR NOT EXISTS (SELECT 1 FROM tasks WHERE task_id=OLD.task_id AND task_kind='wfm' AND creation_origin='wfm_manual')
      OR EXISTS (SELECT 1 FROM wfm_source_projection_cache WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM wfm_rfc_assignment_events WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_plan_revisions WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_execution_events WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_outcome_events WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_lock_events WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM objective_task_membership_current WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_retry_relations WHERE predecessor_task_id=OLD.task_id OR successor_task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_activity_lineage_events WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_operational_count_events WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_sr_links WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_rfc_links WHERE task_id=OLD.task_id)
      OR EXISTS (SELECT 1 FROM task_device_links WHERE task_id=OLD.task_id)
      THEN RAISE(ABORT,'WFM_IDENTITY_PROTECTED') END;
END;
CREATE TRIGGER wfm_source_projection_update_guard BEFORE UPDATE ON wfm_source_projection_cache BEGIN
    SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.source_projection_revision<>OLD.source_projection_revision+1 THEN RAISE(ABORT,'WFM_SOURCE_PROJECTION_INVALID') END;
END;
CREATE TRIGGER wfm_source_projection_delete_guard BEFORE DELETE ON wfm_source_projection_cache BEGIN SELECT RAISE(ABORT,'WFM_SOURCE_PROJECTION_PROTECTED'); END;
CREATE TRIGGER task_plan_revision_update_guard BEFORE UPDATE ON task_plan_revisions BEGIN SELECT RAISE(ABORT,'TASK_PLAN_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_plan_revision_delete_guard BEFORE DELETE ON task_plan_revisions BEGIN
    SELECT CASE WHEN OLD.predecessor_plan_revision_id IS NOT NULL OR OLD.source_observation_id IS NOT NULL OR OLD.origin NOT IN ('manual','objective_initialization') OR EXISTS (SELECT 1 FROM task_plan_revisions p WHERE p.task_id=OLD.task_id AND p.plan_revision_id<>OLD.plan_revision_id) OR NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id) THEN RAISE(ABORT,'TASK_PLAN_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER task_plan_current_insert_guard BEFORE INSERT ON task_plan_current BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM task_plan_revisions WHERE plan_revision_id=NEW.plan_revision_id AND task_id=NEW.task_id) THEN RAISE(ABORT,'TASK_PLAN_CURRENT_INVALID') END;
END;
CREATE TRIGGER task_plan_current_update_guard BEFORE UPDATE ON task_plan_current BEGIN
    SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.revision<>OLD.revision+1 OR NEW.plan_revision_id=OLD.plan_revision_id OR NOT EXISTS (SELECT 1 FROM task_plan_revisions WHERE plan_revision_id=NEW.plan_revision_id AND task_id=NEW.task_id) THEN RAISE(ABORT,'TASK_PLAN_CURRENT_INVALID') END;
END;
CREATE TRIGGER task_plan_current_delete_guard BEFORE DELETE ON task_plan_current BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id) THEN RAISE(ABORT,'TASK_PLAN_CURRENT_PROTECTED') END;
END;
CREATE TRIGGER task_execution_event_insert_guard BEFORE INSERT ON task_execution_events BEGIN
    SELECT CASE WHEN NEW.execution_revision <> COALESCE((SELECT max(execution_revision) FROM task_execution_events WHERE task_id=NEW.task_id),0)+1 THEN RAISE(ABORT,'TASK_EXECUTION_REVISION_SEQUENCE_INVALID') END;
END;
CREATE TRIGGER task_execution_event_update_guard BEFORE UPDATE ON task_execution_events BEGIN SELECT RAISE(ABORT,'TASK_EXECUTION_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_execution_event_delete_guard BEFORE DELETE ON task_execution_events BEGIN SELECT RAISE(ABORT,'TASK_EXECUTION_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_execution_projection_insert_guard BEFORE INSERT ON task_execution_projection BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM task_execution_events WHERE execution_event_id=NEW.last_event_id AND task_id=NEW.task_id AND execution_revision=NEW.revision) OR (SELECT count(*) FROM task_execution_events WHERE task_id=NEW.task_id)<>NEW.revision THEN RAISE(ABORT,'TASK_EXECUTION_PROJECTION_INVALID') END;
END;
CREATE TRIGGER task_execution_projection_update_guard BEFORE UPDATE ON task_execution_projection BEGIN
    SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.revision<>OLD.revision+1 OR NOT EXISTS (SELECT 1 FROM task_execution_events WHERE execution_event_id=NEW.last_event_id AND task_id=NEW.task_id AND execution_revision=NEW.revision) OR (SELECT count(*) FROM task_execution_events WHERE task_id=NEW.task_id)<>NEW.revision THEN RAISE(ABORT,'TASK_EXECUTION_PROJECTION_INVALID') END;
END;
CREATE TRIGGER task_outcome_event_update_guard BEFORE UPDATE ON task_outcome_events BEGIN SELECT RAISE(ABORT,'TASK_OUTCOME_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_outcome_event_delete_guard BEFORE DELETE ON task_outcome_events BEGIN SELECT RAISE(ABORT,'TASK_OUTCOME_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_outcome_current_insert_guard BEFORE INSERT ON task_outcome_current BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM task_outcome_events WHERE outcome_event_id=NEW.outcome_event_id AND task_id=NEW.task_id AND accepted_outcome=NEW.accepted_outcome AND reviewed_at_utc=NEW.reviewed_at_utc) THEN RAISE(ABORT,'TASK_OUTCOME_CURRENT_INVALID') END;
END;
CREATE TRIGGER task_outcome_current_update_guard BEFORE UPDATE ON task_outcome_current BEGIN
    SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.revision<>OLD.revision+1 OR NEW.outcome_event_id=OLD.outcome_event_id OR NOT EXISTS (SELECT 1 FROM task_outcome_events WHERE outcome_event_id=NEW.outcome_event_id AND task_id=NEW.task_id AND accepted_outcome=NEW.accepted_outcome AND reviewed_at_utc=NEW.reviewed_at_utc) THEN RAISE(ABORT,'TASK_OUTCOME_CURRENT_INVALID') END;
END;
CREATE TRIGGER task_lock_event_update_guard BEFORE UPDATE ON task_lock_events BEGIN SELECT RAISE(ABORT,'TASK_LOCK_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_lock_event_delete_guard BEFORE DELETE ON task_lock_events BEGIN SELECT RAISE(ABORT,'TASK_LOCK_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_lock_projection_insert_guard BEFORE INSERT ON task_lock_projection WHEN NEW.last_event_id IS NOT NULL BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM task_lock_events WHERE lock_event_id=NEW.last_event_id AND task_id=NEW.task_id) THEN RAISE(ABORT,'TASK_LOCK_PROJECTION_INVALID') END;
END;
CREATE TRIGGER task_lock_projection_update_guard BEFORE UPDATE ON task_lock_projection BEGIN
    SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.revision<>OLD.revision+1 OR (NEW.last_event_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM task_lock_events WHERE lock_event_id=NEW.last_event_id AND task_id=NEW.task_id)) THEN RAISE(ABORT,'TASK_LOCK_PROJECTION_INVALID') END;
END;
CREATE TRIGGER task_lock_projection_delete_guard BEFORE DELETE ON task_lock_projection BEGIN
    SELECT CASE WHEN OLD.last_event_id IS NOT NULL OR NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id) THEN RAISE(ABORT,'TASK_LOCK_PROJECTION_PROTECTED') END;
END;

CREATE TRIGGER task_sr_link_insert_guard BEFORE INSERT ON task_sr_links BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM tasks WHERE task_id=NEW.task_id AND task_kind='local') THEN RAISE(ABORT,'TASK_RELATIONSHIP_INVALID') END; END;
CREATE TRIGGER task_rfc_link_insert_guard BEFORE INSERT ON task_rfc_links BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM tasks WHERE task_id=NEW.task_id AND task_kind='local') THEN RAISE(ABORT,'TASK_RELATIONSHIP_INVALID') END; END;
CREATE TRIGGER task_sr_link_update_guard BEFORE UPDATE ON task_sr_links BEGIN SELECT CASE WHEN OLD.active<>1 OR NEW.link_id<>OLD.link_id OR NEW.task_id<>OLD.task_id OR NEW.service_request_id<>OLD.service_request_id OR NEW.opened_command_id<>OLD.opened_command_id OR NEW.active<>0 OR NEW.closed_command_id IS NULL THEN RAISE(ABORT,'TASK_RELATIONSHIP_HISTORY_APPEND_ONLY') END; END;
CREATE TRIGGER task_rfc_link_update_guard BEFORE UPDATE ON task_rfc_links BEGIN SELECT CASE WHEN OLD.active<>1 OR NEW.link_id<>OLD.link_id OR NEW.task_id<>OLD.task_id OR NEW.rfc_id<>OLD.rfc_id OR NEW.opened_command_id<>OLD.opened_command_id OR NEW.active<>0 OR NEW.closed_command_id IS NULL THEN RAISE(ABORT,'TASK_RELATIONSHIP_HISTORY_APPEND_ONLY') END; END;
CREATE TRIGGER task_device_link_update_guard BEFORE UPDATE ON task_device_links BEGIN SELECT CASE WHEN OLD.active<>1 OR NEW.link_id<>OLD.link_id OR NEW.task_id<>OLD.task_id OR NEW.device_reference_id<>OLD.device_reference_id OR NEW.opened_command_id<>OLD.opened_command_id OR NEW.active<>0 OR NEW.closed_command_id IS NULL THEN RAISE(ABORT,'TASK_RELATIONSHIP_HISTORY_APPEND_ONLY') END; END;
CREATE TRIGGER task_sr_link_delete_guard BEFORE DELETE ON task_sr_links BEGIN SELECT CASE WHEN OLD.active<>1 OR NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id) THEN RAISE(ABORT,'TASK_RELATIONSHIP_HISTORY_APPEND_ONLY') END; END;
CREATE TRIGGER task_rfc_link_delete_guard BEFORE DELETE ON task_rfc_links BEGIN SELECT CASE WHEN OLD.active<>1 OR NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id) THEN RAISE(ABORT,'TASK_RELATIONSHIP_HISTORY_APPEND_ONLY') END; END;
CREATE TRIGGER task_device_link_delete_guard BEFORE DELETE ON task_device_links BEGIN SELECT CASE WHEN OLD.active<>1 OR NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' AND target_type='task' AND target_id=OLD.task_id) THEN RAISE(ABORT,'TASK_RELATIONSHIP_HISTORY_APPEND_ONLY') END; END;
CREATE TRIGGER task_retry_update_guard BEFORE UPDATE ON task_retry_relations BEGIN SELECT RAISE(ABORT,'TASK_RETRY_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_retry_delete_guard BEFORE DELETE ON task_retry_relations BEGIN SELECT RAISE(ABORT,'TASK_RETRY_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_activity_lineage_update_guard BEFORE UPDATE ON task_activity_lineages BEGIN SELECT RAISE(ABORT,'TASK_ACTIVITY_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_activity_lineage_delete_guard BEFORE DELETE ON task_activity_lineages BEGIN SELECT RAISE(ABORT,'TASK_ACTIVITY_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_activity_event_update_guard BEFORE UPDATE ON task_activity_lineage_events BEGIN SELECT RAISE(ABORT,'TASK_ACTIVITY_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_activity_event_delete_guard BEFORE DELETE ON task_activity_lineage_events BEGIN SELECT RAISE(ABORT,'TASK_ACTIVITY_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_activity_current_insert_guard BEFORE INSERT ON task_activity_lineage_current BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM task_activity_lineage_events WHERE lineage_event_id=NEW.last_event_id AND task_id=NEW.task_id AND new_lineage_id=NEW.activity_lineage_id) THEN RAISE(ABORT,'TASK_ACTIVITY_CURRENT_INVALID') END; END;
CREATE TRIGGER task_activity_current_update_guard BEFORE UPDATE ON task_activity_lineage_current BEGIN SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.revision<>OLD.revision+1 OR NOT EXISTS (SELECT 1 FROM task_activity_lineage_events WHERE lineage_event_id=NEW.last_event_id AND task_id=NEW.task_id AND new_lineage_id=NEW.activity_lineage_id) THEN RAISE(ABORT,'TASK_ACTIVITY_CURRENT_INVALID') END; END;
CREATE TRIGGER task_count_event_update_guard BEFORE UPDATE ON task_operational_count_events BEGIN SELECT RAISE(ABORT,'TASK_COUNT_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_count_event_delete_guard BEFORE DELETE ON task_operational_count_events BEGIN SELECT RAISE(ABORT,'TASK_COUNT_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER task_count_current_insert_guard BEFORE INSERT ON task_operational_count_current BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM task_operational_count_events WHERE inclusion_event_id=NEW.last_event_id AND task_id=NEW.task_id AND included=NEW.included) THEN RAISE(ABORT,'TASK_COUNT_CURRENT_INVALID') END; END;
CREATE TRIGGER task_count_current_update_guard BEFORE UPDATE ON task_operational_count_current BEGIN SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.revision<>OLD.revision+1 OR NOT EXISTS (SELECT 1 FROM task_operational_count_events WHERE inclusion_event_id=NEW.last_event_id AND task_id=NEW.task_id AND included=NEW.included) THEN RAISE(ABORT,'TASK_COUNT_CURRENT_INVALID') END; END;

CREATE TRIGGER objective_allocator_update_guard BEFORE UPDATE ON objective_tracking_allocator BEGIN SELECT CASE WHEN NEW.singleton_id<>1 OR NEW.next_sequence<>OLD.next_sequence+1 OR NEW.revision<>OLD.revision+1 OR NEW.last_command_id IS NULL THEN RAISE(ABORT,'OBJECTIVE_TRACKING_ALLOCATOR_INVALID') END; END;
CREATE TRIGGER objective_allocator_delete_guard BEFORE DELETE ON objective_tracking_allocator BEGIN SELECT RAISE(ABORT,'OBJECTIVE_TRACKING_ALLOCATOR_PROTECTED'); END;
CREATE TRIGGER objective_update_guard BEFORE UPDATE ON objectives BEGIN
    SELECT CASE WHEN NEW.objective_id<>OLD.objective_id OR NEW.tracking_sequence<>OLD.tracking_sequence OR NEW.tracking_id<>OLD.tracking_id OR NEW.creation_origin<>OLD.creation_origin OR NEW.created_at_utc<>OLD.created_at_utc OR NEW.created_command_id<>OLD.created_command_id OR NEW.revision<>OLD.revision+1 OR OLD.superseded_by_objective_id IS NOT NULL OR NEW.superseded_by_objective_id IS NULL OR NEW.superseded_by_objective_id=OLD.objective_id THEN RAISE(ABORT,'OBJECTIVE_IDENTITY_IMMUTABLE') END;
END;
CREATE TRIGGER objective_delete_guard BEFORE DELETE ON objectives BEGIN
    SELECT CASE WHEN OLD.creation_origin<>'manual' OR OLD.superseded_by_objective_id IS NOT NULL OR NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteObjective' AND target_type='objective' AND target_id=OLD.objective_id) THEN RAISE(ABORT,'OBJECTIVE_HARD_DELETE_REQUIRED') END;
END;
CREATE TRIGGER objective_membership_event_update_guard BEFORE UPDATE ON objective_membership_events BEGIN SELECT RAISE(ABORT,'OBJECTIVE_MEMBERSHIP_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER objective_membership_event_delete_guard BEFORE DELETE ON objective_membership_events BEGIN
    SELECT CASE WHEN OLD.event_kind<>'add' OR OLD.from_objective_id IS NOT NULL OR OLD.to_objective_id IS NULL OR OLD.grouping_proposal_id IS NOT NULL
      OR NOT EXISTS (SELECT 1 FROM objectives o WHERE o.objective_id=OLD.to_objective_id AND o.creation_origin='manual' AND o.superseded_by_objective_id IS NULL AND o.created_command_id=OLD.command_id)
      OR NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteObjective' AND target_type='objective' AND target_id=OLD.to_objective_id)
      OR EXISTS (SELECT 1 FROM objective_membership_events e JOIN objectives o ON o.objective_id=OLD.to_objective_id WHERE e.membership_event_id<>OLD.membership_event_id AND (e.from_objective_id=OLD.to_objective_id OR e.to_objective_id=OLD.to_objective_id) AND NOT (e.event_kind='add' AND e.from_objective_id IS NULL AND e.to_objective_id=OLD.to_objective_id AND e.grouping_proposal_id IS NULL AND e.command_id=o.created_command_id))
      THEN RAISE(ABORT,'OBJECTIVE_MEMBERSHIP_HISTORY_APPEND_ONLY') END;
END;
CREATE TRIGGER objective_membership_current_insert_guard BEFORE INSERT ON objective_task_membership_current BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM task_plan_revisions WHERE plan_revision_id=NEW.accepted_plan_revision_id AND task_id=NEW.task_id) OR NOT EXISTS (SELECT 1 FROM objective_membership_events WHERE membership_event_id=NEW.last_event_id AND task_id=NEW.task_id AND to_objective_id=NEW.objective_id AND accepted_plan_revision_id=NEW.accepted_plan_revision_id) THEN RAISE(ABORT,'OBJECTIVE_MEMBERSHIP_INVALID') END;
END;
CREATE TRIGGER objective_membership_current_update_guard BEFORE UPDATE ON objective_task_membership_current BEGIN
    SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.membership_revision<>OLD.membership_revision+1 OR NOT EXISTS (SELECT 1 FROM task_plan_revisions WHERE plan_revision_id=NEW.accepted_plan_revision_id AND task_id=NEW.task_id) OR NOT EXISTS (SELECT 1 FROM objective_membership_events WHERE membership_event_id=NEW.last_event_id AND task_id=NEW.task_id AND to_objective_id=NEW.objective_id AND accepted_plan_revision_id=NEW.accepted_plan_revision_id) THEN RAISE(ABORT,'OBJECTIVE_MEMBERSHIP_INVALID') END;
END;
CREATE TRIGGER objective_membership_nonempty_delete_guard AFTER DELETE ON objective_task_membership_current WHEN EXISTS (SELECT 1 FROM objectives WHERE objective_id=OLD.objective_id AND superseded_by_objective_id IS NULL) AND NOT EXISTS (SELECT 1 FROM objective_task_membership_current WHERE objective_id=OLD.objective_id) AND NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteObjective' AND target_type='objective' AND target_id=OLD.objective_id) BEGIN SELECT RAISE(ABORT,'OBJECTIVE_EMPTY'); END;
CREATE TRIGGER objective_membership_nonempty_move_guard AFTER UPDATE OF objective_id ON objective_task_membership_current WHEN NEW.objective_id<>OLD.objective_id AND EXISTS (SELECT 1 FROM objectives WHERE objective_id=OLD.objective_id AND superseded_by_objective_id IS NULL) AND NOT EXISTS (SELECT 1 FROM objective_task_membership_current WHERE objective_id=OLD.objective_id) BEGIN SELECT RAISE(ABORT,'OBJECTIVE_EMPTY'); END;
CREATE TRIGGER objective_envelope_insert_overlap_guard BEFORE INSERT ON objective_envelope_projection WHEN EXISTS (SELECT 1 FROM objectives WHERE objective_id=NEW.objective_id AND superseded_by_objective_id IS NULL) BEGIN
    SELECT CASE WHEN EXISTS (SELECT 1 FROM objective_envelope_projection e JOIN objectives o ON o.objective_id=e.objective_id WHERE e.objective_id<>NEW.objective_id AND o.superseded_by_objective_id IS NULL AND NEW.start_utc<e.end_utc AND NEW.end_utc>e.start_utc) THEN RAISE(ABORT,'OBJECTIVE_OVERLAP') END;
END;
CREATE TRIGGER objective_envelope_update_guard BEFORE UPDATE ON objective_envelope_projection BEGIN
    SELECT CASE WHEN NEW.objective_id<>OLD.objective_id OR NEW.revision<>OLD.revision+1 OR (EXISTS (SELECT 1 FROM objectives WHERE objective_id=NEW.objective_id AND superseded_by_objective_id IS NULL) AND EXISTS (SELECT 1 FROM objective_envelope_projection e JOIN objectives o ON o.objective_id=e.objective_id WHERE e.objective_id<>NEW.objective_id AND o.superseded_by_objective_id IS NULL AND NEW.start_utc<e.end_utc AND NEW.end_utc>e.start_utc)) THEN RAISE(ABORT,'OBJECTIVE_OVERLAP') END;
END;
CREATE TRIGGER objective_envelope_delete_guard BEFORE DELETE ON objective_envelope_projection BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteObjective' AND target_type='objective' AND target_id=OLD.objective_id) THEN RAISE(ABORT,'OBJECTIVE_PROJECTION_PROTECTED') END; END;
CREATE TRIGGER objective_aggregate_update_guard BEFORE UPDATE ON objective_aggregate_projection BEGIN SELECT CASE WHEN NEW.objective_id<>OLD.objective_id OR NEW.revision<>OLD.revision+1 THEN RAISE(ABORT,'OBJECTIVE_AGGREGATE_INVALID') END; END;
CREATE TRIGGER objective_aggregate_delete_guard BEFORE DELETE ON objective_aggregate_projection BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteObjective' AND target_type='objective' AND target_id=OLD.objective_id) THEN RAISE(ABORT,'OBJECTIVE_PROJECTION_PROTECTED') END; END;
CREATE TRIGGER objective_review_update_guard BEFORE UPDATE ON objective_review_events BEGIN SELECT RAISE(ABORT,'OBJECTIVE_REVIEW_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER objective_review_delete_guard BEFORE DELETE ON objective_review_events BEGIN SELECT RAISE(ABORT,'OBJECTIVE_REVIEW_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER objective_archive_event_update_guard BEFORE UPDATE ON objective_archive_events BEGIN SELECT RAISE(ABORT,'OBJECTIVE_ARCHIVE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER objective_archive_event_delete_guard BEFORE DELETE ON objective_archive_events BEGIN SELECT RAISE(ABORT,'OBJECTIVE_ARCHIVE_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER objective_archive_projection_insert_guard BEFORE INSERT ON objective_archive_projection WHEN NEW.last_event_id IS NOT NULL BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM objective_archive_events WHERE archive_event_id=NEW.last_event_id AND objective_id=NEW.objective_id AND ((NEW.archived=1 AND action='archive') OR (NEW.archived=0 AND action='restore'))) THEN RAISE(ABORT,'OBJECTIVE_ARCHIVE_PROJECTION_INVALID') END; END;
CREATE TRIGGER objective_archive_projection_update_guard BEFORE UPDATE ON objective_archive_projection BEGIN SELECT CASE WHEN NEW.objective_id<>OLD.objective_id OR NEW.revision<>OLD.revision+1 OR (NEW.last_event_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM objective_archive_events WHERE archive_event_id=NEW.last_event_id AND objective_id=NEW.objective_id AND ((NEW.archived=1 AND action='archive') OR (NEW.archived=0 AND action='restore')))) THEN RAISE(ABORT,'OBJECTIVE_ARCHIVE_PROJECTION_INVALID') END; END;
CREATE TRIGGER objective_archive_projection_delete_guard BEFORE DELETE ON objective_archive_projection BEGIN SELECT CASE WHEN OLD.last_event_id IS NOT NULL OR NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteObjective' AND target_type='objective' AND target_id=OLD.objective_id) THEN RAISE(ABORT,'OBJECTIVE_ARCHIVE_PROJECTION_PROTECTED') END; END;

CREATE TRIGGER regroup_proposal_update_guard BEFORE UPDATE ON regroup_proposals BEGIN
    SELECT CASE WHEN OLD.state<>'pending' OR NEW.regroup_proposal_id<>OLD.regroup_proposal_id OR NEW.proposal_kind<>OLD.proposal_kind OR NEW.origin<>OLD.origin OR NEW.risk_tier<>OLD.risk_tier OR NEW.input_fingerprint<>OLD.input_fingerprint OR NEW.survivor_objective_id IS NOT OLD.survivor_objective_id OR NEW.created_at_utc<>OLD.created_at_utc OR NEW.revision<>OLD.revision+1 OR NEW.state NOT IN ('accepted','rejected','superseded') OR NEW.last_command_id IS NULL THEN RAISE(ABORT,'GROUPING_PROPOSAL_HISTORY_INVALID') END;
END;
CREATE TRIGGER regroup_proposal_delete_guard BEFORE DELETE ON regroup_proposals BEGIN SELECT RAISE(ABORT,'GROUPING_PROPOSAL_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER regroup_task_change_update_guard BEFORE UPDATE ON regroup_proposal_task_changes BEGIN SELECT RAISE(ABORT,'GROUPING_PROPOSAL_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER regroup_task_change_delete_guard BEFORE DELETE ON regroup_proposal_task_changes BEGIN SELECT RAISE(ABORT,'GROUPING_PROPOSAL_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER regroup_objective_change_update_guard BEFORE UPDATE ON regroup_proposal_objective_changes BEGIN SELECT RAISE(ABORT,'GROUPING_PROPOSAL_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER regroup_objective_change_delete_guard BEFORE DELETE ON regroup_proposal_objective_changes BEGIN SELECT RAISE(ABORT,'GROUPING_PROPOSAL_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER regroup_rejection_update_guard BEFORE UPDATE ON regroup_rejection_events BEGIN SELECT RAISE(ABORT,'GROUPING_REJECTION_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER regroup_rejection_delete_guard BEFORE DELETE ON regroup_rejection_events BEGIN SELECT RAISE(ABORT,'GROUPING_REJECTION_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER historical_proposal_update_guard BEFORE UPDATE ON historical_objective_proposals BEGIN
    SELECT CASE WHEN OLD.state<>'pending' OR NEW.historical_proposal_id<>OLD.historical_proposal_id OR NEW.task_id<>OLD.task_id OR NEW.expected_wfm_source_projection_revision<>OLD.expected_wfm_source_projection_revision OR NEW.expected_source_plan_start_utc<>OLD.expected_source_plan_start_utc OR NEW.expected_source_plan_end_utc<>OLD.expected_source_plan_end_utc OR NEW.expected_source_observation_id<>OLD.expected_source_observation_id OR NEW.expected_matching_operational_plan_revision_id IS NOT OLD.expected_matching_operational_plan_revision_id OR NEW.input_fingerprint<>OLD.input_fingerprint OR NEW.created_at_utc<>OLD.created_at_utc OR NEW.revision<>OLD.revision+1 OR NEW.state NOT IN ('accepted','rejected','superseded') OR NEW.last_command_id IS NULL THEN RAISE(ABORT,'HISTORICAL_PROPOSAL_HISTORY_INVALID') END;
END;
CREATE TRIGGER historical_proposal_delete_guard BEFORE DELETE ON historical_objective_proposals BEGIN SELECT RAISE(ABORT,'HISTORICAL_PROPOSAL_HISTORY_APPEND_ONLY'); END;
CREATE TRIGGER source_terminal_review_update_guard BEFORE UPDATE ON wfm_source_terminal_reviews BEGIN
    SELECT CASE WHEN OLD.state<>'pending' OR NEW.source_terminal_review_id<>OLD.source_terminal_review_id OR NEW.task_id<>OLD.task_id OR NEW.source_projection_revision<>OLD.source_projection_revision OR NEW.provider_lifecycle_class<>OLD.provider_lifecycle_class OR NEW.input_fingerprint<>OLD.input_fingerprint OR NEW.created_at_utc<>OLD.created_at_utc OR NEW.revision<>OLD.revision+1 OR NEW.state NOT IN ('retain_local_work','terminate_local_work','superseded') OR NEW.last_command_id IS NULL OR (NEW.state='retain_local_work' AND (NEW.decided_at_utc IS NULL OR NEW.local_consequence_event_id IS NOT NULL)) OR (NEW.state='terminate_local_work' AND (NEW.decided_at_utc IS NULL OR NEW.local_consequence_event_id IS NULL OR NOT EXISTS (SELECT 1 FROM task_execution_events WHERE execution_event_id=NEW.local_consequence_event_id AND task_id=NEW.task_id AND event_kind='source_terminal_consequence'))) OR (NEW.state='superseded' AND NEW.local_consequence_event_id IS NOT NULL) THEN RAISE(ABORT,'SOURCE_TERMINAL_REVIEW_HISTORY_INVALID') END;
END;
CREATE TRIGGER source_terminal_review_delete_guard BEFORE DELETE ON wfm_source_terminal_reviews BEGIN SELECT RAISE(ABORT,'SOURCE_TERMINAL_REVIEW_HISTORY_APPEND_ONLY'); END;

-- Narrow transactional exceptions required by accepted regroup/reconsider semantics.
DROP TRIGGER objective_membership_nonempty_delete_guard;
CREATE TRIGGER objective_membership_nonempty_delete_guard AFTER DELETE ON objective_task_membership_current
WHEN EXISTS (SELECT 1 FROM objectives WHERE objective_id=OLD.objective_id AND superseded_by_objective_id IS NULL)
 AND NOT EXISTS (SELECT 1 FROM objective_task_membership_current WHERE objective_id=OLD.objective_id)
 AND NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteObjective' AND target_type='objective' AND target_id=OLD.objective_id)
 AND NOT EXISTS (
    SELECT 1
    FROM command_receipts cr
    JOIN regroup_proposals p ON p.regroup_proposal_id=cr.target_id AND p.state='pending'
    JOIN regroup_proposal_objective_changes c ON c.regroup_proposal_id=p.regroup_proposal_id
    WHERE cr.command_type='AcceptRegroupProposal'
      AND cr.target_type='grouping_proposal'
      AND c.objective_id=OLD.objective_id
      AND c.action='supersede'
 )
BEGIN SELECT RAISE(ABORT,'OBJECTIVE_EMPTY'); END;

DROP TRIGGER objective_membership_nonempty_move_guard;
CREATE TRIGGER objective_membership_nonempty_move_guard AFTER UPDATE OF objective_id ON objective_task_membership_current
WHEN NEW.objective_id<>OLD.objective_id
 AND EXISTS (SELECT 1 FROM objectives WHERE objective_id=OLD.objective_id AND superseded_by_objective_id IS NULL)
 AND NOT EXISTS (SELECT 1 FROM objective_task_membership_current WHERE objective_id=OLD.objective_id)
 AND NOT EXISTS (
    SELECT 1
    FROM command_receipts cr
    JOIN regroup_proposals p ON p.regroup_proposal_id=cr.target_id AND p.state='pending'
    JOIN regroup_proposal_objective_changes c ON c.regroup_proposal_id=p.regroup_proposal_id
    WHERE cr.command_type='AcceptRegroupProposal'
      AND cr.target_type='grouping_proposal'
      AND c.objective_id=OLD.objective_id
      AND c.action='supersede'
 )
BEGIN SELECT RAISE(ABORT,'OBJECTIVE_EMPTY'); END;

DROP TRIGGER regroup_objective_change_update_guard;
CREATE TRIGGER regroup_objective_change_update_guard BEFORE UPDATE ON regroup_proposal_objective_changes BEGIN
    SELECT CASE WHEN NOT (
        OLD.action='create'
        AND OLD.objective_id IS NULL
        AND NEW.objective_id IS NOT NULL
        AND NEW.proposal_objective_change_id=OLD.proposal_objective_change_id
        AND NEW.regroup_proposal_id=OLD.regroup_proposal_id
        AND NEW.action=OLD.action
        AND NEW.expected_objective_revision IS OLD.expected_objective_revision
        AND NEW.expected_envelope_revision IS OLD.expected_envelope_revision
        AND EXISTS (
            SELECT 1 FROM command_receipts
            WHERE command_type='AcceptRegroupProposal'
              AND target_type='grouping_proposal'
              AND target_id=OLD.regroup_proposal_id
        )
        AND EXISTS (
            SELECT 1 FROM regroup_proposals
            WHERE regroup_proposal_id=OLD.regroup_proposal_id AND state='pending'
        )
    ) THEN RAISE(ABORT,'GROUPING_PROPOSAL_HISTORY_APPEND_ONLY') END;
END;

DROP TRIGGER regroup_rejection_update_guard;
CREATE TRIGGER regroup_rejection_update_guard BEFORE UPDATE ON regroup_rejection_events BEGIN
    SELECT CASE WHEN NOT (
        OLD.reconsidered_at_utc IS NULL
        AND NEW.reconsidered_at_utc IS NOT NULL
        AND NEW.rejection_event_id=OLD.rejection_event_id
        AND NEW.regroup_proposal_id=OLD.regroup_proposal_id
        AND NEW.input_fingerprint=OLD.input_fingerprint
        AND NEW.reason_code=OLD.reason_code
        AND NEW.recorded_at_utc=OLD.recorded_at_utc
        AND NEW.command_id=OLD.command_id
    ) THEN RAISE(ABORT,'GROUPING_REJECTION_HISTORY_APPEND_ONLY') END;
END;

-- Permanent WFM Task No retirement authority for the narrow source-free manual
-- hard-delete correction path.  The retired task_id deliberately has no FK:
-- the owning Task row is removed later in the same HardDeleteTask UnitOfWork.
CREATE TABLE wfm_task_no_retirements (
    retirement_id TEXT PRIMARY KEY,
    task_no TEXT NOT NULL UNIQUE CHECK(length(task_no)=16 AND substr(task_no,1,2)='TK' AND substr(task_no,3) NOT GLOB '*[^0-9]*'),
    retired_task_id TEXT NOT NULL UNIQUE,
    retired_at_utc INTEGER NOT NULL CHECK(retired_at_utc >= 0),
    hard_delete_command_id TEXT NOT NULL UNIQUE REFERENCES command_receipts(command_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) STRICT;

CREATE INDEX idx_wfm_task_no_retirements_hard_delete_command
ON wfm_task_no_retirements(hard_delete_command_id,retirement_id);

CREATE TRIGGER wfm_task_no_retirement_insert_guard BEFORE INSERT ON wfm_task_no_retirements BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM command_receipts cr
        JOIN tasks t ON t.task_id=NEW.retired_task_id
        JOIN wfm_task_identities w ON w.task_id=t.task_id
        WHERE cr.command_id=NEW.hard_delete_command_id
          AND cr.command_type='HardDeleteTask'
          AND cr.target_type='task'
          AND cr.target_id=NEW.retired_task_id
          AND t.task_kind='wfm'
          AND t.creation_origin='wfm_manual'
          AND w.task_no=NEW.task_no
          AND NOT EXISTS (SELECT 1 FROM wfm_source_projection_cache s WHERE s.task_id=t.task_id)
    ) THEN RAISE(ABORT,'WFM_TASK_NO_RETIREMENT_INVALID') END;
END;
CREATE TRIGGER wfm_task_no_retirement_update_guard BEFORE UPDATE ON wfm_task_no_retirements BEGIN
    SELECT RAISE(ABORT,'WFM_TASK_NO_RETIREMENT_APPEND_ONLY');
END;
CREATE TRIGGER wfm_task_no_retirement_delete_guard BEFORE DELETE ON wfm_task_no_retirements BEGIN
    SELECT RAISE(ABORT,'WFM_TASK_NO_RETIREMENT_APPEND_ONLY');
END;

CREATE TRIGGER wfm_identity_retired_insert_guard BEFORE INSERT ON wfm_task_identities BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM wfm_task_no_retirements WHERE task_no=NEW.task_no
    ) THEN RAISE(ABORT,'WFM_TASK_NO_RETIRED') END;
END;

CREATE TRIGGER wfm_assignment_retirement_delete_guard BEFORE DELETE ON wfm_rfc_assignment_events BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wfm_task_identities w
        JOIN wfm_task_no_retirements r
          ON r.retired_task_id=w.task_id AND r.task_no=w.task_no
        JOIN command_receipts cr
          ON cr.command_id=r.hard_delete_command_id
        WHERE w.task_id=OLD.task_id
          AND cr.command_type='HardDeleteTask'
          AND cr.target_type='task'
          AND cr.target_id=OLD.task_id
    ) THEN RAISE(ABORT,'WFM_TASK_NO_RETIREMENT_REQUIRED') END;
END;

CREATE TRIGGER wfm_identity_retirement_delete_guard BEFORE DELETE ON wfm_task_identities BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wfm_task_no_retirements r
        JOIN command_receipts cr
          ON cr.command_id=r.hard_delete_command_id
        WHERE r.retired_task_id=OLD.task_id
          AND r.task_no=OLD.task_no
          AND cr.command_type='HardDeleteTask'
          AND cr.target_type='task'
          AND cr.target_id=OLD.task_id
    ) THEN RAISE(ABORT,'WFM_TASK_NO_RETIREMENT_REQUIRED') END;
END;
