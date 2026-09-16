from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..repositories.proposals import ProposalRepository
from ..repositories.runs import SourceCheckpointRepository, SourceCheckpointState


_SOURCE_FAMILIES = frozenset({"advanced_search_sr", "rfc_enhanced", "wfm_service_provider"})
_RUN_STATES = frozenset(
    {
        "discovering",
        "validating",
        "staged",
        "waiting_review",
        "partially_accepted",
        "accepted",
        "rejected",
        "noop_pending_checkpoint",
        "noop",
        "recovery_required",
        "failed",
    }
)
_PUBLISHED_STATES = frozenset(
    {"staged", "waiting_review", "partially_accepted", "accepted", "rejected", "noop_pending_checkpoint", "noop", "recovery_required"}
)
_RUN_SELECT = (
    "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,"
    "vocabulary_registry_id,parser_profile_id,candidate_filename,candidate_chronology_kind,"
    "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
    "observed_row_count,valid_identity_count,invalid_row_count,warning_count,proposal_count,"
    "pending_proposal_count,accepted_proposal_count,rejected_proposal_count,deferred_proposal_count,revision"
)
_QUERY_ID = "ListImportRuns"
_SORT_ID = "IMPORT_RUN_STARTED_ID_DESC_V1"
_FILTER_SCHEMA = "SOMA_IMPORT_RUN_LIST_FILTER_V1"


@dataclass(frozen=True, slots=True)
class ImportRunSummary:
    import_run_id: str
    source_family: str
    invocation_kind: str
    profiles: dict[str, str]
    candidate_filename: str
    candidate_chronology_kind: str
    candidate_chronology_value: int
    logical_fingerprint: str | None
    run_state: str
    started_at_utc: int
    counts: dict[str, int]
    revision: int

    def to_response(self) -> dict[str, object]:
        return {
            "import_run_id": self.import_run_id,
            "source_family": self.source_family,
            "invocation_kind": self.invocation_kind,
            "profiles": dict(self.profiles),
            "candidate_filename": self.candidate_filename,
            "candidate_chronology_kind": self.candidate_chronology_kind,
            "candidate_chronology_value": self.candidate_chronology_value,
            "logical_fingerprint": self.logical_fingerprint,
            "run_state": self.run_state,
            "counts": dict(self.counts),
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class ImportRunPage:
    items: tuple[ImportRunSummary, ...]
    next_cursor: dict[str, object] | None

    def to_response(self) -> dict[str, object]:
        return {"items": [item.to_response() for item in self.items], "next_cursor": self.next_cursor}


@dataclass(frozen=True, slots=True)
class ImportRunDetail:
    run: ImportRunSummary
    checkpoint_comparison: dict[str, object] | None
    review_state: dict[str, object]

    def to_response(self) -> dict[str, object]:
        return {
            "run": self.run.to_response(),
            "checkpoint_comparison": self.checkpoint_comparison,
            "review_state": self.review_state,
        }


def run_summary_from_row(row: Any) -> ImportRunSummary:
    fingerprint = None if row[10] is None else str(row[10])
    if fingerprint is not None and len(fingerprint) != 64:
        raise IntegrityFailure("import run logical fingerprint is invalid")
    return ImportRunSummary(
        import_run_id=require_uuid4(str(row[0])),
        source_family=str(row[1]),
        invocation_kind=str(row[2]),
        profiles={
            "source_profile_id": str(row[3]),
            "header_registry_id": str(row[4]),
            "vocabulary_registry_id": str(row[5]),
            "parser_profile_id": str(row[6]),
        },
        candidate_filename=str(row[7]),
        candidate_chronology_kind=str(row[8]),
        candidate_chronology_value=int(row[9]),
        logical_fingerprint=fingerprint,
        run_state=str(row[11]),
        started_at_utc=int(row[12]),
        counts={
            "observed": int(row[13]),
            "valid_identity": int(row[14]),
            "invalid": int(row[15]),
            "warning": int(row[16]),
            "proposal": int(row[17]),
            "pending": int(row[18]),
            "accepted": int(row[19]),
            "rejected": int(row[20]),
            "deferred": int(row[21]),
        },
        revision=int(row[22]),
    )


def checkpoint_summary(checkpoint: SourceCheckpointState | None) -> dict[str, object] | None:
    if checkpoint is None:
        return None
    return {
        "source_family": checkpoint.source_family,
        "chronology_kind": checkpoint.chronology_kind,
        "chronology_value": checkpoint.chronology_value,
        "logical_fingerprint": checkpoint.logical_fingerprint,
        "import_run_id": checkpoint.accepted_import_run_id,
        "revision": checkpoint.revision,
    }


def checkpoint_comparison(
    run: ImportRunSummary,
    checkpoint: SourceCheckpointState | None,
) -> dict[str, object] | None:
    if run.logical_fingerprint is None or run.run_state not in _PUBLISHED_STATES:
        return None
    candidate = {
        "chronology_kind": run.candidate_chronology_kind,
        "chronology_value": run.candidate_chronology_value,
        "logical_fingerprint": run.logical_fingerprint,
        "import_run_id": run.import_run_id,
    }
    if checkpoint is None:
        return {"classification": "first_source", "candidate": candidate, "checkpoint": None}
    if run.profiles["source_profile_id"] != checkpoint.source_profile_id:
        raise IntegrityFailure("import run and checkpoint source profiles disagree")
    if run.candidate_chronology_kind != checkpoint.chronology_kind:
        raise IntegrityFailure("import run and checkpoint chronology kinds disagree")
    checkpoint_side = {
        "chronology_kind": checkpoint.chronology_kind,
        "chronology_value": checkpoint.chronology_value,
        "logical_fingerprint": checkpoint.logical_fingerprint,
        "import_run_id": checkpoint.accepted_import_run_id,
    }
    if run.candidate_chronology_value > checkpoint.chronology_value:
        classification = "newer_identical" if run.logical_fingerprint == checkpoint.logical_fingerprint else "newer_changed"
    elif run.candidate_chronology_value < checkpoint.chronology_value:
        classification = "older_source"
    elif run.logical_fingerprint == checkpoint.logical_fingerprint:
        classification = "exact_replay"
    else:
        classification = "equal_chronology_changed"
    return {"classification": classification, "candidate": candidate, "checkpoint": checkpoint_side}


class ImportRunQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _filters(source_family: str | None, state: str | None) -> tuple[str | None, str | None]:
        if source_family is not None and source_family not in _SOURCE_FAMILIES:
            raise SomaError("IMPORT_SOURCE_FAMILY_INVALID", "source family is outside the closed LLD-04 registry")
        if state is not None and state not in _RUN_STATES:
            raise ValidationError("state is outside the import-run vocabulary")
        return source_family, state

    @staticmethod
    def _limit(limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError("import run page size must be an integer from 1 through 100")
        return limit

    @staticmethod
    def _cursor(
        cursor: dict[str, object] | None,
        *,
        filter_fingerprint: str,
    ) -> tuple[int, str] | None:
        if cursor is None:
            return None
        if not isinstance(cursor, dict) or set(cursor) != {
            "version", "query_id", "sort_registry_id", "last_key_tuple", "filter_fingerprint", "null_order"
        }:
            raise SomaError("IMPORT_CURSOR_INVALID", "import run cursor fields are invalid")
        if (
            cursor["version"] != 1
            or cursor["query_id"] != _QUERY_ID
            or cursor["sort_registry_id"] != _SORT_ID
            or cursor["null_order"] != "none"
            or cursor["filter_fingerprint"] != filter_fingerprint
        ):
            raise SomaError("IMPORT_CURSOR_INVALID", "import run cursor contract is invalid")
        key = cursor["last_key_tuple"]
        if not isinstance(key, list) or len(key) != 2 or type(key[0]) is not int or key[0] < 0:
            raise SomaError("IMPORT_CURSOR_INVALID", "import run cursor key is invalid")
        try:
            run_id = require_uuid4(str(key[1]))
        except ValidationError as exc:
            raise SomaError("IMPORT_CURSOR_INVALID", "import run cursor key is invalid") from exc
        return int(key[0]), run_id

    def list_runs(
        self,
        *,
        source_family: str | None = None,
        state: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> ImportRunPage:
        family, run_state = self._filters(source_family, state)
        page_limit = self._limit(limit)
        filter_fingerprint = sha256_canonical_json(
            {"schema": _FILTER_SCHEMA, "source_family": family, "state": run_state}
        )
        after = self._cursor(cursor, filter_fingerprint=filter_fingerprint)
        predicates: list[str] = []
        parameters: list[object] = []
        if family is not None:
            predicates.append("source_family=?")
            parameters.append(family)
        if run_state is not None:
            predicates.append("run_state=?")
            parameters.append(run_state)
        if after is not None:
            predicates.append("(started_at_utc<? OR (started_at_utc=? AND import_run_id<?))")
            parameters.extend((after[0], after[0], after[1]))
        where = " WHERE " + " AND ".join(predicates) if predicates else ""
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                f"SELECT {_RUN_SELECT} FROM import_runs{where} "
                "ORDER BY started_at_utc DESC,import_run_id DESC LIMIT ?",
                (*parameters, page_limit + 1),
            ).fetchall()
        has_more = len(rows) > page_limit
        page_rows = rows[:page_limit]
        items = tuple(run_summary_from_row(row) for row in page_rows)
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = {
                "version": 1,
                "query_id": _QUERY_ID,
                "sort_registry_id": _SORT_ID,
                "last_key_tuple": [last.started_at_utc, last.import_run_id],
                "filter_fingerprint": filter_fingerprint,
                "null_order": "none",
            }
        return ImportRunPage(items=items, next_cursor=next_cursor)

    def get_run(self, import_run_id: str) -> ImportRunDetail:
        run_id = require_uuid4(import_run_id)
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                f"SELECT {_RUN_SELECT} FROM import_runs WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
            run = run_summary_from_row(row)
            checkpoint = SourceCheckpointRepository.get(snapshot.connection, run.source_family)
            recovery_authorized = False
            if run.run_state == "recovery_required":
                decision_run = ProposalRepository.get_run(snapshot.connection, run_id)
                fingerprint = ProposalRepository.recovery_review_fingerprint(snapshot.connection, decision_run)
                review = snapshot.connection.execute(
                    "SELECT review_fingerprint_sha256,decision FROM import_recovery_reviews "
                    "WHERE import_run_id=? ORDER BY review_ordinal DESC LIMIT 1",
                    (run_id,),
                ).fetchone()
                recovery_authorized = bool(
                    review is not None and str(review[0]) == fingerprint and str(review[1]) == "authorized"
                )
            can_finalize = (
                run.counts["pending"] == 0
                and run.run_state in {"staged", "waiting_review", "recovery_required"}
                and (run.run_state != "recovery_required" or recovery_authorized)
            )
            return ImportRunDetail(
                run=run,
                checkpoint_comparison=checkpoint_comparison(run, checkpoint),
                review_state={
                    "pending": run.counts["pending"],
                    "accepted": run.counts["accepted"],
                    "rejected": run.counts["rejected"],
                    "deferred": run.counts["deferred"],
                    "can_finalize": can_finalize,
                    "recovery_authorized": recovery_authorized,
                },
            )


__all__ = [
    "ImportRunDetail",
    "ImportRunPage",
    "ImportRunQueryService",
    "ImportRunSummary",
    "checkpoint_comparison",
    "checkpoint_summary",
    "run_summary_from_row",
]
