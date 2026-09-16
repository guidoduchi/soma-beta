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
    {
        "staged",
        "waiting_review",
        "partially_accepted",
        "accepted",
        "rejected",
        "noop_pending_checkpoint",
        "noop",
        "recovery_required",
    }
)
_FINDING_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "high_risk": 3}
_FINDING_SCOPES = frozenset(
    {"workbook", "sheet", "row", "field", "identity", "chronology", "replay", "proposal", "population"}
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
_OBSERVATION_QUERY_ID = "ListPublishedSourceObservations"
_OBSERVATION_SORT_ID = "IMPORT_OBSERVATION_ROW_ASC_V1"
_OBSERVATION_FILTER_SCHEMA = "SOMA_IMPORT_OBSERVATION_LIST_FILTER_V1"
_FINDING_QUERY_ID = "ListImportFindings"
_FINDING_SORT_ID = "IMPORT_FINDING_SEVERITY_ID_ASC_V1"
_FINDING_FILTER_SCHEMA = "SOMA_IMPORT_FINDING_LIST_FILTER_V1"


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


@dataclass(frozen=True, slots=True)
class PublishedObservationField:
    source_observation_field_id: str
    field_key: str
    field_class: str
    value_state: str
    value_kind: str
    display_value: str | int | None

    def to_response(self) -> dict[str, object]:
        return {
            "source_observation_field_id": self.source_observation_field_id,
            "field_key": self.field_key,
            "field_class": self.field_class,
            "value_state": self.value_state,
            "value_kind": self.value_kind,
            "display_value": self.display_value,
        }


@dataclass(frozen=True, slots=True)
class PublishedObservation:
    source_observation_id: str
    source_family: str
    entity_kind: str
    identity_state: str
    canonical_primary_id: str | None
    canonical_parent_rfc_no: str | None
    sheet_ordinal: int
    row_ordinal: int
    source_row_chronology_utc: int | None
    fields: tuple[PublishedObservationField, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "source_observation_id": self.source_observation_id,
            "source_family": self.source_family,
            "entity_kind": self.entity_kind,
            "identity_state": self.identity_state,
            "canonical_primary_id": self.canonical_primary_id,
            "canonical_parent_rfc_no": self.canonical_parent_rfc_no,
            "row_locator": {"sheet_ordinal": self.sheet_ordinal, "row_ordinal": self.row_ordinal},
            "source_row_chronology_utc": self.source_row_chronology_utc,
            "fields": [field.to_response() for field in self.fields],
        }


@dataclass(frozen=True, slots=True)
class ObservationPage:
    items: tuple[PublishedObservation, ...]
    next_cursor: dict[str, object] | None

    def to_response(self) -> dict[str, object]:
        return {"items": [item.to_response() for item in self.items], "next_cursor": self.next_cursor}


@dataclass(frozen=True, slots=True)
class ImportFinding:
    import_finding_id: str
    finding_code: str
    severity: str
    scope_kind: str
    message_text: str
    source_observation_id: str | None
    field_key: str | None
    severity_rank: int

    def to_response(self) -> dict[str, object]:
        return {
            "import_finding_id": self.import_finding_id,
            "finding_code": self.finding_code,
            "severity": self.severity,
            "scope_kind": self.scope_kind,
            "message_text": self.message_text,
            "source_observation_id": self.source_observation_id,
            "field_key": self.field_key,
        }


@dataclass(frozen=True, slots=True)
class FindingPage:
    items: tuple[ImportFinding, ...]
    next_cursor: dict[str, object] | None

    def to_response(self) -> dict[str, object]:
        return {"items": [item.to_response() for item in self.items], "next_cursor": self.next_cursor}


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


def _page_limit(limit: int, *, label: str) -> int:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError(f"{label} page size must be an integer from 1 through 100")
    return limit


def _require_run_state(reader: Any, import_run_id: str) -> str:
    row = reader.execute("SELECT run_state FROM import_runs WHERE import_run_id=?", (import_run_id,)).fetchone()
    if row is None:
        raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
    state = str(row[0])
    if state not in _RUN_STATES:
        raise IntegrityFailure("persisted import run state is outside the closed LLD-04 vocabulary")
    return state


def _observation_cursor(
    cursor: dict[str, object] | None,
    *,
    filter_fingerprint: str,
) -> tuple[int, int, str] | None:
    if cursor is None:
        return None
    expected_fields = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if not isinstance(cursor, dict) or set(cursor) != expected_fields:
        raise SomaError("IMPORT_CURSOR_INVALID", "observation cursor fields are invalid")
    if (
        cursor["version"] != 1
        or cursor["query_id"] != _OBSERVATION_QUERY_ID
        or cursor["sort_registry_id"] != _OBSERVATION_SORT_ID
        or cursor["null_order"] != "none"
        or cursor["filter_fingerprint"] != filter_fingerprint
    ):
        raise SomaError("IMPORT_CURSOR_INVALID", "observation cursor contract is invalid")
    key = cursor["last_key_tuple"]
    if (
        not isinstance(key, list)
        or len(key) != 3
        or type(key[0]) is not int
        or key[0] < 1
        or type(key[1]) is not int
        or key[1] < 1
    ):
        raise SomaError("IMPORT_CURSOR_INVALID", "observation cursor key is invalid")
    try:
        observation_id = require_uuid4(str(key[2]))
    except ValidationError as exc:
        raise SomaError("IMPORT_CURSOR_INVALID", "observation cursor key is invalid") from exc
    return int(key[0]), int(key[1]), observation_id


def _finding_cursor(
    cursor: dict[str, object] | None,
    *,
    filter_fingerprint: str,
) -> tuple[int, str] | None:
    if cursor is None:
        return None
    expected_fields = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if not isinstance(cursor, dict) or set(cursor) != expected_fields:
        raise SomaError("IMPORT_CURSOR_INVALID", "finding cursor fields are invalid")
    if (
        cursor["version"] != 1
        or cursor["query_id"] != _FINDING_QUERY_ID
        or cursor["sort_registry_id"] != _FINDING_SORT_ID
        or cursor["null_order"] != "none"
        or cursor["filter_fingerprint"] != filter_fingerprint
    ):
        raise SomaError("IMPORT_CURSOR_INVALID", "finding cursor contract is invalid")
    key = cursor["last_key_tuple"]
    if (
        not isinstance(key, list)
        or len(key) != 2
        or type(key[0]) is not int
        or key[0] not in _FINDING_SEVERITY_RANK.values()
    ):
        raise SomaError("IMPORT_CURSOR_INVALID", "finding cursor key is invalid")
    try:
        finding_id = require_uuid4(str(key[1]))
    except ValidationError as exc:
        raise SomaError("IMPORT_CURSOR_INVALID", "finding cursor key is invalid") from exc
    return int(key[0]), finding_id


def _display_field_value(row: Any) -> str | int | None:
    value_state = str(row[3])
    value_kind = str(row[4])
    source_text = None if row[5] is None else str(row[5])
    normalized_text = None if row[6] is None else str(row[6])
    integer_value = None if row[7] is None else int(row[7])
    if value_state not in {"usable", "blank", "unknown", "malformed"}:
        raise IntegrityFailure("persisted source observation field value_state is invalid")
    if value_kind not in {"text", "controlled", "instant", "duration_seconds"}:
        raise IntegrityFailure("persisted source observation field value_kind is invalid")
    if value_state == "blank":
        return None
    if value_state in {"unknown", "malformed"}:
        return source_text
    if value_kind in {"text", "controlled"}:
        if normalized_text is None:
            raise IntegrityFailure("usable text source field has no normalized display authority")
        return normalized_text
    if integer_value is None:
        raise IntegrityFailure("usable numeric source field has no integer display authority")
    return integer_value


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
        return _page_limit(limit, label="import run")

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

    def list_published_observations(
        self,
        import_run_id: str,
        *,
        identity_state: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> ObservationPage:
        run_id = require_uuid4(import_run_id)
        if identity_state is not None and identity_state not in {"valid", "invalid"}:
            raise ValidationError("identity_state must be valid, invalid, or null")
        page_limit = _page_limit(limit, label="observation")
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": _OBSERVATION_FILTER_SCHEMA,
                "import_run_id": run_id,
                "identity_state": identity_state,
            }
        )
        after = _observation_cursor(cursor, filter_fingerprint=filter_fingerprint)

        predicates = ["import_run_id=?"]
        parameters: list[object] = [run_id]
        if identity_state is not None:
            predicates.append("identity_state=?")
            parameters.append(identity_state)
        if after is not None:
            predicates.append(
                "(sheet_ordinal>? OR (sheet_ordinal=? AND "
                "(row_ordinal>? OR (row_ordinal=? AND source_observation_id>?))))"
            )
            parameters.extend((after[0], after[0], after[1], after[1], after[2]))
        where = " AND ".join(predicates)

        with ReadSnapshot(self._factory) as snapshot:
            state = _require_run_state(snapshot.connection, run_id)
            if state not in _PUBLISHED_STATES:
                raise SomaError("IMPORT_RUN_UNPUBLISHED", "import run has no published observation authority")
            rows = snapshot.connection.execute(
                "SELECT source_observation_id,source_family,entity_kind,identity_state,canonical_primary_id,"
                "canonical_parent_rfc_no,sheet_ordinal,row_ordinal,source_row_chronology_utc "
                f"FROM source_observations WHERE {where} "
                "ORDER BY sheet_ordinal ASC,row_ordinal ASC,source_observation_id ASC LIMIT ?",
                (*parameters, page_limit + 1),
            ).fetchall()
            page_rows = rows[:page_limit]
            observation_ids = [require_uuid4(str(row[0])) for row in page_rows]
            fields_by_observation: dict[str, list[PublishedObservationField]] = {
                observation_id: [] for observation_id in observation_ids
            }
            if observation_ids:
                placeholders = ",".join("?" for _ in observation_ids)
                field_rows = snapshot.connection.execute(
                    "SELECT source_observation_id,source_observation_field_id,field_key,value_state,value_kind,"
                    "source_text,normalized_text,integer_value,field_class FROM source_observation_fields "
                    f"WHERE source_observation_id IN ({placeholders}) "
                    "ORDER BY source_observation_id ASC,field_key ASC",
                    tuple(observation_ids),
                ).fetchall()
                for field_row in field_rows:
                    observation_id = require_uuid4(str(field_row[0]))
                    field_class = str(field_row[8])
                    if field_class not in {"active", "deferred"}:
                        raise IntegrityFailure("persisted source observation field_class is invalid")
                    fields_by_observation[observation_id].append(
                        PublishedObservationField(
                            source_observation_field_id=require_uuid4(str(field_row[1])),
                            field_key=str(field_row[2]),
                            field_class=field_class,
                            value_state=str(field_row[3]),
                            value_kind=str(field_row[4]),
                            display_value=_display_field_value(field_row[1:]),
                        )
                    )

        items = tuple(
            PublishedObservation(
                source_observation_id=require_uuid4(str(row[0])),
                source_family=str(row[1]),
                entity_kind=str(row[2]),
                identity_state=str(row[3]),
                canonical_primary_id=None if row[4] is None else str(row[4]),
                canonical_parent_rfc_no=None if row[5] is None else str(row[5]),
                sheet_ordinal=int(row[6]),
                row_ordinal=int(row[7]),
                source_row_chronology_utc=None if row[8] is None else int(row[8]),
                fields=tuple(fields_by_observation[require_uuid4(str(row[0]))]),
            )
            for row in page_rows
        )
        next_cursor = None
        if len(rows) > page_limit and items:
            last = items[-1]
            next_cursor = {
                "version": 1,
                "query_id": _OBSERVATION_QUERY_ID,
                "sort_registry_id": _OBSERVATION_SORT_ID,
                "last_key_tuple": [last.sheet_ordinal, last.row_ordinal, last.source_observation_id],
                "filter_fingerprint": filter_fingerprint,
                "null_order": "none",
            }
        return ObservationPage(items=items, next_cursor=next_cursor)

    def list_findings(
        self,
        import_run_id: str,
        *,
        severity: str | None = None,
        scope_kind: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> FindingPage:
        run_id = require_uuid4(import_run_id)
        if severity is not None and severity not in _FINDING_SEVERITY_RANK:
            raise ValidationError("severity is outside the closed finding vocabulary")
        if scope_kind is not None and scope_kind not in _FINDING_SCOPES:
            raise ValidationError("scope_kind is outside the closed finding vocabulary")
        page_limit = _page_limit(limit, label="finding")
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": _FINDING_FILTER_SCHEMA,
                "import_run_id": run_id,
                "severity": severity,
                "scope_kind": scope_kind,
            }
        )
        after = _finding_cursor(cursor, filter_fingerprint=filter_fingerprint)
        severity_case = (
            "CASE severity WHEN 'info' THEN 0 WHEN 'warning' THEN 1 "
            "WHEN 'error' THEN 2 WHEN 'high_risk' THEN 3 ELSE 99 END"
        )
        predicates = ["import_run_id=?"]
        parameters: list[object] = [run_id]
        if severity is not None:
            predicates.append("severity=?")
            parameters.append(severity)
        if scope_kind is not None:
            predicates.append("scope_kind=?")
            parameters.append(scope_kind)
        if after is not None:
            predicates.append(f"(({severity_case})>? OR (({severity_case})=? AND import_finding_id>?))")
            parameters.extend((after[0], after[0], after[1]))
        where = " AND ".join(predicates)

        with ReadSnapshot(self._factory) as snapshot:
            state = _require_run_state(snapshot.connection, run_id)
            if state not in _PUBLISHED_STATES:
                return FindingPage(items=(), next_cursor=None)
            rows = snapshot.connection.execute(
                "SELECT import_finding_id,finding_code,severity,scope_kind,message_text,source_observation_id,field_key,"
                f"{severity_case} AS severity_rank FROM import_findings WHERE {where} "
                "ORDER BY severity_rank ASC,import_finding_id ASC LIMIT ?",
                (*parameters, page_limit + 1),
            ).fetchall()

        page_rows = rows[:page_limit]
        items: list[ImportFinding] = []
        for row in page_rows:
            severity_value = str(row[2])
            rank = int(row[7])
            if _FINDING_SEVERITY_RANK.get(severity_value) != rank:
                raise IntegrityFailure("persisted finding severity is outside the closed rank vocabulary")
            scope = str(row[3])
            if scope not in _FINDING_SCOPES:
                raise IntegrityFailure("persisted finding scope is outside the closed vocabulary")
            items.append(
                ImportFinding(
                    import_finding_id=require_uuid4(str(row[0])),
                    finding_code=str(row[1]),
                    severity=severity_value,
                    scope_kind=scope,
                    message_text=str(row[4]),
                    source_observation_id=None if row[5] is None else require_uuid4(str(row[5])),
                    field_key=None if row[6] is None else str(row[6]),
                    severity_rank=rank,
                )
            )
        next_cursor = None
        if len(rows) > page_limit and items:
            last = items[-1]
            next_cursor = {
                "version": 1,
                "query_id": _FINDING_QUERY_ID,
                "sort_registry_id": _FINDING_SORT_ID,
                "last_key_tuple": [last.severity_rank, last.import_finding_id],
                "filter_fingerprint": filter_fingerprint,
                "null_order": "none",
            }
        return FindingPage(items=tuple(items), next_cursor=next_cursor)


__all__ = [
    "FindingPage",
    "ImportFinding",
    "ImportRunDetail",
    "ImportRunPage",
    "ImportRunQueryService",
    "ImportRunSummary",
    "ObservationPage",
    "PublishedObservation",
    "PublishedObservationField",
    "checkpoint_comparison",
    "checkpoint_summary",
    "run_summary_from_row",
]
