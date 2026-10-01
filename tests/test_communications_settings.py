import sqlite3

import pytest

from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.settings import GRACE_KEY, build_communications_setting_registry
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4


def test_lld09_a049_a050_schedule_reuses_setting_owner_and_exact_replay(initialized_database):
    path, factory_for = initialized_database
    service = CommunicationSettingsService(factory_for(path))
    state = service.schedule_state()
    unchanged = service.set_processing_schedule(state | {'command_id': new_uuid4()})
    assert unchanged['status'] == 'NO_CHANGE'
    payload = state | {'enabled': False, 'interval_minutes': 1, 'overlap_messages': 500, 'command_id': new_uuid4()}
    changed = service.set_processing_schedule(payload)
    assert changed['status'] == 'APPLIED'
    assert service.set_processing_schedule(payload) == changed
    assert service.schedule_state()['enabled'] is False
    with pytest.raises(SomaError) as raised:
        service.set_processing_schedule(state | {'command_id': new_uuid4()})
    assert raised.value.code == 'COMM_STALE'
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT count(*) FROM setting_values').fetchone()[0] == 3
        assert connection.execute('SELECT count(*) FROM audit_events').fetchone()[0] == 4
        assert connection.execute('SELECT count(*) FROM durable_jobs').fetchone()[0] == 0
        assert connection.execute('SELECT count(DISTINCT command_id) FROM setting_values').fetchone()[0] == 1


def test_grace_setting_freshness_defaults_and_bounds(initialized_database):
    path, factory_for = initialized_database
    service = CommunicationSettingsService(factory_for(path))
    assert service.set_orphan_grace({'command_id': new_uuid4(), 'grace_minutes': 10080, 'setting_revision': 0})['status'] == 'NO_CHANGE'
    first = {'command_id': new_uuid4(), 'grace_minutes': 1, 'setting_revision': 0}
    result = service.set_orphan_grace(first)
    assert result['new_revision'] == 1
    service.set_orphan_grace({'command_id': new_uuid4(), 'grace_minutes': 525600, 'setting_revision': 1})
    assert service.set_orphan_grace(first) == result
    with pytest.raises(SomaError) as raised:
        service.set_orphan_grace({'command_id': new_uuid4(), 'grace_minutes': 2, 'setting_revision': 1})
    assert raised.value.code == 'COMM_STALE'
    for value in (True, 0, 525601, 1.0):
        with pytest.raises(ValidationError):
            build_communications_setting_registry().require(GRACE_KEY).validate_value(value)


def test_schedule_audit_failure_rolls_back_all_setting_participants(initialized_database, monkeypatch):
    path, factory_for = initialized_database
    service = CommunicationSettingsService(factory_for(path))
    command = new_uuid4()
    state = service.schedule_state()
    writer = service._boundary._audit_writer
    original = writer.write
    calls = []
    def fail_last(uow, event):
        calls.append(event.action_type)
        if event.action_type == 'communications.processing_schedule.changed':
            raise RuntimeError('injected owner audit failure')
        return original(uow, event)
    monkeypatch.setattr(writer, 'write', fail_last)
    with pytest.raises(RuntimeError):
        service.set_processing_schedule(state | {'command_id': command, 'enabled': False, 'interval_minutes': 2})
    assert calls == ['setting.written', 'setting.written', 'communications.processing_schedule.changed']
    assert service.schedule_state() == state
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT count(*) FROM setting_values').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM audit_events').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM command_receipts').fetchone()[0] == 0
