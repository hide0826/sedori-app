try:
    from ui.image_manager.widget import ImageManagerWidget
except ImportError:
    from .widget import ImageManagerWidget

__all__ = ["ImageManagerWidget"]
