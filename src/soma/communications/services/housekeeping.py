from __future__ import annotations

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import loads_canonical_json

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import integer
from soma.communications.contracts.jobs import CommunicationJobCheckpoint, CommunicationJobCounters, CommunicationJobScope
from soma.communications.jobs.communications import JOB_TYPES
from soma.communications.services.retention import has_protected_dependency, record_transition, retention


class HousekeepingService:
    """Internal due-purge owner; never reads an external source or exported file."""

    def __init__(self, connection_factory):
        self._factory = connection_factory
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_communications_audit_registry()))

    def select_due(self, *, now_utc: int, limit: int = 100, after_key: tuple[int, str] | None = None) -> list[dict]:
        integer(now_utc)
        integer(limit, minimum=1, maximum=500)
        seek, values = "", [now_utc]
        if after_key is not None:
            integer(after_key[0])
            require_uuid4(after_key[1])
            seek = " AND (purge_due_utc,communication_id)>(?,?)"
            values.extend(after_key)
        with ReadSnapshot(self._factory) as reader:
            rows = reader.connection.execute(
                "SELECT communication_id,revision,purge_due_utc FROM communication_retention "
                "WHERE state='ORPHAN_PENDING_PURGE' AND purge_due_utc<=?" + seek +
                " ORDER BY purge_due_utc,communication_id LIMIT ?", (*values, limit),
            ).fetchall()
        return [{"communication_id": row[0], "revision": row[1], "purge_due_utc": row[2]} for row in rows]

    def purge_due(self, *, command_id: str, communication_id: str, selected_revision: int, now_utc: int) -> dict:
        return self._purge_due(command_id=command_id, communication_id=communication_id,
                               selected_revision=selected_revision, now_utc=now_utc)

    def purge_due_claim(self, claim, coordinator, *, command_id: str, communication_id: str,
                        selected_revision: int, now_utc: int) -> dict:
        if claim.job_type != JOB_TYPES["ORPHAN_HOUSEKEEPING"] or claim.contract_version != 1:
            raise ValidationError("Housekeeping received another job type")
        return self._purge_due(command_id=command_id, communication_id=communication_id,
            selected_revision=selected_revision, now_utc=now_utc, claim=claim, coordinator=coordinator)

    def _purge_due(self, *, command_id, communication_id, selected_revision, now_utc, claim=None, coordinator=None):
        require_uuid4(command_id)
        require_uuid4(communication_id)
        integer(selected_revision, minimum=1)
        integer(now_utc)
        semantic = {"selected_retention_revision": selected_revision, "now_utc": now_utc}
        if claim is not None:
            semantic["job_id"] = claim.job_id
        envelope = CommandEnvelope(command_id, "PurgeDueCommunicationOrphan", "communication", communication_id, semantic,
                                   base_revisions={"retention": selected_revision})

        def prepare(uow):
            if claim is not None:
                progress = self._claim_progress(uow, claim, coordinator)
            row = retention(uow, communication_id)
            if (row["state"] != "ORPHAN_PENDING_PURGE" or row["revision"] != selected_revision):
                return no_change(row)
            protected = has_protected_dependency(uow, communication_id)
            if not protected and row["purge_due_utc"] > now_utc:
                return no_change(row)
            completed = []

            def apply(inner):
                if protected:
                    transition = record_transition(inner, row, to_state="RETAINED", reason_code="PROTECTED_DEPENDENCY_RESTORED",
                                                   dependency_event_id=row["last_dependency_event_id"], event_time=now_utc,
                                                   command_id=command_id, orphan_since=None, due=None)
                    action = "communications.orphan_grace.cancelled"
                    payload = {"retention_revision": transition.new_revision, "reason_code": "PROTECTED_DEPENDENCY_RESTORED"}
                else:
                    inner.connection.execute(
                        "DELETE FROM communication_attachment_chunks WHERE communication_attachment_id IN "
                        "(SELECT communication_attachment_id FROM communication_attachments WHERE communication_id=?)", (communication_id,))
                    inner.connection.execute("DELETE FROM communication_attachments WHERE communication_id=?", (communication_id,))
                    inner.connection.execute("DELETE FROM communication_participants WHERE communication_id=?", (communication_id,))
                    # The FTS projection trigger removes the contentless row in
                    # this same transaction; identity/minimized history survives.
                    inner.connection.execute(
                        "UPDATE communications SET subject=NULL,body_text=NULL,body_kind='NONE',fallback_canonical_json=NULL,"
                        "content_state='PURGED',content_revision=content_revision+1,updated_at_utc=? WHERE communication_id=?",
                        (now_utc, communication_id))
                    transition = record_transition(inner, row, to_state="PURGED", reason_code="DUE_ORPHAN_PURGE",
                                                   dependency_event_id=row["last_dependency_event_id"], event_time=now_utc,
                                                   command_id=command_id, orphan_since=row["orphan_since_utc"], due=row["purge_due_utc"])
                    action = "communications.orphan_purged"
                    payload = {"retention_revision": transition.new_revision, "prior_link_count": 0,
                               "prior_hold_count": 0, "reason_code": "DUE_ORPHAN_PURGE"}
                completed.append(transition)
                return audit_event(action, command_id=command_id, target_type="communication", target_id=communication_id,
                                   payload=payload, actor_kind="job",
                                   refs=(AuditResultRef("communication", communication_id), AuditResultRef("communication_retention_event", transition.event_id)))

            def response(inner):
                transition = completed[0]
                return {"status": "APPLIED", "target_id": communication_id, "new_revision": transition.new_revision,
                        "result_refs": [{"type": "communication_retention_event", "id": transition.event_id}]}

            def checkpoint(inner):
                scope, counters, revision = progress
                values = counters.to_response()
                values.update(discovered=counters.discovered+1, inspected=counters.inspected+1)
                advanced = CommunicationJobCounters.from_value(values)
                coordinator.checkpoint_in_uow(inner, claim, CommunicationJobCheckpoint(scope, None, advanced, ()).to_response())
                changed = inner.connection.execute("UPDATE communication_job_counters SET discovered=?,inspected=?,revision=revision+1,updated_at_utc=? WHERE job_id=? AND revision=?",
                    (advanced.discovered, advanced.inspected, now_utc, claim.job_id, revision))
                if changed.rowcount != 1:
                    raise IntegrityFailure("Housekeeping counters changed within their writer transaction")

            return PreparedMutation(False, "communication", communication_id, apply,
                                    response_schema="CommunicationMutationResultV1", response_factory=response,
                                    after_audit=None if claim is None else checkpoint)

        def no_change(row):
            return PreparedMutation(True, None, None, response_schema="CommunicationMutationResultV1",
                                    response={"status": "NO_CHANGE", "target_id": communication_id,
                                              "new_revision": row["revision"], "result_refs": []})

        return self._boundary.execute(envelope, prepare).response

    @staticmethod
    def _claim_progress(writer, claim, coordinator):
        committed = coordinator.assert_claim_current(writer, claim)
        def load(value):
            return loads_canonical_json(value, max_bytes=65536, max_depth=8, max_collection_items=512)
        scope = CommunicationJobScope.from_value(load(claim.payload_json))
        owned = writer.connection.execute("SELECT job_kind,scope_json FROM communication_job_scopes WHERE job_id=?", (claim.job_id,)).fetchone()
        if owned != ("ORPHAN_HOUSEKEEPING", claim.payload_json) or scope.job_kind != "ORPHAN_HOUSEKEEPING":
            raise IntegrityFailure("Housekeeping scope disagrees with its immutable Foundation payload")
        row = writer.connection.execute("SELECT discovered,inspected,matched,retained,unchanged,proposed,skipped,warnings,failures,estimated_total,revision FROM communication_job_counters WHERE job_id=?", (claim.job_id,)).fetchone()
        if row is None:
            raise IntegrityFailure("Housekeeping has no owned counters")
        counters = CommunicationJobCounters(*row[:10])
        if committed is not None:
            checkpoint = CommunicationJobCheckpoint.from_value(load(committed))
            if checkpoint.scope != scope or checkpoint.counters != counters:
                raise IntegrityFailure("Housekeeping counters disagree with committed progress")
        elif counters != CommunicationJobCounters():
            raise IntegrityFailure("Housekeeping counters have no committed checkpoint")
        return scope, counters, row[10]
