from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.services.core import InfrastructureService
from soma.infrastructure.services.participants import SiteDispatchAddressProvider
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.queries.references import ReferenceQueries


def test_site_derived_dispatch_address_is_live_or_bounded_unavailable(
    initialized_database,
) -> None:
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    service = InfrastructureService(factory)
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Dispatch address customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Dispatch address Site",
            "address_text": "40 Initial Street",
        },
    ).response["target"]["id"]

    with ReadSnapshot(factory) as snapshot:
        dispatch_id = str(
            snapshot.connection.execute(
                "SELECT dispatch_location_id FROM site_dispatch_locations WHERE site_id=?",
                (site_id,),
            ).fetchone()[0]
        )
        standalone_address = snapshot.connection.execute(
            "SELECT standalone_address_text FROM dispatch_locations "
            "WHERE dispatch_location_id=?",
            (dispatch_id,),
        ).fetchone()
        assert standalone_address == (None,)

    unavailable = ReferenceQueries(factory).get_reference_by_id(
        reference_type="dispatch_location",
        reference_id=dispatch_id,
    )
    assert unavailable.projection["current_address"] == {
        "source": "SITE",
        "state": "UNAVAILABLE",
        "site_id": None,
        "customer_org_id": None,
        "address_text": None,
    }

    service.execute(
        "UpdateSiteDescriptive",
        command_id=new_uuid4(),
        payload={
            "site_id": site_id,
            "base_revision": 1,
            "name": "Dispatch address Site",
            "address_text": "41 Corrected Street",
            "reason_code": "reviewed_address_correction",
        },
    )
    available = ReferenceQueries(
        factory,
        site_dispatch_address_provider=SiteDispatchAddressProvider(),
    ).get_reference_by_id(
        reference_type="dispatch_location",
        reference_id=dispatch_id,
    )
    assert available.projection["current_address"] == {
        "source": "SITE",
        "state": "READY",
        "site_id": site_id,
        "customer_org_id": customer_id,
        "address_text": "41 Corrected Street",
    }

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT standalone_address_text FROM dispatch_locations "
            "WHERE dispatch_location_id=?",
            (dispatch_id,),
        ).fetchone() == (None,)
