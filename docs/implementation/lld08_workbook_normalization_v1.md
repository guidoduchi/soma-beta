# LLD-08 workbook normalization V1 implementation contract

The owner-approved workbook normalization clarification is now reconciled into
design authority `13efc6979bd6f021b1a0fdbb1074f3a3746e8ce8`. This implementation
contract records the corresponding V1 runtime representation; it does not
override that pinned design authority.

Each row is canonical UTF-8 JSON with exactly `version`, `sheet`, and `fields`.
`version` is `INFRA_WORKBOOK_NORMALIZED_ROW_V1`. `sheet` is one of the two data
sheet names. `fields` has exactly the profile header names for that sheet; every
value is text, exact integer, boolean, or null. Empty and whitespace-only
descriptive cells become null (preserve-on-existing, not an explicit clear).
Descriptive text is trimmed with the shared pinned Unicode whitespace asset,
normalized to NFC, then checked against its owning field bound. Same-instance
nonblank `Soma*` IDs must be canonical UUIDv4. Foreign IDs are NFC-normalized,
trimmed, bounded provenance text only, never direct-target authority. Rack
numbers are exact integers 1..120. IP `Address` is the canonical compressed
host text from `IP_NORMALIZATION_V1`; `Primary` is boolean or null. The row
fingerprint is lowercase SHA-256 of that canonical JSON object.

The logical fingerprint hashes canonical UTF-8 JSON with exactly `version`
(`INFRA_WORKBOOK_LOGICAL_V1`), `format_id`, `workbook_version`, `mode`,
`source_installation_scope_id`, `export_scope`, `network_elements`, and
`ip_addresses`. The two row arrays contain sorted lowercase row fingerprints
and preserve duplicate entries. Metadata `GeneratedAtUtc` and physical row
ordinals are excluded. The source installation scope remains in the hash;
foreign workbook IDs therefore cannot gain same-instance meaning by replay.

Check-now requires an explicitly persisted LLD-02
`infrastructure.import_directory` setting with a positive revision. The
computed default can be displayed but must be saved before the command is
eligible. No synthetic default revision or alternate freshness token is
created; this is reconciled in the pinned design authority.

`INFRA_JOB_ACCEPTED_V1.state` includes `retry_wait` so a coalesced durable
job reports its actual technical state. This closed-enum reconciliation is
present in design authority `13efc6979bd6f021b1a0fdbb1074f3a3746e8ce8`;
consumers must accept the additional value.
