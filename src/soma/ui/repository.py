"""Bounded UI recovery SQL. Caller owns snapshots, validation and transactions."""
from soma.foundation.errors import IntegrityFailure
from soma.foundation.strict_json import loads_canonical_json

COLUMNS = ('working_copy_id', 'owner_profile_id', 'target_type', 'target_id', 'scope_key',
    'draft_contract_id', 'draft_contract_version', 'base_revision_token', 'payload_json', 'dirty_paths_json',
    'content_hash', 'generation', 'created_at_utc', 'updated_at_utc', 'expires_at_utc', 'created_command_id', 'last_checkpoint_command_id')


def _row(row):
    return None if row is None else dict(zip(COLUMNS, row))


class WorkingCopyRepository:
    def get_by_key(self, reader, owner_profile_id, key):
        return _row(reader.connection.execute('SELECT ' + ','.join(COLUMNS) +
            ' FROM ui_working_copies WHERE owner_profile_id=? AND target_type=? AND target_id=? AND scope_key=?',
            (owner_profile_id, key['target_type'], key['target_id'], key['scope_key'])).fetchone())

    def get(self, reader, working_copy_id):
        return _row(reader.connection.execute('SELECT ' + ','.join(COLUMNS) + ' FROM ui_working_copies WHERE working_copy_id=?', (working_copy_id,)).fetchone())

    def count_nonexpired(self, reader, owner_profile_id, now_utc):
        # Capacity is installation-wide; owner identity is checked by the caller.
        return reader.connection.execute('SELECT count(*) FROM ui_working_copies WHERE expires_at_utc>?', (now_utc,)).fetchone()[0]

    def insert(self, uow, row):
        uow.connection.execute('INSERT INTO ui_working_copies(' + ','.join(COLUMNS) + ') VALUES(' + ','.join('?' for _ in COLUMNS) + ')', tuple(row[key] for key in COLUMNS))

    def update_checkpoint(self, uow, row, expected_generation):
        mutable = COLUMNS[5:12] + COLUMNS[13:15] + ('last_checkpoint_command_id',)
        result = uow.connection.execute('UPDATE ui_working_copies SET ' + ','.join(key + '=?' for key in mutable)
            + ' WHERE working_copy_id=? AND generation=?', (*[row[key] for key in mutable], row['working_copy_id'], expected_generation))
        if result.rowcount != 1:
            raise IntegrityFailure('Working-copy generation changed inside its writer')

    def delete(self, uow, working_copy_id, expected_generation):
        result = uow.connection.execute('DELETE FROM ui_working_copies WHERE working_copy_id=? AND generation=?', (working_copy_id, expected_generation))
        if result.rowcount != 1:
            raise IntegrityFailure('Working-copy deletion lost its exact generation')

    def list_restore_candidates(self, reader, owner_profile_id, now_utc, target_type, target_id, cursor, limit):
        conditions, values = ['owner_profile_id=?', 'expires_at_utc>?'], [owner_profile_id, now_utc]
        for key, value in (('target_type', target_type), ('target_id', target_id)):
            if value is not None:
                conditions.append(key + '=?'); values.append(value)
        if cursor is not None:
            conditions.append('(updated_at_utc,working_copy_id)<(?,?)'); values.extend(cursor)
        rows = reader.connection.execute('SELECT ' + ','.join(COLUMNS) + ' FROM ui_working_copies WHERE '
            + ' AND '.join(conditions) + ' ORDER BY updated_at_utc DESC,working_copy_id DESC LIMIT ?', (*values, limit + 1)).fetchall()
        return [_row(row) for row in rows]

    def list_expired(self, reader, now_utc, cursor, limit):
        seek, values = '', [now_utc]
        if cursor is not None:
            seek = ' AND (expires_at_utc,working_copy_id)>(?,?)'; values.extend(cursor)
        return [_row(row) for row in reader.connection.execute('SELECT ' + ','.join(COLUMNS) +
            ' FROM ui_working_copies WHERE expires_at_utc<=?' + seek + ' ORDER BY expires_at_utc,working_copy_id LIMIT ?', (*values, limit))]


def record_response(row):
    payload = loads_canonical_json(row['payload_json'], max_bytes=262144, max_depth=32, max_collection_items=262144)
    if (any(payload.get(key) != row[key] for key in ('draft_contract_id', 'draft_contract_version', 'base_revision_token'))
            or payload.get('dirty_paths') != loads_canonical_json(row['dirty_paths_json'], max_bytes=262144, max_depth=32, max_collection_items=262144)):
        raise IntegrityFailure('Recovery metadata disagrees with its captured payload')
    return {'working_copy_id': row['working_copy_id'], 'owner_profile_id': row['owner_profile_id'],
        'key': {key: row[key] for key in ('target_type', 'target_id', 'scope_key')}, 'generation': row['generation'],
        'payload': payload, 'created_at_utc': row['created_at_utc'], 'updated_at_utc': row['updated_at_utc'],
        'expires_at_utc': row['expires_at_utc'], 'content_hash': row['content_hash']}
