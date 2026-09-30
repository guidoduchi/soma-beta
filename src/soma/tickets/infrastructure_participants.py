"""Ticket-owned read interfaces consumed by Infrastructure."""
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4


class DeviceReferenceOperationalReader:
    @staticmethod
    def get(reader, device_reference_id):
        require_uuid4(device_reference_id)
        row = reader.connection.execute(
            "SELECT device_reference_id,operational_name,revision FROM device_references WHERE device_reference_id=?",
            (device_reference_id,)).fetchone()
        return None if row is None else dict(device_reference_id=row[0], operational_name=row[1], revision=row[2])


class TicketSiteDependencyValidator:
    """Read-only LLD-03 Site blocker provider over current Device Reference links."""

    _MAX_PAGE = 200
    _KINDS = frozenset({"rfc", "sr"})

    def __init__(self, resolution_reader):
        self._resolution_reader = resolution_reader

    def _provider(self):
        provider = self._resolution_reader
        if (
            provider is None
            or not callable(getattr(provider, "list_for_site", None))
            or not callable(getattr(provider, "resolution_for", None))
        ):
            raise IntegrityFailure("Device Reference resolution provider is unavailable")
        return provider

    @classmethod
    def _parse_blocker_cursor(cls, cursor):
        if cursor is None:
            return None
        if not isinstance(cursor, str):
            raise ValidationError("Ticket Site blocker cursor must be text")
        parts = cursor.split(":")
        if len(parts) != 4 or parts[2] not in cls._KINDS:
            raise ValidationError("Ticket Site blocker cursor is invalid")
        return (
            require_uuid4(parts[0]),
            require_uuid4(parts[1]),
            parts[2],
            require_uuid4(parts[3]),
        )

    @staticmethod
    def _resolution_matches(value, *, site_id, network_element_id, device_reference_id):
        if value is None:
            return False
        if isinstance(value, dict):
            raw_network_element_id = value.get("network_element_id")
            raw_site_id = value.get("site_id")
            raw_device_reference_id = value.get("device_reference_id", device_reference_id)
        else:
            raw_network_element_id = getattr(value, "network_element_id", None)
            raw_site_id = getattr(value, "site_id", None)
            raw_device_reference_id = getattr(value, "device_reference_id", device_reference_id)
        if (
            not isinstance(raw_network_element_id, str)
            or not isinstance(raw_site_id, str)
            or not isinstance(raw_device_reference_id, str)
        ):
            raise IntegrityFailure("Device Reference resolution is malformed")
        return (
            require_uuid4(raw_network_element_id) == network_element_id
            and require_uuid4(raw_site_id) == site_id
            and require_uuid4(raw_device_reference_id) == device_reference_id
        )

    @classmethod
    def _validate_resolution_page(cls, raw, after):
        if not isinstance(raw, dict) or set(raw) != {"items", "continuation"}:
            raise IntegrityFailure("Device Reference Site-resolution page is malformed")
        items = raw["items"]
        if not isinstance(items, list) or len(items) > cls._MAX_PAGE:
            raise IntegrityFailure("Device Reference Site-resolution page exceeds its bound")
        pairs = []
        previous = after
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                "network_element_id", "device_reference_id"
            }:
                raise IntegrityFailure("Device Reference Site-resolution row is malformed")
            pair = (
                require_uuid4(item["network_element_id"]),
                require_uuid4(item["device_reference_id"]),
            )
            if previous is not None and pair <= previous:
                raise IntegrityFailure("Device Reference Site-resolution order did not advance")
            pairs.append(pair)
            previous = pair
        continuation = raw["continuation"]
        if continuation is None:
            next_cursor = None
        else:
            if not isinstance(continuation, (list, tuple)) or len(continuation) != 2:
                raise IntegrityFailure("Device Reference Site-resolution continuation is malformed")
            next_cursor = require_uuid4(continuation[0]), require_uuid4(continuation[1])
            if not pairs or next_cursor != pairs[-1]:
                raise IntegrityFailure("Device Reference Site-resolution continuation is not the last row")
        return pairs, next_cursor

    @staticmethod
    def _blocker_id(row):
        network_element_id, device_reference_id, link_kind, link_id = row
        if link_kind not in {"rfc", "sr"}:
            raise IntegrityFailure("Ticket Site blocker kind is invalid")
        return (
            f"{require_uuid4(network_element_id)}:"
            f"{require_uuid4(device_reference_id)}:"
            f"{link_kind}:{require_uuid4(link_id)}"
        )

    @staticmethod
    def _rows_for_pairs(reader, pairs, *, after=None, limit):
        if not pairs:
            return []
        values = ",".join("(?,?)" for _ in pairs)
        params = [value for pair in pairs for value in pair]
        sql = (
            f"WITH resolved(network_element_id,device_reference_id) AS (VALUES {values}) "
            "SELECT * FROM ("
            "SELECT r.network_element_id,r.device_reference_id,'rfc' AS link_kind,"
            "l.rfc_device_reference_link_id AS link_id "
            "FROM resolved r JOIN rfc_device_reference_links l "
            "ON l.device_reference_id=r.device_reference_id "
            "WHERE l.link_state='active' "
            "UNION ALL "
            "SELECT r.network_element_id,r.device_reference_id,'sr' AS link_kind,"
            "l.sr_device_reference_link_id AS link_id "
            "FROM resolved r JOIN sr_device_reference_links l "
            "ON l.device_reference_id=r.device_reference_id "
            "WHERE l.link_state='active'"
            ") blockers "
        )
        if after is not None:
            sql += "WHERE link_kind>? OR (link_kind=? AND link_id>?) "
            params.extend((after[0], after[0], after[1]))
        sql += (
            "ORDER BY network_element_id,device_reference_id,link_kind,link_id LIMIT ?"
        )
        params.append(limit)
        return [
            (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
            for row in reader.connection.execute(sql, tuple(params)).fetchall()
        ]

    @staticmethod
    def _count_for_pairs(reader, pairs):
        if not pairs:
            return 0
        values = ",".join("(?,?)" for _ in pairs)
        params = tuple(value for pair in pairs for value in pair)
        row = reader.connection.execute(
            f"WITH resolved(network_element_id,device_reference_id) AS (VALUES {values}) "
            "SELECT "
            "(SELECT count(*) FROM resolved r JOIN rfc_device_reference_links l "
            "ON l.device_reference_id=r.device_reference_id WHERE l.link_state='active') + "
            "(SELECT count(*) FROM resolved r JOIN sr_device_reference_links l "
            "ON l.device_reference_id=r.device_reference_id WHERE l.link_state='active')",
            params,
        ).fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            raise IntegrityFailure("Ticket Site blocker count is invalid")
        return int(row[0])

    def _collect(self, reader, site_id, cursor, want):
        target_site = require_uuid4(site_id)
        provider = self._provider()
        parsed = self._parse_blocker_cursor(cursor)
        rows = []
        provider_cursor = None

        if parsed is not None:
            network_element_id, device_reference_id, link_kind, link_id = parsed
            resolution = provider.resolution_for(reader, device_reference_id)
            if self._resolution_matches(
                resolution,
                site_id=target_site,
                network_element_id=network_element_id,
                device_reference_id=device_reference_id,
            ):
                rows.extend(
                    self._rows_for_pairs(
                        reader,
                        [(network_element_id, device_reference_id)],
                        after=(link_kind, link_id),
                        limit=want,
                    )
                )
                if len(rows) >= want:
                    return rows[:want]
            provider_cursor = (network_element_id, device_reference_id)

        while len(rows) < want:
            raw = provider.list_for_site(
                reader, target_site, provider_cursor, self._MAX_PAGE
            )
            pairs, next_cursor = self._validate_resolution_page(raw, provider_cursor)
            rows.extend(
                self._rows_for_pairs(
                    reader,
                    pairs,
                    limit=want - len(rows),
                )
            )
            if len(rows) >= want or next_cursor is None:
                break
            provider_cursor = next_cursor
        return rows[:want]

    def guard_archive(self, uow, site_id):
        try:
            return "BLOCKED" if self._collect(uow, site_id, None, 1) else "CLEAR"
        except Exception:
            return "INDETERMINATE"

    def count_blockers(self, snapshot, site_id):
        target_site = require_uuid4(site_id)
        provider = self._provider()
        total = 0
        cursor = None
        while True:
            raw = provider.list_for_site(snapshot, target_site, cursor, self._MAX_PAGE)
            pairs, next_cursor = self._validate_resolution_page(raw, cursor)
            total += self._count_for_pairs(snapshot, pairs)
            if next_cursor is None:
                return total
            cursor = next_cursor

    def list_blockers(self, snapshot, site_id, cursor, limit):
        if type(limit) is not int or limit < 1 or limit > self._MAX_PAGE:
            raise ValidationError("Ticket Site blocker page limit must be in 1..200")
        rows = self._collect(snapshot, site_id, cursor, limit + 1)
        blocker_ids = [self._blocker_id(row) for row in rows]
        visible = blocker_ids[:limit]
        return {
            "blockers": visible,
            "continuation": (
                visible[-1] if len(blocker_ids) > limit and visible else None
            ),
        }
