"""Closed, immutable edit-surface registrations, supplied only at composition."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.strict_json import ObjectContract, canonical_json_bytes_bounded


def closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValidationError('UI request contains missing or unknown fields')
    return value


def text(value, maximum, *, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or '\x00' in value:
        raise ValidationError('UI identity/text exceeds its contract')
    try:
        value.encode('utf8', errors='strict')
    except UnicodeError:
        raise ValidationError('UI text is not valid UTF-8') from None
    return value


def integer(value, minimum=0, maximum=(1 << 63) - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError('UI integer exceeds its contract')
    return value


@dataclass(frozen=True, slots=True)
class WorkingCopyDraftContract:
    target_type: str
    scope_key: str
    schema: ObjectContract
    allowed_dirty_paths: frozenset[str]
    validate_fields: Callable[[dict], None]
    validate_target_id: Callable[[str], object]


class WorkingCopyContractRegistry:
    """No runtime register/plugin entry point. Unknown edit surfaces fail closed."""
    def __init__(self, registrations=()):
        by_key, by_contract = {}, {}
        for contract in registrations:
            if not isinstance(contract, WorkingCopyDraftContract):
                raise ValidationError('UI recovery requires static typed contracts')
            if contract.schema.unknown_field_policy != 'reject' or not callable(contract.validate_fields) or not callable(contract.validate_target_id):
                raise ValidationError('UI recovery requires closed schemas and static validation')
            key = (text(contract.target_type, 64), text(contract.scope_key, 96))
            identity = (text(contract.schema.name, 96), integer(contract.schema.version, 1))
            if key in by_key or identity in by_contract:
                raise ValidationError('UI draft contract authority is duplicated')
            if not isinstance(contract.allowed_dirty_paths, frozenset) or any(
                    not path.startswith('/') or len(path) > 512 for path in contract.allowed_dirty_paths):
                raise ValidationError('UI dirty paths require a closed JSON-pointer registry')
            by_key[key], by_contract[identity] = contract, contract
        self._keys, self._contracts = MappingProxyType(by_key), MappingProxyType(by_contract)

    def get(self, contract_id, version):
        if not isinstance(contract_id, str) or type(version) is not int:
            return None
        return self._contracts.get((contract_id, version))

    def key(self, value):
        value = closed(value, {'target_type', 'target_id', 'scope_key'})
        target, scope = text(value['target_type'], 64), text(value['scope_key'], 96)
        contract = self._keys.get((target, scope))
        if contract is None:
            raise SomaError('UI_WORKING_COPY_CONTRACT_INVALID', 'This edit surface has no registered recovery contract')
        identity = text(value['target_id'], 128)
        contract.validate_target_id(identity)
        return dict(value), contract

    def payload(self, key, value):
        _, contract = self.key(key)
        value = closed(value, {'draft_contract_id', 'draft_contract_version', 'base_revision_token', 'draft', 'dirty_paths'})
        if (value['draft_contract_id'], value['draft_contract_version']) != (contract.schema.name, contract.schema.version) or type(value['draft_contract_version']) is not int:
            raise SomaError('UI_WORKING_COPY_CONTRACT_INVALID', 'Recovery contract does not own this edit surface')
        text(value['base_revision_token'], 256)
        try:
            canonical_json_bytes_bounded(value, max_bytes=262144, max_depth=32, max_collection_items=262144)
        except ValidationError:
            raise SomaError('UI_WORKING_COPY_TOO_LARGE', 'Recovery payload exceeds its canonical bound') from None
        dirty = value['dirty_paths']
        if (not isinstance(dirty, list) or any(not isinstance(path, str) for path in dirty)
                or dirty != sorted(set(dirty)) or not set(dirty) <= contract.allowed_dirty_paths):
            raise SomaError('UI_WORKING_COPY_CONTRACT_INVALID', 'Recovery dirty paths are not registered')
        try:
            draft = contract.schema.validate(value['draft'])
            contract.validate_fields(draft)
        except ValidationError:
            raise SomaError('UI_WORKING_COPY_CONTRACT_INVALID', 'Recovery draft does not match its closed contract') from None
        normalized = dict(value, draft=draft)
        try:
            encoded = canonical_json_bytes_bounded(normalized, max_bytes=262144, max_depth=32, max_collection_items=262144)
        except ValidationError:
            raise SomaError('UI_WORKING_COPY_TOO_LARGE', 'Recovery payload exceeds its canonical bound') from None
        return normalized, encoded

    def validate(self, contract_id, version, draft_json, dirty_paths):
        contract = self.get(contract_id, version)
        if contract is None:
            return 'INVALID'
        try:
            contract.schema.validate(draft_json)
            contract.validate_fields(draft_json)
            if not isinstance(dirty_paths, list) or dirty_paths != sorted(set(dirty_paths)) or not set(dirty_paths) <= contract.allowed_dirty_paths:
                return 'INVALID'
            return 'VALID'
        except (ValidationError, TypeError):
            return 'INVALID'
