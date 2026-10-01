from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import BinaryIO

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

from .common import Chronology, closed, integer, text
from .source import ProviderCheckpoint, SourceFolder

PARTICIPANT_ROLES = frozenset({"FROM", "SENDER", "TO", "CC", "BCC", "REPLY_TO", "OTHER"})


def source_text(value: str | None, *, maximum: int | None = None) -> None:
    if value is not None:
        if not isinstance(value, str):
            raise ValidationError("Communication source text is invalid")
        # The identity algorithm explicitly removes provider terminal NULs.
        text(value.rstrip("\x00"), maximum=maximum)


@dataclass(frozen=True, slots=True)
class ProviderMessageIdentity:
    kind: str
    raw_bytes: bytes = field(repr=False)
    normalization_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in {"MAPI_RECORD_KEY", "PROVIDER_STABLE_OTHER"}:
            raise ValidationError("Provider message identity kind is invalid")
        if not isinstance(self.raw_bytes, bytes) or not self.raw_bytes:
            raise ValidationError("Provider message identity requires nonempty binary evidence")
        if type(self.normalization_version) is not int or self.normalization_version != 1:
            raise ValidationError("Provider identity normalization version is unsupported")

    @classmethod
    def from_value(cls, value) -> ProviderMessageIdentity:
        item = closed(value, {"kind", "value_bytes_b64", "normalization_version"})
        try:
            encoded = text(item["value_bytes_b64"], minimum=1)
            raw = base64.b64decode(encoded, validate=True)
            if base64.b64encode(raw).decode("ascii") != encoded:
                raise ValueError("Noncanonical base64")
        except (ValueError, binascii.Error) as exc:
            raise ValidationError("Provider message identity encoding is invalid") from exc
        return cls(item["kind"], raw, item["normalization_version"])


@dataclass(frozen=True, slots=True)
class CommunicationParticipant:
    role: str
    ordinal: int
    address: str | None = field(repr=False)
    display_name: str | None = field(repr=False)
    contact_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or self.role not in PARTICIPANT_ROLES:
            raise ValidationError("Communication participant role is invalid")
        integer(self.ordinal)
        source_text(self.address)
        source_text(self.display_name)
        if self.contact_id is not None:
            require_uuid4(self.contact_id)


@dataclass(frozen=True, slots=True)
class TransientAttachment:
    ordinal: int
    filename: str | None = field(repr=False)
    mime_type: str | None
    size_bytes: int
    content_stream_ref: BinaryIO = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        integer(self.ordinal)
        integer(self.size_bytes, maximum=104857600)
        source_text(self.filename)
        source_text(self.mime_type)
        if not callable(getattr(self.content_stream_ref, "read", None)):
            raise ValidationError("Attachment content requires a process-local stream")


@dataclass(frozen=True, slots=True)
class TransientMessage:
    folder: SourceFolder
    provider_identity: ProviderMessageIdentity | None
    chronology: Chronology
    subject: str | None = field(repr=False)
    body_kind: str
    body: str | None = field(repr=False)
    participants: tuple[CommunicationParticipant, ...] = field(repr=False)
    attachments: tuple[TransientAttachment, ...] = field(repr=False)
    provider_position: ProviderCheckpoint
    internet_message_id: str | None = field(repr=False)
    direction_conflict: bool
    independently_distinct_source_item: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.folder, SourceFolder) or not isinstance(self.chronology, Chronology) or not isinstance(self.provider_position, ProviderCheckpoint):
            raise ValidationError("Transient message requires typed source and chronology evidence")
        if self.provider_identity is not None and not isinstance(self.provider_identity, ProviderMessageIdentity):
            raise ValidationError("Transient message provider identity is invalid")
        if not isinstance(self.body_kind, str) or self.body_kind not in {"TEXT", "HTML", "RTF_DERIVED_TEXT", "NONE"}:
            raise ValidationError("Transient message body kind is invalid")
        if self.body_kind == "NONE" and self.body is not None:
            raise ValidationError("Absent message body cannot contain text")
        source_text(self.subject, maximum=2048)
        source_text(self.body, maximum=5000000)
        source_text(self.internet_message_id)
        if type(self.direction_conflict) is not bool:
            raise ValidationError("Transient message direction conflict requires an exact boolean")
        if type(self.independently_distinct_source_item) is not bool:
            raise ValidationError("Transient distinct-source evidence requires an exact boolean")
        if (not isinstance(self.participants, tuple) or len(self.participants) > 2000
                or any(not isinstance(item, CommunicationParticipant) for item in self.participants)):
            raise ValidationError("Transient message participants exceed their typed bound")
        if len({(item.role, item.ordinal) for item in self.participants}) != len(self.participants):
            raise ValidationError("Transient message participant ordinals are duplicated")
        if (not isinstance(self.attachments, tuple) or len(self.attachments) > 500
                or any(not isinstance(item, TransientAttachment) for item in self.attachments)):
            raise ValidationError("Transient message attachments exceed their typed bound")
        if len({item.ordinal for item in self.attachments}) != len(self.attachments):
            raise ValidationError("Transient message attachment ordinals are duplicated")
        if sum(item.size_bytes for item in self.attachments) > 524288000:
            raise ValidationError("Transient message total attachment size exceeds its bound")

    @property
    def direction(self) -> str:
        if self.direction_conflict:
            return "UNKNOWN"
        return {"INBOX": "RECEIVED", "SENT": "SENT", "OTHER": "UNKNOWN"}[self.folder.role]
