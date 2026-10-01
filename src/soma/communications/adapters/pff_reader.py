"""Read-only PFF boundary, independent of the release-selected native binding.

The release bridge must preflight parser sizes before allocating content, yield
one bounded TransientMessage at a time, and keep native handles private. It is
injected statically by the packaged host. This module neither chooses a libpff
revision nor discovers alternate providers. No configured bridge means UNSUPPORTED.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import base64
import json
from typing import Protocol

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.strict_json import canonical_json_bytes
from soma.communications.contracts.common import closed, integer, text
from soma.communications.contracts.message import TransientMessage, TransientAttachment
from soma.communications.contracts.source import SourceProbe, ProviderCheckpoint


def _call(operation, *args):
    try:
        return True, operation(*args)
    except Exception:
        return False, None


def _next(iterator):
    try:
        return "ITEM", next(iterator)
    except StopIteration:
        return "END", None
    except Exception:
        return "FAILED", None


class PffReadOnlyBackend(Protocol):
    """Private release bridge. All opens must request native read-only access.

    probe returns typed metadata only. messages receives the exact checkpoint
    and overlap/range policy and yields bounded PffMessage values, never native
    items. Preflight covers body, participant, attachment and aggregate bounds
    before allocation/read. Failure must stop iteration, never imply exhaustion.
    """
    def probe(self, location, profile) -> SourceProbe: ...
    def open(self, location, profile): ...
    def close(self, native): ...
    def messages(self, native, folder, checkpoint, overlap): ...


@dataclass(frozen=True, slots=True)
class PffMessage:
    message: TransientMessage = field(repr=False)
    generation: str
    position: int

    def __post_init__(self):
        if not isinstance(self.message, TransientMessage):
            raise ValidationError("PFF bridge requires bounded typed messages")
        text(self.generation, minimum=1, maximum=128)
        integer(self.position)


class _Reader:
    __slots__ = ("_native", "_owner", "_active")

    def __init__(self, native, owner):
        self._native, self._owner, self._active = native, owner, True

    def __repr__(self):
        return "<SourceReaderHandle>"


class _ContentStream:
    __slots__ = ("_stream", "_reader", "_remaining", "_checked_end")

    def __init__(self, stream, reader, size):
        self._stream, self._reader, self._remaining = stream, reader, size
        self._checked_end = False

    def read(self, size=-1):
        if not self._reader._active:
            raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication reader is closed")
        if type(size) is not int or size < -1:
            raise ValidationError("Communication attachment read size is invalid")
        limit = self._remaining if size == -1 else min(size, self._remaining)
        if limit == 0:
            if self._remaining == 0 and not self._checked_end:
                ok, value = _call(lambda: self._stream.read(1))
                if not ok or type(value) is not bytes or value:
                    raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication attachment size changed")
                self._checked_end = True
            return b""
        ok, value = _call(lambda: self._stream.read(limit))
        if not ok or type(value) is not bytes or len(value) > limit or not value:
            raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication attachment cannot be read")
        self._remaining -= len(value)
        return value

    def __repr__(self):
        return "<TransientAttachmentStream>"


class PffReaderAdapter:
    def __init__(self, backend=None, *, adapter_version=None):
        if backend is not None and adapter_version is None:
            raise ValidationError("A release bridge requires an explicit adapter version")
        self._backend = backend
        self.adapter_version = text(adapter_version or "unconfigured", minimum=1, maximum=128)

    def probe_read_only(self, source_location, adapter_profile):
        if self._backend is None:
            return SourceProbe("UNSUPPORTED", "libpff", self.adapter_version, None, ())
        try:
            result = self._backend.probe(source_location, adapter_profile)
            if not isinstance(result, SourceProbe) or (result.adapter_family, result.adapter_version) != ("libpff", self.adapter_version):
                raise ValueError()
            return result
        except Exception:
            # Parser exception messages, paths and customer content never escape.
            return SourceProbe("CORRUPT", "libpff", self.adapter_version, None, ())

    @contextmanager
    def open_read_only(self, source_location, adapter_profile):
        if self._backend is None:
            raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication source has no installed release bridge")
        ok, native = _call(self._backend.open, source_location, adapter_profile)
        if not ok:
            raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication source cannot be opened")
        reader = _Reader(native, self)
        inspection_completed = False
        try:
            yield reader
            inspection_completed = True
        finally:
            reader._active = False
            reader._native = None
            ok, _ = _call(self._backend.close, native)
            # Preserve an inspection failure. Raising during its unwind would
            # attach that exception as context and replace its registered code.
            if not ok and inspection_completed:
                raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication reader cannot be closed")

    @staticmethod
    def checkpoint(folder_key, generation, position, provider_time=None):
        text(folder_key, minimum=1, maximum=512)
        text(generation, minimum=1, maximum=128)
        integer(position)
        token = base64.urlsafe_b64encode(canonical_json_bytes({"v": 1, "folder": folder_key,
            "generation": generation, "position": position})).rstrip(b"=").decode("ascii")
        return ProviderCheckpoint("COMPOSITE", token, provider_time)

    @staticmethod
    def _decode(checkpoint):
        if not isinstance(checkpoint, ProviderCheckpoint) or checkpoint.checkpoint_kind != "COMPOSITE":
            return None
        try:
            raw = base64.urlsafe_b64decode(checkpoint.opaque_token + "=" * (-len(checkpoint.opaque_token) % 4))
            value = closed(json.loads(raw), {"v", "folder", "generation", "position"})
            if type(value["v"]) is not int or value["v"] != 1 or canonical_json_bytes(value) != raw:
                return None
            text(value["folder"], minimum=1, maximum=512)
            text(value["generation"], minimum=1, maximum=128)
            integer(value["position"])
            if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != checkpoint.opaque_token:
                return None
            return value
        except Exception:
            return None

    def compare_checkpoints(self, left, right):
        a, b = self._decode(left), self._decode(right)
        if a is None or b is None or (a["folder"], a["generation"]) != (b["folder"], b["generation"]):
            return "INDETERMINATE"
        return "BEFORE" if a["position"] < b["position"] else "AFTER" if a["position"] > b["position"] else "EQUAL"

    def enumerate(self, reader, folder_scope, provider_checkpoint, overlap_policy):
        if not isinstance(reader, _Reader) or reader._owner is not self or not reader._active:
            raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication reader is unavailable")
        if provider_checkpoint is not None:
            decoded = self._decode(provider_checkpoint)
            if decoded is None or decoded["folder"] != folder_scope.folder_key:
                raise SomaError("COMM_STALE", "Communication checkpoint is incompatible")
        ok, values = _call(self._backend.messages, reader._native, folder_scope, provider_checkpoint, overlap_policy)
        ok_iterator, iterator = _call(iter, values) if ok else (False, None)
        if not ok_iterator:
            raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication source inspection failed")
        while True:
            state, record = _next(iterator)
            if state == "END":
                return
            if state != "ITEM" or not isinstance(record, PffMessage) or record.message.folder != folder_scope:
                raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication source inspection failed")
            value = record.message
            attachments = tuple(TransientAttachment(item.ordinal, item.filename, item.mime_type, item.size_bytes,
                _ContentStream(item.content_stream_ref, reader, item.size_bytes)) for item in value.attachments)
            yield replace(value, attachments=attachments, provider_position=self.checkpoint(folder_scope.folder_key,
                record.generation, record.position, value.provider_position.provider_time_source_epoch_ms))

    @staticmethod
    def stable_origin_identity(transient_message):
        if not isinstance(transient_message, TransientMessage):
            raise ValidationError("Communication identity requires typed transient evidence")
        return transient_message.provider_identity
