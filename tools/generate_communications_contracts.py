"""Capture pinned LLD-09 transport authority plus accepted owner clarifications.

This is build-time tooling; runtime never consults Git or another branch.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

DESIGN_SHA = "9a0e891127a771251afccca1a281b7ef7dde9e5f"
ROOT = Path(__file__).resolve().parents[1]


def leaf(path: str) -> dict:
    return json.loads(subprocess.check_output(
        ["git", "show", f"{DESIGN_SHA}:spec/lld/communications/{path}"],
        cwd=ROOT, text=True, encoding="utf-8",
    ))


def main() -> None:
    packet = leaf("_index.json")
    captured = {path: leaf(path) for path in packet["normative_paths"]}
    panel_path = "docs/reconciliation/LLD09_COMMUNICATION_PANEL_HTTP_V1.json"
    panel = json.loads((ROOT / panel_path).read_text(encoding="utf-8"))
    if panel["status"] != "ACCEPTED_OWNER_CLARIFICATION" or panel["design_sha"] != DESIGN_SHA:
        raise ValueError("Communication panel HTTP requires pinned owner acceptance")
    captured["routes.json"]["routes"].append(panel["route"])
    captured["types/queries.json"]["types"].append(panel["request"])
    captured["queries/v2/communication-panel.json"] = {**panel["query"], "owner_clarification": panel_path}
    captured["implementation/module-map.json"]["queries"]["GetCommunicationPanel"] = panel["implementation_module"]
    captured["algorithms/matching-retention.json"]["accepted_warehouse_review_clarifications"] = [
        "RTYYMMDDxx is optional return-batch context, not an operational identity, item receipt, disposition or event chronology. Missing RT warns the operator without blocking an otherwise valid item-level receipt.",
        "A batch/thread may include items that were not accepted. Exact SR7/C10 and PartNumber/Bomcode context does not replace owner-governed Fault Tag membership and physical-unit validation.",
        "CLOSED wording alone leaves final disposition unresolved. Do not generate an accepted/rejected domain-fact proposal from it; the operator supplies the actual decision and the existing owner command requires explicit confirmation.",
    ]
    captured["schema/coverage-jobs.json"]["tables"].append({
        "name": "communication_job_cancellation_events", "primary_key": "cancellation_event_id TEXT UUID",
        "columns": ["cancellation_event_id TEXT NOT NULL", "job_id TEXT NOT NULL FK communication_job_scopes",
            "job_kind TEXT NOT NULL CHECK in ORDINARY,TARGETED_BACKFILL,DEEP_SCAN,IDENTITY_RECONCILIATION,ORPHAN_HOUSEKEEPING",
            "prior_state TEXT NOT NULL CHECK in queued,running,waiting_review,retry_wait",
            "resulting_state TEXT NOT NULL CHECK in cancelled", "claim_revoked INTEGER NOT NULL CHECK in 0,1",
            "cancelled_attempt_ordinal INTEGER", "recorded_at_utc INTEGER NOT NULL", "command_id TEXT NOT NULL"],
        "indexes": ["idx_comm_job_cancel_history(job_id,recorded_at_utc DESC,cancellation_event_id DESC)"],
    })
    captured["types/jobs.json"]["types"].extend([
        {"name": "CancelCommunicationJobRequestV1", "kind": "object", "additionalProperties": False,
         "required": ["command_id", "job_id"], "properties": {"command_id": "uuid", "job_id": "uuid"}},
        {"name": "CommunicationJobCancellationResultV1", "kind": "object", "additionalProperties": False,
         "required": ["status", "job_id", "prior_state", "resulting_state", "cancellation_event_id"],
         "properties": {"status": "APPLIED|NO_CHANGE", "job_id": "uuid", "prior_state": "Foundation job state",
            "resulting_state": "Foundation job state", "cancellation_event_id": "uuid|null; present only for actual cancellation"}},
    ])
    captured["commands/v2/cancel-job.json"] = {
        "schema": "SOMA-LLD-COMMAND-V2", "lld_id": "LLD-09", "name": "CancelCommunicationJob",
        "input_type": "CancelCommunicationJobRequestV1", "response_type": "CommunicationJobCancellationResultV1",
        "owner_clarification": "docs/reconciliation/LLD09_QUERY_JOB_CONTRACT_CANDIDATE.md",
        "rules": ["Validate owned scope against Foundation metadata; never cancel another packet's job.",
            "Foundation cancellation, immutable cancellation event, receipt/result and action audit share one outer writer UoW.",
            "Already cancelled, completed or failed returns truthful NO_CHANGE without new event/audit or revision.",
            "Cancellation revokes the active claim and preserves all last committed counters/checkpoints/coverage.",
            "Exact receipt replay precedes mutable job reads; no source availability or revision guard prevents cancellation."],
    }
    captured["implementation/module-map.json"]["commands"]["CancelCommunicationJob"] = "services/job_control.py"
    captured["routes.json"]["routes"].append({
        "method": "POST", "path": "/api/v1/communications/jobs/{job_id}/cancel", "handler_kind": "command",
        "handler": "CancelCommunicationJob", "request_type": "CancelCommunicationJobRequestV1",
        "response_type": "CommunicationJobCancellationResultV1", "success_status": 200,
        "max_request_bytes": 4096, "auth_policy": "LLD12_BROWSER_MUTATION_V1",
        "error_codes": ["VALIDATION_FAILED", "INTEGRITY_FAILURE", "IDEMPOTENCY_CONFLICT"],
    })
    captured["audit/actions.json"]["actions"].append({
        "action_type": "communications.job.cancelled", "action_version": 1,
        "payload_schema": "CommJobCancelledAuditV1", "payload_version": 1, "target": "job_id",
        "payload_fields": ["job_kind", "prior_state", "resulting_state"],
        "forbidden": ["message content", "provider raw identity", "source path", "job payload", "checkpoint", "claim secret"],
    })
    for item in captured["types/common.json"]["types"]:
        if item["name"] == "ChronologyV1":
            item["required"] = ["known", "utc_epoch_seconds", "source_kind"]
            item["properties"]["utc_epoch_seconds"] = item["properties"].pop("utc_epoch_ms")
            item["rule"] = item["rule"].replace("utc_epoch_ms", "utc_epoch_seconds")
        if item["name"] == "GenerateMsgDraftRequestV1":
            item["properties"]["recipients"] = "array[MsgDraftRecipientV1] 1..2000; preserve source order within each role"
            item["properties"]["origin_domain"] = "LLD-05|LLD-07; current local draft flows only"
            item["properties"]["origin_target_type"] = "OBJECTIVE for LLD-05; SPARE_REQUEST for LLD-07"
            item["properties"]["origin_target_id"] = "uuid; required current owner target"
    captured["types/common.json"]["types"].append({
        "name": "MsgDraftRecipientV1", "kind": "object", "additionalProperties": False,
        "required": ["role", "address", "display_name"],
        "properties": {"role": "TO|CC|BCC", "address": "string 1..320; valid mailbox syntax; preserve exact validated bytes",
                       "display_name": "string 0..512|null"},
    })
    terminal = next(table for table in captured["schema/orphan-purge.json"]["tables"] if table["name"] == "communication_terminal_summaries")
    terminal["columns"].append("last_interaction_source_kind TEXT NOT NULL CHECK in RECEIVED_TIME,SENT_TIME,OTHER_PROVIDER_TIME,UNKNOWN")
    terminal["columns"].append("summary_revision INTEGER NOT NULL CHECK summary_revision>=1")
    terminal["constraints"].append("UNIQUE(target_type,target_id,summary_revision)")
    terminal["indexes"].append("idx_comm_terminal_revision(target_type,target_id,summary_revision DESC)")
    captured["types/message.json"]["types"].append({
        "name": "FrozenTerminalCommunicationSummaryV1", "kind": "object", "additionalProperties": False,
        "required": ["terminal_summary_id", "target_type", "target_id", "governing_event_id", "summary_revision",
                     "received_count", "sent_count", "unknown_count", "last_interaction", "last_direction",
                     "coverage_state", "unlink_utc", "summary_fingerprint"],
        "properties": {"terminal_summary_id": "uuid", "target_type": "SERVICE_REQUEST|RFC", "target_id": "uuid",
            "governing_event_id": "immutable owner event identity", "summary_revision": "int>=1",
            "received_count": "int>=0", "sent_count": "int>=0", "unknown_count": "int>=0",
            "last_interaction": "ChronologyV1", "last_direction": "RECEIVED|SENT|MIXED|UNKNOWN",
            "coverage_state": "COMPLETE|PARTIAL|UNKNOWN", "unlink_utc": "int64 UTC seconds", "summary_fingerprint": "sha256"},
    })
    captured["queries/v2/entity-summary.json"]["owner_clarifications"] = {
        "coverage": "COMPLETE requires recorded coverage for current exported target identities from their eligibility boundary or a reviewed full scan across every configured selected folder. UNKNOWN for unproved boundary/range/identity; PARTIAL for explicit incomplete coverage; UNKNOWN takes precedence.",
        "last_direction": "At the latest known interaction UTC second, RECEIVED plus SENT yields MIXED; otherwise uncertain direction yields UNKNOWN; otherwise the single known direction. Without known chronology return UNKNOWN. Chronology provenance follows timestamp/Communication-ID ordering.",
        "freeze_order": "Positive per-target summary_revision allocated in caller UoW; latest frozen summary is the highest revision, not timestamp/UUID order.",
    }
    captured["algorithms/terminal-unlink-orphan.json"]["accepted_owner_clarifications"] = [
        "SR governing event is the accepted status-observation UUID; grace starts at recorded_at_utc, never the possibly old or unknown provider chronology.",
        "RFC grace starts at the accepted local cascade execution time.",
        "RFC governing_event_id is the accepted cascade proposal UUID; LLD-03 supplies its exact accepted_execution_utc through the existing command context, required by Communications apply.",
        "SR apply returns the immutable frozen-summary reference; complete consequences stay relational under the outer command.",
        "Post-purge reversal atomically enqueues exact reconstruction in caller UoW, runnable only after commit; worker revalidates readability. Unproved range or unavailable source leaves frozen evidence and coverage warning.",
    ]
    captured["algorithms/canonical-message-identity.json"]["accepted_conflicting_provider_content"] = (
        "Exact provider identity reuses the canonical ID, but conflicting observed content preserves the retained snapshot and requires reviewed identity reconciliation under COLLISION_REVIEW protection. Exact overlap replays remain unchanged."
    )
    retention_event = next(table for table in captured["schema/orphan-purge.json"]["tables"] if table["name"] == "communication_retention_events")
    aliases = next(table for table in captured["schema/communications.json"]["tables"] if table["name"] == "communication_identity_aliases")
    aliases["columns"].append("alias_evidence_bytes BLOB")
    aliases["rules"] = ["Provider aliases require exact nonempty binary evidence; all alias rows are append-only. Minimized provider keys survive purge."]
    captured["schema/communications.json"]["tables"].extend([
        {"name": "communication_identity_review_evidence", "primary_key": "review_evidence_id TEXT UUID",
         "columns": ["review_evidence_id TEXT NOT NULL", "communication_id TEXT NOT NULL FK communications",
            "source_scope_id TEXT NOT NULL FK communication_source_scopes", "source_revision INTEGER NOT NULL CHECK source_revision>=1",
            "protection_hold_id TEXT NOT NULL FK communication_protection_holds", "provider_identity_kind TEXT NOT NULL",
            "provider_identity_digest TEXT NOT NULL", "provider_identity_bytes BLOB NOT NULL", "fallback_digest TEXT NOT NULL",
            "fallback_canonical_json TEXT", "retained_content_revision INTEGER NOT NULL CHECK retained_content_revision>=1",
            "created_at_utc INTEGER NOT NULL", "decision_event_id TEXT FK communication_identity_review_events"],
         "indexes": ["idx_comm_identity_review_exact(source_scope_id,provider_identity_kind,provider_identity_digest,fallback_digest,review_evidence_id)"]},
        {"name": "communication_identity_review_events", "primary_key": "identity_review_event_id TEXT UUID",
         "columns": ["identity_review_event_id TEXT NOT NULL", "source_scope_id TEXT NOT NULL FK communication_source_scopes",
            "source_revision INTEGER NOT NULL CHECK source_revision>=1", "decision TEXT NOT NULL CHECK in KEEP_SEPARATE,ATTACH_PROVIDER_IDENTITY,CONSOLIDATE_LINKS_AND_ALIASES,KEEP_RETAINED_CONTENT",
            "retained_communication_id TEXT NOT NULL FK communications", "retained_content_revision INTEGER NOT NULL CHECK retained_content_revision>=1",
            "other_communication_id TEXT FK communications", "other_content_revision INTEGER", "review_evidence_id TEXT FK communication_identity_review_evidence",
            "preview_fingerprint TEXT NOT NULL", "closed_link_count INTEGER NOT NULL", "created_link_count INTEGER NOT NULL",
            "attached_alias_count INTEGER NOT NULL", "closed_hold_count INTEGER NOT NULL", "recorded_at_utc INTEGER NOT NULL", "command_id TEXT NOT NULL"],
         "indexes": ["idx_comm_identity_review_history(retained_communication_id,recorded_at_utc DESC,identity_review_event_id DESC)"]},
        {"name": "communication_identity_review_results", "primary_key": "(identity_review_event_id,result_type,result_id)",
         "columns": ["identity_review_event_id TEXT NOT NULL FK communication_identity_review_events", "result_type TEXT NOT NULL", "result_id TEXT NOT NULL"],
         "indexes": []},
        {"name": "communication_identity_review_requests", "primary_key": "job_id TEXT UUID",
         "columns": ["job_id TEXT NOT NULL FK durable_jobs", "requested_command_id TEXT NOT NULL FK command_receipts",
            "execution_command_id TEXT NOT NULL", "request_json TEXT NOT NULL", "preview_fingerprint TEXT NOT NULL"],
         "constraints": ["UNIQUE(execution_command_id)"], "indexes": []},
        {"name": "communication_identity_alias_assignments", "primary_key": "alias_assignment_id TEXT UUID",
         "columns": ["alias_assignment_id TEXT NOT NULL", "source_scope_id TEXT NOT NULL FK communication_source_scopes",
            "provider_identity_kind TEXT NOT NULL", "provider_identity_digest TEXT NOT NULL",
            "identity_alias_id TEXT NOT NULL FK communication_identity_aliases", "identity_review_event_id TEXT NOT NULL FK communication_identity_review_events",
            "assignment_revision INTEGER NOT NULL CHECK assignment_revision>=1"],
         "constraints": ["UNIQUE(source_scope_id,assignment_revision)"],
         "indexes": ["idx_comm_alias_assignment_exact(source_scope_id,provider_identity_kind,provider_identity_digest,assignment_revision DESC)"]},
    ])
    captured["algorithms/canonical-message-identity.json"]["accepted_reviewed_provider_alias"] = (
        "A reviewed provider alias grants reuse of its existing canonical ID only after exact kind/bytes comparison following a digest candidate match; no canonical ID or history is replaced."
    )
    review_fields = {
        "source_scope_id": "uuid", "source_scope_revision": "int>=1; current configuration",
        "decision": "KEEP_SEPARATE|ATTACH_PROVIDER_IDENTITY|CONSOLIDATE_LINKS_AND_ALIASES|KEEP_RETAINED_CONTENT",
        "retained_communication_id": "uuid", "retained_content_revision": "int>=1",
        "other_communication_id": "uuid|null", "other_content_revision": "int>=1|null", "review_evidence_id": "uuid|null",
    }
    captured["types/message.json"]["types"].extend([
        {"name": "CommunicationIdentityReviewRequestV1", "kind": "object", "additionalProperties": False,
         "required": list(review_fields), "properties": review_fields,
         "rules": ["KEEP_RETAINED_CONTENT requires one retained candidate, review_evidence_id and null other candidate/revision; pairwise operations require two distinct candidates and null review_evidence_id."]},
        {"name": "CommunicationIdentityReviewResultV1", "kind": "object", "additionalProperties": False,
         "required": ["status", "identity_review_event_id"],
         "properties": {"status": "APPLIED|NO_CHANGE", "identity_review_event_id": "uuid; immutable review event"}},
    ])
    captured["algorithms/canonical-message-identity.json"]["accepted_content_acknowledgement"] = [
        "KEEP_RETAINED_CONTENT binds current source revision, exact retained content revision, immutable captured evidence and its hold, whether another protected dependency remains and current grace setting in the preview fingerprint. Indexed existence probes bind this complete retention impact without enumerating unrelated siblings.",
        "The decision only closes its own variant hold, records an immutable event and reevaluates retention in one caller receipt/UoW; retained content, identity and content revision do not change.",
        "An already acknowledged exact evidence row with its unchanged retained snapshot yields truthful NO_CHANGE and its original event ref, without new audit or revisions; eligible receipt replay precedes mutable reads.",
        "Captured source revision remains immutable provenance. A current source revision is separately bound at review; keeping existing content grants no acceptance of new content under a changed configuration.",
        "Exact acknowledged variants cannot supply new automatic matching or domain facts for the retained snapshot. Purged evidence cannot authorize a fresh acknowledgement or automatic restoration.",
    ]
    captured["algorithms/canonical-message-identity.json"]["accepted_pairwise_review"] = [
        "ATTACH_PROVIDER_IDENTITY and CONSOLIDATE_LINKS_AND_ALIASES require two retained snapshots and identical complete fallback evidence, not digests alone; KEEP_SEPARATE transfers no identity or links.",
        "A durable reconciliation job stores its immutable closed review request under an owned job-id row; job payload/checkpoint remain scope/counters only, with no repurposed operational target refs or message content.",
        "Provider alias reassignment is append-only and governed by the review event; exact-key lookup uses the highest per-source assignment revision. Canonical IDs and prior aliases survive; outside-pair ownership fails closed.",
        "Pairwise decisions close only generic collision holds, never separate content-variant/proposal/correction/export holds. Consolidation streams donor links, preserves chronology/direction and revalidates current owner eligibility. Retained snapshots and proposals do not move.",
    ]
    captured["types/message.json"]["types"].append({
        "name": "CommunicationIdentityReviewPreviewV1", "kind": "object", "additionalProperties": False,
        "required": ["preview_fingerprint", "closed_link_count", "created_link_count", "attached_alias_count", "closed_hold_count"],
        "properties": {"preview_fingerprint": "sha256", "closed_link_count": "int>=0", "created_link_count": "int>=0",
            "attached_alias_count": "int>=0", "closed_hold_count": "int>=0"},
    })
    captured["implementation/module-map.json"]["commands"].update(
        RequestCommunicationIdentityReconciliation="services/identity_reconciliation.py",
        ApplyCommunicationIdentityReconciliation="services/identity_reconciliation.py",
        DecideCommunicationIdentity="services/identity_review.py",
    )
    captured["implementation/module-map.json"]["queries"].update(
        PreviewCommunicationIdentityReconciliation="services/identity_reconciliation.py",
        PreviewKeepRetainedCommunicationContent="services/identity_review.py",
    )
    retention_event["columns"].append("resulting_retention_revision INTEGER NOT NULL CHECK resulting_retention_revision>=1")
    retention_event["constraints"] = ["UNIQUE(communication_id,resulting_retention_revision)"]
    for item in captured["types/message.json"]["types"]:
        if item["name"] == "TransientMessageV1":
            item["required"].append("internet_message_id")
            item["properties"]["internet_message_id"] = "string|null"
            item["required"].append("direction_conflict")
            item["properties"]["direction_conflict"] = "boolean"
            item["properties"]["independently_distinct_source_item"] = "boolean default false; true only from positive captured adapter evidence, never folder/order/checkpoint-token differences alone"
    captured["migrations/0012-communications.json"].update(
        sequence=16, migration_id="beta_0016_communications", runtime_filename="0016_communications.sql",
    )
    message_schema = captured["schema/communications.json"]["tables"][0]
    message_schema["columns"].extend(["provider_identity_bytes BLOB", "fallback_canonical_json TEXT"])
    message_schema["rules"] = [
        "Digest matches are candidates only; retained identity reuse compares exact provider bytes or complete fallback canonical JSON.",
        "Purge removes fallback_canonical_json with reconstructable content; fallback-only post-purge identity uncertainty requires reviewed reconciliation.",
    ]
    captured["tests/traceability/cross-packet.json"]["migration_edge"]["allocation"] = "spec/lld/migrations.json#sequence=16"
    canonical = captured["interfaces/cross-packet-v2.json"]
    adapter = next(item for item in captured["interfaces.json"]["providers"] if item["name"] == "CommunicationSourceAdapter")
    adapter["methods"].append("compare_checkpoints(lower,upper) -> BEFORE|EQUAL|AFTER|INDETERMINATE; pure own-format token comparison, no content IO")
    for item in canonical["provided"]:
        if item["name"] == "RfcTerminalCommunicationParticipant":
            item["methods"][0] = "preview_terminal_cascade(snapshot,proposal_snapshot,after_key|null,limit<=500) -> RfcTerminalCascadeImpactProviderPageV1"
    for item in [*canonical["consumed"], *captured["interfaces.json"]["providers"]]:
        if item["name"] == "DurableJobCoordinator":
            item["methods"].append("DurableJobMetadataV1 -> read-only versioned metadata projection; state/recorded times/attempt count/retry/cancellation/safe diagnostic; no payload/checkpoint/claim secrets")
        if item["name"] in {"TicketCommunicationIdentityProvider", "TaskObjectiveCommunicationIdentityProvider", "InventoryCommunicationIdentityProvider"}:
            item["methods"] = [method.replace("target_revision,matched_identity)", "target_revision,matched_identity,identity_kind?:keyword)") for method in item["methods"]]
            item["methods"].append("validate_target_revision(reader,target_type,target_id,revision) -> VALID|INVALID|INDETERMINATE")
            item["methods"].extend([
                "lookup_trackable_identifier(reader,exact_value) -> indexed iterator[TrackableIdentityV1]; exact current owner candidate set",
                "current_target_revision(reader,target_type,target_id) -> int>=1|null; read-only owner revision",
                "iter_target_identities(reader,target_type,target_id) -> indexed iterator[TrackableIdentityV1]; same existing owner exports restricted to one target",
            ])
        if item["name"] == "TicketCommunicationIdentityProvider":
            item["methods"].append("RfcTerminalCascadeRfcMembersV1 -> read-only owner projection {proposal_id,proposal_revision,rfc_id,captured_rfc_revision,captured_role}; existing immutable capture membership")
            item["methods"].append("validate_communication_reassociation(reader,target_type,target_id,revision) -> VALID|INVALID|INDETERMINATE; accepted SR terminal/reversal evidence and RFC local cascade state, not provider terminal evidence alone")
            item["methods"].append("accepted_sr_status_event(reader,sr_id,sr_revision,event_id) -> SrCommunicationStatusEvidenceV1|null; exact accepted status observation, current target revision and local acceptance time")
        if item["name"] in {"TaskObjectiveCommunicationIdentityProvider", "InventoryCommunicationIdentityProvider"}:
            item["methods"].append("msg_draft_origin_fingerprint(reader,target_type,target_id,origin_command_id) -> sha256|null; read-only current completed Objective review or new local Spare Request draft context")
        if item["name"] == "InventoryCommunicationIdentityProvider":
            item["methods"].append("resolve_warehouse_receipt_target(reader,exact_sr7,exact_c10) -> WarehouseReceiptTargetV1|null; indexed exact registered pair, unique current submitted membership, exact selected physical unit/open obligation; unresolved requires manual selection, no mutation")
    captured["types/proposal.json"]["types"].append({
        "name": "WarehouseReceiptTargetV1", "kind": "object", "additionalProperties": False,
        "required": ["fault_tag_id", "fault_tag_revision", "membership_id", "membership_revision"],
        "properties": {"fault_tag_id": "uuid", "fault_tag_revision": "int>=1", "membership_id": "uuid", "membership_revision": "int>=1"},
    })
    captured["transitions/communication-retention.json"]["rules"][0] = "elapsed grace uses UTC elapsed whole seconds and configured minutes, never local calendar arithmetic"
    captured["algorithms/canonical-message-identity.json"]["fallback_v1"].update(
        participant_shape=["role", "ordinal", "address", "display_name"],
        from_roles=["FROM", "SENDER"],
        participant_order=["ordinal", "role"],
        attachment_shape=["ordinal", "filename", "size_bytes", "content_sha256"],
        canonical_evidence_max_bytes=1048576,
    )
    captured["types/queries.json"]["types"].append({
        "name": "SourceScopeSummaryV1", "kind": "object", "additionalProperties": False,
        "required": ["source_scope_id", "revision", "display_name", "health_state", "processing_enabled", "selected_folders"],
        "properties": {"source_scope_id": "uuid", "revision": "int>=1", "display_name": "string 1..120",
                       "health_state": "READY|MISSING|LOCKED|CORRUPT|UNSUPPORTED|PARTIAL|UNPROBED",
                       "processing_enabled": "boolean", "selected_folders": "array[SourceFolderV1] 1..64"},
    })
    captured["audit/actions.json"]["actions"].append({
        "action_type": "communications.identity.decided", "action_version": 1,
        "payload_schema": "CommIdentityDecisionAuditV1", "payload_version": 1,
        "target": "identity_review_event_id",
        "payload_fields": ["decision", "source_scope_id", "candidate_count", "closed_link_count", "created_link_count", "attached_alias_count", "closed_hold_count"],
        "forbidden": ["message content", "provider raw identity", "source path"],
    })
    captured["audit/actions.json"]["actions"].append({
        "action_type": "communications.identity.review_required", "action_version": 1,
        "payload_schema": "CommIdentityReviewRequiredAuditV1", "payload_version": 1,
        "target": "communication_id", "payload_fields": ["reason_code", "identity_state", "protection_hold_id"],
        "forbidden": ["message content", "provider raw identity", "source path"],
    })
    captured["audit/actions.json"]["actions"].append({
        "action_type": "communications.orphan_grace.cancelled", "action_version": 1,
        "payload_schema": "CommGraceCancelledAuditV1", "payload_version": 1, "target": "communication_id",
        "payload_fields": ["retention_revision", "reason_code"],
        "forbidden": ["message content", "source path", "provider raw identity"],
    })
    captured["audit/actions.json"]["actions"].append({
        "action_type": "communications.terminal_links.restored", "action_version": 1,
        "payload_schema": "CommTerminalLinksRestoredAuditV1", "payload_version": 1, "target": "terminal_summary_id",
        "payload_fields": ["target_type", "target_id", "governing_event_id", "restored_link_count", "cancelled_grace_count", "reconstruction_required_count"],
        "forbidden": ["message content", "source path", "provider raw identity"],
    })
    captured["types/message.json"]["types"].extend([
        {"name": "SrCommunicationStatusEvidenceV1", "kind": "object", "additionalProperties": False,
         "required": ["terminal", "current", "recorded_at_utc", "command_id", "reviewed_correction"],
         "properties": {"terminal": "boolean", "current": "boolean", "recorded_at_utc": "int64 UTC seconds",
                        "command_id": "uuid", "reviewed_correction": "boolean"}},
        {"name": "CommunicationImpact", "kind": "object", "additionalProperties": False,
         "required": ["target_type", "target_id", "target_revision", "summary", "closed_link_count", "orphaned_communication_count", "impact_fingerprint"],
         "properties": {"target_type": "SERVICE_REQUEST", "target_id": "uuid", "target_revision": "int>=1",
            "summary": "CommunicationEntitySummaryV1", "closed_link_count": "int>=0", "orphaned_communication_count": "int>=0", "impact_fingerprint": "sha256"}},
    ])
    captured["algorithms/matching-retention.json"]["identifier_boundaries"] = {
        "case_sensitive": True, "reject_adjacent_unicode_categories": ["L*", "M*", "N*", "Pc"],
        "unicode_version": "17.0.0", "aliases": "review only",
    }
    captured["algorithms/matching-retention.json"]["registered_match_rules"] = {
        "COMM_EXACT_IDENTIFIER_V1@1": "EXACT_IDENTIFIER; current official identifiers may be AUTO_SAFE after writer validation",
        "COMM_EXACT_ALIAS_V1@1": "EXACT_ALIAS; review required",
        "COMM_REVIEWED_MANUAL_V1@1": "REVIEWED_MANUAL; review required",
    }
    captured["commands/v2/decide-link.json"]["decision_guards"] = {
        "REJECT": "exact proposal revision/fingerprint; no source/target freshness grant needed",
        "ACCEPT": "exact proposal plus fresh retained source evidence and current eligible target/identity",
    }
    job_scope = next(t for t in captured["types/jobs.json"]["types"] if t["name"] == "CommunicationJobScopeV1")
    job_scope["properties"]["source_scope_id"] = "uuid|null; null only for ORPHAN_HOUSEKEEPING"
    job_scope["properties"]["config_revision"] = "int>=1|null; null only for ORPHAN_HOUSEKEEPING"
    job_scope["rules"] = ["ORPHAN_HOUSEKEEPING has null source/revision/bounds and empty folder/target arrays; all other kinds have real source/revision."]
    job_scope["properties"]["target_identity_ids"] = "array[uuid]; existing target UUIDs selecting all current exported identifiers/aliases; each UUID must resolve to exactly one target type"
    for item in captured["types/queries.json"]["types"]:
        if item["name"] == "BackfillPreviewRequestV1":
            item["properties"]["target_identity_ids"] = job_scope["properties"]["target_identity_ids"]
    for item in captured["types/common.json"]["types"]:
        if item["name"] == "StartBackfillRequestV1":
            item["properties"]["target_identity_ids"] = job_scope["properties"]["target_identity_ids"]
    for job in captured["jobs/communication-jobs.json"]["jobs"]:
        policy = job["retry_policy"]
        policy["max_attempts_semantics"] = "total executions including the first"
        if job["job_type"] == "communications.identity_reconciliation":
            policy["retryable"] = ["SOURCE_LOCKED", "IO_TRANSIENT"]
        elif job["job_type"] == "communications.orphan_housekeeping":
            policy["retryable"] = ["PERSISTENCE_BUSY"]
    job_table = next(t for t in captured["schema/coverage-jobs.json"]["tables"] if t["name"] == "communication_job_scopes")
    job_table["columns"] = ["config_revision INTEGER" if c.startswith("config_revision ") else c for c in job_table["columns"]]
    job_table["columns"].append("preview_fingerprint TEXT")
    job_table["columns"].append("execution_config_json TEXT")
    job_table["rules"] = [
        "Deep Scan requires the exact confirmed preview_fingerprint; reviewed backfill records its preview fingerprint.",
        "Deliberate-action proof and session secrets never enter job payload, scope or checkpoint storage.",
        "Mail jobs capture the closed immutable execution_config_json object {adapter_family,adapter_version,overlap_messages,batch_messages}; settings changes affect later jobs, and source revision changes invalidate current work.",
    ]
    detail = next(t for t in captured["types/queries.json"]["types"] if t["name"] == "CommunicationDetailV1")
    detail["required"].append("active_links_next_cursor")
    detail["properties"]["active_links"] = "array[CommunicationLinkSummaryV1] maximum 100"
    detail["properties"]["active_links_next_cursor"] = "CURSOR_V1|null"
    captured["queries/v2/communication-detail.json"]["pagination"] = "First 100 active links plus active_links_next_cursor; continue through ListCommunicationLinks without repeating the body."
    captured["queries/v2/communications.json"]["search_contract"] = {
        "normalization": "trim and collapse whitespace", "syntax": "quoted literal words combined with AND",
        "tokenizer": "FTS5 unicode61", "empty": "no filter", "content": "RETAINED subject/body only",
    }
    query_acceptance = ROOT / "docs/reconciliation/LLD09_QUERY_JOB_CONTRACT_CANDIDATE.md"
    if "Status: ACCEPTED_OWNER_CLARIFICATION" not in query_acceptance.read_text(encoding="utf-8"):
        raise ValueError("Query/job contract requires recorded owner acceptance")
    definitions = {
        "CommunicationListItemV1": {
            "communication_id": "uuid", "source_scope_id": "uuid",
            "identity_state": "PROVIDER_STABLE|FALLBACK|IDENTITY_COLLISION", "chronology": "ChronologyV1",
            "direction": "MessageDirectionV1", "content_state": "RETAINED|PURGED", "subject": "string|null",
            "retention_state": "RETAINED|ORPHAN_PENDING_PURGE|PURGED",
        },
        "AttachmentSummaryV1": {
            "communication_attachment_id": "uuid", "ordinal": "int>=0", "filename": "string|null",
            "mime_type": "string|null", "size_bytes": "int>=0", "sha256": "sha256",
        },
        "CommunicationLinkSummaryV1": {
            "communication_link_id": "uuid", "target_type": "CommunicationTargetTypeV1", "target_id": "uuid",
            "target_revision_at_link": "int>=1", "revision": "int>=1", "origin": "AUTO_SAFE|REVIEWED|MANUAL",
            "direction": "MessageDirectionV1", "effective_chronology": "ChronologyV1",
            "matched_identity_kind": "closed owner-defined string", "matched_identity_value": "string",
            "confidence_basis": "EXACT_IDENTIFIER|EXACT_ALIAS|REVIEWED_MANUAL", "match_rule_id": "string",
            "match_rule_version": "int>=1", "state": "ACTIVE|CLOSED",
        },
        "CommunicationJobSummaryV1": {
            "job_id": "uuid", "source_scope_id": "uuid|null", "job_kind": "Communication job kind",
            "state": "Foundation job state", "phase": "stable_code|null", "counters": "CommunicationJobCountersV1",
            "percentage": "number|null", "created_at_utc": "int64 UTC seconds", "updated_at_utc": "int64 UTC seconds",
            "started_at_utc": "int64 UTC seconds|null", "ended_at_utc": "int64 UTC seconds|null",
            "attempt_count": "int>=0", "next_attempt_at_utc": "int64 UTC seconds|null",
            "cancellation_requested": "boolean", "diagnostic_code": "Foundation stable error code|null",
        },
        "CommunicationLinkQueryV1": {
            "communication_id": "uuid", "state": "ACTIVE|CLOSED|null", "cursor": "CURSOR_V1|null", "limit": "int 1..100",
        },
        "CommunicationLinkPageV1": {"items": "array[CommunicationLinkSummaryV1]", "next_cursor": "CURSOR_V1|null"},
    }
    for name, properties in definitions.items():
        captured["types/queries.json"]["types"].append({
            "name": name, "kind": "object", "additionalProperties": False,
            "required": ["communication_id"] if name == "CommunicationLinkQueryV1" else list(properties),
            "properties": properties,
        })
    captured["queries/v2/communication-links.json"] = {
        "schema": "SOMA-LLD-QUERY-V2", "lld_id": "LLD-09", "name": "ListCommunicationLinks",
        "input_type": "CommunicationLinkQueryV1", "response_type": "CommunicationLinkPageV1",
        "read_consistency": "one LLD-01 read snapshot",
        "ordering": "target_type,target_id,communication_link_id ASC",
        "pagination": {"kind": "keyset CURSOR_V1", "default_limit": 50, "max_limit": 100,
                       "last_key_tuple": ["target_type", "target_id", "communication_link_id"],
                       "filter_fingerprint": "communication_id,state", "null_order": "none"},
        "owner_clarification": str(query_acceptance.relative_to(ROOT)).replace("\\", "/"),
    }
    links = next(t for t in captured["schema/links-proposals.json"]["tables"] if t["name"] == "communication_links")
    links["columns"].append("effective_chronology_source_kind TEXT NOT NULL CHECK in RECEIVED_TIME,SENT_TIME,OTHER_PROVIDER_TIME,UNKNOWN")
    links["indexes"].extend([
        "idx_comm_link_comm_state_order(communication_id,state,target_type,target_id,communication_link_id)",
        "idx_comm_link_comm_order(communication_id,target_type,target_id,communication_link_id)",
    ])
    accepted = json.loads((ROOT / "docs/reconciliation/LLD09_PROPOSAL_CONTRACT_CANDIDATE.json").read_text(encoding="utf-8"))
    if accepted["status"] != "ACCEPTED_OWNER_CLARIFICATION":
        raise ValueError("Proposal contract requires recorded owner acceptance")
    registry = {
        "schema": "SOMA_COMMUNICATIONS_RUNTIME_AUTHORITY_V1",
        "design_sha": DESIGN_SHA,
        "owner_clarification": "docs/reconciliation/LLD09_PROPOSAL_CONTRACT_CANDIDATE.md",
        "query_job_owner_clarification": "docs/reconciliation/LLD09_QUERY_JOB_CONTRACT_CANDIDATE.md",
        "panel_http_owner_clarification": panel_path,
        "packet": packet,
        "leaves": captured,
        "proposal_contracts": accepted,
    }
    destination = ROOT / "src/soma/communications/contracts/registry.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
