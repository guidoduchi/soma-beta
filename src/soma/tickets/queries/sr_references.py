from __future__ import annotations

from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ..sr_references import (
    ReferenceChangePreview,
    ServiceRequestCustomerClassificationParticipant,
    build_contact_preview_state,
    build_customer_preview_state,
)
from .service_requests import ServiceRequestQueryService


class ServiceRequestReferenceQueryService:
    """Read-only LLD-03 Service Request reference context and mutation previews."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        classification_participant: ServiceRequestCustomerClassificationParticipant | None = None,
    ) -> None:
        self._factory = connection_factory
        self._classification_participant = classification_participant

    def get(self, *, service_request_id: str) -> dict[str, Any]:
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT revision FROM service_requests WHERE service_request_id=?",
                (service_request_id,),
            ).fetchone()
            if row is None:
                raise SomaError("NOT_FOUND", "Service Request does not exist")
            context, _warnings = ServiceRequestQueryService._reference_context(
                snapshot.connection,
                service_request_id,
                int(row[0]),
            )
            return context

    def preview_customer_change(
        self,
        *,
        service_request_id: str,
        customer_org_id: str | None,
    ) -> ReferenceChangePreview:
        with ReadSnapshot(self._factory) as snapshot:
            state = build_customer_preview_state(
                snapshot.connection,
                service_request_id=service_request_id,
                customer_org_id=customer_org_id,
            )
            warnings = list(state.preview.warnings)
            eligible = state.preview.eligible
            if self._classification_participant is not None:
                try:
                    impact = self._classification_participant.preview_customer_change(
                        snapshot.connection,
                        service_request_id,
                        customer_org_id,
                    )
                except Exception:
                    impact = "INDETERMINATE"
                if impact == "INDETERMINATE":
                    warnings.append("SR_CUSTOMER_CLASSIFICATION_PARTICIPANT_FAILED")
                    eligible = False
            return ReferenceChangePreview(
                eligible=eligible,
                base_revision=state.preview.base_revision,
                review_fingerprint=state.preview.review_fingerprint,
                warnings=tuple(sorted(set(warnings))),
            )

    def preview_contact_reference(
        self,
        *,
        service_request_id: str,
        reference_role: str,
        contact_id: str | None,
        supporting_sr_source_field_observation_id: str | None = None,
    ) -> ReferenceChangePreview:
        with ReadSnapshot(self._factory) as snapshot:
            return build_contact_preview_state(
                snapshot.connection,
                service_request_id=service_request_id,
                reference_role=reference_role,
                contact_id=contact_id,
                supporting_source_observation_id=supporting_sr_source_field_observation_id,
            ).preview
