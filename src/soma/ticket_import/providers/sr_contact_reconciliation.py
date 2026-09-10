from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.reference.queries.matching import ReferenceMatcher


_ROLE_BINDINGS = {
    "customer_contact": ("sr_contact_reconciliation", "customer_contact_label"),
    "current_handler_reference": ("sr_current_handler_reconciliation", "current_handler_label"),
}


@dataclass(frozen=True, slots=True)
class ReviewedContactCandidate:
    reference_role: str
    contact_id: str
    prior_contact_id: str | None
    source_observation_id: str
    source_observation_field_id: str
    matcher_scope: str
    matcher_explanation: str


class TicketImportSrContactReconciliationProvider:
    """LLD-04 exact source/matcher evidence for reviewed SR Contact reconciliation."""

    @staticmethod
    def _binding(reference_role: str) -> tuple[str, str]:
        try:
            return _ROLE_BINDINGS[reference_role]
        except KeyError as exc:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation role is invalid") from exc

    @classmethod
    def _source_field(
        cls,
        reader: Any,
        *,
        expected_import_run_id: str,
        source_observation_id: str,
        source_observation_field_id: str,
        canonical_sr_no: str,
        reference_role: str,
    ) -> str:
        _proposal_kind, expected_field_key = cls._binding(reference_role)
        row = reader.execute(
            "SELECT o.import_run_id,o.source_family,o.entity_kind,o.identity_state,o.canonical_primary_id,"
            "f.field_key,f.field_class,f.value_state,f.value_kind,f.normalized_text "
            "FROM source_observation_fields f "
            "JOIN source_observations o ON o.source_observation_id=f.source_observation_id "
            "WHERE f.source_observation_field_id=? AND o.source_observation_id=?",
            (source_observation_field_id, source_observation_id),
        ).fetchone()
        if (
            row is None
            or str(row[0]) != expected_import_run_id
            or str(row[1]) != "advanced_search_sr"
            or str(row[2]) != "service_request"
            or str(row[3]) != "valid"
            or str(row[4]) != canonical_sr_no
            or str(row[5]) != expected_field_key
            or str(row[6]) != "active"
            or str(row[7]) != "usable"
            or str(row[8]) != "text"
            or row[9] is None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation source evidence is no longer exact")
        return str(row[9])

    def revalidate_reviewed_candidate(
        self,
        reader: Any,
        *,
        expected_import_run_id: str,
        source_observation_id: str,
        service_request_id: str,
        canonical_sr_no: str,
        reference_role: str,
        current_customer_org_id: str | None,
        field_key: str,
        change_kind: str,
        value_kind: str,
        before_text: str | None,
        after_text: str | None,
        before_integer: int | None,
        after_integer: int | None,
        source_observation_field_id: str | None,
    ) -> ReviewedContactCandidate:
        del service_request_id  # identity is proven by canonical SR/source binding; owner state is revalidated separately.
        self._binding(reference_role)
        if field_key != "contact_id" or change_kind != "set" or value_kind != "identity":
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation proposal change encoding is invalid")
        if before_integer is not None or after_integer is not None or after_text is None or source_observation_field_id is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation identity change is incomplete")
        try:
            target_contact_id = require_uuid4(after_text)
            prior_contact_id = None if before_text is None else require_uuid4(before_text)
        except ValidationError as exc:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation identity is invalid") from exc

        raw_name = self._source_field(
            reader,
            expected_import_run_id=expected_import_run_id,
            source_observation_id=source_observation_id,
            source_observation_field_id=source_observation_field_id,
            canonical_sr_no=canonical_sr_no,
            reference_role=reference_role,
        )
        matcher_scope = "UNBOUND" if current_customer_org_id is None else current_customer_org_id
        match = ReferenceMatcher.match_contact(
            reader,
            scope=matcher_scope,
            raw_name=raw_name,
            limit=2,
        )
        if (
            match.state != "UNIQUE_CANDIDATE"
            or match.candidate_count != 1
            or match.candidate_ids != (target_contact_id,)
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation candidate is no longer uniquely resolved")
        return ReviewedContactCandidate(
            reference_role=reference_role,
            contact_id=target_contact_id,
            prior_contact_id=prior_contact_id,
            source_observation_id=source_observation_id,
            source_observation_field_id=source_observation_field_id,
            matcher_scope=matcher_scope,
            matcher_explanation=match.explanation,
        )

    @classmethod
    def validate_sr_contact_acceptance(
        cls,
        reader: Any,
        proposal_id: str,
        sr_id: str,
        reference_role: str,
        target_contact_id: str,
        source_observation_field_id: str,
        command_context: dict[str, object],
    ) -> str:
        try:
            expected_kind, expected_source_field_key = cls._binding(reference_role)
            require_uuid4(target_contact_id)
        except (SomaError, ValidationError):
            return "INVALID"
        if not isinstance(command_context, dict):
            return "INVALID"
        command_id = command_context.get("command_id")
        proposal_revision = command_context.get("proposal_revision")
        proposal_fingerprint = command_context.get("proposal_fingerprint")
        if (
            not isinstance(command_id, str)
            or type(proposal_revision) is not int
            or proposal_revision <= 0
            or not isinstance(proposal_fingerprint, str)
            or len(proposal_fingerprint) != 64
        ):
            return "INVALID"

        row = reader.execute(
            "SELECT p.proposal_kind,p.target_kind,p.target_internal_id,p.proposal_state,p.source_observation_id,"
            "p.revision,p.proposal_fingerprint_sha256,c.field_key,c.change_kind,c.value_kind,c.after_text,"
            "c.source_observation_field_id,f.field_key,f.field_class,f.value_state,f.value_kind "
            "FROM reconciliation_proposals p "
            "JOIN reconciliation_proposal_changes c ON c.reconciliation_proposal_id=p.reconciliation_proposal_id "
            "JOIN source_observation_fields f ON f.source_observation_field_id=c.source_observation_field_id "
            "WHERE p.reconciliation_proposal_id=? AND c.ordinal=0 "
            "AND NOT EXISTS (SELECT 1 FROM reconciliation_proposal_changes c2 "
            "WHERE c2.reconciliation_proposal_id=p.reconciliation_proposal_id AND c2.ordinal<>0)",
            (proposal_id,),
        ).fetchone()
        receipt = reader.execute(
            "SELECT command_type,target_type,target_id FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if (
            row is None
            or str(row[0]) != expected_kind
            or str(row[1]) != "service_request"
            or str(row[2]) != sr_id
            or str(row[3]) != "pending"
            or row[4] is None
            or int(row[5]) != proposal_revision
            or str(row[6]) != proposal_fingerprint
            or str(row[7]) != "contact_id"
            or str(row[8]) != "set"
            or str(row[9]) != "identity"
            or str(row[10]) != target_contact_id
            or str(row[11]) != source_observation_field_id
            or str(row[12]) != expected_source_field_key
            or str(row[13]) != "active"
            or str(row[14]) != "usable"
            or str(row[15]) != "text"
            or receipt is None
            or str(receipt[0]) != "AcceptReconciliationProposal"
            or str(receipt[1]) != "reconciliation_proposal"
            or str(receipt[2]) != proposal_id
        ):
            return "INVALID"
        return "VALID"
