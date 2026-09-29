from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.services.core import InfrastructureService
from soma.infrastructure.services.participants import SiteDispatchAddressProvider
from soma.infrastructure.services.sites import dependency_snapshot, duplicate_fingerprint
from soma.reference.application.customer_service import CustomerReferenceService


class _ClearSiteDependency:
    @staticmethod
    def guard_archive(reader, site_id):
        del reader, site_id
        return "CLEAR"

    @staticmethod
    def count_blockers(snapshot, site_id):
        del snapshot, site_id
        return 0

    @staticmethod
    def list_blockers(snapshot, site_id, cursor, limit):
        del snapshot, site_id, cursor, limit
        return {"blockers": [], "continuation": None}


def _assembled(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    service = InfrastructureService(
        factory,
        site_dependencies=(
            _ClearSiteDependency(),
            _ClearSiteDependency(),
            _ClearSiteDependency(),
        ),
    )
    first_customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Site certification customer A",
    ).customer_org_id
    second_customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Site certification customer B",
    ).customer_org_id
    return factory, service, first_customer, second_customer


def _site(service, customer_id: str, *, name: str, address: str):
    return service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": name,
            "address_text": address,
        },
    ).response["target"]["id"]


def test_duplicate_site_address_is_review_evidence_not_identity_authority(
    initialized_database,
):
    factory, service, customer_id, _other = _assembled(initialized_database)
    address = "10 Duplicate Avenue"
    first = _site(
        service,
        customer_id,
        name="Duplicate Site A",
        address=address,
    )
    with ReadSnapshot(factory) as snapshot:
        preview = duplicate_fingerprint(snapshot, "10 duplicate avenue")

    second = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Duplicate Site B",
            "address_text": address,
            "duplicate_review_fingerprint": preview,
        },
    ).response["target"]["id"]

    assert first != second
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM sites WHERE address_match_key=?",
            ("10 duplicate avenue",),
        ).fetchone() == (2,)
        dispatches = snapshot.connection.execute(
            "SELECT site_id,dispatch_location_id FROM site_dispatch_locations "
            "WHERE site_id IN (?,?) ORDER BY site_id",
            (first, second),
        ).fetchall()
        assert len(dispatches) == 2
        assert dispatches[0][1] != dispatches[1][1]


def test_site_customer_correction_is_blocked_after_physical_history_exists(
    initialized_database,
):
    factory, service, first_customer, second_customer = _assembled(
        initialized_database
    )
    site_id = _site(
        service,
        first_customer,
        name="Ownership Site",
        address="20 Ownership Road",
    )
    service.execute(
        "CreateNetworkElement",
        command_id=new_uuid4(),
        payload={
            "new_element": {
                "site_id": site_id,
                "operational_name": "NE-OWNERSHIP-BLOCKER",
            }
        },
    )

    with ReadSnapshot(factory) as snapshot:
        row_cursor = snapshot.connection.execute(
            "SELECT * FROM sites WHERE site_id=?",
            (site_id,),
        )
        site_row = dict(
            zip(
                (column[0] for column in row_cursor.description),
                row_cursor.fetchone(),
            )
        )
        preview, physical, owners = dependency_snapshot(
            service,
            snapshot,
            site_id,
            site_row,
        )
    assert physical["network_elements"] == 1
    assert owners == ["CLEAR", "CLEAR", "CLEAR"]

    command_id = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        service.execute(
            "CorrectSiteCustomerOwnership",
            command_id=command_id,
            payload={
                "site_id": site_id,
                "base_revision": 1,
                "new_customer_org_id": second_customer,
                "reason_code": "reviewed_correction",
                "dependency_preview_fingerprint": preview,
            },
        )
    assert blocked.value.code == "SITE_CUSTOMER_CORRECTION_BLOCKED"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT customer_org_id,revision FROM sites WHERE site_id=?",
            (site_id,),
        ).fetchone() == (first_customer, 1)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (0,)


def test_site_archive_preserves_dedicated_dispatch_identity_and_address_derivation(
    initialized_database,
):
    factory, service, customer_id, _other = _assembled(initialized_database)
    site_id = _site(
        service,
        customer_id,
        name="Archive Site",
        address="30 Original Street",
    )
    with ReadSnapshot(factory) as snapshot:
        dispatch_id = snapshot.connection.execute(
            "SELECT dispatch_location_id FROM site_dispatch_locations WHERE site_id=?",
            (site_id,),
        ).fetchone()[0]

    service.execute(
        "UpdateSiteDescriptive",
        command_id=new_uuid4(),
        payload={
            "site_id": site_id,
            "base_revision": 1,
            "name": "Archive Site Renamed",
            "address_text": "31 Corrected Street",
            "reason_code": "address_correction",
        },
    )
    with ReadSnapshot(factory) as snapshot:
        assert SiteDispatchAddressProvider.current_site_address(
            snapshot,
            site_id,
        ) == "31 Corrected Street"
        row_cursor = snapshot.connection.execute(
            "SELECT * FROM sites WHERE site_id=?",
            (site_id,),
        )
        site_row = dict(
            zip(
                (column[0] for column in row_cursor.description),
                row_cursor.fetchone(),
            )
        )
        blocker_preview, physical, owners = dependency_snapshot(
            service,
            snapshot,
            site_id,
            site_row,
        )
    assert not any(physical.values())
    assert owners == ["CLEAR", "CLEAR", "CLEAR"]

    archived = service.execute(
        "ChangeSiteLifecycle",
        command_id=new_uuid4(),
        payload={
            "site_id": site_id,
            "base_revision": 2,
            "target_state": "archived",
            "blocker_preview_fingerprint": blocker_preview,
        },
    )
    assert archived.response["revision"] == 3

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT lifecycle_state,revision FROM sites WHERE site_id=?",
            (site_id,),
        ).fetchone() == ("archived", 3)
        assert snapshot.connection.execute(
            "SELECT dispatch_location_id FROM site_dispatch_locations WHERE site_id=?",
            (site_id,),
        ).fetchone() == (dispatch_id,)
        link = SiteDispatchAddressProvider.site_link_for(snapshot, dispatch_id)
        assert link is not None
        assert link.site_id == site_id
