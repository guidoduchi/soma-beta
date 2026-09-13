from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.objectives_tasks.services.wfm_import import WfmImportReader
from soma.ticket_import.providers.wfm_competing_attempt_evidence import (
    TicketImportWfmCompetingAttemptEvidenceProvider,
)
from soma.tickets.rfc_import_reader import RfcImportReader


_MAGIC = "SOMA_IMPORT_LOGICAL_V1"
_CLASSIFICATION_FINDINGS = frozenset({"SOURCE_EQUIVALENT_DUPLICATE", "SOURCE_IDENTITY_CONFLICT"})
_VALID_CLASSIFICATIONS = frozenset({"UNIQUE", "EQUIVALENT_DUPLICATE", "CONFLICT_MEMBER"})
_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"


@dataclass(frozen=True, slots=True)
class LogicalFinding:
    finding_code: str
    severity: str
    scope_kind: str
    field_key: str | None = None


@dataclass(frozen=True, slots=True)
class LogicalField:
    field_key: str
    field_class: str
    value_state: str
    value_kind: str
    vocabulary_id: str | None = None
    source_text: str | None = None
    normalized_text: str | None = None
    integer_value: int | None = None


@dataclass(frozen=True, slots=True)
class LogicalRow:
    identity_state: str
    entity_kind: str
    canonical_primary_id: str | None
    canonical_parent_rfc_no: str | None
    fields: tuple[LogicalField, ...] = ()
    findings: tuple[LogicalFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class LogicalRowVariant:
    classification: str
    duplicate_count: int
    conflict_variant_count: int
    row: LogicalRow
    row_logical_sha256: str


@dataclass(frozen=True, slots=True)
class LogicalFingerprintResult:
    logical_fingerprint_sha256: str
    stream_bytes: int
    variants: tuple[LogicalRowVariant, ...]


@dataclass(frozen=True, slots=True)
class ProposalChangeDraft:
    ordinal: int
    field_key: str
    change_kind: str
    value_kind: str
    before_text: str | None
    after_text: str | None
    before_integer: int | None
    after_integer: int | None
    source_observation_field_id: str | None

    def fingerprint_object(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "field_key": self.field_key,
            "change_kind": self.change_kind,
            "value_kind": self.value_kind,
            "before_text": self.before_text,
            "after_text": self.after_text,
            "before_integer": self.before_integer,
            "after_integer": self.after_integer,
            "source_observation_field_id": self.source_observation_field_id,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationProposalDraft:
    import_run_id: str
    evidence_mode: str
    source_observation_id: str
    proposal_kind: str
    target_kind: str
    target_internal_id: str
    target_business_id: str
    risk_class: str
    base_state_token_sha256: str
    proposal_fingerprint_sha256: str
    changes: tuple[ProposalChangeDraft, ...]


def _frame_null() -> bytes:
    return b"\x00" + (0).to_bytes(8, "big")


def _frame_text(value: str) -> bytes:
    if not isinstance(value, str) or "\x00" in value:
        raise ValidationError("logical fingerprint text must be NUL-free Unicode")
    try:
        payload = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("logical fingerprint text must be valid Unicode") from exc
    return b"\x01" + len(payload).to_bytes(8, "big") + payload


def _frame_integer(value: int) -> bytes:
    if type(value) is not int or value < 0:
        raise ValidationError("logical fingerprint integers must be nonnegative integers")
    payload = str(value).encode("ascii")
    return b"\x02" + len(payload).to_bytes(8, "big") + payload


def _frame_optional_text(value: str | None) -> bytes:
    return _frame_null() if value is None else _frame_text(value)


def _source_text_token(source_text: str | None) -> str:
    if source_text is None:
        return "NO_SOURCE_TEXT"
    if "\x00" in source_text:
        raise ValidationError("logical source_text token input must be NUL-free")
    try:
        payload = source_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("logical source_text token input must be valid Unicode") from exc
    return f"SOURCE_TEXT_SHA256:{sha256(payload).hexdigest()}"


def _field_value_frame(field: LogicalField) -> bytes:
    if field.value_state == "usable":
        if field.value_kind in {"text", "controlled"}:
            if field.normalized_text is None or field.integer_value is not None:
                raise ValidationError("usable text/controlled logical field requires normalized_text only")
            return _frame_text(field.normalized_text)
        if field.value_kind in {"instant", "duration_seconds"}:
            if field.normalized_text is not None or type(field.integer_value) is not int:
                raise ValidationError("usable instant/duration logical field requires integer_value only")
            return _frame_integer(field.integer_value)
        raise ValidationError("logical field value_kind is outside SOMA_IMPORT_LOGICAL_V1")
    if field.normalized_text is not None or field.integer_value is not None:
        raise ValidationError("non-usable logical field cannot carry normalized authority")
    if field.value_state == "blank":
        return _frame_text("BLANK")
    if field.value_state in {"unknown", "malformed"}:
        return _frame_text(_source_text_token(field.source_text))
    raise ValidationError("logical field value_state is outside SOMA_IMPORT_LOGICAL_V1")


def field_frame(field: LogicalField) -> bytes:
    if field.value_kind == "controlled" and field.vocabulary_id is None:
        raise ValidationError("controlled logical field requires vocabulary_id")
    if field.value_kind != "controlled" and field.vocabulary_id is not None:
        raise ValidationError("non-controlled logical field cannot carry vocabulary_id")
    return b"".join(
        (
            _frame_text("FIELD_V1"),
            _frame_text(field.field_key),
            _frame_text(field.field_class),
            _frame_text(field.value_state),
            _frame_text(field.value_kind),
            _frame_optional_text(field.vocabulary_id),
            _field_value_frame(field),
        )
    )


def field_logical_sha256(field: LogicalField) -> str:
    return sha256(field_frame(field)).hexdigest()


def _finding_sort_key(finding: LogicalFinding) -> tuple[bytes, bytes, bytes, int, bytes]:
    return (
        finding.finding_code.encode("utf-8"),
        finding.severity.encode("utf-8"),
        finding.scope_kind.encode("utf-8"),
        0 if finding.field_key is None else 1,
        b"" if finding.field_key is None else finding.field_key.encode("utf-8"),
    )


def finding_frame(finding: LogicalFinding) -> bytes:
    return b"".join(
        (
            _frame_text("FINDING_V1"),
            _frame_text(finding.finding_code),
            _frame_text(finding.severity),
            _frame_text(finding.scope_kind),
            _frame_optional_text(finding.field_key),
        )
    )


def row_frame(row: LogicalRow) -> bytes:
    if row.identity_state not in {"valid", "invalid"}:
        raise ValidationError("logical row identity_state must be valid or invalid")
    if row.identity_state == "invalid" and (
        row.canonical_primary_id is not None or row.canonical_parent_rfc_no is not None
    ):
        raise ValidationError("invalid logical row cannot carry canonical identity")
    field_keys = [field.field_key for field in row.fields]
    if len(field_keys) != len(set(field_keys)):
        raise ValidationError("logical row cannot repeat a canonical field_key")

    fields = tuple(sorted(row.fields, key=lambda field: field.field_key.encode("utf-8")))
    findings = tuple(
        sorted(
            (finding for finding in row.findings if finding.finding_code not in _CLASSIFICATION_FINDINGS),
            key=_finding_sort_key,
        )
    )
    parts: list[bytes] = [
        _frame_text("ROW_V1"),
        _frame_text(row.identity_state),
        _frame_text(row.entity_kind),
        _frame_optional_text(row.canonical_primary_id),
        _frame_optional_text(row.canonical_parent_rfc_no),
        _frame_integer(len(fields)),
    ]
    parts.extend(field_frame(field) for field in fields)
    parts.append(_frame_integer(len(findings)))
    parts.extend(finding_frame(finding) for finding in findings)
    return b"".join(parts)


def row_logical_sha256(row: LogicalRow) -> str:
    return sha256(row_frame(row)).hexdigest()


def _identity_key(row: LogicalRow) -> tuple[str, str | None, str | None]:
    return row.entity_kind, row.canonical_primary_id, row.canonical_parent_rfc_no


def _variant_sort_key(variant: LogicalRowVariant) -> tuple[int, int, bytes, int, bytes, bytes]:
    row = variant.row
    primary = row.canonical_primary_id
    parent = row.canonical_parent_rfc_no
    return (
        0 if row.identity_state == "invalid" else 1,
        0 if primary is None else 1,
        b"" if primary is None else primary.encode("utf-8"),
        0 if parent is None else 1,
        b"" if parent is None else parent.encode("utf-8"),
        variant.row_logical_sha256.encode("ascii"),
    )


def partition_row_variants(rows: Iterable[LogicalRow]) -> tuple[LogicalRowVariant, ...]:
    prepared = [(row, row_logical_sha256(row)) for row in rows]
    valid_groups: dict[tuple[str, str | None, str | None], dict[str, list[LogicalRow]]] = {}
    invalid_groups: dict[str, list[LogicalRow]] = {}

    for row, digest in prepared:
        if row.identity_state == "valid":
            valid_groups.setdefault(_identity_key(row), {}).setdefault(digest, []).append(row)
        else:
            invalid_groups.setdefault(digest, []).append(row)

    variants: list[LogicalRowVariant] = []
    for variants_by_hash in valid_groups.values():
        conflict_variant_count = len(variants_by_hash)
        for digest, occurrences in variants_by_hash.items():
            count = len(occurrences)
            if conflict_variant_count > 1:
                classification = "CONFLICT_MEMBER"
            else:
                classification = "EQUIVALENT_DUPLICATE" if count > 1 else "UNIQUE"
            variants.append(
                LogicalRowVariant(
                    classification=classification,
                    duplicate_count=count,
                    conflict_variant_count=conflict_variant_count,
                    row=occurrences[0],
                    row_logical_sha256=digest,
                )
            )

    for digest, occurrences in invalid_groups.items():
        count = len(occurrences)
        variants.append(
            LogicalRowVariant(
                classification="EQUIVALENT_DUPLICATE" if count > 1 else "UNIQUE",
                duplicate_count=count,
                conflict_variant_count=1,
                row=occurrences[0],
                row_logical_sha256=digest,
            )
        )

    return tuple(sorted(variants, key=_variant_sort_key))


def compute_logical_fingerprint(
    *,
    source_family: str,
    source_profile_id: str,
    header_registry_id: str,
    vocabulary_registry_id: str,
    parser_profile_id: str,
    rows: Iterable[LogicalRow],
    global_findings: Iterable[LogicalFinding] = (),
) -> LogicalFingerprintResult:
    findings = tuple(
        sorted(
            (finding for finding in global_findings if finding.finding_code not in _CLASSIFICATION_FINDINGS),
            key=_finding_sort_key,
        )
    )
    variants = partition_row_variants(rows)

    parts: list[bytes] = [
        _frame_text(_MAGIC),
        _frame_text(source_family),
        _frame_text(source_profile_id),
        _frame_text(header_registry_id),
        _frame_text(vocabulary_registry_id),
        _frame_text(parser_profile_id),
        _frame_integer(len(findings)),
    ]
    parts.extend(finding_frame(finding) for finding in findings)
    parts.append(_frame_integer(len(variants)))
    for variant in variants:
        if variant.classification not in _VALID_CLASSIFICATIONS:
            raise ValidationError("logical row classification is outside SOMA_IMPORT_LOGICAL_V1")
        parts.extend(
            (
                _frame_text(variant.classification),
                _frame_integer(variant.duplicate_count),
                _frame_integer(variant.conflict_variant_count),
                row_frame(variant.row),
            )
        )
    stream = b"".join(parts)
    return LogicalFingerprintResult(
        logical_fingerprint_sha256=sha256(stream).hexdigest(),
        stream_bytes=len(stream),
        variants=variants,
    )


def classify_replay(
    *,
    candidate_chronology: int,
    logical_fingerprint_sha256: str,
    checkpoint_chronology: int | None,
    checkpoint_logical_fingerprint_sha256: str | None,
) -> str:
    if type(candidate_chronology) is not int or candidate_chronology < 0:
        raise ValidationError("candidate chronology must be a nonnegative integer")
    if checkpoint_chronology is None:
        if checkpoint_logical_fingerprint_sha256 is not None:
            raise ValidationError("checkpoint fingerprint cannot exist without chronology")
        return "NEW_SOURCE"
    if type(checkpoint_chronology) is not int or checkpoint_chronology < 0:
        raise ValidationError("checkpoint chronology must be a nonnegative integer")
    if checkpoint_logical_fingerprint_sha256 is None:
        raise ValidationError("checkpoint chronology requires logical fingerprint")
    if candidate_chronology < checkpoint_chronology:
        return "OLDER_SOURCE_RECOVERY_REQUIRED"
    if candidate_chronology == checkpoint_chronology:
        if logical_fingerprint_sha256 == checkpoint_logical_fingerprint_sha256:
            return "EXACT_REPLAY_NOOP"
        return "CHRONOLOGY_CONTENT_CONFLICT"
    if logical_fingerprint_sha256 == checkpoint_logical_fingerprint_sha256:
        return "NEWER_IDENTICAL_NO_DOMAIN_CHANGE"
    return "NEW_SOURCE"


def _proposal_source_authority(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    task_no: str,
    parent_rfc_no: str,
) -> dict[str, object]:
    row = reader.execute(
        "SELECT r.import_run_id,r.source_family,r.source_profile_id,r.header_registry_id,r.vocabulary_registry_id,"
        "r.parser_profile_id,o.source_observation_id,o.source_family,o.entity_kind,o.identity_state,o.canonical_primary_id,"
        "o.canonical_parent_rfc_no,o.row_logical_sha256 FROM import_runs r "
        "JOIN source_observations o ON o.import_run_id=r.import_run_id "
        "WHERE r.import_run_id=? AND o.source_observation_id=?",
        (import_run_id, source_observation_id),
    ).fetchone()
    if row is None:
        raise SomaError("IMPORT_RUN_STALE", "WFM proposal source authority disappeared")
    if (
        str(row[0]) != import_run_id
        or str(row[1]) != "wfm_service_provider"
        or str(row[7]) != "wfm_service_provider"
        or str(row[8]) != "wfm"
        or str(row[9]) != "valid"
        or str(row[10]) != task_no
        or str(row[11]) != parent_rfc_no
    ):
        raise IntegrityFailure("WFM proposal source authority disagrees with published evidence")
    row_hash = str(row[12])
    if len(row_hash) != 64 or any(character not in "0123456789abcdef" for character in row_hash):
        raise IntegrityFailure("WFM proposal source row logical hash is invalid")
    profile_values = tuple(str(row[index]) for index in range(2, 6))
    if any(not value for value in profile_values):
        raise IntegrityFailure("WFM proposal source profile authority is incomplete")
    return {
        "import_run_id": import_run_id,
        "source_family": "wfm_service_provider",
        "source_profile_id": profile_values[0],
        "header_registry_id": profile_values[1],
        "vocabulary_registry_id": profile_values[2],
        "parser_profile_id": profile_values[3],
        "source_observation_id": source_observation_id,
        "canonical_primary_id": task_no,
        "canonical_parent_rfc_no": parent_rfc_no,
        "row_logical_sha256": row_hash,
    }


def build_wfm_competing_attempt_review_proposal(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    rfc_reader: RfcImportReader | None = None,
    wfm_reader: WfmImportReader | None = None,
    evidence_provider: TicketImportWfmCompetingAttemptEvidenceProvider | None = None,
) -> ReconciliationProposalDraft | None:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    rfc_authority = RfcImportReader() if rfc_reader is None else rfc_reader
    wfm_authority = WfmImportReader() if wfm_reader is None else wfm_reader
    evidence_authority = (
        TicketImportWfmCompetingAttemptEvidenceProvider()
        if evidence_provider is None
        else evidence_provider
    )
    evidence = evidence_authority.load_exact(
        reader,
        expected_import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )

    rfc = rfc_authority.get_by_number(reader, evidence.parent_rfc_no)
    if rfc is None:
        return None
    rfc_id = rfc.get("rfc_id")
    if not isinstance(rfc_id, str):
        raise IntegrityFailure("RFC import reader returned invalid proposal-generation identity")
    try:
        canonical_rfc_id = require_uuid4(rfc_id)
    except ValidationError as exc:
        raise IntegrityFailure("RFC import reader returned noncanonical proposal-generation identity") from exc

    try:
        task_no_status = wfm_authority.task_no_status(reader, evidence.task_no)
    except SomaError as exc:
        if exc.code == "WFM_TASK_NO_INVALID":
            raise IntegrityFailure("published WFM proposal source Task No is not canonical") from exc
        raise
    if task_no_status != "ACTIVE":
        return None
    identity = wfm_authority.get_by_task_no(reader, evidence.task_no)
    if identity is None:
        raise IntegrityFailure("ACTIVE WFM proposal target lacks current identity authority")
    task_id = identity.get("task_id")
    current_rfc_id = identity.get("current_rfc_id")
    if not isinstance(task_id, str):
        raise IntegrityFailure("WFM import reader returned invalid proposal-generation Task identity")
    try:
        canonical_task_id = require_uuid4(task_id)
    except ValidationError as exc:
        raise IntegrityFailure("WFM import reader returned noncanonical proposal-generation Task identity") from exc
    if current_rfc_id != canonical_rfc_id:
        return None

    conflict = wfm_authority.activity_conflicts(
        reader,
        {
            "task_no": evidence.task_no,
            "current_rfc_id": canonical_rfc_id,
            "task_id": canonical_task_id,
        },
        {"start_utc": evidence.planned_start_utc, "end_utc": evidence.planned_end_utc},
        None,
    )
    if conflict.get("classification") != "SAME_REVIEWED_LINEAGE_OVERLAP":
        return None
    if conflict.get("subject_task_id") != canonical_task_id:
        raise IntegrityFailure("WFM conflict reader returned a different proposal-generation subject")
    exact_conflict_count = conflict.get("exact_conflict_count")
    if type(exact_conflict_count) is not int or exact_conflict_count < 1:
        raise IntegrityFailure("WFM conflict reader returned invalid competing-attempt count")
    lineage_id = conflict.get("activity_lineage_id")
    counterpart_id = conflict.get("suggested_counterpart_task_id")
    conflict_fingerprint = conflict.get("conflict_fingerprint")
    if not isinstance(lineage_id, str) or not isinstance(counterpart_id, str):
        raise IntegrityFailure("WFM conflict reader omitted competing-attempt identities")
    try:
        canonical_lineage_id = require_uuid4(lineage_id)
        canonical_counterpart_id = require_uuid4(counterpart_id)
    except ValidationError as exc:
        raise IntegrityFailure("WFM conflict reader returned noncanonical competing-attempt identity") from exc
    if (
        not isinstance(conflict_fingerprint, str)
        or len(conflict_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in conflict_fingerprint)
    ):
        raise IntegrityFailure("WFM conflict reader returned invalid conflict fingerprint")

    change = ProposalChangeDraft(
        ordinal=0,
        field_key="competing_attempt_counterpart",
        change_kind="conflict",
        value_kind="identity",
        before_text=None,
        after_text=canonical_counterpart_id,
        before_integer=None,
        after_integer=None,
        source_observation_field_id=None,
    )
    source = _proposal_source_authority(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
        task_no=evidence.task_no,
        parent_rfc_no=evidence.parent_rfc_no,
    )
    proposal_identity = {
        "proposal_kind": "wfm_competing_attempt_review",
        "evidence_mode": "observed_row",
        "risk_class": "high",
        "target_kind": "activity_lineage",
        "target_internal_id": canonical_lineage_id,
        "target_business_id": evidence.task_no,
    }
    proposal_fingerprint = sha256_canonical_json(
        {
            "schema": _PROPOSAL_FINGERPRINT_SCHEMA,
            "source": source,
            "proposal": proposal_identity,
            "changes": [change.fingerprint_object()],
        }
    )
    return ReconciliationProposalDraft(
        import_run_id=canonical_run_id,
        evidence_mode="observed_row",
        source_observation_id=canonical_observation_id,
        proposal_kind="wfm_competing_attempt_review",
        target_kind="activity_lineage",
        target_internal_id=canonical_lineage_id,
        target_business_id=evidence.task_no,
        risk_class="high",
        base_state_token_sha256=conflict_fingerprint,
        proposal_fingerprint_sha256=proposal_fingerprint,
        changes=(change,),
    )
