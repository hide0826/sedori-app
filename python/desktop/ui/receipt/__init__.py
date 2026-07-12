try:
    from ui.receipt.widget import ReceiptWidget
except ImportError:
    from .widget import ReceiptWidget

__all__ = ["ReceiptWidget"]
