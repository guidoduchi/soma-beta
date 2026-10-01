from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.reference.application.settings_service import SettingService

from soma.communications.contracts.common import Chronology, integer
from soma.communications.contracts.jobs import CommunicationJobScope, bound_from_value
from soma.communications.domain.initial_boundary import initial_boundary
from soma.communications.queries.coverage import coverage_fingerprint, coverage_in_reader
from soma.communications.repositories import sources
from soma.communications.settings import build_communications_setting_registry


def readable_scope(reader, identity, revision):
    require_uuid4(identity)
    integer(revision, minimum=1)
    source = sources.scope(reader, identity)
    if source is None:
        raise SomaError("COMM_SOURCE_NOT_FOUND", "Communication source scope is unavailable")
    if source["revision"] != revision:
        raise SomaError("COMM_STALE", "Communication source configuration changed")
    error = {"MISSING": "COMM_SOURCE_NOT_FOUND", "LOCKED": "COMM_SOURCE_LOCKED"}.get(source["health_state"])
    if error or source["health_state"] not in {"READY", "PARTIAL"}:
        raise SomaError(error or "COMM_SOURCE_UNSUPPORTED", "Communication source is not readable")
    folders = sources.enabled_folders(reader, identity)
    if not 1 <= len(folders) <= 64:
        raise IntegrityFailure("Communication source requires a bounded configured folder selection")
    return source, folders


def ordinary_scope(reader, identity, revision, identities):
    source, folders = readable_scope(reader, identity, revision)
    boundary = initial_boundary(identities.snapshot(reader))
    keys = tuple(sorted(folder["provider_folder_key"] for folder in folders))
    coverage = coverage_in_reader(reader, identity)
    if not boundary.chronology.known and any(folder["high_water"] is None for folder in coverage["folders"]):
        raise SomaError("COMM_COVERAGE_BOUNDARY_UNKNOWN", "Communication historical start requires an explicit bound or Deep Scan")
    lower = boundary.chronology if boundary.chronology.known else None
    return CommunicationJobScope(identity, keys, "ORDINARY", lower, None, (), revision)


def validate_range(lower, upper, *, adapter, allow_open):
    if not allow_open and (lower is None or upper is None):
        raise ValidationError("Communication backfill requires explicit bounds")
    bounds = [value for value in (lower, upper) if value is not None]
    if not bounds:
        return
    if any(isinstance(value, Chronology) for value in bounds):
        if not all(isinstance(value, Chronology) and value.known for value in bounds):
            raise ValidationError("Communication scan requires known chronology bounds of one kind")
        if lower is not None and upper is not None and lower.utc_epoch_seconds > upper.utc_epoch_seconds:
            raise ValidationError("Communication scan range is reversed")
        return
    compare = getattr(adapter, "compare_checkpoints", None)
    if not callable(compare):
        raise ValidationError("Communication provider range cannot be ordered")
    ordering = compare(lower or upper, upper or lower)
    if not isinstance(ordering, str) or ordering not in {"BEFORE", "EQUAL", "AFTER", "INDETERMINATE"}:
        raise IntegrityFailure("Communication adapter returned invalid checkpoint ordering")
    if ordering not in {"BEFORE", "EQUAL"}:
        raise ValidationError("Communication provider range cannot be ordered")


def scan_preview_in_reader(reader, request, *, kind, settings, identities=None, adapter=None):
    source, folders = readable_scope(reader, request["source_scope_id"], request["source_scope_revision"])
    lower, upper = (bound_from_value(request[name]) for name in ("lower_bound", "upper_bound"))
    validate_range(lower, upper, adapter=adapter, allow_open=kind == "DEEP_SCAN")
    target_evidence = None
    if kind == "DEEP_SCAN":
        keys = tuple(sorted(request["folder_keys"]))
        available = {folder["provider_folder_key"] for folder in folders}
        if not keys or not set(keys).issubset(available):
            raise SomaError("COMM_STALE", "Communication scan folder selection changed")
        targets = ()
        confirmation = "DELIBERATE_DEEP_SCAN"
    else:
        targets = tuple(sorted(request["target_identity_ids"]))
        if not targets:
            raise ValidationError("Communication backfill requires accepted target identities")
        found = {}
        wanted = set(targets)

        def selected_identities():
            for identity in identities.snapshot(reader):
                if identity.target_id not in wanted:
                    continue
                prior = found.setdefault(identity.target_id, identity.target_type)
                if prior != identity.target_type:
                    raise SomaError("COMM_TARGET_STALE", "Communication backfill target reference is ambiguous")
                yield identity

        try:
            target_evidence = initial_boundary(selected_identities()).evidence_fingerprint
        except SomaError as exc:
            if exc.code != "COMM_NO_TRACKABLE_TARGETS":
                raise
            raise SomaError("COMM_TARGET_STALE", "Communication backfill targets are no longer trackable") from exc
        if set(found) != set(targets):
            raise SomaError("COMM_TARGET_STALE", "Communication backfill target is no longer trackable")
        keys = tuple(sorted(folder["provider_folder_key"] for folder in folders))
        if not isinstance(lower, Chronology) or not isinstance(upper, Chronology):
            # Provider position duration cannot be inferred from token text.
            confirmation = "REVIEW_CONFIRM"
        else:
            if not lower.known or not upper.known or lower.utc_epoch_seconds > upper.utc_epoch_seconds:
                raise ValidationError("Communication backfill requires ordered known chronology bounds")
            days = settings.get_in_reader(reader, "communications.auto_backfill_max_days")
            confirmation = "AUTO_BOUNDED" if upper.utc_epoch_seconds - lower.utc_epoch_seconds <= days.value * 86400 else "REVIEW_CONFIRM"
    scope = CommunicationJobScope(source["source_scope_id"], keys, kind, lower, upper, targets, source["revision"])
    coverage = coverage_in_reader(reader, source["source_scope_id"], folder_keys=keys)
    settings_values = [settings.get_in_reader(reader, item.setting_key) for item in build_communications_setting_registry().all_for_owner("LLD-09")]
    token = sha256_canonical_json({"schema": "SOMA_COMM_SCAN_PREVIEW_V1", "scope": scope.to_response(),
        "source": {name: source[name] for name in ("revision", "adapter_family", "adapter_version", "health_state", "scope_identity_kind", "scope_identity_value")},
        "folders": [folder for folder in folders if folder["provider_folder_key"] in keys],
        "coverage_fingerprint": coverage_fingerprint(reader, source["source_scope_id"], keys),
        "target_evidence": target_evidence,
        "settings": [{"key": setting.setting_key, "revision": setting.revision, "value": setting.value} for setting in settings_values]})
    warnings = set(coverage["warnings"])
    if source["health_state"] == "PARTIAL":
        warnings.add("COMM_SOURCE_PARTIAL")
    return {"preview_fingerprint": token, "scope": scope.to_response(), "existing_coverage": coverage["folders"],
            "estimated_messages": None, "estimated_bytes": None, "confirmation_class": confirmation, "warnings": sorted(warnings)}


def communication_settings(factory):
    return SettingService(factory, build_communications_setting_registry())
