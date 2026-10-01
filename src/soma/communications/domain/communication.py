from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from email.headerregistry import Address
from email.errors import NonASCIILocalPartDefect

import unicodedata2

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes_bounded, loads_canonical_json
from soma.reference.domain.matching import trim_match_whitespace

from soma.communications.contracts.common import Chronology, DIRECTIONS, closed, fingerprint, integer, text
from soma.communications.contracts.message import PARTICIPANT_ROLES, TransientMessage


def normalized_source_text(value: str | None, *, trim: bool = False, body: bool = False) -> str | None:
    if value is None:
        return None
    cleaned = value.rstrip("\x00").replace("\r\n", "\n").replace("\r", "\n")
    # Body canonicalization preserves text bytes apart from line endings/NULs.
    normalized = cleaned if body else unicodedata2.normalize("NFKC", cleaned)
    return trim_match_whitespace(normalized) if trim else normalized


def normalized_address(value: str | None) -> str | None:
    normalized = normalized_source_text(value, trim=True)
    if not normalized:
        return None
    try:
        parsed = Address(addr_spec=normalized)
    except NonASCIILocalPartDefect:
        # Python's RFC address parser diagnoses international local-parts even
        # when their syntax is sound. Validate syntax with placeholders, then
        # keep the original normalized local-part bytes in identity evidence.
        syntax = "".join("x" if ord(char) > 127 and unicodedata2.category(char)[0] not in "CZ" else char for char in normalized)
        try:
            parsed = Address(addr_spec=syntax)
        except ValueError:
            return None
    except ValueError:
        return None
    if not parsed.username or not parsed.domain or "@" not in normalized:
        return None
    local, domain = normalized.rsplit("@", 1)
    # Domain case is ASCII only; local-part case and bytes remain identity facts.
    domain = "".join(chr(ord(char) + 32) if "A" <= char <= "Z" else char for char in domain)
    return local + "@" + domain


@dataclass(frozen=True, slots=True)
class AttachmentIdentity:
    ordinal: int
    size_bytes: int
    content_sha256: str

    def __post_init__(self) -> None:
        integer(self.ordinal)
        integer(self.size_bytes, maximum=104857600)
        fingerprint(self.content_sha256)


@dataclass(frozen=True, slots=True)
class CanonicalMessageIdentity:
    provider_kind: str | None
    provider_digest: str | None
    provider_bytes: bytes | None = field(repr=False)
    fallback_digest: str
    fallback_canonical_json: str = field(repr=False)
    fallback_version: int = 1


def require_fallback_evidence(source_scope_id: str, version: int, canonical_json: str) -> None:
    """Validate the complete supported object before reviewed identity transfer.

    Equality of two arbitrary JSON blobs cannot establish canonical evidence.
    Digests deliberately do not replace exact-object validation/comparison.
    """
    require_uuid4(source_scope_id)
    if type(version) is not int or version != 1:
        raise ValidationError("Fallback evidence version is unsupported")
    value = loads_canonical_json(canonical_json, max_bytes=1048576, max_depth=5, max_collection_items=20000)
    closed(value, {"version", "source_scope_id", "internet_message_id", "chronology", "direction", "from", "recipients", "subject", "body_sha256", "attachments"})
    if type(value["version"]) is not int or value["version"] != 1 or value["source_scope_id"] != source_scope_id:
        raise ValidationError("Fallback evidence does not belong to this supported source")
    Chronology.from_value(value["chronology"])
    if not isinstance(value["direction"], str) or value["direction"] not in DIRECTIONS:
        raise ValidationError("Fallback direction evidence is invalid")
    for key in ("subject", "internet_message_id"):
        if value[key] is not None:
            text(value[key], maximum=2048 if key == "subject" else None)
    if value["body_sha256"] is not None:
        fingerprint(value["body_sha256"])
    ordinals = set()
    participant_count = 0
    for key in ("from", "recipients"):
        participants = value[key]
        if not isinstance(participants, list) or len(participants) > 2000:
            raise ValidationError("Fallback participants exceed the evidence bound")
        prior = None
        for item in participants:
            closed(item, {"role", "ordinal", "address", "display_name"})
            if (not isinstance(item["role"], str) or item["role"] not in PARTICIPANT_ROLES
                    or (item["role"] in {"FROM", "SENDER"}) != (key == "from")):
                raise ValidationError("Fallback participant role is invalid")
            integer(item["ordinal"])
            order = (item["ordinal"], item["role"])
            if order in ordinals or (prior is not None and order <= prior):
                raise ValidationError("Fallback participant ordering is invalid")
            prior = order
            ordinals.add(order)
            for field_name in ("address", "display_name"):
                if item[field_name] is not None:
                    text(item[field_name])
        participant_count += len(participants)
    if participant_count > 2000:
        raise ValidationError("Fallback participant total exceeds the evidence bound")
    attachments = value["attachments"]
    if not isinstance(attachments, list) or len(attachments) > 500:
        raise ValidationError("Fallback attachments exceed the evidence bound")
    prior = -1
    total_bytes = 0
    for item in attachments:
        closed(item, {"ordinal", "filename", "size_bytes", "content_sha256"})
        integer(item["ordinal"])
        if item["ordinal"] <= prior:
            raise ValidationError("Fallback attachment ordering is invalid")
        prior = item["ordinal"]
        total_bytes += integer(item["size_bytes"], maximum=104857600)
        fingerprint(item["content_sha256"])
        if item["filename"] is not None:
            text(item["filename"])
    if total_bytes > 524288000:
        raise ValidationError("Fallback attachment total exceeds the evidence bound")


def canonical_message_identity(source_scope_id: str, message: TransientMessage,
                               attachment_identities: tuple[AttachmentIdentity, ...]) -> CanonicalMessageIdentity:
    require_uuid4(source_scope_id)
    if not isinstance(message, TransientMessage):
        raise ValidationError("Canonical identity requires a typed transient message")
    if not isinstance(attachment_identities, tuple) or any(not isinstance(x, AttachmentIdentity) for x in attachment_identities):
        raise ValidationError("Canonical identity requires captured attachment evidence")
    evidence = {item.ordinal: item for item in attachment_identities}
    if len(evidence) != len(attachment_identities) or set(evidence) != {item.ordinal for item in message.attachments}:
        raise ValidationError("Canonical identity attachment evidence is incomplete")
    participants = [{"role": item.role, "ordinal": item.ordinal, "address": normalized_address(item.address),
                     "display_name": normalized_source_text(item.display_name, trim=True)}
                    for item in sorted(message.participants, key=lambda x: (x.ordinal, x.role))]
    attachments = []
    for item in sorted(message.attachments, key=lambda x: x.ordinal):
        captured = evidence[item.ordinal]
        if captured.size_bytes != item.size_bytes:
            raise ValidationError("Canonical identity attachment size does not match captured content")
        attachments.append({"ordinal": item.ordinal, "filename": normalized_source_text(item.filename, trim=True),
                            "size_bytes": item.size_bytes, "content_sha256": captured.content_sha256})
    body = normalized_source_text(message.body, body=True)
    canonical = canonical_json_bytes_bounded({
        "version": 1, "source_scope_id": source_scope_id,
        "internet_message_id": normalized_source_text(message.internet_message_id, trim=True),
        "chronology": message.chronology.to_response(), "direction": message.direction,
        "from": [item for item in participants if item["role"] in {"FROM", "SENDER"}],
        "recipients": [item for item in participants if item["role"] not in {"FROM", "SENDER"}],
        "subject": normalized_source_text(message.subject, trim=True),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest() if body is not None else None,
        "attachments": attachments,
    }, max_bytes=1048576, max_depth=5, max_collection_items=20000)
    provider = message.provider_identity
    return CanonicalMessageIdentity(
        None if provider is None else provider.kind,
        None if provider is None else hashlib.sha256(provider.kind.encode("ascii") + b"\x00" + provider.raw_bytes).hexdigest(),
        None if provider is None else provider.raw_bytes, hashlib.sha256(canonical).hexdigest(), canonical.decode("utf-8"),
    )
