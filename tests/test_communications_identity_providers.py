from dataclasses import replace

import pytest

from soma.communications.domain.initial_boundary import initial_boundary
from soma.communications.services.identity_providers import CommunicationIdentityProviders
from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.services.participants import InventoryCommunicationIdentityProvider, InventoryOverviewProjectionProvider
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.services.communication_identity import TaskObjectiveCommunicationIdentityProvider
from soma.tickets.communication_identity import TicketCommunicationIdentityProvider
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService
from test_inventory_proposal_target_participant import _draft
from test_objectives_tasks_objectives import _create_single_task_objective


def providers():
    return CommunicationIdentityProviders(TicketCommunicationIdentityProvider(), TaskObjectiveCommunicationIdentityProvider(), InventoryCommunicationIdentityProvider())


def test_master_data_and_local_task_without_external_identifier_do_not_enable_mail_processing(initialized_database):
    from soma.reference.application.customer_service import CustomerReferenceService
    from test_objectives_tasks_execution_correction import _new_task
    path, builder = initialized_database
    factory = builder(path)
    CustomerReferenceService(factory).create_customer_organization(command_id=new_uuid4(), name='Descriptive-only customer')
    _new_task(factory, name='Local-only task', ordinal=0)
    ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    with ReadSnapshot(factory) as reader:
        assert list(providers().snapshot(reader)) == []


def test_owner_providers_export_closed_identities_and_do_not_infer_source_creation(initialized_database):
    path, builder = initialized_database
    factory = builder(path)
    request, _ = _draft(factory)
    rfc = RfcService(factory).create_or_adopt_identity(command_id=new_uuid4(), rfc_no='NC00000000000001', creation_context='provisional')
    wfm = TaskPlanningService(factory).register_manual_wfm_task(command_id=new_uuid4(), task_no='TK00000000000001', rfc_id=rfc.rfc_id)
    local, objective = _create_single_task_objective(factory, name='Untrackable local task', start_utc=100, end_utc=200)
    unpromoted = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    registry = providers()
    with ReadSnapshot(factory) as reader:
        identities = tuple(registry.snapshot(reader))
        assert {item.target_type for item in identities} == {'SERVICE_REQUEST', 'RFC', 'WFM_TASK', 'OBJECTIVE', 'SPARE_REQUEST'}
        assert local.task_id not in {item.target_id for item in identities}
        assert unpromoted.service_request_id not in {item.target_id for item in identities}
        assert next(item for item in identities if item.target_id == wfm.task_id).effective_from.known is False
        assert next(item for item in identities if item.target_type == 'OBJECTIVE').normalized_value.startswith('MW-')
        assert next(item for item in identities if item.target_id == request).effective_from.known is True
        assert initial_boundary(iter(identities)).chronology.known is False
        overview = tuple(InventoryOverviewProjectionProvider.iter_communication_targets(reader, None, None))
        assert set(overview[0]) == {'target_type', 'target_id', 'target_revision', 'identities'}
    with UnitOfWork(factory) as uow:
        for identity in identities:
            assert registry.validate(uow, identity) == 'VALID'
            assert registry.validate(uow, replace(identity, target_revision=identity.target_revision + 1)) == 'INVALID'
            assert registry.validate_revision(uow, identity.target_type, identity.target_id, identity.target_revision) == 'VALID'
            assert registry.validate_revision(uow, identity.target_type, identity.target_id, identity.target_revision + 1) == 'INVALID'
            assert registry.current_revision(uow, identity.target_type, identity.target_id) == identity.target_revision
            assert tuple(registry.target_snapshot(uow, identity.target_type, identity.target_id)) == tuple(
                item for item in identities if (item.target_type, item.target_id) == (identity.target_type, identity.target_id))
            assert tuple(registry.lookup(uow, identity.normalized_value)) == tuple(item for item in identities if item.normalized_value == identity.normalized_value)


def test_inventory_former_alias_remains_resolvable_without_becoming_auto_safe(initialized_database):
    path, builder = initialized_database
    factory = builder(path)
    request, _ = _draft(factory)
    service = InventoryRequestsRmaService(factory)
    service.assign_or_correct_spare_request_official_id(command_id=new_uuid4(), spare_request_id=request, base_revision=1, sr7='SR0000001', action='assign')
    service.assign_or_correct_spare_request_official_id(command_id=new_uuid4(), spare_request_id=request, base_revision=2, sr7='SR0000002', action='correct', reason_code='CORRECTED_PROVIDER_ID')
    registry = providers()
    with ReadSnapshot(factory) as reader:
        aliases = {item.normalized_value: item for item in registry.snapshot(reader) if item.target_id == request}
        assert aliases['SR0000001'].identity_kind == 'SPARE_REQUEST_ALIAS'
        assert aliases['SR0000002'].identity_kind == 'SPARE_REQUEST_OFFICIAL'
    with UnitOfWork(factory) as uow:
        assert registry.validate(uow, aliases['SR0000001']) == 'VALID'
        assert registry.validate(uow, aliases['SR0000002']) == 'VALID'
        assert InventoryCommunicationIdentityProvider.validate_trackable_target(
            uow, 'spare_request', request, aliases['SR0000001'].target_revision, 'SR0000001') == 'INVALID'
        assert InventoryCommunicationIdentityProvider.validate_trackable_target(
            uow, 'spare_request', request, aliases['SR0000002'].target_revision, 'SR0000002') == 'VALID'
        assert registry.validate(uow, replace(aliases['SR0000001'], identity_kind='SPARE_REQUEST_OFFICIAL')) == 'INVALID'
        assert registry.validate(uow, replace(aliases['SR0000002'], identity_kind='SPARE_REQUEST_ALIAS')) == 'INVALID'


def test_missing_owner_does_not_silently_omit_its_identity_population(initialized_database):
    path, builder = initialized_database
    factory = builder(path)
    registry = CommunicationIdentityProviders(TicketCommunicationIdentityProvider(), None, InventoryCommunicationIdentityProvider())
    with ReadSnapshot(factory) as reader, pytest.raises(IntegrityFailure):
        tuple(registry.snapshot(reader))


def test_sr_reassociation_follows_accepted_terminal_and_reviewed_reversal_evidence(initialized_database):
    from test_sr_source_projection import FakeSrSourceEvidenceProvider, _apply, _delta, _official_sr
    from soma.tickets.sr_source_projection import SrSourceProjectionService
    path, builder = initialized_database
    factory = builder(path)
    sr = _official_sr(factory, '10000991')
    owner = TicketCommunicationIdentityProvider()
    source = SrSourceProjectionService(FakeSrSourceEvidenceProvider())
    with ReadSnapshot(factory) as reader:
        assert owner.validate_communication_reassociation(reader, 'SERVICE_REQUEST', sr.service_request_id, 1) == 'VALID'
    _apply(factory, source, sr.service_request_id, _delta('status', 'Closed', chronology=100))
    with ReadSnapshot(factory) as reader:
        assert owner.validate_communication_reassociation(reader, 'SERVICE_REQUEST', sr.service_request_id, 1) == 'INVALID'
    _apply(factory, source, sr.service_request_id, _delta('status', 'In Progress', chronology=200, precedence_basis='reviewed_correction'))
    with ReadSnapshot(factory) as reader:
        assert owner.validate_communication_reassociation(reader, 'SERVICE_REQUEST', sr.service_request_id, 1) == 'VALID'


def test_rfc_provider_terminal_and_pending_cascade_do_not_establish_applied_local_communication_terminal_state(initialized_database):
    from test_ticket_rfc_terminal_cascade_execute import _terminal_case
    factory, rfc, proposal_id, preview, _, _, _, execute = _terminal_case(initialized_database)
    owner = TicketCommunicationIdentityProvider()
    with ReadSnapshot(factory) as reader:
        assert owner.current_terminal_state(reader, 'RFC', rfc.rfc_id) == 'TERMINAL'
        assert owner.validate_communication_reassociation(reader, 'RFC', rfc.rfc_id, 1) == 'VALID'
    execute.execute(command_id=new_uuid4(), proposal_id=proposal_id, proposal_revision=preview.proposal_revision,
                    execution_review=preview.execution_review, deliberate_action_proof='reviewed-cascade')
    with ReadSnapshot(factory) as reader:
        assert owner.validate_communication_reassociation(reader, 'RFC', rfc.rfc_id, 1) == 'INVALID'
