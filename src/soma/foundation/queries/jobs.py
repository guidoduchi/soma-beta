"""Foundation's versioned read-only durable-job metadata boundary.

This projection is intentionally joinable in a caller's read snapshot. It grants
no job lifecycle authority and exposes no payload, checkpoint or claim identity.
Consumers must apply their own bounded query/filter/cursor contracts.
"""

DURABLE_JOB_METADATA_V1 = "durable_job_metadata_v1"

DURABLE_JOB_METADATA_V1_DDL = """
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
"""
