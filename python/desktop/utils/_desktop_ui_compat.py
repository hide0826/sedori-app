#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI ダイアログの import 互換（services compat とは分離して循環 import を防ぐ）。"""

from __future__ import annotations

try:
    from ui.purchase_row_edit_dialog import PurchaseRowEditDialog
except ImportError:
    from desktop.ui.purchase_row_edit_dialog import PurchaseRowEditDialog  # type: ignore

try:
    from ui.flea_market_settings_widget import FleaMarketSettingsWidget
except ImportError:
    from desktop.ui.flea_market_settings_widget import FleaMarketSettingsWidget  # type: ignore

__all__ = ["FleaMarketSettingsWidget", "PurchaseRowEditDialog"]
