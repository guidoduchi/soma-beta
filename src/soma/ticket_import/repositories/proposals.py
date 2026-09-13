from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json


_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_PROPOSAL_KINDS = frozenset(
    {
        "sr_create_or_adopt",
        "sr_source_projection",
        "sr_customer_reconciliation",
        "sr_contact_reconciliation",
        "sr_current_handler_reconciliation",
        "sr_source_disappearance_review",
        "sr_terminal_reversal_review",
        "sr_suspension_regression_review",
        "rfc_create_or_adopt",
        "rfc_source_projection",
        "rfc_customer_reconciliation",
        "sr_rfc_link_candidate",
        "wfm_create_or_adopt",
        "wfm_source_projection",
        "wfm_provisional_rfc",
        "wfm_provisional_eligibility",
        "wfm_plan_reconciliation",
        "wfm_competing_attempt_review",
    }
)
_TARGET_KINDS = frozenset(
    {
        "service_request",
        "rfc",
        "wfm",
        "customer_organization",
        "contact",
        "source_presence",
        "sr_rfc_relationship",
        "task_plan",
        "activity_lineage",
    }
)
_RISK_CLASSES = frozenset({"low", "medium", "high", "blocked"})
_CHANGE_KINDS = frozenset({"create", "set", "clear", "link", "unlink", "adopt", "candidate", "conflict", "absent", "reappear"})
_VALUE_KINDS = frozenset({"none", "text", "controlled", "instant", "duration_seconds", "identity"})
_TEXT_VALUE_KINDS = frozenset({"none", "text", "controlled", "identity"})
_NUMERIC_VALUE_KINDS = frozenset({"instant", "duration_seconds"})


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    proposal_id: str
    import_run_id: str
    evidence_mode: str
    source_observation_id: str | None
    proposal_kind: str
    target_kind: str
    target_internal_id: str | None
    target_business_id: str | None
    risk_class: str
    base_state_token: str
    proposal_fingerprint: str
    proposal_state: str
    revision: int


@dataclass(frozen=True, slots=True)
class ProposalChangeRecord:
    ordinal: int
    field_key: str
    change_kind: str
    value_kind: str
    before_text: str | None
    after_text: str | None
    before_integer: int | None
    after_integer: int | None
    source_observation_field_id: str | None


@dataclass(frozen=True, slots=True)
class PendingProposalWrite:
    import_run_id: str
    evidence_mode: str
    source_observation_id: str | None
    prior_source_observation_id: str | None
    proposal_kind: str
    target_kind: str
    target_internal_id: str | None
    target_business_id: str | None
    risk_class: str
    base_state_token: str
    proposal_fingerprint: str
    changes: tuple[ProposalChangeRecord, ...]


@dataclass(frozen=True, slots=True)
class ProposalPersistenceResult:
    proposal_id: str
    reused: bool


@dataclass(frozen=True, slots=True)
class ImportRunDecisionState:
    import_run_id: str
    source_family: str
    run_state: str
    candidate_chronology_kind: str
    candidate_chronology_value: int
    logical_fingerprint: str
    pending_count: int
    accepted_count: int
    rejected_count: int
    deferred_count: int
    revision: int


def _validate_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _validate_optional_uuid(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{label} must be a canonical UUID4") from exc


def _validate_optional_text(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ValidationError(f"{label} must be NUL-free text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError(f"{label} must be valid Unicode text") from exc
    return value


def _validate_change(change: ProposalChangeRecord, *, expected_ordinal: int) -> ProposalChangeRecord:
    if not isinstance(change, ProposalChangeRecord):
        raise ValidationError("proposal changes must use ProposalChangeRecord")
    if type(change.ordinal) is not int or change.ordinal != expected_ordinal:
        raise ValidationError("proposal change ordinals must be contiguous from zero")
    if not isinstance(change.field_key, str) or not change.field_key or "\x00" in change.field_key:
        raise ValidationError("proposal change field_key must be nonempty NUL-free text")
    try:
        change.field_key.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("proposal change field_key must be valid Unicode text") from exc
    if change.change_kind not in _CHANGE_KINDS:
        raise ValidationError("proposal change_kind is outside the closed LLD-04 vocabulary")
    if change.value_kind not in _VALUE_KINDS:
        raise ValidationError("proposal value_kind is outside the closed LLD-04 vocabulary")
    before_text = _validate_optional_text(change.before_text, label="proposal before_text")
    after_text = _validate_optional_text(change.after_text, label="proposal after_text")
    before_integer = change.before_integer
    after_integer = change.after_integer
    if before_integer is not None and type(before_integer) is not int:
        raise ValidationError("proposal before_integer must be an integer or null")
    if after_integer is not None and type(after_integer) is not int:
        raise ValidationError("proposal after_integer must be an integer or null")
    if change.value_kind in _TEXT_VALUE_KINDS:
        if before_integer is not None or after_integer is not None:
            raise ValidationError("text/identity proposal changes cannot carry integer values")
    elif change.value_kind in _NUMERIC_VALUE_KINDS:
        if before_text is not None or after_text is not None:
            raise ValidationError("instant/duration proposal changes cannot carry text values")
        if (before_integer is not None and before_integer < 0) or (after_integer is not None and after_integer < 0):
            raise ValidationError("instant/duration proposal values must be nonnegative")
    source_field_id = _validate_optional_uuid(
        change.source_observation_field_id,
        label="source_observation_field_id",
    )
    return ProposalChangeRecord(
        ordinal=change.ordinal,
        field_key=change.field_key,
        change_kind=change.change_kind,
        value_kind=change.value_kind,
        before_text=before_text,
        after_text=after_text,
        before_integer=before_integer,
        after_integer=after_integer,
        source_observation_field_id=source_field_id,
    )


def _validate_pending_write(write: PendingProposalWrite) -> PendingProposalWrite:
    if not isinstance(write, PendingProposalWrite):
        raise ValidationError("pending proposal write contract is invalid")
    import_run_id = require_uuid4(write.import_run_id)
    if write.evidence_mode not in {"observed_row", "population_absence"}:
        raise ValidationError("proposal evidence_mode is invalid")
    source_observation_id = _validate_optional_uuid(write.source_observation_id, label="source_observation_id")
    prior_source_observation_id = _validate_optional_uuid(
        write.prior_source_observation_id,
        label="prior_source_observation_id",
    )
    if write.evidence_mode == "observed_row":
        if source_observation_id is None or prior_source_observation_id is not None:
            raise ValidationError("observed-row proposal requires current source observation only")
    else:
        if source_observation_id is not None or prior_source_observation_id is None:
            raise ValidationError("population-absence proposal requires prior source observation only")
    if write.proposal_kind not in _PROPOSAL_KINDS:
        raise ValidationError("proposal_kind is outside the closed LLD-04 vocabulary")
    if (write.proposal_kind == "sr_source_disappearance_review") != (write.evidence_mode == "population_absence"):
        raise ValidationError("source-disappearance proposal evidence mode is invalid")
    if write.target_kind not in _TARGET_KINDS:
        raise ValidationError("target_kind is outside the closed LLD-04 vocabulary")
    target_internal_id = _validate_optional_uuid(write.target_internal_id, label="target_internal_id")
    target_business_id = _validate_optional_text(write.target_business_id, label="target_business_id")
    if write.risk_class not in _RISK_CLASSES:
        raise ValidationError("proposal risk_class is invalid")
    base_state_token = _validate_sha256(write.base_state_token, label="base_state_token")
    proposal_fingerprint = _validate_sha256(write.proposal_fingerprint, label="proposal_fingerprint")
    if not write.changes:
        raise ValidationError("pending proposal requires at least one immutable change")
    changes = tuple(_validate_change(change, expected_ordinal=index) for index, change in enumerate(write.changes))
    return PendingProposalWrite(
        import_run_id=import_run_id,
        evidence_mode=write.evidence_mode,
        source_observation_id=source_observation_id,
        prior_source_observation_id=prior_source_observation_id,
        proposal_kind=write.proposal_kind,
        target_kind=write.target_kind,
        target_internal_id=target_internal_id,
        target_business_id=target_business_id,
        risk_class=write.risk_class,
        base_state_token=base_state_token,
        proposal_fingerprint=proposal_fingerprint,
        changes=changes,
    )


class ProposalRepository:
    @staticmethod
    def get(reader: Any, proposal_id: str) -> ProposalRecord | None:
        row = reader.execute(
            "SELECT reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,proposal_kind,target_kind,"
            "target_internal_id,target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,"
            "proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return ProposalRecord(
            proposal_id=str(row[0]),
            import_run_id=str(row[1]),
            evidence_mode=str(row[2]),
            source_observation_id=None if row[3] is None else str(row[3]),
            proposal_kind=str(row[4]),
            target_kind=str(row[5]),
            target_internal_id=None if row[6] is None else str(row[6]),
            target_business_id=None if row[7] is None else str(row[7]),
            risk_class=str(row[8]),
            base_state_token=str(row[9]),
            proposal_fingerprint=str(row[10]),
            proposal_state=str(row[11]),
            revision=int(row[12]),
        )

    @staticmethod
    def list_changes(reader: Any, proposal_id: str) -> tuple[ProposalChangeRecord, ...]:
        rows = reader.execute(
            "SELECT ordinal,field_key,change_kind,value_kind,before_text,after_text,before_integer,after_integer,"
            "source_observation_field_id FROM reconciliation_proposal_changes "
            "WHERE reconciliation_proposal_id=? ORDER BY ordinal ASC",
            (proposal_id,),
        ).fetchall()
        changes = tuple(
            ProposalChangeRecord(
                ordinal=int(row[0]),
                field_key=str(row[1]),
                change_kind=str(row[2]),
                value_kind=str(row[3]),
                before_text=None if row[4] is None else str(row[4]),
                after_text=None if row[5] is None else str(row[5]),
                before_integer=None if row[6] is None else int(row[6]),
                after_integer=None if row[7] is None else int(row[7]),
                source_observation_field_id=None if row[8] is None else str(row[8]),
            )
            for row in rows
        )
        if any(change.ordinal != ordinal for ordinal, change in enumerate(changes)):
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal change ordinals are no longer contiguous")
        return changes

    @classmethod
    def insert_or_reuse_pending(
        cls,
        uow: UnitOfWork,
        write: PendingProposalWrite,
    ) -> ProposalPersistenceResult:
        pending = _validate_pending_write(write)
        run = uow.connection.execute(
            "SELECT run_state FROM import_runs WHERE import_run_id=?",
            (pending.import_run_id,),
        ).fetchone()
        if run is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "proposal parent import run does not exist")
        if str(run[0]) != "validating":
            raise SomaError("IMPORT_RUN_STALE", "new proposal evidence may only be appended during final validating publication")

        if pending.evidence_mode == "observed_row":
            source = uow.connection.execute(
                "SELECT import_run_id FROM source_observations WHERE source_observation_id=?",
                (pending.source_observation_id,),
            ).fetchone()
            if source is None or str(source[0]) != pending.import_run_id:
                raise SomaError("IMPORT_RUN_STALE", "observed-row proposal evidence is not owned by the validating run")
        else:
            prior = uow.connection.execute(
                "SELECT 1 FROM source_observations WHERE source_observation_id=?",
                (pending.prior_source_observation_id,),
            ).fetchone()
            if prior is None:
                raise SomaError("IMPORT_RUN_STALE", "population-absence proposal prior evidence disappeared")

        support_ids = tuple(
            sorted(
                {
                    change.source_observation_field_id
                    for change in pending.changes
                    if change.source_observation_field_id is not None
                }
            )
        )
        for support_id in support_ids:
            if uow.connection.execute(
                "SELECT 1 FROM source_observation_fields WHERE source_observation_field_id=?",
                (support_id,),
            ).fetchone() is None:
                raise SomaError("IMPORT_RUN_STALE", "proposal support field evidence disappeared")

        rows = uow.connection.execute(
            "SELECT reconciliation_proposal_id FROM reconciliation_proposals "
            "WHERE import_run_id=? AND proposal_state='pending' AND evidence_mode=? "
            "AND source_observation_id IS ? AND prior_source_observation_id IS ? AND proposal_kind=? AND target_kind=? "
            "AND target_internal_id IS ? AND target_business_id IS ? AND risk_class=? "
            "AND base_state_token_sha256=? AND proposal_fingerprint_sha256=? "
            "ORDER BY reconciliation_proposal_id ASC LIMIT 2",
            (
                pending.import_run_id,
                pending.evidence_mode,
                pending.source_observation_id,
                pending.prior_source_observation_id,
                pending.proposal_kind,
                pending.target_kind,
                pending.target_internal_id,
                pending.target_business_id,
                pending.risk_class,
                pending.base_state_token,
                pending.proposal_fingerprint,
            ),
        ).fetchall()
        if len(rows) > 1:
            raise IntegrityFailure("multiple exact pending reconciliation proposals exist for one material input")
        if rows:
            proposal_id = require_uuid4(str(rows[0][0]))
            if cls.list_changes(uow.connection, proposal_id) != pending.changes:
                raise IntegrityFailure("exact pending reconciliation proposal change evidence disagrees with material input")
            return ProposalPersistenceResult(proposal_id=proposal_id, reused=True)

        proposal_id = new_uuid4()
        created_at_utc = utc_epoch_seconds()
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals("
            "reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,prior_source_observation_id,"
            "proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,base_state_token_sha256,"
            "proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'pending',?,1,NULL)",
            (
                proposal_id,
                pending.import_run_id,
                pending.evidence_mode,
                pending.source_observation_id,
                pending.prior_source_observation_id,
                pending.proposal_kind,
                pending.target_kind,
                pending.target_internal_id,
                pending.target_business_id,
                pending.risk_class,
                pending.base_state_token,
                pending.proposal_fingerprint,
                created_at_utc,
            ),
        )
        for change in pending.changes:
            uow.connection.execute(
                "INSERT INTO reconciliation_proposal_changes("
                "reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,before_text,after_text,"
                "before_integer,after_integer,source_observation_field_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    proposal_id,
                    change.ordinal,
                    change.field_key,
                    change.change_kind,
                    change.value_kind,
                    change.before_text,
                    change.after_text,
                    change.before_integer,
                    change.after_integer,
                    change.source_observation_field_id,
                ),
            )
        return ProposalPersistenceResult(proposal_id=proposal_id, reused=False)

    @staticmethod
    def require_pending(reader: Any, proposal_id: str) -> ProposalRecord:
        proposal = ProposalRepository.get(reader, proposal_id)
        if proposal is None:
            raise SomaError("IMPORT_PROPOSAL_NOT_FOUND", "reconciliation proposal does not exist")
        if proposal.proposal_state != "pending":
            raise SomaError("IMPORT_PROPOSAL_STALE", "reconciliation proposal is no longer pending")
        return proposal

    @staticmethod
    def get_run(reader: Any, import_run_id: str) -> ImportRunDecisionState:
        row = reader.execute(
            "SELECT import_run_id,source_family,run_state,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,pending_proposal_count,accepted_proposal_count,rejected_proposal_count,"
            "deferred_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "parent import run does not exist")
        if row[5] is None:
            raise SomaError("IMPORT_RUN_UNPUBLISHED", "proposal parent run is not published")
        return ImportRunDecisionState(
            import_run_id=str(row[0]),
            source_family=str(row[1]),
            run_state=str(row[2]),
            candidate_chronology_kind=str(row[3]),
            candidate_chronology_value=int(row[4]),
            logical_fingerprint=str(row[5]),
            pending_count=int(row[6]),
            accepted_count=int(row[7]),
            rejected_count=int(row[8]),
            deferred_count=int(row[9]),
            revision=int(row[10]),
        )

    @staticmethod
    def material_equivalence_fingerprint(proposal: ProposalRecord) -> str:
        return sha256_canonical_json(
            {
                "schema": "IMPORT_PROPOSAL_EQUIVALENCE_V1",
                "proposal_kind": proposal.proposal_kind,
                "target_kind": proposal.target_kind,
                "target_internal_id": proposal.target_internal_id,
                "target_business_id": proposal.target_business_id,
                "base_state_token": proposal.base_state_token,
                "proposal_fingerprint": proposal.proposal_fingerprint,
            }
        )

    @staticmethod
    def recovery_review_fingerprint(reader: Any, run: ImportRunDecisionState) -> str:
        checkpoint = reader.execute(
            "SELECT accepted_import_run_id,accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
            "accepted_logical_fingerprint_sha256,revision FROM import_source_checkpoints WHERE source_family=?",
            (run.source_family,),
        ).fetchone()
        if checkpoint is None:
            raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "recovery run has no current source checkpoint")
        pending_rows = reader.execute(
            "SELECT reconciliation_proposal_id,revision,base_state_token_sha256,proposal_fingerprint_sha256 "
            "FROM reconciliation_proposals WHERE import_run_id=? AND proposal_state='pending' "
            "ORDER BY reconciliation_proposal_id ASC",
            (run.import_run_id,),
        ).fetchall()
        return sha256_canonical_json(
            {
                "schema": "IMPORT_RECOVERY_REVIEW_V1",
                "run": {
                    "import_run_id": run.import_run_id,
                    "revision": run.revision,
                    "chronology_kind": run.candidate_chronology_kind,
                    "chronology_value": run.candidate_chronology_value,
                    "logical_fingerprint": run.logical_fingerprint,
                },
                "checkpoint": {
                    "import_run_id": str(checkpoint[0]),
                    "revision": int(checkpoint[4]),
                    "chronology_kind": str(checkpoint[1]),
                    "chronology_value": int(checkpoint[2]),
                    "logical_fingerprint": str(checkpoint[3]),
                },
                "pending_proposals": [
                    {
                        "proposal_id": str(row[0]),
                        "revision": int(row[1]),
                        "base_state_token": str(row[2]),
                        "proposal_fingerprint": str(row[3]),
                    }
                    for row in pending_rows
                ],
            }
        )

    @staticmethod
    def require_current_recovery_authorization(reader: Any, run: ImportRunDecisionState) -> None:
        if run.run_state != "recovery_required":
            return
        current_fingerprint = ProposalRepository.recovery_review_fingerprint(reader, run)
        review = reader.execute(
            "SELECT review_fingerprint_sha256,decision FROM import_recovery_reviews "
            "WHERE import_run_id=? ORDER BY review_ordinal DESC LIMIT 1",
            (run.import_run_id,),
        ).fetchone()
        if review is None or str(review[0]) != current_fingerprint or str(review[1]) != "authorized":
            raise SomaError(
                "IMPORT_RECOVERY_REVIEW_STALE",
                "recovery proposal decision requires the latest exact authorized review",
            )

    @staticmethod
    def transition_decision(
        uow: UnitOfWork,
        *,
        proposal: ProposalRecord,
        run: ImportRunDecisionState,
        decision: str,
        decided_at_utc: int,
        disposition_id: str,
        equivalence_id: str,
        reason_category: str,
        command_id: str,
    ) -> None:
        if decision not in {"rejected", "deferred"}:
            raise SomaError("VALIDATION_ERROR", "decision must be rejected or deferred")
        proposal_update = uow.connection.execute(
            "UPDATE reconciliation_proposals SET proposal_state=?,revision=revision+1,decided_at_utc=? "
            "WHERE reconciliation_proposal_id=? AND proposal_state='pending' AND revision=?",
            (decision, decided_at_utc, proposal.proposal_id, proposal.revision),
        )
        if proposal_update.rowcount != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reconciliation proposal changed before decision commit")

        uow.connection.execute(
            "INSERT INTO proposal_dispositions(proposal_disposition_id,reconciliation_proposal_id,decision,proposal_revision,"
            "proposal_fingerprint_sha256,base_state_token_sha256,reason_category,decision_origin,occurred_at_utc,command_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'operator', ?, ?)",
            (
                disposition_id,
                proposal.proposal_id,
                decision,
                proposal.revision,
                proposal.proposal_fingerprint,
                proposal.base_state_token,
                reason_category,
                decided_at_utc,
                command_id,
            ),
        )
        uow.connection.execute(
            "INSERT INTO proposal_equivalence_decisions(proposal_equivalence_decision_id,proposal_kind,target_internal_id,"
            "target_business_id,material_input_fingerprint_sha256,decision,source_proposal_id,created_at_utc,command_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                equivalence_id,
                proposal.proposal_kind,
                proposal.target_internal_id,
                proposal.target_business_id,
                ProposalRepository.material_equivalence_fingerprint(proposal),
                decision,
                proposal.proposal_id,
                decided_at_utc,
                command_id,
            ),
        )

        counter_column = "rejected_proposal_count" if decision == "rejected" else "deferred_proposal_count"
        target_state = "recovery_required" if run.run_state == "recovery_required" else "waiting_review"
        run_update = uow.connection.execute(
            f"UPDATE import_runs SET run_state=?,pending_proposal_count=pending_proposal_count-1,"
            f"{counter_column}={counter_column}+1,revision=revision+1 "
            "WHERE import_run_id=? AND revision=? AND pending_proposal_count>0 AND run_state IN ('staged','waiting_review','recovery_required')",
            (target_state, run.import_run_id, run.revision),
        )
        if run_update.rowcount != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "parent import run changed before proposal decision commit")

    @staticmethod
    def transition_accept(
        uow: UnitOfWork,
        *,
        proposal: ProposalRecord,
        run: ImportRunDecisionState,
        decided_at_utc: int,
        disposition_id: str,
        reason_category: str | None,
        command_id: str,
    ) -> None:
        proposal_update = uow.connection.execute(
            "UPDATE reconciliation_proposals SET proposal_state='accepted',revision=revision+1,decided_at_utc=? "
            "WHERE reconciliation_proposal_id=? AND proposal_state='pending' AND revision=?",
            (decided_at_utc, proposal.proposal_id, proposal.revision),
        )
        if proposal_update.rowcount != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reconciliation proposal changed before acceptance commit")
        uow.connection.execute(
            "INSERT INTO proposal_dispositions(proposal_disposition_id,reconciliation_proposal_id,decision,proposal_revision,"
            "proposal_fingerprint_sha256,base_state_token_sha256,reason_category,decision_origin,occurred_at_utc,command_id) "
            "VALUES (?, ?, 'accepted', ?, ?, ?, ?, 'operator', ?, ?)",
            (
                disposition_id,
                proposal.proposal_id,
                proposal.revision,
                proposal.proposal_fingerprint,
                proposal.base_state_token,
                reason_category,
                decided_at_utc,
                command_id,
            ),
        )
        target_state = "recovery_required" if run.run_state == "recovery_required" else "waiting_review"
        run_update = uow.connection.execute(
            "UPDATE import_runs SET run_state=?,pending_proposal_count=pending_proposal_count-1,"
            "accepted_proposal_count=accepted_proposal_count+1,revision=revision+1 "
            "WHERE import_run_id=? AND revision=? AND pending_proposal_count>0 "
            "AND run_state IN ('staged','waiting_review','recovery_required')",
            (target_state, run.import_run_id, run.revision),
        )
        if run_update.rowcount != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "parent import run changed before proposal acceptance commit")