import io
from dataclasses import replace

import pytest

from soma.communications.adapters.pff_reader import PffReaderAdapter, PffMessage
from soma.communications.contracts.message import TransientAttachment
from soma.communications.contracts.source import SourceProbe, ProviderCheckpoint
from soma.foundation.errors import SomaError, ValidationError
from test_communications_identity import message


class Backend:
    def __init__(self, values):
        self.values, self.calls = values, []
        self.native = object()

    def probe(self, location, profile):
        return SourceProbe("READY", "libpff", "synthetic-1", "mailbox-A", (message().folder,))

    def open(self, location, profile):
        self.calls.append("read-only-open")
        return self.native

    def close(self, native):
        assert native is self.native
        self.calls.append("close")

    def messages(self, native, folder, checkpoint, overlap):
        assert native is self.native
        self.calls.append((checkpoint, overlap))
        yield from self.values


def test_unconfigured_native_dependency_is_explicitly_unsupported_and_not_a_pin():
    adapter = PffReaderAdapter()
    assert adapter.probe_read_only("private.pst", None).health == "UNSUPPORTED"
    with pytest.raises(SomaError, match="release bridge"):
        with adapter.open_read_only("private.pst", None):
            pass
    with pytest.raises(ValidationError):
        PffReaderAdapter(Backend([]))


def test_typed_boundary_preserves_provider_identity_and_independent_chronology_and_wraps_streams():
    value = replace(message(), attachments=(TransientAttachment(0, "private.txt", "text/plain", 3, io.BytesIO(b"abc")),))
    backend = Backend([PffMessage(value, "generation-A", 5)])
    adapter = PffReaderAdapter(backend, adapter_version="synthetic-1")
    with adapter.open_read_only("private.pst", None) as reader:
        assert repr(reader) == "<SourceReaderHandle>"
        seen = list(adapter.enumerate(reader, value.folder, None, {"overlap_messages": 50}))
        assert adapter.stable_origin_identity(seen[0]) == value.provider_identity
        assert seen[0].chronology == value.chronology
        assert seen[0].direction == value.direction
        assert seen[0].attachments[0].content_stream_ref.read(2) == b"ab"
        assert seen[0].attachments[0].content_stream_ref.read() == b"c"
        assert seen[0].attachments[0].content_stream_ref.read() == b""
    assert backend.calls[-1] == "close"
    with pytest.raises(SomaError):
        seen[0].attachments[0].content_stream_ref.read()


@pytest.mark.parametrize("operation", ["probe", "open", "messages", "close"])
def test_native_exception_content_and_parser_objects_never_cross_boundary(operation):
    backend = Backend([object()])
    def fail(*args):
        raise RuntimeError("PRIVATE_BODY C:/private/mail.pst SECRET_TOKEN")
    setattr(backend, operation, fail)
    adapter = PffReaderAdapter(backend, adapter_version="synthetic-1")
    if operation == "probe":
        assert adapter.probe_read_only("private.pst", None).health == "CORRUPT"
    else:
        with pytest.raises(SomaError) as result:
            with adapter.open_read_only("private.pst", None) as reader:
                if operation != "close":
                    list(adapter.enumerate(reader, message().folder, None, {}))
        assert "PRIVATE" not in str(result.value) and "SECRET" not in str(result.value)
        assert result.value.__context__ is None


def test_checkpoint_total_order_is_pure_and_generation_and_folder_changes_fail_closed():
    adapter = PffReaderAdapter()
    a = adapter.checkpoint("inbox", "A", 1, 1_000)
    b = adapter.checkpoint("inbox", "A", 2, 1_000)
    assert adapter.compare_checkpoints(a, b) == "BEFORE"
    assert adapter.compare_checkpoints(b, a) == "AFTER"
    assert adapter.compare_checkpoints(a, a) == "EQUAL"
    for other in (adapter.checkpoint("sent", "A", 1), adapter.checkpoint("inbox", "B", 1),
                  ProviderCheckpoint("POSITION", "AA", None)):
        assert adapter.compare_checkpoints(a, other) == "INDETERMINATE"


def test_truncated_or_overlong_native_attachment_stream_fails_without_leaking_exception():
    for stream in (io.BytesIO(b""), type("BadStream", (), {"read": lambda self, limit: b"x" * (limit + 1)})()):
        value = replace(message(), attachments=(TransientAttachment(0, None, None, 3, stream),))
        adapter = PffReaderAdapter(Backend([PffMessage(value, "A", 1)]), adapter_version="synthetic-1")
        with adapter.open_read_only("private.pst", None) as reader:
            item = next(adapter.enumerate(reader, value.folder, None, {}))
            with pytest.raises(SomaError):
                item.attachments[0].content_stream_ref.read()


def test_native_attachment_declared_size_cannot_silently_truncate_captured_content():
    value = replace(message(), attachments=(TransientAttachment(0, None, None, 3, io.BytesIO(b"abcd")),))
    adapter = PffReaderAdapter(Backend([PffMessage(value, "A", 1)]), adapter_version="synthetic-1")
    with adapter.open_read_only("private.pst", None) as reader:
        item = next(adapter.enumerate(reader, value.folder, None, {}))
        assert item.attachments[0].content_stream_ref.read() == b"abc"
        with pytest.raises(SomaError):
            item.attachments[0].content_stream_ref.read(1)


def test_cleanup_failure_preserves_sanitized_inspection_error_without_exception_context():
    backend = Backend([])
    def fail(*args):
        raise RuntimeError("PRIVATE_BODY C:/private/mail.pst SECRET_TOKEN")
    backend.messages = backend.close = fail
    adapter = PffReaderAdapter(backend, adapter_version="synthetic-1")
    with pytest.raises(SomaError) as result:
        with adapter.open_read_only("private.pst", None) as reader:
            list(adapter.enumerate(reader, message().folder, None, {}))
    assert str(result.value) == "COMM_SOURCE_UNSUPPORTED: Communication source inspection failed"
    assert result.value.__context__ is None and result.value.__cause__ is None
    assert reader._active is False and reader._native is None


def test_native_stream_read_lookup_failure_is_sanitized_at_attachment_boundary():
    class Stream:
        available = True

        @property
        def read(self):
            if not self.available:
                raise RuntimeError("PRIVATE_BODY SECRET_TOKEN")
            return lambda size: b"abc"[:size]

    stream = Stream()
    value = replace(message(), attachments=(TransientAttachment(0, None, None, 3, stream),))
    adapter = PffReaderAdapter(Backend([PffMessage(value, "A", 1)]), adapter_version="synthetic-1")
    with adapter.open_read_only("private.pst", None) as reader:
        item = next(adapter.enumerate(reader, value.folder, None, {}))
        stream.available = False
        with pytest.raises(SomaError) as result:
            item.attachments[0].content_stream_ref.read()
        assert result.value.__context__ is None and result.value.__cause__ is None
        assert "PRIVATE" not in str(result.value)
