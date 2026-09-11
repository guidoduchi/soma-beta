# RC-006-A2 — Extraction Schema Clarification Amendment 001

Status: **PASS — pre-allocation clarification/tool-hardening; accepted product authority unchanged; allocated assertions remain 0**  
Baseline: `A2-BASELINE-002`  
Applies to: `A2-EXTRACTION-SCHEMA-V1`  
Reason: resolve locator ambiguity and require exact pinned-source verification before first allocation.

## 1. Scope

This amendment is issued before `A2-ASSERT-000001` allocation. It does not add or remove an assertion field, change assertion identity semantics, alter accepted product authority, or permit partial-file allocation.

It clarifies one ambiguous locator definition and strengthens the deterministic allocator so candidate metadata cannot claim source text or locations that are not present in the pinned B002 blob.

## 2. `section_ordinal` clarification

For V1 candidate and assertion records, `section_ordinal` means:

> the **1-based document-wide ordinal of the owning eligible Markdown section heading in source order**, counting every level-2 (`##`) and level-3 (`###`) heading after the document title.

It does **not** mean the occurrence count of an identical heading string.

This interpretation is controlling because V1 requires candidate ordering and uniqueness by `(section_ordinal, assertion_ordinal)`. Every candidate in one section therefore shares one document-wide `section_ordinal`, while `assertion_ordinal` is 1-based within that section.

Level-1 document titles are not assertion-owning sections under V1. Text before the first eligible `##` heading is metadata/context and receives no destination-assertion identity under this initial extraction contract.

## 3. `section_anchor` normalization

For V1 initial extraction, `section_anchor` is deterministically derived from the exact visible `##`/`###` heading text as follows:

1. Unicode NFC normalize;
2. remove Markdown backticks and emphasis-marker characters `` ` ``, `*`, and `_`;
3. lowercase;
4. remove every character except Unicode letters/numbers, ASCII space, and hyphen;
5. collapse one-or-more ASCII spaces to one hyphen; and
6. collapse repeated hyphens and trim leading/trailing hyphens.

The explicit anchor remains assurance metadata, not stable assertion identity.

## 4. Exact pinned-source candidate verification

Before accepting a candidate batch, the allocator shall resolve the candidate source from B002 source commit:

`61bbd665535e942ef3b05c5ed45661639d3a37a9`

and shall prove:

- the resolved source Git blob equals the blob recorded by `RC006_A2_SOURCE_ROLES.tsv`;
- `source_start_line..source_end_line` exists in the pinned source;
- `exact_text` occurs exactly once inside that claimed line range;
- the exact-text occurrence begins on `source_start_line` and ends on `source_end_line`;
- the nearest preceding eligible `##`/`###` heading is exactly `section_heading`;
- that heading's document-wide ordinal equals `section_ordinal`; and
- the deterministic normalized heading anchor equals `section_anchor`.

A mismatch is a validation failure and shall write no allocation state or assertion-ledger records.

## 5. Pre-allocation candidate-validation command

Allocator tool v1.1.0 adds a read-only `validate-candidates` command. It validates one complete candidate file against the same rules later used by allocation and emits deterministic evidence containing the candidate count/hash and pinned-source identity. It does not allocate IDs or modify state/ledger files.

## 6. Gate effect

- prior A2-1 source-role/schema decisions: **retained**;
- allocated assertion identities before amendment: **0**;
- stable IDs renumbered/reused: **0**;
- accepted product authority changed: **0**;
- first candidate batch allocation: **still prohibited until the complete Product Contract candidate file passes the hardened read-only validator**.

This amendment closes the ambiguity/tooling gap before stable identity allocation rather than repairing it after IDs exist.
