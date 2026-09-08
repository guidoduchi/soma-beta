from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from soma.foundation.errors import ValidationError


_MAGIC = "SOMA_IMPORT_LOGICAL_V1"
_CLASSIFICATION_FINDINGS = frozenset({"SOURCE_EQUIVALENT_DUPLICATE", "SOURCE_IDENTITY_CONFLICT"})
_VALID_CLASSIFICATIONS = frozenset({"UNIQUE", "EQUIVALENT_DUPLICATE", "CONFLICT_MEMBER"})


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
