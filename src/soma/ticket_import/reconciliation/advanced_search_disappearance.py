from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.ticket_import.profiles.registry import require_profile_versions
from soma.tickets.service_request_import_reader import ServiceRequestImportReader
from soma.tickets.validation import validate_official_sr_no

from .engine import ProposalChangeDraft

_SOURCE_FAMILY = "advanced_search_sr"
_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"
_FINAL_ROW_BEARING_STATES = ("accepted", "partially_accepted", "rejected")
_CHECKPOINT_RUN_STATES = frozenset({*_FINAL_ROW_BEARING_STATES, "noop"})
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PopulationAbsenceProposalDraft:
    import_run_id: str
    prior_source_observation_id: str
    target_internal_id: str
    target_business_id: str
    base_state_token_sha256: str
    proposal_fingerprint_sha256: str
    changes: tuple[ProposalChangeDraft, ...]


def _require_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise IntegrityFailure(f"{label} is not lowercase SHA-256 hex")
    return value


def _current_run_authority(reader: Any, import_run_id: str) -> dict[str, object]:
    row = reader.execute(
        "SELECT source_family,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_chronology_kind,candidate_chronology_value,run_state,revision "
        "FROM import_runs WHERE import_run_id=?",
        (import_run_id,),
    ).fetchone()
    if row is None:
        raise SomaError("IMPORT_RUN_NOT_FOUND", "Advanced Search disappearance parent run does not exist")
    expected = require_profile_versions(_SOURCE_FAMILY)
    profile_values = tuple(str(row[index]) for index in range(1, 5))
    if str(row[0]) != _SOURCE_FAMILY or profile_values != (
        expected.source_profile_id,
        expected.header_registry_id,
        expected.vocabulary_registry_id,
        expected.parser_profile_id,
    ):
        raise SomaError(
            "IMPORT_SOURCE_PROFILE_MISMATCH",
            "Advanced Search disappearance parent run uses stale source profiles",
        )
    if str(row[7]) != "validating" or int(row[8]) < 1:
        raise SomaError(
            "IMPORT_RUN_STALE",
            "Advanced Search disappearance proposals require the current validating run",
        )
    chronology_value = int(row[6])
    if chronology_value < 0:
        raise IntegrityFailure("Advanced Search disappearance run chronology is invalid")
    return {
        "import_run_id": import_run_id,
        "source_family": _SOURCE_FAMILY,
        "source_profile_id": profile_values[0],
        "header_registry_id": profile_values[1],
        "vocabulary_registry_id": profile_values[2],
        "parser_profile_id": profile_values[3],
        "candidate_chronology_kind": str(row[5]),
        "candidate_chronology_value": chronology_value,
        "revision": int(row[8]),
    }


def _valid_identity_set(reader: Any, import_run_id: str) -> set[str]:
    rows = reader.execute(
        "SELECT DISTINCT canonical_primary_id FROM source_observations "
        "WHERE import_run_id=? AND source_family='advanced_search_sr' "
        "AND entity_kind='service_request' AND identity_state='valid' "
        "ORDER BY canonical_primary_id ASC",
        (import_run_id,),
    ).fetchall()
    identities: set[str] = set()
    for row in rows:
        if row[0] is None:
            raise IntegrityFailure("valid Advanced Search population row has no canonical SR identity")
        identities.add(validate_official_sr_no(str(row[0])))
    return identities


def _resolve_prior_population_run(reader: Any) -> str | None:
    checkpoint = reader.execute(
        "SELECT source_profile_id,accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
        "accepted_logical_fingerprint_sha256,accepted_import_run_id "
        "FROM import_source_checkpoints WHERE source_family='advanced_search_sr'",
    ).fetchone()
    if checkpoint is None:
        return None
    source_profile_id = str(checkpoint[0])
    chronology_kind = str(checkpoint[1])
    chronology_value = int(checkpoint[2])
    fingerprint = _require_sha256(str(checkpoint[3]), label="Advanced Search checkpoint fingerprint")
    checkpoint_run_id = require_uuid4(str(checkpoint[4]))
    checkpoint_run = reader.execute(
        "SELECT source_family,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_chronology_kind,candidate_chronology_value,logical_fingerprint_sha256,run_state "
        "FROM import_runs WHERE import_run_id=?",
        (checkpoint_run_id,),
    ).fetchone()
    if checkpoint_run is None:
        raise IntegrityFailure("Advanced Search checkpoint points to a missing import run")
    if (
        str(checkpoint_run[0]) != _SOURCE_FAMILY
        or str(checkpoint_run[1]) != source_profile_id
        or str(checkpoint_run[5]) != chronology_kind
        or int(checkpoint_run[6]) != chronology_value
        or checkpoint_run[7] is None
        or str(checkpoint_run[7]) != fingerprint
        or str(checkpoint_run[8]) not in _CHECKPOINT_RUN_STATES
    ):
        raise IntegrityFailure("Advanced Search checkpoint authority disagrees with its accepted run")
    if chronology_value < 0:
        raise IntegrityFailure("Advanced Search checkpoint chronology is invalid")

    profile_ids = tuple(str(checkpoint_run[index]) for index in range(1, 5))
    placeholders = ",".join("?" for _ in _FINAL_ROW_BEARING_STATES)
    sql = (
        "SELECT r.import_run_id,r.candidate_chronology_value FROM import_runs r "
        "WHERE r.source_family='advanced_search_sr' AND r.source_profile_id=? "
        "AND r.header_registry_id=? AND r.vocabulary_registry_id=? AND r.parser_profile_id=? "
        "AND r.candidate_chronology_kind=? AND r.candidate_chronology_value<=? "
        "AND r.logical_fingerprint_sha256=? AND r.run_state IN ("
        + placeholders
        + ") AND EXISTS (SELECT 1 FROM source_observations o WHERE o.import_run_id=r.import_run_id) "
        "ORDER BY r.candidate_chronology_value DESC,r.import_run_id ASC LIMIT 1"
    )
    rows = reader.execute(
        sql,
        (
            *profile_ids,
            chronology_kind,
            chronology_value,
            fingerprint,
            *_FINAL_ROW_BEARING_STATES,
        ),
    ).fetchall()
    if not rows:
        raise IntegrityFailure(
            "Advanced Search checkpoint has no row-bearing published representative for its logical population"
        )
    return require_uuid4(str(rows[0][0]))


def build_advanced_search_sr_disappearance_proposals(
    reader: Any,
    *,
    import_run_id: str,
    logical_fingerprint_sha256: str,
    sr_reader: ServiceRequestImportReader | None = None,
) -> tuple[PopulationAbsenceProposalDraft, ...]:
    current_run_id = require_uuid4(import_run_id)
    current_run = _current_run_authority(reader, current_run_id)
    current_fingerprint = _require_sha256(
        logical_fingerprint_sha256,
        label="Advanced Search current logical fingerprint",
    )
    current_identities = _valid_identity_set(reader, current_run_id)
    prior_run_id = _resolve_prior_population_run(reader)
    if prior_run_id is None:
        return ()

    prior_rows = reader.execute(
        "SELECT canonical_primary_id,MIN(source_observation_id) "
        "FROM source_observations WHERE import_run_id=? AND source_family='advanced_search_sr' "
        "AND entity_kind='service_request' AND identity_state='valid' "
        "GROUP BY canonical_primary_id ORDER BY canonical_primary_id ASC",
        (prior_run_id,),
    ).fetchall()
    authority = ServiceRequestImportReader() if sr_reader is None else sr_reader
    proposals: list[PopulationAbsenceProposalDraft] = []
    for row in prior_rows:
        if row[0] is None or row[1] is None:
            raise IntegrityFailure("prior Advanced Search population contains incomplete SR evidence")
        sr_no = validate_official_sr_no(str(row[0]))
        if sr_no in current_identities:
            continue
        prior_observation_id = require_uuid4(str(row[1]))
        prior_evidence = reader.execute(
            "SELECT canonical_primary_id,row_logical_sha256 FROM source_observations "
            "WHERE source_observation_id=? AND import_run_id=? AND source_family='advanced_search_sr' "
            "AND entity_kind='service_request' AND identity_state='valid'",
            (prior_observation_id, prior_run_id),
        ).fetchone()
        if prior_evidence is None or prior_evidence[0] is None or str(prior_evidence[0]) != sr_no:
            raise IntegrityFailure("prior Advanced Search population representative disagrees with SR identity")
        prior_row_hash = _require_sha256(
            str(prior_evidence[1]),
            label="prior Advanced Search row fingerprint",
        )
        target = authority.get_by_official(reader, sr_no)
        if target is None:
            continue
        target_id = target.get("service_request_id")
        if not isinstance(target_id, str) or target.get("official_sr_no") != sr_no:
            raise IntegrityFailure("Service Request import reader returned invalid disappearance target identity")
        service_request_id = require_uuid4(target_id)
        presence = authority.current_source_presence(reader, service_request_id, _SOURCE_FAMILY)
        if presence.warning_active:
            continue
        base_token = _require_sha256(
            authority.source_presence_base_token(reader, service_request_id, _SOURCE_FAMILY),
            label="Service Request source-presence base token",
        )
        if base_token != presence.base_token_sha256:
            raise IntegrityFailure("Service Request source-presence reader returned inconsistent base authority")
        change = ProposalChangeDraft(
            ordinal=0,
            field_key="source_presence",
            change_kind="absent",
            value_kind="identity",
            before_text=sr_no,
            after_text=None,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=None,
        )
        proposal_fingerprint = sha256_canonical_json(
            {
                "schema": _PROPOSAL_FINGERPRINT_SCHEMA,
                "source": {
                    **current_run,
                    "logical_fingerprint_sha256": current_fingerprint,
                    "prior_population_import_run_id": prior_run_id,
                    "prior_source_observation_id": prior_observation_id,
                    "prior_canonical_primary_id": sr_no,
                    "prior_row_logical_sha256": prior_row_hash,
                },
                "proposal": {
                    "proposal_kind": "sr_source_disappearance_review",
                    "evidence_mode": "population_absence",
                    "risk_class": "high",
                    "target_kind": "source_presence",
                    "target_internal_id": service_request_id,
                    "target_business_id": sr_no,
                    "source_presence_base_token": base_token,
                },
                "changes": [change.fingerprint_object()],
            }
        )
        proposals.append(
            PopulationAbsenceProposalDraft(
                import_run_id=current_run_id,
                prior_source_observation_id=prior_observation_id,
                target_internal_id=service_request_id,
                target_business_id=sr_no,
                base_state_token_sha256=base_token,
                proposal_fingerprint_sha256=proposal_fingerprint,
                changes=(change,),
            )
        )
    return tuple(proposals)
