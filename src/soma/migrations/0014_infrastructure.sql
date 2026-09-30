-- LLD-08 Infrastructure; additive migration after the immutable 0013 prefix.
-- Normative design: d3f24ca9752a2ac9cd1a5f9cb9b38dd352681338

CREATE TABLE sites (
    site_id TEXT PRIMARY KEY,
    customer_org_id TEXT NOT NULL REFERENCES customer_organizations(customer_org_id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    name_match_key TEXT NOT NULL,
    address_text TEXT NOT NULL,
    address_match_key TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE site_dispatch_locations (
    site_id TEXT PRIMARY KEY REFERENCES sites(site_id) ON DELETE RESTRICT,
    dispatch_location_id TEXT NOT NULL UNIQUE REFERENCES dispatch_locations(dispatch_location_id) ON DELETE RESTRICT,
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE site_lifecycle_events (
    site_event_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('created','descriptive_corrected','customer_ownership_corrected','archived','reactivated')),
    prior_customer_org_id TEXT NULL REFERENCES customer_organizations(customer_org_id) ON DELETE RESTRICT,
    new_customer_org_id TEXT NULL REFERENCES customer_organizations(customer_org_id) ON DELETE RESTRICT,
    prior_name TEXT NULL,
    new_name TEXT NULL,
    prior_address_text TEXT NULL,
    new_address_text TEXT NULL,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE rooms (
    room_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    name_match_key TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE racks (
    rack_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    name_match_key TEXT NOT NULL,
    height_u INTEGER NOT NULL CHECK(height_u BETWEEN 1 AND 120),
    row_label TEXT NULL,
    column_label TEXT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE room_rack_lifecycle_events (
    placement_reference_event_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('room','rack')),
    room_id TEXT NULL REFERENCES rooms(room_id) ON DELETE RESTRICT,
    rack_id TEXT NULL REFERENCES racks(rack_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('created','descriptive_corrected','archived','reactivated')),
    details_json TEXT NOT NULL CHECK(json_valid(details_json)),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((target_kind='room' AND room_id IS NOT NULL AND rack_id IS NULL) OR (target_kind='rack' AND rack_id IS NOT NULL AND room_id IS NULL))
) STRICT;

CREATE TABLE network_elements (
    network_element_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(site_id) ON DELETE RESTRICT,
    operational_name TEXT NOT NULL,
    name_match_key TEXT NOT NULL,
    manufacturer_serial TEXT NULL,
    serial_match_key TEXT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_lifecycle_events (
    network_element_event_id TEXT PRIMARY KEY,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('created','descriptive_corrected','archived','reactivated')),
    details_json TEXT NOT NULL CHECK(json_valid(details_json)),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_placement_events (
    placement_event_id TEXT PRIMARY KEY,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('place_rack','set_unracked','correct')),
    prior_rack_id TEXT NULL REFERENCES racks(rack_id) ON DELETE RESTRICT,
    new_rack_id TEXT NULL REFERENCES racks(rack_id) ON DELETE RESTRICT,
    prior_u_start INTEGER NULL,
    new_u_start INTEGER NULL,
    prior_u_span INTEGER NULL,
    new_u_span INTEGER NULL,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_placement_current (
    network_element_id TEXT PRIMARY KEY REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    rack_id TEXT NULL REFERENCES racks(rack_id) ON DELETE RESTRICT,
    u_start INTEGER NULL CHECK(u_start IS NULL OR u_start>=1),
    u_span INTEGER NULL CHECK(u_span IS NULL OR u_span>=1),
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES network_element_placement_events(placement_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK((rack_id IS NULL AND u_start IS NULL AND u_span IS NULL) OR (rack_id IS NOT NULL AND u_start IS NOT NULL AND u_span IS NOT NULL))
) STRICT;

CREATE TABLE device_reference_resolution_events (
    resolution_event_id TEXT PRIMARY KEY,
    device_reference_id TEXT NOT NULL REFERENCES device_references(device_reference_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('link','correct','clear')),
    prior_network_element_id TEXT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    new_network_element_id TEXT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE device_reference_resolution_current (
    device_reference_id TEXT PRIMARY KEY REFERENCES device_references(device_reference_id) ON DELETE RESTRICT,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES device_reference_resolution_events(resolution_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_containment_events (
    containment_event_id TEXT PRIMARY KEY,
    child_network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('set_parent','move_parent','clear_parent','correct')),
    prior_parent_network_element_id TEXT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    new_parent_network_element_id TEXT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK(new_parent_network_element_id IS NULL OR new_parent_network_element_id<>child_network_element_id)
) STRICT;

CREATE TABLE network_element_containment_current (
    child_network_element_id TEXT PRIMARY KEY REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    parent_network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES network_element_containment_events(containment_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    CHECK(parent_network_element_id<>child_network_element_id)
) STRICT;

CREATE TABLE cloud_types (
    cloud_type_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_match_key TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE cloud_deployments (
    cloud_deployment_id TEXT PRIMARY KEY,
    cloud_type_id TEXT NOT NULL REFERENCES cloud_types(cloud_type_id) ON DELETE RESTRICT,
    site_id TEXT NOT NULL REFERENCES sites(site_id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    name_match_key TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE cloud_assignment_events (
    cloud_assignment_event_id TEXT PRIMARY KEY,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('assign','change','clear','correct')),
    prior_cloud_deployment_id TEXT NULL REFERENCES cloud_deployments(cloud_deployment_id) ON DELETE RESTRICT,
    new_cloud_deployment_id TEXT NULL REFERENCES cloud_deployments(cloud_deployment_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE cloud_assignment_current (
    network_element_id TEXT PRIMARY KEY REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    cloud_deployment_id TEXT NOT NULL REFERENCES cloud_deployments(cloud_deployment_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES cloud_assignment_events(cloud_assignment_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_ip_identities (
    network_element_ip_id TEXT PRIMARY KEY,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_ip_events (
    ip_event_id TEXT PRIMARY KEY,
    network_element_ip_id TEXT NOT NULL REFERENCES network_element_ip_identities(network_element_ip_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('add','address_corrected','set_primary','unset_primary','remove','reactivate','correction')),
    address_text TEXT NULL,
    canonical_address TEXT NULL,
    ip_family INTEGER NULL CHECK(ip_family IS NULL OR ip_family IN (4,6)),
    target_event_id TEXT NULL REFERENCES network_element_ip_events(ip_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_ip_current (
    network_element_ip_id TEXT PRIMARY KEY REFERENCES network_element_ip_identities(network_element_ip_id) ON DELETE RESTRICT,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    canonical_address TEXT NOT NULL,
    ip_family INTEGER NOT NULL CHECK(ip_family IN (4,6)),
    is_primary INTEGER NOT NULL CHECK(is_primary IN (0,1)),
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES network_element_ip_events(ip_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_models (
    network_element_model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_match_key TEXT NOT NULL,
    manufacturer TEXT NULL,
    manufacturer_match_key TEXT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE model_lifecycle_events (
    model_event_id TEXT PRIMARY KEY,
    network_element_model_id TEXT NOT NULL REFERENCES network_element_models(network_element_model_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('created','descriptive_corrected','archived','reactivated')),
    details_json TEXT NOT NULL CHECK(json_valid(details_json)),
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_model_assignment_events (
    model_assignment_event_id TEXT PRIMARY KEY,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('assign','change','clear','correct')),
    prior_model_id TEXT NULL REFERENCES network_element_models(network_element_model_id) ON DELETE RESTRICT,
    new_model_id TEXT NULL REFERENCES network_element_models(network_element_model_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE network_element_model_current (
    network_element_id TEXT PRIMARY KEY REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    network_element_model_id TEXT NOT NULL REFERENCES network_element_models(network_element_model_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES network_element_model_assignment_events(model_assignment_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE model_bom_compatibility_events (
    compatibility_event_id TEXT PRIMARY KEY,
    compatibility_relation_id TEXT NOT NULL,
    network_element_model_id TEXT NOT NULL REFERENCES network_element_models(network_element_model_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('add','remove','correct')),
    bom_code TEXT NOT NULL,
    bom_key TEXT NOT NULL,
    component_role TEXT NULL,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE model_bom_compatibility_current (
    compatibility_relation_id TEXT PRIMARY KEY,
    network_element_model_id TEXT NOT NULL REFERENCES network_element_models(network_element_model_id) ON DELETE RESTRICT,
    bom_code TEXT NOT NULL,
    bom_key TEXT NOT NULL,
    component_role TEXT NULL,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES model_bom_compatibility_events(compatibility_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE installed_components (
    installed_component_id TEXT PRIMARY KEY,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    creation_origin TEXT NOT NULL CHECK(creation_origin IN ('manual','workbook','maintenance_consequence','legacy_reconciliation')),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    created_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE installed_component_events (
    installed_component_event_id TEXT PRIMARY KEY,
    installed_component_id TEXT NOT NULL REFERENCES installed_components(installed_component_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('registered','installed','removed','descriptive_corrected','condition_changed','correction')),
    bom_code TEXT NULL,
    bom_key TEXT NULL,
    manufacturer_serial TEXT NULL,
    serial_match_key TEXT NULL,
    slot_label TEXT NULL,
    condition_token TEXT NULL CHECK(condition_token IS NULL OR condition_token IN ('unknown','normal','faulty','removed','quarantined')),
    task_id TEXT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    inventory_physical_consequence_id TEXT NULL REFERENCES inventory_physical_consequences(physical_consequence_id) ON DELETE RESTRICT,
    effective_at_utc INTEGER NULL CHECK(effective_at_utc IS NULL OR effective_at_utc>=0),
    target_event_id TEXT NULL REFERENCES installed_component_events(installed_component_event_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE installed_component_current (
    installed_component_id TEXT PRIMARY KEY REFERENCES installed_components(installed_component_id) ON DELETE RESTRICT,
    network_element_id TEXT NOT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK(state IN ('installed','removed','unknown')),
    bom_code TEXT NULL,
    bom_key TEXT NULL,
    manufacturer_serial TEXT NULL,
    serial_match_key TEXT NULL,
    slot_label TEXT NULL,
    slot_match_key TEXT NULL,
    condition_token TEXT NOT NULL CHECK(condition_token IN ('unknown','normal','faulty','removed','quarantined')),
    revision INTEGER NOT NULL CHECK(revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    last_event_id TEXT NOT NULL REFERENCES installed_component_events(installed_component_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE device_part_component_resolution_events (
    resolution_event_id TEXT PRIMARY KEY,
    device_part_unit_id TEXT NOT NULL REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('link','correct','clear')),
    prior_installed_component_id TEXT NULL REFERENCES installed_components(installed_component_id) ON DELETE RESTRICT,
    new_installed_component_id TEXT NULL REFERENCES installed_components(installed_component_id) ON DELETE RESTRICT,
    reason_code TEXT NULL,
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE device_part_component_resolution_current (
    device_part_unit_id TEXT PRIMARY KEY REFERENCES device_part_units(device_part_unit_id) ON DELETE RESTRICT,
    installed_component_id TEXT NOT NULL UNIQUE REFERENCES installed_components(installed_component_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision>0),
    last_event_id TEXT NOT NULL REFERENCES device_part_component_resolution_events(resolution_event_id) ON DELETE RESTRICT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE infrastructure_workbook_exports (
    export_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK(mode IN ('registration_template','discovery','round_trip')),
    installation_scope_id TEXT NOT NULL,
    filter_scope_json TEXT NOT NULL CHECK(json_valid(filter_scope_json)),
    generated_at_utc INTEGER NOT NULL CHECK(generated_at_utc>=0),
    artifact_filename TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
    artifact_size_bytes INTEGER NOT NULL CHECK(artifact_size_bytes>0),
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE infrastructure_workbook_runs (
    workbook_run_id TEXT PRIMARY KEY,
    source_filename TEXT NOT NULL,
    file_sha256 TEXT NOT NULL CHECK(length(file_sha256)=64),
    logical_fingerprint TEXT NOT NULL CHECK(length(logical_fingerprint)=64),
    workbook_version TEXT NOT NULL,
    workbook_mode TEXT NOT NULL CHECK(workbook_mode IN ('registration_template','discovery','round_trip')),
    source_installation_scope_id TEXT NOT NULL,
    installation_relation TEXT NOT NULL CHECK(installation_relation IN ('same_installation','foreign_installation')),
    state TEXT NOT NULL CHECK(state IN ('validating','staged','reviewed','accepted','rejected','failed')),
    network_element_row_count INTEGER NOT NULL DEFAULT 0 CHECK(network_element_row_count>=0),
    ip_row_count INTEGER NOT NULL DEFAULT 0 CHECK(ip_row_count>=0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK(warning_count>=0),
    captured_at_utc INTEGER NOT NULL CHECK(captured_at_utc>=0),
    published_at_utc INTEGER NULL CHECK(published_at_utc IS NULL OR published_at_utc>=captured_at_utc),
    last_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0)
) STRICT;

CREATE TABLE infrastructure_workbook_staging_rows (
    staging_row_id TEXT PRIMARY KEY,
    workbook_run_id TEXT NOT NULL REFERENCES infrastructure_workbook_runs(workbook_run_id) ON DELETE CASCADE,
    sheet_kind TEXT NOT NULL CHECK(sheet_kind IN ('network_elements','ip_addresses')),
    row_ordinal INTEGER NOT NULL CHECK(row_ordinal>=2),
    row_fingerprint TEXT NOT NULL CHECK(length(row_fingerprint)=64),
    normalized_row_json TEXT NOT NULL CHECK(json_valid(normalized_row_json)),
    validation_state TEXT NOT NULL CHECK(validation_state IN ('valid','warning','invalid')),
    warning_codes_json TEXT NOT NULL CHECK(json_valid(warning_codes_json))
) STRICT;

CREATE TABLE infrastructure_workbook_proposals (
    proposal_id TEXT PRIMARY KEY,
    workbook_run_id TEXT NOT NULL REFERENCES infrastructure_workbook_runs(workbook_run_id) ON DELETE RESTRICT,
    staging_row_id TEXT NOT NULL REFERENCES infrastructure_workbook_staging_rows(staging_row_id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK(action IN ('create_network_element','update_network_element','create_related_reference','update_ip_set','unchanged','skip_invalid','ambiguous','unknown_reference','relationship_change')),
    state TEXT NOT NULL CHECK(state IN ('pending','accepted','rejected','superseded')),
    target_network_element_id TEXT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    expected_target_revision INTEGER NULL CHECK(expected_target_revision IS NULL OR expected_target_revision>0),
    input_fingerprint TEXT NOT NULL CHECK(length(input_fingerprint)=64),
    impact_json TEXT NOT NULL CHECK(json_valid(impact_json)),
    created_at_utc INTEGER NOT NULL CHECK(created_at_utc>=0),
    last_command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0)
) STRICT;

CREATE TABLE infrastructure_workbook_row_decisions (
    row_decision_id TEXT PRIMARY KEY,
    workbook_run_id TEXT NOT NULL REFERENCES infrastructure_workbook_runs(workbook_run_id) ON DELETE RESTRICT,
    sheet_kind TEXT NOT NULL CHECK(sheet_kind IN ('network_elements','ip_addresses')),
    row_ordinal INTEGER NOT NULL CHECK(row_ordinal>=2),
    row_fingerprint TEXT NOT NULL CHECK(length(row_fingerprint)=64),
    disposition TEXT NOT NULL CHECK(disposition IN ('created','updated','unchanged','rejected','skipped_invalid','ambiguous','unknown_reference','failed')),
    target_network_element_id TEXT NULL REFERENCES network_elements(network_element_id) ON DELETE RESTRICT,
    warning_codes_json TEXT NOT NULL CHECK(json_valid(warning_codes_json)),
    result_refs_json TEXT NOT NULL CHECK(json_valid(result_refs_json)),
    recorded_at_utc INTEGER NOT NULL CHECK(recorded_at_utc>=0),
    command_id TEXT NULL REFERENCES command_receipts(command_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE infrastructure_workbook_replay_index (
    logical_fingerprint TEXT PRIMARY KEY CHECK(length(logical_fingerprint)=64),
    accepted_workbook_run_id TEXT NOT NULL REFERENCES infrastructure_workbook_runs(workbook_run_id) ON DELETE RESTRICT,
    accepted_at_utc INTEGER NOT NULL CHECK(accepted_at_utc>=0)
) STRICT;

CREATE INDEX infra_001 ON sites(customer_org_id,lifecycle_state,site_id);
CREATE INDEX infra_002 ON sites(address_match_key,site_id);
CREATE INDEX infra_003 ON rooms(site_id,lifecycle_state,room_id);
CREATE INDEX infra_004 ON racks(room_id,lifecycle_state,rack_id);
CREATE INDEX infra_005 ON network_elements(site_id,lifecycle_state,network_element_id);
CREATE INDEX infra_006 ON network_elements(name_match_key,network_element_id);
CREATE INDEX infra_007 ON network_elements(serial_match_key,network_element_id);
CREATE INDEX infra_008 ON network_element_placement_events(network_element_id,recorded_at_utc,placement_event_id);
CREATE INDEX infra_009 ON network_element_placement_current(rack_id,u_start,network_element_id);
CREATE INDEX infra_010 ON site_lifecycle_events(site_id,recorded_at_utc,site_event_id);
CREATE INDEX infra_011 ON device_reference_resolution_current(network_element_id,device_reference_id);
CREATE INDEX infra_012 ON device_reference_resolution_events(device_reference_id,recorded_at_utc,resolution_event_id);
CREATE INDEX infra_013 ON network_element_containment_current(parent_network_element_id,child_network_element_id);
CREATE INDEX infra_014 ON network_element_containment_events(child_network_element_id,recorded_at_utc,containment_event_id);
CREATE INDEX infra_015 ON cloud_types(name_match_key,cloud_type_id);
CREATE INDEX infra_016 ON cloud_deployments(site_id,lifecycle_state,cloud_deployment_id);
CREATE INDEX infra_017 ON cloud_deployments(cloud_type_id,site_id,cloud_deployment_id);
CREATE INDEX infra_018 ON cloud_assignment_current(cloud_deployment_id,network_element_id);
CREATE INDEX infra_019 ON network_element_ip_identities(network_element_id,network_element_ip_id);
CREATE INDEX infra_020 ON network_element_ip_events(network_element_ip_id,recorded_at_utc,ip_event_id);
CREATE UNIQUE INDEX infra_021 ON network_element_ip_current(network_element_id,canonical_address) WHERE active=1;
CREATE UNIQUE INDEX infra_022 ON network_element_ip_current(network_element_id) WHERE active=1 AND is_primary=1;
CREATE INDEX infra_023 ON network_element_ip_current(canonical_address,network_element_id) WHERE active=1;
CREATE INDEX infra_024 ON network_element_models(name_match_key,network_element_model_id);
CREATE INDEX infra_025 ON network_element_model_current(network_element_model_id,network_element_id);
CREATE INDEX infra_026 ON model_bom_compatibility_current(network_element_model_id,bom_key,compatibility_relation_id);
CREATE INDEX infra_027 ON model_bom_compatibility_events(network_element_model_id,recorded_at_utc,compatibility_event_id);
CREATE INDEX infra_028 ON installed_components(network_element_id,installed_component_id);
CREATE INDEX infra_029 ON installed_component_events(installed_component_id,recorded_at_utc,installed_component_event_id);
CREATE INDEX infra_030 ON installed_component_current(network_element_id,bom_key,serial_match_key,installed_component_id);
CREATE UNIQUE INDEX infra_031 ON installed_component_current(network_element_id,slot_match_key) WHERE state='installed' AND slot_match_key IS NOT NULL;
CREATE UNIQUE INDEX infra_032 ON device_part_component_resolution_current(installed_component_id);
CREATE INDEX infra_033 ON device_part_component_resolution_events(device_part_unit_id,recorded_at_utc,resolution_event_id);
CREATE INDEX infra_034 ON infrastructure_workbook_exports(generated_at_utc,export_id);
CREATE INDEX infra_035 ON infrastructure_workbook_runs(state,captured_at_utc,workbook_run_id);
CREATE INDEX infra_036 ON infrastructure_workbook_runs(file_sha256,workbook_run_id);
CREATE UNIQUE INDEX infra_037 ON infrastructure_workbook_staging_rows(workbook_run_id,sheet_kind,row_ordinal);
CREATE INDEX infra_038 ON infrastructure_workbook_proposals(workbook_run_id,state,proposal_id);
CREATE INDEX infra_039 ON infrastructure_workbook_proposals(target_network_element_id,proposal_id);
CREATE UNIQUE INDEX infra_040 ON infrastructure_workbook_row_decisions(workbook_run_id,sheet_kind,row_ordinal);
CREATE INDEX infra_041 ON infrastructure_workbook_row_decisions(target_network_element_id,row_decision_id);
CREATE INDEX infra_042 ON sites(created_command_id);
CREATE INDEX infra_043 ON sites(last_command_id);
CREATE INDEX infra_044 ON site_dispatch_locations(created_command_id);
CREATE INDEX infra_045 ON site_lifecycle_events(prior_customer_org_id);
CREATE INDEX infra_046 ON site_lifecycle_events(new_customer_org_id);
CREATE INDEX infra_047 ON site_lifecycle_events(command_id);
CREATE TRIGGER infra_site_lifecycle_events_update_guard BEFORE UPDATE ON site_lifecycle_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_site_lifecycle_events_delete_guard BEFORE DELETE ON site_lifecycle_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_048 ON rooms(created_command_id);
CREATE INDEX infra_049 ON rooms(last_command_id);
CREATE INDEX infra_050 ON racks(created_command_id);
CREATE INDEX infra_051 ON racks(last_command_id);
CREATE INDEX infra_052 ON room_rack_lifecycle_events(room_id);
CREATE INDEX infra_053 ON room_rack_lifecycle_events(rack_id);
CREATE INDEX infra_054 ON room_rack_lifecycle_events(command_id);
CREATE TRIGGER infra_room_rack_lifecycle_events_update_guard BEFORE UPDATE ON room_rack_lifecycle_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_room_rack_lifecycle_events_delete_guard BEFORE DELETE ON room_rack_lifecycle_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_055 ON network_elements(created_command_id);
CREATE INDEX infra_056 ON network_elements(last_command_id);
CREATE INDEX infra_057 ON network_element_lifecycle_events(network_element_id);
CREATE INDEX infra_058 ON network_element_lifecycle_events(command_id);
CREATE TRIGGER infra_network_element_lifecycle_events_update_guard BEFORE UPDATE ON network_element_lifecycle_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_network_element_lifecycle_events_delete_guard BEFORE DELETE ON network_element_lifecycle_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_059 ON network_element_placement_events(prior_rack_id);
CREATE INDEX infra_060 ON network_element_placement_events(new_rack_id);
CREATE INDEX infra_061 ON network_element_placement_events(command_id);
CREATE TRIGGER infra_network_element_placement_events_update_guard BEFORE UPDATE ON network_element_placement_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_network_element_placement_events_delete_guard BEFORE DELETE ON network_element_placement_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_062 ON network_element_placement_current(last_event_id);
CREATE INDEX infra_063 ON network_element_placement_current(last_command_id);
CREATE INDEX infra_064 ON device_reference_resolution_events(prior_network_element_id);
CREATE INDEX infra_065 ON device_reference_resolution_events(new_network_element_id);
CREATE INDEX infra_066 ON device_reference_resolution_events(command_id);
CREATE TRIGGER infra_device_reference_resolution_events_update_guard BEFORE UPDATE ON device_reference_resolution_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_device_reference_resolution_events_delete_guard BEFORE DELETE ON device_reference_resolution_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_067 ON device_reference_resolution_current(last_event_id);
CREATE INDEX infra_068 ON device_reference_resolution_current(last_command_id);
CREATE INDEX infra_069 ON network_element_containment_events(prior_parent_network_element_id);
CREATE INDEX infra_070 ON network_element_containment_events(new_parent_network_element_id);
CREATE INDEX infra_071 ON network_element_containment_events(command_id);
CREATE TRIGGER infra_network_element_containment_events_update_guard BEFORE UPDATE ON network_element_containment_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_network_element_containment_events_delete_guard BEFORE DELETE ON network_element_containment_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_072 ON network_element_containment_current(last_event_id);
CREATE INDEX infra_073 ON network_element_containment_current(last_command_id);
CREATE INDEX infra_074 ON cloud_types(created_command_id);
CREATE INDEX infra_075 ON cloud_types(last_command_id);
CREATE INDEX infra_076 ON cloud_deployments(created_command_id);
CREATE INDEX infra_077 ON cloud_deployments(last_command_id);
CREATE INDEX infra_078 ON cloud_assignment_events(network_element_id);
CREATE INDEX infra_079 ON cloud_assignment_events(prior_cloud_deployment_id);
CREATE INDEX infra_080 ON cloud_assignment_events(new_cloud_deployment_id);
CREATE INDEX infra_081 ON cloud_assignment_events(command_id);
CREATE TRIGGER infra_cloud_assignment_events_update_guard BEFORE UPDATE ON cloud_assignment_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_cloud_assignment_events_delete_guard BEFORE DELETE ON cloud_assignment_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_082 ON cloud_assignment_current(last_event_id);
CREATE INDEX infra_083 ON cloud_assignment_current(last_command_id);
CREATE INDEX infra_084 ON network_element_ip_identities(created_command_id);
CREATE INDEX infra_085 ON network_element_ip_events(target_event_id);
CREATE INDEX infra_086 ON network_element_ip_events(command_id);
CREATE TRIGGER infra_network_element_ip_events_update_guard BEFORE UPDATE ON network_element_ip_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_network_element_ip_events_delete_guard BEFORE DELETE ON network_element_ip_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_087 ON network_element_ip_current(network_element_id);
CREATE INDEX infra_088 ON network_element_ip_current(last_event_id);
CREATE INDEX infra_089 ON network_element_ip_current(last_command_id);
CREATE INDEX infra_090 ON network_element_models(created_command_id);
CREATE INDEX infra_091 ON network_element_models(last_command_id);
CREATE INDEX infra_092 ON model_lifecycle_events(network_element_model_id);
CREATE INDEX infra_093 ON model_lifecycle_events(command_id);
CREATE TRIGGER infra_model_lifecycle_events_update_guard BEFORE UPDATE ON model_lifecycle_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_model_lifecycle_events_delete_guard BEFORE DELETE ON model_lifecycle_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_094 ON network_element_model_assignment_events(network_element_id);
CREATE INDEX infra_095 ON network_element_model_assignment_events(prior_model_id);
CREATE INDEX infra_096 ON network_element_model_assignment_events(new_model_id);
CREATE INDEX infra_097 ON network_element_model_assignment_events(command_id);
CREATE TRIGGER infra_network_element_model_assignment_events_update_guard BEFORE UPDATE ON network_element_model_assignment_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_network_element_model_assignment_events_delete_guard BEFORE DELETE ON network_element_model_assignment_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_098 ON network_element_model_current(last_event_id);
CREATE INDEX infra_099 ON network_element_model_current(last_command_id);
CREATE INDEX infra_100 ON model_bom_compatibility_events(command_id);
CREATE TRIGGER infra_model_bom_compatibility_events_update_guard BEFORE UPDATE ON model_bom_compatibility_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_model_bom_compatibility_events_delete_guard BEFORE DELETE ON model_bom_compatibility_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_101 ON model_bom_compatibility_current(last_event_id);
CREATE INDEX infra_102 ON model_bom_compatibility_current(last_command_id);
CREATE INDEX infra_103 ON installed_components(created_command_id);
CREATE INDEX infra_104 ON installed_component_events(task_id);
CREATE INDEX infra_105 ON installed_component_events(inventory_physical_consequence_id);
CREATE INDEX infra_106 ON installed_component_events(target_event_id);
CREATE INDEX infra_107 ON installed_component_events(command_id);
CREATE TRIGGER infra_installed_component_events_update_guard BEFORE UPDATE ON installed_component_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_installed_component_events_delete_guard BEFORE DELETE ON installed_component_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_108 ON installed_component_current(last_event_id);
CREATE INDEX infra_109 ON installed_component_current(last_command_id);
CREATE INDEX infra_110 ON device_part_component_resolution_events(prior_installed_component_id);
CREATE INDEX infra_111 ON device_part_component_resolution_events(new_installed_component_id);
CREATE INDEX infra_112 ON device_part_component_resolution_events(command_id);
CREATE TRIGGER infra_device_part_component_resolution_events_update_guard BEFORE UPDATE ON device_part_component_resolution_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_device_part_component_resolution_events_delete_guard BEFORE DELETE ON device_part_component_resolution_events BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_113 ON device_part_component_resolution_current(last_event_id);
CREATE INDEX infra_114 ON device_part_component_resolution_current(last_command_id);
CREATE INDEX infra_115 ON infrastructure_workbook_exports(command_id);
CREATE TRIGGER infra_infrastructure_workbook_exports_update_guard BEFORE UPDATE ON infrastructure_workbook_exports BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_infrastructure_workbook_exports_delete_guard BEFORE DELETE ON infrastructure_workbook_exports BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_116 ON infrastructure_workbook_runs(last_command_id);
CREATE INDEX infra_117 ON infrastructure_workbook_proposals(staging_row_id);
CREATE INDEX infra_118 ON infrastructure_workbook_proposals(last_command_id);
CREATE INDEX infra_119 ON infrastructure_workbook_row_decisions(command_id);
CREATE TRIGGER infra_infrastructure_workbook_row_decisions_update_guard BEFORE UPDATE ON infrastructure_workbook_row_decisions BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_infrastructure_workbook_row_decisions_delete_guard BEFORE DELETE ON infrastructure_workbook_row_decisions BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE INDEX infra_120 ON infrastructure_workbook_replay_index(accepted_workbook_run_id);
CREATE TRIGGER infra_infrastructure_workbook_replay_index_update_guard BEFORE UPDATE ON infrastructure_workbook_replay_index BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER infra_infrastructure_workbook_replay_index_delete_guard BEFORE DELETE ON infrastructure_workbook_replay_index BEGIN SELECT RAISE(ABORT,'INFRA_HISTORY_IMMUTABLE'); END;
CREATE UNIQUE INDEX infra_model_bom_role ON model_bom_compatibility_current(network_element_model_id,bom_key,coalesce(component_role,''));
CREATE TRIGGER infra_staging_cleanup_guard BEFORE DELETE ON infrastructure_workbook_staging_rows
WHEN NOT EXISTS (
    SELECT 1 FROM infrastructure_workbook_runs r
    JOIN infrastructure_workbook_row_decisions d ON d.workbook_run_id=r.workbook_run_id
    WHERE r.workbook_run_id=OLD.workbook_run_id AND r.state IN ('accepted','rejected','failed')
      AND d.sheet_kind=OLD.sheet_kind AND d.row_ordinal=OLD.row_ordinal
      AND d.row_fingerprint=OLD.row_fingerprint
) BEGIN SELECT RAISE(ABORT,'INFRA_STAGING_STILL_REVIEWABLE'); END;
