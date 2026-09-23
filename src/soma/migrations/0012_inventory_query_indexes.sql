CREATE INDEX idx_inv_069_spare_part_units_stock_order
ON spare_part_units(COALESCE(local_tracking_id,''),spare_part_unit_id);

CREATE INDEX idx_inv_070_spare_part_units_stock_bom_order
ON spare_part_units(bom_key,COALESCE(local_tracking_id,''),spare_part_unit_id);
