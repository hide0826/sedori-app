#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗マスタ UI パッケージ。"""
from __future__ import annotations

try:
    from ui.store_master.widget import StoreMasterWidget
    from ui.store_master.store_dialogs import StoreEditDialog, CustomFieldEditDialog
    from ui.store_master.route_dialogs import DraggableStoreListWidget, RouteManagementDialog
    from ui.store_master.store_list import StoreListWidget
    from ui.store_master.expense import (
        ExpenseDestinationEditDialog,
        ExpenseDestinationListWidget,
    )
    from ui.store_master.online import (
        OnlinePlatformEditDialog,
        FleaMarketEditDialog,
        OnlineStoreEditDialog,
        WholesalerEditDialog,
        OnlinePlatformListWidget,
        FleaMarketListWidget,
        OnlineStoreListWidget,
        WholesalerListWidget,
    )
    from ui.store_master.flea_users import (
        FleaMarketUserEditDialog,
        FleaMarketUserListWidget,
    )
except ImportError:
    from .widget import StoreMasterWidget
    from .store_dialogs import StoreEditDialog, CustomFieldEditDialog
    from .route_dialogs import DraggableStoreListWidget, RouteManagementDialog
    from .store_list import StoreListWidget
    from .expense import (
        ExpenseDestinationEditDialog,
        ExpenseDestinationListWidget,
    )
    from .online import (
        OnlinePlatformEditDialog,
        FleaMarketEditDialog,
        OnlineStoreEditDialog,
        WholesalerEditDialog,
        OnlinePlatformListWidget,
        FleaMarketListWidget,
        OnlineStoreListWidget,
        WholesalerListWidget,
    )
    from .flea_users import (
        FleaMarketUserEditDialog,
        FleaMarketUserListWidget,
    )

__all__ = [
    "StoreMasterWidget",
    "StoreEditDialog",
    "CustomFieldEditDialog",
    "DraggableStoreListWidget",
    "RouteManagementDialog",
    "StoreListWidget",
    "ExpenseDestinationEditDialog",
    "ExpenseDestinationListWidget",
    "OnlinePlatformEditDialog",
    "FleaMarketEditDialog",
    "OnlineStoreEditDialog",
    "WholesalerEditDialog",
    "OnlinePlatformListWidget",
    "FleaMarketListWidget",
    "OnlineStoreListWidget",
    "WholesalerListWidget",
    "FleaMarketUserEditDialog",
    "FleaMarketUserListWidget",
]
