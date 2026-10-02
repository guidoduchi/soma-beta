"""Proof of scaffold safety, not proof of LLD12-P008 trusted-runtime operation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from soma.security.runtime.source_control import SourceOutcome, source_action

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_launcher", ROOT / "tools/source_launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class Environment:
    def __init__(self, root, install_status=0):
        self.root = root
        self.calls = []
        self.creations = 0
        self.install_status = install_status

    def create(self, path):
        self.creations += 1
        interpreter = path / "Scripts/python.exe"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_bytes(b"test executable placeholder")

    def run(self, arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        if "-c" in arguments:
            return SimpleNamespace(returncode=0, stdout=json.dumps([[3, 14], str(self.root / ".venv"), "base"]))
        return SimpleNamespace(returncode=self.install_status)


def test_setup_rerun_reuses_environment_and_preserves_data(tmp_path, capsys):
    data = tmp_path / "data/soma.db"
    data.parent.mkdir()
    data.write_bytes(b"authoritative data must remain byte identical")
    runtime = tmp_path / "runtime/runtime.json"
    runtime.parent.mkdir()
    runtime.write_bytes(b"untrusted/stale registry must not be erased")
    env = Environment(tmp_path)
    assert launcher.setup(tmp_path, run=env.run, builder=env) == 0
    assert launcher.setup(tmp_path, run=env.run, builder=env) == 0
    assert env.creations == 1
    assert data.read_bytes() == b"authoritative data must remain byte identical"
    assert runtime.read_bytes() == b"untrusted/stale registry must not be erased"
    installs = [call for call in env.calls if "pip" in call[0]]
    assert len(installs) == 2
    assert all(call[0][-3:] == ["install", "-e", ".[test]"] for call in installs)
    assert all(call[1]["cwd"] == tmp_path and "shell" not in call[1] for call in installs)
    assert "not the production installer" in capsys.readouterr().out


@pytest.mark.parametrize("version,platform", [((3, 12), "nt"), ((3, 15), "nt"), ((3, 14), "posix")])
def test_unsupported_prerequisites_are_explicit(version, platform):
    with pytest.raises(launcher.PrerequisiteError, match="require|Install"):
        launcher.check_python(version, platform)


@pytest.mark.parametrize("version", [(3, 13), (3, 14)])
def test_supported_python(version):
    launcher.check_python(version, "nt")


def test_incomplete_environment_is_preserved(tmp_path):
    environment = tmp_path / ".venv"
    environment.mkdir()
    marker = environment / "keep"
    marker.write_text("keep")
    env = Environment(tmp_path)
    with pytest.raises(launcher.PrerequisiteError, match="missing/incomplete"):
        launcher.setup(tmp_path, run=env.run, builder=env)
    assert env.creations == 0 and marker.read_text() == "keep"
    assert env.calls == []


@pytest.mark.parametrize("payload", ["invalid", "[]", '[[3,12],"wrong","base"]', '[[3,14],"wrong","base"]'])
def test_wrong_environment_rejected_before_pip(tmp_path, payload):
    env = Environment(tmp_path)
    env.create(tmp_path / ".venv")
    def run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=payload)
    with pytest.raises(launcher.PrerequisiteError):
        launcher.setup(tmp_path, run=run, builder=env)
    assert env.creations == 1


def test_setup_dependency_failure_is_actionable(tmp_path, capsys):
    env = Environment(tmp_path, install_status=7)
    assert launcher.setup(tmp_path, run=env.run, builder=env) == 11
    assert "rerun soma_setup.bat" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["run", "console", "stop"])
def test_gate_has_no_external_authority_even_if_a_runtime_exists(action, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("blocked source control attempted external authority")
    import os
    import socket
    import webbrowser
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "unlink", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(webbrowser, "open", forbidden)
    result = source_action(action)
    assert result.outcome is SourceOutcome.DEPENDENCY_PENDING
    assert result.exit_code == 20
    assert "No host was started, opened or stopped" in result.message


@pytest.mark.parametrize("action", ["run", "console", "stop"])
def test_runtime_cli_propagates_dependency_status_without_installing(action, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "check_python", lambda: None)
    monkeypatch.setattr(launcher, "validate_environment", lambda root: root / ".venv/Scripts/python.exe")
    monkeypatch.setattr(launcher, "setup", lambda *args: pytest.fail("runtime cannot install dependencies"))
    assert launcher.main([action]) == 20
    assert "dependency_pending" in capsys.readouterr().err


def test_cli_propagates_prerequisite_and_operation_failures(monkeypatch, capsys):
    def unsupported():
        raise launcher.PrerequisiteError("Install supported Python")
    monkeypatch.setattr(launcher, "check_python", unsupported)
    assert launcher.main(["console"]) == 10
    assert "Install supported Python" in capsys.readouterr().err
    monkeypatch.setattr(launcher, "check_python", lambda: None)
    def broken(root):
        raise OSError("sensitive environment detail")
    monkeypatch.setattr(launcher, "setup", broken)
    assert launcher.main(["setup"]) == 11
    assert "sensitive" not in capsys.readouterr().err


def test_unknown_control_action_cannot_dispatch():
    with pytest.raises(ValueError):
        source_action("kill")


def test_cross_platform_runtime_import_in_fresh_process():
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from soma.security.runtime.source_control import source_action; assert source_action('stop').exit_code == 20", str(ROOT / "src")],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_setup_rejects_file_in_place_of_environment(tmp_path):
    (tmp_path / ".venv").write_bytes(b"preserve this file")
    with pytest.raises(launcher.PrerequisiteError, match="directory"):
        launcher.setup(tmp_path)
    assert (tmp_path / ".venv").read_bytes() == b"preserve this file"


def test_environment_redirect_is_rejected_before_interpreter_execution(tmp_path):
    environment = tmp_path / ".venv"
    environment.mkdir()
    original = Path.is_symlink
    def redirected(path):
        return path == environment or original(path)
    from unittest.mock import patch
    with patch.object(Path, "is_symlink", redirected):
        with pytest.raises(launcher.PrerequisiteError, match="reparse"):
            launcher.setup(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows BAT integration; imports tested on Ubuntu")
def test_real_bat_adapters_propagate_missing_and_blocked_status(tmp_path):
    # Exercise quoting and anchoring from another working directory.
    root = tmp_path / "source checkout & spaces"
    (root / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / "tools/source_launcher.py", root / "tools/source_launcher.py")
    shutil.copy2(ROOT / "pyproject.toml", root / "pyproject.toml")
    shutil.copytree(ROOT / "src/soma/security", root / "src/soma/security", ignore=shutil.ignore_patterns("__pycache__"))
    names = ["soma_run.bat", "soma_run_console.bat", "soma_stop.bat"]
    for name in names:
        shutil.copy2(ROOT / name, root / name)
        result = subprocess.run(f'cmd.exe /d /s /c ""{root / name}""', cwd=tmp_path, capture_output=True, text=True, timeout=15)
        assert result.returncode == 10, result.stderr
        assert "soma_setup.bat" in result.stderr
    import venv
    venv.EnvBuilder(with_pip=False).create(root / ".venv")
    for name in names:
        result = subprocess.run(f'cmd.exe /d /s /c ""{root / name}""', cwd=tmp_path, capture_output=True, text=True, timeout=15)
        assert result.returncode == 20, result.stderr
        assert "dependency_pending" in result.stderr
    assert not (root / "runtime").exists()
    assert not (root / "data").exists()
