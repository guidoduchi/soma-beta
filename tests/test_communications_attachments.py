import hashlib
from dataclasses import replace
from io import BytesIO

import pytest

from soma.communications.contracts.message import TransientAttachment
from soma.communications.domain.attachments import CHUNK_BYTES, CapturedAttachment, capture_attachment
from soma.communications.domain.communication import AttachmentIdentity
from soma.foundation.errors import ValidationError


class ShortReads(BytesIO):
    def read(self, size=-1):
        return super().read(min(size, 997))


def test_attachment_capture_preserves_exact_immutable_bytes_and_chunk_bound():
    content = b"abc\x00" * (CHUNK_BYTES // 4 + 123)
    stream = ShortReads(content)
    attachment = TransientAttachment(7, "example.bin", "application/octet-stream", len(content), stream)
    captured = capture_attachment(attachment)
    assert captured.identity == AttachmentIdentity(7, len(content), hashlib.sha256(content).hexdigest())
    assert tuple(map(len, captured.chunks)) == (CHUNK_BYTES, 492)
    stream.seek(0)
    stream.write(b"changed")
    assert b"".join(captured.chunks) == content and content[:8].hex() not in repr(captured)


def test_empty_attachment_is_valid_without_fabricated_chunks():
    captured = capture_attachment(TransientAttachment(0, None, None, 0, BytesIO()))
    assert captured.chunks == () and captured.identity.content_sha256 == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("declared,actual", [(0, b"x"), (1, b""), (1, b"xx"), (3, b"xx")])
def test_attachment_capture_rejects_truncated_and_oversized_streams(declared, actual):
    with pytest.raises(ValidationError):
        capture_attachment(TransientAttachment(0, None, None, declared, BytesIO(actual)))


def test_captured_attachment_cannot_accept_mutated_hash_or_invalid_chunk_layout():
    captured = capture_attachment(TransientAttachment(0, None, None, 2, BytesIO(b"ab")))
    with pytest.raises(ValidationError):
        replace(captured, chunks=(b"ac",))
    with pytest.raises(ValidationError):
        replace(captured, chunks=(b"a", b"b"))
    with pytest.raises(ValidationError):
        replace(captured, chunks=(bytearray(b"ab"),))
