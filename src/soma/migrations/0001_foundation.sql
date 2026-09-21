CREATE TABLE instance_metadata (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    data_instance_id TEXT NOT NULL UNIQUE,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0)
) STRICT;

CREATE TABLE schema_migrations (
    sequence INTEGER PRIMARY KEY CHECK(sequence > 0),
    migration_id TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    applied_at_utc INTEGER NOT NULL CHECK(applied_at_utc >= 0),
    app_version TEXT NOT NULL
) STRICT;

CREATE TABLE command_receipts (
    command_id TEXT PRIMARY KEY,
    command_type TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK(length(request_hash) = 64),
    target_type TEXT NOT NULL,
    target_id TEXT,
    committed_at_utc INTEGER NOT NULL CHECK(committed_at_utc >= 0),
    result_type TEXT,
    result_id TEXT
) STRICT;

CREATE TABLE audit_events (
    audit_event_id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    action_version INTEGER NOT NULL CHECK(action_version > 0),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc >= 0),
    actor_kind TEXT NOT NULL,
    actor_id TEXT,
    target_type TEXT NOT NULL,
    target_id TEXT,
    reason_category TEXT,
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    correlation_id TEXT,
    job_id TEXT,
    import_run_id TEXT,
    proposal_id TEXT,
    batch_id TEXT,
    payload_schema TEXT NOT NULL,
    payload_version INTEGER NOT NULL CHECK(payload_version > 0),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
) STRICT;

CREATE TABLE audit_event_results (
    audit_event_id TEXT NOT NULL REFERENCES audit_events(audit_event_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    result_type TEXT NOT NULL,
    result_id TEXT NOT NULL,
    PRIMARY KEY(audit_event_id, ordinal),
    UNIQUE(audit_event_id, result_type, result_id)
) STRICT;

CREATE TABLE durable_jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    contract_version INTEGER NOT NULL CHECK(contract_version > 0),
    state TEXT NOT NULL CHECK(state IN ('queued','running','waiting_review','retry_wait','completed','failed','cancelled')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    next_attempt_at_utc INTEGER,
    claimed_run_id TEXT,
    claim_started_at_utc INTEGER,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    checkpoint_json TEXT CHECK(checkpoint_json IS NULL OR json_valid(checkpoint_json)),
    last_error_code TEXT,
    CHECK(
        (state = 'running' AND claimed_run_id IS NOT NULL AND claim_started_at_utc IS NOT NULL)
        OR
        (state <> 'running' AND claimed_run_id IS NULL AND claim_started_at_utc IS NULL)
    )
) STRICT;

CREATE TABLE job_attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    run_id TEXT NOT NULL,
    started_at_utc INTEGER NOT NULL CHECK(started_at_utc >= 0),
    finished_at_utc INTEGER NOT NULL CHECK(finished_at_utc >= started_at_utc),
    outcome TEXT NOT NULL CHECK(outcome IN ('completed','failed','cancelled','interrupted')),
    error_code TEXT,
    UNIQUE(job_id, ordinal)
) STRICT;

CREATE INDEX idx_audit_recorded_at ON audit_events(recorded_at_utc);
CREATE INDEX idx_audit_target ON audit_events(target_type, target_id, recorded_at_utc);
CREATE INDEX idx_audit_command ON audit_events(command_id);
CREATE INDEX idx_jobs_state_due ON durable_jobs(state, next_attempt_at_utc);
CREATE INDEX idx_jobs_type_state ON durable_jobs(job_type, state);

CREATE TRIGGER audit_events_before_update_append_only
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
END;

CREATE TRIGGER audit_events_before_delete_append_only
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
END;

CREATE TRIGGER audit_event_results_before_update_append_only
BEFORE UPDATE ON audit_event_results
BEGIN
    SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
END;

CREATE TRIGGER audit_event_results_before_delete_append_only
BEFORE DELETE ON audit_event_results
BEGIN
    SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
END;

WITH random_uuid(h) AS (
    SELECT lower(hex(randomblob(16)))
)
INSERT INTO instance_metadata(singleton, data_instance_id, created_at_utc)
SELECT
    1,
    substr(h,1,8) || '-' || substr(h,9,4) || '-4' || substr(h,14,3) || '-8' || substr(h,18,3) || '-' || substr(h,21,12),
    CAST(strftime('%s','now') AS INTEGER)
FROM random_uuid;
