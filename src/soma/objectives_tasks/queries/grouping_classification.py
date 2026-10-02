"""Snapshot-local exact grouping classification shared by list and detail."""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections import defaultdict
from typing import Any

from soma.foundation.errors import SomaError, IntegrityFailure
from ..domain.grouping import RegroupCandidate
from ..repositories.grouping import RegroupProposalRecord


@dataclass(frozen=True, slots=True)
class Reproduction:
    input_fingerprint: str
    component_start_utc: int
    component_end_utc: int

    @classmethod
    def from_candidate(cls, candidate: RegroupCandidate):
        return cls(candidate.input_fingerprint, candidate.component_start_utc, candidate.component_end_utc)


@dataclass(frozen=True, slots=True)
class Classification:
    candidate: Reproduction | None
    rejection_suppressed: bool

    @property
    def owner_warnings(self) -> tuple[str, ...]:
        return (("GROUPING_PROPOSAL_STALE",) if self.candidate is None else ()) + (
            ("GROUPING_EQUIVALENT_REJECTION",) if self.rejection_suppressed else ())


def classify_page(reader: Any, proposals: tuple[RegroupProposalRecord, ...]) -> dict[str, Classification]:
    from ..services.grouping import GroupingService, _GROUPING_WORKSET_SOFT_THRESHOLD
    if not proposals:
        return {}
    if len(proposals) > 500:
        raise IntegrityFailure("Grouping classification exceeds its owner page bound")
    ids = tuple(item.proposal_id for item in proposals)
    marks = ",".join("?" for _ in ids)
    stale = {str(row[0]) for row in reader.execute(
        f"SELECT h.regroup_proposal_id FROM regroup_proposals h WHERE h.regroup_proposal_id IN ({marks}) AND EXISTS("
        "SELECT 1 FROM regroup_proposal_task_changes c LEFT JOIN tasks t ON t.task_id=c.task_id "
        "LEFT JOIN task_plan_current pc ON pc.task_id=c.task_id "
        "LEFT JOIN objective_task_membership_current m ON m.task_id=c.task_id "
        "WHERE c.regroup_proposal_id=h.regroup_proposal_id AND (t.task_id IS NULL OR pc.task_id IS NULL "
        "OR t.revision<>c.expected_task_revision OR pc.plan_revision_id IS NOT c.expected_current_plan_revision_id "
        "OR m.objective_id IS NOT c.from_objective_id OR m.membership_revision IS NOT c.expected_membership_revision) LIMIT 1)", ids)}
    stale.update(str(row[0]) for row in reader.execute(
        f"SELECT h.regroup_proposal_id FROM regroup_proposals h WHERE h.regroup_proposal_id IN ({marks}) AND EXISTS("
        "SELECT 1 FROM regroup_proposal_objective_changes c LEFT JOIN objectives o ON o.objective_id=c.objective_id "
        "LEFT JOIN objective_envelope_projection e ON e.objective_id=c.objective_id "
        "WHERE c.regroup_proposal_id=h.regroup_proposal_id AND c.objective_id IS NOT NULL AND ("
        "o.objective_id IS NULL OR o.superseded_by_objective_id IS NOT NULL OR e.objective_id IS NULL "
        "OR c.expected_objective_revision IS NULL OR c.expected_envelope_revision IS NULL "
        "OR o.revision<>c.expected_objective_revision OR e.revision<>c.expected_envelope_revision) LIMIT 1)", ids))
    suppressed = {str(row[0]) for row in reader.execute(
        f"SELECT h.regroup_proposal_id FROM regroup_proposals h WHERE h.regroup_proposal_id IN ({marks}) AND EXISTS("
        "SELECT 1 FROM regroup_rejection_events r WHERE r.input_fingerprint=h.input_fingerprint "
        "AND r.reconsidered_at_utc IS NULL LIMIT 1)", ids)}
    remaining = tuple(item for item in proposals if item.proposal_id not in stale)
    candidates: dict[str, Reproduction] = {}
    if remaining:
        # Exact reproduction needs global grouping authority. The existing
        # synchronous grouping threshold bounds resident supporting material;
        # exceeding it is indeterminate, never a fabricated clear warning set.
        for table in ("tasks", "objectives"):
            if int(reader.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) > _GROUPING_WORKSET_SOFT_THRESHOLD:
                raise SomaError("GROUPING_INDETERMINATE", "Exact list classification requires deferred grouping work")
        snapshot = GroupingService._load_snapshot(reader)
        ordinary = tuple(item for item in remaining if item.proposal_kind != "manual_merge")
        if ordinary:
            base = GroupingService._candidates(reader, origin=ordinary[0].origin, _snapshot=snapshot)
            wanted = {(item.proposal_kind, item.input_fingerprint): item.proposal_id for item in ordinary}
            matches: dict[tuple[str, str], list[RegroupCandidate]] = defaultdict(list)
            for origin in sorted({item.origin for item in ordinary}):
                for candidate in base:
                    current = replace(candidate, origin=origin)
                    key = (current.proposal_kind, current.input_fingerprint)
                    if key in wanted:
                        matches[key].append(current)
            for item in ordinary:
                match = matches.get((item.proposal_kind, item.input_fingerprint), [])
                if len(match) == 1:
                    candidates[item.proposal_id] = Reproduction.from_candidate(match[0])
        manual = tuple(item for item in remaining if item.proposal_kind == "manual_merge")
        if manual:
            candidates.update(_manual_candidates(reader, manual, snapshot))
    return {item.proposal_id: Classification(candidates.get(item.proposal_id), item.proposal_id in suppressed)
            for item in proposals}


def _manual_candidates(reader, proposals, snapshot):
    from ..services.grouping import GroupingService, _ManualGroupingAuthority, _GROUPING_WORKSET_SOFT_THRESHOLD
    ids = tuple(item.proposal_id for item in proposals)
    marks = ",".join("?" for _ in ids)
    scopes = {str(row[0]): (str(row[2]), str(row[3])) for row in reader.execute(
        "SELECT regroup_proposal_id,COUNT(*),MIN(objective_id),MAX(objective_id),COUNT(DISTINCT objective_id) "
        f"FROM regroup_proposal_objective_changes WHERE regroup_proposal_id IN ({marks}) "
        "AND objective_id IS NOT NULL AND action IN ('retain','supersede') GROUP BY regroup_proposal_id", ids)
        if int(row[1]) == 2 and int(row[4]) == 2}
    objective_ids = sorted({identity for pair in scopes.values() for identity in pair})
    counts, members = {}, defaultdict(list)
    for offset in range(0, len(objective_ids), 500):
        chunk = objective_ids[offset:offset + 500]
        placeholders = ",".join("?" for _ in chunk)
        counts.update((str(row[0]), int(row[1])) for row in reader.execute(
            f"SELECT objective_id,COUNT(*) FROM objective_task_membership_current WHERE objective_id IN ({placeholders}) GROUP BY objective_id", chunk))
        for row in reader.execute(
            "SELECT t.task_id,t.revision,pc.plan_revision_id,pc.revision,p.start_utc,p.end_utc,"
            "m.objective_id,m.accepted_plan_revision_id,m.membership_revision,COALESCE(l.explicit_membership_lock,0),"
            "COALESCE(x.execution_state,'not_started'),oc.accepted_outcome,COALESCE(sp.provider_lifecycle_class,'unknown') "
            "FROM objective_task_membership_current m JOIN tasks t ON t.task_id=m.task_id "
            "JOIN task_plan_current pc ON pc.task_id=t.task_id JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id AND p.task_id=t.task_id "
            "LEFT JOIN task_lock_projection l ON l.task_id=t.task_id LEFT JOIN task_execution_projection x ON x.task_id=t.task_id "
            "LEFT JOIN task_outcome_current oc ON oc.task_id=t.task_id LEFT JOIN wfm_source_projection_cache sp ON sp.task_id=t.task_id "
            f"WHERE m.objective_id IN ({placeholders}) ORDER BY m.objective_id,t.task_id", chunk):
            members[str(row[6])].append(row)
    if sum(sum(counts.get(identity,0) for identity in pair) for pair in set(scopes.values())) > _GROUPING_WORKSET_SOFT_THRESHOLD:
        raise SomaError("GROUPING_INDETERMINATE", "Exact manual page classification requires deferred grouping work")
    scopes_with_envelopes = []
    for proposal_id, pair in scopes.items():
        objectives = [snapshot.objectives.get(identity) for identity in pair]
        if all(item is not None for item in objectives):
            scopes_with_envelopes.append((proposal_id, *pair, min(item.start_utc for item in objectives), max(item.end_utc for item in objectives)))
    neighbors = set()
    for offset in range(0, len(scopes_with_envelopes), 128):
        chunk = scopes_with_envelopes[offset:offset + 128]
        values = ",".join("(?,?,?,?,?)" for _ in chunk)
        neighbors.update(str(row[0]) for row in reader.execute(
            f"WITH scopes(id,left_id,right_id,start_utc,end_utc) AS (VALUES {values}) SELECT id FROM scopes s WHERE EXISTS("
            "SELECT 1 FROM objectives o JOIN objective_envelope_projection e ON e.objective_id=o.objective_id "
            "WHERE o.superseded_by_objective_id IS NULL AND o.objective_id NOT IN (s.left_id,s.right_id) "
            "AND e.start_utc<s.end_utc AND e.end_utc>s.start_utc)", tuple(value for row in chunk for value in row)))
    results, cache = {}, {}
    for proposal in proposals:
        pair = scopes.get(proposal.proposal_id)
        if pair is None:
            continue
        key = (pair, proposal.origin, proposal.proposal_id in neighbors)
        if key not in cache:
            objects = sorted((snapshot.objectives[identity] for identity in pair if identity in snapshot.objectives), key=lambda item: (item.tracking_sequence,item.objective_id))
            rows = tuple((item.objective_id,item.tracking_sequence,item.revision,item.envelope_revision,item.start_utc,item.end_utc,item.execution_state,item.creation_origin) for item in objects)
            authority = _ManualGroupingAuthority(rows, proposal.proposal_id in neighbors,
                tuple((identity,counts[identity]) for identity in pair if identity in counts),
                tuple(row for identity in pair for row in members[identity]),snapshot.competing_task_ids)
            try:
                candidate = GroupingService._manual_exact_touch_candidate(reader,objective_ids=pair,origin=proposal.origin,_authority=authority)
                cache[key] = Reproduction.from_candidate(candidate)
            except SomaError as exc:
                if exc.code not in {"GROUPING_INDETERMINATE", "GROUPING_PROPOSAL_STALE", "VALIDATION_FAILED"}:
                    raise
                cache[key] = None
        candidate = cache[key]
        if candidate is not None and candidate.input_fingerprint == proposal.input_fingerprint:
            results[proposal.proposal_id] = candidate
    return results
