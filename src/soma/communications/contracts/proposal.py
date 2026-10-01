from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.strict_json import canonical_json_bytes_bounded, loads_canonical_json
from .matching import validate_identity_confidence, validate_match_rule

_REGISTRY = json.loads(files(__package__).joinpath("registry.json").read_text(encoding="utf-8"))["proposal_contracts"]
_CONTRACTS = {(x["id"], x["version"]): x for x in _REGISTRY["contracts"]}
_DEFINITIONS = _REGISTRY["payload_schema"]["$defs"]


def _check(schema: dict, value: Any) -> None:
    if "$ref" in schema:
        _check(_DEFINITIONS[schema["$ref"].rsplit("/", 1)[1]], value)
        return
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ValidationError("Communication proposal schema identity is invalid")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError("Communication proposal enum is invalid")
    kinds = schema.get("type", [])
    if isinstance(kinds, str):
        kinds = [kinds]
    actual = "null" if value is None else "boolean" if type(value) is bool else "integer" if type(value) is int else "string" if isinstance(value, str) else "object" if isinstance(value, dict) else "unsupported"
    if kinds and actual not in kinds:
        raise ValidationError("Communication proposal value has the wrong type")
    if actual == "object" and "properties" in schema:
        props = schema["properties"]
        if set(schema.get("required", ())) - value.keys() or (not schema.get("additionalProperties", True) and value.keys() - props.keys()):
            raise ValidationError("Communication proposal has missing or unknown fields")
        for key, item in value.items():
            if key in props:
                _check(props[key], item)
    if actual == "string":
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value)):
            raise ValidationError("Communication proposal text exceeds its bounds")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ValidationError("Communication proposal identity/fingerprint is invalid")
    if actual == "integer" and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
        raise ValidationError("Communication proposal integer exceeds its bounds")
    for condition in schema.get("allOf", ()):
        try:
            _check(condition["if"], value)
        except ValidationError:
            continue
        _check(condition["then"], value)


@dataclass(frozen=True, slots=True)
class ValidatedProposalPayload:
    contract_id: str
    contract_version: int
    target_type: str
    owner_packet: str
    canonical_json: str

    def to_value(self) -> dict:
        return loads_canonical_json(self.canonical_json, max_bytes=4096, max_depth=4, max_collection_items=32)


class CommunicationProposalContractRegistry:
    """Static release registry. Messages and runtime callers cannot register kinds."""

    def owner_for(self, contract_id: str, contract_version: int) -> str:
        return self._resolve(contract_id, contract_version)["owner"]

    def is_link_contract(self, contract_id: str, contract_version: int) -> bool:
        return self._resolve(contract_id, contract_version)["is_link_contract"]

    @staticmethod
    def _resolve(contract_id: str, version: int) -> dict:
        if not isinstance(contract_id, str) or type(version) is not int:
            raise ValidationError("Communication proposal contract identity is invalid")
        try:
            return _CONTRACTS[(contract_id, version)]
        except KeyError as exc:
            raise ValidationError("Communication proposal contract/version is unregistered") from exc

    def validate(self, contract_id: str, contract_version: int, target_type: str, payload: Any) -> ValidatedProposalPayload:
        contract = self._resolve(contract_id, contract_version)
        if target_type not in contract["target_types"]:
            raise ValidationError("Communication proposal target is not owned by this contract")
        encoded = canonical_json_bytes_bounded(payload, max_bytes=4096, max_depth=4, max_collection_items=32)
        normalized = loads_canonical_json(encoded.decode("utf-8"), max_bytes=4096, max_depth=4, max_collection_items=32)
        _check(_DEFINITIONS[contract["payload_definition"]], normalized)
        if contract["is_link_contract"]:
            validate_match_rule(normalized["match_rule_id"], normalized["match_rule_version"], normalized["confidence_basis"])
            validate_identity_confidence(normalized["matched_identity_kind"], normalized["confidence_basis"])
        if "facts" in normalized and "reason_code" in normalized["facts"]:
            reason = normalized["facts"]["reason_code"]
            if reason is not None and (len(reason.encode("utf-8")) > 384 or reason != reason.strip() or any(x in reason for x in ("\x00", "\r", "\n"))):
                raise ValidationError("Communication warehouse reason is not a normalized bounded code")
        return ValidatedProposalPayload(contract_id, contract_version, target_type, contract["owner"], encoded.decode("utf-8"))
