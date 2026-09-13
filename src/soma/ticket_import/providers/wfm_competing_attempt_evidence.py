from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import require_uuid4


_PUBLISHED_RUN_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)
_SOURCE_FAMILY = "wfm_service_provider"
_SOURCE_PROFILE_ID = "WFM_SERVICE_PROVIDER_V1"


@dataclass(frozen=True, slots=True)
class PublishedWfmCompetingAttemptEvidence:
    source_observation_id: str
    import_run_id: str
    task_no: str
    parent_rfc_no: str
    planned_start_field_id: str
    planned_start_utc: int
    planned_end_field_id: str
    planned_end_utc: int


class TicketImportWfmCompetingAttemptEvidenceProvider:
    """Read-only LLD-04 authority for one exact published WFM review observation."""

    @staticmethod
    def load_exact(
        reader: Any,
        *,
        expected_import_run_id: str,
        source_observation_id: str,
    ) -> PublishedWfmCompetingAttemptEvidence:
        observation_id = require_uuid4(source_observation_id)
        row = reader.execute(
            "SELECT o.source_observation_id,o.import_run_id,o.source_family,o.entity_kind,o.identity_state,"
            "o.canonical_primary_id,o.canonical_parent_rfc_no,r.run_state,r.source_family,r.source_profile_id "
            "FROM source_observations o JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.source_observation_id=?",
            (observation_id,),
        ).fetchone()
        if (
            row is None
            or str(row[1]) != expected_import_run_id
            or str(row[2]) != _SOURCE_FAMILY
            or str(row[3]) != "wfm"
            or str(row[4]) != "valid"
            or row[5] is None
            or row[6] is None
            or str(row[7]) not in _PUBLISHED_RUN_STATES
            or str(row[8]) != _SOURCE_FAMILY
            or str(row[9]) != _SOURCE_PROFILE_ID
        ):
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "competing-attempt proposal no longer binds exact published WFM evidence",
            )

        conflict = reader.execute(
            "SELECT 1 FROM import_findings WHERE import_run_id=? AND source_observation_id=? "
            "AND finding_code='SOURCE_IDENTITY_CONFLICT' LIMIT 1",
            (expected_import_run_id, observation_id),
        ).fetchone()
        if conflict is not None:
            raise SomaError(
                "IMPORT_PROPOSAL_BLOCKED",
                "WFM observation is blocked by a current source identity conflict",
            )

        fields = reader.execute(
            "SELECT source_observation_field_id,field_key,field_class,value_state,value_kind,integer_value "
            "FROM source_observation_fields WHERE source_observation_id=? "
            "AND field_key IN ('planned_start','planned_end') ORDER BY field_key",
            (observation_id,),
        ).fetchall()
        if len(fields) != 2:
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "competing-attempt source observation no longer has the exact plan pair",
            )
        by_key = {str(field[1]): field for field in fields}
        if set(by_key) != {"planned_start", "planned_end"}:
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM source plan field identity changed")

        def require_instant(field: Any, *, key: str) -> tuple[str, int]:
            if (
                str(field[2]) != "active"
                or str(field[3]) != "usable"
                or str(field[4]) != "instant"
                or type(field[5]) is not int
                or int(field[5]) < 0
            ):
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    f"WFM {key} is no longer usable active instant evidence",
                )
            return require_uuid4(str(field[0])), int(field[5])

        start_field_id, start_utc = require_instant(by_key["planned_start"], key="planned_start")
        end_field_id, end_utc = require_instant(by_key["planned_end"], key="planned_end")
        if end_utc <= start_utc:
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM source plan interval is no longer valid")

        return PublishedWfmCompetingAttemptEvidence(
            source_observation_id=observation_id,
            import_run_id=expected_import_run_id,
            task_no=str(row[5]),
            parent_rfc_no=str(row[6]),
            planned_start_field_id=start_field_id,
            planned_start_utc=start_utc,
            planned_end_field_id=end_field_id,
            planned_end_utc=end_utc,
        )
