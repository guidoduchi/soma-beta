from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes, loads_strict_bytes

_ORIGIN = re.compile(r"^http://127\.0\.0\.1:([1-9][0-9]{0,4})$")
_BIRTH = re.compile(r"^[1-9][0-9]{0,19}$")


@dataclass(frozen=True, slots=True)
class RuntimeRegistryRecord:
    registry_version: int
    origin: str
    pid: int
    process_birth_id: str
    run_id: str
    protocol_version: str
    data_instance_id: str
    readiness_locator: str
    published_at_utc: int

    def validate(self) -> None:
        origin = _ORIGIN.fullmatch(self.origin) if isinstance(self.origin, str) else None
        if type(self.registry_version) is not int or self.registry_version != 2 or origin is None or int(origin[1]) > 65535:
            raise ValidationError("runtime registry version/origin is invalid")
        if type(self.pid) is not int or self.pid <= 0:
            raise ValidationError("runtime registry pid is invalid")
        if not isinstance(self.process_birth_id, str) or not _BIRTH.fullmatch(self.process_birth_id) or int(self.process_birth_id) > 2**64 - 1:
            raise ValidationError("runtime registry process birth identity is invalid")
        require_uuid4(self.run_id)
        require_uuid4(self.data_instance_id)
        if self.protocol_version != "1":
            raise ValidationError("runtime registry protocol version is invalid")
        if (
            not isinstance(self.readiness_locator, str)
            or self.readiness_locator != f"run-{self.run_id}.dpapi"
        ):
            raise ValidationError("runtime registry readiness locator is invalid")
        if type(self.published_at_utc) is not int or self.published_at_utc < 0:
            raise ValidationError("runtime registry publication time is invalid")

    def document(self) -> dict[str, object]:
        self.validate()
        return {
            "registry_version": self.registry_version,
            "origin": self.origin,
            "pid": self.pid,
            "process_birth_id": self.process_birth_id,
            "run_id": self.run_id,
            "protocol_version": self.protocol_version,
            "data_instance_id": self.data_instance_id,
            "readiness_locator": self.readiness_locator,
            "published_at_utc": self.published_at_utc,
        }


class RuntimeRegistry:
    @staticmethod
    def _parse(raw: bytes) -> RuntimeRegistryRecord:
        value = loads_strict_bytes(raw, max_bytes=16_384)
        if not isinstance(value, dict) or set(value) != {
            "registry_version",
            "origin",
            "pid",
            "process_birth_id",
            "run_id",
            "protocol_version",
            "data_instance_id",
            "readiness_locator",
            "published_at_utc",
        }:
            raise IntegrityFailure("runtime registry shape is invalid")
        try:
            record = RuntimeRegistryRecord(
                registry_version=value["registry_version"],
                origin=value["origin"],
                pid=value["pid"],
                process_birth_id=value["process_birth_id"],
                run_id=value["run_id"],
                protocol_version=value["protocol_version"],
                data_instance_id=value["data_instance_id"],
                readiness_locator=value["readiness_locator"],
                published_at_utc=value["published_at_utc"],
            )
            record.validate()
        except (ValidationError, TypeError) as exc:
            raise IntegrityFailure("runtime registry values are invalid") from exc
        return record

    @classmethod
    def read(cls, path: Path) -> RuntimeRegistryRecord | None:
        target = Path(path)
        try:
            with target.open("rb") as handle:
                raw = handle.read(16_385)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise IntegrityFailure("runtime registry cannot be read") from exc
        return cls._parse(raw)

    @staticmethod
    def publish(path: Path, record: RuntimeRegistryRecord, *, file_security=None) -> None:
        target = Path(path)
        if not target.is_absolute() or not target.parent.exists():
            raise ValidationError("runtime registry path is unavailable")
        if target.exists():
            raise IntegrityFailure("existing runtime registry requires trusted reconciliation before publication")
        payload = canonical_json_bytes(record.document()) + b"\n"
        temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4()}"
        created = False
        try:
            if file_security is not None:
                file_security.verify(target.parent)
            with (temporary.open("xb") if file_security is None else file_security.create_file(temporary)) as handle:
                created = True
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if file_security is not None:
                file_security.ensure_owner_only_file(temporary)
            # Publication must never replace a registry that appeared meanwhile.
            if os.name == "nt":
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
                temporary.unlink()
            if file_security is not None:
                file_security.ensure_owner_only_file(target)
            try:
                directory_fd = os.open(target.parent, os.O_RDONLY)
            except (OSError, TypeError):
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
        except BaseException:
            if created:
                temporary.unlink(missing_ok=True)
            raise

    @classmethod
    def remove_owned(
        cls,
        path: Path,
        *,
        run_id: str,
        data_instance_id: str,
        pid: int | None = None,
        process_birth_id: str | None = None,
        file_security=None,
    ) -> bool:
        require_uuid4(run_id)
        require_uuid4(data_instance_id)
        if file_security is not None:
            file_security.verify(Path(path).parent)
            if not Path(path).exists():
                return False
            file_security.ensure_owner_only_file(path)
        if file_security is not None:
            with Path(path).open("rb") as handle:
                captured = handle.read(16_385)
            current = cls._parse(captured)
        else:
            current = cls.read(path)
        if current is None:
            return False
        if current.run_id != run_id or current.data_instance_id != data_instance_id:
            return False
        if pid is not None and current.pid != pid or process_birth_id is not None and current.process_birth_id != process_birth_id:
            return False
        if file_security is not None:
            file_security.ensure_owner_only_file(path)
            return file_security.remove_exact_file(path, captured)
        try:
            Path(path).unlink()
        except FileNotFoundError:
            return False
        return True
