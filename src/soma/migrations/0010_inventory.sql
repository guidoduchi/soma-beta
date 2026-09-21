-- SOMA Beta LLD-07 Inventory relational backbone.
-- Normative owner: spec/lld/inventory, migration beta_0010_inventory.

CREATE TABLE inventory_tracking_allocators (
    allocator_kind TEXT PRIMARY KEY CHECK(allocator_kind IN ('spare_request','local_spare_unit','fault_tag','device_part_creation')),
    next_sequence INTEGER NOT NULL CHECK(next_sequence BETWEEN 1 AND 100000000),
    revision INTEGER NOT NULL CHECK(revision>0),
    last_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE device_part_units (
    device_part_unit_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON DELETE RESTRICT,
    device_reference_id TEXT NOT NULL REFERENCES device_references(device_reference_id) ON DELETE RESTRICT,
    creation_sequence INTEGER NOT NULL UNIQUE CHECK(creation_sequence BETWEEN 1 AND 99999999),
    bom_code TEXT NOT NULL,
    bom_key TEXT NOT NULL,
    manufacturer_serial TEXT NULL,
    serial_key TEXT NULL,
    slot_label TEXT NULL,
    creation_origin TEXT NOT NULL CHECK(creation_origin IN ('manual_fault_registration','manual_component_registration','reviewed_reconciliation')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE device_part_lifecycle_events (
    device_part_event_id TEXT PRIMARY KEY,
    device_part_unit_id TEXT NOT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('registered','fault_observed','condition_changed','removed','installed','correction')),
    condition_token TEXT NULL CHECK(condition_token IS NULL OR condition_token IN ('unknown','normal','faulty','removed','installed','quarantined')),
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES device_part_lifecycle_events(device_part_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    evidence_kind TEXT NULL,
    evidence_id TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE device_part_current_projection (
    device_part_unit_id TEXT PRIMARY KEY REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    condition_token TEXT NOT NULL CHECK(condition_token IN ('unknown','normal','faulty','removed','installed','quarantined')),
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_event_id TEXT NOT NULL REFERENCES device_part_lifecycle_events(device_part_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_needs (
    spare_need_id TEXT PRIMARY KEY,
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON DELETE RESTRICT,
    bom_code TEXT NOT NULL,
    bom_key TEXT NOT NULL,
    description TEXT NULL,
    planned_quantity INTEGER NOT NULL CHECK(planned_quantity BETWEEN 1 AND 1000000),
    creation_origin TEXT NOT NULL CHECK(creation_origin IN ('manual','system_aggregate','external_request_reconciliation')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_need_lifecycle_events (
    need_event_id TEXT PRIMARY KEY,
    spare_need_id TEXT NOT NULL REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('created','planned_quantity_changed','resolved','cancelled','reactivated','history_removed')),
    planned_quantity INTEGER NULL CHECK(planned_quantity IS NULL OR planned_quantity BETWEEN 1 AND 1000000),
    reason_code TEXT NULL,
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_need_current_projection (
    spare_need_id TEXT PRIMARY KEY REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','resolved','cancelled','removed')),
    planned_quantity INTEGER NOT NULL CHECK(planned_quantity BETWEEN 1 AND 1000000),
    contributor_count INTEGER NOT NULL CHECK(contributor_count>=0),
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_need_active_keys (
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON DELETE RESTRICT,
    bom_key TEXT NOT NULL,
    spare_need_id TEXT NOT NULL UNIQUE REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    PRIMARY KEY(service_request_id,bom_key)
) STRICT;

CREATE TABLE spare_need_contributors (
    contributor_relationship_id TEXT PRIMARY KEY,
    spare_need_id TEXT NOT NULL REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    device_part_unit_id TEXT NOT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    opened_at_utc INTEGER NOT NULL CHECK(opened_at_utc>=0),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    closed_at_utc INTEGER NULL CHECK(closed_at_utc IS NULL OR closed_at_utc>=0),
    closed_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    close_reason TEXT NULL
) STRICT;

CREATE TABLE spare_requests (
    spare_request_id TEXT PRIMARY KEY,
    tracking_sequence INTEGER NOT NULL UNIQUE CHECK(tracking_sequence BETWEEN 1 AND 99999999),
    tracking_id TEXT NOT NULL UNIQUE CHECK(length(tracking_id)=12 AND substr(tracking_id,1,4)='SPR-' AND substr(tracking_id,5) NOT GLOB '*[^0-9]*'),
    service_request_id TEXT NOT NULL REFERENCES service_requests(service_request_id) ON DELETE RESTRICT,
    requester_contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON DELETE RESTRICT,
    requester_context_json TEXT NOT NULL CHECK(json_valid(requester_context_json)),
    creation_origin TEXT NOT NULL CHECK(creation_origin IN ('soma_draft','external_registration')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_request_need_allocations (
    request_need_allocation_id TEXT PRIMARY KEY,
    spare_request_id TEXT NOT NULL REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    spare_need_id TEXT NOT NULL REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 1000000),
    revision INTEGER NOT NULL CHECK(revision>0),
    active_draft INTEGER NOT NULL CHECK(active_draft IN (0,1)),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_request_draft_logistics (
    spare_request_id TEXT PRIMARY KEY REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    mode TEXT NOT NULL CHECK(mode IN ('delivery','self_pickup')),
    receiver_contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON DELETE RESTRICT,
    dispatch_location_id TEXT NOT NULL REFERENCES dispatch_locations(dispatch_location_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_request_lifecycle_events (
    request_event_id TEXT PRIMARY KEY,
    spare_request_id TEXT NOT NULL REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('created','submission_accepted','submission_corrected_false','cancelled','rejected','acknowledgement_accepted','authorization_progress','correction')),
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES spare_request_lifecycle_events(request_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    evidence_kind TEXT NULL,
    evidence_id TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_request_identifier_events (
    identifier_event_id TEXT PRIMARY KEY,
    spare_request_id TEXT NOT NULL REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('assign','correct')),
    prior_sr7 TEXT NULL,
    new_sr7 TEXT NOT NULL CHECK(length(new_sr7)=9 AND substr(new_sr7,1,2)='SR' AND substr(new_sr7,3) NOT GLOB '*[^0-9]*'),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_request_identifier_aliases (
    alias_id TEXT PRIMARY KEY,
    spare_request_id TEXT NOT NULL REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    sr7 TEXT NOT NULL UNIQUE CHECK(length(sr7)=9 AND substr(sr7,1,2)='SR' AND substr(sr7,3) NOT GLOB '*[^0-9]*'),
    alias_kind TEXT NOT NULL CHECK(alias_kind IN ('current','former')),
    source_identifier_event_id TEXT NOT NULL REFERENCES spare_request_identifier_events(identifier_event_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_request_submission_snapshots (
    submission_snapshot_id TEXT PRIMARY KEY,
    spare_request_id TEXT NOT NULL REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    submission_event_id TEXT NOT NULL UNIQUE REFERENCES spare_request_lifecycle_events(request_event_id) ON DELETE RESTRICT,
    temporary_tracking_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('delivery','self_pickup')),
    receiver_contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON DELETE RESTRICT,
    dispatch_location_id TEXT NOT NULL REFERENCES dispatch_locations(dispatch_location_id) ON DELETE RESTRICT,
    location_name_snapshot TEXT NOT NULL,
    location_address_snapshot TEXT NOT NULL,
    recipient_context_json TEXT NOT NULL CHECK(json_valid(recipient_context_json)),
    effective_submission_at_utc INTEGER NULL CHECK(effective_submission_at_utc IS NULL OR effective_submission_at_utc>=0),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    evidence_kind TEXT NULL,
    evidence_id TEXT NULL,
    snapshot_hash TEXT NOT NULL CHECK(length(snapshot_hash)=64)
) STRICT;

CREATE TABLE spare_request_submission_allocations (
    submission_allocation_id TEXT PRIMARY KEY,
    submission_snapshot_id TEXT NOT NULL REFERENCES spare_request_submission_snapshots(submission_snapshot_id) ON DELETE RESTRICT,
    request_need_allocation_id TEXT NOT NULL REFERENCES spare_request_need_allocations(request_need_allocation_id) ON DELETE RESTRICT,
    spare_need_id TEXT NOT NULL REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 1000000),
    requested_bom_code TEXT NOT NULL,
    requested_bom_key TEXT NOT NULL
) STRICT;

CREATE TABLE spare_request_current_projection (
    spare_request_id TEXT PRIMARY KEY REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('draft','submitted_awaiting_response','acknowledged','partially_authorized','authorized','cancelled','rejected')),
    current_sr7 TEXT NULL CHECK(current_sr7 IS NULL OR (length(current_sr7)=9 AND substr(current_sr7,1,2)='SR')),
    current_submission_snapshot_id TEXT NULL REFERENCES spare_request_submission_snapshots(submission_snapshot_id) ON DELETE RESTRICT,
    submitted_quantity INTEGER NOT NULL DEFAULT 0 CHECK(submitted_quantity>=0),
    authorized_rma_count INTEGER NOT NULL DEFAULT 0 CHECK(authorized_rma_count>=0),
    response_warning_start_utc INTEGER NULL CHECK(response_warning_start_utc IS NULL OR response_warning_start_utc>=0),
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE rma_authorization_batches (
    authorization_batch_id TEXT PRIMARY KEY,
    spare_request_id TEXT NOT NULL REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    batch_ordinal INTEGER NOT NULL CHECK(batch_ordinal>0),
    accepted_at_utc INTEGER NOT NULL CHECK(accepted_at_utc>=0),
    evidence_kind TEXT NULL,
    evidence_id TEXT NULL,
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE rmas (
    rma_id TEXT PRIMARY KEY,
    spare_request_id TEXT NOT NULL REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    authorization_batch_id TEXT NOT NULL REFERENCES rma_authorization_batches(authorization_batch_id) ON DELETE RESTRICT,
    response_ordinal INTEGER NOT NULL CHECK(response_ordinal>0),
    promised_bom_code TEXT NOT NULL,
    promised_bom_key TEXT NOT NULL,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE rma_identifier_events (
    identifier_event_id TEXT PRIMARY KEY,
    rma_id TEXT NOT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('assign','correct')),
    prior_c10 TEXT NULL,
    new_c10 TEXT NOT NULL CHECK(length(new_c10)=11 AND substr(new_c10,1,1)='C' AND substr(new_c10,2) NOT GLOB '*[^0-9]*'),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE rma_identifier_aliases (
    alias_id TEXT PRIMARY KEY,
    rma_id TEXT NOT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    c10 TEXT NOT NULL UNIQUE CHECK(length(c10)=11 AND substr(c10,1,1)='C' AND substr(c10,2) NOT GLOB '*[^0-9]*'),
    alias_kind TEXT NOT NULL CHECK(alias_kind IN ('current','former')),
    source_identifier_event_id TEXT NOT NULL REFERENCES rma_identifier_events(identifier_event_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE rma_assignment_events (
    assignment_event_id TEXT PRIMARY KEY,
    rma_id TEXT NOT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    prior_device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    new_device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('auto_assign','manual_assign','reassign','clear','correction')),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE rma_current_assignment (
    rma_id TEXT PRIMARY KEY REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    device_part_unit_id TEXT NOT NULL UNIQUE REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    assignment_event_id TEXT NOT NULL UNIQUE REFERENCES rma_assignment_events(assignment_event_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_part_units (
    spare_part_unit_id TEXT PRIMARY KEY,
    local_tracking_sequence INTEGER NULL UNIQUE CHECK(local_tracking_sequence IS NULL OR local_tracking_sequence BETWEEN 1 AND 99999999),
    local_tracking_id TEXT NULL UNIQUE CHECK(local_tracking_id IS NULL OR (length(local_tracking_id)=12 AND substr(local_tracking_id,1,4)='LSU-' AND substr(local_tracking_id,5) NOT GLOB '*[^0-9]*')),
    bom_code TEXT NOT NULL,
    bom_key TEXT NOT NULL,
    manufacturer_serial TEXT NULL,
    serial_key TEXT NULL,
    creation_origin TEXT NOT NULL CHECK(creation_origin IN ('manual_local','direct_rma_receipt','extracted','legacy','reviewed_reconciliation')),
    origin_rma_id TEXT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    parent_spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK(parent_spare_part_unit_id IS NULL OR parent_spare_part_unit_id<>spare_part_unit_id)
) STRICT;

CREATE TABLE rma_direct_inbound_units (
    direct_inbound_relationship_id TEXT PRIMARY KEY,
    rma_id TEXT NOT NULL UNIQUE REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NOT NULL UNIQUE REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    relationship_event_id TEXT NOT NULL UNIQUE,
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_part_lifecycle_events (
    unit_event_id TEXT PRIMARY KEY,
    spare_part_unit_id TEXT NOT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('registered','received','condition_changed','custody_changed','location_changed','installed','removed','quarantined','dismantled','scrapped','returned','correction')),
    condition_token TEXT NULL CHECK(condition_token IS NULL OR condition_token IN ('new','used','faulty','incompatible','unknown')),
    disposition_token TEXT NULL CHECK(disposition_token IS NULL OR disposition_token IN ('available','reserved','in_transit','installed','quarantined','dismantled','scrapped','returned','unavailable')),
    location_kind TEXT NULL,
    location_ref_id TEXT NULL,
    custody_text TEXT NULL,
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES spare_part_lifecycle_events(unit_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    evidence_kind TEXT NULL,
    evidence_id TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE spare_part_current_projection (
    spare_part_unit_id TEXT PRIMARY KEY REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    condition_token TEXT NOT NULL CHECK(condition_token IN ('new','used','faulty','incompatible','unknown')),
    disposition_token TEXT NOT NULL CHECK(disposition_token IN ('available','reserved','in_transit','installed','quarantined','dismantled','scrapped','returned','unavailable')),
    location_kind TEXT NULL,
    location_ref_id TEXT NULL,
    custody_text TEXT NULL,
    active_task_allocation_id TEXT NULL,
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE task_unit_allocation_events (
    allocation_event_id TEXT PRIMARY KEY,
    allocation_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NOT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    spare_need_id TEXT NULL REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('reserve','release','reassign','correction')),
    prior_task_id TEXT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES task_unit_allocation_events(allocation_event_id) ON DELETE RESTRICT,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE task_unit_allocation_current (
    allocation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NOT NULL UNIQUE REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    spare_need_id TEXT NULL REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES task_unit_allocation_events(allocation_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE local_need_fulfillment_events (
    local_fulfillment_event_id TEXT PRIMARY KEY,
    spare_need_id TEXT NOT NULL REFERENCES spare_needs(spare_need_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NOT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    task_id TEXT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK(quantity=1),
    event_kind TEXT NOT NULL CHECK(event_kind IN ('selected','released','superseded')),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE inventory_physical_consequences (
    physical_consequence_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    task_review_fingerprint TEXT NOT NULL CHECK(length(task_review_fingerprint)=64),
    target_device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    rma_id TEXT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE physical_consequence_events (
    consequence_event_id TEXT PRIMARY KEY,
    physical_consequence_id TEXT NOT NULL REFERENCES inventory_physical_consequences(physical_consequence_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('accept','correct','supersede')),
    physical_disposition TEXT NOT NULL CHECK(physical_disposition IN ('installed_used','unused','inbound_faulty','incompatible','dismantled','removed_only','no_physical_change','other_reviewed')),
    installed_spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    removed_device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    inbound_spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    parent_dismantled_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES physical_consequence_events(consequence_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE physical_consequence_current (
    physical_consequence_id TEXT PRIMARY KEY REFERENCES inventory_physical_consequences(physical_consequence_id) ON DELETE RESTRICT,
    task_review_fingerprint TEXT NOT NULL CHECK(length(task_review_fingerprint)=64),
    physical_disposition TEXT NOT NULL,
    installed_spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    removed_device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    inbound_spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    parent_dismantled_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_event_id TEXT NOT NULL REFERENCES physical_consequence_events(consequence_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE rma_return_selection_events (
    return_selection_event_id TEXT PRIMARY KEY,
    rma_id TEXT NOT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    physical_consequence_id TEXT NOT NULL REFERENCES inventory_physical_consequences(physical_consequence_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('select','correct','clear','close','reopen_after_rejection')),
    device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES rma_return_selection_events(return_selection_event_id) ON DELETE RESTRICT,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((event_kind IN ('clear','close') AND device_part_unit_id IS NULL AND spare_part_unit_id IS NULL) OR (event_kind NOT IN ('clear','close') AND ((device_part_unit_id IS NOT NULL AND spare_part_unit_id IS NULL) OR (device_part_unit_id IS NULL AND spare_part_unit_id IS NOT NULL))))
) STRICT;

CREATE TABLE rma_return_obligation_current (
    rma_id TEXT PRIMARY KEY REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    obligation_state TEXT NOT NULL CHECK(obligation_state IN ('not_established','open','closed_accepted')),
    device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    physical_consequence_id TEXT NULL REFERENCES inventory_physical_consequences(physical_consequence_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NULL REFERENCES rma_return_selection_events(return_selection_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((obligation_state='not_established' AND device_part_unit_id IS NULL AND spare_part_unit_id IS NULL) OR (obligation_state IN ('open','closed_accepted') AND ((device_part_unit_id IS NOT NULL AND spare_part_unit_id IS NULL) OR (device_part_unit_id IS NULL AND spare_part_unit_id IS NOT NULL))))
) STRICT;

CREATE TABLE actual_logistics_events (
    logistics_event_id TEXT PRIMARY KEY,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('dispatch','pickup','delivery','receipt','custody_change','location_change','return_pickup','warehouse_delivery','correction')),
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    dispatch_location_id TEXT NULL REFERENCES dispatch_locations(dispatch_location_id) ON DELETE RESTRICT,
    location_name_snapshot TEXT NULL,
    location_address_snapshot TEXT NULL,
    receiver_contact_id TEXT NULL REFERENCES contacts(contact_id) ON DELETE RESTRICT,
    receiver_snapshot_json TEXT NULL CHECK(receiver_snapshot_json IS NULL OR json_valid(receiver_snapshot_json)),
    custody_text TEXT NULL,
    observed_condition TEXT NULL,
    target_event_id TEXT NULL REFERENCES actual_logistics_events(logistics_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    evidence_kind TEXT NULL,
    evidence_id TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE logistics_rma_participants (
    logistics_rma_participant_id TEXT PRIMARY KEY,
    logistics_event_id TEXT NOT NULL REFERENCES actual_logistics_events(logistics_event_id) ON DELETE RESTRICT,
    rma_id TEXT NOT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    closed_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    close_reason TEXT NULL
) STRICT;

CREATE TABLE logistics_spare_unit_participants (
    logistics_spare_participant_id TEXT PRIMARY KEY,
    logistics_event_id TEXT NOT NULL REFERENCES actual_logistics_events(logistics_event_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NOT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    closed_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    close_reason TEXT NULL
) STRICT;

CREATE TABLE logistics_device_part_participants (
    logistics_device_participant_id TEXT PRIMARY KEY,
    logistics_event_id TEXT NOT NULL REFERENCES actual_logistics_events(logistics_event_id) ON DELETE RESTRICT,
    device_part_unit_id TEXT NOT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    opened_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    closed_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    close_reason TEXT NULL
) STRICT;

CREATE TABLE fault_tags (
    fault_tag_id TEXT PRIMARY KEY,
    tracking_sequence INTEGER NOT NULL UNIQUE CHECK(tracking_sequence BETWEEN 1 AND 99999999),
    tracking_id TEXT NOT NULL UNIQUE CHECK(length(tracking_id)=11 AND substr(tracking_id,1,3)='FT-' AND substr(tracking_id,4) NOT GLOB '*[^0-9]*'),
    creation_origin TEXT NOT NULL CHECK(creation_origin='manual'),
    draft_return_method TEXT NOT NULL CHECK(draft_return_method IN ('pickup','non_pickup')),
    draft_pickup_dispatch_location_id TEXT NULL REFERENCES dispatch_locations(dispatch_location_id) ON DELETE RESTRICT,
    draft_pickup_contact_id TEXT NULL REFERENCES contacts(contact_id) ON DELETE RESTRICT,
    draft_pickup_instructions TEXT NULL,
    draft_revision INTEGER NOT NULL CHECK(draft_revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((draft_return_method='pickup') OR (draft_pickup_dispatch_location_id IS NULL AND draft_pickup_contact_id IS NULL))
) STRICT;

CREATE TABLE fault_tag_memberships (
    fault_tag_membership_id TEXT PRIMARY KEY,
    fault_tag_id TEXT NOT NULL REFERENCES fault_tags(fault_tag_id) ON DELETE RESTRICT,
    rma_id TEXT NOT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    physical_consequence_id TEXT NOT NULL REFERENCES inventory_physical_consequences(physical_consequence_id) ON DELETE RESTRICT,
    device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    return_reason TEXT NOT NULL,
    draft_revision INTEGER NOT NULL CHECK(draft_revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((device_part_unit_id IS NOT NULL AND spare_part_unit_id IS NULL) OR (device_part_unit_id IS NULL AND spare_part_unit_id IS NOT NULL))
) STRICT;

CREATE TABLE fault_tag_lifecycle_events (
    fault_tag_event_id TEXT PRIMARY KEY,
    fault_tag_id TEXT NOT NULL REFERENCES fault_tags(fault_tag_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('created','submission_accepted','submission_corrected_false','cancelled','superseded','archived','restored','correction')),
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES fault_tag_lifecycle_events(fault_tag_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    evidence_kind TEXT NULL,
    evidence_id TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE fault_tag_submission_snapshots (
    fault_tag_submission_snapshot_id TEXT PRIMARY KEY,
    fault_tag_id TEXT NOT NULL REFERENCES fault_tags(fault_tag_id) ON DELETE RESTRICT,
    submission_event_id TEXT NOT NULL UNIQUE REFERENCES fault_tag_lifecycle_events(fault_tag_event_id) ON DELETE RESTRICT,
    tracking_id TEXT NOT NULL,
    return_method TEXT NOT NULL CHECK(return_method IN ('pickup','non_pickup')),
    pickup_dispatch_location_id TEXT NULL REFERENCES dispatch_locations(dispatch_location_id) ON DELETE RESTRICT,
    pickup_location_name_snapshot TEXT NULL,
    pickup_location_address_snapshot TEXT NULL,
    pickup_contact_id TEXT NULL REFERENCES contacts(contact_id) ON DELETE RESTRICT,
    pickup_contact_snapshot_json TEXT NULL CHECK(pickup_contact_snapshot_json IS NULL OR json_valid(pickup_contact_snapshot_json)),
    pickup_instructions_snapshot TEXT NULL,
    recipient_context_json TEXT NULL CHECK(recipient_context_json IS NULL OR json_valid(recipient_context_json)),
    effective_submission_at_utc INTEGER NULL CHECK(effective_submission_at_utc IS NULL OR effective_submission_at_utc>=0),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    snapshot_hash TEXT NOT NULL CHECK(length(snapshot_hash)=64),
    CHECK((return_method='pickup' AND pickup_dispatch_location_id IS NOT NULL AND pickup_location_name_snapshot IS NOT NULL AND pickup_location_address_snapshot IS NOT NULL) OR (return_method='non_pickup' AND pickup_dispatch_location_id IS NULL AND pickup_location_name_snapshot IS NULL AND pickup_location_address_snapshot IS NULL AND pickup_contact_id IS NULL AND pickup_contact_snapshot_json IS NULL))
) STRICT;

CREATE TABLE fault_tag_membership_submission_snapshots (
    membership_snapshot_id TEXT PRIMARY KEY,
    fault_tag_submission_snapshot_id TEXT NOT NULL REFERENCES fault_tag_submission_snapshots(fault_tag_submission_snapshot_id) ON DELETE RESTRICT,
    fault_tag_membership_id TEXT NOT NULL REFERENCES fault_tag_memberships(fault_tag_membership_id) ON DELETE RESTRICT,
    rma_id TEXT NOT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    physical_consequence_id TEXT NOT NULL REFERENCES inventory_physical_consequences(physical_consequence_id) ON DELETE RESTRICT,
    return_reason TEXT NOT NULL,
    display_snapshot_json TEXT NOT NULL CHECK(json_valid(display_snapshot_json)),
    CHECK((device_part_unit_id IS NOT NULL AND spare_part_unit_id IS NULL) OR (device_part_unit_id IS NULL AND spare_part_unit_id IS NOT NULL))
) STRICT;

CREATE TABLE fault_tag_membership_events (
    membership_event_id TEXT PRIMARY KEY,
    fault_tag_membership_id TEXT NOT NULL REFERENCES fault_tag_memberships(fault_tag_membership_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('submitted','warehouse_received','warehouse_accepted','warehouse_rejected','cancelled','superseded','correct')),
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES fault_tag_membership_events(membership_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    evidence_kind TEXT NULL,
    evidence_id TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE fault_tag_membership_current (
    fault_tag_membership_id TEXT PRIMARY KEY REFERENCES fault_tag_memberships(fault_tag_membership_id) ON DELETE RESTRICT,
    fault_tag_id TEXT NOT NULL REFERENCES fault_tags(fault_tag_id) ON DELETE RESTRICT,
    rma_id TEXT NOT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK(state IN ('draft','submitted_awaiting_receipt','warehouse_received','accepted','rejected','cancelled','superseded')),
    active_submitted INTEGER NOT NULL CHECK(active_submitted IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_event_id TEXT NULL REFERENCES fault_tag_membership_events(membership_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((device_part_unit_id IS NOT NULL AND spare_part_unit_id IS NULL) OR (device_part_unit_id IS NULL AND spare_part_unit_id IS NOT NULL))
) STRICT;

CREATE TABLE fault_tag_current_projection (
    fault_tag_id TEXT PRIMARY KEY REFERENCES fault_tags(fault_tag_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK(state IN ('draft','submitted','in_warehouse_review','terminal_completed','terminal_with_rejected','cancelled','superseded')),
    archived INTEGER NOT NULL CHECK(archived IN (0,1)),
    current_submission_snapshot_id TEXT NULL REFERENCES fault_tag_submission_snapshots(fault_tag_submission_snapshot_id) ON DELETE RESTRICT,
    submitted_member_count INTEGER NOT NULL CHECK(submitted_member_count>=0),
    awaiting_receipt_count INTEGER NOT NULL CHECK(awaiting_receipt_count>=0),
    awaiting_final_count INTEGER NOT NULL CHECK(awaiting_final_count>=0),
    accepted_count INTEGER NOT NULL CHECK(accepted_count>=0),
    rejected_count INTEGER NOT NULL CHECK(rejected_count>=0),
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE fault_tag_lineage (
    fault_tag_lineage_id TEXT PRIMARY KEY,
    relation_type TEXT NOT NULL CHECK(relation_type IN ('corrects_replaces','resend_of')),
    predecessor_fault_tag_id TEXT NOT NULL REFERENCES fault_tags(fault_tag_id) ON DELETE RESTRICT,
    successor_fault_tag_id TEXT NOT NULL REFERENCES fault_tags(fault_tag_id) ON DELETE RESTRICT,
    reason_code TEXT NOT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK(predecessor_fault_tag_id<>successor_fault_tag_id)
) STRICT;

CREATE TABLE rma_lifecycle_projection (
    rma_id TEXT PRIMARY KEY REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK(state IN ('promised','dispatched','received','physical_consequence_pending','return_open','fault_tagged','warehouse_received','closed_accepted','return_rejected')),
    current_target_device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    direct_inbound_spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    return_device_part_unit_id TEXT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    return_spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    return_obligation_open INTEGER NOT NULL CHECK(return_obligation_open IN (0,1)),
    active_fault_tag_membership_id TEXT NULL REFERENCES fault_tag_memberships(fault_tag_membership_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK(NOT(return_device_part_unit_id IS NOT NULL AND return_spare_part_unit_id IS NOT NULL))
) STRICT;

CREATE TABLE inventory_lifecycle_batches (
    inventory_batch_id TEXT PRIMARY KEY,
    batch_kind TEXT NOT NULL CHECK(batch_kind IN ('manual_bulk','proposal_acceptance','correction_bulk')),
    target_count INTEGER NOT NULL CHECK(target_count>0),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE inventory_proposals (
    inventory_proposal_id TEXT PRIMARY KEY,
    proposal_kind TEXT NOT NULL CHECK(proposal_kind IN ('spare_request_submission','official_sr7','rma_authorization','dispatch','receipt','fault_tag_submission','warehouse_received','warehouse_final_decision')),
    evidence_kind TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    source_proposal_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','accepted','rejected','superseded')),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    risk_tier TEXT NOT NULL CHECK(risk_tier IN ('normal','high','material_final')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    revision INTEGER NOT NULL CHECK(revision>0),
    last_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE inventory_proposal_targets (
    inventory_proposal_target_id TEXT PRIMARY KEY,
    inventory_proposal_id TEXT NOT NULL REFERENCES inventory_proposals(inventory_proposal_id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('spare_request','rma','spare_part_unit','fault_tag','fault_tag_membership')),
    spare_request_id TEXT NULL REFERENCES spare_requests(spare_request_id) ON DELETE RESTRICT,
    rma_id TEXT NULL REFERENCES rmas(rma_id) ON DELETE RESTRICT,
    spare_part_unit_id TEXT NULL REFERENCES spare_part_units(spare_part_unit_id) ON DELETE RESTRICT,
    fault_tag_id TEXT NULL REFERENCES fault_tags(fault_tag_id) ON DELETE RESTRICT,
    fault_tag_membership_id TEXT NULL REFERENCES fault_tag_memberships(fault_tag_membership_id) ON DELETE RESTRICT,
    expected_revision INTEGER NOT NULL CHECK(expected_revision>0),
    proposed_action TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    CHECK((target_kind='spare_request' AND spare_request_id IS NOT NULL AND rma_id IS NULL AND spare_part_unit_id IS NULL AND fault_tag_id IS NULL AND fault_tag_membership_id IS NULL) OR (target_kind='rma' AND rma_id IS NOT NULL AND spare_request_id IS NULL AND spare_part_unit_id IS NULL AND fault_tag_id IS NULL AND fault_tag_membership_id IS NULL) OR (target_kind='spare_part_unit' AND spare_part_unit_id IS NOT NULL AND spare_request_id IS NULL AND rma_id IS NULL AND fault_tag_id IS NULL AND fault_tag_membership_id IS NULL) OR (target_kind='fault_tag' AND fault_tag_id IS NOT NULL AND spare_request_id IS NULL AND rma_id IS NULL AND spare_part_unit_id IS NULL AND fault_tag_membership_id IS NULL) OR (target_kind='fault_tag_membership' AND fault_tag_membership_id IS NOT NULL AND spare_request_id IS NULL AND rma_id IS NULL AND spare_part_unit_id IS NULL AND fault_tag_id IS NULL))
) STRICT;

CREATE TABLE inventory_attention_projection (
    attention_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    attention_kind TEXT NOT NULL CHECK(attention_kind IN ('spare_request_response_overdue','partial_rma_authorization','rma_assignment_conflict','receipt_bom_mismatch','task_outcome_consequence_pending','return_obligation_open','warehouse_final_decision_pending','warehouse_rejected_resend_required','proposal_review_required','stock_conflict')),
    severity TEXT NOT NULL CHECK(severity IN ('info','warning','action_required','high')),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

INSERT INTO inventory_tracking_allocators(allocator_kind,next_sequence,revision,last_command_id) VALUES
    ('spare_request',1,1,NULL),
    ('local_spare_unit',1,1,NULL),
    ('fault_tag',1,1,NULL),
    ('device_part_creation',1,1,NULL);

CREATE INDEX idx_inv_001_device_part_units ON device_part_units(service_request_id,bom_key,creation_sequence);
CREATE INDEX idx_inv_002_device_part_units ON device_part_units(device_reference_id,creation_sequence);
CREATE INDEX idx_inv_003_device_part_units ON device_part_units(bom_key,serial_key,device_part_unit_id);
CREATE INDEX idx_inv_004_device_part_lifecycle_events ON device_part_lifecycle_events(device_part_unit_id,recorded_at_utc,device_part_event_id);
CREATE INDEX idx_inv_005_spare_needs ON spare_needs(service_request_id,bom_key,spare_need_id);
CREATE INDEX idx_inv_006_spare_need_lifecycle_events ON spare_need_lifecycle_events(spare_need_id,recorded_at_utc,need_event_id);
CREATE INDEX idx_inv_007_spare_need_contributors ON spare_need_contributors(spare_need_id,active,device_part_unit_id);
CREATE UNIQUE INDEX idx_inv_008_spare_need_contributors ON spare_need_contributors(device_part_unit_id) WHERE active=1;
CREATE INDEX idx_inv_009_spare_requests ON spare_requests(requester_contact_id,created_at_utc,spare_request_id);
CREATE INDEX idx_inv_010_spare_request_need_allocations ON spare_request_need_allocations(spare_request_id,active_draft,spare_need_id);
CREATE UNIQUE INDEX idx_inv_011_spare_request_need_allocations ON spare_request_need_allocations(spare_request_id,spare_need_id) WHERE active_draft=1;
CREATE INDEX idx_inv_012_spare_request_draft_logistics ON spare_request_draft_logistics(receiver_contact_id,spare_request_id);
CREATE INDEX idx_inv_013_spare_request_draft_logistics ON spare_request_draft_logistics(dispatch_location_id,spare_request_id);
CREATE INDEX idx_inv_014_spare_request_identifier_aliases ON spare_request_identifier_aliases(spare_request_id,alias_kind);
CREATE UNIQUE INDEX idx_inv_015_spare_request_identifier_aliases ON spare_request_identifier_aliases(spare_request_id) WHERE alias_kind='current';
CREATE INDEX idx_inv_016_spare_request_submission_snapshots ON spare_request_submission_snapshots(spare_request_id,recorded_at_utc,submission_snapshot_id);
CREATE INDEX idx_inv_017_spare_request_submission_allocations ON spare_request_submission_allocations(submission_snapshot_id,submission_allocation_id);
CREATE INDEX idx_inv_018_spare_request_lifecycle_events ON spare_request_lifecycle_events(spare_request_id,recorded_at_utc,request_event_id);
CREATE UNIQUE INDEX idx_inv_019_rma_authorization_batches ON rma_authorization_batches(spare_request_id,batch_ordinal);
CREATE INDEX idx_inv_020_rmas ON rmas(spare_request_id,authorization_batch_id,response_ordinal);
CREATE UNIQUE INDEX idx_inv_021_rma_identifier_aliases ON rma_identifier_aliases(rma_id) WHERE alias_kind='current';
CREATE INDEX idx_inv_022_rma_assignment_events ON rma_assignment_events(rma_id,recorded_at_utc,assignment_event_id);
CREATE UNIQUE INDEX idx_inv_023_rma_current_assignment ON rma_current_assignment(device_part_unit_id);
CREATE INDEX idx_inv_024_spare_part_units ON spare_part_units(bom_key,serial_key,spare_part_unit_id);
CREATE INDEX idx_inv_025_spare_part_units ON spare_part_units(origin_rma_id,spare_part_unit_id);
CREATE INDEX idx_inv_026_spare_part_units ON spare_part_units(parent_spare_part_unit_id,spare_part_unit_id);
CREATE INDEX idx_inv_027_spare_part_lifecycle_events ON spare_part_lifecycle_events(spare_part_unit_id,recorded_at_utc,unit_event_id);
CREATE INDEX idx_inv_028_spare_part_current_projection ON spare_part_current_projection(disposition_token,condition_token,spare_part_unit_id);
CREATE INDEX idx_inv_029_task_unit_allocation_events ON task_unit_allocation_events(task_id,recorded_at_utc,allocation_event_id);
CREATE INDEX idx_inv_030_task_unit_allocation_events ON task_unit_allocation_events(spare_part_unit_id,recorded_at_utc,allocation_event_id);
CREATE INDEX idx_inv_031_task_unit_allocation_current ON task_unit_allocation_current(task_id,allocation_id);
CREATE UNIQUE INDEX idx_inv_032_task_unit_allocation_current ON task_unit_allocation_current(spare_part_unit_id);
CREATE INDEX idx_inv_033_local_need_fulfillment_events ON local_need_fulfillment_events(spare_need_id,recorded_at_utc,local_fulfillment_event_id);
CREATE INDEX idx_inv_034_inventory_physical_consequences ON inventory_physical_consequences(task_id,target_device_part_unit_id,physical_consequence_id);
CREATE INDEX idx_inv_035_inventory_physical_consequences ON inventory_physical_consequences(rma_id,physical_consequence_id);
CREATE INDEX idx_inv_036_physical_consequence_events ON physical_consequence_events(physical_consequence_id,recorded_at_utc,consequence_event_id);
CREATE INDEX idx_inv_037_rma_return_selection_events ON rma_return_selection_events(rma_id,recorded_at_utc,return_selection_event_id);
CREATE INDEX idx_inv_038_rma_return_obligation_current ON rma_return_obligation_current(obligation_state,rma_id);
CREATE INDEX idx_inv_039_actual_logistics_events ON actual_logistics_events(event_kind,recorded_at_utc,logistics_event_id);
CREATE INDEX idx_inv_040_logistics_rma_participants ON logistics_rma_participants(rma_id,active,logistics_event_id);
CREATE INDEX idx_inv_041_logistics_spare_unit_participants ON logistics_spare_unit_participants(spare_part_unit_id,active,logistics_event_id);
CREATE INDEX idx_inv_042_logistics_device_part_participants ON logistics_device_part_participants(device_part_unit_id,active,logistics_event_id);
CREATE INDEX idx_inv_043_fault_tag_memberships ON fault_tag_memberships(fault_tag_id,fault_tag_membership_id);
CREATE INDEX idx_inv_044_fault_tag_memberships ON fault_tag_memberships(rma_id,fault_tag_membership_id);
CREATE INDEX idx_inv_045_fault_tag_lifecycle_events ON fault_tag_lifecycle_events(fault_tag_id,recorded_at_utc,fault_tag_event_id);
CREATE INDEX idx_inv_046_fault_tag_submission_snapshots ON fault_tag_submission_snapshots(fault_tag_id,recorded_at_utc,fault_tag_submission_snapshot_id);
CREATE UNIQUE INDEX idx_inv_047_fault_tag_membership_submission_snapshots ON fault_tag_membership_submission_snapshots(fault_tag_submission_snapshot_id,fault_tag_membership_id);
CREATE INDEX idx_inv_048_fault_tag_membership_submission_snapshots ON fault_tag_membership_submission_snapshots(fault_tag_membership_id,membership_snapshot_id);
CREATE INDEX idx_inv_049_fault_tag_membership_events ON fault_tag_membership_events(fault_tag_membership_id,recorded_at_utc,membership_event_id);
CREATE INDEX idx_inv_050_fault_tag_membership_current ON fault_tag_membership_current(fault_tag_id,state,fault_tag_membership_id);
CREATE UNIQUE INDEX idx_inv_051_fault_tag_membership_current ON fault_tag_membership_current(rma_id) WHERE active_submitted=1;
CREATE UNIQUE INDEX idx_inv_052_fault_tag_membership_current ON fault_tag_membership_current(device_part_unit_id) WHERE active_submitted=1 AND device_part_unit_id IS NOT NULL;
CREATE UNIQUE INDEX idx_inv_053_fault_tag_membership_current ON fault_tag_membership_current(spare_part_unit_id) WHERE active_submitted=1 AND spare_part_unit_id IS NOT NULL;
CREATE INDEX idx_inv_054_fault_tag_lineage ON fault_tag_lineage(predecessor_fault_tag_id,relation_type,fault_tag_lineage_id);
CREATE UNIQUE INDEX idx_inv_055_fault_tag_lineage ON fault_tag_lineage(successor_fault_tag_id) WHERE relation_type='corrects_replaces';
CREATE UNIQUE INDEX idx_inv_056_fault_tag_lineage ON fault_tag_lineage(predecessor_fault_tag_id) WHERE relation_type='corrects_replaces';
CREATE UNIQUE INDEX idx_inv_057_fault_tag_lineage ON fault_tag_lineage(successor_fault_tag_id) WHERE relation_type='resend_of';
CREATE INDEX idx_inv_058_rma_lifecycle_projection ON rma_lifecycle_projection(state,return_obligation_open,rma_id);
CREATE INDEX idx_inv_059_rma_lifecycle_projection ON rma_lifecycle_projection(current_target_device_part_unit_id,rma_id);
CREATE INDEX idx_inv_060_rma_lifecycle_projection ON rma_lifecycle_projection(direct_inbound_spare_part_unit_id,rma_id);
CREATE INDEX idx_inv_061_rma_lifecycle_projection ON rma_lifecycle_projection(active_fault_tag_membership_id,rma_id);
CREATE UNIQUE INDEX idx_inv_062_inventory_proposals ON inventory_proposals(evidence_kind,evidence_id,source_proposal_key);
CREATE INDEX idx_inv_063_inventory_proposals ON inventory_proposals(state,created_at_utc,inventory_proposal_id);
CREATE INDEX idx_inv_064_inventory_proposal_targets ON inventory_proposal_targets(inventory_proposal_id,inventory_proposal_target_id);
CREATE INDEX idx_inv_065_inventory_proposal_targets ON inventory_proposal_targets(spare_request_id,inventory_proposal_id);
CREATE INDEX idx_inv_066_inventory_proposal_targets ON inventory_proposal_targets(rma_id,inventory_proposal_id);
CREATE INDEX idx_inv_067_inventory_proposal_targets ON inventory_proposal_targets(fault_tag_membership_id,inventory_proposal_id);
CREATE INDEX idx_inv_068_inventory_attention_projection ON inventory_attention_projection(attention_kind,severity,target_id);

CREATE INDEX idx_inv_fk_inventory_tracking_allocators_last_command_id ON inventory_tracking_allocators(last_command_id);
CREATE INDEX idx_inv_fk_device_part_units_service_request_id ON device_part_units(service_request_id);
CREATE INDEX idx_inv_fk_device_part_units_device_reference_id ON device_part_units(device_reference_id);
CREATE INDEX idx_inv_fk_device_part_units_created_command_id ON device_part_units(created_command_id);
CREATE INDEX idx_inv_fk_device_part_lifecycle_events_device_part_unit_id ON device_part_lifecycle_events(device_part_unit_id);
CREATE INDEX idx_inv_fk_device_part_lifecycle_events_target_event_id ON device_part_lifecycle_events(target_event_id);
CREATE INDEX idx_inv_fk_device_part_lifecycle_events_command_id ON device_part_lifecycle_events(command_id);
CREATE INDEX idx_inv_fk_device_part_current_projection_device_part_unit_id ON device_part_current_projection(device_part_unit_id);
CREATE INDEX idx_inv_fk_device_part_current_projection_last_event_id ON device_part_current_projection(last_event_id);
CREATE INDEX idx_inv_fk_device_part_current_projection_last_command_id ON device_part_current_projection(last_command_id);
CREATE INDEX idx_inv_fk_spare_needs_service_request_id ON spare_needs(service_request_id);
CREATE INDEX idx_inv_fk_spare_needs_created_command_id ON spare_needs(created_command_id);
CREATE INDEX idx_inv_fk_spare_need_lifecycle_events_spare_need_id ON spare_need_lifecycle_events(spare_need_id);
CREATE INDEX idx_inv_fk_spare_need_lifecycle_events_command_id ON spare_need_lifecycle_events(command_id);
CREATE INDEX idx_inv_fk_spare_need_current_projection_spare_need_id ON spare_need_current_projection(spare_need_id);
CREATE INDEX idx_inv_fk_spare_need_current_projection_last_command_id ON spare_need_current_projection(last_command_id);
CREATE INDEX idx_inv_fk_spare_need_active_keys_service_request_id ON spare_need_active_keys(service_request_id);
CREATE INDEX idx_inv_fk_spare_need_active_keys_spare_need_id ON spare_need_active_keys(spare_need_id);
CREATE INDEX idx_inv_fk_spare_need_contributors_spare_need_id ON spare_need_contributors(spare_need_id);
CREATE INDEX idx_inv_fk_spare_need_contributors_device_part_unit_id ON spare_need_contributors(device_part_unit_id);
CREATE INDEX idx_inv_fk_spare_need_contributors_opened_command_id ON spare_need_contributors(opened_command_id);
CREATE INDEX idx_inv_fk_spare_need_contributors_closed_command_id ON spare_need_contributors(closed_command_id);
CREATE INDEX idx_inv_fk_spare_requests_service_request_id ON spare_requests(service_request_id);
CREATE INDEX idx_inv_fk_spare_requests_requester_contact_id ON spare_requests(requester_contact_id);
CREATE INDEX idx_inv_fk_spare_requests_created_command_id ON spare_requests(created_command_id);
CREATE INDEX idx_inv_fk_spare_request_need_allocations_spare_request_id ON spare_request_need_allocations(spare_request_id);
CREATE INDEX idx_inv_fk_spare_request_need_allocations_spare_need_id ON spare_request_need_allocations(spare_need_id);
CREATE INDEX idx_inv_fk_spare_request_need_allocations_created_command_id ON spare_request_need_allocations(created_command_id);
CREATE INDEX idx_inv_fk_spare_request_need_allocations_last_command_id ON spare_request_need_allocations(last_command_id);
CREATE INDEX idx_inv_fk_spare_request_draft_logistics_spare_request_id ON spare_request_draft_logistics(spare_request_id);
CREATE INDEX idx_inv_fk_spare_request_draft_logistics_receiver_contact_id ON spare_request_draft_logistics(receiver_contact_id);
CREATE INDEX idx_inv_fk_spare_request_draft_logistics_dispatch_location_id ON spare_request_draft_logistics(dispatch_location_id);
CREATE INDEX idx_inv_fk_spare_request_draft_logistics_last_command_id ON spare_request_draft_logistics(last_command_id);
CREATE INDEX idx_inv_fk_spare_request_lifecycle_events_spare_request_id ON spare_request_lifecycle_events(spare_request_id);
CREATE INDEX idx_inv_fk_spare_request_lifecycle_events_target_event_id ON spare_request_lifecycle_events(target_event_id);
CREATE INDEX idx_inv_fk_spare_request_lifecycle_events_command_id ON spare_request_lifecycle_events(command_id);
CREATE INDEX idx_inv_fk_spare_request_identifier_events_spare_request_id ON spare_request_identifier_events(spare_request_id);
CREATE INDEX idx_inv_fk_spare_request_identifier_events_command_id ON spare_request_identifier_events(command_id);
CREATE INDEX idx_inv_fk_spare_request_identifier_aliases_spare_request_id ON spare_request_identifier_aliases(spare_request_id);
CREATE INDEX idx_inv_fk_spare_request_identifier_aliases_source_identifier_event_id ON spare_request_identifier_aliases(source_identifier_event_id);
CREATE INDEX idx_inv_fk_spare_request_submission_snapshots_spare_request_id ON spare_request_submission_snapshots(spare_request_id);
CREATE INDEX idx_inv_fk_spare_request_submission_snapshots_submission_event_id ON spare_request_submission_snapshots(submission_event_id);
CREATE INDEX idx_inv_fk_spare_request_submission_snapshots_receiver_contact_id ON spare_request_submission_snapshots(receiver_contact_id);
CREATE INDEX idx_inv_fk_spare_request_submission_snapshots_dispatch_location_id ON spare_request_submission_snapshots(dispatch_location_id);
CREATE INDEX idx_inv_fk_spare_request_submission_allocations_submission_snapshot_id ON spare_request_submission_allocations(submission_snapshot_id);
CREATE INDEX idx_inv_fk_spare_request_submission_allocations_request_need_allocation_id ON spare_request_submission_allocations(request_need_allocation_id);
CREATE INDEX idx_inv_fk_spare_request_submission_allocations_spare_need_id ON spare_request_submission_allocations(spare_need_id);
CREATE INDEX idx_inv_fk_spare_request_current_projection_spare_request_id ON spare_request_current_projection(spare_request_id);
CREATE INDEX idx_inv_fk_spare_request_current_projection_current_submission_snapshot_id ON spare_request_current_projection(current_submission_snapshot_id);
CREATE INDEX idx_inv_fk_spare_request_current_projection_last_command_id ON spare_request_current_projection(last_command_id);
CREATE INDEX idx_inv_fk_rma_authorization_batches_spare_request_id ON rma_authorization_batches(spare_request_id);
CREATE INDEX idx_inv_fk_rma_authorization_batches_command_id ON rma_authorization_batches(command_id);
CREATE INDEX idx_inv_fk_rmas_spare_request_id ON rmas(spare_request_id);
CREATE INDEX idx_inv_fk_rmas_authorization_batch_id ON rmas(authorization_batch_id);
CREATE INDEX idx_inv_fk_rmas_created_command_id ON rmas(created_command_id);
CREATE INDEX idx_inv_fk_rma_identifier_events_rma_id ON rma_identifier_events(rma_id);
CREATE INDEX idx_inv_fk_rma_identifier_events_command_id ON rma_identifier_events(command_id);
CREATE INDEX idx_inv_fk_rma_identifier_aliases_rma_id ON rma_identifier_aliases(rma_id);
CREATE INDEX idx_inv_fk_rma_identifier_aliases_source_identifier_event_id ON rma_identifier_aliases(source_identifier_event_id);
CREATE INDEX idx_inv_fk_rma_assignment_events_rma_id ON rma_assignment_events(rma_id);
CREATE INDEX idx_inv_fk_rma_assignment_events_prior_device_part_unit_id ON rma_assignment_events(prior_device_part_unit_id);
CREATE INDEX idx_inv_fk_rma_assignment_events_new_device_part_unit_id ON rma_assignment_events(new_device_part_unit_id);
CREATE INDEX idx_inv_fk_rma_assignment_events_command_id ON rma_assignment_events(command_id);
CREATE INDEX idx_inv_fk_rma_current_assignment_rma_id ON rma_current_assignment(rma_id);
CREATE INDEX idx_inv_fk_rma_current_assignment_device_part_unit_id ON rma_current_assignment(device_part_unit_id);
CREATE INDEX idx_inv_fk_rma_current_assignment_assignment_event_id ON rma_current_assignment(assignment_event_id);
CREATE INDEX idx_inv_fk_rma_current_assignment_last_command_id ON rma_current_assignment(last_command_id);
CREATE INDEX idx_inv_fk_spare_part_units_origin_rma_id ON spare_part_units(origin_rma_id);
CREATE INDEX idx_inv_fk_spare_part_units_parent_spare_part_unit_id ON spare_part_units(parent_spare_part_unit_id);
CREATE INDEX idx_inv_fk_spare_part_units_created_command_id ON spare_part_units(created_command_id);
CREATE INDEX idx_inv_fk_rma_direct_inbound_units_rma_id ON rma_direct_inbound_units(rma_id);
CREATE INDEX idx_inv_fk_rma_direct_inbound_units_spare_part_unit_id ON rma_direct_inbound_units(spare_part_unit_id);
CREATE INDEX idx_inv_fk_rma_direct_inbound_units_opened_command_id ON rma_direct_inbound_units(opened_command_id);
CREATE INDEX idx_inv_fk_spare_part_lifecycle_events_spare_part_unit_id ON spare_part_lifecycle_events(spare_part_unit_id);
CREATE INDEX idx_inv_fk_spare_part_lifecycle_events_target_event_id ON spare_part_lifecycle_events(target_event_id);
CREATE INDEX idx_inv_fk_spare_part_lifecycle_events_command_id ON spare_part_lifecycle_events(command_id);
CREATE INDEX idx_inv_fk_spare_part_current_projection_spare_part_unit_id ON spare_part_current_projection(spare_part_unit_id);
CREATE INDEX idx_inv_fk_spare_part_current_projection_last_command_id ON spare_part_current_projection(last_command_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_events_task_id ON task_unit_allocation_events(task_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_events_spare_part_unit_id ON task_unit_allocation_events(spare_part_unit_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_events_spare_need_id ON task_unit_allocation_events(spare_need_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_events_prior_task_id ON task_unit_allocation_events(prior_task_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_events_target_event_id ON task_unit_allocation_events(target_event_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_events_command_id ON task_unit_allocation_events(command_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_current_task_id ON task_unit_allocation_current(task_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_current_spare_part_unit_id ON task_unit_allocation_current(spare_part_unit_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_current_spare_need_id ON task_unit_allocation_current(spare_need_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_current_last_event_id ON task_unit_allocation_current(last_event_id);
CREATE INDEX idx_inv_fk_task_unit_allocation_current_last_command_id ON task_unit_allocation_current(last_command_id);
CREATE INDEX idx_inv_fk_local_need_fulfillment_events_spare_need_id ON local_need_fulfillment_events(spare_need_id);
CREATE INDEX idx_inv_fk_local_need_fulfillment_events_spare_part_unit_id ON local_need_fulfillment_events(spare_part_unit_id);
CREATE INDEX idx_inv_fk_local_need_fulfillment_events_task_id ON local_need_fulfillment_events(task_id);
CREATE INDEX idx_inv_fk_local_need_fulfillment_events_command_id ON local_need_fulfillment_events(command_id);
CREATE INDEX idx_inv_fk_inventory_physical_consequences_task_id ON inventory_physical_consequences(task_id);
CREATE INDEX idx_inv_fk_inventory_physical_consequences_target_device_part_unit_id ON inventory_physical_consequences(target_device_part_unit_id);
CREATE INDEX idx_inv_fk_inventory_physical_consequences_rma_id ON inventory_physical_consequences(rma_id);
CREATE INDEX idx_inv_fk_inventory_physical_consequences_created_command_id ON inventory_physical_consequences(created_command_id);
CREATE INDEX idx_inv_fk_physical_consequence_events_physical_consequence_id ON physical_consequence_events(physical_consequence_id);
CREATE INDEX idx_inv_fk_physical_consequence_events_installed_spare_part_unit_id ON physical_consequence_events(installed_spare_part_unit_id);
CREATE INDEX idx_inv_fk_physical_consequence_events_removed_device_part_unit_id ON physical_consequence_events(removed_device_part_unit_id);
CREATE INDEX idx_inv_fk_physical_consequence_events_inbound_spare_part_unit_id ON physical_consequence_events(inbound_spare_part_unit_id);
CREATE INDEX idx_inv_fk_physical_consequence_events_parent_dismantled_unit_id ON physical_consequence_events(parent_dismantled_unit_id);
CREATE INDEX idx_inv_fk_physical_consequence_events_target_event_id ON physical_consequence_events(target_event_id);
CREATE INDEX idx_inv_fk_physical_consequence_events_command_id ON physical_consequence_events(command_id);
CREATE INDEX idx_inv_fk_physical_consequence_current_physical_consequence_id ON physical_consequence_current(physical_consequence_id);
CREATE INDEX idx_inv_fk_physical_consequence_current_installed_spare_part_unit_id ON physical_consequence_current(installed_spare_part_unit_id);
CREATE INDEX idx_inv_fk_physical_consequence_current_removed_device_part_unit_id ON physical_consequence_current(removed_device_part_unit_id);
CREATE INDEX idx_inv_fk_physical_consequence_current_inbound_spare_part_unit_id ON physical_consequence_current(inbound_spare_part_unit_id);
CREATE INDEX idx_inv_fk_physical_consequence_current_parent_dismantled_unit_id ON physical_consequence_current(parent_dismantled_unit_id);
CREATE INDEX idx_inv_fk_physical_consequence_current_last_event_id ON physical_consequence_current(last_event_id);
CREATE INDEX idx_inv_fk_physical_consequence_current_last_command_id ON physical_consequence_current(last_command_id);
CREATE INDEX idx_inv_fk_rma_return_selection_events_rma_id ON rma_return_selection_events(rma_id);
CREATE INDEX idx_inv_fk_rma_return_selection_events_physical_consequence_id ON rma_return_selection_events(physical_consequence_id);
CREATE INDEX idx_inv_fk_rma_return_selection_events_device_part_unit_id ON rma_return_selection_events(device_part_unit_id);
CREATE INDEX idx_inv_fk_rma_return_selection_events_spare_part_unit_id ON rma_return_selection_events(spare_part_unit_id);
CREATE INDEX idx_inv_fk_rma_return_selection_events_target_event_id ON rma_return_selection_events(target_event_id);
CREATE INDEX idx_inv_fk_rma_return_selection_events_command_id ON rma_return_selection_events(command_id);
CREATE INDEX idx_inv_fk_rma_return_obligation_current_rma_id ON rma_return_obligation_current(rma_id);
CREATE INDEX idx_inv_fk_rma_return_obligation_current_device_part_unit_id ON rma_return_obligation_current(device_part_unit_id);
CREATE INDEX idx_inv_fk_rma_return_obligation_current_spare_part_unit_id ON rma_return_obligation_current(spare_part_unit_id);
CREATE INDEX idx_inv_fk_rma_return_obligation_current_physical_consequence_id ON rma_return_obligation_current(physical_consequence_id);
CREATE INDEX idx_inv_fk_rma_return_obligation_current_last_event_id ON rma_return_obligation_current(last_event_id);
CREATE INDEX idx_inv_fk_rma_return_obligation_current_last_command_id ON rma_return_obligation_current(last_command_id);
CREATE INDEX idx_inv_fk_actual_logistics_events_dispatch_location_id ON actual_logistics_events(dispatch_location_id);
CREATE INDEX idx_inv_fk_actual_logistics_events_receiver_contact_id ON actual_logistics_events(receiver_contact_id);
CREATE INDEX idx_inv_fk_actual_logistics_events_target_event_id ON actual_logistics_events(target_event_id);
CREATE INDEX idx_inv_fk_actual_logistics_events_command_id ON actual_logistics_events(command_id);
CREATE INDEX idx_inv_fk_logistics_rma_participants_logistics_event_id ON logistics_rma_participants(logistics_event_id);
CREATE INDEX idx_inv_fk_logistics_rma_participants_rma_id ON logistics_rma_participants(rma_id);
CREATE INDEX idx_inv_fk_logistics_rma_participants_opened_command_id ON logistics_rma_participants(opened_command_id);
CREATE INDEX idx_inv_fk_logistics_rma_participants_closed_command_id ON logistics_rma_participants(closed_command_id);
CREATE INDEX idx_inv_fk_logistics_spare_unit_participants_logistics_event_id ON logistics_spare_unit_participants(logistics_event_id);
CREATE INDEX idx_inv_fk_logistics_spare_unit_participants_spare_part_unit_id ON logistics_spare_unit_participants(spare_part_unit_id);
CREATE INDEX idx_inv_fk_logistics_spare_unit_participants_opened_command_id ON logistics_spare_unit_participants(opened_command_id);
CREATE INDEX idx_inv_fk_logistics_spare_unit_participants_closed_command_id ON logistics_spare_unit_participants(closed_command_id);
CREATE INDEX idx_inv_fk_logistics_device_part_participants_logistics_event_id ON logistics_device_part_participants(logistics_event_id);
CREATE INDEX idx_inv_fk_logistics_device_part_participants_device_part_unit_id ON logistics_device_part_participants(device_part_unit_id);
CREATE INDEX idx_inv_fk_logistics_device_part_participants_opened_command_id ON logistics_device_part_participants(opened_command_id);
CREATE INDEX idx_inv_fk_logistics_device_part_participants_closed_command_id ON logistics_device_part_participants(closed_command_id);
CREATE INDEX idx_inv_fk_fault_tags_draft_pickup_dispatch_location_id ON fault_tags(draft_pickup_dispatch_location_id);
CREATE INDEX idx_inv_fk_fault_tags_draft_pickup_contact_id ON fault_tags(draft_pickup_contact_id);
CREATE INDEX idx_inv_fk_fault_tags_created_command_id ON fault_tags(created_command_id);
CREATE INDEX idx_inv_fk_fault_tag_memberships_fault_tag_id ON fault_tag_memberships(fault_tag_id);
CREATE INDEX idx_inv_fk_fault_tag_memberships_rma_id ON fault_tag_memberships(rma_id);
CREATE INDEX idx_inv_fk_fault_tag_memberships_physical_consequence_id ON fault_tag_memberships(physical_consequence_id);
CREATE INDEX idx_inv_fk_fault_tag_memberships_device_part_unit_id ON fault_tag_memberships(device_part_unit_id);
CREATE INDEX idx_inv_fk_fault_tag_memberships_spare_part_unit_id ON fault_tag_memberships(spare_part_unit_id);
CREATE INDEX idx_inv_fk_fault_tag_memberships_created_command_id ON fault_tag_memberships(created_command_id);
CREATE INDEX idx_inv_fk_fault_tag_lifecycle_events_fault_tag_id ON fault_tag_lifecycle_events(fault_tag_id);
CREATE INDEX idx_inv_fk_fault_tag_lifecycle_events_target_event_id ON fault_tag_lifecycle_events(target_event_id);
CREATE INDEX idx_inv_fk_fault_tag_lifecycle_events_command_id ON fault_tag_lifecycle_events(command_id);
CREATE INDEX idx_inv_fk_fault_tag_submission_snapshots_fault_tag_id ON fault_tag_submission_snapshots(fault_tag_id);
CREATE INDEX idx_inv_fk_fault_tag_submission_snapshots_submission_event_id ON fault_tag_submission_snapshots(submission_event_id);
CREATE INDEX idx_inv_fk_fault_tag_submission_snapshots_pickup_dispatch_location_id ON fault_tag_submission_snapshots(pickup_dispatch_location_id);
CREATE INDEX idx_inv_fk_fault_tag_submission_snapshots_pickup_contact_id ON fault_tag_submission_snapshots(pickup_contact_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_submission_snapshots_fault_tag_submission_snapshot_id ON fault_tag_membership_submission_snapshots(fault_tag_submission_snapshot_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_submission_snapshots_fault_tag_membership_id ON fault_tag_membership_submission_snapshots(fault_tag_membership_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_submission_snapshots_rma_id ON fault_tag_membership_submission_snapshots(rma_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_submission_snapshots_device_part_unit_id ON fault_tag_membership_submission_snapshots(device_part_unit_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_submission_snapshots_spare_part_unit_id ON fault_tag_membership_submission_snapshots(spare_part_unit_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_submission_snapshots_physical_consequence_id ON fault_tag_membership_submission_snapshots(physical_consequence_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_events_fault_tag_membership_id ON fault_tag_membership_events(fault_tag_membership_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_events_target_event_id ON fault_tag_membership_events(target_event_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_events_command_id ON fault_tag_membership_events(command_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_current_fault_tag_membership_id ON fault_tag_membership_current(fault_tag_membership_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_current_fault_tag_id ON fault_tag_membership_current(fault_tag_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_current_rma_id ON fault_tag_membership_current(rma_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_current_device_part_unit_id ON fault_tag_membership_current(device_part_unit_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_current_spare_part_unit_id ON fault_tag_membership_current(spare_part_unit_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_current_last_event_id ON fault_tag_membership_current(last_event_id);
CREATE INDEX idx_inv_fk_fault_tag_membership_current_last_command_id ON fault_tag_membership_current(last_command_id);
CREATE INDEX idx_inv_fk_fault_tag_current_projection_fault_tag_id ON fault_tag_current_projection(fault_tag_id);
CREATE INDEX idx_inv_fk_fault_tag_current_projection_current_submission_snapshot_id ON fault_tag_current_projection(current_submission_snapshot_id);
CREATE INDEX idx_inv_fk_fault_tag_current_projection_last_command_id ON fault_tag_current_projection(last_command_id);
CREATE INDEX idx_inv_fk_fault_tag_lineage_predecessor_fault_tag_id ON fault_tag_lineage(predecessor_fault_tag_id);
CREATE INDEX idx_inv_fk_fault_tag_lineage_successor_fault_tag_id ON fault_tag_lineage(successor_fault_tag_id);
CREATE INDEX idx_inv_fk_fault_tag_lineage_command_id ON fault_tag_lineage(command_id);
CREATE INDEX idx_inv_fk_rma_lifecycle_projection_rma_id ON rma_lifecycle_projection(rma_id);
CREATE INDEX idx_inv_fk_rma_lifecycle_projection_current_target_device_part_unit_id ON rma_lifecycle_projection(current_target_device_part_unit_id);
CREATE INDEX idx_inv_fk_rma_lifecycle_projection_direct_inbound_spare_part_unit_id ON rma_lifecycle_projection(direct_inbound_spare_part_unit_id);
CREATE INDEX idx_inv_fk_rma_lifecycle_projection_return_device_part_unit_id ON rma_lifecycle_projection(return_device_part_unit_id);
CREATE INDEX idx_inv_fk_rma_lifecycle_projection_return_spare_part_unit_id ON rma_lifecycle_projection(return_spare_part_unit_id);
CREATE INDEX idx_inv_fk_rma_lifecycle_projection_active_fault_tag_membership_id ON rma_lifecycle_projection(active_fault_tag_membership_id);
CREATE INDEX idx_inv_fk_rma_lifecycle_projection_last_command_id ON rma_lifecycle_projection(last_command_id);
CREATE INDEX idx_inv_fk_inventory_lifecycle_batches_command_id ON inventory_lifecycle_batches(command_id);
CREATE INDEX idx_inv_fk_inventory_proposals_last_command_id ON inventory_proposals(last_command_id);
CREATE INDEX idx_inv_fk_inventory_proposal_targets_inventory_proposal_id ON inventory_proposal_targets(inventory_proposal_id);
CREATE INDEX idx_inv_fk_inventory_proposal_targets_spare_request_id ON inventory_proposal_targets(spare_request_id);
CREATE INDEX idx_inv_fk_inventory_proposal_targets_rma_id ON inventory_proposal_targets(rma_id);
CREATE INDEX idx_inv_fk_inventory_proposal_targets_spare_part_unit_id ON inventory_proposal_targets(spare_part_unit_id);
CREATE INDEX idx_inv_fk_inventory_proposal_targets_fault_tag_id ON inventory_proposal_targets(fault_tag_id);
CREATE INDEX idx_inv_fk_inventory_proposal_targets_fault_tag_membership_id ON inventory_proposal_targets(fault_tag_membership_id);
CREATE INDEX idx_inv_fk_inventory_attention_projection_last_command_id ON inventory_attention_projection(last_command_id);

CREATE TRIGGER inv_device_part_lifecycle_events_update_guard
BEFORE UPDATE ON device_part_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_DEVICE_PART_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_device_part_lifecycle_events_delete_guard
BEFORE DELETE ON device_part_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_DEVICE_PART_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_need_lifecycle_events_update_guard
BEFORE UPDATE ON spare_need_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_NEED_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_need_lifecycle_events_delete_guard
BEFORE DELETE ON spare_need_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_NEED_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_request_lifecycle_events_update_guard
BEFORE UPDATE ON spare_request_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_request_lifecycle_events_delete_guard
BEFORE DELETE ON spare_request_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_request_identifier_events_update_guard
BEFORE UPDATE ON spare_request_identifier_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_IDENTIFIER_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_request_identifier_events_delete_guard
BEFORE DELETE ON spare_request_identifier_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_IDENTIFIER_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_request_submission_snapshots_update_guard
BEFORE UPDATE ON spare_request_submission_snapshots BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_SUBMISSION_SNAPSHOTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_request_submission_snapshots_delete_guard
BEFORE DELETE ON spare_request_submission_snapshots BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_SUBMISSION_SNAPSHOTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_request_submission_allocations_update_guard
BEFORE UPDATE ON spare_request_submission_allocations BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_SUBMISSION_ALLOCATIONS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_request_submission_allocations_delete_guard
BEFORE DELETE ON spare_request_submission_allocations BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_REQUEST_SUBMISSION_ALLOCATIONS_IMMUTABLE');
END;
CREATE TRIGGER inv_rma_identifier_events_update_guard
BEFORE UPDATE ON rma_identifier_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_RMA_IDENTIFIER_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_rma_identifier_events_delete_guard
BEFORE DELETE ON rma_identifier_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_RMA_IDENTIFIER_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_rma_assignment_events_update_guard
BEFORE UPDATE ON rma_assignment_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_RMA_ASSIGNMENT_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_rma_assignment_events_delete_guard
BEFORE DELETE ON rma_assignment_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_RMA_ASSIGNMENT_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_part_lifecycle_events_update_guard
BEFORE UPDATE ON spare_part_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_PART_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_spare_part_lifecycle_events_delete_guard
BEFORE DELETE ON spare_part_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_SPARE_PART_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_task_unit_allocation_events_update_guard
BEFORE UPDATE ON task_unit_allocation_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_TASK_UNIT_ALLOCATION_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_task_unit_allocation_events_delete_guard
BEFORE DELETE ON task_unit_allocation_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_TASK_UNIT_ALLOCATION_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_physical_consequence_events_update_guard
BEFORE UPDATE ON physical_consequence_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_PHYSICAL_CONSEQUENCE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_physical_consequence_events_delete_guard
BEFORE DELETE ON physical_consequence_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_PHYSICAL_CONSEQUENCE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_rma_return_selection_events_update_guard
BEFORE UPDATE ON rma_return_selection_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_RMA_RETURN_SELECTION_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_rma_return_selection_events_delete_guard
BEFORE DELETE ON rma_return_selection_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_RMA_RETURN_SELECTION_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_actual_logistics_events_update_guard
BEFORE UPDATE ON actual_logistics_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_ACTUAL_LOGISTICS_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_actual_logistics_events_delete_guard
BEFORE DELETE ON actual_logistics_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_ACTUAL_LOGISTICS_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_fault_tag_lifecycle_events_update_guard
BEFORE UPDATE ON fault_tag_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_fault_tag_lifecycle_events_delete_guard
BEFORE DELETE ON fault_tag_lifecycle_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_LIFECYCLE_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_fault_tag_submission_snapshots_update_guard
BEFORE UPDATE ON fault_tag_submission_snapshots BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_SUBMISSION_SNAPSHOTS_IMMUTABLE');
END;
CREATE TRIGGER inv_fault_tag_submission_snapshots_delete_guard
BEFORE DELETE ON fault_tag_submission_snapshots BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_SUBMISSION_SNAPSHOTS_IMMUTABLE');
END;
CREATE TRIGGER inv_fault_tag_membership_submission_snapshots_update_guard
BEFORE UPDATE ON fault_tag_membership_submission_snapshots BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_MEMBERSHIP_SUBMISSION_SNAPSHOTS_IMMUTABLE');
END;
CREATE TRIGGER inv_fault_tag_membership_submission_snapshots_delete_guard
BEFORE DELETE ON fault_tag_membership_submission_snapshots BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_MEMBERSHIP_SUBMISSION_SNAPSHOTS_IMMUTABLE');
END;
CREATE TRIGGER inv_fault_tag_membership_events_update_guard
BEFORE UPDATE ON fault_tag_membership_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_MEMBERSHIP_EVENTS_IMMUTABLE');
END;
CREATE TRIGGER inv_fault_tag_membership_events_delete_guard
BEFORE DELETE ON fault_tag_membership_events BEGIN
    SELECT RAISE(ABORT,'INVENTORY_FAULT_TAG_MEMBERSHIP_EVENTS_IMMUTABLE');
END;
