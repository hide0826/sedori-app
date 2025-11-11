#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルート関連機能（登録・サマリー・訪問DB）をまとめたタブウィジェット
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from ui.route_summary_widget import RouteSummaryWidget
from ui.route_list_widget import RouteListWidget
from ui.route_visit_widget import RouteVisitLogWidget


class RouteManagementWidget(QWidget):
    """ルート登録・サマリー・訪問DBを統合したタブ"""

    def __init__(self, api_client=None, inventory_widget: Optional[QWidget] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.api_client = api_client
        self.inventory_widget = inventory_widget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.inner_tabs = QTabWidget()
        layout.addWidget(self.inner_tabs)

        # ルート登録
        self.route_summary_widget = RouteSummaryWidget(api_client, inventory_widget=inventory_widget)
        self.inner_tabs.addTab(self.route_summary_widget, "ルート登録")

        # ルートサマリー一覧
        self.route_list_widget = RouteListWidget()
        self.inner_tabs.addTab(self.route_list_widget, "ルートサマリー")

        # ルート訪問DB
        self.route_visit_widget = RouteVisitLogWidget()
        self.inner_tabs.addTab(self.route_visit_widget, "ルート訪問DB")

        # 保存完了時にサマリー・訪問DBを更新
        self.route_summary_widget.data_saved.connect(self.route_list_widget.load_routes)
        self.route_summary_widget.data_saved.connect(self.route_visit_widget.load_data)

        if inventory_widget is not None:
            self.set_inventory_widget(inventory_widget)

    def set_inventory_widget(self, inventory_widget: QWidget):
        """後から仕入管理ウィジェットを差し替え"""
        self.inventory_widget = inventory_widget
        self.route_summary_widget.inventory_widget = inventory_widget
        if hasattr(inventory_widget, "set_route_summary_widget"):
            inventory_widget.set_route_summary_widget(self.route_summary_widget)

