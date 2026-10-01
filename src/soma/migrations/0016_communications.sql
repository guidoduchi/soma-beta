-- LLD-09; pinned design 9a0e8911 plus accepted session clarifications.

-- Runtime allocation: beta_0016_communications. Accepted prefix 1-15 is unchanged.

CREATE TABLE communication_source_scopes(
    source_scope_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    adapter_family TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    scope_identity_kind TEXT NOT NULL CHECK(scope_identity_kind IN ('PROVIDER_ACCOUNT','OPERATOR_CONFIRMED_LOCAL_SCOPE')),
    scope_identity_value TEXT NOT NULL,
    current_location TEXT NOT NULL,
    health_state TEXT NOT NULL CHECK(health_state IN ('READY','MISSING','LOCKED','CORRUPT','UNSUPPORTED','PARTIAL','UNPROBED')),
    processing_enabled INTEGER NOT NULL CHECK(processing_enabled IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision>=1),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc IS NULL OR created_at_utc>=0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc IS NULL OR updated_at_utc>=0),
    display_name_folded TEXT NOT NULL,
    PRIMARY KEY(source_scope_id),
    UNIQUE(adapter_family,scope_identity_kind,scope_identity_value),
    CHECK(length(display_name) BETWEEN 1 AND 120),
    CHECK(length(current_location) BETWEEN 1 AND 1024)
) STRICT;

CREATE INDEX idx_comm_scope_health ON communication_source_scopes(health_state,source_scope_id);

CREATE INDEX idx_comm_scope_display ON communication_source_scopes(display_name_folded,source_scope_id);

CREATE INDEX idx_comm_scope_health_display ON communication_source_scopes(health_state,display_name_folded,source_scope_id);

CREATE INDEX idx_comm_scope_provider_identity ON communication_source_scopes(adapter_family,scope_identity_kind,scope_identity_value);

CREATE TABLE communication_source_folders(
    source_folder_id TEXT NOT NULL,
    source_scope_id TEXT NOT NULL REFERENCES communication_source_scopes(source_scope_id) ON DELETE RESTRICT,
    provider_folder_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('INBOX','SENT','OTHER')),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision>=1),
    PRIMARY KEY(source_folder_id),
    UNIQUE(source_scope_id,provider_folder_key)
) STRICT;

CREATE INDEX idx_comm_folder_scope_enabled ON communication_source_folders(source_scope_id,enabled,source_folder_id);

CREATE INDEX idx_comm_fk_communication_source_folders_source_scope_id ON communication_source_folders(source_scope_id);

CREATE TABLE communication_source_scope_events(
    source_scope_event_id TEXT NOT NULL,
    source_scope_id TEXT NOT NULL REFERENCES communication_source_scopes(source_scope_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('CREATED','LOCATION_CHANGED','FOLDERS_CHANGED','IDENTITY_RECONCILED','HEALTH_CHANGED','ARCHIVED')),
    prior_revision INTEGER,
    new_revision INTEGER NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    command_id TEXT REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    PRIMARY KEY(source_scope_event_id)
) STRICT;

CREATE INDEX idx_comm_scope_events ON communication_source_scope_events(source_scope_id,recorded_at_utc,source_scope_event_id);

CREATE INDEX idx_comm_fk_communication_source_scope_events_source_scope_id ON communication_source_scope_events(source_scope_id);

CREATE INDEX idx_comm_fk_communication_source_scope_events_command_id ON communication_source_scope_events(command_id);

CREATE TRIGGER communication_source_scope_events_update_guard BEFORE UPDATE ON communication_source_scope_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_source_scope_events_delete_guard BEFORE DELETE ON communication_source_scope_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communications(
    communication_id TEXT NOT NULL,
    source_scope_id TEXT NOT NULL REFERENCES communication_source_scopes(source_scope_id) ON DELETE RESTRICT,
    provider_identity_kind TEXT,
    provider_identity_digest TEXT,
    fallback_version INTEGER,
    fallback_digest TEXT,
    identity_state TEXT NOT NULL CHECK(identity_state IN ('PROVIDER_STABLE','FALLBACK','IDENTITY_COLLISION')),
    chronology_known INTEGER NOT NULL CHECK(chronology_known IN (0,1)),
    chronology_utc INTEGER CHECK(chronology_utc IS NULL OR chronology_utc>=0),
    chronology_source_kind TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('RECEIVED','SENT','UNKNOWN')),
    subject TEXT,
    body_kind TEXT NOT NULL CHECK(body_kind IN ('TEXT','HTML','RTF_DERIVED_TEXT','NONE')),
    body_text TEXT,
    content_state TEXT NOT NULL CHECK(content_state IN ('RETAINED','PURGED')),
    content_revision INTEGER NOT NULL CHECK(content_revision>=1),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc IS NULL OR created_at_utc>=0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc IS NULL OR updated_at_utc>=0),
    provider_identity_bytes BLOB,
    fallback_canonical_json TEXT CHECK(fallback_canonical_json IS NULL OR json_valid(fallback_canonical_json)),
    PRIMARY KEY(communication_id),
    CHECK((chronology_known=0 AND chronology_utc IS NULL AND chronology_source_kind='UNKNOWN') OR (chronology_known=1 AND chronology_utc IS NOT NULL AND chronology_source_kind IN ('RECEIVED_TIME','SENT_TIME','OTHER_PROVIDER_TIME'))),
    CHECK(provider_identity_digest IS NULL OR length(provider_identity_digest)=64),
    CHECK(fallback_digest IS NULL OR length(fallback_digest)=64),
    CHECK(content_state!='PURGED' OR (subject IS NULL AND body_text IS NULL AND body_kind='NONE' AND fallback_canonical_json IS NULL)),
    CHECK(subject IS NULL OR length(subject)<=2048),
    CHECK(body_text IS NULL OR length(body_text)<=5000000),
    CHECK(fallback_canonical_json IS NULL OR length(CAST(fallback_canonical_json AS BLOB))<=1048576)
) STRICT;

CREATE UNIQUE INDEX ux_comm_provider_identity ON communications(source_scope_id,provider_identity_kind,provider_identity_digest) WHERE provider_identity_digest IS NOT NULL AND identity_state='PROVIDER_STABLE';

CREATE INDEX idx_comm_fallback ON communications(source_scope_id,fallback_version,fallback_digest);

CREATE INDEX idx_comm_chronology ON communications(source_scope_id,chronology_known,chronology_utc DESC,communication_id);

CREATE INDEX idx_comm_fk_communications_source_scope_id ON communications(source_scope_id);

CREATE INDEX idx_comm_global_chronology ON communications(chronology_known DESC,chronology_utc DESC,communication_id DESC);

CREATE INDEX idx_comm_scope_chronology_order ON communications(source_scope_id,chronology_known DESC,chronology_utc DESC,communication_id DESC);

CREATE INDEX idx_comm_provider_candidate ON communications(source_scope_id,provider_identity_kind,provider_identity_digest);

CREATE TABLE communication_identity_aliases(
    identity_alias_id TEXT NOT NULL,
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    alias_kind TEXT NOT NULL,
    alias_digest TEXT NOT NULL,
    normalization_version INTEGER NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    alias_evidence_bytes BLOB,
    PRIMARY KEY(identity_alias_id),
    UNIQUE(communication_id,alias_kind,alias_digest,normalization_version),
    CHECK(alias_kind NOT IN ('MAPI_RECORD_KEY','PROVIDER_STABLE_OTHER') OR (normalization_version=1 AND alias_evidence_bytes IS NOT NULL AND length(alias_evidence_bytes)>0))
) STRICT;

CREATE INDEX idx_comm_alias_lookup ON communication_identity_aliases(alias_kind,alias_digest,identity_alias_id);

CREATE INDEX idx_comm_fk_communication_identity_aliases_communication_id ON communication_identity_aliases(communication_id);

CREATE TRIGGER communication_identity_aliases_update_guard BEFORE UPDATE ON communication_identity_aliases BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_identity_aliases_delete_guard BEFORE DELETE ON communication_identity_aliases BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_participants(
    communication_participant_id TEXT NOT NULL,
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK(role IN ('FROM','SENDER','TO','CC','BCC','REPLY_TO','OTHER')),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    normalized_address TEXT,
    display_name TEXT,
    contact_id TEXT,
    contact_revision INTEGER,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    PRIMARY KEY(communication_participant_id),
    UNIQUE(communication_id,role,ordinal)
) STRICT;

CREATE INDEX idx_comm_participant_comm ON communication_participants(communication_id,role,ordinal);

CREATE INDEX idx_comm_participant_address ON communication_participants(normalized_address,communication_id);

CREATE INDEX idx_comm_fk_communication_participants_communication_id ON communication_participants(communication_id);

CREATE TABLE communication_attachments(
    communication_attachment_id TEXT NOT NULL,
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    filename TEXT,
    mime_type TEXT,
    size_bytes INTEGER NOT NULL CHECK(size_bytes>=0),
    sha256 TEXT NOT NULL,
    chunk_count INTEGER NOT NULL CHECK(chunk_count>=0),
    PRIMARY KEY(communication_attachment_id),
    UNIQUE(communication_id,ordinal)
) STRICT;

CREATE INDEX idx_comm_attachment_comm ON communication_attachments(communication_id,ordinal);

CREATE INDEX idx_comm_fk_communication_attachments_communication_id ON communication_attachments(communication_id);

CREATE TABLE communication_attachment_chunks(
    communication_attachment_id TEXT NOT NULL REFERENCES communication_attachments(communication_attachment_id) ON DELETE RESTRICT,
    chunk_index INTEGER NOT NULL CHECK(chunk_index>=0),
    content BLOB NOT NULL,
    chunk_sha256 TEXT NOT NULL,
    PRIMARY KEY(communication_attachment_id,chunk_index),
    CHECK(length(content)<=1048576)
) STRICT;

CREATE INDEX idx_comm_fk_communication_attachment_chunks_communication_attachment_id ON communication_attachment_chunks(communication_attachment_id);

CREATE TABLE communication_identity_review_evidence(
    review_evidence_id TEXT NOT NULL,
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    source_scope_id TEXT NOT NULL REFERENCES communication_source_scopes(source_scope_id) ON DELETE RESTRICT,
    source_revision INTEGER NOT NULL CHECK(source_revision>=1),
    protection_hold_id TEXT NOT NULL REFERENCES communication_protection_holds(protection_hold_id) ON DELETE RESTRICT,
    provider_identity_kind TEXT NOT NULL,
    provider_identity_digest TEXT NOT NULL,
    provider_identity_bytes BLOB NOT NULL,
    fallback_digest TEXT NOT NULL,
    fallback_canonical_json TEXT CHECK(fallback_canonical_json IS NULL OR json_valid(fallback_canonical_json)),
    retained_content_revision INTEGER NOT NULL CHECK(retained_content_revision>=1),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc IS NULL OR created_at_utc>=0),
    decision_event_id TEXT REFERENCES communication_identity_review_events(identity_review_event_id) ON DELETE RESTRICT,
    PRIMARY KEY(review_evidence_id),
    CHECK(provider_identity_kind IN ('MAPI_RECORD_KEY','PROVIDER_STABLE_OTHER')),
    CHECK(length(provider_identity_bytes)>0),
    CHECK(length(provider_identity_digest)=64 AND provider_identity_digest NOT GLOB '*[^0-9a-f]*'),
    CHECK(length(fallback_digest)=64 AND fallback_digest NOT GLOB '*[^0-9a-f]*'),
    CHECK(fallback_canonical_json IS NULL OR length(CAST(fallback_canonical_json AS BLOB))<=1048576)
) STRICT;

CREATE INDEX idx_comm_identity_review_exact ON communication_identity_review_evidence(source_scope_id,provider_identity_kind,provider_identity_digest,fallback_digest,review_evidence_id);

CREATE INDEX idx_comm_fk_communication_identity_review_evidence_communication_id ON communication_identity_review_evidence(communication_id);

CREATE INDEX idx_comm_fk_communication_identity_review_evidence_source_scope_id ON communication_identity_review_evidence(source_scope_id);

CREATE INDEX idx_comm_fk_communication_identity_review_evidence_protection_hold_id ON communication_identity_review_evidence(protection_hold_id);

CREATE INDEX idx_comm_fk_communication_identity_review_evidence_decision_event_id ON communication_identity_review_evidence(decision_event_id);

CREATE TABLE communication_identity_review_events(
    identity_review_event_id TEXT NOT NULL,
    source_scope_id TEXT NOT NULL REFERENCES communication_source_scopes(source_scope_id) ON DELETE RESTRICT,
    source_revision INTEGER NOT NULL CHECK(source_revision>=1),
    decision TEXT NOT NULL CHECK(decision IN ('KEEP_SEPARATE','ATTACH_PROVIDER_IDENTITY','CONSOLIDATE_LINKS_AND_ALIASES','KEEP_RETAINED_CONTENT')),
    retained_communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    retained_content_revision INTEGER NOT NULL CHECK(retained_content_revision>=1),
    other_communication_id TEXT REFERENCES communications(communication_id) ON DELETE RESTRICT,
    other_content_revision INTEGER,
    review_evidence_id TEXT REFERENCES communication_identity_review_evidence(review_evidence_id) ON DELETE RESTRICT,
    preview_fingerprint TEXT NOT NULL,
    closed_link_count INTEGER NOT NULL,
    created_link_count INTEGER NOT NULL,
    attached_alias_count INTEGER NOT NULL,
    closed_hold_count INTEGER NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    PRIMARY KEY(identity_review_event_id),
    CHECK(length(preview_fingerprint)=64 AND preview_fingerprint NOT GLOB '*[^0-9a-f]*'),
    CHECK(closed_link_count>=0 AND created_link_count>=0 AND attached_alias_count>=0 AND closed_hold_count>=0),
    CHECK((other_communication_id IS NULL AND other_content_revision IS NULL) OR (other_communication_id IS NOT NULL AND other_content_revision>=1 AND other_communication_id!=retained_communication_id)),
    CHECK((decision='KEEP_RETAINED_CONTENT' AND other_communication_id IS NULL AND review_evidence_id IS NOT NULL) OR (decision!='KEEP_RETAINED_CONTENT' AND other_communication_id IS NOT NULL AND review_evidence_id IS NULL))
) STRICT;

CREATE INDEX idx_comm_identity_review_history ON communication_identity_review_events(retained_communication_id,recorded_at_utc DESC,identity_review_event_id DESC);

CREATE INDEX idx_comm_fk_communication_identity_review_events_source_scope_id ON communication_identity_review_events(source_scope_id);

CREATE INDEX idx_comm_fk_communication_identity_review_events_retained_communication_id ON communication_identity_review_events(retained_communication_id);

CREATE INDEX idx_comm_fk_communication_identity_review_events_other_communication_id ON communication_identity_review_events(other_communication_id);

CREATE INDEX idx_comm_fk_communication_identity_review_events_review_evidence_id ON communication_identity_review_events(review_evidence_id);

CREATE INDEX idx_comm_fk_communication_identity_review_events_command_id ON communication_identity_review_events(command_id);

CREATE TRIGGER communication_identity_review_events_update_guard BEFORE UPDATE ON communication_identity_review_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_identity_review_events_delete_guard BEFORE DELETE ON communication_identity_review_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_identity_review_results(
    identity_review_event_id TEXT NOT NULL REFERENCES communication_identity_review_events(identity_review_event_id) ON DELETE RESTRICT,
    result_type TEXT NOT NULL,
    result_id TEXT NOT NULL,
    PRIMARY KEY(identity_review_event_id,result_type,result_id),
    CHECK(result_type IN ('communication_identity_alias','communication_link_event','communication_retention_event','communication_protection_hold'))
) STRICT;

CREATE INDEX idx_comm_fk_communication_identity_review_results_identity_review_event_id ON communication_identity_review_results(identity_review_event_id);

CREATE TRIGGER communication_identity_review_results_update_guard BEFORE UPDATE ON communication_identity_review_results BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_identity_review_results_delete_guard BEFORE DELETE ON communication_identity_review_results BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_identity_review_requests(
    job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE RESTRICT,
    requested_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    execution_command_id TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK(request_json IS NULL OR json_valid(request_json)),
    preview_fingerprint TEXT NOT NULL,
    PRIMARY KEY(job_id),
    UNIQUE(execution_command_id),
    CHECK(length(CAST(request_json AS BLOB))<=65536),
    CHECK(length(preview_fingerprint)=64 AND preview_fingerprint NOT GLOB '*[^0-9a-f]*')
) STRICT;

CREATE INDEX idx_comm_fk_communication_identity_review_requests_job_id ON communication_identity_review_requests(job_id);

CREATE INDEX idx_comm_fk_communication_identity_review_requests_requested_command_id ON communication_identity_review_requests(requested_command_id);

CREATE TRIGGER communication_identity_review_requests_update_guard BEFORE UPDATE ON communication_identity_review_requests BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_identity_review_requests_delete_guard BEFORE DELETE ON communication_identity_review_requests BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_identity_alias_assignments(
    alias_assignment_id TEXT NOT NULL,
    source_scope_id TEXT NOT NULL REFERENCES communication_source_scopes(source_scope_id) ON DELETE RESTRICT,
    provider_identity_kind TEXT NOT NULL,
    provider_identity_digest TEXT NOT NULL,
    identity_alias_id TEXT NOT NULL REFERENCES communication_identity_aliases(identity_alias_id) ON DELETE RESTRICT,
    identity_review_event_id TEXT NOT NULL REFERENCES communication_identity_review_events(identity_review_event_id) ON DELETE RESTRICT,
    assignment_revision INTEGER NOT NULL CHECK(assignment_revision>=1),
    PRIMARY KEY(alias_assignment_id),
    UNIQUE(source_scope_id,assignment_revision),
    CHECK(provider_identity_kind IN ('MAPI_RECORD_KEY','PROVIDER_STABLE_OTHER')),
    CHECK(length(provider_identity_digest)=64 AND provider_identity_digest NOT GLOB '*[^0-9a-f]*')
) STRICT;

CREATE INDEX idx_comm_alias_assignment_exact ON communication_identity_alias_assignments(source_scope_id,provider_identity_kind,provider_identity_digest,assignment_revision DESC);

CREATE INDEX idx_comm_fk_communication_identity_alias_assignments_source_scope_id ON communication_identity_alias_assignments(source_scope_id);

CREATE INDEX idx_comm_fk_communication_identity_alias_assignments_identity_alias_id ON communication_identity_alias_assignments(identity_alias_id);

CREATE INDEX idx_comm_fk_communication_identity_alias_assignments_identity_review_event_id ON communication_identity_alias_assignments(identity_review_event_id);

CREATE TRIGGER communication_identity_alias_assignments_update_guard BEFORE UPDATE ON communication_identity_alias_assignments BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_identity_alias_assignments_delete_guard BEFORE DELETE ON communication_identity_alias_assignments BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_links(
    communication_link_id TEXT NOT NULL,
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    target_type TEXT NOT NULL CHECK(target_type IN ('SERVICE_REQUEST','SPARE_REQUEST','RMA','RFC','WFM_TASK','OBJECTIVE','FAULT_TAG')),
    target_id TEXT NOT NULL,
    target_revision_at_link INTEGER NOT NULL,
    matched_identity_kind TEXT NOT NULL,
    matched_identity_value TEXT NOT NULL,
    match_rule_id TEXT NOT NULL,
    match_rule_version INTEGER NOT NULL,
    confidence_basis TEXT NOT NULL CHECK(confidence_basis IN ('EXACT_IDENTIFIER','EXACT_ALIAS','REVIEWED_MANUAL')),
    direction TEXT NOT NULL CHECK(direction IN ('RECEIVED','SENT','UNKNOWN')),
    effective_chronology_known INTEGER NOT NULL CHECK(effective_chronology_known IN (0,1)),
    effective_chronology_utc INTEGER CHECK(effective_chronology_utc IS NULL OR effective_chronology_utc>=0),
    origin TEXT NOT NULL CHECK(origin IN ('AUTO_SAFE','REVIEWED','MANUAL')),
    state TEXT NOT NULL CHECK(state IN ('ACTIVE','CLOSED')),
    revision INTEGER NOT NULL CHECK(revision>=1),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc IS NULL OR created_at_utc>=0),
    closed_at_utc INTEGER CHECK(closed_at_utc IS NULL OR closed_at_utc>=0),
    close_reason TEXT,
    effective_chronology_source_kind TEXT NOT NULL CHECK(effective_chronology_source_kind IN ('RECEIVED_TIME','SENT_TIME','OTHER_PROVIDER_TIME','UNKNOWN')),
    canonical_chronology_known INTEGER NOT NULL DEFAULT 0 CHECK(canonical_chronology_known IN (0,1)),
    canonical_chronology_utc INTEGER,
    PRIMARY KEY(communication_link_id),
    CHECK((effective_chronology_known=0 AND effective_chronology_utc IS NULL AND effective_chronology_source_kind='UNKNOWN') OR (effective_chronology_known=1 AND effective_chronology_utc IS NOT NULL AND effective_chronology_source_kind!='UNKNOWN')),
    CHECK((state='ACTIVE' AND closed_at_utc IS NULL) OR (state='CLOSED' AND closed_at_utc IS NOT NULL))
) STRICT;

CREATE UNIQUE INDEX ux_comm_link_active ON communication_links(communication_id,target_type,target_id) WHERE state='ACTIVE';

CREATE INDEX idx_comm_link_target ON communication_links(target_type,target_id,state,effective_chronology_utc DESC,communication_link_id);

CREATE INDEX idx_comm_link_comm ON communication_links(communication_id,state,communication_link_id);

CREATE INDEX idx_comm_link_comm_state_order ON communication_links(communication_id,state,target_type,target_id,communication_link_id);

CREATE INDEX idx_comm_link_comm_order ON communication_links(communication_id,target_type,target_id,communication_link_id);

CREATE INDEX idx_comm_fk_communication_links_communication_id ON communication_links(communication_id);

CREATE INDEX idx_comm_link_target_canonical_order ON communication_links(target_type,target_id,state,canonical_chronology_known DESC,canonical_chronology_utc DESC,communication_id DESC);

CREATE INDEX idx_comm_link_target_event_order ON communication_links(target_type,target_id,state,communication_link_id);

CREATE TABLE communication_link_events(
    communication_link_event_id TEXT NOT NULL,
    communication_link_id TEXT NOT NULL REFERENCES communication_links(communication_link_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('CREATED','CORRECTED','CLOSED','RESTORED')),
    prior_revision INTEGER,
    new_revision INTEGER NOT NULL,
    reason_code TEXT NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    command_id TEXT REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    PRIMARY KEY(communication_link_event_id)
) STRICT;

CREATE INDEX idx_comm_link_events ON communication_link_events(communication_link_id,recorded_at_utc,communication_link_event_id);

CREATE INDEX idx_comm_fk_communication_link_events_communication_link_id ON communication_link_events(communication_link_id);

CREATE INDEX idx_comm_fk_communication_link_events_command_id ON communication_link_events(command_id);

CREATE TRIGGER communication_link_events_update_guard BEFORE UPDATE ON communication_link_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_link_events_delete_guard BEFORE DELETE ON communication_link_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_proposals(
    communication_proposal_id TEXT NOT NULL,
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    target_type TEXT NOT NULL CHECK(target_type IN ('SERVICE_REQUEST','SPARE_REQUEST','RMA','RFC','WFM_TASK','OBJECTIVE','FAULT_TAG')),
    target_id TEXT NOT NULL,
    target_revision INTEGER NOT NULL,
    proposal_contract_id TEXT NOT NULL,
    proposal_contract_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL CHECK(payload_json IS NULL OR json_valid(payload_json)),
    source_fingerprint TEXT NOT NULL,
    proposal_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('PENDING','DEFERRED','ACCEPTED','REJECTED','SUPERSEDED')),
    revision INTEGER NOT NULL CHECK(revision>=1),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc IS NULL OR created_at_utc>=0),
    decided_at_utc INTEGER CHECK(decided_at_utc IS NULL OR decided_at_utc>=0),
    decision_reason_code TEXT,
    PRIMARY KEY(communication_proposal_id),
    UNIQUE(communication_id,target_type,target_id,proposal_contract_id,proposal_fingerprint)
) STRICT;

CREATE INDEX idx_comm_proposal_queue ON communication_proposals(state,target_type,created_at_utc,communication_proposal_id);

CREATE INDEX idx_comm_proposal_target ON communication_proposals(target_type,target_id,state,communication_proposal_id);

CREATE INDEX idx_comm_fk_communication_proposals_communication_id ON communication_proposals(communication_id);

CREATE INDEX idx_comm_proposal_dependency ON communication_proposals(communication_id,state,communication_proposal_id);

CREATE INDEX idx_comm_proposal_created ON communication_proposals(created_at_utc DESC,communication_proposal_id DESC);

CREATE INDEX idx_comm_proposal_state_created ON communication_proposals(state,created_at_utc DESC,communication_proposal_id DESC);

CREATE INDEX idx_comm_proposal_target_created ON communication_proposals(target_type,target_id,created_at_utc DESC,communication_proposal_id DESC);

CREATE INDEX idx_comm_proposal_target_state_created ON communication_proposals(target_type,target_id,state,created_at_utc DESC,communication_proposal_id DESC);

CREATE INDEX idx_comm_proposal_type_created ON communication_proposals(target_type,created_at_utc DESC,communication_proposal_id DESC);

CREATE INDEX idx_comm_proposal_id_created ON communication_proposals(target_id,created_at_utc DESC,communication_proposal_id DESC);

CREATE INDEX idx_comm_proposal_id_state_created ON communication_proposals(target_id,state,created_at_utc DESC,communication_proposal_id DESC);

CREATE TRIGGER comm_proposal_evidence_immutable BEFORE UPDATE OF communication_id,target_type,target_id,target_revision,proposal_contract_id,proposal_contract_version,payload_json,source_fingerprint,proposal_fingerprint,created_at_utc ON communication_proposals WHEN NEW.communication_id IS NOT OLD.communication_id OR NEW.target_type IS NOT OLD.target_type OR NEW.target_id IS NOT OLD.target_id OR NEW.target_revision IS NOT OLD.target_revision OR NEW.proposal_contract_id IS NOT OLD.proposal_contract_id OR NEW.proposal_contract_version IS NOT OLD.proposal_contract_version OR NEW.payload_json IS NOT OLD.payload_json OR NEW.source_fingerprint IS NOT OLD.source_fingerprint OR NEW.proposal_fingerprint IS NOT OLD.proposal_fingerprint OR NEW.created_at_utc IS NOT OLD.created_at_utc BEGIN SELECT RAISE(ABORT,'Communication proposal evidence is immutable'); END;

CREATE TABLE communication_proposal_events(
    communication_proposal_event_id TEXT NOT NULL,
    communication_proposal_id TEXT NOT NULL REFERENCES communication_proposals(communication_proposal_id) ON DELETE RESTRICT,
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    owner_result_refs_json TEXT CHECK(owner_result_refs_json IS NULL OR json_valid(owner_result_refs_json)),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    command_id TEXT REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    PRIMARY KEY(communication_proposal_event_id)
) STRICT;

CREATE INDEX idx_comm_proposal_events ON communication_proposal_events(communication_proposal_id,recorded_at_utc,communication_proposal_event_id);

CREATE INDEX idx_comm_fk_communication_proposal_events_communication_proposal_id ON communication_proposal_events(communication_proposal_id);

CREATE INDEX idx_comm_fk_communication_proposal_events_command_id ON communication_proposal_events(command_id);

CREATE TRIGGER communication_proposal_events_update_guard BEFORE UPDATE ON communication_proposal_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_proposal_events_delete_guard BEFORE DELETE ON communication_proposal_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_forward_coverage(
    source_scope_id TEXT NOT NULL REFERENCES communication_source_scopes(source_scope_id) ON DELETE RESTRICT,
    source_folder_id TEXT NOT NULL REFERENCES communication_source_folders(source_folder_id) ON DELETE RESTRICT,
    adapter_version TEXT NOT NULL,
    checkpoint_kind TEXT,
    checkpoint_token TEXT,
    provider_time_source_epoch_ms INTEGER,
    state TEXT NOT NULL CHECK(state IN ('NONE','PARTIAL','COMPLETE_TO_HIGH_WATER','UNKNOWN')),
    revision INTEGER NOT NULL CHECK(revision>=1),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc IS NULL OR updated_at_utc>=0),
    PRIMARY KEY(source_scope_id,source_folder_id)
) STRICT;

CREATE INDEX idx_comm_forward_state ON communication_forward_coverage(state,source_scope_id,source_folder_id);

CREATE INDEX idx_comm_fk_communication_forward_coverage_source_scope_id ON communication_forward_coverage(source_scope_id);

CREATE INDEX idx_comm_fk_communication_forward_coverage_source_folder_id ON communication_forward_coverage(source_folder_id);

CREATE TABLE communication_historical_coverage_segments(
    coverage_segment_id TEXT NOT NULL,
    source_scope_id TEXT NOT NULL REFERENCES communication_source_scopes(source_scope_id) ON DELETE RESTRICT,
    source_folder_id TEXT NOT NULL REFERENCES communication_source_folders(source_folder_id) ON DELETE RESTRICT,
    lower_bound_json TEXT NOT NULL CHECK(lower_bound_json IS NULL OR json_valid(lower_bound_json)),
    upper_bound_json TEXT NOT NULL CHECK(upper_bound_json IS NULL OR json_valid(upper_bound_json)),
    state TEXT NOT NULL CHECK(state IN ('PARTIAL','BOUNDED_COMPLETE','UNKNOWN')),
    job_id TEXT NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    PRIMARY KEY(coverage_segment_id)
) STRICT;

CREATE INDEX idx_comm_hist_scope ON communication_historical_coverage_segments(source_scope_id,source_folder_id,recorded_at_utc,coverage_segment_id);

CREATE INDEX idx_comm_fk_communication_historical_coverage_segments_source_scope_id ON communication_historical_coverage_segments(source_scope_id);

CREATE INDEX idx_comm_fk_communication_historical_coverage_segments_source_folder_id ON communication_historical_coverage_segments(source_folder_id);

CREATE INDEX idx_comm_hist_state ON communication_historical_coverage_segments(source_scope_id,source_folder_id,state);

CREATE INDEX idx_comm_hist_time_range ON communication_historical_coverage_segments(source_scope_id,source_folder_id,json_extract(lower_bound_json,'$.utc_epoch_seconds'),coverage_segment_id);

CREATE TABLE communication_job_scopes(
    job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE RESTRICT,
    job_kind TEXT NOT NULL CHECK(job_kind IN ('ORDINARY','TARGETED_BACKFILL','DEEP_SCAN','IDENTITY_RECONCILIATION','ORPHAN_HOUSEKEEPING')),
    source_scope_id TEXT,
    scope_json TEXT NOT NULL CHECK(scope_json IS NULL OR json_valid(scope_json)),
    config_revision INTEGER,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc IS NULL OR created_at_utc>=0),
    preview_fingerprint TEXT,
    execution_config_json TEXT CHECK(execution_config_json IS NULL OR json_valid(execution_config_json)),
    PRIMARY KEY(job_id),
    CHECK((job_kind='ORPHAN_HOUSEKEEPING' AND source_scope_id IS NULL AND config_revision IS NULL) OR (job_kind!='ORPHAN_HOUSEKEEPING' AND source_scope_id IS NOT NULL AND config_revision IS NOT NULL AND config_revision>=1)),
    CHECK(preview_fingerprint IS NULL OR (length(preview_fingerprint)=64 AND preview_fingerprint NOT GLOB '*[^0-9a-f]*')),
    CHECK(job_kind!='DEEP_SCAN' OR preview_fingerprint IS NOT NULL),
    CHECK((job_kind='ORPHAN_HOUSEKEEPING' AND execution_config_json IS NULL) OR (job_kind!='ORPHAN_HOUSEKEEPING' AND execution_config_json IS NOT NULL))
) STRICT;

CREATE INDEX idx_comm_job_scope ON communication_job_scopes(source_scope_id,job_kind,created_at_utc,job_id);

CREATE INDEX idx_comm_fk_communication_job_scopes_job_id ON communication_job_scopes(job_id);

CREATE TRIGGER comm_job_scope_immutable BEFORE UPDATE ON communication_job_scopes BEGIN SELECT RAISE(ABORT,'Communication job scope is immutable'); END;

CREATE TABLE communication_job_counters(
    job_id TEXT NOT NULL REFERENCES communication_job_scopes(job_id) ON DELETE RESTRICT,
    discovered INTEGER NOT NULL,
    inspected INTEGER NOT NULL,
    matched INTEGER NOT NULL,
    retained INTEGER NOT NULL,
    unchanged INTEGER NOT NULL,
    proposed INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    warnings INTEGER NOT NULL,
    failures INTEGER NOT NULL,
    estimated_total INTEGER,
    revision INTEGER NOT NULL,
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc IS NULL OR updated_at_utc>=0),
    PRIMARY KEY(job_id),
    CHECK(discovered>=0),
    CHECK(inspected>=0),
    CHECK(matched>=0),
    CHECK(retained>=0),
    CHECK(unchanged>=0),
    CHECK(proposed>=0),
    CHECK(skipped>=0),
    CHECK(warnings>=0),
    CHECK(failures>=0),
    CHECK(estimated_total IS NULL OR estimated_total>=0),
    CHECK(revision>=1)
) STRICT;

CREATE INDEX idx_comm_fk_communication_job_counters_job_id ON communication_job_counters(job_id);

CREATE TABLE communication_job_cancellation_events(
    cancellation_event_id TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES communication_job_scopes(job_id) ON DELETE RESTRICT,
    job_kind TEXT NOT NULL CHECK(job_kind IN ('ORDINARY','TARGETED_BACKFILL','DEEP_SCAN','IDENTITY_RECONCILIATION','ORPHAN_HOUSEKEEPING')),
    prior_state TEXT NOT NULL CHECK(prior_state IN ('queued','running','waiting_review','retry_wait')),
    resulting_state TEXT NOT NULL CHECK(resulting_state IN ('cancelled')),
    claim_revoked INTEGER NOT NULL CHECK(claim_revoked IN (0,1)),
    cancelled_attempt_ordinal INTEGER,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    PRIMARY KEY(cancellation_event_id),
    CHECK((prior_state='running' AND claim_revoked=1 AND cancelled_attempt_ordinal IS NOT NULL AND cancelled_attempt_ordinal>=1) OR (prior_state!='running' AND claim_revoked=0 AND cancelled_attempt_ordinal IS NULL))
) STRICT;

CREATE INDEX idx_comm_job_cancel_history ON communication_job_cancellation_events(job_id,recorded_at_utc DESC,cancellation_event_id DESC);

CREATE INDEX idx_comm_fk_communication_job_cancellation_events_job_id ON communication_job_cancellation_events(job_id);

CREATE INDEX idx_comm_fk_communication_job_cancellation_events_command_id ON communication_job_cancellation_events(command_id);

CREATE TRIGGER communication_job_cancellation_events_update_guard BEFORE UPDATE ON communication_job_cancellation_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_job_cancellation_events_delete_guard BEFORE DELETE ON communication_job_cancellation_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_retention(
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK(state IN ('RETAINED','ORPHAN_PENDING_PURGE','PURGED')),
    orphan_since_utc INTEGER CHECK(orphan_since_utc IS NULL OR orphan_since_utc>=0),
    purge_due_utc INTEGER CHECK(purge_due_utc IS NULL OR purge_due_utc>=0),
    last_dependency_event_id TEXT,
    revision INTEGER NOT NULL CHECK(revision>=1),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc IS NULL OR updated_at_utc>=0),
    PRIMARY KEY(communication_id),
    CHECK((state='RETAINED' AND purge_due_utc IS NULL) OR (state='ORPHAN_PENDING_PURGE' AND orphan_since_utc IS NOT NULL AND purge_due_utc IS NOT NULL AND purge_due_utc>orphan_since_utc) OR state='PURGED')
) STRICT;

CREATE INDEX idx_comm_retention_due ON communication_retention(state,purge_due_utc,communication_id);

CREATE INDEX idx_comm_fk_communication_retention_communication_id ON communication_retention(communication_id);

CREATE TABLE communication_protection_holds(
    protection_hold_id TEXT NOT NULL,
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    hold_kind TEXT NOT NULL CHECK(hold_kind IN ('PROPOSAL','CORRECTION','COLLISION_REVIEW','PROTECTED_EXPORT','OTHER_GOVERNED')),
    owner_ref TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('ACTIVE','CLOSED')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc IS NULL OR created_at_utc>=0),
    closed_at_utc INTEGER CHECK(closed_at_utc IS NULL OR closed_at_utc>=0),
    PRIMARY KEY(protection_hold_id),
    UNIQUE(communication_id,hold_kind,owner_ref)
) STRICT;

CREATE INDEX idx_comm_hold_active ON communication_protection_holds(communication_id,state,protection_hold_id);

CREATE INDEX idx_comm_fk_communication_protection_holds_communication_id ON communication_protection_holds(communication_id);

CREATE TABLE communication_retention_events(
    retention_event_id TEXT NOT NULL,
    communication_id TEXT NOT NULL REFERENCES communications(communication_id) ON DELETE RESTRICT,
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    dependency_fingerprint TEXT NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc IS NULL OR recorded_at_utc>=0),
    command_id TEXT REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    resulting_retention_revision INTEGER NOT NULL CHECK(resulting_retention_revision>=1),
    PRIMARY KEY(retention_event_id),
    UNIQUE(communication_id,resulting_retention_revision)
) STRICT;

CREATE INDEX idx_comm_retention_events ON communication_retention_events(communication_id,recorded_at_utc,retention_event_id);

CREATE INDEX idx_comm_fk_communication_retention_events_communication_id ON communication_retention_events(communication_id);

CREATE INDEX idx_comm_fk_communication_retention_events_command_id ON communication_retention_events(command_id);

CREATE TRIGGER communication_retention_events_update_guard BEFORE UPDATE ON communication_retention_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_retention_events_delete_guard BEFORE DELETE ON communication_retention_events BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_terminal_summaries(
    terminal_summary_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('SERVICE_REQUEST','RFC')),
    target_id TEXT NOT NULL,
    governing_event_id TEXT NOT NULL,
    received_count INTEGER NOT NULL,
    sent_count INTEGER NOT NULL,
    unknown_count INTEGER NOT NULL,
    last_interaction_known INTEGER NOT NULL CHECK(last_interaction_known IN (0,1)),
    last_interaction_utc INTEGER CHECK(last_interaction_utc IS NULL OR last_interaction_utc>=0),
    last_direction TEXT NOT NULL CHECK(last_direction IN ('RECEIVED','SENT','MIXED','UNKNOWN')),
    coverage_state TEXT NOT NULL CHECK(coverage_state IN ('COMPLETE','PARTIAL','UNKNOWN')),
    unlink_utc INTEGER NOT NULL CHECK(unlink_utc IS NULL OR unlink_utc>=0),
    summary_fingerprint TEXT NOT NULL,
    last_interaction_source_kind TEXT NOT NULL CHECK(last_interaction_source_kind IN ('RECEIVED_TIME','SENT_TIME','OTHER_PROVIDER_TIME','UNKNOWN')),
    summary_revision INTEGER NOT NULL CHECK(summary_revision>=1),
    PRIMARY KEY(terminal_summary_id),
    UNIQUE(target_type,target_id,governing_event_id),
    UNIQUE(target_type,target_id,summary_revision),
    CHECK(received_count>=0 AND sent_count>=0 AND unknown_count>=0),
    CHECK((last_interaction_known=0 AND last_interaction_utc IS NULL AND last_interaction_source_kind='UNKNOWN') OR (last_interaction_known=1 AND last_interaction_utc IS NOT NULL AND last_interaction_source_kind!='UNKNOWN'))
) STRICT;

CREATE INDEX idx_comm_terminal_target ON communication_terminal_summaries(target_type,target_id,unlink_utc DESC,terminal_summary_id);

CREATE INDEX idx_comm_terminal_revision ON communication_terminal_summaries(target_type,target_id,summary_revision DESC);

CREATE TRIGGER communication_terminal_summaries_update_guard BEFORE UPDATE ON communication_terminal_summaries BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TRIGGER communication_terminal_summaries_delete_guard BEFORE DELETE ON communication_terminal_summaries BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;

CREATE TABLE communication_msg_drafts(
    msg_draft_id TEXT NOT NULL,
    origin_domain TEXT NOT NULL,
    origin_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    origin_target_type TEXT,
    origin_target_id TEXT,
    template_id TEXT NOT NULL,
    template_version INTEGER NOT NULL,
    subject_snapshot TEXT NOT NULL,
    body_format TEXT NOT NULL CHECK(body_format IN ('TEXT','HTML')),
    body_snapshot TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('GENERATED','EXPORTED','RECONCILED_SENT')),
    revision INTEGER NOT NULL CHECK(revision>=1),
    generated_at_utc INTEGER NOT NULL CHECK(generated_at_utc IS NULL OR generated_at_utc>=0),
    reconciled_communication_id TEXT,
    PRIMARY KEY(msg_draft_id),
    UNIQUE(origin_command_id,content_fingerprint),
    CHECK((origin_domain='LLD-05' AND origin_target_type='OBJECTIVE' AND origin_target_id IS NOT NULL) OR (origin_domain='LLD-07' AND origin_target_type='SPARE_REQUEST' AND origin_target_id IS NOT NULL)),
    CHECK(template_version>=1 AND length(template_id)<=128 AND length(subject_snapshot)<=2048 AND length(body_snapshot)<=5000000),
    CHECK(length(content_fingerprint)=64 AND content_fingerprint NOT GLOB '*[^0-9a-f]*')
) STRICT;

CREATE INDEX idx_msg_draft_origin ON communication_msg_drafts(origin_domain,origin_target_type,origin_target_id,generated_at_utc,msg_draft_id);

CREATE INDEX idx_comm_fk_communication_msg_drafts_origin_command_id ON communication_msg_drafts(origin_command_id);

CREATE INDEX idx_msg_draft_target_dependency ON communication_msg_drafts(origin_target_type,origin_target_id);

CREATE TRIGGER comm_msg_snapshot_immutable BEFORE UPDATE ON communication_msg_drafts WHEN NEW.msg_draft_id IS NOT OLD.msg_draft_id OR NEW.origin_domain IS NOT OLD.origin_domain OR NEW.origin_command_id IS NOT OLD.origin_command_id OR NEW.origin_target_type IS NOT OLD.origin_target_type OR NEW.origin_target_id IS NOT OLD.origin_target_id OR NEW.template_id IS NOT OLD.template_id OR NEW.template_version IS NOT OLD.template_version OR NEW.subject_snapshot IS NOT OLD.subject_snapshot OR NEW.body_format IS NOT OLD.body_format OR NEW.body_snapshot IS NOT OLD.body_snapshot OR NEW.content_fingerprint IS NOT OLD.content_fingerprint OR NEW.generated_at_utc IS NOT OLD.generated_at_utc BEGIN SELECT RAISE(ABORT,'MSG draft snapshot is immutable'); END;

CREATE TABLE communication_msg_draft_recipients(
    msg_draft_recipient_id TEXT NOT NULL,
    msg_draft_id TEXT NOT NULL REFERENCES communication_msg_drafts(msg_draft_id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK(role IN ('TO','CC','BCC')),
    ordinal INTEGER NOT NULL,
    address TEXT NOT NULL,
    display_name TEXT,
    PRIMARY KEY(msg_draft_recipient_id),
    UNIQUE(msg_draft_id,role,ordinal),
    CHECK(ordinal BETWEEN 0 AND 1999),
    CHECK(length(address) BETWEEN 1 AND 320),
    CHECK(display_name IS NULL OR length(display_name)<=512)
) STRICT;

CREATE INDEX idx_msg_recipient_draft ON communication_msg_draft_recipients(msg_draft_id,role,ordinal);

CREATE INDEX idx_comm_fk_communication_msg_draft_recipients_msg_draft_id ON communication_msg_draft_recipients(msg_draft_id);

CREATE TRIGGER communication_msg_draft_recipients_update_guard BEFORE UPDATE ON communication_msg_draft_recipients BEGIN SELECT RAISE(ABORT,'MSG draft provenance is immutable'); END;

CREATE TRIGGER communication_msg_draft_recipients_delete_guard BEFORE DELETE ON communication_msg_draft_recipients BEGIN SELECT RAISE(ABORT,'MSG draft provenance is immutable'); END;

CREATE UNIQUE INDEX idx_msg_recipient_snapshot_order ON communication_msg_draft_recipients(msg_draft_id,ordinal);

CREATE TABLE communication_msg_draft_exports(
    msg_draft_export_id TEXT NOT NULL,
    msg_draft_id TEXT NOT NULL REFERENCES communication_msg_drafts(msg_draft_id) ON DELETE RESTRICT,
    artifact_sha256 TEXT NOT NULL,
    artifact_size_bytes INTEGER NOT NULL,
    exported_at_utc INTEGER NOT NULL CHECK(exported_at_utc IS NULL OR exported_at_utc>=0),
    location_fingerprint TEXT,
    PRIMARY KEY(msg_draft_export_id),
    CHECK(length(artifact_sha256)=64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'),
    CHECK(artifact_size_bytes>=0),
    CHECK(location_fingerprint IS NULL OR (length(location_fingerprint)=64 AND location_fingerprint NOT GLOB '*[^0-9a-f]*'))
) STRICT;

CREATE INDEX idx_msg_export_draft ON communication_msg_draft_exports(msg_draft_id,exported_at_utc,msg_draft_export_id);

CREATE INDEX idx_comm_fk_communication_msg_draft_exports_msg_draft_id ON communication_msg_draft_exports(msg_draft_id);

CREATE TRIGGER communication_msg_draft_exports_update_guard BEFORE UPDATE ON communication_msg_draft_exports BEGIN SELECT RAISE(ABORT,'MSG draft provenance is immutable'); END;

CREATE TRIGGER communication_msg_draft_exports_delete_guard BEFORE DELETE ON communication_msg_draft_exports BEGIN SELECT RAISE(ABORT,'MSG draft provenance is immutable'); END;

CREATE INDEX idx_msg_export_reuse ON communication_msg_draft_exports(msg_draft_id,artifact_sha256,artifact_size_bytes,location_fingerprint);

CREATE TRIGGER comm_alias_assignment_insert_guard BEFORE INSERT ON communication_identity_alias_assignments WHEN NOT EXISTS(SELECT 1 FROM communication_identity_aliases a JOIN communications c USING(communication_id) JOIN communication_identity_review_events e ON e.identity_review_event_id=NEW.identity_review_event_id WHERE a.identity_alias_id=NEW.identity_alias_id AND a.alias_kind=NEW.provider_identity_kind AND a.alias_digest=NEW.provider_identity_digest AND a.normalization_version=1 AND c.source_scope_id=NEW.source_scope_id AND e.source_scope_id=NEW.source_scope_id AND e.retained_communication_id=a.communication_id AND e.decision IN ('ATTACH_PROVIDER_IDENTITY','CONSOLIDATE_LINKS_AND_ALIASES')) BEGIN SELECT RAISE(ABORT,'Provider assignment requires exact alias and governing review'); END;

CREATE TRIGGER comm_review_evidence_insert_guard BEFORE INSERT ON communication_identity_review_evidence WHEN NEW.decision_event_id IS NOT NULL OR NEW.fallback_canonical_json IS NULL OR NOT EXISTS(SELECT 1 FROM communications c JOIN communication_source_scopes s USING(source_scope_id) WHERE c.communication_id=NEW.communication_id AND c.source_scope_id=NEW.source_scope_id AND s.revision=NEW.source_revision AND c.content_state='RETAINED' AND c.content_revision=NEW.retained_content_revision) OR NOT EXISTS(SELECT 1 FROM communication_protection_holds h WHERE h.protection_hold_id=NEW.protection_hold_id AND h.communication_id=NEW.communication_id AND h.hold_kind='COLLISION_REVIEW' AND h.state='ACTIVE' AND h.owner_ref=NEW.review_evidence_id) BEGIN SELECT RAISE(ABORT,'Identity review evidence requires its retained snapshot and governed hold'); END;

CREATE TRIGGER comm_review_evidence_identity_guard BEFORE UPDATE OF review_evidence_id,communication_id,source_scope_id,source_revision,protection_hold_id,provider_identity_kind,provider_identity_digest,provider_identity_bytes,fallback_digest,retained_content_revision,created_at_utc ON communication_identity_review_evidence BEGIN SELECT RAISE(ABORT,'Identity review origin evidence is immutable'); END;

CREATE TRIGGER comm_review_evidence_content_guard BEFORE UPDATE OF fallback_canonical_json ON communication_identity_review_evidence WHEN NEW.fallback_canonical_json IS NOT OLD.fallback_canonical_json AND NOT (NEW.fallback_canonical_json IS NULL AND EXISTS(SELECT 1 FROM communications WHERE communication_id=OLD.communication_id AND content_state='PURGED')) BEGIN SELECT RAISE(ABORT,'Identity review content may only be cleared by canonical purge'); END;

CREATE TRIGGER comm_review_evidence_decision_guard BEFORE UPDATE OF decision_event_id ON communication_identity_review_evidence WHEN NEW.decision_event_id IS NOT OLD.decision_event_id AND (OLD.decision_event_id IS NOT NULL OR NOT EXISTS(SELECT 1 FROM communication_identity_review_events e WHERE e.identity_review_event_id=NEW.decision_event_id AND e.decision='KEEP_RETAINED_CONTENT' AND e.review_evidence_id=OLD.review_evidence_id AND e.retained_communication_id=OLD.communication_id AND e.retained_content_revision=OLD.retained_content_revision)) BEGIN SELECT RAISE(ABORT,'Identity review acknowledgement requires its exact immutable decision'); END;

CREATE TRIGGER comm_review_evidence_delete_guard BEFORE DELETE ON communication_identity_review_evidence BEGIN SELECT RAISE(ABORT,'Minimized identity review evidence survives purge'); END;

CREATE TRIGGER comm_review_evidence_purge AFTER UPDATE OF content_state ON communications WHEN NEW.content_state='PURGED' BEGIN UPDATE communication_identity_review_evidence SET fallback_canonical_json=NULL WHERE communication_id=NEW.communication_id; END;

CREATE INDEX idx_jobs_created ON durable_jobs(created_at_utc DESC,job_id DESC);
CREATE INDEX idx_jobs_state_created ON durable_jobs(state,created_at_utc DESC,job_id DESC);
CREATE VIEW durable_job_metadata_v1 AS
SELECT j.job_id,j.job_type,j.contract_version,j.state,j.created_at_utc,j.updated_at_utc,
       j.attempt_count,j.next_attempt_at_utc,
       CASE WHEN j.state='cancelled' THEN 1 ELSE 0 END AS cancellation_requested,
       CASE WHEN length(j.last_error_code) BETWEEN 1 AND 64
                 AND j.last_error_code GLOB '[A-Z]*'
                 AND j.last_error_code NOT GLOB '*[^A-Z0-9_]*'
            THEN j.last_error_code ELSE NULL END AS diagnostic_code,
       COALESCE((SELECT a.started_at_utc FROM job_attempts a
                 WHERE a.job_id=j.job_id AND a.ordinal=1),
                CASE WHEN j.attempt_count=1 AND j.state='running' THEN j.claim_started_at_utc ELSE NULL END)
           AS started_at_utc,
       CASE WHEN j.state IN ('completed','failed','cancelled')
            THEN (SELECT a.finished_at_utc FROM job_attempts a
                  WHERE a.job_id=j.job_id AND a.ordinal=j.attempt_count
                    AND a.finished_at_utc=j.updated_at_utc
                    AND ((j.state='completed' AND a.outcome='completed')
                         OR (j.state='failed' AND a.outcome IN ('failed','interrupted'))
                         OR (j.state='cancelled' AND a.outcome='cancelled')))
            ELSE NULL END AS ended_at_utc
FROM durable_jobs j;

CREATE VIEW rfc_terminal_cascade_rfc_members_v1 AS
SELECT p.rfc_terminal_cascade_proposal_id AS proposal_id,p.revision AS proposal_revision,
       m.rfc_id,m.captured_rfc_revision,m.captured_role
FROM rfc_terminal_cascade_proposals p
JOIN rfc_terminal_cascade_rfc_members m
  ON m.rfc_terminal_cascade_proposal_id=p.rfc_terminal_cascade_proposal_id;

CREATE INDEX idx_comm_job_created ON communication_job_scopes(created_at_utc DESC,job_id DESC);

CREATE INDEX idx_comm_job_kind_created ON communication_job_scopes(job_kind,created_at_utc DESC,job_id DESC);

CREATE INDEX idx_comm_job_source_created ON communication_job_scopes(source_scope_id,created_at_utc DESC,job_id DESC);

CREATE TABLE communication_match_runs(job_id TEXT PRIMARY KEY REFERENCES communication_job_scopes(job_id) ON DELETE RESTRICT,state TEXT NOT NULL CHECK(state IN ('PREPARING','READY')),registry_fingerprint TEXT CHECK(registry_fingerprint IS NULL OR (length(registry_fingerprint)=64 AND registry_fingerprint NOT GLOB '*[^0-9a-f]*')),identity_count INTEGER NOT NULL DEFAULT 0 CHECK(identity_count>=0),CHECK((state='PREPARING' AND registry_fingerprint IS NULL) OR (state='READY' AND registry_fingerprint IS NOT NULL AND identity_count>0))) STRICT;

CREATE TABLE communication_match_tokens(job_id TEXT NOT NULL REFERENCES communication_match_runs(job_id) ON DELETE RESTRICT,token TEXT NOT NULL CHECK(length(token) BETWEEN 1 AND 512),target_type TEXT NOT NULL CHECK(target_type IN ('SERVICE_REQUEST','SPARE_REQUEST','RMA','RFC','WFM_TASK','OBJECTIVE','FAULT_TAG')),target_id TEXT NOT NULL,target_revision INTEGER NOT NULL CHECK(target_revision>=1),identity_kind TEXT NOT NULL CHECK(length(identity_kind) BETWEEN 1 AND 128),effective_known INTEGER NOT NULL CHECK(effective_known IN (0,1)),effective_utc INTEGER CHECK(effective_utc IS NULL OR effective_utc>=0),effective_source TEXT NOT NULL CHECK(effective_source IN ('RECEIVED_TIME','SENT_TIME','OTHER_PROVIDER_TIME','UNKNOWN')),export_ordinal INTEGER NOT NULL CHECK(export_ordinal>=0),PRIMARY KEY(job_id,token,target_type,target_id,identity_kind),UNIQUE(job_id,export_ordinal),CHECK((effective_known=0 AND effective_utc IS NULL AND effective_source='UNKNOWN') OR (effective_known=1 AND effective_utc IS NOT NULL AND effective_source!='UNKNOWN'))) STRICT;

CREATE INDEX idx_comm_match_token_order ON communication_match_tokens(job_id,token,export_ordinal);

CREATE INDEX idx_comm_match_job_target ON communication_match_tokens(job_id,target_id,target_type,target_revision);

CREATE INDEX idx_comm_match_target_order ON communication_match_tokens(target_type,target_id,job_id,export_ordinal);

CREATE TABLE communication_match_lengths(job_id TEXT NOT NULL REFERENCES communication_match_runs(job_id) ON DELETE RESTRICT,prefix TEXT NOT NULL,token_length INTEGER NOT NULL CHECK(token_length BETWEEN 1 AND 512),PRIMARY KEY(job_id,prefix,token_length),CHECK(length(prefix)=min(8,token_length))) STRICT;

CREATE TRIGGER comm_match_run_sealed BEFORE UPDATE ON communication_match_runs WHEN OLD.state='READY' BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;

CREATE TRIGGER comm_match_tokens_insert BEFORE INSERT ON communication_match_tokens WHEN (SELECT state FROM communication_match_runs WHERE job_id=NEW.job_id)='READY' BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;

CREATE TRIGGER comm_match_tokens_update BEFORE UPDATE ON communication_match_tokens WHEN (SELECT state FROM communication_match_runs WHERE job_id=OLD.job_id)='READY' OR (SELECT state FROM communication_match_runs WHERE job_id=NEW.job_id)='READY' BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;

CREATE TRIGGER comm_match_tokens_delete BEFORE DELETE ON communication_match_tokens WHEN (SELECT state FROM communication_match_runs WHERE job_id=OLD.job_id)='READY' BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;

CREATE TRIGGER comm_match_lengths_insert BEFORE INSERT ON communication_match_lengths WHEN (SELECT state FROM communication_match_runs WHERE job_id=NEW.job_id)='READY' BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;

CREATE TRIGGER comm_match_lengths_update BEFORE UPDATE ON communication_match_lengths WHEN (SELECT state FROM communication_match_runs WHERE job_id=OLD.job_id)='READY' OR (SELECT state FROM communication_match_runs WHERE job_id=NEW.job_id)='READY' BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;

CREATE TRIGGER comm_match_lengths_delete BEFORE DELETE ON communication_match_lengths WHEN (SELECT state FROM communication_match_runs WHERE job_id=OLD.job_id)='READY' BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;

CREATE TRIGGER comm_link_message_immutable BEFORE UPDATE OF communication_id ON communication_links WHEN NEW.communication_id IS NOT OLD.communication_id BEGIN SELECT RAISE(ABORT,'Communication link message identity is immutable'); END;

CREATE TRIGGER comm_link_chronology_insert AFTER INSERT ON communication_links BEGIN UPDATE communication_links SET canonical_chronology_known=(SELECT chronology_known FROM communications WHERE communication_id=NEW.communication_id),canonical_chronology_utc=(SELECT chronology_utc FROM communications WHERE communication_id=NEW.communication_id) WHERE communication_link_id=NEW.communication_link_id; END;

CREATE TRIGGER comm_link_chronology_message_update AFTER UPDATE OF chronology_known,chronology_utc ON communications BEGIN UPDATE communication_links SET canonical_chronology_known=NEW.chronology_known,canonical_chronology_utc=NEW.chronology_utc WHERE communication_id=NEW.communication_id; END;

CREATE TRIGGER comm_link_chronology_projection_guard BEFORE UPDATE OF canonical_chronology_known,canonical_chronology_utc ON communication_links WHEN NEW.canonical_chronology_known IS NOT (SELECT chronology_known FROM communications WHERE communication_id=NEW.communication_id) OR NEW.canonical_chronology_utc IS NOT (SELECT chronology_utc FROM communications WHERE communication_id=NEW.communication_id) BEGIN SELECT RAISE(ABORT,'Communication ordering projection must agree with canonical chronology'); END;

CREATE VIRTUAL TABLE communication_search_fts USING fts5(subject,body,content='',contentless_delete=1);

CREATE TRIGGER comm_search_insert AFTER INSERT ON communications WHEN NEW.content_state='RETAINED' BEGIN INSERT INTO communication_search_fts(rowid,subject,body) VALUES(NEW.rowid,NEW.subject,NEW.body_text); END;

CREATE TRIGGER comm_search_update AFTER UPDATE OF subject,body_text,content_state ON communications BEGIN DELETE FROM communication_search_fts WHERE rowid=OLD.rowid; INSERT INTO communication_search_fts(rowid,subject,body) SELECT NEW.rowid,NEW.subject,NEW.body_text WHERE NEW.content_state='RETAINED'; END;

CREATE TRIGGER comm_search_delete AFTER DELETE ON communications BEGIN DELETE FROM communication_search_fts WHERE rowid=OLD.rowid; END;

CREATE TRIGGER comm_retention_purged_insert_guard BEFORE INSERT ON communication_retention WHEN NEW.state='PURGED' AND NOT EXISTS(SELECT 1 FROM communications WHERE communication_id=NEW.communication_id AND content_state='PURGED') BEGIN SELECT RAISE(ABORT,'Communication content must be purged first'); END;

CREATE TRIGGER comm_retention_purged_update_guard BEFORE UPDATE ON communication_retention WHEN NEW.state='PURGED' AND NOT EXISTS(SELECT 1 FROM communications WHERE communication_id=NEW.communication_id AND content_state='PURGED') BEGIN SELECT RAISE(ABORT,'Communication content must be purged first'); END;

CREATE TRIGGER comm_content_purge_dependencies BEFORE UPDATE OF content_state ON communications WHEN NEW.content_state='PURGED' AND (EXISTS(SELECT 1 FROM communication_links WHERE communication_id=NEW.communication_id AND state='ACTIVE') OR EXISTS(SELECT 1 FROM communication_protection_holds WHERE communication_id=NEW.communication_id AND state='ACTIVE') OR EXISTS(SELECT 1 FROM communication_proposals WHERE communication_id=NEW.communication_id AND state IN ('PENDING','DEFERRED')) OR EXISTS(SELECT 1 FROM communication_participants WHERE communication_id=NEW.communication_id) OR EXISTS(SELECT 1 FROM communication_attachments WHERE communication_id=NEW.communication_id)) BEGIN SELECT RAISE(ABORT,'Communication purge dependencies survive'); END;
