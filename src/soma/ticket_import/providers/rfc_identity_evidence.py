from __future__ import annotations

from typing import Any

from soma.foundation.errors import SomaError
from soma.ticket_import.profiles.registry import require_profile_versions
from soma.tickets.validation import validate_rfc_no


_PUBLISHED_RUN_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)
_SOURCE_FAMILY = "rfc_enhanced"


class TicketImportRfcIdentityEvidenceProvider:
    """LLD-04 validator for one exact published Enhanced RFC identity observation."""

    @staticmethod
    def validate_observed_identity(
        reader: Any,
        *,
        expected_import_run_id: str,
        source_observation_id: str,
        canonical_rfc_no: str,
    ) -> None:
        try:
            canonical = validate_rfc_no(canonical_rfc_no)
        except Exception as exc:
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "proposal target is not an exact RFC identity",
            ) from exc
        expected_profile = require_profile_versions(_SOURCE_FAMILY)
        row = reader.execute(
            "SELECT o.import_run_id,o.source_family,o.entity_kind,o.identity_state,o.canonical_primary_id,"
            "o.canonical_parent_rfc_no,o.presence_state,r.run_state,r.source_family,r.source_profile_id,"
            "r.header_registry_id,r.vocabulary_registry_id,r.parser_profile_id "
            "FROM source_observations o JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.source_observation_id=?",
            (source_observation_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal RFC identity observation no longer exists")
        if (
            str(row[0]) != expected_import_run_id
            or str(row[1]) != _SOURCE_FAMILY
            or str(row[2]) != "rfc"
            or str(row[3]) != "valid"
            or row[4] is None
            or str(row[4]) != canonical
            or row[5] is not None
            or str(row[6]) != "observed_valid_identity"
            or str(row[7]) not in _PUBLISHED_RUN_STATES
            or str(row[8]) != _SOURCE_FAMILY
            or (
                str(row[9]),
                str(row[10]),
                str(row[11]),
                str(row[12]),
            )
            != (
                expected_profile.source_profile_id,
                expected_profile.header_registry_id,
                expected_profile.vocabulary_registry_id,
                expected_profile.parser_profile_id,
            )
        ):
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "proposal no longer binds exact published RFC identity evidence",
            )
