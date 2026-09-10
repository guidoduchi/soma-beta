from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from .rfc_branches import RfcBranchQueryService

_HISTORY_REVIEW_SCHEMA = "SOMA_RFC_HIERARCHY_REVIEW_V1"
_HISTORY_UNAVAILABLE_WARNING = "RFC_HISTORY_RISK_PROVIDER_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RfcHierarchyHistoryAuthority:
    status: str
    risk: str | None
    evidence_exact_count: int | None
    provider_fingerprint: str | None
    warning_code: str | None

    def to_response(self) -> dict[str, object]:
        return {
            "status": self.status,
            "risk": self.risk,
            "evidence_exact_count": self.evidence_exact_count,
            "provider_fingerprint": self.provider_fingerprint,
            "warning_code": self.warning_code,
        }


class RfcHistoryRiskProvider(Protocol):
    def hierarchy_history_authority(
        self,
        reader: object,
        rfc_id: str,
    ) -> RfcHierarchyHistoryAuthority | dict[str, object]: ...


class _UnavailableRfcHistoryRiskProvider:
    def hierarchy_history_authority(
        self,
        reader: object,
        rfc_id: str,
    ) -> RfcHierarchyHistoryAuthority:
        del reader, rfc_id
        return RfcHierarchyHistoryAuthority(
            status="INDETERMINATE",
            risk=None,
            evidence_exact_count=None,
            provider_fingerprint=None,
            warning_code=_HISTORY_UNAVAILABLE_WARNING,
        )


def _bounded_warning_code(value: object) -> str:
    if not isinstance(value, str):
        raise IntegrityFailure("RFC hierarchy history warning code is invalid")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise IntegrityFailure("RFC hierarchy history warning code is invalid") from exc
    if not encoded or len(encoded) > 128 or "\x00" in value or "\r" in value or "\n" in value:
        raise IntegrityFailure("RFC hierarchy history warning code is invalid")
    return value


def normalize_history_authority(value: object) -> RfcHierarchyHistoryAuthority:
    if isinstance(value, RfcHierarchyHistoryAuthority):
        raw: dict[str, object] = value.to_response()
    elif isinstance(value, dict):
        if set(value) != {
            "status",
            "risk",
            "evidence_exact_count",
            "provider_fingerprint",
            "warning_code",
        }:
            raise IntegrityFailure("RFC hierarchy history authority fields are invalid")
        raw = dict(value)
    else:
        raise IntegrityFailure("RFC hierarchy history provider returned an invalid authority")

    status = raw["status"]
    risk = raw["risk"]
    count = raw["evidence_exact_count"]
    fingerprint = raw["provider_fingerprint"]
    warning = raw["warning_code"]
    if status == "READY":
        if risk not in {"LOW", "HIGH"} or type(count) is not int or count < 0 or warning is not None:
            raise IntegrityFailure("READY RFC hierarchy history authority is invalid")
        if not isinstance(fingerprint, str):
            raise IntegrityFailure("READY RFC hierarchy history fingerprint is invalid")
        try:
            from soma.tickets.validation import validate_optional_sha256

            validated = validate_optional_sha256(fingerprint, field="history_provider_fingerprint")
        except ValidationError as exc:
            raise IntegrityFailure("READY RFC hierarchy history fingerprint is invalid") from exc
        if validated is None:
            raise IntegrityFailure("READY RFC hierarchy history fingerprint is invalid")
        return RfcHierarchyHistoryAuthority("READY", str(risk), count, validated, None)
    if status == "INDETERMINATE":
        if risk is not None or count is not None or fingerprint is not None:
            raise IntegrityFailure("INDETERMINATE RFC hierarchy history authority is invalid")
        return RfcHierarchyHistoryAuthority(
            "INDETERMINATE",
            None,
            None,
            None,
            _bounded_warning_code(warning),
        )
    raise IntegrityFailure("RFC hierarchy history authority status is invalid")


def hierarchy_review_fingerprint(
    *,
    action: str,
    child_rfc_id: str,
    old_parent_rfc_id: str,
    new_parent_rfc_id: str | None,
    old_edge_id: str,
    old_branch_fingerprint: str,
    new_branch_fingerprint: str | None,
    history_risk: str,
    history_evidence_exact_count: int,
    history_provider_fingerprint: str,
    blockers: tuple[str, ...],
    warnings: tuple[str, ...],
) -> str:
    return sha256_canonical_json(
        {
            "schema": _HISTORY_REVIEW_SCHEMA,
            "action": action,
            "child_rfc_id": child_rfc_id,
            "old_parent_rfc_id": old_parent_rfc_id,
            "new_parent_rfc_id": new_parent_rfc_id,
            "old_edge_id": old_edge_id,
            "old_branch_fingerprint": old_branch_fingerprint,
            "new_branch_fingerprint": new_branch_fingerprint,
            "history_risk": history_risk,
            "history_evidence_exact_count": history_evidence_exact_count,
            "history_provider_fingerprint": history_provider_fingerprint,
            "blockers": list(blockers),
            "warnings": list(warnings),
        }
    )


@dataclass(frozen=True, slots=True)
class RfcHierarchyMutationPreview:
    action: str
    child_rfc_id: str
    old_parent_rfc_id: str
    new_parent_rfc_id: str | None
    old_edge_id: str
    base_revisions: dict[str, int]
    old_branch_fingerprint: str
    new_branch_fingerprint: str | None
    history_authority: RfcHierarchyHistoryAuthority
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    review_required: bool
    review_fingerprint: str | None

    def to_response(self) -> dict[str, object]:
        return {
            "action": self.action,
            "child_rfc_id": self.child_rfc_id,
            "old_parent_rfc_id": self.old_parent_rfc_id,
            "new_parent_rfc_id": self.new_parent_rfc_id,
            "old_edge_id": self.old_edge_id,
            "base_revisions": dict(self.base_revisions),
            "old_branch_fingerprint": self.old_branch_fingerprint,
            "new_branch_fingerprint": self.new_branch_fingerprint,
            "history_authority": self.history_authority.to_response(),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "review_required": self.review_required,
            "review_fingerprint": self.review_fingerprint,
        }


class RfcHierarchyPreviewEvaluator:
    """Build the exact hierarchy review authority against the supplied stable reader."""

    def __init__(
        self,
        history_risk_provider: RfcHistoryRiskProvider | None = None,
    ) -> None:
        self._history_risk_provider = history_risk_provider or _UnavailableRfcHistoryRiskProvider()

    @staticmethod
    def _load_rfc(connection: Any, rfc_id: str) -> tuple[str | None, int]:
        row = connection.execute(
            "SELECT customer_org_id,revision FROM rfcs WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        return (None if row[0] is None else str(row[0]), int(row[1]))

    @staticmethod
    def _active_parent(connection: Any, child_rfc_id: str) -> tuple[str, str] | None:
        row = connection.execute(
            "SELECT rfc_hierarchy_edge_id,parent_rfc_id FROM rfc_hierarchy_edges "
            "WHERE child_rfc_id=? AND edge_state='active'",
            (child_rfc_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1])

    @classmethod
    def _governing_root(cls, connection: Any, rfc_id: str) -> str:
        parent = cls._active_parent(connection, rfc_id)
        if parent is None:
            return rfc_id
        root_id = parent[1]
        if cls._active_parent(connection, root_id) is not None:
            raise IntegrityFailure("RFC hierarchy exceeds the accepted two-level invariant")
        return root_id

    @staticmethod
    def _append_code(codes: list[str], code: str) -> None:
        if code not in codes:
            codes.append(code)

    def evaluate(
        self,
        reader: object,
        *,
        action: str,
        child_rfc_id: str,
        new_parent_rfc_id: str | None,
    ) -> RfcHierarchyMutationPreview:
        if action not in {"reparent", "detach"}:
            raise ValidationError("RFC hierarchy preview action must be reparent or detach")
        child_id = require_uuid4(child_rfc_id)
        if action == "reparent":
            if new_parent_rfc_id is None:
                raise ValidationError("new_parent_rfc_id is required for RFC reparent preview")
            new_parent_id = require_uuid4(new_parent_rfc_id)
        else:
            if new_parent_rfc_id is not None:
                raise ValidationError("new_parent_rfc_id must be null for RFC detach preview")
            new_parent_id = None

        connection = getattr(reader, "connection", None)
        if connection is None:
            raise IntegrityFailure("RFC hierarchy preview requires a stable reader context")
        child_customer, child_revision = self._load_rfc(connection, child_id)
        old_parent_edge = self._active_parent(connection, child_id)
        if old_parent_edge is None:
            raise SomaError("RFC_PARENT_CONFLICT", "RFC is not currently subordinate")
        old_edge_id, old_parent_id = old_parent_edge
        _, old_parent_revision = self._load_rfc(connection, old_parent_id)
        if self._active_parent(connection, old_parent_id) is not None:
            raise IntegrityFailure("RFC hierarchy contains a subordinate parent")
        old_branch_fingerprint = RfcBranchQueryService.branch_fingerprint_from_connection(
            connection,
            old_parent_id,
        )

        blockers: list[str] = []
        warnings: list[str] = []
        base_revisions: dict[str, int] = {
            old_parent_id: old_parent_revision,
            child_id: child_revision,
        }
        new_branch_fingerprint: str | None = None

        if action == "reparent":
            assert new_parent_id is not None
            new_parent_customer, new_parent_revision = self._load_rfc(connection, new_parent_id)
            base_revisions[new_parent_id] = new_parent_revision
            new_root_id = self._governing_root(connection, new_parent_id)
            new_branch_fingerprint = RfcBranchQueryService.branch_fingerprint_from_connection(
                connection,
                new_root_id,
            )

            if new_parent_id == child_id:
                self._append_code(blockers, "RFC_HIERARCHY_CYCLE")
            if new_parent_id == old_parent_id:
                self._append_code(blockers, "RFC_PARENT_CONFLICT")
            if self._active_parent(connection, new_parent_id) is not None:
                self._append_code(blockers, "RFC_HIERARCHY_DEPTH")
            if connection.execute(
                "SELECT 1 FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'",
                (child_id,),
            ).fetchone() is not None:
                self._append_code(blockers, "RFC_HIERARCHY_DEPTH")
            if connection.execute(
                "SELECT 1 FROM sr_rfc_links WHERE rfc_id=? AND link_state='active'",
                (child_id,),
            ).fetchone() is not None:
                self._append_code(blockers, "RFC_DIRECT_SR_LINK_ON_SUBORDINATE")
            if (
                child_customer is not None
                and new_parent_customer is not None
                and child_customer != new_parent_customer
            ):
                self._append_code(blockers, "RFC_CUSTOMER_MISMATCH")
            elif child_customer is None or new_parent_customer is None:
                self._append_code(warnings, "RFC_CUSTOMER_UNRESOLVED")

        authority = normalize_history_authority(
            self._history_risk_provider.hierarchy_history_authority(reader, child_id)
        )
        review_required = authority.status == "READY" and authority.risk == "HIGH"
        review_fingerprint: str | None = None
        if authority.status == "READY":
            assert authority.risk is not None
            assert authority.evidence_exact_count is not None
            assert authority.provider_fingerprint is not None
            review_fingerprint = hierarchy_review_fingerprint(
                action=action,
                child_rfc_id=child_id,
                old_parent_rfc_id=old_parent_id,
                new_parent_rfc_id=new_parent_id,
                old_edge_id=old_edge_id,
                old_branch_fingerprint=old_branch_fingerprint,
                new_branch_fingerprint=new_branch_fingerprint,
                history_risk=authority.risk,
                history_evidence_exact_count=authority.evidence_exact_count,
                history_provider_fingerprint=authority.provider_fingerprint,
                blockers=tuple(blockers),
                warnings=tuple(warnings),
            )

        return RfcHierarchyMutationPreview(
            action=action,
            child_rfc_id=child_id,
            old_parent_rfc_id=old_parent_id,
            new_parent_rfc_id=new_parent_id,
            old_edge_id=old_edge_id,
            base_revisions=base_revisions,
            old_branch_fingerprint=old_branch_fingerprint,
            new_branch_fingerprint=new_branch_fingerprint,
            history_authority=authority,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            review_required=review_required,
            review_fingerprint=review_fingerprint,
        )


class RfcHierarchyPreviewQueryService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        history_risk_provider: RfcHistoryRiskProvider | None = None,
    ) -> None:
        self._factory = connection_factory
        self._evaluator = RfcHierarchyPreviewEvaluator(history_risk_provider)

    def preview(
        self,
        *,
        action: str,
        child_rfc_id: str,
        new_parent_rfc_id: str | None = None,
    ) -> RfcHierarchyMutationPreview:
        with ReadSnapshot(self._factory) as snapshot:
            return self._evaluator.evaluate(
                snapshot,
                action=action,
                child_rfc_id=child_rfc_id,
                new_parent_rfc_id=new_parent_rfc_id,
            )


class SrRfcLinkPreviewQueryService:
    """Read-only PreviewSrRfcLink owner; resolves subordinate origin to its governing root."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        from soma.tickets.relationships import ServiceRequestRfcRelationshipService

        self._evaluator = ServiceRequestRfcRelationshipService(connection_factory)

    def preview(self, *, service_request_id: str, rfc_id: str):
        sr_id = require_uuid4(service_request_id)
        requested_rfc_id = require_uuid4(rfc_id)
        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            parent = connection.execute(
                "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
                (requested_rfc_id,),
            ).fetchone()
            if parent is None:
                root_rfc_id = requested_rfc_id
                subordinate_origin_rfc_id = None
            else:
                root_rfc_id = str(parent[0])
                subordinate_origin_rfc_id = requested_rfc_id
                if connection.execute(
                    "SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
                    (root_rfc_id,),
                ).fetchone() is not None:
                    raise IntegrityFailure("RFC hierarchy exceeds the accepted two-level invariant")
            result = self._evaluator._preview_with_reader(
                connection,
                service_request_id=sr_id,
                rfc_id=root_rfc_id,
                subordinate_origin_rfc_id=subordinate_origin_rfc_id,
            )
            return replace(result, requested_rfc_id=requested_rfc_id)
