"""Real Windows primitives, separately from injected launcher/protocol tests."""
import os
from pathlib import Path
import secrets
import subprocess
import sys

import pytest

from soma.foundation.errors import SecurityNotReady
from soma.foundation.identifiers import new_uuid4
from soma.security.crypto.dpapi import WindowsDpapiProvider
from soma.security.runtime.windows import WindowsAclProvider, local_app_data, process_identity

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows trust primitives")


def test_dpapi_native_round_trip_and_separate_bindings():
    provider = WindowsDpapiProvider()
    installation_id = new_uuid4()
    secret = secrets.token_bytes(32)
    protected = provider.protect_current_user(secret, "run_control", installation_id)
    assert secret not in protected
    assert provider.unprotect_current_user(protected, "run_control", installation_id) == secret
    for purpose, binding, blob in [("live_data_dek", installation_id, protected), ("run_control", new_uuid4(), protected), ("run_control", installation_id, protected[:-1]), ("run_control", installation_id, protected[:-1] + bytes([protected[-1] ^ 1]))]:
        with pytest.raises(SecurityNotReady):
            provider.unprotect_current_user(blob, purpose, binding)


def test_dpapi_live_key_magic_and_exact_length():
    provider = WindowsDpapiProvider()
    installation_id = new_uuid4()
    secret = secrets.token_bytes(32)
    protected = provider.protect_current_user(secret, "live_data_dek", installation_id)
    assert protected.startswith(b"SOMA-DPAPI-KEY-V1\0")
    assert provider.unprotect_current_user(protected, "live_data_dek", installation_id) == secret
    with pytest.raises(SecurityNotReady):
        provider.protect_current_user(b"short", "run_control", installation_id)


def test_native_process_creation_identity_and_image():
    first = process_identity(os.getpid())
    assert first == process_identity(os.getpid())
    assert str(int(first.process_birth_id)) == first.process_birth_id
    assert first.image.samefile(sys._base_executable) or first.image.samefile(sys.executable)
    child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"])
    try:
        identity = process_identity(child.pid)
        assert identity.pid == child.pid
        assert identity.process_birth_id != first.process_birth_id
    finally:
        # Only terminate the test's own retained child handle, never discovered PIDs.
        child.terminate()
        child.wait(timeout=10)
    with pytest.raises(SecurityNotReady):
        process_identity(child.pid)


def test_native_owner_only_creation_and_broad_acl_rejection(tmp_path):
    provider = WindowsAclProvider()
    directory = tmp_path / "owned"
    provider.ensure_owner_only_directory(directory)
    provider.verify(directory)
    file = directory / "secret.dpapi"
    with provider.create_file(file) as handle:
        handle.write(b"ciphertext")
    provider.ensure_owner_only_file(file)
    assert file.read_bytes() == b"ciphertext"
    with pytest.raises(SecurityNotReady):
        provider.verify(tmp_path)
    with pytest.raises(SecurityNotReady):
        provider.create_file(file)


def test_native_known_folder_is_existing_absolute():
    assert local_app_data().is_absolute()
    assert local_app_data().is_dir()
