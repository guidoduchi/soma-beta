"""Stable, bounded recovery projections; domain authority is a read-only provider."""
import hashlib

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.ui.contracts import closed, integer, text
from soma.ui.repository import WorkingCopyRepository, record_response


class WorkingCopyQueries:
    def __init__(self, connection_factory, contracts, revision_reader, *, clock=utc_epoch_seconds):
        self._factory, self._contracts, self._revisions, self._clock = connection_factory, contracts, revision_reader, clock
        self._repository = WorkingCopyRepository()

    def _restore(self, snapshot, row):
        record = record_response(row)
        payload, encoded = self._contracts.payload(record['key'], record['payload'])
        if hashlib.sha256(encoded).hexdigest() != record['content_hash']:
            raise IntegrityFailure('Recovery payload does not match its accepted content hash')
        current = None
        try:
            value = self._revisions.current_revision_token(snapshot, row['target_type'], row['target_id'], row['scope_key'])
            if value == 'MISSING':
                freshness = 'TARGET_MISSING'
            elif value == 'INDETERMINATE':
                freshness = 'INDETERMINATE'
            else:
                current = text(value, 256)
                freshness = 'CURRENT' if current == payload['base_revision_token'] else 'STALE'
        except Exception:
            freshness = 'INDETERMINATE'
        return {'record': record, 'freshness': freshness, 'current_revision_token': current,
            'restore_allowed': freshness in {'CURRENT', 'STALE'}, 'requires_conflict_review': freshness == 'STALE'}

    def get_working_copy(self, request, *, owner_profile_id):
        require_uuid4(owner_profile_id)
        identity = require_uuid4(closed(request, {'working_copy_id'})['working_copy_id'])
        with ReadSnapshot(self._factory) as snapshot:
            row = self._repository.get(snapshot, identity)
            if row is None or row['owner_profile_id'] != owner_profile_id or row['expires_at_utc'] <= integer(self._clock()):
                return {'state': 'NOT_FOUND', 'restore': None}
            return {'state': 'FOUND', 'restore': self._restore(snapshot, row)}

    def list_restore_candidates(self, request, *, owner_profile_id):
        require_uuid4(owner_profile_id)
        if not isinstance(request, dict) or set(request) - {'target_type', 'target_id', 'cursor', 'limit'}:
            raise SomaError('INVALID_CURSOR', 'Recovery query has unknown fields')
        target_type, target_id = request.get('target_type'), request.get('target_id')
        if target_type is not None:
            text(target_type, 64)
        if target_id is not None:
            text(target_id, 128)
        limit = integer(request.get('limit', 50), 1, 50)
        fingerprint = sha256_canonical_json({'owner_profile_id': owner_profile_id, 'target_type': target_type, 'target_id': target_id})
        cursor, key = request.get('cursor'), None
        if cursor is not None:
            try:
                closed(cursor, {'version', 'query_id', 'sort_registry_id', 'last_key_tuple', 'filter_fingerprint', 'null_order'})
                if (type(cursor['version']) is not int or cursor['version'] != 1 or cursor['query_id'] != 'ListWorkingCopyRestoreCandidates'
                        or cursor['sort_registry_id'] != 'UI_WORKING_COPY_UPDATED_V1' or cursor['filter_fingerprint'] != fingerprint or cursor['null_order'] != 'none'):
                    raise ValueError()
                key = cursor['last_key_tuple']
                if not isinstance(key, list) or len(key) != 2:
                    raise ValueError()
                integer(key[0]); require_uuid4(key[1])
            except (ValueError, SomaError):
                raise SomaError('INVALID_CURSOR', 'Recovery cursor is stale or invalid') from None
        with ReadSnapshot(self._factory) as snapshot:
            rows = self._repository.list_restore_candidates(snapshot, owner_profile_id, integer(self._clock()), target_type, target_id, key, limit)
            page = rows[:limit]
            items = [self._restore(snapshot, row) for row in page]
        continuation = None
        if len(rows) > limit:
            last = page[-1]
            continuation = {'version': 1, 'query_id': 'ListWorkingCopyRestoreCandidates', 'sort_registry_id': 'UI_WORKING_COPY_UPDATED_V1',
                'last_key_tuple': [last['updated_at_utc'], last['working_copy_id']], 'filter_fingerprint': fingerprint, 'null_order': 'none'}
        return {'items': items, 'next_cursor': continuation}
