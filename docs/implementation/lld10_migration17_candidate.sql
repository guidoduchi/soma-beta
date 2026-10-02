-- LLD-10; central allocation 17 supersedes provisional packet-local sequence 16.

CREATE TABLE ui_working_copies(
    working_copy_id TEXT PRIMARY KEY,
    owner_profile_id TEXT NOT NULL REFERENCES local_user_profiles(local_user_profile_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    target_type TEXT NOT NULL CHECK(length(target_type) BETWEEN 1 AND 64),
    target_id TEXT NOT NULL CHECK(length(target_id) BETWEEN 1 AND 128),
    scope_key TEXT NOT NULL CHECK(length(scope_key) BETWEEN 1 AND 96),
    draft_contract_id TEXT NOT NULL CHECK(length(draft_contract_id) BETWEEN 1 AND 96),
    draft_contract_version INTEGER NOT NULL CHECK(draft_contract_version>0),
    base_revision_token TEXT NOT NULL CHECK(length(base_revision_token) BETWEEN 1 AND 256),
    payload_json TEXT NOT NULL CHECK(length(payload_json)>1),
    dirty_paths_json TEXT NOT NULL CHECK(length(dirty_paths_json)>1),
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    generation INTEGER NOT NULL CHECK(generation>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc>=created_at_utc),
    expires_at_utc INTEGER NOT NULL CHECK(expires_at_utc>updated_at_utc),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    last_checkpoint_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CHECK(expires_at_utc=updated_at_utc+604800),
    CHECK(json_valid(payload_json) AND json_type(payload_json)='object'),
    CHECK(json_valid(dirty_paths_json) AND json_type(dirty_paths_json)='array'),
    CHECK(length(CAST(payload_json AS BLOB))<=262144),
    CHECK(content_hash NOT GLOB '*[^0-9a-f]*')
) STRICT;

CREATE UNIQUE INDEX uq_ui_working_copy_key ON ui_working_copies(owner_profile_id,target_type,target_id,scope_key);

CREATE INDEX idx_ui_working_copy_expiry ON ui_working_copies(expires_at_utc,working_copy_id);

CREATE INDEX idx_ui_working_copy_target ON ui_working_copies(target_type,target_id,updated_at_utc,working_copy_id);

CREATE INDEX idx_ui_working_copy_created_command ON ui_working_copies(created_command_id);

CREATE INDEX idx_ui_working_copy_checkpoint_command ON ui_working_copies(last_checkpoint_command_id);
