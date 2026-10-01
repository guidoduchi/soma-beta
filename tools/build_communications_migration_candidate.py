"""Build the unaccepted LLD-09 schema candidate from its captured schema leaves.

Refuses to rewrite a migration already present in the runtime manifest. The SQL
candidate is reviewed/tested before its hash is added to that manifest.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from soma.foundation.queries.jobs import DURABLE_JOB_METADATA_V1_DDL
from soma.tickets.queries.communication_cascade import RFC_TERMINAL_CASCADE_RFC_MEMBERS_V1_DDL
TARGETS = "'SERVICE_REQUEST','SPARE_REQUEST','RMA','RFC','WFM_TASK','OBJECTIVE','FAULT_TAG'"
SCHEMAS = ("source-scopes", "communications", "links-proposals", "coverage-jobs", "orphan-purge", "msg-drafts")


def main() -> None:
    directory = ROOT / "src/soma/migrations"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if any(x["sequence"] >= 16 for x in manifest["migrations"]):
        raise ValueError("Migration 16 is already in the runtime manifest; refusing rewrite")
    authority = json.loads((ROOT / "src/soma/communications/contracts/registry.json").read_text(encoding="utf-8"))["leaves"]
    tables = [t for path in SCHEMAS for t in authority[f"schema/{path}.json"]["tables"]]
    keys = {t["name"]: t["primary_key"].split()[0] for t in tables}
    keys.update(durable_jobs="job_id", command_receipts="command_id")
    output = ["-- LLD-09; pinned design 9a0e8911 plus accepted session clarifications.", "-- Runtime allocation: beta_0016_communications. Accepted prefix 1-15 is unchanged."]
    for table in tables:
        name = table["name"]
        columns = []
        fk_columns = []
        for source in table["columns"]:
            column = source.split()[0]
            if name == "communication_retention" and column == "communication_id":
                source += " FK communications"
            source = source.replace("FK LLD01 durable_jobs", "FK durable_jobs")
            source = source.replace("CHECK closed CommunicationTargetTypeV1", f"CHECK({column} IN ({TARGETS}))")
            source = re.sub(r"CHECK in ([A-Z0-9_,]+)", lambda m: f"CHECK({column} IN (" + ",".join(x if x.isdecimal() else repr(x) for x in m[1].split(",")) + "))", source)
            source = re.sub(r"CHECK in ([a-z_,]+)", lambda m: f"CHECK({column} IN (" + ",".join(repr(x) for x in m[1].split(",")) + "))", source)
            source = re.sub(r"CHECK ([a-z_]+)>=([0-9]+)", r"CHECK(\1>=\2)", source)
            match = re.search(r" FK ([a-z_]+)", source)
            if match:
                parent = match[1]
                source = source[:match.start()] + f" REFERENCES {parent}({keys[parent]}) ON DELETE RESTRICT"
                fk_columns.append(column)
            if column == "command_id":
                source += " REFERENCES command_receipts(command_id) ON DELETE RESTRICT"
                fk_columns.append(column)
            if name == "communication_msg_drafts" and column == "origin_command_id":
                source += " REFERENCES command_receipts(command_id) ON DELETE RESTRICT"
                fk_columns.append(column)
            if source.startswith(column + " INTEGER") and column.endswith("_utc"):
                source += f" CHECK({column} IS NULL OR {column}>=0)"
            if column.endswith("_json"):
                source += f" CHECK({column} IS NULL OR json_valid({column}))"
            columns.append(source)
        if name == "communication_source_scopes":
            columns.append("display_name_folded TEXT NOT NULL")
        if name == "communication_links":
            # Rebuildable ordering projection, maintained from Communications;
            # effective link chronology remains independent business evidence.
            columns.extend(["canonical_chronology_known INTEGER NOT NULL DEFAULT 0 CHECK(canonical_chronology_known IN (0,1))",
                            "canonical_chronology_utc INTEGER"])
        pk = table["primary_key"]
        columns.append("PRIMARY KEY" + pk if pk.startswith("(") else f"PRIMARY KEY({pk.split()[0]})")
        for guard in table.get("constraints", ()):
            if guard.startswith("UNIQUE("):
                columns.append(guard)
        if name == "communication_source_scopes":
            columns.extend(["CHECK(length(display_name) BETWEEN 1 AND 120)", "CHECK(length(current_location) BETWEEN 1 AND 1024)"])
        if name == "communications":
            columns.extend([
                "CHECK((chronology_known=0 AND chronology_utc IS NULL AND chronology_source_kind='UNKNOWN') OR (chronology_known=1 AND chronology_utc IS NOT NULL AND chronology_source_kind IN ('RECEIVED_TIME','SENT_TIME','OTHER_PROVIDER_TIME')))",
                "CHECK(provider_identity_digest IS NULL OR length(provider_identity_digest)=64)",
                "CHECK(fallback_digest IS NULL OR length(fallback_digest)=64)",
                "CHECK(content_state!='PURGED' OR (subject IS NULL AND body_text IS NULL AND body_kind='NONE' AND fallback_canonical_json IS NULL))",
                "CHECK(subject IS NULL OR length(subject)<=2048)", "CHECK(body_text IS NULL OR length(body_text)<=5000000)",
                "CHECK(fallback_canonical_json IS NULL OR length(CAST(fallback_canonical_json AS BLOB))<=1048576)",
            ])
        if name == "communication_links":
            columns.append("CHECK((effective_chronology_known=0 AND effective_chronology_utc IS NULL AND effective_chronology_source_kind='UNKNOWN') OR (effective_chronology_known=1 AND effective_chronology_utc IS NOT NULL AND effective_chronology_source_kind!='UNKNOWN'))")
            columns.append("CHECK((state='ACTIVE' AND closed_at_utc IS NULL) OR (state='CLOSED' AND closed_at_utc IS NOT NULL))")
        if name == "communication_identity_aliases":
            columns.append("CHECK(alias_kind NOT IN ('MAPI_RECORD_KEY','PROVIDER_STABLE_OTHER') OR (normalization_version=1 AND alias_evidence_bytes IS NOT NULL AND length(alias_evidence_bytes)>0))")
        if name == "communication_identity_review_evidence":
            columns.extend(["CHECK(provider_identity_kind IN ('MAPI_RECORD_KEY','PROVIDER_STABLE_OTHER'))", "CHECK(length(provider_identity_bytes)>0)",
                "CHECK(length(provider_identity_digest)=64 AND provider_identity_digest NOT GLOB '*[^0-9a-f]*')",
                "CHECK(length(fallback_digest)=64 AND fallback_digest NOT GLOB '*[^0-9a-f]*')",
                "CHECK(fallback_canonical_json IS NULL OR length(CAST(fallback_canonical_json AS BLOB))<=1048576)"])
        if name == "communication_identity_review_events":
            columns.extend(["CHECK(length(preview_fingerprint)=64 AND preview_fingerprint NOT GLOB '*[^0-9a-f]*')",
                "CHECK(closed_link_count>=0 AND created_link_count>=0 AND attached_alias_count>=0 AND closed_hold_count>=0)",
                "CHECK((other_communication_id IS NULL AND other_content_revision IS NULL) OR (other_communication_id IS NOT NULL AND other_content_revision>=1 AND other_communication_id!=retained_communication_id))",
                "CHECK((decision='KEEP_RETAINED_CONTENT' AND other_communication_id IS NULL AND review_evidence_id IS NOT NULL) OR (decision!='KEEP_RETAINED_CONTENT' AND other_communication_id IS NOT NULL AND review_evidence_id IS NULL))"])
        if name == "communication_identity_review_results":
            columns.append("CHECK(result_type IN ('communication_identity_alias','communication_link_event','communication_retention_event','communication_protection_hold'))")
        if name == "communication_identity_review_requests":
            columns.extend(["CHECK(length(CAST(request_json AS BLOB))<=65536)",
                "CHECK(length(preview_fingerprint)=64 AND preview_fingerprint NOT GLOB '*[^0-9a-f]*')"])
        if name == "communication_identity_alias_assignments":
            columns.extend(["CHECK(provider_identity_kind IN ('MAPI_RECORD_KEY','PROVIDER_STABLE_OTHER'))",
                "CHECK(length(provider_identity_digest)=64 AND provider_identity_digest NOT GLOB '*[^0-9a-f]*')"])
        if name == "communication_retention":
            columns.append("CHECK((state='RETAINED' AND purge_due_utc IS NULL) OR (state='ORPHAN_PENDING_PURGE' AND orphan_since_utc IS NOT NULL AND purge_due_utc IS NOT NULL AND purge_due_utc>orphan_since_utc) OR state='PURGED')")
        if name == "communication_attachment_chunks":
            columns.append("CHECK(length(content)<=1048576)")
        if name == "communication_job_counters":
            columns.extend(f"CHECK({x}>=0)" for x in ("discovered", "inspected", "matched", "retained", "unchanged", "proposed", "skipped", "warnings", "failures"))
            columns.extend(["CHECK(estimated_total IS NULL OR estimated_total>=0)", "CHECK(revision>=1)"])
        if name == "communication_job_cancellation_events":
            columns.append("CHECK((prior_state='running' AND claim_revoked=1 AND cancelled_attempt_ordinal IS NOT NULL AND cancelled_attempt_ordinal>=1) OR (prior_state!='running' AND claim_revoked=0 AND cancelled_attempt_ordinal IS NULL))")
        if name == "communication_job_scopes":
            columns.append("CHECK((job_kind='ORPHAN_HOUSEKEEPING' AND source_scope_id IS NULL AND config_revision IS NULL) OR (job_kind!='ORPHAN_HOUSEKEEPING' AND source_scope_id IS NOT NULL AND config_revision IS NOT NULL AND config_revision>=1))")
            columns.append("CHECK(preview_fingerprint IS NULL OR (length(preview_fingerprint)=64 AND preview_fingerprint NOT GLOB '*[^0-9a-f]*'))")
            columns.append("CHECK(job_kind!='DEEP_SCAN' OR preview_fingerprint IS NOT NULL)")
            columns.append("CHECK((job_kind='ORPHAN_HOUSEKEEPING' AND execution_config_json IS NULL) OR (job_kind!='ORPHAN_HOUSEKEEPING' AND execution_config_json IS NOT NULL))")
        if name == "communication_terminal_summaries":
            columns.extend(["CHECK(received_count>=0 AND sent_count>=0 AND unknown_count>=0)",
                            "CHECK((last_interaction_known=0 AND last_interaction_utc IS NULL AND last_interaction_source_kind='UNKNOWN') OR (last_interaction_known=1 AND last_interaction_utc IS NOT NULL AND last_interaction_source_kind!='UNKNOWN'))"])
        if name == "communication_msg_drafts":
            columns.extend(["CHECK((origin_domain='LLD-05' AND origin_target_type='OBJECTIVE' AND origin_target_id IS NOT NULL) OR (origin_domain='LLD-07' AND origin_target_type='SPARE_REQUEST' AND origin_target_id IS NOT NULL))",
                            "CHECK(template_version>=1 AND length(template_id)<=128 AND length(subject_snapshot)<=2048 AND length(body_snapshot)<=5000000)",
                            "CHECK(length(content_fingerprint)=64 AND content_fingerprint NOT GLOB '*[^0-9a-f]*')"])
        if name == "communication_msg_draft_recipients":
            columns.extend(["CHECK(ordinal BETWEEN 0 AND 1999)", "CHECK(length(address) BETWEEN 1 AND 320)", "CHECK(display_name IS NULL OR length(display_name)<=512)"])
        if name == "communication_msg_draft_exports":
            columns.extend(["CHECK(length(artifact_sha256)=64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*')", "CHECK(artifact_size_bytes>=0)",
                            "CHECK(location_fingerprint IS NULL OR (length(location_fingerprint)=64 AND location_fingerprint NOT GLOB '*[^0-9a-f]*'))"])
        output.append(f"CREATE TABLE {name}(\n    " + ",\n    ".join(columns) + "\n) STRICT;")
        for index in table.get("indexes", ()):
            unique = index.startswith("UNIQUE PARTIAL ")
            spec = index.removeprefix("UNIQUE PARTIAL ")
            index_name, remaining = spec.split("(", 1)
            output.append(f"CREATE {'UNIQUE ' if unique else ''}INDEX {index_name} ON {name}(" + remaining + ";")
        # Leading-prefix indexes cover every declared FK, even when a packet
        # index starts with a different state/filter column.
        for column in fk_columns:
            output.append(f"CREATE INDEX idx_comm_fk_{name}_{column} ON {name}({column});")
        if name == "communication_source_scopes":
            output.append("CREATE INDEX idx_comm_scope_display ON communication_source_scopes(display_name_folded,source_scope_id);")
            output.append("CREATE INDEX idx_comm_scope_health_display ON communication_source_scopes(health_state,display_name_folded,source_scope_id);")
            output.append("CREATE INDEX idx_comm_scope_provider_identity ON communication_source_scopes(adapter_family,scope_identity_kind,scope_identity_value);")
        if name == "communications":
            output.append("CREATE INDEX idx_comm_global_chronology ON communications(chronology_known DESC,chronology_utc DESC,communication_id DESC);")
            output.append("CREATE INDEX idx_comm_scope_chronology_order ON communications(source_scope_id,chronology_known DESC,chronology_utc DESC,communication_id DESC);")
            output.append("CREATE INDEX idx_comm_provider_candidate ON communications(source_scope_id,provider_identity_kind,provider_identity_digest);")
        if name == "communication_links":
            output.append("CREATE INDEX idx_comm_link_target_canonical_order ON communication_links(target_type,target_id,state,canonical_chronology_known DESC,canonical_chronology_utc DESC,communication_id DESC);")
            output.append("CREATE INDEX idx_comm_link_target_event_order ON communication_links(target_type,target_id,state,communication_link_id);")
        if name == "communication_proposals":
            output.append("CREATE INDEX idx_comm_proposal_dependency ON communication_proposals(communication_id,state,communication_proposal_id);")
            output.append("CREATE INDEX idx_comm_proposal_created ON communication_proposals(created_at_utc DESC,communication_proposal_id DESC);")
            output.append("CREATE INDEX idx_comm_proposal_state_created ON communication_proposals(state,created_at_utc DESC,communication_proposal_id DESC);")
            output.append("CREATE INDEX idx_comm_proposal_target_created ON communication_proposals(target_type,target_id,created_at_utc DESC,communication_proposal_id DESC);")
            output.append("CREATE INDEX idx_comm_proposal_target_state_created ON communication_proposals(target_type,target_id,state,created_at_utc DESC,communication_proposal_id DESC);")
            output.append("CREATE INDEX idx_comm_proposal_type_created ON communication_proposals(target_type,created_at_utc DESC,communication_proposal_id DESC);")
            output.append("CREATE INDEX idx_comm_proposal_id_created ON communication_proposals(target_id,created_at_utc DESC,communication_proposal_id DESC);")
            output.append("CREATE INDEX idx_comm_proposal_id_state_created ON communication_proposals(target_id,state,created_at_utc DESC,communication_proposal_id DESC);")
            output.append("CREATE TRIGGER comm_proposal_evidence_immutable BEFORE UPDATE OF communication_id,target_type,target_id,target_revision,proposal_contract_id,proposal_contract_version,payload_json,source_fingerprint,proposal_fingerprint,created_at_utc ON communication_proposals WHEN NEW.communication_id IS NOT OLD.communication_id OR NEW.target_type IS NOT OLD.target_type OR NEW.target_id IS NOT OLD.target_id OR NEW.target_revision IS NOT OLD.target_revision OR NEW.proposal_contract_id IS NOT OLD.proposal_contract_id OR NEW.proposal_contract_version IS NOT OLD.proposal_contract_version OR NEW.payload_json IS NOT OLD.payload_json OR NEW.source_fingerprint IS NOT OLD.source_fingerprint OR NEW.proposal_fingerprint IS NOT OLD.proposal_fingerprint OR NEW.created_at_utc IS NOT OLD.created_at_utc BEGIN SELECT RAISE(ABORT,'Communication proposal evidence is immutable'); END;")
        if name == "communication_msg_drafts":
            output.append("CREATE INDEX idx_msg_draft_target_dependency ON communication_msg_drafts(origin_target_type,origin_target_id);")
            immutable = ('msg_draft_id','origin_domain','origin_command_id','origin_target_type','origin_target_id','template_id','template_version','subject_snapshot','body_format','body_snapshot','content_fingerprint','generated_at_utc')
            output.append("CREATE TRIGGER comm_msg_snapshot_immutable BEFORE UPDATE ON communication_msg_drafts WHEN " + " OR ".join(f"NEW.{column} IS NOT OLD.{column}" for column in immutable) + " BEGIN SELECT RAISE(ABORT,'MSG draft snapshot is immutable'); END;")
        if name in {"communication_msg_draft_recipients", "communication_msg_draft_exports"}:
            for operation in ("UPDATE", "DELETE"):
                output.append(f"CREATE TRIGGER {name}_{operation.lower()}_guard BEFORE {operation} ON {name} BEGIN SELECT RAISE(ABORT,'MSG draft provenance is immutable'); END;")
        if name == "communication_msg_draft_exports":
            output.append("CREATE INDEX idx_msg_export_reuse ON communication_msg_draft_exports(msg_draft_id,artifact_sha256,artifact_size_bytes,location_fingerprint);")
        if name == "communication_msg_draft_recipients":
            # One role-ordered snapshot ordinal gives a constant indexed guard,
            # instead of recounting the recipient collection for every insert.
            output.append("CREATE UNIQUE INDEX idx_msg_recipient_snapshot_order ON communication_msg_draft_recipients(msg_draft_id,ordinal);")
        if name == "communication_historical_coverage_segments":
            output.append("CREATE INDEX idx_comm_hist_state ON communication_historical_coverage_segments(source_scope_id,source_folder_id,state);")
            output.append("CREATE INDEX idx_comm_hist_time_range ON communication_historical_coverage_segments(source_scope_id,source_folder_id,json_extract(lower_bound_json,'$.utc_epoch_seconds'),coverage_segment_id);")
        if name == "communication_job_scopes":
            output.append("CREATE TRIGGER comm_job_scope_immutable BEFORE UPDATE ON communication_job_scopes BEGIN SELECT RAISE(ABORT,'Communication job scope is immutable'); END;")
        if name.endswith("_events") or name in {"communication_terminal_summaries", "communication_identity_aliases", "communication_identity_review_results", "communication_identity_review_requests", "communication_identity_alias_assignments"}:
            for operation in ("UPDATE", "DELETE"):
                output.append(f"CREATE TRIGGER {name}_{operation.lower()}_guard BEFORE {operation} ON {name} BEGIN SELECT RAISE(ABORT,'Communication history is append-only'); END;")
    output.extend([
        "CREATE TRIGGER comm_alias_assignment_insert_guard BEFORE INSERT ON communication_identity_alias_assignments WHEN NOT EXISTS(SELECT 1 FROM communication_identity_aliases a JOIN communications c USING(communication_id) JOIN communication_identity_review_events e ON e.identity_review_event_id=NEW.identity_review_event_id WHERE a.identity_alias_id=NEW.identity_alias_id AND a.alias_kind=NEW.provider_identity_kind AND a.alias_digest=NEW.provider_identity_digest AND a.normalization_version=1 AND c.source_scope_id=NEW.source_scope_id AND e.source_scope_id=NEW.source_scope_id AND e.retained_communication_id=a.communication_id AND e.decision IN ('ATTACH_PROVIDER_IDENTITY','CONSOLIDATE_LINKS_AND_ALIASES')) BEGIN SELECT RAISE(ABORT,'Provider assignment requires exact alias and governing review'); END;",
        "CREATE TRIGGER comm_review_evidence_insert_guard BEFORE INSERT ON communication_identity_review_evidence WHEN NEW.decision_event_id IS NOT NULL OR NEW.fallback_canonical_json IS NULL OR NOT EXISTS(SELECT 1 FROM communications c JOIN communication_source_scopes s USING(source_scope_id) WHERE c.communication_id=NEW.communication_id AND c.source_scope_id=NEW.source_scope_id AND s.revision=NEW.source_revision AND c.content_state='RETAINED' AND c.content_revision=NEW.retained_content_revision) OR NOT EXISTS(SELECT 1 FROM communication_protection_holds h WHERE h.protection_hold_id=NEW.protection_hold_id AND h.communication_id=NEW.communication_id AND h.hold_kind='COLLISION_REVIEW' AND h.state='ACTIVE' AND h.owner_ref=NEW.review_evidence_id) BEGIN SELECT RAISE(ABORT,'Identity review evidence requires its retained snapshot and governed hold'); END;",
        "CREATE TRIGGER comm_review_evidence_identity_guard BEFORE UPDATE OF review_evidence_id,communication_id,source_scope_id,source_revision,protection_hold_id,provider_identity_kind,provider_identity_digest,provider_identity_bytes,fallback_digest,retained_content_revision,created_at_utc ON communication_identity_review_evidence BEGIN SELECT RAISE(ABORT,'Identity review origin evidence is immutable'); END;",
        "CREATE TRIGGER comm_review_evidence_content_guard BEFORE UPDATE OF fallback_canonical_json ON communication_identity_review_evidence WHEN NEW.fallback_canonical_json IS NOT OLD.fallback_canonical_json AND NOT (NEW.fallback_canonical_json IS NULL AND EXISTS(SELECT 1 FROM communications WHERE communication_id=OLD.communication_id AND content_state='PURGED')) BEGIN SELECT RAISE(ABORT,'Identity review content may only be cleared by canonical purge'); END;",
        "CREATE TRIGGER comm_review_evidence_decision_guard BEFORE UPDATE OF decision_event_id ON communication_identity_review_evidence WHEN NEW.decision_event_id IS NOT OLD.decision_event_id AND (OLD.decision_event_id IS NOT NULL OR NOT EXISTS(SELECT 1 FROM communication_identity_review_events e WHERE e.identity_review_event_id=NEW.decision_event_id AND e.decision='KEEP_RETAINED_CONTENT' AND e.review_evidence_id=OLD.review_evidence_id AND e.retained_communication_id=OLD.communication_id AND e.retained_content_revision=OLD.retained_content_revision)) BEGIN SELECT RAISE(ABORT,'Identity review acknowledgement requires its exact immutable decision'); END;",
        "CREATE TRIGGER comm_review_evidence_delete_guard BEFORE DELETE ON communication_identity_review_evidence BEGIN SELECT RAISE(ABORT,'Minimized identity review evidence survives purge'); END;",
        "CREATE TRIGGER comm_review_evidence_purge AFTER UPDATE OF content_state ON communications WHEN NEW.content_state='PURGED' BEGIN UPDATE communication_identity_review_evidence SET fallback_canonical_json=NULL WHERE communication_id=NEW.communication_id; END;",
        DURABLE_JOB_METADATA_V1_DDL.strip(),
        RFC_TERMINAL_CASCADE_RFC_MEMBERS_V1_DDL.strip(),
        "CREATE INDEX idx_comm_job_created ON communication_job_scopes(created_at_utc DESC,job_id DESC);",
        "CREATE INDEX idx_comm_job_kind_created ON communication_job_scopes(job_kind,created_at_utc DESC,job_id DESC);",
        "CREATE INDEX idx_comm_job_source_created ON communication_job_scopes(source_scope_id,created_at_utc DESC,job_id DESC);",
        # Rebuildable run index, containing owner-exported identifiers only.
        # Mail content and unmatched source-item keys never enter these tables.
        "CREATE TABLE communication_match_runs(job_id TEXT PRIMARY KEY REFERENCES communication_job_scopes(job_id) ON DELETE RESTRICT,state TEXT NOT NULL CHECK(state IN ('PREPARING','READY')),registry_fingerprint TEXT CHECK(registry_fingerprint IS NULL OR (length(registry_fingerprint)=64 AND registry_fingerprint NOT GLOB '*[^0-9a-f]*')),identity_count INTEGER NOT NULL DEFAULT 0 CHECK(identity_count>=0),CHECK((state='PREPARING' AND registry_fingerprint IS NULL) OR (state='READY' AND registry_fingerprint IS NOT NULL AND identity_count>0))) STRICT;",
        f"CREATE TABLE communication_match_tokens(job_id TEXT NOT NULL REFERENCES communication_match_runs(job_id) ON DELETE RESTRICT,token TEXT NOT NULL CHECK(length(token) BETWEEN 1 AND 512),target_type TEXT NOT NULL CHECK(target_type IN ({TARGETS})),target_id TEXT NOT NULL,target_revision INTEGER NOT NULL CHECK(target_revision>=1),identity_kind TEXT NOT NULL CHECK(length(identity_kind) BETWEEN 1 AND 128),effective_known INTEGER NOT NULL CHECK(effective_known IN (0,1)),effective_utc INTEGER CHECK(effective_utc IS NULL OR effective_utc>=0),effective_source TEXT NOT NULL CHECK(effective_source IN ('RECEIVED_TIME','SENT_TIME','OTHER_PROVIDER_TIME','UNKNOWN')),export_ordinal INTEGER NOT NULL CHECK(export_ordinal>=0),PRIMARY KEY(job_id,token,target_type,target_id,identity_kind),UNIQUE(job_id,export_ordinal),CHECK((effective_known=0 AND effective_utc IS NULL AND effective_source='UNKNOWN') OR (effective_known=1 AND effective_utc IS NOT NULL AND effective_source!='UNKNOWN'))) STRICT;",
        "CREATE INDEX idx_comm_match_token_order ON communication_match_tokens(job_id,token,export_ordinal);",
        "CREATE INDEX idx_comm_match_job_target ON communication_match_tokens(job_id,target_id,target_type,target_revision);",
        "CREATE INDEX idx_comm_match_target_order ON communication_match_tokens(target_type,target_id,job_id,export_ordinal);",
        "CREATE TABLE communication_match_lengths(job_id TEXT NOT NULL REFERENCES communication_match_runs(job_id) ON DELETE RESTRICT,prefix TEXT NOT NULL,token_length INTEGER NOT NULL CHECK(token_length BETWEEN 1 AND 512),PRIMARY KEY(job_id,prefix,token_length),CHECK(length(prefix)=min(8,token_length))) STRICT;",
        "CREATE TRIGGER comm_match_run_sealed BEFORE UPDATE ON communication_match_runs WHEN OLD.state='READY' BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;",
        *[f"CREATE TRIGGER comm_match_{table}_{op.lower()} BEFORE {op} ON communication_match_{table} WHEN " + " OR ".join(f"(SELECT state FROM communication_match_runs WHERE job_id={image}.job_id)='READY'" for image in (('NEW',) if op=='INSERT' else ('OLD',) if op=='DELETE' else ('OLD','NEW'))) + " BEGIN SELECT RAISE(ABORT,'Communication matching snapshot is immutable'); END;" for table in ('tokens','lengths') for op in ('INSERT','UPDATE','DELETE')],
        "CREATE TRIGGER comm_link_message_immutable BEFORE UPDATE OF communication_id ON communication_links WHEN NEW.communication_id IS NOT OLD.communication_id BEGIN SELECT RAISE(ABORT,'Communication link message identity is immutable'); END;",
        "CREATE TRIGGER comm_link_chronology_insert AFTER INSERT ON communication_links BEGIN UPDATE communication_links SET canonical_chronology_known=(SELECT chronology_known FROM communications WHERE communication_id=NEW.communication_id),canonical_chronology_utc=(SELECT chronology_utc FROM communications WHERE communication_id=NEW.communication_id) WHERE communication_link_id=NEW.communication_link_id; END;",
        "CREATE TRIGGER comm_link_chronology_message_update AFTER UPDATE OF chronology_known,chronology_utc ON communications BEGIN UPDATE communication_links SET canonical_chronology_known=NEW.chronology_known,canonical_chronology_utc=NEW.chronology_utc WHERE communication_id=NEW.communication_id; END;",
        "CREATE TRIGGER comm_link_chronology_projection_guard BEFORE UPDATE OF canonical_chronology_known,canonical_chronology_utc ON communication_links WHEN NEW.canonical_chronology_known IS NOT (SELECT chronology_known FROM communications WHERE communication_id=NEW.communication_id) OR NEW.canonical_chronology_utc IS NOT (SELECT chronology_utc FROM communications WHERE communication_id=NEW.communication_id) BEGIN SELECT RAISE(ABORT,'Communication ordering projection must agree with canonical chronology'); END;",
        "CREATE VIRTUAL TABLE communication_search_fts USING fts5(subject,body,content='',contentless_delete=1);",
        "CREATE TRIGGER comm_search_insert AFTER INSERT ON communications WHEN NEW.content_state='RETAINED' BEGIN INSERT INTO communication_search_fts(rowid,subject,body) VALUES(NEW.rowid,NEW.subject,NEW.body_text); END;",
        "CREATE TRIGGER comm_search_update AFTER UPDATE OF subject,body_text,content_state ON communications BEGIN DELETE FROM communication_search_fts WHERE rowid=OLD.rowid; INSERT INTO communication_search_fts(rowid,subject,body) SELECT NEW.rowid,NEW.subject,NEW.body_text WHERE NEW.content_state='RETAINED'; END;",
        "CREATE TRIGGER comm_search_delete AFTER DELETE ON communications BEGIN DELETE FROM communication_search_fts WHERE rowid=OLD.rowid; END;",
        "CREATE TRIGGER comm_retention_purged_insert_guard BEFORE INSERT ON communication_retention WHEN NEW.state='PURGED' AND NOT EXISTS(SELECT 1 FROM communications WHERE communication_id=NEW.communication_id AND content_state='PURGED') BEGIN SELECT RAISE(ABORT,'Communication content must be purged first'); END;",
        "CREATE TRIGGER comm_retention_purged_update_guard BEFORE UPDATE ON communication_retention WHEN NEW.state='PURGED' AND NOT EXISTS(SELECT 1 FROM communications WHERE communication_id=NEW.communication_id AND content_state='PURGED') BEGIN SELECT RAISE(ABORT,'Communication content must be purged first'); END;",
        "CREATE TRIGGER comm_content_purge_dependencies BEFORE UPDATE OF content_state ON communications WHEN NEW.content_state='PURGED' AND (EXISTS(SELECT 1 FROM communication_links WHERE communication_id=NEW.communication_id AND state='ACTIVE') OR EXISTS(SELECT 1 FROM communication_protection_holds WHERE communication_id=NEW.communication_id AND state='ACTIVE') OR EXISTS(SELECT 1 FROM communication_proposals WHERE communication_id=NEW.communication_id AND state IN ('PENDING','DEFERRED')) OR EXISTS(SELECT 1 FROM communication_participants WHERE communication_id=NEW.communication_id) OR EXISTS(SELECT 1 FROM communication_attachments WHERE communication_id=NEW.communication_id)) BEGIN SELECT RAISE(ABORT,'Communication purge dependencies survive'); END;",
    ])
    (ROOT / "docs/implementation/lld09_migration16_candidate.sql").write_text("\n\n".join(output) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
