CREATE TABLE sr_source_presence_events (
    sr_source_presence_event_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    source_family TEXT NOT NULL CHECK(source_family='advanced_search_sr'),
    event_kind TEXT NOT NULL CHECK(event_kind IN ('disappearance_reviewed','reappearance_confirmed')),
    prior_presence_event_id TEXT REFERENCES sr_source_presence_events(sr_source_presence_event_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    import_run_id TEXT NOT NULL CHECK(length(import_run_id)>0),
    source_observation_id TEXT,
    prior_source_observation_id TEXT,
    reconciliation_proposal_id TEXT,
    accepted_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    CHECK(event_kind='disappearance_reviewed' OR prior_presence_event_id IS NOT NULL),
    CHECK(
        (event_kind='disappearance_reviewed' AND source_observation_id IS NULL AND prior_source_observation_id IS NOT NULL AND reconciliation_proposal_id IS NOT NULL)
        OR
        (event_kind='reappearance_confirmed' AND source_observation_id IS NOT NULL AND prior_source_observation_id IS NULL AND reconciliation_proposal_id IS NULL)
    )
) STRICT;

CREATE UNIQUE INDEX uq_sr_source_presence_chain_root
    ON sr_source_presence_events(service_request_id,source_family)
    WHERE prior_presence_event_id IS NULL;
CREATE UNIQUE INDEX uq_sr_source_presence_successor
    ON sr_source_presence_events(prior_presence_event_id)
    WHERE prior_presence_event_id IS NOT NULL;
CREATE INDEX idx_sr_source_presence_current
    ON sr_source_presence_events(service_request_id,source_family,sr_source_presence_event_id);
CREATE INDEX idx_sr_source_presence_command_fk
    ON sr_source_presence_events(accepted_command_id,sr_source_presence_event_id);
CREATE INDEX idx_sr_source_presence_import_ref
    ON sr_source_presence_events(import_run_id,sr_source_presence_event_id);
CREATE INDEX idx_sr_source_presence_observation_ref
    ON sr_source_presence_events(source_observation_id,sr_source_presence_event_id);
CREATE INDEX idx_sr_source_presence_prior_observation_ref
    ON sr_source_presence_events(prior_source_observation_id,sr_source_presence_event_id);
CREATE INDEX idx_sr_source_presence_proposal_ref
    ON sr_source_presence_events(reconciliation_proposal_id,sr_source_presence_event_id);

CREATE TRIGGER sr_source_presence_update_guard
BEFORE UPDATE ON sr_source_presence_events BEGIN
    SELECT RAISE(ABORT,'SR_SOURCE_PRESENCE_APPEND_ONLY');
END;

CREATE TRIGGER sr_source_presence_delete_guard
BEFORE DELETE ON sr_source_presence_events BEGIN
    SELECT RAISE(ABORT,'SR_SOURCE_PRESENCE_APPEND_ONLY');
END;

CREATE TRIGGER sr_source_presence_prior_guard
BEFORE INSERT ON sr_source_presence_events
WHEN NEW.prior_presence_event_id IS NOT NULL BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM sr_source_presence_events prior
        WHERE prior.sr_source_presence_event_id=NEW.prior_presence_event_id
          AND prior.service_request_id=NEW.service_request_id
          AND prior.source_family=NEW.source_family
          AND ((prior.event_kind='disappearance_reviewed' AND NEW.event_kind='reappearance_confirmed')
               OR (prior.event_kind='reappearance_confirmed' AND NEW.event_kind='disappearance_reviewed'))
    ) THEN RAISE(ABORT,'SR_SOURCE_PRESENCE_PRIOR_INVALID') END;
END;
