from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import loads_strict, sha256_canonical_json
from soma.tickets.audit_registry import build_tickets_audit_registry

Reader = ReadSnapshot | UnitOfWork


class RfcSourceProvenanceProvider(Protocol):
    def has_accepted_source_provenance(self, reader: Reader, rfc_id: str) -> str: ...


class RfcHardDeleteDependencyProvider(Protocol):
    def classify_hard_delete_dependency(self, reader: Reader, rfc_id: str) -> str: ...


_LOCAL_GUARD_CODES = (
    "RFC_CREATION_CONTEXT_NOT_LOCAL",
    "RFC_REVISION_NOT_INITIAL",
    "RFC_ARCHIVE_STATE_NOT_ACTIVE",
    "RFC_SOURCE_PROJECTION_PRESENT",
    "RFC_HIERARCHY_HISTORY_PRESENT",
    "RFC_SR_RELATIONSHIP_HISTORY_PRESENT",
    "RFC_DEVICE_REFERENCE_HISTORY_PRESENT",
    "RFC_WORKING_NOTE_HISTORY_PRESENT",
    "RFC_TERMINAL_CASCADE_HISTORY_PRESENT",
    "RFC_ARCHIVE_HISTORY_PRESENT",
    "RFC_PROTECTED_AUDIT_HISTORY_PRESENT",
)
_PROVIDER_REGISTRY = (
    ("source_evidence", "RFC_SOURCE_PROVENANCE_PRESENT", "RFC_SOURCE_PROVENANCE_INDETERMINATE"),
    ("tasks_objectives", "RFC_TASKS_OBJECTIVES_DEPENDENCY", "RFC_TASKS_OBJECTIVES_INDETERMINATE"),
    ("inventory", "RFC_INVENTORY_DEPENDENCY", "RFC_INVENTORY_INDETERMINATE"),
    ("communications", "RFC_COMMUNICATIONS_DEPENDENCY", "RFC_COMMUNICATIONS_INDETERMINATE"),
)


@dataclass(frozen=True, slots=True)
class RfcHardDeleteBlocker:
    code: str
    source: str


@dataclass(frozen=True, slots=True)
class RfcHardDeleteProviderFreshness:
    status: str
    freshness_token: str


@dataclass(frozen=True, slots=True)
class RfcHardDeletePreview:
    eligible: bool
    rfc_revision: int
    eligibility_fingerprint: str
    blockers: tuple[RfcHardDeleteBlocker, ...]
    provider_freshness: dict[str, RfcHardDeleteProviderFreshness]

    def to_response(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "rfc_revision": self.rfc_revision,
            "eligibility_fingerprint": self.eligibility_fingerprint,
            "blockers": [asdict(blocker) for blocker in self.blockers],
            "provider_freshness": {key: asdict(value) for key, value in self.provider_freshness.items()},
        }


class RfcHardDeleteQueryService:
    """One closed eligibility predicate shared by preview and writer revalidation."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        source_evidence_provider: RfcSourceProvenanceProvider,
        task_participant: RfcHardDeleteDependencyProvider,
        inventory_provider: RfcHardDeleteDependencyProvider,
        communication_participant: RfcHardDeleteDependencyProvider,
    ) -> None:
        self._factory = connection_factory
        self._source = source_evidence_provider
        self._dependencies = (task_participant, inventory_provider, communication_participant)
        self._creation_contract = build_tickets_audit_registry().resolve(
            "ticket.rfc.identity_created_or_adopted", 1
        ).payload_contract

    @staticmethod
    def load_identity(reader: Reader, rfc_id: str) -> tuple[str, int, str]:
        row = reader.connection.execute(
            "SELECT rfc_no,revision,local_archive_state FROM rfcs WHERE rfc_id=?", (rfc_id,)
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        return row[0], row[1], row[2]

    def _creation_context(self, reader: Reader, rfc_id: str, rfc_no: str) -> tuple[str, str | None]:
        rows = reader.connection.execute(
            "SELECT action_version,payload_schema,payload_version,payload_json,audit_event_id FROM audit_events "
            "WHERE target_type='rfc' AND target_id=? "
            "AND action_type='ticket.rfc.identity_created_or_adopted' LIMIT 2", (rfc_id,)
        ).fetchall()
        if len(rows) != 1 or rows[0][:3] != (1, "RfcIdentityAuditV1", 1):
            return "invalid", None
        try:
            payload = self._creation_contract.validate(loads_strict(rows[0][3], max_bytes=16_384))
            context = payload["creation_context"]
            if (
                payload["rfc_id"] != rfc_id
                or payload["rfc_no"] != rfc_no
                or type(payload["resulting_revision"]) is not int
                or payload["resulting_revision"] != 1
                or not isinstance(context, str)
                or context not in {"manual", "provisional", "accepted_source_adoption"}
            ):
                return "invalid", None
            if payload["customer_org_id"] is not None:
                require_uuid4(payload["customer_org_id"])
        except ValidationError:
            return "invalid", None
        return context, rows[0][4] if context in {"manual", "provisional"} else None

    def evaluate(
        self, reader: Reader, *, rfc_id: str, identity: tuple[str, int, str]
    ) -> RfcHardDeletePreview:
        rfc_no, revision, archive_state = identity
        context, permitted_creation_id = self._creation_context(reader, rfc_id, rfc_no)
        # EXISTS keeps each history check bounded without limiting protected history.
        history = reader.connection.execute(
            "SELECT "
            "EXISTS(SELECT 1 FROM rfc_current_source_projection WHERE rfc_id=:id),"
            "EXISTS(SELECT 1 FROM rfc_hierarchy_edges WHERE parent_rfc_id=:id OR child_rfc_id=:id),"
            "EXISTS(SELECT 1 FROM sr_rfc_links WHERE rfc_id=:id),"
            "EXISTS(SELECT 1 FROM rfc_device_reference_links WHERE rfc_id=:id),"
            "(EXISTS(SELECT 1 FROM rfc_working_notes WHERE rfc_id=:id) OR "
            "EXISTS(SELECT 1 FROM audit_events WHERE payload_schema='WorkingNoteAuditV1' "
            "AND payload_version=1 AND json_extract(payload_json,'$.owner_type')='rfc' "
            "AND json_extract(payload_json,'$.owner_id')=:id)),"
            "(EXISTS(SELECT 1 FROM rfc_terminal_cascade_proposals WHERE trigger_rfc_id=:id) OR "
            "EXISTS(SELECT 1 FROM rfc_terminal_cascade_rfc_members WHERE rfc_id=:id) OR "
            "EXISTS(SELECT 1 FROM rfc_terminal_cascade_wfm_members WHERE owning_rfc_id=:id)),"
            "(EXISTS(SELECT 1 FROM rfc_archive_operations WHERE requested_rfc_id=:id) OR "
            "EXISTS(SELECT 1 FROM rfc_archive_operation_members WHERE rfc_id=:id) OR "
            "EXISTS(SELECT 1 FROM rfc_archive_events WHERE rfc_id=:id)),"
            "EXISTS(SELECT 1 FROM audit_events WHERE target_type='rfc' AND target_id=:id "
            "AND (:creation_id IS NULL OR audit_event_id<>:creation_id))",
            {"id": rfc_id, "creation_id": permitted_creation_id},
        ).fetchone()
        local_guards = [
            {"code": code, "status": "BLOCKED" if blocked else "CLEAR"}
            for code, blocked in zip(
                _LOCAL_GUARD_CODES,
                (context not in {"manual", "provisional"}, revision != 1, archive_state != "active", *history),
                strict=True,
            )
        ]
        blockers = [RfcHardDeleteBlocker(guard["code"], "local") for guard in local_guards
                    if guard["status"] == "BLOCKED"]
        statuses = []
        try:
            source_status = self._source.has_accepted_source_provenance(reader, rfc_id)
            statuses.append({"YES": "BLOCKED", "NO": "CLEAR"}.get(source_status, "INDETERMINATE")
                            if isinstance(source_status, str) else "INDETERMINATE")
        except Exception:
            statuses.append("INDETERMINATE")
        for provider in self._dependencies:
            try:
                status = provider.classify_hard_delete_dependency(reader, rfc_id)
                if not isinstance(status, str) or status not in {"CLEAR", "BLOCKED", "INDETERMINATE"}:
                    status = "INDETERMINATE"
            except Exception:
                status = "INDETERMINATE"
            statuses.append(status)
        providers = {}
        for (provider_id, blocked_code, indeterminate_code), status in zip(_PROVIDER_REGISTRY, statuses, strict=True):
            token = sha256_canonical_json({
                "schema": "SOMA_RFC_HARD_DELETE_PROVIDER_CLASSIFICATION_V1",
                "provider_id": provider_id, "rfc_id": rfc_id, "status": status,
            })
            providers[provider_id] = RfcHardDeleteProviderFreshness(status, token)
            if status != "CLEAR":
                blockers.append(RfcHardDeleteBlocker(
                    blocked_code if status == "BLOCKED" else indeterminate_code, provider_id
                ))
        fingerprint = sha256_canonical_json({
            "schema": "SOMA_RFC_HARD_DELETE_ELIGIBILITY_V1",
            "rfc_id": rfc_id, "rfc_no": rfc_no, "rfc_revision": revision,
            "local_archive_state": archive_state, "creation_context": context,
            "local_guards": local_guards,
            "providers": [{"provider_id": key, **asdict(value)} for key, value in providers.items()],
        })
        return RfcHardDeletePreview(not blockers, revision, fingerprint, tuple(blockers), providers)

    def preview(self, *, rfc_id: str) -> RfcHardDeletePreview:
        canonical_id = require_uuid4(rfc_id)
        with ReadSnapshot(self._factory) as snapshot:
            identity = self.load_identity(snapshot, canonical_id)
            return self.evaluate(snapshot, rfc_id=canonical_id, identity=identity)
