from __future__ import annotations

from functools import lru_cache

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import loads_strict

from soma.communications.contracts.common import Chronology, TARGET_TYPES, TrackableIdentity, closed
from soma.communications.contracts.jobs import CommunicationExecutionConfig, CommunicationJobScope, bound_from_value
from soma.communications.domain.summaries import identity_evidence, summary_direction
from soma.communications.queries.communications import list_communications_in_reader
from soma.communications.queries.coverage import coverage_in_reader
from soma.communications.repositories.summaries import frozen_in_reader


def _target(target_type, target_id):
    if not isinstance(target_type, str) or target_type not in TARGET_TYPES:
        raise ValidationError("Communication summary target type is invalid")
    require_uuid4(target_id)


def _run_identity_evidence(reader, job_id, target_type, target_id):
    rows = reader.connection.execute(
        "SELECT target_revision,identity_kind,token,effective_known,effective_utc,effective_source "
        "FROM communication_match_tokens WHERE target_type=? AND target_id=? AND job_id=? ORDER BY export_ordinal",
        (target_type, target_id, job_id),
    )
    return identity_evidence(TrackableIdentity(target_type, target_id, revision, kind, token,
        Chronology(bool(known), instant, source)) for revision, kind, token, known, instant, source in rows)


def target_coverage_in_reader(reader, identity_providers, target_type, target_id):
    """Reduce recorded ranges; no mail IO, owner-table access or wall-clock inference.

    Memory is bounded by one range and a 128-job local evidence cache. Complete
    intervals are consumed in indexed lower-time order and merged incrementally.
    Current identity evidence is streamed once, never cached across snapshots.
    """
    expected = identity_evidence(identity_providers.target_snapshot(reader, target_type, target_id))
    if not expected[1] or not reader.connection.execute("SELECT 1 FROM communication_historical_coverage_segments LIMIT 1").fetchone():
        return "UNKNOWN"
    eligibility = expected[2]

    @lru_cache(maxsize=128)
    def identity_matches(job_id):
        return _run_identity_evidence(reader, job_id, target_type, target_id) == expected

    source_count, unknown, partial = 0, False, False
    for source_id, revision, adapter_family, adapter_version in reader.connection.execute(
        "SELECT source_scope_id,revision,adapter_family,adapter_version FROM communication_source_scopes ORDER BY source_scope_id"
    ):
        source_count += 1
        folder_count = 0
        for folder_id, folder_key, forward_adapter, forward_state, high_water_ms in reader.connection.execute(
            "SELECT f.source_folder_id,f.provider_folder_key,c.adapter_version,c.state,c.provider_time_source_epoch_ms "
            "FROM communication_source_folders f LEFT JOIN communication_forward_coverage c "
            "ON c.source_scope_id=f.source_scope_id AND c.source_folder_id=f.source_folder_id "
            "WHERE f.source_scope_id=? AND f.enabled=1 ORDER BY f.provider_folder_key LIMIT 65", (source_id,),
        ):
            folder_count += 1
            if folder_count > 64:
                raise IntegrityFailure("Communication summary exceeds the selected-folder bound")
            reached, full, proved, folder_unknown, folder_partial = eligibility, False, False, False, False
            for lower_json, upper_json, state, job_id, scope_json, config_json, reviewed, run_state in reader.connection.execute(
                "SELECT h.lower_bound_json,h.upper_bound_json,h.state,h.job_id,j.scope_json,j.execution_config_json,"
                "j.preview_fingerprint,r.state FROM communication_historical_coverage_segments h "
                "LEFT JOIN communication_job_scopes j ON j.job_id=h.job_id "
                "LEFT JOIN communication_match_runs r ON r.job_id=h.job_id "
                "WHERE h.source_scope_id=? AND h.source_folder_id=? "
                "ORDER BY json_extract(h.lower_bound_json,'$.utc_epoch_seconds'),h.coverage_segment_id", (source_id, folder_id),
            ):
                if scope_json is None:
                    folder_unknown = True
                    continue
                scope = CommunicationJobScope.from_value(loads_strict(scope_json))
                if scope.source_scope_id != source_id or folder_key not in scope.folder_keys:
                    raise IntegrityFailure("Communication coverage contradicts its recorded job scope")
                if scope.target_identity_ids and target_id not in scope.target_identity_ids:
                    continue
                if scope.config_revision != revision:
                    continue
                config = CommunicationExecutionConfig.from_value(loads_strict(config_json))
                if (config.adapter_family != adapter_family or config.adapter_version != adapter_version
                        or run_state != "READY" or not identity_matches(job_id)):
                    folder_unknown = True
                    continue
                lower = bound_from_value(loads_strict(lower_json))
                upper = bound_from_value(loads_strict(upper_json))
                reviewed_full = (scope.job_kind == "DEEP_SCAN" and reviewed is not None and lower is None and upper is None
                                 and scope.lower_bound is None and scope.upper_bound is None)
                known_range = (isinstance(lower, Chronology) and lower.known and isinstance(upper, Chronology)
                               and upper.known and lower.utc_epoch_seconds <= upper.utc_epoch_seconds)
                if not reviewed_full and known_range:
                    # Recorded subranges cannot extend a reviewed job range.
                    # Opaque provider-position scopes need adapter evidence,
                    # rather than an invented time-to-position conversion.
                    if (not isinstance(scope.lower_bound, Chronology) or not scope.lower_bound.known
                            or lower.utc_epoch_seconds < scope.lower_bound.utc_epoch_seconds
                            or (scope.upper_bound is not None and (not isinstance(scope.upper_bound, Chronology)
                                or not scope.upper_bound.known or upper.utc_epoch_seconds > scope.upper_bound.utc_epoch_seconds))):
                        folder_unknown = True
                        continue
                if not reviewed_full and (eligibility is None or not known_range):
                    folder_unknown = True
                    continue
                proved = True
                if state == "UNKNOWN":
                    folder_unknown = True
                elif state == "PARTIAL":
                    folder_partial = True
                elif reviewed_full:
                    full = True
                elif reached is not None and lower.utc_epoch_seconds <= reached:
                    reached = max(reached, upper.utc_epoch_seconds)
            if not proved:
                folder_unknown = True
            if not full:
                if (forward_adapter != adapter_version or forward_state in {None, "NONE", "UNKNOWN"}
                        or high_water_ms is None or eligibility is None):
                    folder_unknown = True
                elif forward_state == "PARTIAL":
                    folder_partial = True
                elif reached is None or reached * 1000 < high_water_ms:
                    # Provider checkpoints keep milliseconds. A whole-second
                    # interval must reach the actual checkpoint, not its floor.
                    folder_unknown = True
            unknown |= folder_unknown
            partial |= folder_partial
        if not folder_count:
            unknown = True
    return "UNKNOWN" if unknown or not source_count else "PARTIAL" if partial else "COMPLETE"


def live_summary_in_reader(reader, identity_providers, target_type, target_id):
    _target(target_type, target_id)
    counts = reader.connection.execute(
        "SELECT coalesce(sum(c.direction='RECEIVED'),0),coalesce(sum(c.direction='SENT'),0),"
        "coalesce(sum(c.direction='UNKNOWN'),0),coalesce(max(c.content_state='RETAINED'),0) "
        "FROM communication_links l JOIN communications c USING(communication_id) "
        "WHERE l.target_type=? AND l.target_id=? AND l.state='ACTIVE'", (target_type, target_id),
    ).fetchone()
    latest = reader.connection.execute(
        "SELECT c.chronology_utc,c.chronology_source_kind FROM communication_links l "
        "INDEXED BY idx_comm_link_target_canonical_order JOIN communications c USING(communication_id) "
        "WHERE l.target_type=? AND l.target_id=? AND l.state='ACTIVE' AND l.canonical_chronology_known=1 "
        "ORDER BY l.canonical_chronology_utc DESC,l.communication_id DESC LIMIT 1", (target_type, target_id),
    ).fetchone()
    chronology, direction = Chronology(False, None, "UNKNOWN"), "UNKNOWN"
    if latest is not None:
        chronology = Chronology(True, latest[0], latest[1])
        tied = reader.connection.execute(
            "SELECT coalesce(sum(c.direction='RECEIVED'),0),coalesce(sum(c.direction='SENT'),0),coalesce(sum(c.direction='UNKNOWN'),0) "
            "FROM communication_links l JOIN communications c USING(communication_id) WHERE l.target_type=? AND l.target_id=? "
            "AND l.state='ACTIVE' AND l.canonical_chronology_known=1 AND l.canonical_chronology_utc=?",
            (target_type, target_id, latest[0]),
        ).fetchone()
        direction = summary_direction(*tied)
    pending = reader.connection.execute("SELECT count(*) FROM communication_proposals WHERE target_type=? AND target_id=? "
        "AND state IN ('PENDING','DEFERRED')", (target_type, target_id)).fetchone()[0]
    coverage = target_coverage_in_reader(reader, identity_providers, target_type, target_id)
    return {"target_type": target_type, "target_id": target_id, "received_count": counts[0], "sent_count": counts[1],
        "unknown_count": counts[2], "last_interaction": chronology.to_response(), "last_direction": direction,
        "pending_proposals": pending, "coverage_state": coverage,
        "warnings": [] if coverage == "COMPLETE" else ["COMM_COVERAGE_INCOMPLETE"], "body_navigation_available": bool(counts[3])}


class CommunicationSummaryProvider:
    def __init__(self, identity_providers):
        self._identities = identity_providers

    @staticmethod
    def terminal_summary(snapshot, target_type, target_id):
        _target(target_type, target_id)
        return frozen_in_reader(snapshot, target_type, target_id)

    @staticmethod
    def source_coverage(snapshot, source_scope_id):
        return coverage_in_reader(snapshot, source_scope_id)

    def entity_summary(self, snapshot, target_type, target_id):
        _target(target_type, target_id)
        frozen = frozen_in_reader(snapshot, target_type, target_id)
        if frozen is not None and not snapshot.connection.execute(
            "SELECT 1 FROM communication_links WHERE target_type=? AND target_id=? AND state='ACTIVE' LIMIT 1",
            (target_type, target_id),
        ).fetchone():
            pending = snapshot.connection.execute("SELECT count(*) FROM communication_proposals WHERE target_type=? AND target_id=? "
                "AND state IN ('PENDING','DEFERRED')", (target_type, target_id)).fetchone()[0]
            revision = self._identities.current_revision(snapshot, target_type, target_id)
            reversed_or_unproved = revision is None or self._identities.validate_reassociation(snapshot, target_type, target_id, revision) != "INVALID"
            coverage = "UNKNOWN" if reversed_or_unproved else frozen["coverage_state"]
            warnings = ["COMM_TERMINAL_FROZEN"]
            if coverage != "COMPLETE":
                warnings.append("COMM_COVERAGE_INCOMPLETE")
            if reversed_or_unproved:
                warnings.append("COMM_RECONSTRUCTION_REQUIRED")
            return {"target_type": target_type, "target_id": target_id,
                **{name: frozen[name] for name in ("received_count", "sent_count", "unknown_count", "last_interaction", "last_direction")},
                "pending_proposals": pending, "coverage_state": coverage, "warnings": sorted(warnings), "body_navigation_available": False}
        return live_summary_in_reader(snapshot, self._identities, target_type, target_id)


class CommunicationPanelProjectionProvider:
    def __init__(self, summary_provider):
        self._summaries = summary_provider

    def panel(self, snapshot, target_type, target_id, cursor=None, limit=50):
        from soma.communications.contracts.common import integer
        _target(target_type, target_id)
        integer(limit, minimum=1, maximum=50)
        summary = self._summaries.entity_summary(snapshot, target_type, target_id)
        frozen = "COMM_TERMINAL_FROZEN" in summary["warnings"]
        messages = list_communications_in_reader(snapshot, {"target_type": target_type, "target_id": target_id,
            "cursor": cursor, "limit": limit})
        return {"summary": summary, "recent_messages": messages, "terminal_frozen": frozen, "warnings": summary["warnings"]}


class SummaryQueries:
    def __init__(self, connection_factory, identity_providers):
        self._factory = connection_factory
        self._provider = CommunicationSummaryProvider(identity_providers)

    def get_entity_summary(self, request):
        item = closed(request, {"target_type", "target_id"})
        with ReadSnapshot(self._factory) as reader:
            return self._provider.entity_summary(reader, **item)
