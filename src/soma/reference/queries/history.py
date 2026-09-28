from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ._cursor import decode_cursor, encode_cursor

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class CustomerAccountCodeHistoryItem:
    customer_org_identifier_id: str
    value_text: str
    lifecycle_state: str
    created_at_utc: int
    superseded_at_utc: int | None
    created_command_id: str
    superseded_command_id: str | None


@dataclass(frozen=True, slots=True)
class CustomerAccountCodeHistoryPage:
    exact_count: int
    items: tuple[CustomerAccountCodeHistoryItem, ...]
    continuation: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ContactChannelItem:
    contact_channel_id: str
    channel_kind: str
    value_text: str
    lifecycle_state: str
    revision: int
    created_at_utc: int
    updated_at_utc: int


@dataclass(frozen=True, slots=True)
class ContactChannelPage:
    exact_count: int | None
    items: tuple[ContactChannelItem, ...]
    continuation: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ContactAffiliationHistoryItem:
    contact_affiliation_id: str
    customer_org_id: str
    is_current: bool
    opened_at_utc: int
    closed_at_utc: int | None
    opened_command_id: str
    closed_command_id: str | None


@dataclass(frozen=True, slots=True)
class ContactAffiliationHistoryPage:
    exact_count: int
    items: tuple[ContactAffiliationHistoryItem, ...]
    continuation: dict[str, Any] | None


class ReferenceHistoryQueries:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _limit(limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise SomaError("FIELD_BOUND_EXCEEDED", "Reference history page limit must be in 1..200")
        return limit

    @staticmethod
    def _require_customer(connection: Any, customer_org_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM customer_organizations WHERE customer_org_id=?",
            (customer_org_id,),
        ).fetchone() is None:
            raise SomaError("NOT_FOUND", "Customer Organization does not exist")

    @staticmethod
    def _require_contact(connection: Any, contact_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM contacts WHERE contact_id=?",
            (contact_id,),
        ).fetchone() is None:
            raise SomaError("NOT_FOUND", "Contact does not exist")

    @classmethod
    def customer_account_code_history_from_connection(
        cls,
        connection: Any,
        *,
        customer_org_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> CustomerAccountCodeHistoryPage:
        limit = cls._limit(limit)
        cls._require_customer(connection, customer_org_id)
        filter_payload = {
            "schema": "SOMA_ACCOUNT_CODE_HISTORY_FILTER_V1",
            "customer_org_id": customer_org_id,
        }
        key = decode_cursor(
            cursor,
            query_id="GetCustomerAccountCodeHistory",
            sort_registry_id="ACCOUNT_CODE_HISTORY_CREATED_ID_ASC_V1",
            filter_payload=filter_payload,
            key_length=2,
        )
        params: tuple[object, ...] = (customer_org_id,)
        after_sql = ""
        if key is not None:
            created_at_utc, identifier_id = key
            if type(created_at_utc) is not int or not isinstance(identifier_id, str):
                raise ValidationError("Account Code history cursor key is invalid")
            after_sql = (
                " AND (created_at_utc>? OR "
                "(created_at_utc=? AND customer_org_identifier_id>?))"
            )
            params += (created_at_utc, created_at_utc, identifier_id)
        exact_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM customer_org_identifiers "
                "WHERE customer_org_id=? AND identifier_type='customer_account_code'",
                (customer_org_id,),
            ).fetchone()[0]
        )
        rows = connection.execute(
            "SELECT customer_org_identifier_id,value_text,lifecycle_state,created_at_utc,"
            "superseded_at_utc,created_command_id,superseded_command_id "
            "FROM customer_org_identifiers "
            "WHERE customer_org_id=? AND identifier_type='customer_account_code'"
            + after_sql
            + " ORDER BY created_at_utc,customer_org_identifier_id LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(
            CustomerAccountCodeHistoryItem(
                customer_org_identifier_id=str(row[0]),
                value_text=str(row[1]),
                lifecycle_state=str(row[2]),
                created_at_utc=int(row[3]),
                superseded_at_utc=None if row[4] is None else int(row[4]),
                created_command_id=str(row[5]),
                superseded_command_id=None if row[6] is None else str(row[6]),
            )
            for row in visible
        )
        continuation = None
        if has_more and items:
            last = items[-1]
            continuation = encode_cursor(
                query_id="GetCustomerAccountCodeHistory",
                sort_registry_id="ACCOUNT_CODE_HISTORY_CREATED_ID_ASC_V1",
                last_key_tuple=(last.created_at_utc, last.customer_org_identifier_id),
                filter_payload=filter_payload,
            )
        return CustomerAccountCodeHistoryPage(exact_count, items, continuation)

    @classmethod
    def contact_channels_from_connection(
        cls,
        connection: Any,
        *,
        contact_id: str,
        include_archived: bool = False,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
        include_exact_count: bool = False,
    ) -> ContactChannelPage:
        limit = cls._limit(limit)
        if type(include_archived) is not bool or type(include_exact_count) is not bool:
            raise ValidationError("Contact channel query flags must be boolean")
        cls._require_contact(connection, contact_id)
        filter_payload = {
            "schema": "SOMA_CONTACT_CHANNEL_FILTER_V1",
            "contact_id": contact_id,
            "include_archived": include_archived,
        }
        key = decode_cursor(
            cursor,
            query_id="GetContactChannels",
            sort_registry_id="CONTACT_CHANNEL_KIND_CREATED_ID_ASC_V1",
            filter_payload=filter_payload,
            key_length=3,
        )
        where = "contact_id=?"
        params: tuple[object, ...] = (contact_id,)
        if not include_archived:
            where += " AND lifecycle_state='active'"
        if key is not None:
            channel_kind, created_at_utc, channel_id = key
            if (
                not isinstance(channel_kind, str)
                or type(created_at_utc) is not int
                or not isinstance(channel_id, str)
            ):
                raise ValidationError("Contact channel cursor key is invalid")
            where += (
                " AND (channel_kind>? OR "
                "(channel_kind=? AND created_at_utc>?) OR "
                "(channel_kind=? AND created_at_utc=? AND contact_channel_id>?))"
            )
            params += (
                channel_kind,
                channel_kind,
                created_at_utc,
                channel_kind,
                created_at_utc,
                channel_id,
            )
        exact_count = None
        if include_exact_count:
            count_where = "contact_id=?"
            count_params: tuple[object, ...] = (contact_id,)
            if not include_archived:
                count_where += " AND lifecycle_state='active'"
            exact_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM contact_channels WHERE " + count_where,
                    count_params,
                ).fetchone()[0]
            )
        rows = connection.execute(
            "SELECT contact_channel_id,channel_kind,value_text,lifecycle_state,revision,"
            "created_at_utc,updated_at_utc FROM contact_channels WHERE "
            + where
            + " ORDER BY channel_kind,created_at_utc,contact_channel_id LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(
            ContactChannelItem(
                contact_channel_id=str(row[0]),
                channel_kind=str(row[1]),
                value_text=str(row[2]),
                lifecycle_state=str(row[3]),
                revision=int(row[4]),
                created_at_utc=int(row[5]),
                updated_at_utc=int(row[6]),
            )
            for row in visible
        )
        continuation = None
        if has_more and items:
            last = items[-1]
            continuation = encode_cursor(
                query_id="GetContactChannels",
                sort_registry_id="CONTACT_CHANNEL_KIND_CREATED_ID_ASC_V1",
                last_key_tuple=(
                    last.channel_kind,
                    last.created_at_utc,
                    last.contact_channel_id,
                ),
                filter_payload=filter_payload,
            )
        return ContactChannelPage(exact_count, items, continuation)

    @classmethod
    def contact_affiliation_history_from_connection(
        cls,
        connection: Any,
        *,
        contact_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> ContactAffiliationHistoryPage:
        limit = cls._limit(limit)
        cls._require_contact(connection, contact_id)
        filter_payload = {
            "schema": "SOMA_CONTACT_AFFILIATION_HISTORY_FILTER_V1",
            "contact_id": contact_id,
        }
        key = decode_cursor(
            cursor,
            query_id="GetContactAffiliationHistory",
            sort_registry_id="CONTACT_AFFILIATION_OPENED_ID_ASC_V1",
            filter_payload=filter_payload,
            key_length=2,
        )
        params: tuple[object, ...] = (contact_id,)
        after_sql = ""
        if key is not None:
            opened_at_utc, affiliation_id = key
            if type(opened_at_utc) is not int or not isinstance(affiliation_id, str):
                raise ValidationError("Contact affiliation cursor key is invalid")
            after_sql = (
                " AND (opened_at_utc>? OR "
                "(opened_at_utc=? AND contact_affiliation_id>?))"
            )
            params += (opened_at_utc, opened_at_utc, affiliation_id)
        exact_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM contact_affiliations WHERE contact_id=?",
                (contact_id,),
            ).fetchone()[0]
        )
        rows = connection.execute(
            "SELECT contact_affiliation_id,customer_org_id,is_current,opened_at_utc,"
            "closed_at_utc,opened_command_id,closed_command_id "
            "FROM contact_affiliations WHERE contact_id=?"
            + after_sql
            + " ORDER BY opened_at_utc,contact_affiliation_id LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(
            ContactAffiliationHistoryItem(
                contact_affiliation_id=str(row[0]),
                customer_org_id=str(row[1]),
                is_current=bool(int(row[2])),
                opened_at_utc=int(row[3]),
                closed_at_utc=None if row[4] is None else int(row[4]),
                opened_command_id=str(row[5]),
                closed_command_id=None if row[6] is None else str(row[6]),
            )
            for row in visible
        )
        continuation = None
        if has_more and items:
            last = items[-1]
            continuation = encode_cursor(
                query_id="GetContactAffiliationHistory",
                sort_registry_id="CONTACT_AFFILIATION_OPENED_ID_ASC_V1",
                last_key_tuple=(last.opened_at_utc, last.contact_affiliation_id),
                filter_payload=filter_payload,
            )
        return ContactAffiliationHistoryPage(exact_count, items, continuation)

    def get_customer_account_code_history(
        self,
        *,
        customer_org_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> CustomerAccountCodeHistoryPage:
        with ReadSnapshot(self._factory) as snapshot:
            return self.customer_account_code_history_from_connection(
                snapshot.connection,
                customer_org_id=customer_org_id,
                cursor=cursor,
                limit=limit,
            )

    def get_contact_channels(
        self,
        *,
        contact_id: str,
        include_archived: bool = False,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
        include_exact_count: bool = False,
    ) -> ContactChannelPage:
        with ReadSnapshot(self._factory) as snapshot:
            return self.contact_channels_from_connection(
                snapshot.connection,
                contact_id=contact_id,
                include_archived=include_archived,
                cursor=cursor,
                limit=limit,
                include_exact_count=include_exact_count,
            )

    def get_contact_affiliation_history(
        self,
        *,
        contact_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> ContactAffiliationHistoryPage:
        with ReadSnapshot(self._factory) as snapshot:
            return self.contact_affiliation_history_from_connection(
                snapshot.connection,
                contact_id=contact_id,
                cursor=cursor,
                limit=limit,
            )
