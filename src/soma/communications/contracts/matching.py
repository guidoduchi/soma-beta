from __future__ import annotations

from soma.foundation.errors import ValidationError

MATCH_RULES = {
    ("COMM_EXACT_IDENTIFIER_V1", 1): "EXACT_IDENTIFIER",
    ("COMM_EXACT_ALIAS_V1", 1): "EXACT_ALIAS",
    ("COMM_REVIEWED_MANUAL_V1", 1): "REVIEWED_MANUAL",
}
ALIASES = frozenset({"SERVICE_REQUEST_LOCAL_ALIAS", "SPARE_REQUEST_ALIAS", "RMA_ALIAS"})


def validate_match_rule(rule_id, version, confidence_basis):
    if (not isinstance(rule_id, str) or type(version) is not int
            or MATCH_RULES.get((rule_id, version)) != confidence_basis):
        raise ValidationError("Communication match rule is not registered for this confidence basis")


def validate_identity_confidence(identity_kind, confidence_basis):
    if ((confidence_basis == "EXACT_IDENTIFIER" and identity_kind in ALIASES)
            or (confidence_basis == "EXACT_ALIAS" and identity_kind not in ALIASES)):
        raise ValidationError("Communication identity kind disagrees with the matching evidence")
