from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.strict_json import (
    ObjectContract,
    loads_canonical_json,
    sha256_canonical_json,
)


@dataclass(frozen=True, slots=True)
class ReportSectionDescriptor:
    section_kind: str
    schema_name: str
    schema_version: int
    ordinal: int
    payload_contract: ObjectContract


@dataclass(frozen=True, slots=True)
class ReportSectionRow:
    canonical_row_key: str
    payload: dict[str, object]


class ReportSectionContributor(Protocol):
    def section_descriptor(self) -> ReportSectionDescriptor: ...

    def stream_snapshot_rows(
        self,
        snapshot: Any,
        report_request: dict[str, object],
        as_of_utc: int,
    ) -> tuple[ReportSectionRow, ...]: ...


class ReportSectionContributorRegistry:
    """Closed deterministic registry assembled once at the composition root."""

    def __init__(self, contributors: tuple[ReportSectionContributor, ...] = ()) -> None:
        resolved: list[tuple[ReportSectionDescriptor, ReportSectionContributor]] = []
        identities: set[tuple[str, str, int]] = set()
        ordinals: set[int] = set()
        for contributor in contributors:
            descriptor = contributor.section_descriptor()
            self._validate_descriptor(descriptor)
            identity = (
                descriptor.section_kind,
                descriptor.schema_name,
                descriptor.schema_version,
            )
            if identity in identities:
                raise ValidationError("duplicate report section schema registration")
            if descriptor.ordinal in ordinals:
                raise ValidationError("duplicate report section ordinal registration")
            identities.add(identity)
            ordinals.add(descriptor.ordinal)
            resolved.append((descriptor, contributor))
        resolved.sort(key=lambda item: (item[0].ordinal, item[0].section_kind))
        self._entries = tuple(resolved)
        self._by_identity = {
            (
                descriptor.section_kind,
                descriptor.schema_name,
                descriptor.schema_version,
            ): descriptor
            for descriptor, _contributor in self._entries
        }

    @staticmethod
    def _validate_descriptor(descriptor: ReportSectionDescriptor) -> None:
        if not isinstance(descriptor, ReportSectionDescriptor):
            raise ValidationError("report section contributor returned invalid descriptor")
        for value, label in (
            (descriptor.section_kind, "section_kind"),
            (descriptor.schema_name, "schema_name"),
        ):
            if (
                not isinstance(value, str)
                or not value
                or len(value.encode("utf-8")) > 256
            ):
                raise ValidationError(f"report section {label} is invalid")
        if type(descriptor.schema_version) is not int or descriptor.schema_version < 1:
            raise ValidationError("report section schema_version is invalid")
        if type(descriptor.ordinal) is not int or descriptor.ordinal < 1:
            raise ValidationError("report section ordinal is invalid")
        if not isinstance(descriptor.payload_contract, ObjectContract):
            raise ValidationError("report section payload contract is invalid")
        if (
            descriptor.payload_contract.name != descriptor.schema_name
            or descriptor.payload_contract.version != descriptor.schema_version
        ):
            raise ValidationError("report section descriptor disagrees with payload contract")

    def ordered_contributors(
        self,
        _report_kind: str,
    ) -> tuple[ReportSectionContributor, ...]:
        return tuple(contributor for _descriptor, contributor in self._entries)

    def descriptor(
        self,
        section_kind: str,
        schema_name: str,
        schema_version: int,
    ) -> ReportSectionDescriptor:
        descriptor = self._by_identity.get((section_kind, schema_name, schema_version))
        if descriptor is None:
            raise ValidationError("unknown report section schema/version")
        return descriptor

    def validate_staged_row(
        self,
        *,
        section_kind: str,
        schema_name: str,
        schema_version: int,
        section_ordinal: int,
        canonical_row_key: str,
        payload_json: str,
        payload_sha256: str,
    ) -> dict[str, object]:
        descriptor = self.descriptor(section_kind, schema_name, schema_version)
        if section_ordinal != descriptor.ordinal:
            raise ValidationError("report section ordinal disagrees with registry")
        if (
            not isinstance(canonical_row_key, str)
            or not canonical_row_key
            or len(canonical_row_key.encode("utf-8")) > 1024
        ):
            raise ValidationError("report section canonical row key is invalid")
        if not isinstance(payload_json, str):
            raise ValidationError("report section payload must be canonical JSON text")
        payload = loads_canonical_json(
            payload_json,
            max_bytes=descriptor.payload_contract.max_utf8_bytes,
            max_depth=descriptor.payload_contract.max_depth,
            max_collection_items=descriptor.payload_contract.max_collection_items,
        )
        normalized = descriptor.payload_contract.validate(payload)
        expected = sha256_canonical_json(normalized)
        if payload_sha256 != expected:
            raise ValidationError("report section payload hash disagrees with exact schema payload")
        return normalized

    def emit_rows(
        self,
        *,
        snapshot: Any,
        report_kind: str,
        report_request: dict[str, object],
        as_of_utc: int,
    ) -> tuple[dict[str, object], ...]:
        emitted: list[dict[str, object]] = []
        seen_keys: set[tuple[str, str]] = set()
        for descriptor, contributor in self._entries:
            rows = contributor.stream_snapshot_rows(
                snapshot,
                report_request,
                as_of_utc,
            )
            if not isinstance(rows, tuple):
                raise IntegrityFailure("report section contributor must emit a bounded tuple")
            prior_key: str | None = None
            for row_ordinal, row in enumerate(rows, start=1):
                if not isinstance(row, ReportSectionRow):
                    raise IntegrityFailure("report section contributor emitted invalid row")
                key = row.canonical_row_key
                if prior_key is not None and key <= prior_key:
                    raise IntegrityFailure(
                        "report section contributor rows are not canonically ordered"
                    )
                prior_key = key
                normalized = descriptor.payload_contract.validate(row.payload)
                identity = (descriptor.section_kind, key)
                if identity in seen_keys:
                    raise IntegrityFailure("report section contributor emitted duplicate row key")
                seen_keys.add(identity)
                emitted.append(
                    {
                        "section_kind": descriptor.section_kind,
                        "schema_name": descriptor.schema_name,
                        "schema_version": descriptor.schema_version,
                        "section_ordinal": descriptor.ordinal,
                        "row_ordinal": row_ordinal,
                        "canonical_row_key": key,
                        "payload": normalized,
                        "payload_sha256": sha256_canonical_json(normalized),
                    }
                )
        return tuple(emitted)


__all__ = [
    "ReportSectionContributor",
    "ReportSectionContributorRegistry",
    "ReportSectionDescriptor",
    "ReportSectionRow",
]
