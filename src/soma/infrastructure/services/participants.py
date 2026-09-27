from soma.foundation.errors import SomaError
from soma.infrastructure.repositories.core import get, one
from soma.reference.queries.references import SiteDispatchLink


class DeviceReferenceResolutionReader:
    @staticmethod
    def resolution_for(reader, device_reference_id):
        return get(reader, "device_reference_resolution_current", device_reference_id, optional=True)


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
