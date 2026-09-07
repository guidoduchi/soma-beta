# SOMA Beta 1.0 — LLD Peer Review Pass 1

Status: **PASS**

## Review source and corrected successor

Initial frozen source:
- Commit: `7a1371d4301f4f8234d65dd9990d0423ebffb677`
- Tree: `a916ed9fedab18a1ac3e5511780ac959362b76f0`
- Initial structural workflow: `34092357361`

Corrected semantic source independently re-reviewed:
- Commit: `27fa4cdc068e21629973cdca0d0af3af6c91f589`
- Tree: `53d8ffbbd0867fc6fd5236eaf4bea63cd2e33360`
- Hardened workflow run: `34156857798`
- Final integrity result: `BLOCKER=0 HIGH=0 MEDIUM=0 LOW=0`

Authority order: normalized requirements/accepted decisions > focused contracts > architecture/glossary/reconciliation > HLD > LLD > implementation guidance.

## Initial findings and closure evidence

| ID | Initial severity | Closure | Corrected authority/evidence |
|---|---:|---|---|
| `LLD-P1-001` | HIGH | **CLOSED** | Replaced Objective-execution semantics with `StartSelectedObjectiveTasks`. The command starts only explicitly selected Task attempts; Objective `in_progress` remains derived and there is no Objective start event/timestamp/execution authority. Route, DTO, audit, transition, UI, implementation map, traceability and acceptance evidence were propagated. |
| `LLD-P1-002` | HIGH | **CLOSED** | Spare Request now persists immutable `requester_contact_id` plus bounded creation-time requester context, distinct from receiver logistics. Active/nonterminal requester relationships participate in LLD-02 Contact archive guards; terminal history preserves requester identity/context. Dedicated requester acceptance and supporting-requirement traceability were added. |
| `LLD-P1-003` | HIGH | **CLOSED** | LLD-09 authoritative application chronology was converted from `*_utc_ms` to canonical UTC whole-second `*_utc` fields. Provider checkpoint millisecond precision is retained only as explicitly source-owned provenance. `validate_chronology_precision.py` now fails closed on regression. |
| `LLD-P1-004` | HIGH | **CLOSED** | `HistoricalObjectiveProposalRepository` now matches accepted command/HLD semantics: valid accepted source-plan evidence may support reviewed historical structure when no conflicting operational plan exists; matching operational plan may be reused; dedicated historical plan is created only by explicit acceptance and never fabricates execution/outcome/Inventory facts. |
| `LLD-P1-005` | BLOCKER | **CLOSED** | Added canonical owner-side `interfaces/cross-packet-v2.json` registries across all packets and hardened SIG-008 with `validate_interfaces.py` plus manifest enforcement. Provider existence, exact methods/types and UoW/read-only semantics are now proved from actual registries rather than consumer traceability claims. Current result: `SIG-008 BLOCKER=0`. |
| `LLD-P1-006` | HIGH | **CLOSED** | Portable backup is now `SOMA_PORTABLE_BACKUP_SET_V1`: atomic `.somabackupset` directory containing encrypted `payload.somabackup`, canonical detached `manifest.json`, and detached HMAC-SHA-256 `auth.json`, with independent HKDF domains for KEK and authenticity. Missing/invalid companion evidence blocks restore before live mutation. `validate_portable_backup_set.py` enforces the contract. |
| `LLD-P1-007` | HIGH | **CLOSED** | Decision Ledger O-001/O-003/O-004/O-005/O-006/O-007/O-010 were moved to resolved state with exact LLD authority. No unresolved Beta 1.0 HLD/LLD design question remains; exact release builds/dependency hashes/signing identity remain release-candidate verification evidence rather than open product behavior. |
| `LLD-P1-008` | MEDIUM | **CLOSED** | Removed mandatory persisted `username`. LLD-02 now owns immutable profile/actor identity plus editable descriptive `display_name`, defaulted server-side to `Local Administrator`; setup/login remain password-only and display-name edits cannot affect credentials, sessions, actor identity, security revision or encryption. Dedicated Local User Profile validator passes. |
| `LLD-P1-009` | HIGH | **CLOSED** | RFC terminal cascade and Device Reference regularization now call LLD-12 `validate_and_consume(uow,...)` inside the same authoritative UnitOfWork after exact state re-read. Proof consumption rolls back with participant failure and second use fails. |

## Hardened machine proof on corrected source

Workflow `34156857798` executed all of the following successfully on the same commit:

- cross-packet interface closure: `BLOCKER=0`
- canonical interface manifest closure: `BLOCKER=0`
- HLD-14 chronology precision: `HIGH=0`
- portable backup companion-set closure: `HIGH=0`
- Local User Profile password-only identity closure: `MEDIUM=0`
- final evidence-normalized review-ready gate: `BLOCKER=0 HIGH=0 MEDIUM=0 LOW=0`

The reverse traceability reconciliation is recorded in `docs/reconciliation/LLD_PASS1_REVERSE_TRACEABILITY.md` and found no forward requirement orphan, reverse implementation-authority orphan, unresolved provider seam, or new semantic contradiction.

## Independent corrected-successor semantic re-review

The corrected source was reviewed again from the consequences inward rather than merely checking that the original findings disappeared. The following high-risk invariants were reconfirmed:

- WFM remains a Task and Inventory owns no Task lifecycle.
- WFM source plan, accepted operational Task plan, Objective membership-pinned plan/envelope and actual execution remain separate authorities.
- RFC terminal source evidence creates/revises pending cascade evidence only; local consequences require explicit deliberate execution in one shared UoW.
- Direct SR↔RFC relation targets the root RFC and RFC hierarchy remains exactly two levels.
- Product Line remains reusable/customer-neutral; customer-specific Contract Product Line remains SLA authority; live policy revisions recalculate current truth while completed reports remain immutable.
- Device Reference remains operational identity before and after Infrastructure regularization.
- Objective timezone remains scheduling-only; ordinary/SLA/source chronology is not rewritten.
- Communications remain evidence/proposal authority only and persist known application instants as UTC whole seconds.
- UI working copy/Undo remains non-authoritative and invokes owner-defined commands/safe inverses.
- Overview remains derived/read-only from one shared read snapshot.
- Password, live DEK, portable recovery, browser session and launcher/run-control identities remain separate security authorities.
- Portable restore remains verify-before-mutation and payload-only recovery is forbidden.
- No new semantic contradiction was introduced by the correction set.

## Pass 1 verdict

**PASS.**

All initial Pass-1 BLOCKER/HIGH/MEDIUM findings are corrected and propagated. The corrected semantic source passes the hardened machine gate and an independent semantic re-review. Traceability and reverse-orphan reconciliation are complete for Pass 1.

This PASS does **not** authorize implementation. All packet `ai_implementation_ready` and `owner_accepted` flags remain false. Pass 2 implementation-determinism/engineering-safety review is still required, followed by project-owner acceptance of the complete corrected LLD set.
