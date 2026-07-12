try:
    from ui.product.widget import ProductWidget
except ImportError:
    from .widget import ProductWidget

__all__ = ["ProductWidget"]
