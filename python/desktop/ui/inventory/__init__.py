try:
    from ui.inventory.widget import InventoryWidget
except ImportError:
    from .widget import InventoryWidget

__all__ = ["InventoryWidget"]
