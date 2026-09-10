from soma.tickets.queries.device_references import TicketDeviceReferenceQueryService
from soma.tickets.queries.relationship_previews import SrRfcLinkPreviewQueryService
from soma.tickets.queries.relationships import ServiceRequestRfcQueryService
from soma.tickets.queries.working_notes import WorkingNoteQueryService


def test_lld03_read_model_query_owners_match_certified_module_map() -> None:
    assert ServiceRequestRfcQueryService.__module__ == "soma.tickets.queries.relationships"
    assert TicketDeviceReferenceQueryService.__module__ == "soma.tickets.queries.device_references"
    assert WorkingNoteQueryService.__module__ == "soma.tickets.queries.working_notes"
    assert SrRfcLinkPreviewQueryService.__module__ == "soma.tickets.queries.relationship_previews"
