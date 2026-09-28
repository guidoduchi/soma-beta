from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ._cursor import decode_cursor, encode_cursor
from .history import ContactChannelPage, ReferenceHistoryQueries

ReferenceType = Literal[
    "customer_organization",
    "contact",
    "dispatch_location",
    "local_user_profile",
]
ListableReferenceType = Literal[
    "customer_organization",
    "contact",
    "dispatch_location",
]

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class SiteDispatchLink:
    site_id: str
    customer_org_id: str | None = None


class SiteDispatchAddressProvider(Protocol):
    def site_link_for(
        self,
        snapshot: ReadSnapshot,
        dispatch_location_id: str,
    ) -> SiteDispatchLink | None: ...

    def current_site_address(
        self,
        snapshot: ReadSnapshot,
        site_id: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ReferenceSummary:
    reference_type: ListableReferenceType
    reference_id: str
    display_name: str
    revision: int
    lifecycle_state: str
    projection: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReferencePage:
    items: tuple[ReferenceSummary, ...]
    continuation: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ReferenceDetail:
    reference_type: ReferenceType
    reference_id: str
    revision: int
    lifecycle_state: str
    projection: dict[str, object]


class ReferenceQueries:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        site_dispatch_address_provider: SiteDispatchAddressProvider | None = None,
    ) -> None:
        self._factory = connection_factory
        self._site_addresses = site_dispatch_address_provider

    @staticmethod
    def _limit(limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise SomaError("FIELD_BOUND_EXCEEDED", "Reference page limit must be in 1..200")
        return limit

    @staticmethod
    def _customer_detail(connection: Any, customer_org_id: str) -> ReferenceDetail:
        row = connection.execute(
            "SELECT customer_org_id,name,lifecycle_state,revision "
            "FROM customer_organizations WHERE customer_org_id=?",
            (customer_org_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Customer Organization does not exist")
        current = connection.execute(
            "SELECT customer_org_identifier_id,value_text,created_at_utc "
            "FROM customer_org_identifiers "
            "WHERE customer_org_id=? AND identifier_type='customer_account_code' "
            "AND lifecycle_state='active'",
            (customer_org_id,),
        ).fetchone()
        history_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM customer_org_identifiers "
                "WHERE customer_org_id=? AND identifier_type='customer_account_code'",
                (customer_org_id,),
            ).fetchone()[0]
        )
        claim = (
            None
            if current is None
            else {
                "customer_org_identifier_id": str(current[0]),
                "value_text": str(current[1]),
                "created_at_utc": int(current[2]),
            }
        )
        return ReferenceDetail(
            "customer_organization",
            str(row[0]),
            int(row[3]),
            str(row[2]),
            {
                "name": str(row[1]),
                "current_account_code": claim,
                "account_code_history_count": history_count,
            },
        )

    @staticmethod
    def _contact_detail(
        connection: Any,
        contact_id: str,
        *,
        channel_limit: int,
    ) -> ReferenceDetail:
        row = connection.execute(
            "SELECT contact_id,name,lifecycle_state,revision FROM contacts WHERE contact_id=?",
            (contact_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Contact does not exist")
        affiliation = connection.execute(
            "SELECT contact_affiliation_id,customer_org_id,opened_at_utc "
            "FROM contact_affiliations WHERE contact_id=? AND is_current=1",
            (contact_id,),
        ).fetchone()
        channels: ContactChannelPage = ReferenceHistoryQueries.contact_channels_from_connection(
            connection,
            contact_id=contact_id,
            include_archived=False,
            limit=channel_limit,
            include_exact_count=True,
        )
        current_affiliation = (
            None
            if affiliation is None
            else {
                "contact_affiliation_id": str(affiliation[0]),
                "customer_org_id": str(affiliation[1]),
                "opened_at_utc": int(affiliation[2]),
            }
        )
        return ReferenceDetail(
            "contact",
            str(row[0]),
            int(row[3]),
            str(row[2]),
            {
                "name": str(row[1]),
                "current_affiliation": current_affiliation,
                "active_channel_count": channels.exact_count or 0,
                "channels": channels.items,
                "channels_continuation": channels.continuation,
            },
        )

    def _dispatch_detail(
        self,
        snapshot: ReadSnapshot,
        dispatch_location_id: str,
    ) -> ReferenceDetail:
        row = snapshot.connection.execute(
            "SELECT dispatch_location_id,name,address_mode,standalone_address_text,"
            "lifecycle_state,revision FROM dispatch_locations WHERE dispatch_location_id=?",
            (dispatch_location_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Dispatch Location does not exist")
        address_mode = str(row[2])
        if address_mode == "standalone":
            address_projection: dict[str, object] = {
                "source": "STANDALONE",
                "state": "READY",
                "site_id": None,
                "customer_org_id": None,
                "address_text": str(row[3]),
            }
        elif address_mode == "site_derived":
            if self._site_addresses is None:
                address_projection = {
                    "source": "SITE",
                    "state": "UNAVAILABLE",
                    "site_id": None,
                    "customer_org_id": None,
                    "address_text": None,
                }
            else:
                link = self._site_addresses.site_link_for(snapshot, dispatch_location_id)
                if link is None:
                    raise SomaError(
                        "PERSISTENCE_FAILURE",
                        "site-derived Dispatch Location has no owning Site link",
                    )
                address_projection = {
                    "source": "SITE",
                    "state": "READY",
                    "site_id": link.site_id,
                    "customer_org_id": link.customer_org_id,
                    "address_text": self._site_addresses.current_site_address(
                        snapshot,
                        link.site_id,
                    ),
                }
        else:
            raise SomaError("PERSISTENCE_FAILURE", "Dispatch Location address mode is invalid")
        return ReferenceDetail(
            "dispatch_location",
            str(row[0]),
            int(row[5]),
            str(row[4]),
            {
                "name": str(row[1]),
                "address_mode": address_mode,
                "current_address": address_projection,
            },
        )

    @staticmethod
    def _profile_detail(connection: Any, local_user_profile_id: str) -> ReferenceDetail:
        row = connection.execute(
            "SELECT local_user_profile_id,display_name,revision "
            "FROM local_user_profiles WHERE local_user_profile_id=? AND singleton_guard=1",
            (local_user_profile_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Local User Profile does not exist")
        return ReferenceDetail(
            "local_user_profile",
            str(row[0]),
            int(row[2]),
            "active",
            {"display_name": str(row[1])},
        )

    def get_reference_by_id(
        self,
        *,
        reference_type: ReferenceType,
        reference_id: str,
        channel_limit: int = _DEFAULT_LIMIT,
    ) -> ReferenceDetail:
        channel_limit = self._limit(channel_limit)
        with ReadSnapshot(self._factory) as snapshot:
            if reference_type == "customer_organization":
                return self._customer_detail(snapshot.connection, reference_id)
            if reference_type == "contact":
                return self._contact_detail(
                    snapshot.connection,
                    reference_id,
                    channel_limit=channel_limit,
                )
            if reference_type == "dispatch_location":
                return self._dispatch_detail(snapshot, reference_id)
            if reference_type == "local_user_profile":
                return self._profile_detail(snapshot.connection, reference_id)
            raise ValidationError("Reference type is invalid")

    def list_active_references(
        self,
        *,
        reference_type: ListableReferenceType,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> ReferencePage:
        limit = self._limit(limit)
        definitions = {
            "customer_organization": (
                "customer_organizations",
                "customer_org_id",
                "name",
                "name_match_key",
                "CUSTOMER_REFERENCE_NAME_ID_ASC_V1",
            ),
            "contact": (
                "contacts",
                "contact_id",
                "name",
                "name_match_key",
                "CONTACT_REFERENCE_NAME_ID_ASC_V1",
            ),
            "dispatch_location": (
                "dispatch_locations",
                "dispatch_location_id",
                "name",
                "name_match_key",
                "DISPATCH_REFERENCE_NAME_ID_ASC_V1",
            ),
        }
        if reference_type not in definitions:
            raise ValidationError("Reference list type is invalid")
        table, id_column, name_column, key_column, sort_registry_id = definitions[reference_type]
        filter_payload = {
            "schema": "SOMA_ACTIVE_REFERENCE_FILTER_V1",
            "reference_type": reference_type,
            "lifecycle_state": "active",
        }
        key = decode_cursor(
            cursor,
            query_id="ListActiveReferences",
            sort_registry_id=sort_registry_id,
            filter_payload=filter_payload,
            key_length=2,
        )
        where = "lifecycle_state='active'"
        params: tuple[object, ...] = ()
        if key is not None:
            display_key, reference_id = key
            if not isinstance(display_key, str) or not isinstance(reference_id, str):
                raise ValidationError("Reference list cursor key is invalid")
            where += (
                f" AND ({key_column}>? OR "
                f"({key_column}=? AND {id_column}>?))"
            )
            params = (display_key, display_key, reference_id)
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                f"SELECT {id_column},{name_column},{key_column},revision,lifecycle_state "
                f"FROM {table} WHERE {where} "
                f"ORDER BY {key_column},{id_column} LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(
            ReferenceSummary(
                reference_type=reference_type,
                reference_id=str(row[0]),
                display_name=str(row[1]),
                revision=int(row[3]),
                lifecycle_state=str(row[4]),
                projection={"name": str(row[1])},
            )
            for row in visible
        )
        continuation = None
        if has_more and visible:
            last = visible[-1]
            continuation = encode_cursor(
                query_id="ListActiveReferences",
                sort_registry_id=sort_registry_id,
                last_key_tuple=(str(last[2]), str(last[0])),
                filter_payload=filter_payload,
            )
        return ReferencePage(items, continuation)
