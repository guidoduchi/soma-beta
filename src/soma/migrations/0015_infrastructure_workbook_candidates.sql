-- Forward-only LLD-08 repair: bounded proposal candidate identities.
-- Existing proposals predate candidate persistence and therefore have none.
ALTER TABLE infrastructure_workbook_proposals
ADD COLUMN candidate_ids_json TEXT NOT NULL DEFAULT '[]'
CHECK (json_valid(candidate_ids_json)
       AND json_type(candidate_ids_json) = 'array'
       AND json_array_length(candidate_ids_json) <= 500);
