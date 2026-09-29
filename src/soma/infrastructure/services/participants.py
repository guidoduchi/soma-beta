from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.infrastructure.repositories.core import get, one
from soma.reference.queries.references import SiteDispatchLink


class DeviceReferenceResolutionReader:
    _MAX_SITE_PAGE = 200

    @staticmethod
    def _site_cursor(cursor):
        if cursor is None:
            return None
        if not isinstance(cursor, (list, tuple)) or len(cursor) != 2:
            raise ValidationError("Device Reference Site-resolution cursor is invalid")
        return require_uuid4(cursor[0]), require_uuid4(cursor[1])

    @staticmethod
    def resolution_for(reader, device_reference_id):
        identity = require_uuid4(device_reference_id)
        return one(
            reader,
            "SELECT r.device_reference_id,r.network_element_id,n.site_id,r.revision,"
            "r.last_event_id,r.last_command_id "
            "FROM device_reference_resolution_current r "
            "JOIN network_elements n ON n.network_element_id=r.network_element_id "
            "WHERE r.device_reference_id=?",
            (identity,),
        )

    @classmethod
    def list_for_site(cls, reader, site_id, cursor, limit):
        identity = require_uuid4(site_id)
        if type(limit) is not int or limit < 1 or limit > cls._MAX_SITE_PAGE:
            raise ValidationError("Device Reference Site-resolution page limit must be in 1..200")
        after = cls._site_cursor(cursor)
        sql = (
            "SELECT r.network_element_id,r.device_reference_id "
            "FROM network_elements n "
            "JOIN device_reference_resolution_current r "
            "ON r.network_element_id=n.network_element_id "
            "WHERE n.site_id=? "
        )
        params = [identity]
        if after is not None:
            sql += (
                "AND (r.network_element_id>? OR "
                "(r.network_element_id=? AND r.device_reference_id>?)) "
            )
            params.extend((after[0], after[0], after[1]))
        sql += "ORDER BY r.network_element_id,r.device_reference_id LIMIT ?"
        params.append(limit + 1)
        result = reader.connection.execute(sql, tuple(params)).fetchall()
        visible = result[:limit]
        items = [
            {
                "network_element_id": str(row[0]),
                "device_reference_id": str(row[1]),
            }
            for row in visible
        ]
        continuation = (
            [str(visible[-1][0]), str(visible[-1][1])]
            if len(result) > limit and visible
            else None
        )
        return {"items": items, "continuation": continuation}


class SiteDispatchAddressProvider:
    @staticmethod
    def site_link_for(reader, dispatch_location_id):
        row = one(reader, "SELECT s.site_id,s.customer_org_id FROM site_dispatch_locations l JOIN sites s ON s.site_id=l.site_id WHERE l.dispatch_location_id=?", (dispatch_location_id,))
        return None if row is None else SiteDispatchLink(row["site_id"], row["customer_org_id"])

    @staticmethod
    def current_site_address(reader, site_id):
        return get(reader, "sites", site_id)["address_text"]


class DevicePartInstalledComponentResolution:
    def __init__(self, service):
        self.service = service

    def current(self, reader, device_part_unit_id):
        return get(reader, "device_part_component_resolution_current", device_part_unit_id, optional=True)

    def validate_target(self, uow, device_part_unit_id, installed_component_id):
        from .regularization import validate_component_target
        return validate_component_target(self.service, uow, device_part_unit_id, installed_component_id)

    def link_or_correct(self, uow, device_part_unit_id, installed_component_id_or_null, context):
        from .regularization import prepare
        if not uow.connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (context["command_id"],)).fetchone():
            raise SomaError("PERSISTENCE_FAILURE", "Parent command receipt must precede resolution")
        plan = prepare(self.service, uow, "ResolveDevicePartToInstalledComponent",
                       dict(device_part_unit_id=device_part_unit_id,
                            installed_component_id=installed_component_id_or_null,
                            base_revision=context["base_revision"], reason_code=context["reason_code"]),
                       context["command_id"])
        plan.apply(uow)
        return plan.result_refs
