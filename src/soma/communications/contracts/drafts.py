from __future__ import annotations

from dataclasses import dataclass, field
from email.errors import NonASCIILocalPartDefect
from email.headerregistry import Address

import unicodedata2

from soma.foundation.errors import ValidationError
from soma.communications.contracts.common import closed, text


def _valid_mailbox(value):
    try:
        parsed = Address(addr_spec=value)
    except NonASCIILocalPartDefect:
        # Validate international local-part syntax without normalizing the
        # exact address which will be stored in the authored draft snapshot.
        syntax = "".join("x" if ord(char) > 127 and unicodedata2.category(char)[0] not in "CZ" else char for char in value)
        try:
            parsed = Address(addr_spec=syntax)
        except ValueError:
            return False
    except ValueError:
        return False
    return bool(parsed.username and parsed.domain)


@dataclass(frozen=True, slots=True)
class MsgDraftRecipient:
    role: str
    address: str = field(repr=False)
    display_name: str | None = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.role, str) or self.role not in {"TO", "CC", "BCC"}:
            raise ValidationError("MSG draft recipient role is invalid")
        text(self.address, minimum=1, maximum=320)
        if not _valid_mailbox(self.address):
            raise ValidationError("MSG draft recipient mailbox syntax is invalid")
        if self.display_name is not None:
            text(self.display_name, maximum=512)

    @classmethod
    def from_value(cls, value):
        return cls(**closed(value, {"role", "address", "display_name"}))

    def to_value(self):
        return {"role": self.role, "address": self.address, "display_name": self.display_name}


def draft_recipients(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 2000:
        raise ValidationError("MSG draft recipient count is outside its contract")
    return tuple(MsgDraftRecipient.from_value(item) for item in value)


@dataclass(frozen=True, slots=True)
class MsgDraftSnapshot:
    subject: str = field(repr=False)
    body_format: str
    body: str = field(repr=False)
    recipients: tuple[MsgDraftRecipient, ...] = field(repr=False)

    def __post_init__(self):
        text(self.subject, maximum=2048)
        text(self.body, maximum=5000000)
        if not isinstance(self.body_format, str) or self.body_format not in {"TEXT", "HTML"}:
            raise ValidationError("MSG draft body format is invalid")
        if (not isinstance(self.recipients, tuple) or not 1 <= len(self.recipients) <= 2000
                or any(not isinstance(item, MsgDraftRecipient) for item in self.recipients)):
            raise ValidationError("MSG draft requires a bounded typed recipient snapshot")

    @property
    def role_ordered_recipients(self):
        return tuple(item for role in ("TO", "CC", "BCC") for item in self.recipients if item.role == role)
