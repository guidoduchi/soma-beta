"""UI intent persistence only; exactly one Foundation command/UoW per mutation."""
import hashlib

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import canonical_json_bytes
from soma.ui.audit import build_ui_audit_registry, event
from soma.ui.contracts import closed, integer
from soma.ui.repository import WorkingCopyRepository


def checkpoint_result(row):
    return {key: row[key] for key in ('working_copy_id', 'generation', 'content_hash', 'updated_at_utc', 'expires_at_utc')}


class WorkingCopyCommands:
    def __init__(self, connection_factory, contracts, *, clock=utc_epoch_seconds):
        self._contracts, self._clock = contracts, clock
        self._repository = WorkingCopyRepository()
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_ui_audit_registry()))

    def checkpoint_working_copy(self, request, *, owner_profile_id):
        require_uuid4(owner_profile_id)
        request = closed(request, {'command_id', 'key', 'expected_generation', 'payload'})
        command = require_uuid4(request['command_id'])
        expected = integer(request['expected_generation'])
        # Construct replay authority before inspecting mutable registry or rows.
        envelope = CommandEnvelope(command, 'CheckpointWorkingCopy', 'ui_working_copy', None,
            {'owner_profile_id': owner_profile_id, **{key: value for key, value in request.items() if key != 'command_id'}})
        replay = self._boundary.lookup_replay(envelope)
        if replay is not None:
            return replay.response
        key, contract = self._contracts.key(request['key'])
        payload, encoded = self._contracts.payload(key, request['payload'])
        content_hash = hashlib.sha256(encoded).hexdigest()
        dirty_json = canonical_json_bytes(payload['dirty_paths']).decode('utf8')

        def prepare(writer):
            # Static release registry, still checked at the authoritative boundary.
            self._contracts.payload(key, payload)
            now = integer(self._clock())
            prior = self._repository.get_by_key(writer, owner_profile_id, key)
            if (prior is None and expected != 0) or (prior is not None and prior['generation'] != expected):
                raise SomaError('UI_WORKING_COPY_CONFLICT', 'Recovery generation changed; review the current copy')
            if prior is not None and prior['content_hash'] == content_hash and prior['payload_json'].encode('utf8') == encoded and prior['dirty_paths_json'] == dirty_json:
                return PreparedMutation(True, None, None, response_schema='WorkingCopyCheckpointResultV1', response=checkpoint_result(prior))
            if prior is None and self._repository.count_nonexpired(writer, owner_profile_id, now) >= 256:
                raise SomaError('UI_WORKING_COPY_CAPACITY', 'Recovery capacity reached; discard or expire an existing copy')
            identity = new_uuid4() if prior is None else prior['working_copy_id']
            generation = integer(1 if prior is None else prior['generation'] + 1, 1)
            row = dict(key, working_copy_id=identity, owner_profile_id=owner_profile_id,
                draft_contract_id=contract.schema.name, draft_contract_version=contract.schema.version,
                base_revision_token=payload['base_revision_token'], payload_json=encoded.decode('utf8'), dirty_paths_json=dirty_json,
                content_hash=content_hash, generation=generation, created_at_utc=now if prior is None else prior['created_at_utc'],
                updated_at_utc=now, expires_at_utc=integer(now + 604800),
                created_command_id=command if prior is None else prior['created_command_id'], last_checkpoint_command_id=command)

            def apply(inner):
                if prior is None:
                    self._repository.insert(inner, row)
                else:
                    self._repository.update_checkpoint(inner, row, expected)
                return event('ui.working_copy.checkpointed', command_id=command, target_type='ui_working_copy', target_id=identity,
                    owner_profile_id=owner_profile_id, payload={'scope_key': key['scope_key'], 'draft_contract_id': contract.schema.name,
                    'draft_contract_version': contract.schema.version, 'base_revision_fingerprint_sha256': hashlib.sha256(payload['base_revision_token'].encode('utf8')).hexdigest(),
                    'generation': generation, 'payload_byte_count': len(encoded), 'content_hash': content_hash})
            return PreparedMutation(False, 'ui_working_copy', identity, apply,
                response_schema='WorkingCopyCheckpointResultV1', response=checkpoint_result(row))
        return self._boundary.execute(envelope, prepare).response

    def discard_working_copy(self, request, *, owner_profile_id):
        require_uuid4(owner_profile_id)
        request = closed(request, {'command_id', 'working_copy_id', 'expected_generation'})
        command, identity = require_uuid4(request['command_id']), require_uuid4(request['working_copy_id'])
        expected = integer(request['expected_generation'], 1)
        envelope = CommandEnvelope(command, 'DiscardWorkingCopy', 'ui_working_copy', identity,
            {'owner_profile_id': owner_profile_id, 'working_copy_id': identity, 'expected_generation': expected}, base_revisions={'generation': expected})
        def prepare(writer):
            row = self._repository.get(writer, identity)
            if row is None or row['owner_profile_id'] != owner_profile_id:
                raise SomaError('UI_WORKING_COPY_NOT_FOUND', 'Recovery copy is unavailable')
            if row['generation'] != expected:
                raise SomaError('UI_WORKING_COPY_CONFLICT', 'Recovery generation changed; newer intent was preserved')
            def apply(inner):
                self._repository.delete(inner, identity, expected)
                return event('ui.working_copy.discarded', command_id=command, target_type='ui_working_copy', target_id=identity,
                    owner_profile_id=owner_profile_id, payload={'scope_key': row['scope_key'], 'discarded_generation': expected})
            return PreparedMutation(False, 'ui_working_copy', identity, apply, response_schema='DiscardWorkingCopyResponseV1',
                response={'working_copy_id': identity, 'discarded_generation': expected, 'discarded': True})
        return self._boundary.execute(envelope, prepare).response

    def prune_expired_working_copies(self, request):
        request = closed(request, {'command_id', 'batch_limit'})
        command = require_uuid4(request['command_id']); limit = integer(request['batch_limit'], 1, 100)
        envelope = CommandEnvelope(command, 'PruneExpiredWorkingCopies', 'ui_working_copy_batch', command, {'batch_limit': limit})
        def prepare(writer):
            now = integer(self._clock())
            rows = self._repository.list_expired(writer, now, None, limit)
            result = {'deleted_count': 0, 'more_due': False}
            if not rows:
                return PreparedMutation(True, None, None, response_schema='PruneExpiredWorkingCopiesResponseV1', response=result)
            def apply(inner):
                for row in rows:
                    # An unexpected same-UoW refresh must also survive cleanup.
                    current = self._repository.get(inner, row['working_copy_id'])
                    if current is not None and current['generation'] == row['generation'] and current['expires_at_utc'] <= now:
                        self._repository.delete(inner, current['working_copy_id'], current['generation'])
                        result['deleted_count'] += 1
                result['more_due'] = inner.connection.execute('SELECT EXISTS(SELECT 1 FROM ui_working_copies WHERE expires_at_utc<=?)', (now,)).fetchone()[0] == 1
                return event('ui.working_copy.expired_pruned', command_id=command, target_type='ui_working_copy_batch', target_id=command,
                    actor_kind='system', payload=dict(result))
            return PreparedMutation(False, 'ui_working_copy_batch', command, apply,
                response_schema='PruneExpiredWorkingCopiesResponseV1', response_factory=lambda writer: dict(result))
        return self._boundary.execute(envelope, prepare).response
