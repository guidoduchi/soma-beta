-- Forward-only repair: the accepted untouched-draft deletion command may
-- remove its sole initial fact, never protected lifecycle history.
-- Existing migration bytes and all update guards remain unchanged.

DROP TRIGGER inv_spare_need_lifecycle_events_delete_guard;
CREATE TRIGGER inv_spare_need_lifecycle_events_delete_guard
BEFORE DELETE ON spare_need_lifecycle_events
WHEN NOT (
    OLD.event_kind='created'
    AND (SELECT COUNT(*) FROM spare_need_lifecycle_events WHERE spare_need_id=OLD.spare_need_id)=1
    AND EXISTS (SELECT 1 FROM spare_needs e WHERE e.spare_need_id=OLD.spare_need_id
        AND e.creation_origin='manual' AND e.created_command_id=OLD.command_id)
    AND EXISTS (SELECT 1 FROM command_receipts r
        WHERE r.command_type='HardDeleteUntouchedInventoryDraft'
        AND r.target_type='spare_need' AND r.target_id=OLD.spare_need_id
        AND NOT EXISTS (SELECT 1 FROM command_receipt_results x WHERE x.command_id=r.command_id))
)
BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_NEED_LIFECYCLE_EVENTS_IMMUTABLE');
END;
DROP TRIGGER inv_spare_request_lifecycle_events_delete_guard;
CREATE TRIGGER inv_spare_request_lifecycle_events_delete_guard
BEFORE DELETE ON spare_request_lifecycle_events
WHEN NOT (
    OLD.event_kind='created'
    AND (SELECT COUNT(*) FROM spare_request_lifecycle_events WHERE spare_request_id=OLD.spare_request_id)=1
    AND EXISTS (SELECT 1 FROM spare_requests e WHERE e.spare_request_id=OLD.spare_request_id
        AND e.creation_origin='soma_draft' AND e.created_command_id=OLD.command_id)
    AND EXISTS (SELECT 1 FROM command_receipts r
        WHERE r.command_type='HardDeleteUntouchedInventoryDraft'
        AND r.target_type='spare_request' AND r.target_id=OLD.spare_request_id
        AND NOT EXISTS (SELECT 1 FROM command_receipt_results x WHERE x.command_id=r.command_id))
)
BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_LIFECYCLE_EVENTS_IMMUTABLE');
END;
DROP TRIGGER inv_spare_part_lifecycle_events_delete_guard;
CREATE TRIGGER inv_spare_part_lifecycle_events_delete_guard
BEFORE DELETE ON spare_part_lifecycle_events
WHEN NOT (
    OLD.event_kind='registered'
    AND (SELECT COUNT(*) FROM spare_part_lifecycle_events WHERE spare_part_unit_id=OLD.spare_part_unit_id)=1
    AND EXISTS (SELECT 1 FROM spare_part_units e WHERE e.spare_part_unit_id=OLD.spare_part_unit_id
        AND e.creation_origin='manual_local' AND e.created_command_id=OLD.command_id)
    AND EXISTS (SELECT 1 FROM command_receipts r
        WHERE r.command_type='HardDeleteUntouchedInventoryDraft'
        AND r.target_type='spare_part_unit' AND r.target_id=OLD.spare_part_unit_id
        AND NOT EXISTS (SELECT 1 FROM command_receipt_results x WHERE x.command_id=r.command_id))
)
BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_PART_LIFECYCLE_EVENTS_IMMUTABLE');
END;
DROP TRIGGER inv_fault_tag_lifecycle_events_delete_guard;
CREATE TRIGGER inv_fault_tag_lifecycle_events_delete_guard
BEFORE DELETE ON fault_tag_lifecycle_events
WHEN NOT (
    OLD.event_kind='created'
    AND (SELECT COUNT(*) FROM fault_tag_lifecycle_events WHERE fault_tag_id=OLD.fault_tag_id)=1
    AND EXISTS (SELECT 1 FROM fault_tags e WHERE e.fault_tag_id=OLD.fault_tag_id
        AND e.creation_origin='manual' AND e.created_command_id=OLD.command_id)
    AND EXISTS (SELECT 1 FROM command_receipts r
        WHERE r.command_type='HardDeleteUntouchedInventoryDraft'
        AND r.target_type='fault_tag' AND r.target_id=OLD.fault_tag_id
        AND NOT EXISTS (SELECT 1 FROM command_receipt_results x WHERE x.command_id=r.command_id))
)
BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_LIFECYCLE_EVENTS_IMMUTABLE');
END;
