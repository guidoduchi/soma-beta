from __future__ import annotations

import re
from typing import Any

from soma.foundation.errors import SomaError


_SR8_RE = re.compile(r"[0-9]{8}\Z", flags=re.ASCII)
_PUBLISHED_RUN_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)


class TicketImportSrIdentityEvidenceProvider:
    """LLD-04 validator for one exact published Advanced Search SR identity observation."""

    @staticmethod
    def validate_observed_identity(
        reader: Any,
        *,
        expected_import_run_id: str,
        source_observation_id: str,
        canonical_sr_no: str,
    ) -> None:
        if not isinstance(canonical_sr_no, str) or _SR8_RE.fullmatch(canonical_sr_no) is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal target is not an exact eight-digit Service Request identity")
        row = reader.execute(
            "SELECT o.import_run_id,o.source_family,o.entity_kind,o.identity_state,o.canonical_primary_id,"
            "o.presence_state,r.run_state FROM source_observations o "
            "JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.source_observation_id=?",
            (source_observation_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal source identity observation no longer exists")
        if (
            str(row[0]) != expected_import_run_id
            or str(row[1]) != "advanced_search_sr"
            or str(row[2]) != "service_request"
            or str(row[3]) != "valid"
            or row[4] is None
            or str(row[4]) != canonical_sr_no
            or str(row[5]) != "observed_valid_identity"
            or str(row[6]) not in _PUBLISHED_RUN_STATES
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal no longer binds exact published SR identity evidence")
