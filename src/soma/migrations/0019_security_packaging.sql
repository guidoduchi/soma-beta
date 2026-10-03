-- LLD-12, global forward allocation 19 (owner reconciliation).
-- Complete accepted security-core schema; workflow implementation remains scoped.

CREATE TABLE security_auth_credentials(
    singleton_guard INTEGER PRIMARY KEY CHECK(singleton_guard=1),
    local_user_profile_id TEXT NOT NULL UNIQUE REFERENCES local_user_profiles(local_user_profile_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    verifier_phc TEXT NOT NULL CHECK(length(verifier_phc) BETWEEN 32 AND 1024),
    verifier_profile TEXT NOT NULL CHECK(verifier_profile='ARGON2ID_V1'),
    security_revision INTEGER NOT NULL CHECK(security_revision>0),
    configured_at_utc INTEGER NOT NULL CHECK(configured_at_utc>=0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc>=configured_at_utc),
    reset_verifier_sha256 BLOB NOT NULL CHECK(length(reset_verifier_sha256)=32)
) STRICT;

CREATE TABLE security_auto_login(
    singleton_guard INTEGER PRIMARY KEY CHECK(singleton_guard=1),
    credential_id TEXT NOT NULL UNIQUE,
    token_verifier_sha256 BLOB NOT NULL CHECK(length(token_verifier_sha256)=32),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision>0),
    updated_at_utc INTEGER NOT NULL CHECK(updated_at_utc>=0)
) STRICT;

CREATE TABLE managed_backup_catalog(
    backup_id TEXT PRIMARY KEY,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    state TEXT NOT NULL CHECK(state IN ('building','verifying','verified','failed','pruned','restored')),
    relative_artifact_name TEXT NOT NULL CHECK(length(relative_artifact_name)>0),
    artifact_sha256 BLOB CHECK(artifact_sha256 IS NULL OR length(artifact_sha256)=32),
    source_schema_version INTEGER NOT NULL CHECK(source_schema_version>=0),
    verified_at_utc INTEGER,
    failure_code TEXT,
    revision INTEGER NOT NULL CHECK(revision>0),
    CHECK(state<>'verified' OR (artifact_sha256 IS NOT NULL AND verified_at_utc IS NOT NULL))
) STRICT;

CREATE INDEX idx_managed_backup_verified_created ON managed_backup_catalog(state,created_at_utc DESC,backup_id);

CREATE TRIGGER security_auth_credentials_no_delete
BEFORE DELETE ON security_auth_credentials
BEGIN
    SELECT RAISE(ABORT, 'security_auth_credentials ordinary DELETE forbidden');
END;

CREATE TRIGGER managed_backup_catalog_identity_immutable
BEFORE UPDATE OF backup_id,created_at_utc ON managed_backup_catalog
WHEN NEW.backup_id IS NOT OLD.backup_id OR NEW.created_at_utc IS NOT OLD.created_at_utc
BEGIN
    SELECT RAISE(ABORT, 'managed_backup_catalog identity/created_at immutable');
END;
