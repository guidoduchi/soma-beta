from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from openpyxl import Workbook

from soma.foundation.errors import SomaError
from soma.ticket_import.parsing.discovery import (
    discover_rfc_enhanced_automatic,
    discover_rfc_enhanced_manual,
    discover_wfm_service_provider_automatic,
)


def _workbook(path) -> None:
    workbook = Workbook()
    workbook.active.append(["header"])
    workbook.active.append(["value"])
    workbook.save(path)


def test_rfc_automatic_ranks_by_mtime_not_collision_suffix(tmp_path) -> None:
    older = tmp_path / "Enhanced Excel Data Export (99).xlsx"
    newer = tmp_path / "Enhanced Excel Data Export (1).xlsx"
    ignored = tmp_path / "Enhanced Excel Data Export (0).xlsx"
    for path in (older, newer, ignored):
        _workbook(path)

    os.utime(older, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    os.utime(newer, ns=(1_800_000_000_000_000_000, 1_800_000_000_000_000_000))
    os.utime(ignored, ns=(1_900_000_000_000_000_000, 1_900_000_000_000_000_000))

    candidate = discover_rfc_enhanced_automatic(tmp_path, sleep_fn=lambda _seconds: None)

    assert candidate.source_family == "rfc_enhanced"
    assert candidate.profile_id == "RFC_ENHANCED_V1"
    assert candidate.filename == newer.name
    assert candidate.chronology_kind == "filesystem_mtime_ns"
    assert candidate.chronology_value == newer.stat().st_mtime_ns
    assert candidate.discovery_provenance == "automatic"


def test_rfc_manual_allows_nonautomatic_xlsx_filename_and_uses_mtime(tmp_path) -> None:
    selected = tmp_path / "operator-selected-rfc.xlsx"
    _workbook(selected)
    os.utime(selected, ns=(1_800_000_000_000_000_123, 1_800_000_000_000_000_123))
    filesystem_mtime_ns = selected.stat().st_mtime_ns

    candidate = discover_rfc_enhanced_manual(selected, sleep_fn=lambda _seconds: None)

    assert candidate.filename == selected.name
    assert candidate.chronology_value == filesystem_mtime_ns
    assert candidate.discovery_provenance == "manual"


def test_wfm_automatic_requires_timestamp_immediately_after_exact_family_marker(tmp_path) -> None:
    exact = tmp_path / "Service Provider Plan Creation20260916120000.xlsx"
    collision = tmp_path / "Service Provider Plan Creation20260916130000 (2).xlsx"
    undeclared_separator = tmp_path / "Service Provider Plan Creation 20260916140000.xlsx"
    malformed_calendar = tmp_path / "Service Provider Plan Creation20260230150000.xlsx"
    for path in (exact, collision, undeclared_separator, malformed_calendar):
        _workbook(path)

    candidate = discover_wfm_service_provider_automatic(tmp_path, sleep_fn=lambda _seconds: None)

    assert candidate.source_family == "wfm_service_provider"
    assert candidate.profile_id == "WFM_SERVICE_PROVIDER_V1"
    assert candidate.filename == collision.name
    assert candidate.chronology_kind == "embedded_filename_timestamp_utc"
    assert candidate.chronology_value == int(datetime(2026, 9, 16, 18, 0, tzinfo=UTC).timestamp())


def test_wfm_automatic_does_not_substitute_mtime_for_invalid_embedded_chronology(tmp_path) -> None:
    invalid = tmp_path / "Service Provider Plan Creation 20260916140000.xlsx"
    _workbook(invalid)
    os.utime(invalid, ns=(1_900_000_000_000_000_000, 1_900_000_000_000_000_000))

    with pytest.raises(SomaError) as excinfo:
        discover_wfm_service_provider_automatic(tmp_path, sleep_fn=lambda _seconds: None)

    assert excinfo.value.code == "IMPORT_SOURCE_UNAVAILABLE"


def test_rfc_and_wfm_automatic_ties_use_utf8_filename_bytes(tmp_path) -> None:
    # RFC tie: collision suffix magnitude is not chronology; bytewise filename order wins.
    rfc_a = tmp_path / "Enhanced Excel Data Export (1).xlsx"
    rfc_b = tmp_path / "Enhanced Excel Data Export (2).xlsx"
    _workbook(rfc_a)
    _workbook(rfc_b)
    tied_mtime = 1_800_000_000_000_000_000
    os.utime(rfc_a, ns=(tied_mtime, tied_mtime))
    os.utime(rfc_b, ns=(tied_mtime, tied_mtime))
    assert discover_rfc_enhanced_automatic(tmp_path, sleep_fn=lambda _seconds: None).filename == rfc_a.name

    # WFM tie: same embedded chronology, bytewise filename order wins independently of mtime.
    wfm_a = tmp_path / "Service Provider Plan Creation20260916120000 (1).xlsx"
    wfm_b = tmp_path / "Service Provider Plan Creation20260916120000 (2).xlsx"
    _workbook(wfm_a)
    _workbook(wfm_b)
    os.utime(wfm_a, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    os.utime(wfm_b, ns=(1_900_000_000_000_000_000, 1_900_000_000_000_000_000))
    assert discover_wfm_service_provider_automatic(tmp_path, sleep_fn=lambda _seconds: None).filename == wfm_a.name
