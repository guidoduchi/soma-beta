from __future__ import annotations

from typing import Any

from .import_mutations import (
    ServiceRequestImportMutationService,
    ServiceRequestImportReader as _ServiceRequestImportReader,
)


class ServiceRequestImportReader(_ServiceRequestImportReader):
    """Canonical LLD-03 import reader for governed reconciliation freshness."""

    @staticmethod
    def source_identity_base_token(reader: Any, official_sr_no: str) -> str:
        return ServiceRequestImportMutationService.source_identity_base_token(reader, official_sr_no)

    @staticmethod
    def customer_reconciliation_base_token(
        reader: Any,
        service_request_id: str,
        target_customer_org_id: str,
    ) -> str:
        return ServiceRequestImportMutationService.customer_reconciliation_base_token(
            reader,
            service_request_id,
            target_customer_org_id,
        )
