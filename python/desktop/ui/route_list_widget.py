#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルートサマリー一覧ウィジェット

ルート登録機能で保存されたデータを一覧表示
- 日付/ルート名/総仕入点数/総想定粗利/平均仕入価格/総稼働時間/想定時給
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QLabel, QGroupBox
)
from PySide6.QtCore import Qt, Signal
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from database.route_db import RouteDatabase
from database.store_db import StoreDatabase


class RouteListWidget(QWidget):
    """ルートサマリー一覧ウィジェット"""
    
    # データ更新シグナル
    route_selected = Signal(int)  # route_idを送信
    
    def __init__(self):
        super().__init__()
        self.route_db = RouteDatabase()
        self.store_db = StoreDatabase()
        self._sync_done = False  # 同期フラグ
        
        self.setup_ui()
        self.load_routes()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # ヘッダー
        header_label = QLabel("ルートサマリー一覧")
        header_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(header_label)
        
        # 操作ボタン
        self.setup_action_buttons(layout)
        
        # テーブル
        self.setup_table(layout)
        
        # 統計情報
        self.update_statistics()
    
    def setup_action_buttons(self, parent_layout):
        """操作ボタンの設定"""
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        
        # 更新ボタン
        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(self.load_routes)
        button_layout.addWidget(refresh_btn)
        
        button_layout.addStretch()
        
        parent_layout.addWidget(button_group)
    
    def setup_table(self, parent_layout):
        """テーブルの設定"""
        table_group = QGroupBox("ルート一覧")
        table_layout = QVBoxLayout(table_group)
        
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # ソート機能を有効化
        self.table.setSortingEnabled(True)
        
        # ヘッダー設定
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        # 文字数に応じて自動で幅をフィット
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionsClickable(True)
        
        # ダブルクリックで詳細表示
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        table_layout.addWidget(self.table)
        
        # 統計情報ラベル
        self.stats_label = QLabel("統計: 読み込み中...")
        table_layout.addWidget(self.stats_label)
        
        parent_layout.addWidget(table_group)
    
    def load_routes(self):
        """ルート一覧を読み込む"""
        # 既存データの同期（毎回実行して最新化）
        try:
            self.route_db.sync_total_item_count_from_visits()
        except Exception:
            pass
        
        routes = self.route_db.list_route_summaries()
        self.update_table(routes)
        self.update_statistics()
    
    def update_table(self, routes: list):
        """テーブルを更新"""
        # ソート機能を一時的に無効化
        self.table.setSortingEnabled(False)
        
        columns = ["日付", "ルート名", "総仕入点数", "総想定粗利", "平均仕入価格", "総稼働時間", "想定時給"]
        
        self.table.setRowCount(len(routes))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        
        # データの設定
        for i, route in enumerate(routes):
            # 日付
            self.table.setItem(i, 0, QTableWidgetItem(route.get('route_date', '')))
            
            # ルート名（ルートコードから変換）
            route_code = route.get('route_code', '')
            route_name = self.store_db.get_route_name_by_code(route_code) or route_code
            self.table.setItem(i, 1, QTableWidgetItem(route_name))
            
            # 総仕入点数
            total_item_count = route.get('total_item_count', 0) or 0
            item_count_item = QTableWidgetItem()
            item_count_item.setData(Qt.EditRole, total_item_count)
            item_count_item.setText(str(total_item_count))
            self.table.setItem(i, 2, item_count_item)
            
            # 総想定粗利
            total_gross_profit = route.get('total_gross_profit', 0) or 0
            profit_item = QTableWidgetItem()
            profit_item.setData(Qt.EditRole, total_gross_profit)
            profit_item.setText(f"{total_gross_profit:,}" if total_gross_profit else "0")
            self.table.setItem(i, 3, profit_item)
            
            # 平均仕入価格
            avg_price = route.get('avg_purchase_price', 0) or 0
            avg_item = QTableWidgetItem()
            avg_item.setData(Qt.EditRole, avg_price)
            avg_item.setText(f"{avg_price:,.0f}" if avg_price else "0")
            self.table.setItem(i, 4, avg_item)
            
            # 総稼働時間
            working_hours = route.get('total_working_hours', 0) or 0
            hours_item = QTableWidgetItem()
            hours_item.setData(Qt.EditRole, working_hours)
            hours_item.setText(f"{working_hours:.1f}" if working_hours else "0.0")
            self.table.setItem(i, 5, hours_item)
            
            # 想定時給
            hourly_rate = route.get('estimated_hourly_rate', 0) or 0
            rate_item = QTableWidgetItem()
            rate_item.setData(Qt.EditRole, hourly_rate)
            rate_item.setText(f"{hourly_rate:,.0f}" if hourly_rate else "0")
            self.table.setItem(i, 6, rate_item)
            
            # 各行にIDを保持（ダブルクリック時の参照用）
            self.table.item(i, 0).setData(Qt.UserRole, route.get('id'))
        
        # ソート機能を再有効化
        self.table.setSortingEnabled(True)
        
        # 列幅の自動調整
        self.table.resizeColumnsToContents()
    
    def update_statistics(self):
        """統計情報を更新"""
        routes = self.route_db.list_route_summaries()
        self.stats_label.setText(
            f"統計: ルート数 {len(routes)}件"
        )
    
    def on_item_double_clicked(self, item: QTableWidgetItem):
        """ダブルクリック時の処理"""
        route_id = item.data(Qt.UserRole)
        if route_id:
            self.route_selected.emit(route_id)

