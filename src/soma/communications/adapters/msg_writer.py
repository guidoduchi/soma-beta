from __future__ import annotations

import hashlib
import io
import struct
from dataclasses import dataclass, field
from importlib.metadata import version

import msgforge
import olefile

from soma.communications.contracts.drafts import MsgDraftSnapshot
from soma.foundation.errors import SomaError


def _failure():
    return SomaError("COMM_MSG_BUILD_FAILED", "MSG draft construction or independent verification failed")


def _stream(ole, path, artifact_length):
    if ole.get_size(path) > artifact_length:
        raise ValueError("Invalid MSG stream length")
    with ole.openstream(path) as stream:
        return stream.read(artifact_length + 1)


def _properties(ole, storage, header_size, artifact_length):
    content = _stream(ole, [*storage, "__properties_version1.0"], artifact_length)
    if len(content) < header_size or (len(content) - header_size) % 16:
        raise ValueError("Invalid MSG property stream")
    result = {}
    for offset in range(header_size, len(content), 16):
        tag, flags, value = struct.unpack_from("<IIQ", content, offset)
        if tag in result:
            raise ValueError("Duplicate MSG property")
        result[tag] = value
        if tag & 0xFFFF in {0x001F, 0x0102}:
            path = [*storage, f"__substg1.0_{tag:08X}"]
            size = ole.get_size(path)
            if size != value - (2 if tag & 0xFFFF == 0x001F else 0):
                raise ValueError("MSG property length mismatch")
            _stream(ole, path, artifact_length)
    return content[:header_size], result


def _unicode(ole, storage, tag, properties, artifact_length):
    if tag not in properties:
        return ""
    return _stream(ole, [*storage, f"__substg1.0_{tag:08X}"], artifact_length).decode("utf-16-le", errors="strict")


def verify_msg_bytes(content: bytes, expected: MsgDraftSnapshot):
    """Independent CFB/OXMSG reader; does not call msgforge parsing internals.

    Checks message/recipient property streams, lengths, authored content and
    unsent semantics. Supported Outlook compatibility remains a release gate.
    """
    if not isinstance(content, bytes) or not isinstance(expected, MsgDraftSnapshot):
        raise _failure()
    try:
        with olefile.OleFileIO(io.BytesIO(content), raise_defects=olefile.DEFECT_INCORRECT) as ole:
            header, root = _properties(ole, [], 32, len(content))
            recipients = expected.role_ordered_recipients
            if struct.unpack_from("<II", header, 16) != (len(recipients), 0):
                raise ValueError("MSG recipient or attachment count mismatch")
            if (_unicode(ole, [], 0x001A001F, root, len(content)) != "IPM.Note"
                    or root.get(0x0E070003) != 0x08
                    or any(tag in root for tag in (0x00390040, 0x0E060040))
                    or root.get(0x0023000B, 0) or root.get(0x0029000B, 0)):
                raise ValueError("MSG is not an unsent note")
            if _unicode(ole, [], 0x0037001F, root, len(content)) != expected.subject:
                raise ValueError("MSG subject differs from authored snapshot")
            if expected.body_format == "TEXT":
                actual = _unicode(ole, [], 0x1000001F, root, len(content))
            else:
                actual = "" if 0x10130102 not in root else _stream(ole, ["__substg1.0_10130102"], len(content)).decode("utf-8", errors="strict")
            if actual != expected.body:
                raise ValueError("MSG body differs from authored snapshot")
            storages = ole.listdir(streams=False, storages=True)
            expected_storages = {("__nameid_version1.0",)} | {(f"__recip_version1.0_#{index:08X}",) for index in range(len(recipients))}
            if {tuple(path) for path in storages} != expected_storages:
                raise ValueError("Unexpected MSG storage")
            for name in ("00020102", "00030102", "00040102"):
                _stream(ole, ["__nameid_version1.0", "__substg1.0_" + name], len(content))
            for index, recipient in enumerate(recipients):
                storage = [f"__recip_version1.0_#{index:08X}"]
                _, properties = _properties(ole, storage, 8, len(content))
                if (properties.get(0x0C150003) != {"TO": 1, "CC": 2, "BCC": 3}[recipient.role]
                        or properties.get(0x30000003) != index
                        or _unicode(ole, storage, 0x3002001F, properties, len(content)) != "SMTP"
                        or _unicode(ole, storage, 0x3003001F, properties, len(content)) != recipient.address
                        or _unicode(ole, storage, 0x39FE001F, properties, len(content)) != recipient.address
                        or _unicode(ole, storage, 0x3001001F, properties, len(content)) != (recipient.display_name or recipient.address)):
                    raise ValueError("MSG recipient differs from authored snapshot")
            if ole.parsing_issues:
                raise ValueError("CFB structural defects")
    except Exception:
        pass
    else:
        return
    # Raise after leaving the handler so __context__ carries no parser exception
    # or authored bytes, including when a diagnostic consumer inspects it.
    raise _failure() from None


@dataclass(frozen=True, slots=True)
class VerifiedMsgArtifact:
    content: bytes = field(repr=False)
    sha256: str
    size_bytes: int


class MsgDraftWriter:
    def build(self, snapshot: MsgDraftSnapshot):
        if not isinstance(snapshot, MsgDraftSnapshot):
            raise _failure()
        try:
            if any(version(package) != pinned for package, pinned in (
                    ("msgforge", "1.0.0"), ("compressed-rtf", "1.0.7"), ("olefile", "0.47"))):
                raise ValueError("Unsupported MSG writer version")
            roles = {role.lower(): [(item.address, item.display_name) for item in snapshot.recipients if item.role == role]
                     for role in ("TO", "CC", "BCC")}
            note = msgforge.Message(subject=snapshot.subject, sent=False, **roles,
                **({"text_body": snapshot.body} if snapshot.body_format == "TEXT" else {"html_body": snapshot.body}))
            content = note.as_bytes()
        except Exception:
            pass
        else:
            verify_msg_bytes(content, snapshot)
            return VerifiedMsgArtifact(content, hashlib.sha256(content).hexdigest(), len(content))
        raise _failure() from None
