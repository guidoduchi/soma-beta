from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from soma.foundation.errors import SomaError
from soma.ticket_import.parsing import discovery


def test_posix_absolute_path_is_not_reinterpreted_as_windows_alternate_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.os, "name", "posix")

    discovery._reject_unsupported_windows_namespace(PurePosixPath("/tmp/soma-import"))


def test_literal_windows_unc_namespace_is_still_rejected_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.os, "name", "posix")

    with pytest.raises(SomaError) as excinfo:
        discovery._reject_unsupported_windows_namespace(PureWindowsPath(r"\\server\share\import"))

    assert excinfo.value.code == "IMPORT_SOURCE_UNAVAILABLE"


def test_windows_host_normalizes_forward_slashes_before_namespace_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.os, "name", "nt")

    with pytest.raises(SomaError) as excinfo:
        discovery._reject_unsupported_windows_namespace(PurePosixPath("//server/share/import"))

    assert excinfo.value.code == "IMPORT_SOURCE_UNAVAILABLE"
