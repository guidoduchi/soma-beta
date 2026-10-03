"""Fresh TrustedLocalInstanceV1 proof; registry timestamps never prove trust."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from soma.foundation.errors import SecurityNotReady
from soma.foundation.runtime.registry import RuntimeRegistry, RuntimeRegistryRecord
from soma.security.runtime.control import direct_request, read_owned_file
from soma.security.runtime.windows import process_identity, reject_redirects


@dataclass(frozen=True, slots=True)
class TrustedInstance:
    registry: RuntimeRegistryRecord
    secret: bytes = field(repr=False)


class TrustedInstanceVerifier:
    def __init__(self, instance_root, expected_image, installation_id, *, file_security, dpapi, process_reader=process_identity, request=direct_request):
        self.root = reject_redirects(Path(instance_root))
        self.registry_path = self.root / "runtime" / "runtime.json"
        self.image = reject_redirects(Path(expected_image)).resolve(strict=True)
        self.installation_id = installation_id
        self.files = file_security
        self.dpapi = dpapi
        self.process = process_reader
        self.request = request

    def verify(self, *, require_ready=True):
        reject_redirects(self.registry_path)
        if not self.root.exists():
            return None
        self.files.verify(self.root)
        if not self.registry_path.parent.exists():
            return None
        self.files.verify(self.registry_path.parent)
        if not self.registry_path.exists():
            return None
        raw = read_owned_file(self.registry_path, self.files, limit=16_384)
        record = RuntimeRegistry._parse(raw)
        identity = self.process(record.pid)
        if identity.pid != record.pid or identity.process_birth_id != record.process_birth_id or identity.image != self.image:
            raise SecurityNotReady("runtime process identity mismatch")
        secret_file = self.registry_path.parent / record.readiness_locator
        secret = self.dpapi.unprotect_current_user(read_owned_file(secret_file, self.files), "run_control", self.installation_id)
        if not isinstance(secret, bytes) or len(secret) != 32:
            raise SecurityNotReady("runtime credential length is invalid")
        health = self.request(record.origin, secret, "GET", "/api/v1/runtime/health", timeout=2)
        expected_fields = {"protocol_version", "run_id", "data_instance_id", "host_state", "app_version", "migration_sequence", "migration_id", "integrity_state", "started_at_utc", "pid", "process_birth_id"}
        if set(health) != expected_fields or any(type(health[key]) is not type(getattr(record, key)) or health[key] != getattr(record, key) for key in ("protocol_version", "run_id", "data_instance_id", "pid", "process_birth_id")):
            raise SecurityNotReady("runtime authenticated health identity mismatch")
        if not isinstance(health["host_state"], str) or health["host_state"] not in {"LISTENING_NOT_READY", "READY", "QUIESCING"} or require_ready and health["host_state"] != "READY":
            raise SecurityNotReady("runtime is not ready")
        if any(type(health[key]) is not int or health[key] < 0 for key in ("migration_sequence", "started_at_utc")) or not isinstance(health["app_version"], str) or not health["app_version"] or not isinstance(health["integrity_state"], str) or health["migration_id"] is not None and not isinstance(health["migration_id"], str):
            raise SecurityNotReady("runtime health fields are invalid")
        if health["host_state"] == "READY" and health["integrity_state"] != "VERIFIED":
            raise SecurityNotReady("runtime readiness integrity is unverified")
        # Revalidate process and registry after the network boundary.
        if self.process(record.pid) != identity or read_owned_file(self.registry_path, self.files, limit=16_384) != raw:
            raise SecurityNotReady("runtime identity changed during verification")
        return TrustedInstance(record, secret)
