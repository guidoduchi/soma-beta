"""Ticket-owned read interfaces consumed by Infrastructure."""
from soma.foundation.identifiers import require_uuid4


class DeviceReferenceOperationalReader:
    @staticmethod
    def get(reader, device_reference_id):
        require_uuid4(device_reference_id)
        row = reader.connection.execute(
            "SELECT device_reference_id,operational_name,revision FROM device_references WHERE device_reference_id=?",
            (device_reference_id,)).fetchone()
        return None if row is None else dict(device_reference_id=row[0], operational_name=row[1], revision=row[2])
