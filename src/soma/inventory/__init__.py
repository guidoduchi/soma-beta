"""LLD-07 Inventory domain implementation."""

from .contracts.inventory import InventoryMutationResult, InventoryRef
from .services.needs_stock import InventoryNeedsStockService

__all__ = ["InventoryMutationResult", "InventoryNeedsStockService", "InventoryRef"]
