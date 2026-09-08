from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import require_uuid4
from soma.reference.queries.matching import ReferenceMatcher


@dataclass(frozen=True, slots=True)
class ReviewedCustomerCandidate:
    customer_org_id: str
    prior_customer_org_id: str | None
    source_observation_id: str
    supporting_source_observation_field_id: str
    matcher_explanation: str


class TicketImportSrCustomerReconciliationProvider:
    """LLD-04 exact source/matcher evidence provider for reviewed SR Customer reconciliation."""

    @staticmethod
    def _source_fields(
        reader: Any,
        *,
        expected_import_run_id: str,
        source_observation_id: str,
        canonical_sr_no: str,
    ) -> dict[str, tuple[str, str]]:
        observation = reader.execute(
            "SELECT import_run_id,source_family,entity_kind,identity_state,canonical_primary_id "
            "FROM source_observations WHERE source_observation_id=?",
            (source_observation_id,),
        ).fetchone()
        if (
            observation is None
            or str(observation[0]) != expected_import_run_id
            or str(observation[1]) != "advanced_search_sr"
            or str(observation[2]) != "service_request"
            or str(observation[3]) != "valid"
            or str(observation[4]) != canonical_sr_no
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation source observation is no longer exact")
        rows = reader.execute(
            "SELECT source_observation_field_id,field_key,value_state,value_kind,normalized_text,field_class "
            "FROM source_observation_fields WHERE source_observation_id=? "
            "AND field_key IN ('customer_account_code','customer_org_label') "
            "ORDER BY field_key ASC,source_observation_field_id ASC",
            (source_observation_id,),
        ).fetchall()
        usable: dict[str, tuple[str, str]] = {}
        for row in rows:
            if str(row[2]) != "usable" or str(row[3]) != "text" or str(row[5]) != "active" or row[4] is None:
                continue
            key = str(row[1])
            if key in usable:
                raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation source contains duplicate usable evidence")
            usable[key] = (str(row[0]), str(row[4]))
        return usable

    def revalidate_reviewed_candidate(
        self,
        reader: Any,
        *,
        proposal_id: str,
        expected_import_run_id: str,
        source_observation_id: str,
        service_request_id: str,
        canonical_sr_no: str,
        field_key: str,
        change_kind: str,
        value_kind: str,
        before_text: str | None,
        after_text: str | None,
        before_integer: int | None,
        after_integer: int | None,
        source_observation_field_id: str | None,
    ) -> ReviewedCustomerCandidate:
        if field_key != "customer_org_id" or change_kind != "set" or value_kind != "identity":
            raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation proposal change encoding is invalid")
        if before_integer is not None or after_integer is not None or after_text is None or source_observation_field_id is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation identity change is incomplete")
        require_uuid4(after_text)
        if before_text is not None:
            require_uuid4(before_text)

        fields = self._source_fields(
            reader,
            expected_import_run_id=expected_import_run_id,
            source_observation_id=source_observation_id,
            canonical_sr_no=canonical_sr_no,
        )
        account = fields.get("customer_account_code")
        label = fields.get("customer_org_label")
        if account is None and label is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation no longer has usable matching evidence")
        strongest_field_id = account[0] if account is not None else label[0]  # type: ignore[index]
        if source_observation_field_id != strongest_field_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation evidence pointer is no longer strongest exact evidence")

        match = ReferenceMatcher.match_customer_org(
            reader,
            raw_account_code=None if account is None else account[1],
            raw_name=None if label is None else label[1],
            limit=2,
        )
        if match.state != "UNIQUE_CANDIDATE" or match.candidate_count != 1 or match.candidate_ids != (after_text,):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation candidate is no longer uniquely resolved")
        return ReviewedCustomerCandidate(
            customer_org_id=after_text,
            prior_customer_org_id=before_text,
            source_observation_id=source_observation_id,
            supporting_source_observation_field_id=source_observation_field_id,
            matcher_explanation=match.explanation,
        )

    @staticmethod
    def validate_accepted_relationship_proposal(
        reader: Any,
        *,
        proposal_id: str,
        service_request_id: str,
        customer_org_id: str,
    ) -> str:
        row = reader.execute(
            "SELECT p.proposal_kind,p.target_kind,p.target_internal_id,p.proposal_state,p.source_observation_id,"
            "c.field_key,c.change_kind,c.value_kind,c.after_text "
            "FROM reconciliation_proposals p JOIN reconciliation_proposal_changes c "
            "ON c.reconciliation_proposal_id=p.reconciliation_proposal_id "
            "WHERE p.reconciliation_proposal_id=? AND c.ordinal=0 "
            "AND NOT EXISTS (SELECT 1 FROM reconciliation_proposal_changes c2 "
            "WHERE c2.reconciliation_proposal_id=p.reconciliation_proposal_id AND c2.ordinal<>0)",
            (proposal_id,),
        ).fetchone()
        receipt_count = reader.execute(
            "SELECT COUNT(*) FROM command_receipts "
            "WHERE command_type='AcceptReconciliationProposal' "
            "AND target_type='reconciliation_proposal' AND target_id=?",
            (proposal_id,),
        ).fetchone()
        if (
            row is None
            or str(row[0]) != "sr_customer_reconciliation"
            or str(row[1]) != "service_request"
            or str(row[2]) != service_request_id
            or str(row[3]) != "pending"
            or row[4] is None
            or str(row[5]) != "customer_org_id"
            or str(row[6]) != "set"
            or str(row[7]) != "identity"
            or str(row[8]) != customer_org_id
            or receipt_count is None
            or int(receipt_count[0]) != 1
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "pending Customer reconciliation proposal evidence is not exact")
        return str(row[4])
