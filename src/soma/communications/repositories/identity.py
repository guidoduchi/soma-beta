from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.identifiers import require_uuid4

from soma.communications.domain.communication import CanonicalMessageIdentity


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    disposition: str  # NEW, REUSE, COLLISION_REVIEW
    communication_id: str | None = None


def resolve_identity(reader, source_scope_id: str, identity: CanonicalMessageIdentity,
                     *, independently_distinct_source_item: bool = False) -> IdentityResolution:
    """Read-only candidate resolution, repeated inside the commit writer UoW.

    Digests never authorize identity reuse on their own. LIMIT 2 detects
    ambiguity without materializing a collision set or exposing its content.
    """
    require_uuid4(source_scope_id)
    if type(independently_distinct_source_item) is not bool:
        raise TypeError("Distinct-source evidence must be an exact boolean")
    if identity.provider_digest is not None:
        assignment = reader.connection.execute(
            "SELECT a.communication_id FROM communication_identity_alias_assignments s "
            "JOIN communication_identity_aliases a USING(identity_alias_id) WHERE s.source_scope_id=? "
            "AND s.provider_identity_kind=? AND s.provider_identity_digest=? AND a.alias_evidence_bytes=? "
            "ORDER BY s.assignment_revision DESC LIMIT 1",
            (source_scope_id, identity.provider_kind, identity.provider_digest, identity.provider_bytes),
        ).fetchone()
        if assignment is not None:
            return IdentityResolution("REUSE", assignment[0])
        aliases = reader.connection.execute(
            "SELECT DISTINCT a.communication_id FROM communication_identity_aliases a JOIN communications c USING(communication_id) "
            "WHERE c.source_scope_id=? AND a.alias_kind=? AND a.alias_digest=? AND a.normalization_version=1 AND a.alias_evidence_bytes=? LIMIT 2",
            (source_scope_id, identity.provider_kind, identity.provider_digest, identity.provider_bytes),
        ).fetchall()
        if aliases:
            # An explicit reviewed alias is stronger authority than an earlier
            # unreviewed duplicate candidate. Multiple reviewed owners still
            # fail closed rather than selecting an arbitrary UUID.
            return IdentityResolution("REUSE", aliases[0][0]) if len(aliases) == 1 else IdentityResolution("COLLISION_REVIEW")
        rows = reader.connection.execute(
            "SELECT communication_id,provider_identity_bytes,identity_state FROM communications "
            "WHERE source_scope_id=? AND provider_identity_kind=? AND provider_identity_digest=? LIMIT 2",
            (source_scope_id, identity.provider_kind, identity.provider_digest),
        ).fetchall()
        if rows:
            # Exact stable origin evidence can identify an already retained
            # review candidate too. Reuse preserves its collision state/holds;
            # it does not consolidate the separate fallback candidate or grant
            # automatic linking. Multiple owners/digest-only hits still fail.
            if len(rows) == 1 and rows[0][1] == identity.provider_bytes and rows[0][2] in {"PROVIDER_STABLE", "IDENTITY_COLLISION"}:
                return IdentityResolution("REUSE", rows[0][0])
            return IdentityResolution("COLLISION_REVIEW")
        # A new stable identity can be a later alias of fallback evidence.
        # That attachment requires explicit reviewed reconciliation.
    rows = reader.connection.execute(
        "SELECT communication_id,fallback_canonical_json,identity_state FROM communications "
        "WHERE source_scope_id=? AND fallback_version=? AND fallback_digest=? LIMIT 2",
        (source_scope_id, identity.fallback_version, identity.fallback_digest),
    ).fetchall()
    if not rows:
        return IdentityResolution("NEW")
    if (identity.provider_digest is None and not independently_distinct_source_item and len(rows) == 1
            and rows[0][1] == identity.fallback_canonical_json and rows[0][2] == "FALLBACK"):
        return IdentityResolution("REUSE", rows[0][0])
    return IdentityResolution("COLLISION_REVIEW")
