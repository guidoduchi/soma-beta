"""Detached/reuse/stop races with the real production composition."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

import pytest

from soma.security.runtime import source_control as control
from soma.security.runtime.windows import WindowsAclProvider

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native detached launcher")


@pytest.fixture
def real_launcher(tmp_path, monkeypatch):
    pytest.importorskip("sqlcipher3")
    root = tmp_path / "instance"
    files = WindowsAclProvider()
    files.ensure_owner_only_directory(root)
    original = subprocess.Popen
    children, opened = [], []
    def spawn(arguments, **options):
        # Only replace the CLI's fixed root selection for isolation. The child
        # runs the identical production foreground/composition function.
        child = original([sys.executable, "-I", "-u", "-c", spawn.program, str(root)], **options)
        children.append(child)
        return child
    spawn.program = "import sys; from pathlib import Path; from soma.security.runtime.source_control import foreground; foreground(Path(sys.argv[1]))"
    monkeypatch.setattr(control.subprocess, "Popen", spawn)
    monkeypatch.setattr(control, "open_verified_origin", opened.append)
    yield root, files, children, opened
    try:
        from soma.foundation.errors import SomaError
        try:
            control.stop(root, files)
        except SomaError:
            pass  # Adversarial/crashed test evidence is deliberately preserved.
    finally:
        for child in children:
            child.wait(timeout=15)


def test_detached_ready_reuse_idempotent_stop_and_new_run(real_launcher):
    root, files, children, opened = real_launcher
    assert control.stop(root, files).outcome is control.SourceOutcome.NO_VALID_INSTANCE
    assert control.detached(root, files).exit_code == 0
    first = control.verified_instance(root, files).registry
    assert control.detached(root, files).exit_code == 0
    assert len(children) == 1 and opened == [first.origin, first.origin]
    assert control.stop(root, files).outcome is control.SourceOutcome.STOPPED
    assert control.stop(root, files).outcome is control.SourceOutcome.NO_VALID_INSTANCE
    assert control.detached(root, files).exit_code == 0
    second = control.verified_instance(root, files).registry
    assert first.run_id != second.run_id and first.process_birth_id != second.process_birth_id
    assert first.data_instance_id == second.data_instance_id
    assert control.stop(root, files).exit_code == 0


def test_simultaneous_launchers_converge_on_one_real_host(real_launcher):
    root, files, children, opened = real_launcher
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: control.detached(root, files), range(2)))
    assert [result.exit_code for result in results] == [0, 0]
    trusted = control.verified_instance(root, files)
    assert opened == [trusted.registry.origin, trusted.registry.origin]
    assert control.stop(root, files).exit_code == 0


@pytest.mark.parametrize("phase", ["before_ready", "bound_before_publish", "published_before_ready"])
def test_native_startup_crash_never_opens_unverified_instance(real_launcher, monkeypatch, phase):
    root, files, children, opened = real_launcher
    spawn = control.subprocess.Popen
    normal = spawn.program
    prefix = "import os,sys; from pathlib import Path; from soma.application import SourceApplication; app=SourceApplication(Path(sys.argv[1])); "
    if phase == "before_ready":
        injected = "app.host._startup_reconciler=lambda *args: os._exit(7); app.host.start()"
    elif phase == "bound_before_publish":
        injected = "original=app.server.start; app.server.start=lambda sock: (original(sock),os._exit(8)); app.host.start()"
    else:
        injected = "app.server.authenticated_self_health=lambda expected: os._exit(9); app.host.start()"
    spawn.program = prefix + injected
    assert control.detached(root, files).exit_code == 30
    assert opened == []
    children[-1].wait(timeout=5)
    if phase == "published_before_ready":
        from soma.foundation.errors import SomaError
        registry = root / "runtime" / "runtime.json"
        before = registry.read_bytes()
        monkeypatch.setattr(control, "canonical_source_instance", lambda: root)
        assert control.source_action("stop").exit_code == 31
        assert control.source_action("run").exit_code == 31
        assert registry.read_bytes() == before and opened == []
    else:
        assert not (root / "runtime" / "runtime.json").exists()
        orphans = {path: path.read_bytes() for path in (root / "runtime").glob("run-*.dpapi")}
        assert control.stop(root, files).exit_code == 0
        spawn.program = normal
        assert control.detached(root, files).exit_code == 0
        assert control.stop(root, files).exit_code == 0
        assert all(path.read_bytes() == value for path, value in orphans.items())
