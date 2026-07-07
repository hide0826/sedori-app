try:
    from ui.repricer.widget import RepricerWidget
except ImportError:
    from .widget import RepricerWidget

__all__ = ["RepricerWidget"]
