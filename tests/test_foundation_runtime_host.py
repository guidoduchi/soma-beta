from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.runtime import HostRuntime, InstancePaths, RuntimeRegistry


class _Server:
    def __init__(self, *, self_health: bool = True, fail_start: bool = False) -> None:
        self.self_health = self_health
        self.fail_start = fail_start
        self.started = False
        self.stopped = False
        self.health_calls = []
        self.stop_timeouts = []

    def start(self, bound_socket) -> None:
        if self.fail_start:
            raise RuntimeError("injected server startup failure")
        bound_socket.listen(8)
        self.started = True

    def authenticated_self_health(self, expected) -> bool:
        self.health_calls.append(expected)
        return self.self_health

    def stop(self, timeout_seconds=None) -> None:
        self.stop_timeouts.append(timeout_seconds)
        self.stopped = True

    def is_stopped(self) -> bool:
        return self.stopped


class _RunSecurity:
    def __init__(self) -> None:
        self.prepared = []
        self.closed = []

    def prepare_run(self, **values) -> None:
        self.prepared.append(values)

    def close_run(self, **values) -> None:
        self.closed.append(values)


def _runtime(
    tmp_path,
    migration_directory,
    security_provider,
    *,
    server=None,
    run_security=None,
):
    paths = InstancePaths.from_root(tmp_path.resolve())
    factory = ConnectionFactory(paths.database, security_provider, driver=sqlite3)
    manifest = MigrationManifest.load(migration_directory)
    reconciled = []

    def runner_factory(ownership_assertion):
        return MigrationRunner(
            canonical_database_path=paths.database,
            manifest=manifest,
            factory_for_path=lambda path: ConnectionFactory(
                path,
                security_provider,
                driver=sqlite3,
            ),
            app_version="runtime-test",
            ownership_assertion=ownership_assertion,
        )

    security = run_security or _RunSecurity()
    adapter = server or _Server()
    runtime = HostRuntime(
        paths=paths,
        connection_factory=factory,
        migration_manifest=manifest,
        migration_runner_factory=runner_factory,
        server=adapter,
        run_security=security,
        startup_reconciler=lambda run_id, now: reconciled.append((run_id, now)),
        app_version="test",
        protocol_version="1",
        process_birth_id="runtime-test-process",
    )
    return runtime, paths, adapter, security, reconciled


def test_host_reaches_ready_only_after_verified_migration_security_server_and_self_health(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, paths, server, security, reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    health = runtime.start()

    assert runtime.state == "READY"
    assert health.host_state == "READY"
    assert health.migration_sequence == len(MigrationManifest.load(migration_directory).entries)
    assert health.migration_id == MigrationManifest.load(migration_directory).entries[-1].migration_id
    assert health.integrity_state == "VERIFIED"
    assert health.data_instance_id
    assert len(reconciled) == 1 and reconciled[0][0] == health.run_id
    assert server.started
    assert len(server.health_calls) == 1
    assert server.health_calls[0].host_state == "LISTENING_NOT_READY"
    assert security.prepared[0]["run_id"] == health.run_id

    registry = RuntimeRegistry.read(paths.registry)
    assert registry is not None
    assert registry.run_id == health.run_id
    assert registry.data_instance_id == health.data_instance_id
    assert registry.readiness_locator.endswith(
        f":{int(registry.readiness_locator.rsplit(':',1)[1])}"
    )

    quiescing = runtime.quiesce()
    assert quiescing.shutdown_state == "QUIESCING"
    assert runtime.quiesce().shutdown_state == "ALREADY_QUIESCING"
    stopped = runtime.shutdown(grace_seconds=1)
    assert stopped.shutdown_state == "STOPPED"
    assert runtime.state == "STOPPED"
    assert server.stopped
    assert security.closed == [
        {"run_id": health.run_id, "data_instance_id": health.data_instance_id}
    ]
    assert not paths.registry.exists()

    # Released instance ownership permits a later host.
    runtime2, _paths2, _server2, _security2, _reconciled2 = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    health2 = runtime2.start()
    assert health2.data_instance_id == health.data_instance_id
    assert health2.run_id != health.run_id
    runtime2.shutdown(grace_seconds=1)


def test_host_failure_after_registry_publication_unwinds_only_current_owned_resources(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    server = _Server(self_health=False)
    runtime, paths, _server, security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
        server=server,
    )

    with pytest.raises(SomaError) as raised:
        runtime.start()
    assert raised.value.code == "SECURITY_NOT_READY"
    assert runtime.state == "FAILED"
    assert server.stopped
    assert not paths.registry.exists()
    assert len(security.prepared) == 1
    assert len(security.closed) == 1

    replacement, _paths, _adapter, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    replacement.start()
    replacement.shutdown(grace_seconds=1)


def test_host_server_start_failure_never_publishes_registry_and_releases_lock(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, paths, server, security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
        server=_Server(fail_start=True),
    )
    with pytest.raises(RuntimeError, match="injected server startup failure"):
        runtime.start()
    assert runtime.state == "FAILED"
    assert not paths.registry.exists()
    assert len(security.prepared) == 1
    assert len(security.closed) == 1

    replacement, _paths, _adapter, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    replacement.start()
    replacement.shutdown(grace_seconds=1)


def test_host_executor_quiescence_rejects_new_work(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, _paths, _server, _security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    runtime.start()
    assert runtime.request_executor.submit(lambda: 7).result(timeout=2) == 7
    runtime.quiesce()
    with pytest.raises(SomaError) as raised:
        runtime.request_executor.submit(lambda: 8)
    assert raised.value.code == "HOST_QUIESCING"
    runtime.shutdown(grace_seconds=1)



def test_shutdown_request_commits_one_receipt_audit_then_closes_writer_admission(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, _paths, _server, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    health = runtime.start()
    command_id = __import__("soma.foundation.identifiers", fromlist=["new_uuid4"]).new_uuid4()

    accepted = runtime.request_shutdown(
        command_id=command_id,
        run_id=health.run_id,
        data_instance_id=health.data_instance_id,
    )
    assert accepted.shutdown_state == "QUIESCING"
    assert runtime.state == "QUIESCING"

    with ReadSnapshot(runtime.connection_factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE command_id=? AND action_type='foundation.runtime_shutdown_requested'",
            (command_id,),
        ).fetchone()[0] == 1

    with pytest.raises(SomaError) as raised:
        with UnitOfWork(runtime.connection_factory):
            pass
    assert raised.value.code == "HOST_QUIESCING"

    repeated = runtime.request_shutdown(
        command_id=command_id,
        run_id=health.run_id,
        data_instance_id=health.data_instance_id,
    )
    assert repeated.shutdown_state == "ALREADY_QUIESCING"
    with ReadSnapshot(runtime.connection_factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1

    runtime.shutdown(grace_seconds=1)


class _PartialStartServer(_Server):
    def start(self, bound_socket) -> None:
        bound_socket.listen(8)
        self.started = True
        raise RuntimeError("injected failure after server resource acquisition")


class _FailingStopServer(_Server):
    def __init__(self, *, self_health: bool = False) -> None:
        super().__init__(self_health=self_health)
        self.stop_failures_remaining = 1

    def stop(self, timeout_seconds=None) -> None:
        self.stop_timeouts.append(timeout_seconds)
        if self.stop_failures_remaining:
            self.stop_failures_remaining -= 1
            raise RuntimeError("injected server stop failure")
        self.stopped = True


def test_prepare_for_start_failure_requiesces_writer_gate(
    tmp_path,
    migration_directory,
    security_provider,
    monkeypatch,
) -> None:
    runtime, _paths, _server, _security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    runtime.start()
    runtime.shutdown(grace_seconds=1)

    def fail_prepare(_self):
        raise OSError("injected path preparation failure")

    monkeypatch.setattr(InstancePaths, "prepare_for_start", fail_prepare)
    with pytest.raises(OSError, match="injected path preparation failure"):
        runtime.start()

    assert runtime.state == "FAILED"
    with pytest.raises(SomaError) as raised:
        with UnitOfWork(runtime.connection_factory):
            pass
    assert raised.value.code == "HOST_QUIESCING"


def test_partial_server_start_is_owned_and_stopped_during_failed_start(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    server = _PartialStartServer()
    runtime, paths, _server, security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
        server=server,
    )

    with pytest.raises(
        RuntimeError,
        match="injected failure after server resource acquisition",
    ):
        runtime.start()

    assert runtime.state == "FAILED"
    assert server.started
    assert server.stopped
    assert not paths.registry.exists()
    assert len(security.closed) == 1

    replacement, _paths, _adapter, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    replacement.start()
    replacement.shutdown(grace_seconds=1)


def test_failed_stop_retains_runtime_ownership_until_server_is_proved_stopped(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    server = _FailingStopServer(self_health=False)
    runtime, paths, _server, security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
        server=server,
    )

    with pytest.raises(SomaError) as raised:
        runtime.start()
    assert raised.value.code == "SECURITY_NOT_READY"
    assert any(
        "failed-start cleanup also failed" in note
        for note in getattr(raised.value, "__notes__", ())
    )
    assert paths.registry.exists()
    assert security.closed == []
    assert runtime._lock is not None and runtime._lock.held

    replacement, _paths, _adapter, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    with pytest.raises(SomaError) as replacement_error:
        replacement.start()
    assert replacement_error.value.code == "INSTANCE_OWNED"

    runtime._close_runtime_resources()
    assert server.stopped
    assert not paths.registry.exists()
    assert len(security.closed) == 1

    replacement.start()
    replacement.shutdown(grace_seconds=1)



class _PartialRunSecurity(_RunSecurity):
    def prepare_run(self, **values) -> None:
        super().prepare_run(**values)
        raise RuntimeError("injected partial security preparation failure")


def test_partial_security_prepare_is_closed_and_releases_ownership(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    partial_security = _PartialRunSecurity()
    runtime, paths, server, security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
        run_security=partial_security,
    )

    with pytest.raises(
        RuntimeError,
        match="injected partial security preparation failure",
    ):
        runtime.start()

    assert runtime.state == "FAILED"
    assert not server.started
    assert len(security.prepared) == 1
    assert len(security.closed) == 1
    assert not paths.registry.exists()
    assert runtime._lock is None

    replacement, _paths, _adapter, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    replacement.start()
    replacement.shutdown(grace_seconds=1)


def test_shutdown_passes_one_decreasing_deadline_budget_to_all_waiting_stages(
    tmp_path,
    migration_directory,
    security_provider,
    monkeypatch,
) -> None:
    runtime, _paths, server, _security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    runtime.start()

    request_executor = runtime.request_executor
    background_executor = runtime.background_executor
    write_waits: list[float] = []
    request_waits: list[float] = []
    background_waits: list[float] = []
    seen_deadlines: list[float] = []
    remaining = iter((0.9, 0.8, 0.7, 0.6, 0.5))

    def remaining_seconds(deadline: float) -> float:
        seen_deadlines.append(deadline)
        return next(remaining)

    monkeypatch.setattr(
        HostRuntime,
        "_remaining_shutdown_seconds",
        staticmethod(remaining_seconds),
    )
    monkeypatch.setattr(
        runtime._write_gate,
        "wait_for_drain",
        lambda timeout: write_waits.append(timeout) or True,
    )
    monkeypatch.setattr(
        request_executor,
        "drain",
        lambda timeout: request_waits.append(timeout) or True,
    )
    monkeypatch.setattr(
        background_executor,
        "drain",
        lambda timeout: background_waits.append(timeout) or True,
    )

    stopped = runtime.shutdown(grace_seconds=1)

    assert stopped.shutdown_state == "STOPPED"
    assert write_waits == [0.9]
    assert request_waits == [0.8]
    assert background_waits == [0.7]
    assert server.stop_timeouts == [0.5]
    assert len(seen_deadlines) == 5
    assert len(set(seen_deadlines)) == 1


def test_zero_grace_still_attempts_nonblocking_checkpoint_and_cleanup_when_idle(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, paths, server, security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    runtime.start()

    stopped = runtime.shutdown(grace_seconds=0)

    assert stopped.shutdown_state == "STOPPED"
    assert runtime.state == "STOPPED"
    assert server.stop_timeouts == [0.0]
    assert not paths.registry.exists()
    assert len(security.closed) == 1
    assert runtime._lock is None


def test_shutdown_drain_timeout_retains_ownership_and_can_be_retried(
    tmp_path,
    migration_directory,
    security_provider,
    monkeypatch,
) -> None:
    runtime, paths, _server, security, _ = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    runtime.start()
    request_executor = runtime.request_executor

    monkeypatch.setattr(request_executor, "drain", lambda timeout: False)
    with pytest.raises(SomaError) as raised:
        runtime.shutdown(grace_seconds=0.01)
    assert raised.value.code == "INTERNAL_ERROR"
    assert runtime.state == "QUIESCING"
    assert paths.registry.exists()
    assert security.closed == []
    assert runtime._lock is not None and runtime._lock.held

    with pytest.raises(SomaError) as gated:
        with UnitOfWork(runtime.connection_factory):
            pass
    assert gated.value.code == "HOST_QUIESCING"

    replacement, _paths, _adapter, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    with pytest.raises(SomaError) as replacement_error:
        replacement.start()
    assert replacement_error.value.code == "INSTANCE_OWNED"

    monkeypatch.setattr(request_executor, "drain", lambda timeout: True)
    runtime.shutdown(grace_seconds=1)

    replacement.start()
    replacement.shutdown(grace_seconds=1)
