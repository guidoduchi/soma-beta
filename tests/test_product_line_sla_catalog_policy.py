from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.reference.application.customer_service import CustomerReferenceService
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.policy import ProductLineSlaPolicyService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def test_catalog_creation_initial_policy_revision_and_exact_replay(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Acme Telecom",
    )
    catalog = ProductLineSlaCatalogService(factory)

    product_command = new_uuid4()
    product = catalog.create_product_line(
        command_id=product_command,
        name="IP Core",
    )
    product_replay = catalog.create_product_line(
        command_id=product_command,
        name="IP Core",
    )
    assert product_replay.replayed is True
    assert product_replay.target_id == product.target_id
    assert product.revision == 1

    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name="Managed Services 2026",
        contract_reference="MS-2026-001",
    )

    cpl_command = new_uuid4()
    cpl = catalog.create_contract_product_line(
        command_id=cpl_command,
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name="IT Default",
        initial_template_source="IT_DEFAULT_V1",
    )
    replay = catalog.create_contract_product_line(
        command_id=cpl_command,
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name="IT Default",
        initial_template_source="IT_DEFAULT_V1",
    )
    assert replay.replayed is True
    assert replay.target_id == cpl.target_id
    assert replay.policy_revision_id == cpl.policy_revision_id
    assert cpl.revision == 1
    assert cpl.policy_revision_id is not None

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        cpl_row = connection.execute(
            "SELECT contract_id,product_line_id,current_policy_revision_id,revision "
            "FROM contract_product_lines WHERE contract_product_line_id=?",
            (cpl.target_id,),
        ).fetchone()
        assert tuple(cpl_row) == (
            contract.target_id,
            product.target_id,
            cpl.policy_revision_id,
            1,
        )

        policy = connection.execute(
            "SELECT contract_product_line_id,revision_ordinal,policy_name,template_source "
            "FROM sla_policy_revisions WHERE policy_revision_id=?",
            (cpl.policy_revision_id,),
        ).fetchone()
        assert tuple(policy) == (cpl.target_id, 1, "IT Default", "IT_DEFAULT_V1")

        tiers = connection.execute(
            "SELECT policy_tier_id,severity,tier_ordinal,required_percentage_millionths,"
            "maximum_duration_numerator_seconds,maximum_duration_denominator,derived_from_tier_id "
            "FROM sla_policy_tiers WHERE policy_revision_id=? "
            "ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'major' THEN 2 WHEN 'minor' THEN 3 ELSE 4 END,"
            "tier_ordinal",
            (cpl.policy_revision_id,),
        ).fetchall()
        assert len(tiers) == 7
        minor_ids = {int(row[2]): str(row[0]) for row in tiers if str(row[1]) == "minor"}
        derived = [row for row in tiers if str(row[1]) == "non_fault_inquiry"]
        assert [int(row[3]) for row in derived] == [85_000_000, 100_000_000]
        assert [int(row[4]) for row in derived] == [5_832_000, 7_776_000]
        assert [str(row[6]) for row in derived] == [minor_ids[1], minor_ids[2]]

        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (cpl_command,),
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_revise_policy_advances_cpl_once_and_preserves_prior_revision(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Beta Carrier",
    )
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(command_id=new_uuid4(), name="NFV")
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name="NFV Support",
        contract_reference="NFV-42",
    )
    cpl = catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name="Initial IT",
        initial_template_source="IT_DEFAULT_V1",
    )
    assert cpl.policy_revision_id is not None

    service = ProductLineSlaPolicyService(factory)
    command_id = new_uuid4()
    revised = service.revise_policy(
        command_id=command_id,
        contract_product_line_id=cpl.target_id,
        base_revision=1,
        policy_name="NFV Default",
        template_source="NFV_DEFAULT_V1",
        reason_category="contract_policy_revision",
    )
    replay = service.revise_policy(
        command_id=command_id,
        contract_product_line_id=cpl.target_id,
        base_revision=1,
        policy_name="NFV Default",
        template_source="NFV_DEFAULT_V1",
        reason_category="contract_policy_revision",
    )
    assert replay.replayed is True
    assert replay.policy_revision_id == revised.policy_revision_id
    assert revised.policy_revision_ordinal == 2
    assert revised.cpl_revision == 2
    assert revised.tier_count == 4

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        current = connection.execute(
            "SELECT current_policy_revision_id,revision FROM contract_product_lines "
            "WHERE contract_product_line_id=?",
            (cpl.target_id,),
        ).fetchone()
        assert tuple(current) == (revised.policy_revision_id, 2)

        revisions = connection.execute(
            "SELECT policy_revision_id,revision_ordinal,policy_name,template_source "
            "FROM sla_policy_revisions WHERE contract_product_line_id=? ORDER BY revision_ordinal",
            (cpl.target_id,),
        ).fetchall()
        assert [tuple(row) for row in revisions] == [
            (cpl.policy_revision_id, 1, "Initial IT", "IT_DEFAULT_V1"),
            (revised.policy_revision_id, 2, "NFV Default", "NFV_DEFAULT_V1"),
        ]
        old_tier_count = connection.execute(
            "SELECT COUNT(*) FROM sla_policy_tiers WHERE policy_revision_id=?",
            (cpl.policy_revision_id,),
        ).fetchone()[0]
        new_tiers = connection.execute(
            "SELECT severity,required_percentage_millionths,maximum_duration_numerator_seconds,"
            "maximum_duration_denominator FROM sla_policy_tiers WHERE policy_revision_id=? "
            "ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'major' THEN 2 WHEN 'minor' THEN 3 ELSE 4 END,"
            "tier_ordinal",
            (revised.policy_revision_id,),
        ).fetchall()
        assert old_tier_count == 7
        assert [tuple(row) for row in new_tiers] == [
            ("critical", 100_000_000, 259_200, 1),
            ("major", 100_000_000, 1_296_000, 1),
            ("minor", 100_000_000, 7_776_000, 1),
            ("non_fault_inquiry", 100_000_000, 11_664_000, 1),
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=? AND action_type='sla.policy.revised'",
            (command_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()
