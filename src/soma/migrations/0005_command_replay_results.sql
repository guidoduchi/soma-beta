CREATE TABLE command_receipt_results (
    command_id TEXT PRIMARY KEY REFERENCES command_receipts(command_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    response_schema TEXT NOT NULL,
    response_version INTEGER NOT NULL CHECK(response_version > 0),
    response_json TEXT NOT NULL CHECK(json_valid(response_json)),
    response_sha256 TEXT NOT NULL CHECK(length(response_sha256) = 64)
) STRICT;

CREATE TRIGGER command_receipt_results_before_update_append_only
BEFORE UPDATE ON command_receipt_results
BEGIN
    SELECT RAISE(ABORT, 'COMMAND_REPLAY_RESULT_APPEND_ONLY');
END;

CREATE TRIGGER command_receipt_results_before_delete_append_only
BEFORE DELETE ON command_receipt_results
BEGIN
    SELECT RAISE(ABORT, 'COMMAND_REPLAY_RESULT_APPEND_ONLY');
END;
