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

_REGISTRY_SCHEMA = "SOMA-RUNTIME-REGISTRY-V1"
_LOCATOR = re.compile(r"^http://127\.0\.0\.1:[1-9][0-9]{0,4}$")


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

    def validate(self) -> None:
        if self.registry_version != 1 or self.origin != "SOMA":
            raise ValidationError("runtime registry version/origin is invalid")
        if type(self.pid) is not int or self.pid <= 0:
            raise ValidationError("runtime registry pid is invalid")
        if not isinstance(self.process_birth_id, str) or not self.process_birth_id:
            raise ValidationError("runtime registry process birth identity is invalid")
        require_uuid4(self.run_id)
        require_uuid4(self.data_instance_id)
        if not isinstance(self.protocol_version, str) or not self.protocol_version:
            raise ValidationError("runtime registry protocol version is invalid")
        if (
            not isinstance(self.readiness_locator, str)
            or _LOCATOR.fullmatch(self.readiness_locator) is None
        ):
            raise ValidationError("runtime registry readiness locator is invalid")

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
            )
            record.validate()
        except (ValidationError, TypeError) as exc:
            raise IntegrityFailure("runtime registry values are invalid") from exc
        return record

    @classmethod
    def read(cls, path: Path) -> RuntimeRegistryRecord | None:
        target = Path(path)
        try:
            raw = target.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise IntegrityFailure("runtime registry cannot be read") from exc
        return cls._parse(raw)

    @staticmethod
    def publish(path: Path, record: RuntimeRegistryRecord) -> None:
        target = Path(path)
        if not target.is_absolute() or not target.parent.exists():
            raise ValidationError("runtime registry path is unavailable")
        payload = canonical_json_bytes(record.document()) + b"\n"
        temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4()}"
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
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
            temporary.unlink(missing_ok=True)
            raise

    @classmethod
    def remove_owned(
        cls,
        path: Path,
        *,
        run_id: str,
        data_instance_id: str,
    ) -> bool:
        require_uuid4(run_id)
        require_uuid4(data_instance_id)
        current = cls.read(path)
        if current is None:
            return False
        if current.run_id != run_id or current.data_instance_id != data_instance_id:
            return False
        try:
            Path(path).unlink()
        except FileNotFoundError:
            return False
        return True
