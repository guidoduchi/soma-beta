from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from soma.foundation.errors import SomaError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.reference.domain.matching import PROFILE_ID, normalize_match_key

CandidateState = Literal["UNRESOLVED", "UNIQUE_CANDIDATE", "AMBIGUOUS"]


@dataclass(frozen=True, slots=True)
class CandidateResult:
    state: CandidateState
    explanation: str
    candidate_count: int
    candidate_ids: tuple[str, ...]
    continuation_after_id: str | None


class ReferenceMatchingQueries:
    """Pure candidate queries. Selection/adoption remains an owning command concern."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _require_profile(connection: Any) -> None:
        row = connection.execute(
            "SELECT matching_profile_id FROM reference_metadata WHERE singleton=1"
        ).fetchone()
        if row is None or str(row[0]) != PROFILE_ID:
            raise SomaError(
                "MATCH_PROFILE_UNSUPPORTED",
                "stored reference matching profile is not supported by this build",
            )

    @staticmethod
    def _page(
        candidate_ids: set[str], *, after_candidate_id: str | None, limit: int
    ) -> tuple[tuple[str, ...], str | None]:
        if type(limit) is not int or limit < 1 or limit > 200:
            raise SomaError("FIELD_BOUND_EXCEEDED", "candidate page limit must be in 1..200")
        ordered = sorted(candidate_ids)
        if after_candidate_id is not None:
            ordered = [candidate_id for candidate_id in ordered if candidate_id > after_candidate_id]
        visible = tuple(ordered[:limit])
        continuation = visible[-1] if len(ordered) > limit and visible else None
        return visible, continuation

    def match_customer_organization(
        self,
        *,
        raw_account_code: str | None = None,
        raw_name: str | None = None,
        after_candidate_id: str | None = None,
        limit: int = 50,
    ) -> CandidateResult:
        if raw_account_code is None and raw_name is None:
            raise SomaError("MATCH_INPUT_INVALID", "at least one Customer match value is required")
        code_key = (
            None
            if raw_account_code is None
            else normalize_match_key(raw_account_code, raw_max_utf8_bytes=512)
        )
        name_key = (
            None
            if raw_name is None
            else normalize_match_key(raw_name, raw_max_utf8_bytes=1024)
        )

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            self._require_profile(connection)
            code_ids: set[str] = set()
            name_ids: set[str] = set()
            if code_key is not None:
                code_ids = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT i.customer_org_id FROM customer_org_identifiers i "
                        "JOIN customer_organizations c ON c.customer_org_id=i.customer_org_id "
                        "WHERE i.identifier_type='customer_account_code' AND i.match_key=? "
                        "AND i.lifecycle_state='active' AND c.lifecycle_state='active'",
                        (code_key,),
                    ).fetchall()
                }
            if name_key is not None:
                name_ids = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT customer_org_id FROM customer_organizations "
                        "WHERE lifecycle_state='active' AND name_match_key=?",
                        (name_key,),
                    ).fetchall()
                }

        if code_key is not None and len(code_ids) == 1:
            sole_code = next(iter(code_ids))
            differing_name = name_ids - {sole_code}
            if differing_name:
                candidates = code_ids | name_ids
                explanation = "ACCOUNT_CODE_NAME_CONFLICT"
            else:
                candidates = code_ids
                explanation = "ACCOUNT_CODE_MATCH"
        elif code_key is not None and len(code_ids) > 1:
            candidates = code_ids | name_ids
            explanation = "ACCOUNT_CODE_MULTIPLE_CLAIMS"
        elif code_key is not None:
            candidates = name_ids
            if len(name_ids) == 1:
                explanation = "ACCOUNT_CODE_UNRESOLVED_NAME_CANDIDATE"
            elif len(name_ids) > 1:
                explanation = "ACCOUNT_CODE_UNRESOLVED_NAME_AMBIGUOUS"
            else:
                explanation = "NO_CANONICAL_CANDIDATE"
        else:
            candidates = name_ids
            explanation = "NAME_MATCH" if candidates else "NO_CANONICAL_CANDIDATE"

        visible, continuation = self._page(
            candidates, after_candidate_id=after_candidate_id, limit=limit
        )
        count = len(candidates)
        state: CandidateState = (
            "UNRESOLVED" if count == 0 else "UNIQUE_CANDIDATE" if count == 1 else "AMBIGUOUS"
        )
        return CandidateResult(state, explanation, count, visible, continuation)

    def match_contact(
        self,
        *,
        scope: str,
        raw_name: str | None = None,
        raw_email: str | None = None,
        after_candidate_id: str | None = None,
        limit: int = 50,
    ) -> CandidateResult:
        if not isinstance(scope, str) or not scope:
            raise SomaError("MATCH_INPUT_INVALID", "Contact match scope is required")
        if raw_name is None and raw_email is None:
            raise SomaError("MATCH_INPUT_INVALID", "at least one Contact match value is required")
        name_key = (
            None
            if raw_name is None
            else normalize_match_key(raw_name, raw_max_utf8_bytes=1024)
        )
        email_key = (
            None
            if raw_email is None
            else normalize_match_key(raw_email, raw_max_utf8_bytes=2048)
        )

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            self._require_profile(connection)
            if scope != "UNBOUND":
                customer = connection.execute(
                    "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
                    (scope,),
                ).fetchone()
                if customer is None:
                    raise SomaError("NOT_FOUND", "Customer Organization scope does not exist")
                if str(customer[0]) != "active":
                    raise SomaError("CUSTOMER_ORG_INACTIVE", "Customer Organization scope is archived")

            where_scope = (
                "NOT EXISTS (SELECT 1 FROM contact_affiliations a WHERE a.contact_id=c.contact_id AND a.is_current=1)"
                if scope == "UNBOUND"
                else "EXISTS (SELECT 1 FROM contact_affiliations a WHERE a.contact_id=c.contact_id "
                "AND a.is_current=1 AND a.customer_org_id=?)"
            )
            scope_params: tuple[object, ...] = () if scope == "UNBOUND" else (scope,)
            candidates: set[str] = set()
            if name_key is not None:
                rows = connection.execute(
                    "SELECT c.contact_id FROM contacts c WHERE c.lifecycle_state='active' "
                    f"AND c.name_match_key=? AND {where_scope}",
                    (name_key, *scope_params),
                ).fetchall()
                candidates.update(str(row[0]) for row in rows)
            if email_key is not None:
                rows = connection.execute(
                    "SELECT DISTINCT c.contact_id FROM contacts c "
                    "JOIN contact_channels ch ON ch.contact_id=c.contact_id "
                    "WHERE c.lifecycle_state='active' AND ch.lifecycle_state='active' "
                    "AND ch.channel_kind='email' AND ch.match_key=? AND "
                    f"{where_scope}",
                    (email_key, *scope_params),
                ).fetchall()
                candidates.update(str(row[0]) for row in rows)

        visible, continuation = self._page(
            candidates, after_candidate_id=after_candidate_id, limit=limit
        )
        count = len(candidates)
        state: CandidateState = (
            "UNRESOLVED" if count == 0 else "UNIQUE_CANDIDATE" if count == 1 else "AMBIGUOUS"
        )
        return CandidateResult(
            state,
            "EXACT_SCOPED_REFERENCE_MATCH" if count else "NO_CANONICAL_CANDIDATE",
            count,
            visible,
            continuation,
        )
