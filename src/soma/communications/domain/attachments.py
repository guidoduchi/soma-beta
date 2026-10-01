"""Bounded, immutable attachment bytes captured before an authoritative UoW."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from soma.foundation.errors import ValidationError

from soma.communications.contracts.message import TransientAttachment, TransientMessage
from soma.communications.domain.communication import AttachmentIdentity

CHUNK_BYTES = 1048576


@dataclass(frozen=True, slots=True)
class CapturedAttachment:
    identity: AttachmentIdentity
    chunks: tuple[bytes, ...] = field(repr=False)
    chunk_digests: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self):
        if not isinstance(self.identity, AttachmentIdentity) or not isinstance(self.chunks, tuple):
            raise ValidationError("Captured attachment evidence requires immutable typed bytes")
        digest, size, chunk_digests = hashlib.sha256(), 0, []
        for index, chunk in enumerate(self.chunks):
            if not isinstance(chunk, bytes) or not chunk or len(chunk) > CHUNK_BYTES:
                raise ValidationError("Captured attachment chunk is invalid")
            if index < len(self.chunks) - 1 and len(chunk) != CHUNK_BYTES:
                raise ValidationError("Captured attachment chunk ordering is invalid")
            digest.update(chunk)
            chunk_digests.append(hashlib.sha256(chunk).hexdigest())
            size += len(chunk)
            if size > self.identity.size_bytes:
                raise ValidationError("Captured attachment exceeds its declared size")
        if size != self.identity.size_bytes or digest.hexdigest() != self.identity.content_sha256:
            raise ValidationError("Captured attachment does not match its identity evidence")
        object.__setattr__(self, "chunk_digests", tuple(chunk_digests))


def capture_attachment(attachment: TransientAttachment) -> CapturedAttachment:
    if not isinstance(attachment, TransientAttachment):
        raise ValidationError("Attachment capture requires a typed transient attachment")
    digest, chunks, remaining = hashlib.sha256(), [], attachment.size_bytes
    while remaining:
        # Streams may return short reads. Accumulate exactly one chunk without
        # assuming that one read exhausts either the chunk or the attachment.
        expected = min(CHUNK_BYTES, remaining)
        buffer, obtained = bytearray(expected), 0
        while obtained < expected:
            value = attachment.content_stream_ref.read(expected - obtained)
            if not isinstance(value, bytes) or not value or len(value) > expected - obtained:
                raise ValidationError("Attachment stream does not match its declared size")
            buffer[obtained:obtained + len(value)] = value
            obtained += len(value)
        chunk = bytes(buffer)
        digest.update(chunk)
        chunks.append(chunk)
        remaining -= len(chunk)
    tail = attachment.content_stream_ref.read(1)
    if not isinstance(tail, bytes) or tail:
        raise ValidationError("Attachment stream exceeds its declared size")
    return CapturedAttachment(AttachmentIdentity(attachment.ordinal, attachment.size_bytes, digest.hexdigest()), tuple(chunks))


def capture_attachments(message: TransientMessage) -> tuple[CapturedAttachment, ...]:
    if not isinstance(message, TransientMessage):
        raise ValidationError("Attachment capture requires a typed transient message")
    return tuple(capture_attachment(item) for item in message.attachments)
