"""Static UI assembly. No missing production draft schemas are manufactured."""
from dataclasses import dataclass

from soma.ui.commands import WorkingCopyCommands
from soma.ui.contracts import WorkingCopyContractRegistry
from soma.ui.queries import WorkingCopyQueries
from soma.ui.routes import WorkingCopyRoutes
from soma.ui.settings import build_ui_setting_registry


@dataclass(frozen=True, slots=True)
class UiRuntime:
    contracts: WorkingCopyContractRegistry
    commands: WorkingCopyCommands
    queries: WorkingCopyQueries
    routes: WorkingCopyRoutes


def build_ui_runtime(connection_factory, *, revision_reader, session_security, clock=None):
    # Accepted owner clarification: actual production entries await design reconciliation.
    contracts = WorkingCopyContractRegistry()
    options = {} if clock is None else {'clock': clock}
    commands = WorkingCopyCommands(connection_factory, contracts, **options)
    queries = WorkingCopyQueries(connection_factory, contracts, revision_reader, **options)
    return UiRuntime(contracts, commands, queries, WorkingCopyRoutes(commands, queries, session_security))
