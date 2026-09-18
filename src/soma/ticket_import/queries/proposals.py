from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.objectives_tasks.services.wfm_import import WfmImportBaseTarget, WfmImportReader
from soma.objectives_tasks.services.wfm_import_reassignment import WfmImportParentReassignmentParticipant
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.rfc_wfm_provisional import RfcWfmProvisionalEligibilityService
from soma.tickets.service_request_import_reader import ServiceRequestImportReader

from ..repositories.proposals import ProposalChangeRecord, ProposalRecord, ProposalRepository
from ..repositories.runs import SourceCheckpointRepository


_PROPOSAL_STATES = ("pending", "accepted", "rejected", "deferred", "superseded", "no_change")
_PROPOSAL_STATE_RANK = {state: rank for rank, state in enumerate(_PROPOSAL_STATES)}
_RISK_CLASSES = ("low", "medium", "high", "blocked")
_RISK_RANK = {risk: rank for rank, risk in enumerate(_RISK_CLASSES)}
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
_PUBLISHED_RUN_STATES = frozenset(
    {
        "staged",
        "waiting_review",
        "partially_accepted",
        "accepted",
        "rejected",
        "noop_pending_checkpoint",
        "noop",
        "recovery_required",
    }
)
_GENERIC_SR_ACCEPT_KINDS = frozenset(
    {
        "sr_create_or_adopt",
        "sr_source_projection",
        "sr_customer_reconciliation",
        "sr_contact_reconciliation",
        "sr_current_handler_reconciliation",
        "sr_source_disappearance_review",
        "sr_terminal_reversal_review",
        "sr_suspension_regression_review",
    }
)
_GENERIC_RFC_ACCEPT_KINDS = frozenset(
    {
        "rfc_create_or_adopt",
        "rfc_source_projection",
        "rfc_customer_reconciliation",
        "sr_rfc_link_candidate",
    }
)
_GENERIC_WFM_ACCEPT_KINDS = frozenset(
    {
        "wfm_create_or_adopt",
        "wfm_source_projection",
        "wfm_provisional_rfc",
        "wfm_provisional_eligibility",
        "wfm_plan_reconciliation",
    }
)
_GENERIC_ACCEPT_KINDS = _GENERIC_SR_ACCEPT_KINDS | _GENERIC_RFC_ACCEPT_KINDS | _GENERIC_WFM_ACCEPT_KINDS
_SR_SOURCE_PROJECTION_KINDS = frozenset(
    {"sr_source_projection", "sr_terminal_reversal_review", "sr_suspension_regression_review"}
)
_TERMINAL_SR_STATUSES = frozenset({"Closed", "Resolved", "Cancelled"})
_PROPOSAL_QUERY_ID = "ListReconciliationProposals"
_PROPOSAL_SORT_ID = "IMPORT_PROPOSAL_STATE_RISK_ID_V1"
_PROPOSAL_FILTER_SCHEMA = "SOMA_IMPORT_PROPOSAL_LIST_FILTER_V1"


@dataclass(frozen=True, slots=True)
class ProposalSummary:
    proposal_id: str
    proposal_kind: str
    target_kind: str
    risk_class: str
    state: str
    proposal_revision: int
    proposal_fingerprint: str
    base_state_token: str
    evidence: dict[str, object]
    state_rank: int
    risk_rank: int

    def to_response(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_kind": self.proposal_kind,
            "target_kind": self.target_kind,
            "risk_class": self.risk_class,
            "state": self.state,
            "proposal_revision": self.proposal_revision,
            "proposal_fingerprint": self.proposal_fingerprint,
            "base_state_token": self.base_state_token,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ProposalPage:
    items: tuple[ProposalSummary, ...]
    next_cursor: dict[str, object] | None

    def to_response(self) -> dict[str, object]:
        return {"items": [item.to_response() for item in self.items], "next_cursor": self.next_cursor}


@dataclass(frozen=True, slots=True)
class ProposalReview:
    proposal: ProposalSummary
    changes: tuple[dict[str, object], ...]
    target_preview: dict[str, object]
    stale: bool
    allowed_dispositions: tuple[str, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "proposal": self.proposal.to_response(),
            "changes": [dict(change) for change in self.changes],
            "target_preview": dict(self.target_preview),
            "stale": self.stale,
            "allowed_dispositions": list(self.allowed_dispositions),
        }


@dataclass(frozen=True, slots=True)
class ImportRecoveryPreview:
    import_run_id: str
    review_fingerprint: str
    classification: str
    candidate: dict[str, object]
    checkpoint: dict[str, object]
    proposal_count: int
    finding_count: int
    allowed_actions: tuple[str, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "import_run_id": self.import_run_id,
            "review_fingerprint": self.review_fingerprint,
            "classification": self.classification,
            "candidate": dict(self.candidate),
            "checkpoint": dict(self.checkpoint),
            "proposal_count": self.proposal_count,
            "finding_count": self.finding_count,
            "allowed_actions": list(self.allowed_actions),
        }


@dataclass(frozen=True, slots=True)
class WfmPlanReviewContext:
    proposal_id: str
    source_plan: dict[str, int]
    operational_plan: dict[str, object] | None
    plan_diff: dict[str, object]
    source_chronology: int | None
    objective_regrouping_consequence: str
    base_state_token: str

    def to_response(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "source_plan": dict(self.source_plan),
            "operational_plan": None if self.operational_plan is None else dict(self.operational_plan),
            "plan_diff": dict(self.plan_diff),
            "source_chronology": self.source_chronology,
            "objective_regrouping_consequence": self.objective_regrouping_consequence,
            "base_state_token": self.base_state_token,
        }


def _proposal_cursor(
    cursor: dict[str, object] | None,
    *,
    filter_fingerprint: str,
) -> tuple[int, int, str] | None:
    if cursor is None:
        return None
    expected_fields = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if not isinstance(cursor, dict) or set(cursor) != expected_fields:
        raise SomaError("IMPORT_CURSOR_INVALID", "proposal cursor fields are invalid")
    if (
        cursor["version"] != 1
        or cursor["query_id"] != _PROPOSAL_QUERY_ID
        or cursor["sort_registry_id"] != _PROPOSAL_SORT_ID
        or cursor["null_order"] != "none"
        or cursor["filter_fingerprint"] != filter_fingerprint
    ):
        raise SomaError("IMPORT_CURSOR_INVALID", "proposal cursor contract is invalid")
    key = cursor["last_key_tuple"]
    if (
        not isinstance(key, list)
        or len(key) != 3
        or type(key[0]) is not int
        or key[0] not in _PROPOSAL_STATE_RANK.values()
        or type(key[1]) is not int
        or key[1] not in _RISK_RANK.values()
    ):
        raise SomaError("IMPORT_CURSOR_INVALID", "proposal cursor key is invalid")
    try:
        proposal_id = require_uuid4(str(key[2]))
    except ValidationError as exc:
        raise SomaError("IMPORT_CURSOR_INVALID", "proposal cursor key is invalid") from exc
    return int(key[0]), int(key[1]), proposal_id


def _page_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError("proposal page size must be an integer from 1 through 100")
    return limit


def _proposal_summary_from_row(row: Any) -> ProposalSummary:
    state = str(row[11])
    risk = str(row[8])
    state_rank = int(row[13])
    risk_rank = int(row[14])
    if _PROPOSAL_STATE_RANK.get(state) != state_rank:
        raise IntegrityFailure("persisted proposal state is outside the closed rank vocabulary")
    if _RISK_RANK.get(risk) != risk_rank:
        raise IntegrityFailure("persisted proposal risk is outside the closed rank vocabulary")
    mode = str(row[2])
    if mode not in {"observed_row", "population_absence"}:
        raise IntegrityFailure("persisted proposal evidence mode is invalid")
    source_observation_id = None if row[3] is None else require_uuid4(str(row[3]))
    prior_source_observation_id = None if row[4] is None else require_uuid4(str(row[4]))
    if (mode == "observed_row") != (source_observation_id is not None and prior_source_observation_id is None):
        raise IntegrityFailure("persisted proposal observed-row evidence binding is invalid")
    if (mode == "population_absence") != (source_observation_id is None and prior_source_observation_id is not None):
        raise IntegrityFailure("persisted proposal population-absence evidence binding is invalid")
    return ProposalSummary(
        proposal_id=require_uuid4(str(row[0])),
        proposal_kind=str(row[5]),
        target_kind=str(row[6]),
        risk_class=risk,
        state=state,
        proposal_revision=int(row[12]),
        proposal_fingerprint=str(row[10]),
        base_state_token=str(row[9]),
        evidence={
            "mode": mode,
            "import_run_id": require_uuid4(str(row[1])),
            "source_observation_id": source_observation_id,
            "prior_source_observation_id": prior_source_observation_id,
        },
        state_rank=state_rank,
        risk_rank=risk_rank,
    )


def _typed_change(change: ProposalChangeRecord) -> dict[str, object]:
    if change.value_kind in {"instant", "duration_seconds"}:
        before: object = change.before_integer
        after: object = change.after_integer
    else:
        before = change.before_text
        after = change.after_text
    return {
        "ordinal": change.ordinal,
        "field_key": change.field_key,
        "change_kind": change.change_kind,
        "value_kind": change.value_kind,
        "before": before,
        "after": after,
        "source_observation_field_id": change.source_observation_field_id,
    }


def _run_review_authorized(reader: Any, import_run_id: str) -> bool:
    row = reader.execute("SELECT run_state FROM import_runs WHERE import_run_id=?", (import_run_id,)).fetchone()
    if row is None:
        raise IntegrityFailure("proposal parent import run disappeared")
    state = str(row[0])
    if state not in {"staged", "waiting_review", "recovery_required"}:
        return False
    if state != "recovery_required":
        return True
    run = ProposalRepository.get_run(reader, import_run_id)
    fingerprint = ProposalRepository.recovery_review_fingerprint(reader, run)
    review = reader.execute(
        "SELECT review_fingerprint_sha256,decision FROM import_recovery_reviews "
        "WHERE import_run_id=? ORDER BY review_ordinal DESC LIMIT 1",
        (import_run_id,),
    ).fetchone()
    return bool(review is not None and str(review[0]) == fingerprint and str(review[1]) == "authorized")


def _current_sr_status_is_terminal(reader: Any, service_request_id: str) -> bool:
    row = reader.execute(
        "SELECT o.value_state,o.value_kind,o.text_value FROM sr_current_source_projection p "
        "JOIN sr_source_field_observations o ON o.sr_source_field_observation_id=p.status_observation_id "
        "WHERE p.service_request_id=?",
        (service_request_id,),
    ).fetchone()
    if row is None:
        return False
    if str(row[0]) != "usable" or str(row[1]) != "controlled" or row[2] is None:
        raise IntegrityFailure("current Service Request Status projection is invalid")
    return str(row[2]) in _TERMINAL_SR_STATUSES


def _reviewed_sr_correction_materiality_current(
    reader: Any,
    proposal: ProposalRecord,
    changes: tuple[ProposalChangeRecord, ...],
) -> bool:
    if proposal.proposal_kind not in {"sr_terminal_reversal_review", "sr_suspension_regression_review"}:
        return True
    if proposal.risk_class != "high" or proposal.target_internal_id is None or len(changes) != 1:
        return False
    change = changes[0]
    if proposal.proposal_kind == "sr_terminal_reversal_review":
        if (
            change.field_key != "status"
            or change.change_kind != "set"
            or change.value_kind != "controlled"
            or change.before_text is None
            or change.after_text is None
            or change.before_integer is not None
            or change.after_integer is not None
            or change.source_observation_field_id is None
            or change.after_text in _TERMINAL_SR_STATUSES
        ):
            return False
        row = reader.execute(
            "SELECT o.value_state,o.value_kind,o.text_value FROM sr_current_source_projection p "
            "JOIN sr_source_field_observations o ON o.sr_source_field_observation_id=p.status_observation_id "
            "WHERE p.service_request_id=?",
            (proposal.target_internal_id,),
        ).fetchone()
        return bool(
            row is not None
            and str(row[0]) == "usable"
            and str(row[1]) == "controlled"
            and row[2] is not None
            and str(row[2]) in _TERMINAL_SR_STATUSES
            and str(row[2]) == change.before_text
        )

    if (
        change.field_key != "suspension_duration"
        or change.change_kind != "set"
        or change.value_kind != "duration_seconds"
        or change.before_text is not None
        or change.after_text is not None
        or type(change.before_integer) is not int
        or change.before_integer <= 0
        or change.after_integer != 0
        or change.source_observation_field_id is None
    ):
        return False
    row = reader.execute(
        "SELECT o.value_state,o.value_kind,o.integer_value FROM sr_current_source_projection p "
        "JOIN sr_source_field_observations o "
        "ON o.sr_source_field_observation_id=p.suspension_duration_observation_id "
        "WHERE p.service_request_id=?",
        (proposal.target_internal_id,),
    ).fetchone()
    return bool(
        row is not None
        and str(row[0]) == "usable"
        and str(row[1]) == "duration_seconds"
        and type(row[2]) is int
        and int(row[2]) > 0
        and int(row[2]) == change.before_integer
    )


def _source_projection_shape_current(
    reader: Any,
    proposal: ProposalRecord,
    changes: tuple[ProposalChangeRecord, ...],
) -> bool:
    if not changes or len(changes) > 11:
        return False
    if len({change.field_key for change in changes}) != len(changes):
        return False
    if proposal.proposal_kind in {"sr_terminal_reversal_review", "sr_suspension_regression_review"}:
        return _reviewed_sr_correction_materiality_current(reader, proposal, changes)
    terminal_target = next(
        (
            change
            for change in changes
            if change.field_key == "status" and change.after_text in _TERMINAL_SR_STATUSES
        ),
        None,
    )
    if terminal_target is None or proposal.target_internal_id is None:
        return True
    if _current_sr_status_is_terminal(reader, proposal.target_internal_id):
        return True
    return proposal.risk_class == "high" and len(changes) == 1


def _sr_target_preview(
    reader: Any,
    proposal: ProposalRecord,
    changes: tuple[ProposalChangeRecord, ...],
) -> tuple[dict[str, object], str | None, bool]:
    sr_reader = ServiceRequestImportReader()
    kind = proposal.proposal_kind
    business_id = proposal.target_business_id
    internal_id = proposal.target_internal_id
    if business_id is None:
        return ({"owner": "LLD-03", "preview_available": False}, None, False)

    if kind == "sr_create_or_adopt":
        current = sr_reader.get_by_official(reader, business_id)
        token = sr_reader.source_identity_base_token(reader, business_id)
        binding_current = current is None if internal_id is None else bool(current and current["service_request_id"] == internal_id)
        return (
            {
                "owner": "LLD-03",
                "target_kind": "service_request",
                "official_sr_no": business_id,
                "identity": current,
            },
            token,
            binding_current,
        )

    if internal_id is None:
        return (
            {
                "owner": "LLD-03",
                "target_kind": "service_request",
                "official_sr_no": business_id,
                "preview_available": False,
            },
            None,
            False,
        )
    current = sr_reader.get_by_official(reader, business_id)
    binding_current = bool(current and current["service_request_id"] == internal_id)

    if kind in _SR_SOURCE_PROJECTION_KINDS:
        try:
            projection = sr_reader.current_source_projection(reader, internal_id)
            field_keys = tuple(change.field_key for change in changes)
            token = sr_reader.source_field_set_base_token(reader, internal_id, field_keys)
        except (SomaError, ValidationError):
            projection = None
            token = None
        shape_current = _source_projection_shape_current(reader, proposal, changes)
        return (
            {
                "owner": "LLD-03",
                "target_kind": "service_request",
                "identity": current,
                "current_source_projection": projection,
            },
            token,
            binding_current and shape_current,
        )

    if kind == "sr_customer_reconciliation":
        try:
            references = sr_reader.current_reference_context(reader, internal_id)
            target_customer_id = changes[0].after_text if len(changes) == 1 else None
            token = (
                None
                if target_customer_id is None
                else sr_reader.customer_reconciliation_base_token(reader, internal_id, target_customer_id)
            )
        except SomaError:
            references = None
            token = None
        return (
            {
                "owner": "LLD-03",
                "target_kind": "service_request",
                "identity": current,
                "current_reference_context": references,
            },
            token,
            binding_current,
        )

    if kind in {"sr_contact_reconciliation", "sr_current_handler_reconciliation"}:
        reference_role = "customer_contact" if kind == "sr_contact_reconciliation" else "current_handler_reference"
        try:
            references = sr_reader.current_reference_context(reader, internal_id)
            change = changes[0] if len(changes) == 1 else None
            token = (
                None
                if change is None or change.after_text is None or change.source_observation_field_id is None
                else sr_reader.contact_reconciliation_base_token(
                    reader,
                    internal_id,
                    reference_role,
                    change.after_text,
                    change.source_observation_field_id,
                )
            )
        except SomaError:
            references = None
            token = None
        return (
            {
                "owner": "LLD-03",
                "target_kind": "service_request",
                "identity": current,
                "reference_role": reference_role,
                "current_reference_context": references,
            },
            token,
            binding_current,
        )

    if kind == "sr_source_disappearance_review":
        try:
            presence = sr_reader.current_source_presence(reader, internal_id, "advanced_search_sr")
            token = sr_reader.source_presence_base_token(reader, internal_id, "advanced_search_sr")
            presence_preview: dict[str, object] | None = {
                "source_family": presence.source_family,
                "latest_event_id": presence.latest_event_id,
                "latest_event_kind": presence.latest_event_kind,
                "active_disappearance_event_id": presence.active_disappearance_event_id,
                "warning_active": presence.warning_active,
            }
        except SomaError:
            presence_preview = None
            token = None
        return (
            {
                "owner": "LLD-03",
                "target_kind": "source_presence",
                "identity": current,
                "current_source_presence": presence_preview,
            },
            token,
            binding_current,
        )

    return (
        {
            "owner": "LLD-03",
            "target_kind": proposal.target_kind,
            "target_internal_id": internal_id,
            "target_business_id": business_id,
            "preview_available": False,
        },
        None,
        False,
    )


def _rfc_target_preview(
    reader: Any,
    proposal: ProposalRecord,
    changes: tuple[ProposalChangeRecord, ...],
) -> tuple[dict[str, object], str | None, bool]:
    authority = RfcImportReader()
    kind = proposal.proposal_kind
    business_id = proposal.target_business_id
    internal_id = proposal.target_internal_id
    if business_id is None:
        return ({"owner": "LLD-03", "preview_available": False}, None, False)

    if kind == "rfc_create_or_adopt":
        current = authority.get_by_number(reader, business_id)
        token = RfcImportMutationService.source_identity_base_token(reader, business_id)
        binding = current is None if internal_id is None else bool(current and current.get("rfc_id") == internal_id)
        return (
            {
                "owner": "LLD-03",
                "target_kind": "rfc",
                "rfc_no": business_id,
                "identity": current,
            },
            token,
            binding,
        )

    current = authority.get_by_number(reader, business_id)
    binding = bool(current and internal_id is not None and current.get("rfc_id") == internal_id)
    if not binding or internal_id is None:
        return (
            {
                "owner": "LLD-03",
                "target_kind": proposal.target_kind,
                "rfc_no": business_id,
                "identity": current,
            },
            None,
            False,
        )

    if kind == "rfc_source_projection":
        token = authority.source_acceptance_base_token(reader, internal_id)
        return (
            {
                "owner": "LLD-03",
                "target_kind": "rfc",
                "identity": current,
                "current_source_projection": authority.current_source_projection(reader, internal_id),
            },
            token,
            True,
        )

    if kind == "rfc_customer_reconciliation":
        change = changes[0] if len(changes) == 1 else None
        if (
            change is None
            or change.field_key != "customer_org_id"
            or change.after_text is None
        ):
            return ({"owner": "LLD-03", "identity": current}, None, False)
        token = RfcImportMutationService.customer_reconciliation_base_token(
            reader,
            internal_id,
            change.after_text,
        )
        return (
            {
                "owner": "LLD-03",
                "target_kind": "rfc",
                "identity": current,
                "candidate_customer_org_id": change.after_text,
            },
            token,
            True,
        )

    if kind == "sr_rfc_link_candidate":
        change = changes[0] if len(changes) == 1 else None
        if (
            change is None
            or change.field_key != "service_request_id"
            or change.after_text is None
        ):
            return ({"owner": "LLD-03", "identity": current}, None, False)
        sr_row = reader.execute(
            "SELECT official_sr_no FROM service_requests WHERE service_request_id=?",
            (change.after_text,),
        ).fetchone()
        if sr_row is None:
            return (
                {
                    "owner": "LLD-03",
                    "target_kind": "sr_rfc_relationship",
                    "identity": current,
                    "candidate_service_request_id": change.after_text,
                },
                None,
                False,
            )
        sr = ServiceRequestImportReader().get_by_official(reader, str(sr_row[0]))
        if sr is None or sr.get("service_request_id") != change.after_text:
            raise IntegrityFailure("SR-link review preview resolved mismatched Service Request authority")
        context = RfcImportMutationService.sr_link_candidate_context(
            reader,
            change.after_text,
            internal_id,
        )
        return (
            {
                "owner": "LLD-03",
                "target_kind": "sr_rfc_relationship",
                "identity": current,
                "candidate_service_request": sr,
                "duplicate_active": context.duplicate_active,
                "risk_class": context.risk_class,
            },
            context.base_state_token,
            not context.duplicate_active,
        )

    return ({"owner": "LLD-03", "identity": current}, None, False)


def _wfm_target_preview(
    reader: Any,
    proposal: ProposalRecord,
    changes: tuple[ProposalChangeRecord, ...],
) -> tuple[dict[str, object], str | None, bool]:
    kind = proposal.proposal_kind
    task_no = proposal.target_business_id
    task_id = proposal.target_internal_id

    if kind == "wfm_provisional_rfc":
        if task_no is None:
            return ({"owner": "LLD-03", "preview_available": False}, None, False)
        current = RfcImportReader().get_by_number(reader, task_no)
        token = RfcImportMutationService.source_identity_base_token(reader, task_no)
        return (
            {
                "owner": "LLD-03",
                "target_kind": "rfc",
                "rfc_no": task_no,
                "identity": current,
            },
            token,
            current is None,
        )

    if kind == "wfm_provisional_eligibility":
        if task_no is None:
            return ({"owner": "LLD-03", "preview_available": False}, None, False)
        current = RfcImportReader().get_by_number(reader, task_no)
        token = RfcWfmProvisionalEligibilityService.base_state_token(reader, task_no)
        binding = current is not None and (task_id is None or current.get("rfc_id") == task_id)
        projection = None
        if current is not None and isinstance(current.get("rfc_id"), str):
            projection = RfcImportReader().current_source_projection(reader, str(current["rfc_id"]))
        return (
            {
                "owner": "LLD-03",
                "target_kind": "rfc",
                "rfc_no": task_no,
                "identity": current,
                "current_source_projection": projection,
            },
            token,
            binding,
        )

    if task_no is None:
        return ({"owner": "LLD-05", "preview_available": False}, None, False)

    identity = WfmImportReader.get_by_task_no(reader, task_no)
    status = WfmImportReader.task_no_status(reader, task_no)

    if kind == "wfm_create_or_adopt":
        if task_id is None:
            token = WfmImportReader.source_acceptance_base_token(
                reader,
                WfmImportBaseTarget(kind, task_no, None),
            )
            return (
                {
                    "owner": "LLD-05",
                    "target_kind": "wfm",
                    "task_no": task_no,
                    "task_no_status": status,
                    "identity": identity,
                },
                token,
                status == "ABSENT" and identity is None,
            )

        source = reader.execute(
            "SELECT canonical_parent_rfc_no FROM source_observations "
            "WHERE source_observation_id=? AND import_run_id=?",
            (proposal.source_observation_id, proposal.import_run_id),
        ).fetchone()
        if source is None or source[0] is None:
            return ({"owner": "LLD-05", "identity": identity}, None, False)
        parent = RfcImportReader().get_by_number(reader, str(source[0]))
        if parent is None or not isinstance(parent.get("rfc_id"), str):
            return ({"owner": "LLD-05", "identity": identity}, None, False)
        token = WfmImportParentReassignmentParticipant.base_state_token(
            reader,
            task_no=task_no,
            task_id=task_id,
            new_rfc_id=str(parent["rfc_id"]),
        )
        return (
            {
                "owner": "LLD-05",
                "target_kind": "wfm",
                "task_no_status": status,
                "identity": identity,
                "reviewed_parent_rfc": parent,
            },
            token,
            bool(identity is not None and identity.get("task_id") == task_id and status == "ACTIVE"),
        )

    if task_id is None or identity is None or identity.get("task_id") != task_id or status != "ACTIVE":
        return (
            {
                "owner": "LLD-05",
                "target_kind": proposal.target_kind,
                "task_no_status": status,
                "identity": identity,
            },
            None,
            False,
        )

    if kind in {"wfm_source_projection", "wfm_plan_reconciliation"}:
        token = WfmImportReader.source_acceptance_base_token(
            reader,
            WfmImportBaseTarget(kind, task_no, task_id),
        )
        preview = {
            "owner": "LLD-05",
            "target_kind": proposal.target_kind,
            "task_no_status": status,
            "identity": identity,
            "current_source_projection": WfmImportReader.source_projection(reader, task_id),
        }
        if kind == "wfm_plan_reconciliation":
            preview["source_plan"] = WfmImportReader.source_plan(reader, task_id)
            preview["operational_plan"] = WfmImportReader.operational_plan_context(reader, task_id)
        return (preview, token, True)

    return (
        {
            "owner": "LLD-05",
            "target_kind": proposal.target_kind,
            "task_no_status": status,
            "identity": identity,
        },
        None,
        False,
    )


def _plan_diff(
    source_plan: dict[str, int],
    operational_plan: dict[str, object] | None,
) -> dict[str, object]:
    source_start = source_plan.get("start_utc")
    source_end = source_plan.get("end_utc")
    if type(source_start) is not int or type(source_end) is not int or source_start < 0 or source_end <= source_start:
        raise IntegrityFailure("WFM source plan projection is invalid")

    operational_start: int | None = None
    operational_end: int | None = None
    if operational_plan is not None:
        start = operational_plan.get("start_utc")
        end = operational_plan.get("end_utc")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise IntegrityFailure("WFM operational plan projection is invalid")
        operational_start = start
        operational_end = end

    return {
        "start": {
            "source_utc": source_start,
            "operational_utc": operational_start,
            "changed": source_start != operational_start,
        },
        "end": {
            "source_utc": source_end,
            "operational_utc": operational_end,
            "changed": source_end != operational_end,
        },
    }


class ProposalQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = ProposalRepository()

    def list_proposals(
        self,
        import_run_id: str,
        *,
        state: str | None = None,
        risk: str | None = None,
        kind: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> ProposalPage:
        run_id = require_uuid4(import_run_id)
        if state is not None and state not in _PROPOSAL_STATE_RANK:
            raise ValidationError("proposal state is outside the closed vocabulary")
        if risk is not None and risk not in _RISK_RANK:
            raise ValidationError("proposal risk is outside the closed vocabulary")
        if kind is not None and kind not in _PROPOSAL_KINDS:
            raise ValidationError("proposal kind is outside the closed vocabulary")
        page_limit = _page_limit(limit)
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": _PROPOSAL_FILTER_SCHEMA,
                "import_run_id": run_id,
                "state": state,
                "risk": risk,
                "kind": kind,
            }
        )
        after = _proposal_cursor(cursor, filter_fingerprint=filter_fingerprint)
        state_case = (
            "CASE proposal_state WHEN 'pending' THEN 0 WHEN 'accepted' THEN 1 WHEN 'rejected' THEN 2 "
            "WHEN 'deferred' THEN 3 WHEN 'superseded' THEN 4 WHEN 'no_change' THEN 5 ELSE 99 END"
        )
        risk_case = (
            "CASE risk_class WHEN 'low' THEN 0 WHEN 'medium' THEN 1 WHEN 'high' THEN 2 "
            "WHEN 'blocked' THEN 3 ELSE 99 END"
        )
        predicates = ["import_run_id=?"]
        parameters: list[object] = [run_id]
        if state is not None:
            predicates.append("proposal_state=?")
            parameters.append(state)
        if risk is not None:
            predicates.append("risk_class=?")
            parameters.append(risk)
        if kind is not None:
            predicates.append("proposal_kind=?")
            parameters.append(kind)
        where = " AND ".join(predicates)

        with ReadSnapshot(self._factory) as snapshot:
            run = snapshot.connection.execute("SELECT run_state FROM import_runs WHERE import_run_id=?", (run_id,)).fetchone()
            if run is None:
                raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
            if str(run[0]) not in _PUBLISHED_RUN_STATES:
                return ProposalPage(items=(), next_cursor=None)
            ranked_where = ""
            ranked_parameters: list[object] = []
            if after is not None:
                ranked_where = (
                    " WHERE (state_rank>? OR (state_rank=? AND "
                    "(risk_rank<? OR (risk_rank=? AND reconciliation_proposal_id>?))))"
                )
                ranked_parameters.extend((after[0], after[0], after[1], after[1], after[2]))
            rows = snapshot.connection.execute(
                "WITH ranked AS (SELECT reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
                "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,risk_class,"
                "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,revision,"
                f"{state_case} AS state_rank,{risk_case} AS risk_rank FROM reconciliation_proposals WHERE {where}) "
                "SELECT reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
                "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,risk_class,"
                "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,revision,state_rank,risk_rank "
                f"FROM ranked{ranked_where} ORDER BY state_rank ASC,risk_rank DESC,reconciliation_proposal_id ASC LIMIT ?",
                (*parameters, *ranked_parameters, page_limit + 1),
            ).fetchall()

        page_rows = rows[:page_limit]
        items = tuple(_proposal_summary_from_row(row) for row in page_rows)
        next_cursor = None
        if len(rows) > page_limit and items:
            last = items[-1]
            next_cursor = {
                "version": 1,
                "query_id": _PROPOSAL_QUERY_ID,
                "sort_registry_id": _PROPOSAL_SORT_ID,
                "last_key_tuple": [last.state_rank, last.risk_rank, last.proposal_id],
                "filter_fingerprint": filter_fingerprint,
                "null_order": "none",
            }
        return ProposalPage(items=items, next_cursor=next_cursor)

    def get_review(self, proposal_id: str) -> ProposalReview:
        canonical_id = require_uuid4(proposal_id)
        state_case = (
            "CASE proposal_state WHEN 'pending' THEN 0 WHEN 'accepted' THEN 1 WHEN 'rejected' THEN 2 "
            "WHEN 'deferred' THEN 3 WHEN 'superseded' THEN 4 WHEN 'no_change' THEN 5 ELSE 99 END"
        )
        risk_case = (
            "CASE risk_class WHEN 'low' THEN 0 WHEN 'medium' THEN 1 WHEN 'high' THEN 2 "
            "WHEN 'blocked' THEN 3 ELSE 99 END"
        )
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
                "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,risk_class,"
                "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,revision,"
                f"{state_case} AS state_rank,{risk_case} AS risk_rank "
                "FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
                (canonical_id,),
            ).fetchone()
            if row is None:
                raise SomaError("IMPORT_PROPOSAL_NOT_FOUND", "reconciliation proposal does not exist")
            summary = _proposal_summary_from_row(row)
            proposal = self._repository.get(snapshot.connection, canonical_id)
            if proposal is None:
                raise IntegrityFailure("proposal disappeared inside stable review snapshot")
            changes = self._repository.list_changes(snapshot.connection, canonical_id)
            try:
                if proposal.proposal_kind in _GENERIC_SR_ACCEPT_KINDS:
                    target_preview, current_token, binding_current = _sr_target_preview(
                        snapshot.connection,
                        proposal,
                        changes,
                    )
                elif proposal.proposal_kind in _GENERIC_RFC_ACCEPT_KINDS:
                    target_preview, current_token, binding_current = _rfc_target_preview(
                        snapshot.connection,
                        proposal,
                        changes,
                    )
                elif proposal.proposal_kind in _GENERIC_WFM_ACCEPT_KINDS:
                    target_preview, current_token, binding_current = _wfm_target_preview(
                        snapshot.connection,
                        proposal,
                        changes,
                    )
                else:
                    target_preview = {
                        "owner": "dedicated_review_command",
                        "target_kind": proposal.target_kind,
                        "target_internal_id": proposal.target_internal_id,
                        "target_business_id": proposal.target_business_id,
                        "preview_available": False,
                    }
                    current_token = proposal.base_state_token
                    binding_current = proposal.proposal_kind == "wfm_competing_attempt_review"
            except (SomaError, ValidationError) as exc:
                target_preview = {
                    "owner": "stale_owner_authority",
                    "target_kind": proposal.target_kind,
                    "target_internal_id": proposal.target_internal_id,
                    "target_business_id": proposal.target_business_id,
                    "preview_available": False,
                    "stale_code": getattr(exc, "code", "VALIDATION_FAILED"),
                }
                current_token = None
                binding_current = False
            stale = (
                current_token is None
                or not binding_current
                or not hmac.compare_digest(current_token, proposal.base_state_token)
            )
            review_authorized = _run_review_authorized(snapshot.connection, proposal.import_run_id)
            allowed: list[str] = []
            if proposal.proposal_state == "pending" and review_authorized:
                if proposal.risk_class != "blocked" and not stale and proposal.proposal_kind in _GENERIC_ACCEPT_KINDS:
                    allowed.append("accept")
                allowed.extend(("reject", "defer"))
            return ProposalReview(
                proposal=summary,
                changes=tuple(_typed_change(change) for change in changes),
                target_preview=target_preview,
                stale=stale,
                allowed_dispositions=tuple(allowed),
            )


class ImportRecoveryQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def preview(self, import_run_id: str) -> ImportRecoveryPreview:
        run_id = require_uuid4(import_run_id)
        with ReadSnapshot(self._factory) as snapshot:
            run = ProposalRepository.get_run(snapshot.connection, run_id)
            if run.run_state != "recovery_required":
                raise SomaError("IMPORT_RUN_NOT_RECOVERY_REQUIRED", "import run is not awaiting recovery review")
            checkpoint = SourceCheckpointRepository.get(snapshot.connection, run.source_family)
            if checkpoint is None:
                raise IntegrityFailure("recovery-required import run has no source checkpoint")
            profile = snapshot.connection.execute(
                "SELECT source_profile_id FROM import_runs WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
            if profile is None or str(profile[0]) != checkpoint.source_profile_id:
                raise IntegrityFailure("recovery run and checkpoint source profiles disagree")
            if run.candidate_chronology_kind != checkpoint.chronology_kind:
                raise IntegrityFailure("recovery run and checkpoint chronology kinds disagree")
            if run.candidate_chronology_value < checkpoint.chronology_value:
                classification = "older_source"
            elif (
                run.candidate_chronology_value == checkpoint.chronology_value
                and run.logical_fingerprint != checkpoint.logical_fingerprint
            ):
                classification = "equal_chronology_different_content"
            else:
                raise IntegrityFailure("recovery-required run no longer has a recovery classification")
            finding = snapshot.connection.execute(
                "SELECT COUNT(*) FROM import_findings WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
            proposal = snapshot.connection.execute(
                "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
            review_fingerprint = ProposalRepository.recovery_review_fingerprint(snapshot.connection, run)
            candidate = {
                "chronology_kind": run.candidate_chronology_kind,
                "chronology_value": run.candidate_chronology_value,
                "logical_fingerprint": run.logical_fingerprint,
                "import_run_id": run.import_run_id,
            }
            checkpoint_side = {
                "chronology_kind": checkpoint.chronology_kind,
                "chronology_value": checkpoint.chronology_value,
                "logical_fingerprint": checkpoint.logical_fingerprint,
                "import_run_id": checkpoint.accepted_import_run_id,
            }
            actions = ["defer", "authorize_correction"]
            if run.accepted_count == 0:
                actions.insert(0, "reject")
            return ImportRecoveryPreview(
                import_run_id=run_id,
                review_fingerprint=review_fingerprint,
                classification=classification,
                candidate=candidate,
                checkpoint=checkpoint_side,
                proposal_count=int(proposal[0]),
                finding_count=int(finding[0]),
                allowed_actions=tuple(actions),
            )


class WfmPlanReviewQueryService:
    """Read-only LLD-04 WFM plan-review context projected through LLD-05 owner readers."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._proposals = ProposalRepository()

    def get_context(self, proposal_id: str) -> WfmPlanReviewContext:
        canonical_id = require_uuid4(proposal_id)
        with ReadSnapshot(self._factory) as snapshot:
            proposal = self._proposals.get(snapshot.connection, canonical_id)
            if proposal is None:
                raise SomaError("IMPORT_PROPOSAL_NOT_FOUND", "reconciliation proposal does not exist")
            if proposal.proposal_kind != "wfm_plan_reconciliation":
                raise SomaError("IMPORT_PROPOSAL_KIND_INVALID", "proposal is not a WFM plan reconciliation")
            if (
                proposal.evidence_mode != "observed_row"
                or proposal.source_observation_id is None
                or proposal.target_kind != "task_plan"
                or proposal.target_internal_id is None
                or proposal.target_business_id is None
                or proposal.risk_class != "high"
            ):
                raise IntegrityFailure("WFM plan reconciliation proposal binding is invalid")

            source_row = snapshot.connection.execute(
                "SELECT import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,"
                "source_row_chronology_utc FROM source_observations WHERE source_observation_id=?",
                (proposal.source_observation_id,),
            ).fetchone()
            if source_row is None:
                raise IntegrityFailure("WFM plan reconciliation source observation is missing")
            if (
                str(source_row[0]) != proposal.import_run_id
                or str(source_row[1]) != "wfm_service_provider"
                or str(source_row[2]) != "wfm"
                or str(source_row[3]) != "valid"
                or str(source_row[4]) != proposal.target_business_id
            ):
                raise IntegrityFailure("WFM plan reconciliation source observation binding is invalid")
            source_chronology = None if source_row[5] is None else int(source_row[5])
            if source_chronology is not None and source_chronology < 0:
                raise IntegrityFailure("WFM plan reconciliation source chronology is invalid")

            identity = WfmImportReader.get_by_task_no(snapshot.connection, proposal.target_business_id)
            if identity is None or identity.get("task_id") != proposal.target_internal_id:
                raise IntegrityFailure("WFM plan reconciliation target identity is no longer owner-authoritative")

            source_plan = WfmImportReader.source_plan(snapshot.connection, proposal.target_internal_id)
            if source_plan is None:
                raise IntegrityFailure("WFM plan reconciliation has no current source-plan authority")
            operational_plan = WfmImportReader.operational_plan_context(
                snapshot.connection,
                proposal.target_internal_id,
            )

            WfmImportReader.source_acceptance_base_token(
                snapshot.connection,
                WfmImportBaseTarget(
                    "wfm_plan_reconciliation",
                    proposal.target_business_id,
                    proposal.target_internal_id,
                ),
            )

            return WfmPlanReviewContext(
                proposal_id=proposal.proposal_id,
                source_plan=dict(source_plan),
                operational_plan=None if operational_plan is None else dict(operational_plan),
                plan_diff=_plan_diff(source_plan, operational_plan),
                source_chronology=source_chronology,
                objective_regrouping_consequence="INDETERMINATE",
                base_state_token=proposal.base_state_token,
            )


__all__ = [
    "ImportRecoveryPreview",
    "ImportRecoveryQueryService",
    "ProposalPage",
    "ProposalQueryService",
    "ProposalReview",
    "ProposalSummary",
    "WfmPlanReviewContext",
    "WfmPlanReviewQueryService",
]
