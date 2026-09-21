from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Literal

from soma.foundation.errors import SomaError
from soma.foundation.strict_json import sha256_canonical_json

from .matching import PROFILE_ID
from .validation import validate_account_code

ProposedAction = Literal["CONFIRM_SHARED_CLAIM", "REASSIGN_CLAIM"]


@dataclass(frozen=True, slots=True)
class AccountCodeReviewSnapshot:
    proposed_action: ProposedAction
    target_customer_org_id: str
    from_customer_org_id: str | None
    normalized_code_key: str
    claimant_count: int
    customer_reference_generation: int
    review_snapshot_hash: str
    claimant_customer_org_ids: tuple[str, ...]
    claimant_exact_count: int
    continuation_after_customer_org_id: str | None


def _customer_state(connection: Any, customer_org_id: str) -> tuple[int, str | None]:
    row = connection.execute(
        "SELECT revision, lifecycle_state FROM customer_organizations WHERE customer_org_id = ?",
        (customer_org_id,),
    ).fetchone()
    if row is None or str(row[1]) != "active":
        raise SomaError("REFERENCE_NOT_ACTIVE", "Customer Organization is missing or archived")
    claim = connection.execute(
        "SELECT match_key FROM customer_org_identifiers "
        "WHERE customer_org_id = ? AND identifier_type = 'customer_account_code' "
        "AND lifecycle_state = 'active'",
        (customer_org_id,),
    ).fetchone()
    return int(row[0]), None if claim is None else str(claim[0])


def _review_document(
    connection: Any,
    *,
    normalized_code_key: str,
    proposed_action: ProposedAction,
    target_customer_org_id: str,
    from_customer_org_id: str | None,
) -> tuple[dict[str, object], int, int]:
    metadata = connection.execute(
        "SELECT matching_profile_id, customer_reference_generation FROM reference_metadata WHERE singleton_guard = 1"
    ).fetchone()
    if metadata is None or str(metadata[0]) != PROFILE_ID:
        raise SomaError("MATCHING_PROFILE_MISMATCH", "stored matching profile is unsupported")
    generation = int(metadata[1])
    target_revision, target_current_key = _customer_state(connection, target_customer_org_id)

    source_payload: dict[str, object] | None = None
    if proposed_action == "REASSIGN_CLAIM":
        if from_customer_org_id is None or from_customer_org_id == target_customer_org_id:
            raise SomaError("REVIEW_CONTEXT_INVALID", "reassignment requires a distinct source Customer")
        source_revision, source_current_key = _customer_state(connection, from_customer_org_id)
        if source_current_key != normalized_code_key:
            raise SomaError("REVIEW_CONTEXT_INVALID", "source Customer no longer owns the reviewed Account Code")
        source_payload = {
            "customer_org_id": from_customer_org_id,
            "revision": source_revision,
        }
    elif proposed_action != "CONFIRM_SHARED_CLAIM":
        raise SomaError("REVIEW_CONTEXT_INVALID", "unsupported Account Code review action")

    claimant_count = int(
        connection.execute(
            "SELECT count(*) FROM customer_org_identifiers "
            "WHERE identifier_type = 'customer_account_code' AND match_key = ? AND lifecycle_state = 'active'",
            (normalized_code_key,),
        ).fetchone()[0]
    )
    document: dict[str, object] = {
        "schema": "REVIEW_ACCOUNT_CODE_V1",
        "matching_profile_id": PROFILE_ID,
        "customer_reference_generation": generation,
        "normalized_code_key": normalized_code_key,
        "proposed_action": proposed_action,
        "target": {
            "customer_org_id": target_customer_org_id,
            "revision": target_revision,
            "current_code_key": target_current_key,
        },
        "source": source_payload,
        "claimant_count": claimant_count,
    }
    return document, generation, claimant_count


def preview_account_code_review(
    connection: Any,
    *,
    raw_account_code: str,
    proposed_action: ProposedAction,
    target_customer_org_id: str,
    from_customer_org_id: str | None = None,
    page_size: int = 50,
    after_customer_org_id: str | None = None,
) -> AccountCodeReviewSnapshot:
    if page_size < 1 or page_size > 200:
        raise SomaError("PAGE_SIZE_INVALID", "review claimant page size must be between 1 and 200")
    _, match_key = validate_account_code(raw_account_code)
    document, generation, claimant_count = _review_document(
        connection,
        normalized_code_key=match_key,
        proposed_action=proposed_action,
        target_customer_org_id=target_customer_org_id,
        from_customer_org_id=from_customer_org_id,
    )
    params: list[object] = [match_key]
    after_sql = ""
    if after_customer_org_id is not None:
        after_sql = " AND customer_org_id > ?"
        params.append(after_customer_org_id)
    params.append(page_size + 1)
    rows = connection.execute(
        "SELECT customer_org_id FROM customer_org_identifiers "
        "WHERE identifier_type = 'customer_account_code' AND match_key = ? AND lifecycle_state = 'active'"
        + after_sql
        + " ORDER BY customer_org_id LIMIT ?",
        tuple(params),
    ).fetchall()
    ids = tuple(str(row[0]) for row in rows[:page_size])
    continuation = ids[-1] if len(rows) > page_size and ids else None
    return AccountCodeReviewSnapshot(
        proposed_action=proposed_action,
        target_customer_org_id=target_customer_org_id,
        from_customer_org_id=from_customer_org_id,
        normalized_code_key=match_key,
        claimant_count=claimant_count,
        customer_reference_generation=generation,
        review_snapshot_hash=sha256_canonical_json(document),
        claimant_customer_org_ids=ids,
        claimant_exact_count=claimant_count,
        continuation_after_customer_org_id=continuation,
    )


def validate_account_code_review(
    connection: Any,
    *,
    raw_account_code: str,
    proposed_action: ProposedAction,
    target_customer_org_id: str,
    review_snapshot_hash: str,
    from_customer_org_id: str | None = None,
) -> tuple[str, int]:
    _, match_key = validate_account_code(raw_account_code)
    document, _, claimant_count = _review_document(
        connection,
        normalized_code_key=match_key,
        proposed_action=proposed_action,
        target_customer_org_id=target_customer_org_id,
        from_customer_org_id=from_customer_org_id,
    )
    current_hash = sha256_canonical_json(document)
    if not hmac.compare_digest(current_hash, review_snapshot_hash):
        raise SomaError("REVIEW_CONTEXT_STALE", "Customer Account Code review context changed")
    if proposed_action == "CONFIRM_SHARED_CLAIM":
        different_count = int(
            connection.execute(
                "SELECT count(*) FROM customer_org_identifiers "
                "WHERE identifier_type = 'customer_account_code' AND match_key = ? "
                "AND lifecycle_state = 'active' AND customer_org_id <> ?",
                (match_key, target_customer_org_id),
            ).fetchone()[0]
        )
        if different_count < 1:
            raise SomaError("REVIEW_CONTEXT_INVALID", "shared-claim confirmation requires another claimant")
    return match_key, claimant_count
