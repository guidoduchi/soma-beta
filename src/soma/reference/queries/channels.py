from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.reference.domain.validation import validate_email_channel

ChannelState = Literal["USABLE", "MISSING", "ARCHIVED", "INVALID", "MULTIPLE_USABLE"]


@dataclass(frozen=True, slots=True)
class ChannelUseValidation:
    state: ChannelState
    contact_id: str
    contact_channel_id: str | None
    channel_kind: str
    value_text: str | None
    usable_count: int
    candidate_channel_ids: tuple[str, ...]
    continuation_after_id: str | None
    reason_code: str | None


class ContactChannelQueries:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def validate_for_use(
        self,
        *,
        contact_id: str,
        contact_channel_id: str | None = None,
        auto_select: bool = False,
        purpose: str = "msg_recipient",
        after_channel_id: str | None = None,
        limit: int = 50,
    ) -> ChannelUseValidation:
        if purpose != "msg_recipient":
            raise SomaError("VALIDATION_FAILED", "unsupported Contact channel purpose")
        if auto_select == (contact_channel_id is not None):
            raise SomaError(
                "VALIDATION_FAILED",
                "choose either AUTO_SELECT or one specific Contact channel",
            )
        if type(limit) is not int or limit < 1 or limit > 200:
            raise SomaError("FIELD_BOUND_EXCEEDED", "channel page limit must be in 1..200")

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            contact = connection.execute(
                "SELECT lifecycle_state FROM contacts WHERE contact_id=?", (contact_id,)
            ).fetchone()
            if contact is None:
                raise SomaError("NOT_FOUND", "Contact does not exist")
            if str(contact[0]) != "active":
                return ChannelUseValidation(
                    "ARCHIVED", contact_id, contact_channel_id, "email", None, 0, (), None, "REFERENCE_ARCHIVED"
                )

            if contact_channel_id is not None:
                row = connection.execute(
                    "SELECT contact_id,channel_kind,value_text,lifecycle_state FROM contact_channels "
                    "WHERE contact_channel_id=?",
                    (contact_channel_id,),
                ).fetchone()
                if row is None or str(row[0]) != contact_id:
                    raise SomaError("CHANNEL_NOT_OWNED", "selected channel does not belong to Contact")
                if str(row[3]) != "active":
                    return ChannelUseValidation(
                        "ARCHIVED",
                        contact_id,
                        contact_channel_id,
                        str(row[1]),
                        None,
                        0,
                        (),
                        None,
                        "CHANNEL_NOT_USABLE",
                    )
                if str(row[1]) != "email":
                    return ChannelUseValidation(
                        "INVALID", contact_id, contact_channel_id, str(row[1]), None, 0, (), None, "CHANNEL_INVALID"
                    )
                try:
                    accepted, _ = validate_email_channel(str(row[2]))
                except ValidationError:
                    return ChannelUseValidation(
                        "INVALID", contact_id, contact_channel_id, "email", None, 0, (), None, "CHANNEL_INVALID"
                    )
                return ChannelUseValidation(
                    "USABLE", contact_id, contact_channel_id, "email", accepted, 1, (contact_channel_id,), None, None
                )

            rows = connection.execute(
                "SELECT contact_channel_id,value_text FROM contact_channels "
                "WHERE contact_id=? AND channel_kind='email' AND lifecycle_state='active' "
                "ORDER BY contact_channel_id",
                (contact_id,),
            ).fetchall()

        usable: list[tuple[str, str]] = []
        for row in rows:
            try:
                accepted, _ = validate_email_channel(str(row[1]))
            except ValidationError:
                continue
            usable.append((str(row[0]), accepted))
        count = len(usable)
        if count == 0:
            return ChannelUseValidation(
                "MISSING", contact_id, None, "email", None, 0, (), None, "CHANNEL_NOT_USABLE"
            )
        if count == 1:
            channel_id, value = usable[0]
            return ChannelUseValidation(
                "USABLE", contact_id, channel_id, "email", value, 1, (channel_id,), None, None
            )

        ordered_ids = [channel_id for channel_id, _ in usable]
        if after_channel_id is not None:
            ordered_ids = [channel_id for channel_id in ordered_ids if channel_id > after_channel_id]
        visible = tuple(ordered_ids[:limit])
        continuation = visible[-1] if len(ordered_ids) > limit and visible else None
        return ChannelUseValidation(
            "MULTIPLE_USABLE",
            contact_id,
            None,
            "email",
            None,
            count,
            visible,
            continuation,
            "CHANNEL_SELECTION_REQUIRED",
        )
