from __future__ import annotations

from typing import Any

from .import_mutations import (
    ServiceRequestImportMutationService,
    ServiceRequestImportReader as _ServiceRequestImportReader,
)


class ServiceRequestImportReader(_ServiceRequestImportReader):
    """Canonical LLD-03 import reader, including exact official-identity freshness."""

    @staticmethod
    def source_identity_base_token(reader: Any, official_sr_no: str) -> str:
        return ServiceRequestImportMutationService.source_identity_base_token(reader, official_sr_no)
