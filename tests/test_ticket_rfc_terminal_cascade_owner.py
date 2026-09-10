from __future__ import annotations

import soma.tickets.rfc_terminal_cascade_execute as compatibility_module
from soma.tickets.rfc_terminal_cascade import (
    RfcTerminalCascadeExecutionService,
    RfcTerminalCascadeRefreshService,
)


def test_terminal_cascade_public_command_owners_match_certified_module_map() -> None:
    assert RfcTerminalCascadeExecutionService.__module__ == "soma.tickets.rfc_terminal_cascade"
    assert RfcTerminalCascadeRefreshService.__module__ == "soma.tickets.rfc_terminal_cascade"
    assert compatibility_module.RfcTerminalCascadeExecutionService is RfcTerminalCascadeExecutionService
