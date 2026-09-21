from __future__ import annotations

import ctypes
import os
import re
import stat as stat_module
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from soma.foundation.errors import SomaError

from .xlsx_security import XlsxPreflightResult, preflight_xlsx


_ADVANCED_SEARCH_FILENAME = re.compile(
    r"\AAdvanced Search\(Service Request\)([0-9]{14})\.xlsx\Z"
)
_RFC_ENHANCED_FILENAME = re.compile(
    r"\AEnhanced Excel Data Export(?: \(([1-9][0-9]*)\))?\.xlsx\Z"
)
_WFM_SERVICE_PROVIDER_FILENAME = re.compile(
    r"\AService Provider Plan Creation([0-9]{14})(?: \(([1-9][0-9]*)\))?\.xlsx\Z"
)
_ADVANCED_SEARCH_PROFILE_ID = "ADVANCED_SEARCH_SR_V1"
_ADVANCED_SEARCH_FAMILY = "advanced_search_sr"
_RFC_ENHANCED_PROFILE_ID = "RFC_ENHANCED_V1"
_RFC_ENHANCED_FAMILY = "rfc_enhanced"
_WFM_SERVICE_PROVIDER_PROFILE_ID = "WFM_SERVICE_PROVIDER_V1"
_WFM_SERVICE_PROVIDER_FAMILY = "wfm_service_provider"
_EMBEDDED_CHRONOLOGY_KIND = "embedded_filename_timestamp_utc"
_FILESYSTEM_CHRONOLOGY_KIND = "filesystem_mtime_ns"
_STABILITY_INTERVAL_SECONDS = 1.0
_STABILITY_MAX_ATTEMPTS = 3
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_MAX_FILENAME_UTF8_BYTES = 1024


@dataclass(frozen=True, slots=True)
class CandidateDescriptor:
    source_family: str
    profile_id: str
    path: Path
    filename: str
    stable_size_bytes: int
    stable_mtime_ns: int
    chronology_kind: str
    chronology_value: int
    discovery_provenance: str
    preflight: XlsxPreflightResult


@dataclass(frozen=True, slots=True)
class _RankedPath:
    path: Path
    filename: str
    chronology_value: int


@dataclass(frozen=True, slots=True)
class _StableFile:
    size_bytes: int
    mtime_ns: int
    device: int
    inode: int


def _source_unavailable(message: str) -> SomaError:
    return SomaError("IMPORT_SOURCE_UNAVAILABLE", message)


def _unstable() -> SomaError:
    return SomaError("IMPORT_FILE_UNSTABLE", "selected source file did not reach a stable readable state")


def _is_reparse_stat(stat_result: os.stat_result) -> bool:
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _reject_unsupported_windows_namespace(path: Path) -> None:
    raw = os.fspath(path)
    normalized = raw.replace("/", "\\") if os.name == "nt" else raw
    lowered = normalized.lower()
    if (
        normalized.startswith("\\\\")
        or normalized.startswith("\\") and not re.match(r"\A[A-Za-z]:\\", normalized)
        or lowered.startswith("\\?\\")
        or lowered.startswith("\\.\\")
        or lowered.startswith("\\" + "??\\")
    ):
        raise _source_unavailable("configured import path uses an unsupported Windows namespace")


def _assert_no_reparse_chain(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    chain = tuple(reversed(absolute.parents)) + (absolute,)
    for component in chain:
        try:
            stat_result = os.lstat(component)
        except OSError as exc:
            raise _source_unavailable("configured import path is unavailable") from exc
        if stat_module.S_ISLNK(stat_result.st_mode) or _is_reparse_stat(stat_result):
            raise _source_unavailable("configured import path traverses a symbolic link or reparse point")


def _assert_absolute_local_directory(directory: Path) -> Path:
    _reject_unsupported_windows_namespace(directory)
    if not directory.is_absolute():
        raise _source_unavailable("configured import directory is not an absolute local path")
    _assert_no_reparse_chain(directory)
    absolute = Path(os.path.abspath(os.fspath(directory)))
    try:
        stat_result = os.lstat(absolute)
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise _source_unavailable("configured import directory is unavailable") from exc
    if not stat_module.S_ISDIR(stat_result.st_mode) or _is_reparse_stat(stat_result):
        raise _source_unavailable("configured import directory is not a safe direct directory")
    return resolved


def _assert_safe_direct_file(directory: Path, entry: os.DirEntry[str]) -> Path | None:
    try:
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            return None
        stat_result = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    if _is_reparse_stat(stat_result) or not stat_module.S_ISREG(stat_result.st_mode):
        return None
    candidate = Path(entry.path)
    try:
        resolved = candidate.resolve(strict=True)
        common = os.path.commonpath((os.path.normcase(os.fspath(directory)), os.path.normcase(os.fspath(resolved))))
    except (OSError, ValueError):
        return None
    if common != os.path.normcase(os.fspath(directory)):
        return None
    return resolved


def _asia_shanghai_timezone(local: datetime):
    try:
        return ZoneInfo("Asia/Shanghai")
    except ZoneInfoNotFoundError:
        # Supported Windows Python installations do not necessarily ship IANA tzdata.
        # China has observed UTC+08 without DST since 1992. Fail closed for historical
        # timestamps rather than silently applying a modern fixed offset to older data.
        if local.year < 1992:
            raise ValueError("Asia/Shanghai historical timezone data is unavailable")
        return timezone(timedelta(hours=8), name="Asia/Shanghai")


def _america_guayaquil_timezone(local: datetime):
    try:
        return ZoneInfo("America/Guayaquil")
    except ZoneInfoNotFoundError:
        # WFM exports are modern operational artifacts. Mainland Ecuador is UTC-05 in
        # the supported modern period; fail closed for older dates where historical
        # timezone data would be required instead of guessing.
        if local.year < 1993:
            raise ValueError("America/Guayaquil historical timezone data is unavailable")
        return timezone(timedelta(hours=-5), name="America/Guayaquil")


def _parse_local_filename_timestamp(token: str, *, zone_factory: Callable[[datetime], object]) -> int | None:
    try:
        local = datetime.strptime(token, "%Y%m%d%H%M%S")
        zone = zone_factory(local)
        aware = local.replace(tzinfo=zone, fold=0)
        alternate = local.replace(tzinfo=zone, fold=1)
        if aware.utcoffset() != alternate.utcoffset():
            return None
        utc_instant = aware.astimezone(UTC)
        if utc_instant.astimezone(zone).replace(tzinfo=None) != local:
            return None
        epoch = int(utc_instant.timestamp())
        return epoch if epoch >= 0 else None
    except (OverflowError, TypeError, ValueError):
        return None


def _parse_advanced_search_filename(filename: str) -> int | None:
    match = _ADVANCED_SEARCH_FILENAME.fullmatch(filename)
    if match is None:
        return None
    return _parse_local_filename_timestamp(match.group(1), zone_factory=_asia_shanghai_timezone)


def _parse_rfc_enhanced_filename(filename: str) -> bool:
    return _RFC_ENHANCED_FILENAME.fullmatch(filename) is not None


def _parse_wfm_service_provider_filename(filename: str) -> int | None:
    match = _WFM_SERVICE_PROVIDER_FILENAME.fullmatch(filename)
    if match is None:
        return None
    return _parse_local_filename_timestamp(match.group(1), zone_factory=_america_guayaquil_timezone)


def _probe_stat(path: Path) -> _StableFile:
    try:
        stat_result = os.lstat(path)
    except OSError as exc:
        raise _unstable() from exc
    if (
        not stat_module.S_ISREG(stat_result.st_mode)
        or stat_module.S_ISLNK(stat_result.st_mode)
        or _is_reparse_stat(stat_result)
    ):
        raise _unstable()
    return _StableFile(
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
        int(stat_result.st_dev),
        int(stat_result.st_ino),
    )


def _openable_without_writer(path: Path) -> bool:
    if os.name != "nt":
        try:
            with path.open("rb"):
                return True
        except OSError:
            return False

    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        os.fspath(path),
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        return False
    try:
        return True
    finally:
        close_handle(handle)


def _probe_stability(
    path: Path,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> _StableFile:
    for _ in range(_STABILITY_MAX_ATTEMPTS):
        before = _probe_stat(path)
        sleep_fn(_STABILITY_INTERVAL_SECONDS)
        after = _probe_stat(path)
        if before == after and _openable_without_writer(path):
            return after
    raise _unstable()


def _preflight_stable(path: Path, stable: _StableFile) -> XlsxPreflightResult:
    try:
        preflight = preflight_xlsx(path)
    except SomaError:
        if _probe_stat(path) != stable:
            raise _unstable()
        raise
    if _probe_stat(path) != stable:
        raise _unstable()
    return preflight


def _probe_ranked_selection(
    ranked: list[_RankedPath],
    *,
    sleep_fn: Callable[[float], None],
) -> tuple[_RankedPath, _StableFile]:
    selected = ranked[0]
    selected_stability: _StableFile | None = None
    for candidate in ranked:
        try:
            stable = _probe_stability(candidate.path, sleep_fn=sleep_fn)
        except SomaError:
            if candidate.path == selected.path:
                raise
            continue
        if candidate.path == selected.path:
            selected_stability = stable
    if selected_stability is None:
        raise _unstable()
    return selected, selected_stability


def discover_advanced_search_automatic(
    directory: str | os.PathLike[str] | None,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CandidateDescriptor:
    """Select and validate the exact newest automatic Advanced Search candidate.

    Discovery is read-only. It does not create an ImportRun or mutate domain authority.
    The selected candidate is security-preflighted; an unsafe/unstable newest candidate
    fails visibly and is never replaced by an older file.
    """

    if directory is None:
        raise SomaError("IMPORT_SOURCE_NOT_CONFIGURED", "Advanced Search import directory is not configured")
    root = _assert_absolute_local_directory(Path(directory))

    ranked: list[_RankedPath] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                chronology = _parse_advanced_search_filename(entry.name)
                if chronology is None:
                    continue
                if len(entry.name.encode("utf-8", errors="strict")) > _MAX_FILENAME_UTF8_BYTES:
                    continue
                safe_path = _assert_safe_direct_file(root, entry)
                if safe_path is None:
                    continue
                ranked.append(_RankedPath(safe_path, entry.name, chronology))
    except OSError as exc:
        raise _source_unavailable("configured Advanced Search directory cannot be enumerated") from exc

    if not ranked:
        raise _source_unavailable("configured Advanced Search directory has no eligible automatic source file")

    ranked.sort(key=lambda candidate: (-candidate.chronology_value, candidate.filename.encode("utf-8")))
    selected, selected_stability = _probe_ranked_selection(ranked, sleep_fn=sleep_fn)
    preflight = _preflight_stable(selected.path, selected_stability)

    return CandidateDescriptor(
        source_family=_ADVANCED_SEARCH_FAMILY,
        profile_id=_ADVANCED_SEARCH_PROFILE_ID,
        path=selected.path,
        filename=selected.filename,
        stable_size_bytes=selected_stability.size_bytes,
        stable_mtime_ns=selected_stability.mtime_ns,
        chronology_kind=_EMBEDDED_CHRONOLOGY_KIND,
        chronology_value=selected.chronology_value,
        discovery_provenance="automatic",
        preflight=preflight,
    )


def discover_advanced_search_manual(
    selected_path: str | os.PathLike[str],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CandidateDescriptor:
    """Stabilize and preflight one explicitly selected Advanced Search workbook."""

    requested = Path(selected_path)
    _reject_unsupported_windows_namespace(requested)
    if not requested.is_absolute():
        raise _source_unavailable("selected Advanced Search workbook path is not absolute")
    _assert_no_reparse_chain(requested)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise _source_unavailable("selected Advanced Search workbook is unavailable") from exc
    chronology = _parse_advanced_search_filename(resolved.name)
    if chronology is None:
        raise SomaError(
            "IMPORT_SOURCE_PROFILE_MISMATCH",
            "selected workbook filename does not match the Advanced Search source profile",
        )
    stable = _probe_stability(resolved, sleep_fn=sleep_fn)
    preflight = _preflight_stable(resolved, stable)
    return CandidateDescriptor(
        source_family=_ADVANCED_SEARCH_FAMILY,
        profile_id=_ADVANCED_SEARCH_PROFILE_ID,
        path=resolved,
        filename=resolved.name,
        stable_size_bytes=stable.size_bytes,
        stable_mtime_ns=stable.mtime_ns,
        chronology_kind=_EMBEDDED_CHRONOLOGY_KIND,
        chronology_value=chronology,
        discovery_provenance="manual",
        preflight=preflight,
    )


def discover_rfc_enhanced_automatic(
    directory: str | os.PathLike[str] | None,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CandidateDescriptor:
    """Select the highest-ranked Enhanced RFC workbook from the shared RFC/WFM directory."""

    if directory is None:
        raise SomaError("IMPORT_SOURCE_NOT_CONFIGURED", "RFC/WFM import directory is not configured")
    root = _assert_absolute_local_directory(Path(directory))
    ranked: list[_RankedPath] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not _parse_rfc_enhanced_filename(entry.name):
                    continue
                if len(entry.name.encode("utf-8", errors="strict")) > _MAX_FILENAME_UTF8_BYTES:
                    continue
                safe_path = _assert_safe_direct_file(root, entry)
                if safe_path is None:
                    continue
                try:
                    chronology = int(os.lstat(safe_path).st_mtime_ns)
                except OSError:
                    continue
                if chronology < 0:
                    continue
                ranked.append(_RankedPath(safe_path, entry.name, chronology))
    except OSError as exc:
        raise _source_unavailable("configured RFC/WFM directory cannot be enumerated") from exc

    if not ranked:
        raise _source_unavailable("configured RFC/WFM directory has no eligible Enhanced RFC source file")

    ranked.sort(key=lambda candidate: (-candidate.chronology_value, candidate.filename.encode("utf-8")))
    selected, selected_stability = _probe_ranked_selection(ranked, sleep_fn=sleep_fn)
    if selected_stability.mtime_ns != selected.chronology_value:
        raise _unstable()
    preflight = _preflight_stable(selected.path, selected_stability)
    return CandidateDescriptor(
        source_family=_RFC_ENHANCED_FAMILY,
        profile_id=_RFC_ENHANCED_PROFILE_ID,
        path=selected.path,
        filename=selected.filename,
        stable_size_bytes=selected_stability.size_bytes,
        stable_mtime_ns=selected_stability.mtime_ns,
        chronology_kind=_FILESYSTEM_CHRONOLOGY_KIND,
        chronology_value=selected.chronology_value,
        discovery_provenance="automatic",
        preflight=preflight,
    )


def discover_rfc_enhanced_manual(
    selected_path: str | os.PathLike[str],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CandidateDescriptor:
    """Stabilize an explicitly selected local RFC .xlsx; filename family matching is not required."""

    requested = Path(selected_path)
    _reject_unsupported_windows_namespace(requested)
    if not requested.is_absolute():
        raise _source_unavailable("selected Enhanced RFC workbook path is not absolute")
    _assert_no_reparse_chain(requested)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise _source_unavailable("selected Enhanced RFC workbook is unavailable") from exc
    if not resolved.name.endswith(".xlsx"):
        raise SomaError(
            "IMPORT_SOURCE_PROFILE_MISMATCH",
            "selected RFC workbook does not use the required .xlsx extension",
        )
    stable = _probe_stability(resolved, sleep_fn=sleep_fn)
    if stable.mtime_ns < 0:
        raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "selected RFC workbook has unusable filesystem chronology")
    preflight = _preflight_stable(resolved, stable)
    return CandidateDescriptor(
        source_family=_RFC_ENHANCED_FAMILY,
        profile_id=_RFC_ENHANCED_PROFILE_ID,
        path=resolved,
        filename=resolved.name,
        stable_size_bytes=stable.size_bytes,
        stable_mtime_ns=stable.mtime_ns,
        chronology_kind=_FILESYSTEM_CHRONOLOGY_KIND,
        chronology_value=stable.mtime_ns,
        discovery_provenance="manual",
        preflight=preflight,
    )


def discover_wfm_service_provider_automatic(
    directory: str | os.PathLike[str] | None,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CandidateDescriptor:
    """Select the newest exact Service Provider WFM workbook by embedded export timestamp."""

    if directory is None:
        raise SomaError("IMPORT_SOURCE_NOT_CONFIGURED", "RFC/WFM import directory is not configured")
    root = _assert_absolute_local_directory(Path(directory))
    ranked: list[_RankedPath] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                chronology = _parse_wfm_service_provider_filename(entry.name)
                if chronology is None:
                    continue
                if len(entry.name.encode("utf-8", errors="strict")) > _MAX_FILENAME_UTF8_BYTES:
                    continue
                safe_path = _assert_safe_direct_file(root, entry)
                if safe_path is None:
                    continue
                ranked.append(_RankedPath(safe_path, entry.name, chronology))
    except OSError as exc:
        raise _source_unavailable("configured RFC/WFM directory cannot be enumerated") from exc

    if not ranked:
        raise _source_unavailable("configured RFC/WFM directory has no eligible Service Provider WFM source file")

    ranked.sort(key=lambda candidate: (-candidate.chronology_value, candidate.filename.encode("utf-8")))
    selected, selected_stability = _probe_ranked_selection(ranked, sleep_fn=sleep_fn)
    preflight = _preflight_stable(selected.path, selected_stability)
    return CandidateDescriptor(
        source_family=_WFM_SERVICE_PROVIDER_FAMILY,
        profile_id=_WFM_SERVICE_PROVIDER_PROFILE_ID,
        path=selected.path,
        filename=selected.filename,
        stable_size_bytes=selected_stability.size_bytes,
        stable_mtime_ns=selected_stability.mtime_ns,
        chronology_kind=_EMBEDDED_CHRONOLOGY_KIND,
        chronology_value=selected.chronology_value,
        discovery_provenance="automatic",
        preflight=preflight,
    )


def discover_wfm_service_provider_manual(
    selected_path: str | os.PathLike[str],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CandidateDescriptor:
    """Stabilize one explicitly selected WFM workbook with supported embedded chronology."""

    requested = Path(selected_path)
    _reject_unsupported_windows_namespace(requested)
    if not requested.is_absolute():
        raise _source_unavailable("selected Service Provider WFM workbook path is not absolute")
    _assert_no_reparse_chain(requested)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise _source_unavailable("selected Service Provider WFM workbook is unavailable") from exc
    chronology = _parse_wfm_service_provider_filename(resolved.name)
    if chronology is None:
        raise SomaError(
            "IMPORT_SOURCE_PROFILE_MISMATCH",
            "selected WFM workbook filename does not contain supported embedded source chronology",
        )
    stable = _probe_stability(resolved, sleep_fn=sleep_fn)
    preflight = _preflight_stable(resolved, stable)
    return CandidateDescriptor(
        source_family=_WFM_SERVICE_PROVIDER_FAMILY,
        profile_id=_WFM_SERVICE_PROVIDER_PROFILE_ID,
        path=resolved,
        filename=resolved.name,
        stable_size_bytes=stable.size_bytes,
        stable_mtime_ns=stable.mtime_ns,
        chronology_kind=_EMBEDDED_CHRONOLOGY_KIND,
        chronology_value=chronology,
        discovery_provenance="manual",
        preflight=preflight,
    )


__all__ = [
    "CandidateDescriptor",
    "discover_advanced_search_automatic",
    "discover_advanced_search_manual",
    "discover_rfc_enhanced_automatic",
    "discover_rfc_enhanced_manual",
    "discover_wfm_service_provider_automatic",
    "discover_wfm_service_provider_manual",
]
