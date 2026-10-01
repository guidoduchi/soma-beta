"""Local operator artifact publication, with no mail-store mutation API."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from soma.communications.contracts.common import text
from soma.foundation.errors import SomaError, ValidationError


def destination(value):
    text(value, minimum=1, maximum=1024)
    path = Path(value)
    if not path.is_absolute() or value.startswith(("\\\\", "//")):
        raise ValidationError("MSG destination must be a local absolute file path")
    # Resolve existing symlinks before considering either extension or protection.
    try:
        path = path.resolve()
        if path.suffix.lower() != ".msg" or not path.parent.is_dir() or path.is_dir():
            raise ValidationError("MSG destination must select a file in an existing local directory")
        if os.name == "nt" and (os.path.isreserved(str(path)) or ":" in path.name):
            raise ValidationError("MSG destination filename is invalid")
    except (OSError, RuntimeError):
        raise ValidationError("MSG destination cannot be resolved") from None
    return path


def require_unprotected(path, locations):
    for location in locations:
        try:
            protected = Path(location).resolve()
            if path == protected or protected in path.parents:
                raise ValidationError("MSG destination is a protected source location")
        except (OSError, RuntimeError):
            raise ValidationError("Source location protection cannot be established") from None


def _matches(path, artifact):
    if not path.exists() or path.stat().st_size != artifact.size_bytes:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest() == artifact.sha256


class MsgDraftPublisher:
    def publish(self, path, artifact):
        """Verify a matching retry, or fsync and atomically replace a sibling file.

        A DB failure intentionally leaves the published operator artifact. Its
        next attempt verifies the exact hash without requiring earlier DB state.
        Errors contain neither local paths nor authored content.
        """
        succeeded = False
        temporary = None
        try:
            if _matches(path, artifact):
                succeeded = True
            else:
                descriptor, temporary = tempfile.mkstemp(prefix=".soma-msg-", suffix=".tmp", dir=path.parent)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(artifact.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                if not _matches(Path(temporary), artifact):
                    raise OSError("Artifact verification failed")
                os.replace(temporary, path)
                temporary = None
                succeeded = _matches(path, artifact)
        except (OSError, ValueError):
            pass
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        if not succeeded:
            raise SomaError("COMM_MSG_BUILD_FAILED", "MSG draft publication or hash reconciliation failed")
