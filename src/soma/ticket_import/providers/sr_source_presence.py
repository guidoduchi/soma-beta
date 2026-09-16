from __future__ import annotations

from typing import Any

from soma.foundation.identifiers import require_uuid4
from soma.tickets.validation import validate_official_sr_no

from ..reconciliation.advanced_search_disappearance import _resolve_prior_population_run


_PUBLISHED_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)
_ORDINARY_PRESENCE_STATES = frozenset(
    {"staged", "waiting_review", "partially_accepted", "accepted", "rejected"}
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

    @staticmethod
    def _run_chronology(reader: Any, import_run_id: str) -> tuple[str, int, str] | None:
        row = reader.execute(
            "SELECT source_family,candidate_chronology_kind,candidate_chronology_value,run_state "
            "FROM import_runs WHERE import_run_id=?",
            (require_uuid4(import_run_id),),
        ).fetchone()
        if row is None or str(row[0]) != "advanced_search_sr":
            return None
        value = int(row[2])
        if value < 0:
            return None
        return str(row[1]), value, str(row[3])

    @staticmethod
    def _run_contains_identity(reader: Any, import_run_id: str, official: str) -> bool:
        return (
            reader.execute(
                "SELECT 1 FROM source_observations WHERE import_run_id=? "
                "AND source_family='advanced_search_sr' AND entity_kind='service_request' "
                "AND identity_state='valid' AND presence_state='observed_valid_identity' "
                "AND canonical_primary_id=? LIMIT 1",
                (require_uuid4(import_run_id), official),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _has_recovery_lineage(reader: Any, import_run_id: str) -> bool:
        run_id = require_uuid4(import_run_id)
        review = reader.execute(
            "SELECT 1 FROM import_recovery_reviews WHERE import_run_id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        if review is not None:
            return True
        event = reader.execute(
            "SELECT 1 FROM import_recovery_events WHERE import_run_id=? LIMIT 1",
            (run_id,),
        ).fetchone()
        return event is not None

    @classmethod
    def _later_authoritative_presence_exists(
        cls,
        reader: Any,
        *,
        absence_run_id: str,
        prior_population_run_id: str,
        official: str,
    ) -> bool:
        absence = cls._run_chronology(reader, absence_run_id)
        if absence is None:
            return False
        chronology_kind, chronology_value, _run_state = absence
        placeholders = ",".join("?" for _ in sorted(_ORDINARY_PRESENCE_STATES))
        ordinary = reader.execute(
            "SELECT 1 FROM import_runs r WHERE r.source_family='advanced_search_sr' "
            "AND r.candidate_chronology_kind=? AND r.candidate_chronology_value>? "
            "AND r.run_state IN ("
            + placeholders
            + ") AND NOT EXISTS (SELECT 1 FROM import_recovery_reviews rr WHERE rr.import_run_id=r.import_run_id) "
            "AND NOT EXISTS (SELECT 1 FROM import_recovery_events re WHERE re.import_run_id=r.import_run_id) "
            "AND EXISTS (SELECT 1 FROM source_observations o WHERE o.import_run_id=r.import_run_id "
            "AND o.source_family='advanced_search_sr' AND o.entity_kind='service_request' "
            "AND o.identity_state='valid' AND o.presence_state='observed_valid_identity' "
            "AND o.canonical_primary_id=?) LIMIT 1",
            (
                chronology_kind,
                chronology_value,
                *sorted(_ORDINARY_PRESENCE_STATES),
                official,
            ),
        ).fetchone()
        if ordinary is not None:
            return True

        checkpoint = reader.execute(
            "SELECT accepted_candidate_chronology_kind,accepted_candidate_chronology_value "
            "FROM import_source_checkpoints WHERE source_family='advanced_search_sr'",
        ).fetchone()
        if checkpoint is None:
            return False
        checkpoint_kind = str(checkpoint[0])
        checkpoint_value = int(checkpoint[1])
        if checkpoint_kind != chronology_kind or checkpoint_value < chronology_value:
            return False
        representative = _resolve_prior_population_run(reader)
        if representative is None or not cls._run_contains_identity(reader, representative, official):
            return False
        if checkpoint_value > chronology_value:
            return True
        return representative != require_uuid4(prior_population_run_id)

    @staticmethod
    def _is_representative_conflict_free_observation(
        reader: Any,
        *,
        import_run_id: str,
        official: str,
        source_observation_id: str,
    ) -> bool:
        row = reader.execute(
            "SELECT COUNT(*),COUNT(DISTINCT row_logical_sha256),MIN(source_observation_id) "
            "FROM source_observations WHERE import_run_id=? "
            "AND source_family='advanced_search_sr' AND entity_kind='service_request' "
            "AND identity_state='valid' AND presence_state='observed_valid_identity' "
            "AND canonical_primary_id=?",
            (require_uuid4(import_run_id), official),
        ).fetchone()
        if row is None:
            return False
        return (
            int(row[0]) >= 1
            and int(row[1]) == 1
            and row[2] is not None
            and str(row[2]) == require_uuid4(source_observation_id)
        )

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
            "SELECT o.canonical_primary_id,o.source_family,o.entity_kind,o.identity_state,o.import_run_id,r.run_state "
            "FROM source_observations o JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.source_observation_id=?",
            (require_uuid4(prior_source_observation_id),),
        ).fetchone()
        if prior is None or (
            str(prior[0]) != official
            or str(prior[1]) != source_family
            or str(prior[2]) != "service_request"
            or str(prior[3]) != "valid"
            or str(prior[5]) not in _PUBLISHED_STATES
        ):
            return "INVALID"
        prior_population_run_id = require_uuid4(str(prior[4]))
        present = reader.execute(
            "SELECT 1 FROM source_observations WHERE import_run_id=? AND source_family=? "
            "AND entity_kind='service_request' AND identity_state='valid' AND canonical_primary_id=? LIMIT 1",
            (import_run_id, source_family, official),
        ).fetchone()
        if present is not None:
            return "INVALID"
        if self._later_authoritative_presence_exists(
            reader,
            absence_run_id=import_run_id,
            prior_population_run_id=prior_population_run_id,
            official=official,
        ):
            return "INVALID"
        return "VALID"

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
        if row is None or not (
            str(row[0]) == import_run_id
            and str(row[1]) == source_family
            and str(row[2]) == "service_request"
            and str(row[3]) == "valid"
            and str(row[4]) == official
            and str(row[5]) == "observed_valid_identity"
            and str(row[6]) == source_family
            and str(row[7]) in _PUBLISHED_STATES
        ):
            return "INVALID"
        if not self._is_representative_conflict_free_observation(
            reader,
            import_run_id=import_run_id,
            official=official,
            source_observation_id=source_observation_id,
        ):
            return "INVALID"

        event_id = command_context.get("expected_active_disappearance_event_id")
        if not isinstance(event_id, str):
            return "INVALID"
        event = reader.execute(
            "SELECT service_request_id,event_kind,import_run_id FROM sr_source_presence_events "
            "WHERE sr_source_presence_event_id=?",
            (require_uuid4(event_id),),
        ).fetchone()
        if event is None or (
            str(event[0]) != sr_id or str(event[1]) != "disappearance_reviewed"
        ):
            return "INVALID"
        absence_run_id = require_uuid4(str(event[2]))
        absence = self._run_chronology(reader, absence_run_id)
        candidate = self._run_chronology(reader, import_run_id)
        if absence is None or candidate is None:
            return "INVALID"
        absence_kind, absence_value, _absence_state = absence
        candidate_kind, candidate_value, candidate_state = candidate
        if candidate_kind != absence_kind or candidate_value < absence_value:
            return "INVALID"
        if candidate_value > absence_value:
            if candidate_state not in _ORDINARY_PRESENCE_STATES:
                return "INVALID"
            return "INVALID" if self._has_recovery_lineage(reader, import_run_id) else "VALID"

        representative = _resolve_prior_population_run(reader)
        return "VALID" if representative == import_run_id else "INVALID"
