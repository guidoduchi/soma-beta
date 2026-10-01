from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import sqlite3
import struct

import msgforge
import olefile
import pytest

from soma.communications.adapters.msg_writer import MsgDraftWriter, verify_msg_bytes
from soma.communications.contracts.drafts import MsgDraftRecipient, MsgDraftSnapshot, draft_recipients
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4


def snapshot(body_format="TEXT"):
    recipients = draft_recipients([
        {"role": "CC", "address": "CaseSensitive@EXAMPLE.com", "display_name": "CC name"},
        {"role": "TO", "address": "quoted@example.com", "display_name": None},
        {"role": "BCC", "address": "bcc@example.com", "display_name": "BCC name"},
        {"role": "TO", "address": "second@example.com", "display_name": "Second TO"},
    ])
    return MsgDraftSnapshot("Authored subject 界 😀", body_format,
        "<p>Exact HTML 界 😀\r\nsecond line</p>" if body_format == "HTML" else "Exact body 界 😀\r\nsecond line", recipients)


@pytest.mark.parametrize("body_format", ["TEXT", "HTML"])
def test_pinned_writer_is_deterministic_and_independent_reader_verifies_unsent_exact_authored_content(body_format):
    original = snapshot(body_format)
    first, second = MsgDraftWriter().build(original), MsgDraftWriter().build(original)
    assert first == second
    assert first.sha256 == hashlib.sha256(first.content).hexdigest()
    assert first.size_bytes == len(first.content)
    assert "Authored" not in repr(first)
    assert [(item.role, item.address) for item in original.role_ordered_recipients] == [
        ("TO", "quoted@example.com"), ("TO", "second@example.com"), ("CC", "CaseSensitive@EXAMPLE.com"), ("BCC", "bcc@example.com")]
    verify_msg_bytes(first.content, original)
    for changed in (replace(original, subject="Changed"), replace(original, body="Changed"),
                    replace(original, recipients=(MsgDraftRecipient("TO", "other@example.com", None),))):
        with pytest.raises(SomaError) as raised:
            verify_msg_bytes(first.content, changed)
        assert raised.value.code == "COMM_MSG_BUILD_FAILED"
        assert raised.value.__context__ is None


def test_independent_reader_rejects_sent_semantics_and_malformed_cfb_without_raw_exception_leakage():
    original = snapshot()
    roles = {role.lower(): [(item.address, item.display_name) for item in original.recipients if item.role == role] for role in ("TO", "CC", "BCC")}
    sent = msgforge.Message(subject=original.subject, text_body=original.body, sent=True, **roles).as_bytes()
    valid = MsgDraftWriter().build(original).content
    modified = io.BytesIO(valid)
    with olefile.OleFileIO(modified, write_mode=True) as ole:
        properties = bytearray(ole.openstream("__properties_version1.0").read())
        offset = next(offset for offset in range(32, len(properties), 16) if struct.unpack_from("<I", properties, offset)[0] == 0x0E070003)
        struct.pack_into("<Q", properties, offset + 8, 1)
        ole.write_stream("__properties_version1.0", bytes(properties))
    for content in (sent, modified.getvalue(), b"SecretMalformedArtifact", valid[:512]):
        with pytest.raises(SomaError) as raised:
            verify_msg_bytes(content, original)
        assert raised.value.code == "COMM_MSG_BUILD_FAILED"
        assert "Secret" not in str(raised.value)
        assert raised.value.__context__ is None


def test_writer_error_is_sanitized_and_has_no_exception_context(monkeypatch):
    def fail(self):
        raise RuntimeError("SecretBody SecretAddress@example.com C:/SecretPath")
    monkeypatch.setattr(msgforge.Message, "as_bytes", fail)
    with pytest.raises(SomaError) as raised:
        MsgDraftWriter().build(snapshot())
    assert raised.value.code == "COMM_MSG_BUILD_FAILED"
    assert "Secret" not in str(raised.value)
    assert raised.value.__context__ is None


def test_approved_recipient_bounds_closed_fields_syntax_and_exact_address_bytes():
    recipient = {"role": "TO", "address": '"Case Sensitive"@EXAMPLE.com', "display_name": None}
    assert draft_recipients([recipient])[0].address == recipient["address"]
    assert len(draft_recipients([recipient] * 2000)) == 2000
    for value in ([], [recipient] * 2001, [{**recipient, "extra": "field"}], [{**recipient, "role": "FROM"}],
                  [{**recipient, "address": "invalid mailbox"}], [{**recipient, "address": "a\n@example.com"}],
                  [{**recipient, "address": "a" * 321}], [{**recipient, "display_name": "x" * 513}]):
        with pytest.raises(ValidationError):
            draft_recipients(value)


def test_large_unicode_draft_verifies_cfb_difat_and_preserves_exact_body():
    original = replace(snapshot(), subject="", body="𐍈" * 2_000_000)
    artifact = MsgDraftWriter().build(original)
    assert artifact.size_bytes > 8_000_000
    verify_msg_bytes(artifact.content, original)


def test_full_approved_recipient_bound_round_trips_all_roles_and_duplicate_addresses():
    recipients = tuple(MsgDraftRecipient(("TO", "CC", "BCC")[index % 3], "same@example.com", f"Recipient {index}") for index in range(2000))
    original = MsgDraftSnapshot("Bounded recipients", "TEXT", "", recipients)
    artifact = MsgDraftWriter().build(original)
    verify_msg_bytes(artifact.content, original)


def test_terminal_summary_schema_preserves_chronology_source_and_rejects_unknown_inconsistency(communication_database):
    path, _ = communication_database
    base = (new_uuid4(), "SERVICE_REQUEST", new_uuid4(), new_uuid4(), 0, 0, 0, 0, None, "UNKNOWN", "UNKNOWN", 100, "a" * 64, "UNKNOWN")
    with sqlite3.connect(path) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(communication_terminal_summaries)")]
        assert "last_interaction_source_kind" in columns and "summary_revision" in columns
        # Explicit column names keep this chronology check independent of the
        # accepted per-target freeze sequence added in the same candidate.
        insert = "INSERT INTO communication_terminal_summaries(" + ",".join(columns[:-1]) + ",summary_revision) VALUES(" + ",".join("?" for _ in base) + ",?)"
        connection.execute(insert, (*base, 1))
        for known, instant, kind in ((0, None, "RECEIVED_TIME"), (1, 100, "UNKNOWN"), (1, None, "SENT_TIME")):
            invalid = (*base[:7], known, instant, *base[9:-1], kind)
            invalid = (new_uuid4(), *invalid[1:3], new_uuid4(), *invalid[4:])
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(insert, (*invalid, 2))
        known = (new_uuid4(), *base[1:3], new_uuid4(), *base[4:7], 1, 100, *base[9:-1], "RECEIVED_TIME")
        connection.execute(insert, (*known, 2))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE communication_terminal_summaries SET last_interaction_source_kind='SENT_TIME'")
