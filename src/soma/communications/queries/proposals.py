from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import loads_canonical_json

from soma.communications.contracts.common import TARGET_TYPES, fingerprint, integer
from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.contracts.queries import cursor_key, next_cursor
from soma.communications.domain.proposals import proposal_fingerprint

QUERY = "ListCommunicationProposals"
STATES = frozenset({"PENDING", "DEFERRED", "ACCEPTED", "REJECTED", "SUPERSEDED"})


def list_proposals_in_reader(reader, request, registry):
    if not isinstance(request, dict) or set(request) - {"state", "target_type", "target_id", "cursor", "limit"}:
        raise ValidationError("Communication proposal query has unknown fields")
    filters = {name: request.get(name) for name in ("state", "target_type", "target_id")}
    for name, allowed in (("state", STATES), ("target_type", TARGET_TYPES)):
        if filters[name] is not None and (not isinstance(filters[name], str) or filters[name] not in allowed):
            raise ValidationError("Communication proposal query filter is invalid")
    if filters["target_id"] is not None:
        require_uuid4(filters["target_id"])
    limit = integer(request.get("limit", 50), minimum=1, maximum=100)
    key = cursor_key(request.get("cursor"), query=QUERY, filters=filters, null_order="none", key_length=2)
    conditions, values = [], []
    for name, value in filters.items():
        if value is not None:
            conditions.append(f"p.{name}=?")
            values.append(value)
    if key is not None:
        integer(key[0])
        require_uuid4(key[1])
        conditions.append("(p.created_at_utc,p.communication_proposal_id)<(?,?)")
        values.extend(key)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = reader.connection.execute(
        "SELECT p.communication_proposal_id,p.revision,p.communication_id,c.source_scope_id,p.target_type,p.target_id,"
        "p.target_revision,p.proposal_contract_id,p.proposal_contract_version,p.payload_json,p.source_fingerprint,"
        "p.proposal_fingerprint,p.created_at_utc FROM communication_proposals p JOIN communications c "
        "ON c.communication_id=p.communication_id" + where +
        " ORDER BY p.created_at_utc DESC,p.communication_proposal_id DESC LIMIT ?", (*values, limit + 1),
    ).fetchall()
    page = rows[:limit]
    items = []
    for row in page:
        try:
            parsed = loads_canonical_json(row[9], max_bytes=4096, max_depth=4, max_collection_items=32)
            payload = registry.validate(row[7], row[8], row[4], parsed)
            if payload.canonical_json != row[9]:
                raise IntegrityFailure("Communication proposal evidence is noncanonical")
            fingerprint(row[10])
            fingerprint(row[11])
            if proposal_fingerprint(row[10], row[5], row[6], payload) != row[11]:
                raise IntegrityFailure("Communication proposal fingerprint disagrees with immutable evidence")
        except ValidationError:
            raise IntegrityFailure("Stored Communication proposal violates its static contract") from None
        items.append({"proposal_id": row[0], "proposal_revision": row[1], "communication_id": row[2],
                      "source_scope_id": row[3], "target_type": row[4], "target_id": row[5], "target_revision": row[6],
                      "proposal_contract_id": row[7], "proposal_contract_version": row[8], "payload": payload.to_value(),
                      "source_fingerprint": row[10], "proposal_fingerprint": row[11]})
    continuation = None
    if len(rows) > limit:
        last = page[-1]
        continuation = next_cursor(query=QUERY, filters=filters, null_order="none", key=(last[12], last[0]))
    return {"items": items, "next_cursor": continuation}


class ProposalQueries:
    def __init__(self, connection_factory):
        self._factory = connection_factory
        self._registry = CommunicationProposalContractRegistry()

    def list_proposals(self, request):
        with ReadSnapshot(self._factory) as reader:
            return list_proposals_in_reader(reader, request, self._registry)
