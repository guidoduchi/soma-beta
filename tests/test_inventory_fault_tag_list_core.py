"""Accepted core query infrastructure, not full FaultTagListQuery certification."""
import copy

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.api.routes_fault_tags import build_route_adapter
from soma.inventory.queries.fault_tags import InventoryFaultTagQueryService
from soma.inventory.services.fault_tags import InventoryFaultTagsService


def seeded(initialized_database):
    path, builder = initialized_database
    factory = builder(path)
    service = InventoryFaultTagsService(factory)
    rows = [service.create_fault_tag_draft(command_id=new_uuid4(), return_method='non_pickup') for _ in range(4)]
    return factory, sorted(row['fault_tag_id'] for row in rows)


def counts(factory):
    with ReadSnapshot(factory) as snapshot:
        return tuple(snapshot.connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                     for table in ('command_receipts', 'audit_events', 'fault_tags', 'fault_tag_memberships'))


def test_core_http_paging_keeps_exact_total_and_full_cursor_without_member_enumeration(initialized_database):
    factory, ids = seeded(initialized_database)
    query = InventoryFaultTagQueryService(factory)
    adapter = build_route_adapter({'FaultTagListQuery': lambda _route, request: query.list_query(dict(request))})
    before = counts(factory)
    first = adapter.dispatch('GET', '/api/v1/inventory/fault-tags', {'state': 'draft', 'archived': False, 'limit': 2})
    assert first.response_type == 'FaultTagPageV1'
    assert first.body['exact_total'] == 4
    assert [item['fault_tag_id'] for item in first.body['items']] == ids[:2]
    assert all(set(item) == {'fault_tag_id', 'tracking_handle', 'state', 'archived', 'submitted_member_count',
        'awaiting_receipt_count', 'awaiting_final_count', 'accepted_count', 'rejected_count', 'revision'} for item in first.body['items'])
    cursor = first.body['continuation']
    assert cursor['last_key_tuple'] == [ids[1]]
    assert set(cursor) == {'version', 'query_id', 'sort_registry_id', 'last_key_tuple', 'filter_fingerprint', 'null_order'}
    second = query.list_query({'state': 'draft', 'archived': False, 'limit': 3, 'cursor': cursor})
    assert [item['fault_tag_id'] for item in second['items']] == ids[2:]
    assert second['exact_total'] == 4 and second['continuation'] is None
    assert counts(factory) == before
    for changed in ({'state': 'submitted', 'archived': False}, {'state': 'draft', 'archived': True}):
        with pytest.raises(ValidationError): query.list_query(dict(changed, cursor=cursor))


@pytest.mark.parametrize('mutation', ['version_bool', 'query', 'sort', 'null', 'key', 'identity', 'unknown'])
def test_core_cursor_rejects_wrong_owner_incomplete_key_and_unregistered_fields(initialized_database, mutation):
    factory, _ids = seeded(initialized_database)
    query = InventoryFaultTagQueryService(factory)
    cursor = copy.deepcopy(query.list_tags(limit=1)['continuation'])
    if mutation == 'version_bool': cursor['version'] = True
    if mutation == 'query': cursor['query_id'] = 'InventoryAttentionQuery'
    if mutation == 'sort': cursor['sort_registry_id'] = 'other'
    if mutation == 'null': cursor['null_order'] = 'none'
    if mutation == 'key': cursor['last_key_tuple'] = []
    if mutation == 'identity': cursor['last_key_tuple'] = ['invalid']
    if mutation == 'unknown': cursor['draft'] = 'must not persist'
    with pytest.raises(ValidationError): query.list_tags(cursor=cursor)


@pytest.mark.parametrize('dto', [{'after_id': 'invalid'}, {'attention': True}, {'service_request_id': 'invalid'},
    {'sr7': 'SR1234567'}, {'c10': 'C0000000001'}, {'limit': True}, {'limit': 0}, {'limit': 501}, {'archived': 1}])
def test_core_unclosed_filters_and_invalid_bounds_fail_closed(initialized_database, dto):
    path, builder = initialized_database
    with pytest.raises(ValidationError): InventoryFaultTagQueryService(builder(path)).list_query(dto)
