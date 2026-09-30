from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4


FORMAT_ID = "SOMA-INFRA-XLSX"
WORKBOOK_VERSION = "1.0"
MODES = frozenset({"registration_template", "discovery", "round_trip"})
SHEET_ORDER = ("Metadata", "Network Elements", "IP Addresses")
HEADERS = {
    "Metadata": ("Key", "Value"),
    "Network Elements": (
        "SomaNetworkElementId", "OperationalName", "ManufacturerSerial",
        "SomaModelId", "ModelName", "SomaSiteId", "SiteName", "SiteAddress",
        "SomaRoomId", "RoomName", "SomaRackId", "RackName", "RackHeightU",
        "RackRow", "RackColumn", "RackUStart", "RackUSpan",
        "SomaCloudDeploymentId", "CloudTypeName", "CloudDeploymentName",
        "SomaParentNetworkElementId", "ImportComment",
    ),
    "IP Addresses": (
        "SomaIpId", "SomaNetworkElementId", "OperationalName", "Address", "Primary",
    ),
}
METADATA_KEYS = (
    "FormatId", "WorkbookVersion", "Mode", "SourceInstallationScopeId",
    "GeneratedAtUtc", "ExportScopeJson",
)


def artifact_filename(mode: str, export_id: str, generated_at_utc: int) -> str:
    if mode not in MODES:
        raise ValidationError("Unsupported Infrastructure workbook mode")
    require_uuid4(export_id)
    if type(generated_at_utc) is not int or generated_at_utc < 0:
        raise ValidationError("Workbook generation timestamp must be a UTC epoch second")
    try:
        local_time = datetime.fromtimestamp(generated_at_utc, timezone.utc).astimezone(
            ZoneInfo("America/Guayaquil")
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise ValidationError("Workbook generation timestamp is out of range") from exc
    return (
        f"SOMA_Infrastructure_{mode}_{local_time:%Y%m%d_%H%M%S}_"
        f"{export_id.replace('-', '')[:8]}.xlsx"
    )
