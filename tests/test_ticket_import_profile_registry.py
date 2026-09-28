from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.ticket_import.profiles.registry import require_auto_accept_policy


def test_rfc_wfm_auto_accept_v1_has_empty_mutation_allowlist() -> None:
    policy = require_auto_accept_policy("RFC_WFM_AUTO_ACCEPT_V1")
    assert policy.policy_id == "RFC_WFM_AUTO_ACCEPT_V1"
    assert policy.mutation_classes == frozenset()
    assert policy.allows_mutation_class("rfc_terminal_status") is False
    assert policy.allows_mutation_class("wfm_plan_reconciliation") is False


def test_unknown_auto_accept_policy_fails_closed() -> None:
    with pytest.raises(SomaError) as excinfo:
        require_auto_accept_policy("RFC_WFM_AUTO_ACCEPT_V2")
    assert excinfo.value.code == "IMPORT_SOURCE_PROFILE_MISMATCH"
