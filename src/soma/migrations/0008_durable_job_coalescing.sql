ALTER TABLE durable_jobs
ADD COLUMN dedupe_sha256 TEXT
CHECK(
    dedupe_sha256 IS NULL
    OR (
        length(dedupe_sha256) = 64
        AND dedupe_sha256 NOT GLOB '*[^0-9a-f]*'
    )
);

CREATE INDEX idx_jobs_dedupe_state
ON durable_jobs(job_type, contract_version, dedupe_sha256, state);

CREATE UNIQUE INDEX uq_jobs_active_dedupe
ON durable_jobs(job_type, contract_version, dedupe_sha256)
WHERE dedupe_sha256 IS NOT NULL
  AND state IN ('queued','running','waiting_review','retry_wait');
