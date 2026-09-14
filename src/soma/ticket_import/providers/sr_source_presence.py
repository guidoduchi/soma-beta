from __future__ import annotations

from typing import Any

from soma.foundation.identifiers import require_uuid4
from soma.tickets.validation import validate_official_sr_no


_PUBLISHED_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)


class TicketImportSrSourcePresenceEvidenceProvider:
    """Read-only LLD-04 validator for opaque Advanced Search presence evidence."""

    @staticmethod
    def _official_sr_no(reader: Any, service_request_id: str) -> str | None:
        row = reader.execute(
            "SELECT official_sr_no FROM service_requests WHERE service_request_id=?",
            (require_uuid4(service_request_id),),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return validate_official_sr_no(str(row[0]))

    def validate_disappearance_acceptance(
        self,
        reader: Any,
        proposal_id: str,
        sr_id: str,
        source_family: str,
        import_run_id: str,
        prior_source_observation_id: str,
        command_context: dict[str, object],
    ) -> str:
        if source_family != "advanced_search_sr":
            return "INVALID"
        official = self._official_sr_no(reader, sr_id)
        if official is None:
            return "INVALID"
        proposal = reader.execute(
            "SELECT p.import_run_id,p.evidence_mode,p.source_observation_id,p.prior_source_observation_id,"
            "p.proposal_kind,p.target_kind,p.target_internal_id,p.target_business_id,p.risk_class,p.proposal_state,"
            "p.revision,p.proposal_fingerprint_sha256,r.source_family,r.run_state "
            "FROM reconciliation_proposals p JOIN import_runs r ON r.import_run_id=p.import_run_id "
            "WHERE p.reconciliation_proposal_id=?",
            (require_uuid4(proposal_id),),
        ).fetchone()
        if proposal is None:
            return "INVALID"
        command_id = command_context.get("command_id")
        receipt = reader.execute(
            "SELECT command_type,target_type,target_id FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if receipt is None or tuple(receipt) != (
            "AcceptReconciliationProposal",
            "reconciliation_proposal",
            proposal_id,
        ):
            return "INVALID"
        if (
            str(proposal[0]) != import_run_id
            or str(proposal[1]) != "population_absence"
            or proposal[2] is not None
            or str(proposal[3]) != prior_source_observation_id
            or str(proposal[4]) != "sr_source_disappearance_review"
            or str(proposal[5]) != "source_presence"
            or str(proposal[6]) != sr_id
            or str(proposal[7]) != official
            or str(proposal[8]) != "high"
            or str(proposal[9]) != "pending"
            or str(proposal[12]) != source_family
            or str(proposal[13]) not in _PUBLISHED_STATES
            or command_context.get("proposal_revision") != int(proposal[10])
            or command_context.get("proposal_fingerprint") != str(proposal[11])
        ):
            return "INVALID"
        prior = reader.execute(
            "SELECT o.canonical_primary_id,o.source_family,o.entity_kind,o.identity_state,r.run_state "
            "FROM source_observations o JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.source_observation_id=?",
            (require_uuid4(prior_source_observation_id),),
        ).fetchone()
        if prior is None or (
            str(prior[0]) != official
            or str(prior[1]) != source_family
            or str(prior[2]) != "service_request"
            or str(prior[3]) != "valid"
            or str(prior[4]) not in _PUBLISHED_STATES
        ):
            return "INVALID"
        present = reader.execute(
            "SELECT 1 FROM source_observations WHERE import_run_id=? AND source_family=? "
            "AND entity_kind='service_request' AND identity_state='valid' AND canonical_primary_id=? LIMIT 1",
            (import_run_id, source_family, official),
        ).fetchone()
        return "VALID" if present is None else "INVALID"

    def validate_reappearance_evidence(
        self,
        reader: Any,
        sr_id: str,
        source_family: str,
        import_run_id: str,
        source_observation_id: str,
        command_context: dict[str, object],
    ) -> str:
        if source_family != "advanced_search_sr":
            return "INVALID"
        official = self._official_sr_no(reader, sr_id)
        if official is None:
            return "INVALID"
        row = reader.execute(
            "SELECT o.import_run_id,o.source_family,o.entity_kind,o.identity_state,o.canonical_primary_id,"
            "o.presence_state,r.source_family,r.run_state FROM source_observations o "
            "JOIN import_runs r ON r.import_run_id=o.import_run_id WHERE o.source_observation_id=?",
            (require_uuid4(source_observation_id),),
        ).fetchone()
        if row is None:
            return "INVALID"
        return (
            "VALID"
            if str(row[0]) == import_run_id
            and str(row[1]) == source_family
            and str(row[2]) == "service_request"
            and str(row[3]) == "valid"
            and str(row[4]) == official
            and str(row[5]) == "observed_valid_identity"
            and str(row[6]) == source_family
            and str(row[7]) in _PUBLISHED_STATES
            else "INVALID"
        )
