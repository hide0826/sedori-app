#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗マスタ管理ウィジェット（後方互換エントリポイント）。

実装は ui/store_master/ パッケージに分割済み。
"""
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
