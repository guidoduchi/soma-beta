from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace

import pytest

from soma.foundation.errors import SomaError, SecurityNotReady, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.runtime.registry import RuntimeRegistry, RuntimeRegistryRecord
from soma.security.auth.sessions import SessionSecurityProvider
from soma.security.crypto.dpapi import WindowsDpapiProvider
from soma.security.crypto.live_key import LiveDataKeyProvider
from soma.security.crypto.sqlcipher_provider import SqlCipherConnectionSecurityProvider
from soma.security.runtime.control import RunControlProvider, encode_secret
from soma.security.runtime.trust import TrustedInstanceVerifier
from soma.security.runtime.windows import WindowsAclProvider, process_identity


@pytest.fixture
def native_run(tmp_path):
    if os.name != "nt":
        pytest.skip("native Windows run credential integration")
    files = WindowsAclProvider()
    root = tmp_path / "instance"
    files.ensure_owner_only_directory(root)
    identity = process_identity(os.getpid())
    run, data, installation = new_uuid4(), new_uuid4(), new_uuid4()
    control = RunControlProvider(root / "runtime", installation, file_security=files)
    locator = control.prepare_run(run_id=run, data_instance_id=data, readiness_locator="http://127.0.0.1:12345")
    record = RuntimeRegistryRecord(2, "http://127.0.0.1:12345", identity.pid, identity.process_birth_id, run, "1", data, locator, 1)
    RuntimeRegistry.publish(root / "runtime/runtime.json", record, file_security=files)
    health = dict(protocol_version="1", run_id=run, data_instance_id=data, host_state="READY", app_version="test", migration_sequence=17, migration_id="test", integrity_state="VERIFIED", started_at_utc=1, pid=identity.pid, process_birth_id=identity.process_birth_id)
    verifier = TrustedInstanceVerifier(root, identity.image, installation, file_security=files, dpapi=WindowsDpapiProvider(), request=lambda *args, **kwargs: dict(health))
    yield root, files, control, record, health, verifier
    control.close_run(run_id=run, data_instance_id=data)


def test_native_trust_and_control_domain_separation(native_run):
    root, files, control, record, health, verifier = native_run
    trusted = verifier.verify()
    assert trusted.registry == record
    assert encode_secret(trusted.secret) not in repr(trusted)
    assert trusted.secret not in (root / "runtime/runtime.json").read_bytes()
    headers = {"host": "127.0.0.1:12345", "x-soma-run-auth": encode_secret(trusted.secret)}
    assert control.authenticate_control_request(headers, record.run_id).authenticated
    for wrong in [{**headers, "host": "localhost:12345"}, {**headers, "x-forwarded-host": "127.0.0.1:12345"}, {**headers, "x-soma-run-auth": "browser-cookie"}]:
        with pytest.raises(SomaError):
            control.authenticate_control_request(wrong, record.run_id)
    with pytest.raises(SomaError):
        control.authenticate_control_request(headers, new_uuid4())


@pytest.mark.parametrize("field,value", [("run_id", "wrong-run"), ("data_instance_id", "wrong-data"), ("pid", 1), ("process_birth_id", "1"), ("protocol_version", "2"), ("host_state", "LISTENING_NOT_READY"), ("host_state", "QUIESCING")])
def test_health_mismatch_never_proves_trust(native_run, field, value):
    root, files, control, record, health, verifier = native_run
    health[field] = value
    before = (root / "runtime/runtime.json").read_bytes()
    with pytest.raises(SecurityNotReady):
        verifier.verify()
    assert (root / "runtime/runtime.json").read_bytes() == before


@pytest.mark.parametrize("failure", ["dead", "birth", "image"])
def test_dead_reused_or_foreign_process_never_contacts_port(native_run, failure):
    root, files, control, record, health, verifier = native_run
    identity = process_identity(record.pid)
    def read(pid):
        if failure == "dead":
            raise SecurityNotReady("dead process")
        return replace(identity, process_birth_id="1") if failure == "birth" else replace(identity, image=Path("C:/foreign/python.exe"))
    verifier.process = read
    verifier.request = lambda *args, **kwargs: pytest.fail("untrusted process must not receive credential")
    with pytest.raises(SecurityNotReady):
        verifier.verify()
    assert (root / "runtime/runtime.json").exists()


def test_missing_registry_is_nonmutating_and_malformed_is_preserved(native_run):
    root, files, control, record, health, verifier = native_run
    registry = root / "runtime/runtime.json"
    registry.unlink()
    assert verifier.verify() is None
    assert not registry.exists()
    with files.create_file(registry) as handle:
        handle.write(b"{malformed")
    with pytest.raises(SomaError):
        verifier.verify()
    assert registry.read_bytes() == b"{malformed"


@pytest.mark.parametrize("changes", [{"registry_version": 1}, {"registry_version": True}, {"origin": "http://127.0.0.1:65536"}, {"origin": "http://127.0.0.1:12345/"}, {"origin": "http://user@127.0.0.1:12345"}, {"origin": "http://localhost:12345"}, {"origin": "http://127.0.0.1:12345?secret=x"}, {"process_birth_id": "001"}, {"process_birth_id": "18446744073709551616"}, {"readiness_locator": "../foreign.dpapi"}, {"published_at_utc": True}])
def test_registry_v2_rejects_adversarial_shapes(native_run, changes):
    record = native_run[3]
    with pytest.raises(ValidationError):
        replace(record, **changes).validate()


def test_run_cleanup_preserves_foreign_replacement(native_run):
    root, files, control, record, health, verifier = native_run
    path = root / "runtime" / record.readiness_locator
    original = path.read_bytes()
    path.write_bytes(b"foreign envelope")
    with pytest.raises(SecurityNotReady):
        control.close_run(run_id=record.run_id, data_instance_id=record.data_instance_id)
    assert path.read_bytes() == b"foreign envelope"
    path.write_bytes(original)


def test_undecryptable_run_secret_never_contacts_port(native_run):
    root, files, control, record, health, verifier = native_run
    path = root / "runtime" / record.readiness_locator
    original = path.read_bytes()
    try:
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        verifier.request = lambda *args, **kwargs: pytest.fail("invalid credential cannot contact port")
        with pytest.raises(SecurityNotReady):
            verifier.verify()
        assert path.exists()
    finally:
        path.write_bytes(original)


def test_publication_preserves_existing_foreign_registry(native_run):
    root, files, control, record, health, verifier = native_run
    path = root / "runtime/runtime.json"
    original = path.read_bytes()
    with pytest.raises(SomaError):
        RuntimeRegistry.publish(path, replace(record, run_id=new_uuid4()), file_security=files)
    assert path.read_bytes() == original


def test_reused_loopback_port_with_foreign_health_never_proves_trust(native_run):
    from test_security_control_http import endpoint
    from soma.security.runtime.control import direct_request
    root, files, control, record, health, verifier = native_run
    path = root / "runtime/runtime.json"
    with endpoint(body={**health, "run_id": new_uuid4()}) as (origin, calls):
        # Live PID/birth/image and DPAPI still pass; mere HTTP reachability cannot.
        path.write_text(json.dumps(replace(record, origin=origin).document()), encoding="utf-8")
        before = path.read_bytes()
        verifier.request = direct_request
        with pytest.raises(SecurityNotReady, match="health identity mismatch"):
            verifier.verify()
        assert len(calls) == 1 and calls[0][0] == "/api/v1/runtime/health"
        assert path.read_bytes() == before


def test_live_key_creation_requires_lock_and_preserves_existing_database(native_run):
    root, files, _, _, _, _ = native_run
    owned = [False]
    provider = LiveDataKeyProvider(root, new_uuid4(), ownership_assertion=lambda: owned[0], file_security=files)
    with pytest.raises(SecurityNotReady):
        provider.prepare()
    assert not provider.path.exists()
    owned[0] = True
    key = provider.prepare()
    assert len(key) == 32
    assert provider.prepare() == key
    provider.path.unlink()
    (root / "data").mkdir()
    (root / "data/soma.db").write_bytes(b"preserve")
    with pytest.raises(SecurityNotReady):
        provider.prepare()
    assert not provider.path.exists()
    assert (root / "data/soma.db").read_bytes() == b"preserve"


def test_sqlcipher_rejects_plaintext_or_wrong_core_before_schema():
    calls = []
    class Connection:
        def execute(self, sql):
            calls.append(sql)
            return SimpleNamespace(fetchone=lambda: ("4.12.0 community",))
    provider = SqlCipherConnectionSecurityProvider(None)
    with pytest.raises(SecurityNotReady, match="4.17.0"):
        provider.verify_cipher_connection(Connection())
    assert calls == ["PRAGMA cipher_version"]


@pytest.mark.parametrize("failed_pragma", [None, "cipher_page_size", "cipher_use_hmac", "cipher_plaintext_header_size", "cipher_memory_security", "cipher_hmac_algorithm", "foreign_keys"])
def test_sqlcipher_profile_verification_and_fail_closed_pragmas(failed_pragma):
    values = {"cipher_version": "4.17.0 community", "cipher_page_size": 4096, "cipher_use_hmac": 1, "cipher_plaintext_header_size": 0, "cipher_memory_security": 1, "cipher_hmac_algorithm": "HMAC_SHA512", "foreign_keys": 1}
    calls = []
    class Connection:
        def execute(self, sql):
            calls.append(sql)
            if sql == "PRAGMA foreign_keys=ON":
                value = 1
            elif sql.startswith("PRAGMA "):
                name = sql.removeprefix("PRAGMA ")
                value = "wrong" if name == failed_pragma else values[name]
            else:
                value = 0
            return SimpleNamespace(fetchone=lambda: (value,))
    provider = SqlCipherConnectionSecurityProvider(None)
    if failed_pragma is None:
        assert provider.verify_cipher_connection(Connection()).cipher_version == "4.17.0"
        assert calls[-1] == "SELECT count(*) FROM sqlite_master"
    else:
        with pytest.raises(SecurityNotReady):
            provider.verify_cipher_connection(Connection())
        assert "SELECT count(*) FROM sqlite_master" not in calls


def test_session_cookie_csrf_expiry_capacity_and_run_control_separation():
    now = [0]
    run, actor = new_uuid4(), new_uuid4()
    sessions = SessionSecurityProvider(run, "http://127.0.0.1:12345", monotonic=lambda: now[0], utc=lambda: 0)
    session = sessions.issue_session(run, actor)
    headers = {"host": "127.0.0.1:12345", "cookie": session.cookie.split(";", 1)[0]}
    assert sessions.validate_request(SimpleNamespace(headers=headers), mutation=False).actor_id == actor
    for bad in [headers, {**headers, "origin": "http://localhost:12345", "x-soma-csrf": session.csrf_token}, {"host": "127.0.0.1:12345", "x-soma-run-auth": encode_secret(secrets.token_bytes(32))}]:
        with pytest.raises(SomaError):
            sessions.validate_request(SimpleNamespace(headers=bad), mutation=True)
    valid = {**headers, "origin": "http://127.0.0.1:12345", "x-soma-csrf": session.csrf_token}
    sessions.validate_request(SimpleNamespace(headers=valid), mutation=True)
    for _ in range(3):
        sessions.issue_session(run, actor)
    with pytest.raises(SomaError):
        sessions.issue_session(run, actor)
    now[0] = 43200
    with pytest.raises(SomaError):
        sessions.validate_request(SimpleNamespace(headers=headers), mutation=False)
    replacement = sessions.issue_session(run, actor)
    sessions.invalidate_all("run_end")
    with pytest.raises(SomaError):
        sessions.validate_request(SimpleNamespace(headers={**headers, "cookie": replacement.cookie.split(";", 1)[0]}), mutation=False)
