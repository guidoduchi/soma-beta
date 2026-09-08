CREATE TABLE reference_metadata (
    singleton_guard INTEGER PRIMARY KEY CHECK(singleton_guard = 1),
    matching_profile_id TEXT NOT NULL CHECK(length(matching_profile_id) > 0),
    customer_reference_generation INTEGER NOT NULL DEFAULT 0 CHECK(customer_reference_generation >= 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0)
) STRICT;

CREATE TABLE local_user_profiles (
    local_user_profile_id TEXT PRIMARY KEY,
    singleton_guard INTEGER NOT NULL UNIQUE CHECK(singleton_guard = 1),
    display_name TEXT NOT NULL CHECK(length(display_name) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc)
) STRICT;

CREATE TABLE customer_organizations (
    customer_org_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) > 0),
    name_match_key TEXT NOT NULL CHECK(length(name_match_key) > 0),
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc)
) STRICT;

CREATE TABLE customer_org_identifiers (
    customer_org_identifier_id TEXT PRIMARY KEY,
    customer_org_id TEXT NOT NULL REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    identifier_type TEXT NOT NULL CHECK(identifier_type = 'customer_account_code'),
    value_text TEXT NOT NULL CHECK(length(value_text) > 0),
    match_key TEXT NOT NULL CHECK(length(match_key) > 0),
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','superseded')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    superseded_at_utc INTEGER,
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    superseded_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK(
        (lifecycle_state = 'active' AND superseded_at_utc IS NULL AND superseded_command_id IS NULL)
        OR
        (lifecycle_state = 'superseded' AND superseded_at_utc IS NOT NULL AND superseded_command_id IS NOT NULL)
    )
) STRICT;

CREATE TABLE contacts (
    contact_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) > 0),
    name_match_key TEXT NOT NULL CHECK(length(name_match_key) > 0),
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc)
) STRICT;

CREATE TABLE contact_channels (
    contact_channel_id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    channel_kind TEXT NOT NULL CHECK(channel_kind = 'email'),
    value_text TEXT NOT NULL CHECK(length(value_text) > 0),
    match_key TEXT NOT NULL CHECK(length(match_key) > 0),
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc)
) STRICT;

CREATE TABLE contact_affiliations (
    contact_affiliation_id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    customer_org_id TEXT NOT NULL REFERENCES customer_organizations(customer_org_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    is_current INTEGER NOT NULL CHECK(is_current IN (0,1)),
    opened_at_utc INTEGER NOT NULL CHECK(opened_at_utc >= 0),
    closed_at_utc INTEGER CHECK(closed_at_utc IS NULL OR closed_at_utc >= opened_at_utc),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    closed_command_id TEXT REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK(
        (is_current = 1 AND closed_at_utc IS NULL AND closed_command_id IS NULL)
        OR
        (is_current = 0 AND closed_at_utc IS NOT NULL AND closed_command_id IS NOT NULL)
    )
) STRICT;

CREATE TABLE dispatch_locations (
    dispatch_location_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) > 0),
    name_match_key TEXT NOT NULL CHECK(length(name_match_key) > 0),
    address_mode TEXT NOT NULL CHECK(address_mode IN ('standalone','site_derived')),
    standalone_address_text TEXT,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc >= 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= created_at_utc),
    CHECK(
        (address_mode = 'standalone' AND standalone_address_text IS NOT NULL AND length(standalone_address_text) > 0)
        OR
        (address_mode = 'site_derived' AND standalone_address_text IS NULL)
    )
) STRICT;

CREATE TABLE reference_lifecycle_events (
    reference_lifecycle_event_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK(target_type IN ('customer_organization','contact','dispatch_location')),
    target_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('created','archived','reactivated','descriptive_corrected')),
    occurred_at_utc INTEGER NOT NULL CHECK(occurred_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    reason_category TEXT
) STRICT;

CREATE TABLE setting_values (
    setting_key TEXT PRIMARY KEY,
    contract_name TEXT NOT NULL,
    contract_version INTEGER NOT NULL CHECK(contract_version > 0),
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc >= 0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

INSERT INTO reference_metadata(singleton_guard, matching_profile_id, customer_reference_generation, created_at_utc)
VALUES (1, 'UNICODE_MATCH_V1', 0, CAST(strftime('%s','now') AS INTEGER));

CREATE INDEX idx_customer_org_active_name_match
ON customer_organizations(lifecycle_state, name_match_key, customer_org_id);

CREATE UNIQUE INDEX uq_customer_org_active_identifier_type
ON customer_org_identifiers(customer_org_id, identifier_type)
WHERE lifecycle_state = 'active';

CREATE INDEX idx_customer_active_identifier_value
ON customer_org_identifiers(identifier_type, match_key, customer_org_id)
WHERE lifecycle_state = 'active';

CREATE INDEX idx_customer_identifier_history
ON customer_org_identifiers(customer_org_id, identifier_type, created_at_utc, customer_org_identifier_id);

CREATE INDEX idx_contacts_active_name_match
ON contacts(lifecycle_state, name_match_key, contact_id);

CREATE INDEX idx_contact_channels_contact
ON contact_channels(contact_id, lifecycle_state, channel_kind, created_at_utc, contact_channel_id);

CREATE INDEX idx_contact_channels_match
ON contact_channels(channel_kind, lifecycle_state, match_key, contact_id);

CREATE UNIQUE INDEX uq_contact_current_affiliation
ON contact_affiliations(contact_id)
WHERE is_current = 1;

CREATE INDEX idx_contact_affiliation_customer_current
ON contact_affiliations(customer_org_id, is_current, contact_id);

CREATE INDEX idx_contact_affiliation_history
ON contact_affiliations(contact_id, opened_at_utc, contact_affiliation_id);

CREATE INDEX idx_dispatch_active_name_match
ON dispatch_locations(lifecycle_state, name_match_key, dispatch_location_id);

CREATE INDEX idx_reference_lifecycle_target
ON reference_lifecycle_events(target_type, target_id, occurred_at_utc, reference_lifecycle_event_id);

CREATE INDEX idx_customer_identifier_created_command
ON customer_org_identifiers(created_command_id);

CREATE INDEX idx_customer_identifier_superseded_command
ON customer_org_identifiers(superseded_command_id)
WHERE superseded_command_id IS NOT NULL;

CREATE INDEX idx_contact_affiliation_opened_command
ON contact_affiliations(opened_command_id);

CREATE INDEX idx_contact_affiliation_closed_command
ON contact_affiliations(closed_command_id)
WHERE closed_command_id IS NOT NULL;

CREATE INDEX idx_reference_lifecycle_command
ON reference_lifecycle_events(command_id);

CREATE INDEX idx_setting_values_command
ON setting_values(command_id);

CREATE TRIGGER reference_customer_organizations_delete_forbidden
BEFORE DELETE ON customer_organizations
BEGIN
    SELECT RAISE(ABORT, 'REFERENCE_DELETE_FORBIDDEN');
END;

CREATE TRIGGER reference_contacts_delete_forbidden
BEFORE DELETE ON contacts
BEGIN
    SELECT RAISE(ABORT, 'REFERENCE_DELETE_FORBIDDEN');
END;

CREATE TRIGGER reference_dispatch_locations_delete_forbidden
BEFORE DELETE ON dispatch_locations
BEGIN
    SELECT RAISE(ABORT, 'REFERENCE_DELETE_FORBIDDEN');
END;

CREATE TRIGGER contact_channels_delete_forbidden
BEFORE DELETE ON contact_channels
BEGIN
    SELECT RAISE(ABORT, 'CONTACT_CHANNEL_DELETE_FORBIDDEN');
END;

CREATE TRIGGER customer_identifier_history_delete_forbidden
BEFORE DELETE ON customer_org_identifiers
BEGIN
    SELECT RAISE(ABORT, 'CUSTOMER_IDENTIFIER_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER customer_identifier_history_update_guard
BEFORE UPDATE ON customer_org_identifiers
BEGIN
    SELECT CASE
        WHEN OLD.lifecycle_state <> 'active'
          OR NEW.customer_org_identifier_id <> OLD.customer_org_identifier_id
          OR NEW.customer_org_id <> OLD.customer_org_id
          OR NEW.identifier_type <> OLD.identifier_type
          OR NEW.value_text <> OLD.value_text
          OR NEW.match_key <> OLD.match_key
          OR NEW.created_at_utc <> OLD.created_at_utc
          OR NEW.created_command_id <> OLD.created_command_id
          OR NEW.lifecycle_state <> 'superseded'
          OR NEW.superseded_at_utc IS NULL
          OR NEW.superseded_command_id IS NULL
        THEN RAISE(ABORT, 'CUSTOMER_IDENTIFIER_HISTORY_APPEND_ONLY')
    END;
END;

CREATE TRIGGER contact_affiliation_history_delete_forbidden
BEFORE DELETE ON contact_affiliations
BEGIN
    SELECT RAISE(ABORT, 'CONTACT_AFFILIATION_HISTORY_APPEND_ONLY');
END;

CREATE TRIGGER contact_affiliation_history_update_guard
BEFORE UPDATE ON contact_affiliations
BEGIN
    SELECT CASE
        WHEN OLD.is_current <> 1
          OR NEW.contact_affiliation_id <> OLD.contact_affiliation_id
          OR NEW.contact_id <> OLD.contact_id
          OR NEW.customer_org_id <> OLD.customer_org_id
          OR NEW.opened_at_utc <> OLD.opened_at_utc
          OR NEW.opened_command_id <> OLD.opened_command_id
          OR NEW.is_current <> 0
          OR NEW.closed_at_utc IS NULL
          OR NEW.closed_command_id IS NULL
        THEN RAISE(ABORT, 'CONTACT_AFFILIATION_HISTORY_APPEND_ONLY')
    END;
END;

CREATE TRIGGER reference_lifecycle_events_update_forbidden
BEFORE UPDATE ON reference_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'REFERENCE_LIFECYCLE_APPEND_ONLY');
END;

CREATE TRIGGER reference_lifecycle_events_delete_forbidden
BEFORE DELETE ON reference_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'REFERENCE_LIFECYCLE_APPEND_ONLY');
END;

CREATE TRIGGER customer_reference_generation_after_customer_insert
AFTER INSERT ON customer_organizations
BEGIN
    UPDATE reference_metadata
    SET customer_reference_generation = customer_reference_generation + 1
    WHERE singleton_guard = 1;
END;

CREATE TRIGGER customer_reference_generation_after_customer_update
AFTER UPDATE ON customer_organizations
BEGIN
    UPDATE reference_metadata
    SET customer_reference_generation = customer_reference_generation + 1
    WHERE singleton_guard = 1;
END;

CREATE TRIGGER customer_reference_generation_after_identifier_insert
AFTER INSERT ON customer_org_identifiers
BEGIN
    UPDATE reference_metadata
    SET customer_reference_generation = customer_reference_generation + 1
    WHERE singleton_guard = 1;
END;

CREATE TRIGGER customer_reference_generation_after_identifier_update
AFTER UPDATE ON customer_org_identifiers
BEGIN
    UPDATE reference_metadata
    SET customer_reference_generation = customer_reference_generation + 1
    WHERE singleton_guard = 1;
END;
