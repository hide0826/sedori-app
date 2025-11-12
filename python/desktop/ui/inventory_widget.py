#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入管理ウィジェット

CSV取込 → 17列テーブル表示 → 検索/フィルタ → 編集可能
Q列ハイライト、交互行色、100+行対応
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QSplitter, QMessageBox, QFrame,
    QCheckBox, QSpinBox, QDateEdit, QFileDialog,
    QDialog, QDialogButtonBox, QSizePolicy, QInputDialog
)
from PySide6.QtCore import Qt, QDate, Signal, QSettings
from PySide6.QtGui import QFont, QColor, QPalette
import pandas as pd
from pathlib import Path
import re
import sys
import os
from typing import List, Dict, Any, Optional

# プロジェクトルートをパスに追加（相対インポート用）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.store_db import StoreDatabase
from database.inventory_db import InventoryDatabase
from database.inventory_route_snapshot_db import InventoryRouteSnapshotDatabase
from database.product_db import ProductDatabase
from database.product_purchase_db import ProductPurchaseDatabase
from ui.star_rating_widget import StarRatingWidget


class InventoryWidget(QWidget):
    """仕入管理ウィジェット"""
    
    # シグナル定義
    data_loaded = Signal(int)  # データ読み込み完了
    sku_generated = Signal(int)  # SKU生成完了
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.inventory_data = None
        self.filtered_data = None
        self.excluded_highlight_on = False
        
        # ルートサマリーウィジェットへの参照（後で設定される）
        self.route_summary_widget = None
        
        # データベースの初期化
        self.store_db = StoreDatabase()
        self.inventory_db = InventoryDatabase()
        self.route_snapshot_db = InventoryRouteSnapshotDatabase()
        self.product_db = ProductDatabase()
        self.product_purchase_db = ProductPurchaseDatabase()
        
        # UIの初期化
        self.route_template_btn = None
        self.matching_btn = None
        self.setup_ui()
    
    def set_route_summary_widget(self, widget):
        self.route_summary_widget = widget
        if self.route_template_btn:
            self.route_template_btn.setEnabled(widget is not None)
        if self.matching_btn:
            self.matching_btn.setEnabled(widget is not None)
        if widget and getattr(widget, "last_loaded_template_path", ""):
            try:
                path = widget.last_loaded_template_path
                if path:
                    # route_template_status は削除済み
                    self.refresh_route_template_view()
            except Exception:
                pass
        if widget:
            self.refresh_route_template_view()
        
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：ファイル操作エリア
        self.setup_file_operations()
        
        # 表示モード切り替え
        self.setup_view_mode_selector()
        
        # 検索・フィルタ・出品設定
        self.setup_search_listing_panel()
        
        # データテーブル（折りたたみ対応）
        self.setup_data_table()
        
        # ルートテンプレート読み込みエリア
        self.setup_route_template_panel()
        
        # SKUテンプレ設定パネル（既存機能）
        self.setup_settings_panel()
        
        # 初期表示モード適用
        self.on_view_mode_changed(self.view_mode_combo.currentIndex())
        
    def setup_file_operations(self):
        """ファイル操作エリアの設定（改良版）"""
        file_group = QGroupBox("ファイル操作・アクション")
        file_layout = QHBoxLayout(file_group)
        
        # ファイル操作セクション
        file_ops_layout = QHBoxLayout()
        
        # CSV取込ボタン
        self.import_btn = QPushButton("CSV取込")
        self.import_btn.clicked.connect(self.import_csv)
        self.import_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        file_ops_layout.addWidget(self.import_btn)
        
        # エクスポートボタン
        self.export_btn = QPushButton("CSV出力")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        file_ops_layout.addWidget(self.export_btn)
        
        # データクリアボタン
        self.clear_btn = QPushButton("データクリア")
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setEnabled(False)
        file_ops_layout.addWidget(self.clear_btn)
        
        # 保存ボタン
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self.save_inventory_data)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffc107;
                color: #000;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e0a800;
            }
        """)
        file_ops_layout.addWidget(self.save_btn)
        
        # 保存履歴ボタン
        self.load_history_btn = QPushButton("保存履歴")
        self.load_history_btn.clicked.connect(self.open_saved_history)
        self.load_history_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        file_ops_layout.addWidget(self.load_history_btn)
        
        file_layout.addLayout(file_ops_layout)
        
        # アクションボタンセクション
        action_ops_layout = QHBoxLayout()
        
        # SKU生成ボタン
        self.generate_sku_btn = QPushButton("SKU生成")
        self.generate_sku_btn.clicked.connect(self.generate_sku)
        self.generate_sku_btn.setEnabled(False)
        self.generate_sku_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        action_ops_layout.addWidget(self.generate_sku_btn)
        
        # 出品CSV生成ボタン
        self.export_listing_btn = QPushButton("出品CSV生成")
        self.export_listing_btn.clicked.connect(self.export_listing_csv)
        self.export_listing_btn.setEnabled(False)
        action_ops_layout.addWidget(self.export_listing_btn)
        
        # 古物台帳生成ボタン
        self.antique_register_btn = QPushButton("古物台帳生成")
        self.antique_register_btn.clicked.connect(self.generate_antique_register)
        self.antique_register_btn.setEnabled(False)
        action_ops_layout.addWidget(self.antique_register_btn)

        # ルートテンプレート読み込みボタン
        self.route_template_btn = QPushButton("ルートテンプレ読込")
        self.route_template_btn.clicked.connect(self.apply_route_template)
        self.route_template_btn.setEnabled(self.route_summary_widget is not None)
        action_ops_layout.addWidget(self.route_template_btn)
        
        # 照合処理実行ボタン
        self.matching_btn = QPushButton("照合処理実行")
        self.matching_btn.clicked.connect(self.run_matching)
        self.matching_btn.setEnabled(self.route_summary_widget is not None)
        self.matching_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        action_ops_layout.addWidget(self.matching_btn)
        
        file_layout.addLayout(action_ops_layout)

        # SKU設定トグルボタン
        self.toggle_settings_btn = QPushButton("SKU設定")
        self.toggle_settings_btn.clicked.connect(self.toggle_settings_panel)
        file_layout.addWidget(self.toggle_settings_btn)
        
        file_layout.addStretch()
        
        # データ件数表示
        self.data_count_label = QLabel("データ件数: 0")
        file_layout.addWidget(self.data_count_label)
        file_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        self.layout().addWidget(file_group)

    def setup_view_mode_selector(self):
        selector_layout = QHBoxLayout()
        mode_label = QLabel("表示モード:")
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["デフォルト", "仕入データビュー", "ルートテンプレートビュー"])
        self.view_mode_combo.currentIndexChanged.connect(self.on_view_mode_changed)
        selector_layout.addWidget(mode_label)
        selector_layout.addWidget(self.view_mode_combo)
        selector_layout.addStretch()
        self.layout().addLayout(selector_layout)
        self.view_mode_combo.setCurrentIndex(0)

    def on_view_mode_changed(self, index: int):
        mode = self.view_mode_combo.currentText()
        search_group = getattr(self, "search_listing_group", None)
        data_group = getattr(self, "data_group", None)
        template_group = getattr(self, "route_template_group", None)
        if mode == "デフォルト":
            if search_group:
                search_group.setVisible(True)
            if data_group:
                data_group.setVisible(True)
            if template_group:
                template_group.setVisible(True)
        elif mode == "仕入データビュー":
            if search_group:
                search_group.setVisible(True)
            if data_group:
                data_group.setVisible(True)
            if template_group:
                template_group.setVisible(False)
        elif mode == "ルートテンプレートビュー":
            if search_group:
                search_group.setVisible(False)
            if data_group:
                data_group.setVisible(False)
            if template_group:
                template_group.setVisible(True)
        
        # 表示モード切り替え後にテーブルのサイズを再調整
        # レイアウトの再計算を促す
        if hasattr(self, 'data_table'):
            # テーブルのサイズポリシーを確認し、必要に応じて再設定
            self.data_table.updateGeometry()
            # 親ウィジェットのレイアウトを更新
            if self.data_table.parent():
                self.data_table.parent().updateGeometry()
            # データがある場合はテーブルを再更新して全行が表示されるようにする
            if self.filtered_data is not None and len(self.filtered_data) > 0:
                # テーブルの行数を確認し、必要に応じて再設定
                current_rows = self.data_table.rowCount()
                expected_rows = len(self.filtered_data)
                if current_rows != expected_rows:
                    # 行数が一致しない場合は再更新
                    self.update_table()
        
    def setup_search_listing_panel(self):
        """検索・フィルタと出品設定をまとめたエリア"""
        self.search_listing_group = QGroupBox("検索・フィルタと出品設定")
        self.search_listing_group.setCheckable(True)
        self.search_listing_group.setChecked(True)
        outer_layout = QVBoxLayout(self.search_listing_group)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)
        
        self.search_listing_content = QWidget()
        content_layout = QHBoxLayout(self.search_listing_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        
        # 検索エリア
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)
        search_label = QLabel("検索:")
        search_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("商品名、ASIN、JANコードで検索...")
        self.search_edit.textChanged.connect(self.apply_filters)
        self.search_edit.setMinimumWidth(220)
        search_layout.addWidget(self.search_edit, 1)
        
        self.clear_search_btn = QPushButton("クリア")
        self.clear_search_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(self.clear_search_btn)
        content_layout.addWidget(search_widget, 2)
        
        # フィルタエリア
        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(6)
        
        price_label = QLabel("販売予定価格:")
        filter_layout.addWidget(price_label)
        
        self.min_price_spin = QSpinBox()
        self.min_price_spin.setRange(0, 999999)
        self.min_price_spin.setValue(0)
        self.min_price_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.min_price_spin.setFixedWidth(70)
        self.min_price_spin.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.min_price_spin)
        
        price_to_label = QLabel("〜")
        filter_layout.addWidget(price_to_label)
        
        self.max_price_spin = QSpinBox()
        self.max_price_spin.setRange(0, 999999)
        self.max_price_spin.setValue(999999)
        self.max_price_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.max_price_spin.setFixedWidth(70)
        self.max_price_spin.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.max_price_spin)
        
        self.reset_filters_btn = QPushButton("リセット")
        self.reset_filters_btn.clicked.connect(self.reset_filters)
        filter_layout.addWidget(self.reset_filters_btn)
        content_layout.addWidget(filter_widget, 1)
        
        # 出品設定エリア
        listing_settings_widget = self.create_listing_settings_section()
        content_layout.addWidget(listing_settings_widget, 1)
        
        content_layout.addStretch()
        
        outer_layout.addWidget(self.search_listing_content)
        self.search_listing_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        def _on_toggle(checked: bool):
            self.search_listing_content.setVisible(checked)
        self.search_listing_group.toggled.connect(_on_toggle)
        
        self.layout().addWidget(self.search_listing_group)
    
    def create_listing_settings_section(self) -> QWidget:
        """出品リスト生成設定のUI"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        self.chk_include_title = QCheckBox("タイトルを出力する")
        self.chk_include_title.setChecked(True)
        self.chk_include_title.setToolTip("無効にすると、出品CSVのtitle列を空欄で出力します")
        layout.addWidget(self.chk_include_title)
        
        self.chk_enable_takane = QCheckBox("高値を設定する")
        self.chk_enable_takane.setToolTip("有効にすると、takane欄にpriceの〇%上を自動設定")
        layout.addWidget(self.chk_enable_takane)
        
        self.lbl_takane_pct = QLabel("+%:")
        layout.addWidget(self.lbl_takane_pct)
        
        self.spin_takane_pct = QSpinBox()
        self.spin_takane_pct.setRange(0, 200)
        self.spin_takane_pct.setValue(5)
        self.spin_takane_pct.setFixedWidth(60)
        layout.addWidget(self.spin_takane_pct)
        
        layout.addStretch()
        
        # 永続化
        self.chk_include_title.toggled.connect(self.save_listing_settings)
        self.chk_enable_takane.toggled.connect(self.save_listing_settings)
        self.spin_takane_pct.valueChanged.connect(self.save_listing_settings)
        self.load_listing_settings()
        
        return container

    def _get_qsettings(self) -> QSettings:
        # 会社名/アプリ名は任意の固定値で統一
        return QSettings("HIRIO", "SedoriDesktopApp")

    def load_listing_settings(self):
        try:
            s = self._get_qsettings()
            include_title = s.value("listing/include_title", True, type=bool)
            enable_takane = s.value("listing/enable_takane", False, type=bool)
            takane_pct = s.value("listing/takane_pct", 5, type=int)
            self.chk_include_title.setChecked(bool(include_title))
            self.chk_enable_takane.setChecked(bool(enable_takane))
            try:
                self.spin_takane_pct.setValue(int(takane_pct))
            except Exception:
                pass
        except Exception as e:
            print(f"出品設定ロード失敗: {e}")

    def save_listing_settings(self):
        try:
            s = self._get_qsettings()
            s.setValue("listing/include_title", self.chk_include_title.isChecked())
            s.setValue("listing/enable_takane", self.chk_enable_takane.isChecked())
            s.setValue("listing/takane_pct", int(self.spin_takane_pct.value()))
        except Exception as e:
            print(f"出品設定セーブ失敗: {e}")
        
    def setup_data_table(self):
        """データテーブルエリアの設定（折りたたみ対応）"""
        self.data_group = QGroupBox("取り込んだデータ一覧")
        self.data_group.setCheckable(True)
        self.data_group.setChecked(True)
        outer_layout = QVBoxLayout(self.data_group)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)
        
        self.data_group_content = QWidget()
        data_layout = QVBoxLayout(self.data_group_content)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(6)
        
        # テーブルウィジェットの作成
        self.data_table = QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.data_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        
        # スクロールバーの設定（常に表示）
        self.data_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.data_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # テーブルのサイズポリシー（高さはExpandingでスクロール可能に）
        self.data_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 最小高さは設定しない（レイアウトに任せる）
        # 代わりに、親ウィジェットのレイアウトで適切にサイズが決まるようにする
        
        # ヘッダーの設定
        header = self.data_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        # 列の定義（15列対応・指定順序）
        self.column_headers = [
            "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
            "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "コメント",
            "発送方法", "仕入先", "コンディション説明"
        ]
        
        self.data_table.setColumnCount(len(self.column_headers))
        self.data_table.setHorizontalHeaderLabels(self.column_headers)
        
        # 選択変更時の自動スクロール・ハイライト機能
        self.data_table.itemSelectionChanged.connect(self.on_data_selection_changed)
        
        # テーブルをグループに追加（stretch factorを1に設定してスクロール可能に）
        data_layout.addWidget(self.data_table, 1)
        
        # 統計情報をグループ内に配置
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel("統計: なし")
        stats_layout.addWidget(self.stats_label)
        # 除外商品確認トグルボタン
        self.toggle_excluded_btn = QPushButton("除外商品確認")
        self.toggle_excluded_btn.setToolTip("コメントに『除外』、または発送方法がFBA以外の商品をハイライト表示します。もう一度押すと解除。")
        self.toggle_excluded_btn.clicked.connect(self.toggle_excluded_highlight)
        stats_layout.addWidget(self.toggle_excluded_btn)
        stats_layout.addStretch()
        data_layout.addLayout(stats_layout)
        
        # コンテンツエリアのサイズポリシー（Expandingでスクロール可能に）
        self.data_group_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer_layout.addWidget(self.data_group_content, 1)  # stretch factorを1に設定
        
        def _on_toggle(checked: bool):
            self.data_group_content.setVisible(checked)
            # 折りたたみ時にエリアの高さを調整
            if checked:
                # 展開時：Expandingで高さを確保
                self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                self.data_group.setMaximumHeight(16777215)  # 制限を解除
                # ルートテンプレートエリアを制限（取り込んだデータ一覧が優先）
                if hasattr(self, 'route_template_group'):
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    self.route_template_group.setMaximumHeight(200)  # 最大高さを制限
                    # 店舗履歴テーブルを制限
                    if hasattr(self, 'route_template_table'):
                        self.route_template_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                        self.route_template_table.setMaximumHeight(200)  # 最大高さを制限
                        # テーブルの stretch factor を0に（制限）
                        if hasattr(self, 'route_template_content'):
                            content_layout = self.route_template_content.layout()
                            if isinstance(content_layout, QVBoxLayout):
                                content_layout.setStretchFactor(self.route_template_table, 0)  # テーブルを制限
                    # レイアウトの stretch factor を動的に変更
                    main_layout = self.layout()
                    if isinstance(main_layout, QVBoxLayout):
                        # 取り込んだデータ一覧の stretch factor を3に（展開時）
                        main_layout.setStretchFactor(self.data_group, 3)
                        # ルートテンプレートの stretch factor を0に（制限）
                        main_layout.setStretchFactor(self.route_template_group, 0)
            else:
                # 折りたたみ時：Maximumで高さを最小限に
                self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                # 折りたたみ時は高さを最小限にする（ヘッダーの高さのみ）
                header_height = self.data_group.sizeHint().height()
                self.data_group.setMaximumHeight(header_height)
                # ルートテンプレートエリアを拡張（空いたスペースを利用）
                if hasattr(self, 'route_template_group'):
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                    self.route_template_group.setMaximumHeight(16777215)  # 制限を解除
                    # 店舗履歴テーブルを拡張（ルート情報ラベルは固定）
                    if hasattr(self, 'route_template_table'):
                        self.route_template_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                        self.route_template_table.setMaximumHeight(16777215)  # 制限を解除
                        # テーブルの stretch factor を大きく（空いたスペースを利用）
                        if hasattr(self, 'route_template_content'):
                            content_layout = self.route_template_content.layout()
                            if isinstance(content_layout, QVBoxLayout):
                                content_layout.setStretchFactor(self.route_template_table, 1)  # テーブルを拡張
                    # レイアウトの stretch factor を動的に変更
                    main_layout = self.layout()
                    if isinstance(main_layout, QVBoxLayout):
                        # 取り込んだデータ一覧の stretch factor を0に（折りたたみ時）
                        main_layout.setStretchFactor(self.data_group, 0)
                        # ルートテンプレートの stretch factor を大きく（空いたスペースを利用）
                        main_layout.setStretchFactor(self.route_template_group, 3)
            # レイアウトを再計算
            self.data_group.updateGeometry()
            if hasattr(self, 'route_template_group'):
                self.route_template_group.updateGeometry()
            if self.data_group.parent():
                self.data_group.parent().updateGeometry()
        self.data_group.toggled.connect(_on_toggle)
        self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        
        # レイアウトに追加（stretch factorを大きくして、取り込んだデータ一覧エリアの高さを確保）
        self.layout().addWidget(self.data_group, 3)  # stretch factor = 3（高さを優先）

    def setup_route_template_panel(self):
        """ルートテンプレート読み込みエリア（レイアウト先行の仮実装）"""
        self.route_template_group = QGroupBox("ルートテンプレート")
        self.route_template_group.setCheckable(True)
        self.route_template_group.setChecked(True)
        outer_layout = QVBoxLayout(self.route_template_group)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)
        
        self.route_template_content = QWidget()
        content_layout = QVBoxLayout(self.route_template_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        
        self.route_template_summary_label = QLabel("ルート情報: ー")
        self.route_template_summary_label.setStyleSheet("font-weight: bold;")
        # ルート情報ラベルは固定サイズ（stretch factor = 0）
        content_layout.addWidget(self.route_template_summary_label, 0)
        
        self.route_template_table = QTableWidget()
        headers = [
            "訪問順序", "店舗コード", "店舗名", "IN時間", "OUT時間",
            "滞在(分)", "移動(分)", "想定粗利", "仕入点数", "評価", "メモ"
        ]
        self.route_template_table.setColumnCount(len(headers))
        self.route_template_table.setHorizontalHeaderLabels(headers)
        self.route_template_table.setAlternatingRowColors(True)
        self.route_template_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.route_template_table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.route_template_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        # 評価列（列インデックス9）だけは後で手動調整するため、一旦Interactiveに設定
        header.setSectionResizeMode(9, QHeaderView.Interactive)
        header.setStretchLastSection(True)
        # 星評価が綺麗に収まるように行の高さを調整
        self.route_template_table.verticalHeader().setDefaultSectionSize(24)
        # ルートテンプレートテーブルの高さ設定（初期値は制限あり）
        self.route_template_table.setMinimumHeight(150)
        self.route_template_table.setMaximumHeight(200)  # 初期は最大高さを制限
        self.route_template_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # テーブルをレイアウトに追加（stretch factorを0にして高さを制限、折りたたみ時に動的に変更）
        content_layout.addWidget(self.route_template_table, 0)
        
        buttons_layout = QHBoxLayout()
        self.combined_save_btn = QPushButton("統合保存")
        self.combined_save_btn.clicked.connect(self.save_combined_snapshot)
        buttons_layout.addWidget(self.combined_save_btn)
        
        self.combined_load_btn = QPushButton("統合読込")
        self.combined_load_btn.clicked.connect(self.open_combined_snapshot_history)
        buttons_layout.addWidget(self.combined_load_btn)
        buttons_layout.addStretch()
        content_layout.addLayout(buttons_layout)
        
        # 前回読込表示を削除（取り込んだデータ一覧エリアの高さを確保）
        # self.route_template_status は削除
        
        outer_layout.addWidget(self.route_template_content)
        
        def _on_toggle(checked: bool):
            self.route_template_content.setVisible(checked)
            # 折りたたみ時にエリアの高さを調整
            if checked:
                # 展開時：Maximumで高さを制限
                self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                self.route_template_group.setMaximumHeight(16777215)  # 制限を解除
            else:
                # 折りたたみ時：Maximumで高さを最小限に
                self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                # 折りたたみ時は高さを最小限にする（ヘッダーの高さのみ）
                header_height = self.route_template_group.sizeHint().height()
                self.route_template_group.setMaximumHeight(header_height)
            # レイアウトを再計算
            self.route_template_group.updateGeometry()
            if self.route_template_group.parent():
                self.route_template_group.parent().updateGeometry()
        self.route_template_group.toggled.connect(_on_toggle)
        self.route_template_content.setVisible(True)
        
        # ルートテンプレートグループのサイズポリシーを制限（高さを縮小）
        self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        # レイアウトに追加（stretch factorを小さくして、取り込んだデータ一覧エリアの高さを確保）
        self.layout().addWidget(self.route_template_group, 0)  # stretch factor = 0（最小限の高さ）
        self.refresh_route_template_view()

    def apply_route_template(self):
        """ルートテンプレートの読み込みを実行"""
        if not self.route_summary_widget:
            QMessageBox.warning(self, "ルートテンプレート", "ルート機能が未初期化です。ルータブが有効か確認してください。")
            return
        try:
            file_path = self.route_summary_widget.load_template()
            if not file_path:
                # route_template_status は削除済み
                return
            try:
                s = self._get_qsettings()
                s.setValue("route_template/last_selected", file_path)
            except Exception:
                pass
            self.refresh_route_template_view()
            # route_template_status は削除済み（読み込み完了メッセージは表示しない）
        except Exception as e:
            QMessageBox.critical(self, "テンプレート読込エラー", f"テンプレートの読み込みに失敗しました:\n{e}")
        
    def refresh_route_template_view(self):
        """ルートテンプレートの情報を表示に反映"""
        if not self.route_summary_widget:
            self.route_template_table.setRowCount(0)
            self.route_template_summary_label.setText("ルート情報: ー")
            return
        try:
            route_data = self.route_summary_widget.get_route_data()
            
            # ルートIDがある場合はデータベースから最新データを取得
            route_id = self.route_summary_widget.current_route_id
            if route_id:
                try:
                    # データベースから店舗訪問詳細を取得
                    from database.route_db import RouteDatabase
                    route_db = RouteDatabase()
                    visits_from_db = route_db.get_store_visits_by_route(route_id)
                    
                    # 店舗名を補完し、評価が無い場合は計算
                    visits = []
                    for visit in visits_from_db:
                        store_code = visit.get('store_code', '')
                        store_name = visit.get('store_name', '')
                        if not store_name and store_code:
                            # 店舗マスタから店舗名を取得
                            store_info = self.store_db.get_store_by_supplier_code(store_code)
                            if store_info:
                                store_name = store_info.get('store_name', '')
                        visit['store_name'] = store_name
                        
                        # 評価が無い、または0の場合、かつ仕入れ点数と想定粗利がある場合は計算する
                        store_rating = visit.get('store_rating')
                        store_item_count = visit.get('store_item_count', 0)
                        store_gross_profit = visit.get('store_gross_profit', 0)
                        
                        # 評価が無い、または0の場合で、仕入れ点数と想定粗利がある場合は評価を計算
                        if (not store_rating or store_rating == 0) and store_item_count and store_gross_profit:
                            rating = self._calculate_store_rating_from_visit(visit)
                            visit['store_rating'] = rating
                        elif not store_rating:
                            visit['store_rating'] = 0.0
                        
                        visits.append(visit)
                except Exception as db_err:
                    # データベース取得に失敗した場合はテーブルから取得
                    print(f"DBから取得失敗、テーブルから取得: {db_err}")
                    visits = self.route_summary_widget.get_store_visits_data()
            else:
                # ルートIDがない場合はテーブルから取得
                visits = self.route_summary_widget.get_store_visits_data()
            
            # メモ欄があれば店舗マスタの備考欄に保存・追記
            self._save_memos_to_store_master(visits)
            
            self.populate_route_template_table(visits)
            route_code = route_data.get('route_code', '')
            route_date = route_data.get('route_date', '')
            dep = self._format_hm(route_data.get('departure_time'))
            ret = self._format_hm(route_data.get('return_time'))
            toll_outbound = route_data.get('toll_fee_outbound', 0)
            toll_return = route_data.get('toll_fee_return', 0)
            summary_parts = []
            if route_date:
                summary_parts.append(route_date)
            if route_code:
                summary_parts.append(route_code)
            times = []
            if dep:
                times.append(f"出発 {dep}")
            if ret:
                times.append(f"帰宅 {ret}")
            costs = []
            if toll_outbound is not None:
                try:
                    toll_outbound_val = float(toll_outbound)
                    costs.append(f"往路高速代 {int(toll_outbound_val):,}円")
                except (ValueError, TypeError):
                    pass
            if toll_return is not None:
                try:
                    toll_return_val = float(toll_return)
                    costs.append(f"復路高速代 {int(toll_return_val):,}円")
                except (ValueError, TypeError):
                    pass
            summary_text = " / ".join(summary_parts) if summary_parts else "ー"
            if times:
                summary_text = f"{summary_text} | {' / '.join(times)}"
            if costs:
                summary_text = f"{summary_text} | {' / '.join(costs)}"
            self.route_template_summary_label.setText(f"ルート情報: {summary_text}")
        except Exception as e:
            self.route_template_table.setRowCount(0)
            self.route_template_summary_label.setText("ルート情報: ー")
            print(f"ルートテンプレート表示更新エラー: {e}")
            import traceback
            traceback.print_exc()

    def populate_route_template_table(self, visits: List[Dict[str, Any]]):
        if not isinstance(visits, list):
            visits = []
        headers = [
            "訪問順序", "店舗コード", "店舗名", "IN時間", "OUT時間",
            "滞在(分)", "移動(分)", "想定粗利", "仕入点数", "評価", "メモ"
        ]
        self.route_template_table.setRowCount(len(visits))
        self.route_template_table.setColumnCount(len(headers))
        self.route_template_table.setHorizontalHeaderLabels(headers)
        for row, visit in enumerate(visits):
            def _set(col: int, value: Any):
                item = QTableWidgetItem("" if value is None else str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.route_template_table.setItem(row, col, item)
            
            _set(0, visit.get('visit_order', row + 1))
            _set(1, visit.get('store_code', ''))
            _set(2, visit.get('store_name', ''))
            _set(3, self._format_hm(visit.get('store_in_time')))
            _set(4, self._format_hm(visit.get('store_out_time')))
            _set(5, visit.get('stay_duration', ''))
            _set(6, visit.get('travel_time_from_prev', ''))
            _set(7, visit.get('store_gross_profit', ''))
            _set(8, visit.get('store_item_count', ''))
            
            # 評価列に星評価ウィジェットを設定（ルート登録タブのロジックに合わせる）
            store_rating = visit.get('store_rating')
            try:
                rating_value = float(store_rating) if store_rating not in (None, '') else 0.0
            except (TypeError, ValueError):
                rating_value = 0.0
            # 星評価ウィジェットを設定（編集不可）
            star_widget = StarRatingWidget(self.route_template_table, rating=rating_value, star_size=14)
            star_widget.setEnabled(False)  # 編集不可にする
            self.route_template_table.setCellWidget(row, 9, star_widget)
            
            # メモ列（列インデックス10）は読み込み専用
            # 店舗マスタの備考欄からメモを取得して表示
            store_code = visit.get('store_code', '')
            memo_text = visit.get('store_notes', '')
            if store_code and not memo_text:
                # 店舗マスタから備考を取得
                store_info = self.store_db.get_store_by_supplier_code(store_code)
                if store_info:
                    custom_fields = store_info.get('custom_fields', {})
                    memo_text = custom_fields.get('notes', '')
            
            _set(10, memo_text)
        
        # 列幅の調整（評価列の右端が見切れないように）
        self.route_template_table.resizeColumnsToContents()
        
        # 評価列（列インデックス9）の幅を自動調整（StarRatingWidgetのsizeHint()に基づく）
        # 最初の行の星評価ウィジェットから実際のサイズを取得
        if len(visits) > 0:
            first_star_widget = self.route_template_table.cellWidget(0, 9)
            if first_star_widget and isinstance(first_star_widget, StarRatingWidget):
                # sizeHint()で推奨サイズを取得
                recommended_size = first_star_widget.sizeHint()
                # 余裕を持たせて+10px追加
                rating_column_width = recommended_size.width() + 10
                self.route_template_table.setColumnWidth(9, rating_column_width)
            else:
                # フォールバック: 固定幅を設定
                self.route_template_table.setColumnWidth(9, 130)
        else:
            # データがない場合のフォールバック
            self.route_template_table.setColumnWidth(9, 130)

    def _save_memos_to_store_master(self, visits: List[Dict[str, Any]]):
        """ルートテンプレート読み込み時にメモ欄があれば店舗マスタの備考欄に保存・追記"""
        for visit in visits:
            store_code = visit.get('store_code', '')
            memo_text = visit.get('store_notes', '').strip()
            
            # メモ欄が空の場合はスキップ
            if not store_code or not memo_text:
                continue
            
            # 店舗マスタから現在の備考を取得
            store_info = self.store_db.get_store_by_supplier_code(store_code)
            if not store_info:
                continue
            
            # custom_fieldsから現在のnotesを取得
            custom_fields = store_info.get('custom_fields', {})
            current_notes = custom_fields.get('notes', '').strip()
            
            # 新しいメモを追記（カンマ区切り）
            if current_notes:
                # 既存の備考に新しいメモを追記（重複チェック）
                notes_list = [n.strip() for n in current_notes.split(',') if n.strip()]
                if memo_text not in notes_list:
                    notes_list.append(memo_text)
                    updated_notes = ', '.join(notes_list)
                else:
                    updated_notes = current_notes  # 既に存在する場合は変更なし
            else:
                updated_notes = memo_text  # 既存の備考がない場合は新しいメモを設定
            
            # 店舗マスタの備考欄を更新
            custom_fields['notes'] = updated_notes
            store_data = {
                'affiliated_route_name': store_info.get('affiliated_route_name'),
                'route_code': store_info.get('route_code'),
                'supplier_code': store_info.get('supplier_code'),
                'store_name': store_info.get('store_name'),
                'address': store_info.get('address'),
                'phone': store_info.get('phone'),
                'custom_fields': custom_fields
            }
            
            try:
                self.store_db.update_store(store_info['id'], store_data)
            except Exception as e:
                print(f"店舗マスタの備考欄更新エラー: {e}")
    
    def _calculate_store_rating_from_visit(self, visit: Dict[str, Any]) -> float:
        """店舗訪問データから評価を計算（ルート登録タブのロジックに合わせる）"""
        try:
            # 仕入れ点数、想定粗利、滞在時間を取得
            qty = self._safe_float(visit.get('store_item_count', 0))
            profit = self._safe_float(visit.get('store_gross_profit', 0))
            stay = self._safe_float(visit.get('stay_duration', 0))
            
            if qty <= 0 or profit <= 0:
                return 0.0
            
            stay = max(1.0, stay)
            
            # 基礎スコアを決定（仕入れ点数ベース）
            base_score = self._determine_base_score(int(round(qty)))
            
            # 粗利係数を計算
            profit_per_minute = profit / stay
            profit_threshold = 190.0
            profit_scale = 30.0
            profit_factor = max(0.0, min(5.0, (profit_per_minute - profit_threshold) / profit_scale))
            
            # 最終スコアを計算
            base_weight = 0.7
            profit_weight = 0.3
            final_score = (base_weight * base_score) + (profit_weight * profit_factor)
            
            # 0.0〜5.0の範囲に制限し、0.5刻みに丸める
            final_score = max(0.0, min(5.0, final_score))
            return round(final_score * 2) / 2
        except Exception as e:
            print(f"評価計算エラー: {e}")
            return 0.0
    
    def _determine_base_score(self, item_count: int) -> int:
        """仕入れ点数から基礎スコアを決定"""
        if item_count >= 10:
            return 5
        if item_count >= 7:
            return 4
        if item_count >= 5:
            return 3
        if item_count >= 3:
            return 2
        if item_count >= 1:
            return 1
        return 0
    
    def _safe_float(self, value: Any) -> float:
        """安全にfloatに変換"""
        if value is None or value == '':
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    
    @staticmethod
    def _format_hm(value: Optional[str]) -> str:
        if not value:
            return ''
        text = str(value)
        if ' ' in text:
            text = text.split(' ')[1]
        return text[:5]

    def save_combined_snapshot(self):
        if self.inventory_data is None or len(self.inventory_data) == 0:
            QMessageBox.information(self, "統合保存", "仕入データがありません。")
            return
        if not self.route_summary_widget:
            QMessageBox.information(self, "統合保存", "ルートテンプレートが未ロードです。")
            return
        try:
            purchase_records = self.inventory_data.fillna("").to_dict(orient="records")
        except Exception:
            purchase_records = []
        route_data = self.route_summary_widget.get_route_data()
        visits = self.route_summary_widget.get_store_visits_data()
        payload = {"route": route_data, "visits": visits}
        route_date = route_data.get('route_date', '')
        route_code = route_data.get('route_code', '')
        snapshot_name = (route_date or "未設定").strip()
        if route_code:
            snapshot_name = f"{snapshot_name} {route_code}".strip()
        if not snapshot_name or snapshot_name == "未設定":
            from datetime import datetime
            snapshot_name = datetime.now().strftime("Snapshot %Y-%m-%d %H:%M:%S")
        self.route_snapshot_db.save_snapshot(snapshot_name, purchase_records, payload)
        QMessageBox.information(self, "統合保存", f"統合スナップショットを保存しました。\n{snapshot_name}")

    def open_combined_snapshot_history(self):
        snapshots = self.route_snapshot_db.list_snapshots()
        if not snapshots:
            QMessageBox.information(self, "統合読込", "統合スナップショットがありません。")
            return
        
        # カスタムダイアログを使用
        dlg = CombinedSnapshotDialog(self.route_snapshot_db, self)
        res = dlg.exec()
        if res == QDialog.Accepted:
            snapshot_id = dlg.get_selected_snapshot_id()
            if snapshot_id:
                snapshot = self.route_snapshot_db.get_snapshot(snapshot_id)
                if not snapshot:
                    QMessageBox.warning(self, "統合読込", "選択したスナップショットを取得できませんでした。")
                    return
                self._restore_combined_snapshot(snapshot)

    def _restore_combined_snapshot(self, snapshot: Dict[str, Any]):
        try:
            purchase_data = snapshot.get("purchase_data") or []
            if purchase_data:
                try:
                    self.inventory_data = pd.DataFrame(purchase_data)
                except Exception:
                    self.inventory_data = pd.DataFrame()
                self.filtered_data = self.inventory_data.copy()
                
                # SKU自動マッチング処理（商品DBから仕入れ日・ASINで検索）
                self._auto_match_sku_from_product_db()
                
                self.update_table()
                self.update_data_count()
            else:
                self.inventory_data = pd.DataFrame()
                self.filtered_data = self.inventory_data
                self.update_table()
                self.update_data_count()
            
            route_payload = snapshot.get("route_data") or {}
            route_data = route_payload.get("route", {})
            visits = route_payload.get("visits", [])
            if self.route_summary_widget and route_data:
                if hasattr(self.route_summary_widget, "apply_route_snapshot"):
                    self.route_summary_widget.apply_route_snapshot(route_data, visits)
                self.refresh_route_template_view()
            # route_template_status は削除済み（スナップショット読込メッセージは表示しない）
            QMessageBox.information(self, "統合読込", "統合スナップショットを読み込みました。")
        except Exception as e:
            QMessageBox.critical(self, "統合読込エラー", f"スナップショットの読み込みに失敗しました:\n{e}")

    # アクションボタンはファイル操作エリアに統合済み
    
    def _auto_match_sku_from_product_db(self):
        """
        商品DBから仕入れ日とASINでマッチングしてSKUを自動設定する
        
        取り込んだデータ一覧のSKUが「未実装」の行について、
        商品DBタブの仕入DBに仕入れ日・ASINを確認してマッチする物はSKUを取得して設定する
        """
        if self.inventory_data is None or len(self.inventory_data) == 0:
            return
        
        matched_count = 0
        try:
            # 商品DBタブの仕入DBから最新スナップショットを取得
            purchase_records = []
            try:
                snapshots = self.product_purchase_db.list_snapshots()
                if snapshots:
                    latest_snapshot = self.product_purchase_db.get_snapshot(snapshots[0]["id"])
                    if latest_snapshot and latest_snapshot.get("data"):
                        purchase_records = latest_snapshot["data"]
            except Exception:
                pass
            
            # SKUが「未実装」の行をチェック
            for idx, row in self.inventory_data.iterrows():
                sku = str(row.get('SKU', '')).strip()
                # NaNや空文字列も「未実装」として扱う
                if pd.isna(row.get('SKU')) or sku == '' or sku == 'nan' or sku == 'None':
                    sku = '未実装'
                
                if sku != '未実装':
                    continue
                
                # 仕入れ日とASINを取得
                purchase_date = str(row.get('仕入れ日', '')).strip()
                asin = str(row.get('ASIN', '')).strip()
                
                # 仕入れ日とASINが両方ある場合のみ検索
                if not purchase_date or not asin or purchase_date == 'nan' or asin == 'nan':
                    continue
                
                matched_sku = None
                
                # 1. 商品DBタブの仕入DB（最新スナップショット）から検索
                if purchase_records:
                    normalized_target_date = self._normalize_date_for_match(purchase_date)
                    for purchase_record in purchase_records:
                        record_date = str(purchase_record.get('仕入れ日', '') or purchase_record.get('purchase_date', '')).strip()
                        record_asin = str(purchase_record.get('ASIN', '') or purchase_record.get('asin', '')).strip()
                        record_sku = str(purchase_record.get('SKU', '') or purchase_record.get('sku', '')).strip()
                        
                        normalized_record_date = self._normalize_date_for_match(record_date)
                        
                        # 日付形式を正規化して比較
                        if normalized_record_date == normalized_target_date:
                            if record_asin.upper() == asin.upper() and record_sku and record_sku != '未実装':
                                matched_sku = record_sku
                                break
                
                # 2. 商品DB（productsテーブル）から検索（フォールバック）
                if not matched_sku:
                    product = self.product_db.find_by_date_and_asin(purchase_date, asin)
                    if product and product.get('sku'):
                        matched_sku = product['sku']
                
                # SKUを設定
                if matched_sku:
                    self.inventory_data.at[idx, 'SKU'] = matched_sku
                    matched_count += 1
            
            # マッチした場合はfiltered_dataも更新してテーブルを再描画
            if matched_count > 0:
                self.filtered_data = self.inventory_data.copy()
                self.update_table()
        except Exception:
            pass
    
    def _normalize_date_for_match(self, date_str: str) -> str:
        """
        日付文字列を正規化して比較用の形式に変換
        
        例:
        - "2025/11/8 10:22" -> "2025-11-08"
        - "2025-11-08" -> "2025-11-08"
        - "2025/11/08" -> "2025-11-08"
        """
        if not date_str or date_str == 'nan':
            return ''
        
        date_str = str(date_str).strip()
        
        # 時刻部分を削除
        if ' ' in date_str:
            date_str = date_str.split(' ')[0]
        
        # スラッシュをハイフンに変換
        date_str = date_str.replace('/', '-')
        
        # 日付部分を抽出（yyyy-MM-dd形式に統一）
        parts = date_str.split('-')
        if len(parts) >= 3:
            year = parts[0].zfill(4)
            month = parts[1].zfill(2)
            day = parts[2].zfill(2)
            return f"{year}-{month}-{day}"
        
        return date_str
        
    def import_csv(self):
        """CSVファイルの取込"""
        # デフォルトディレクトリを設定（デバッグ用：暫定的に変更）
        default_dir = r"D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\20251026鎌倉ルート"
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "CSVファイルを選択",
            default_dir,
            "CSVファイル (*.csv);;すべてのファイル (*)"
        )
        
        if file_path:
            try:
                # CSVファイルの読み込み（複数エンコーディング対応）
                df = self._read_csv_with_encoding_fallback(file_path)
                
                # 列マッピングと並び替え
                self.inventory_data = self._map_and_reorder_columns(df)
                self.filtered_data = self.inventory_data.copy()
                
                # SKU自動マッチング処理（商品DBから仕入れ日・ASINで検索）
                self._auto_match_sku_from_product_db()
                
                # テーブルの更新
                self.update_table()
                
                # ボタンの有効化
                self.export_btn.setEnabled(True)
                self.clear_btn.setEnabled(True)
                self.save_btn.setEnabled(True)
                self.generate_sku_btn.setEnabled(True)
                self.export_listing_btn.setEnabled(True)
                self.antique_register_btn.setEnabled(True)
                
                # データ件数の更新
                self.update_data_count()
                
                QMessageBox.information(
                    self, 
                    "取込完了", 
                    f"CSVファイルを読み込みました（{len(self.inventory_data)}行）"
                )
                
                # シグナル発火
                self.data_loaded.emit(len(self.inventory_data))
                
            except Exception as e:
                QMessageBox.warning(self, "エラー", f"CSVファイルの読み込みに失敗しました:\n{str(e)}")
    
    def _read_csv_with_encoding_fallback(self, file_path):
        """複数エンコーディングでCSVファイルを読み込む"""
        encodings = ['utf-8', 'shift_jis', 'cp932', 'utf-8-sig', 'iso-2022-jp']
        
        for encoding in encodings:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                print(f"CSV読み込み成功: エンコーディング={encoding}, 行数={len(df)}")
                return df
            except UnicodeDecodeError:
                print(f"エンコーディング {encoding} で読み込み失敗、次のエンコーディングを試行")
                continue
            except Exception as e:
                print(f"エンコーディング {encoding} で予期しないエラー: {e}")
                continue
        
        # すべてのエンコーディングで失敗した場合
        raise Exception("すべてのエンコーディングでCSVファイルの読み込みに失敗しました")
    
    def _map_and_reorder_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """CSV列を指定順序にマッピング・並び替え"""
        # CSVファイルの列名と新しい列名のマッピング
        # 参考データ: StockList_20250927_2108_standard.csv
        column_mapping = {
            # 仕入れ日
            "仕入日": "仕入れ日",
            "仕入れ日": "仕入れ日",
            "日付": "仕入れ日",
            # コンディション
            "状態": "コンディション",
            "コンディション": "コンディション",
            "condition": "コンディション",
            # ASIN
            "ASIN": "ASIN",
            "asin": "ASIN",
            # JAN
            "JAN": "JAN",
            "jan": "JAN",
            "JANコード": "JAN",
            # 商品名
            "商品名": "商品名",
            "商品名": "商品名",
            "title": "商品名",
            "name": "商品名",
            # 仕入れ個数
            "仕入個数": "仕入れ個数",
            "仕入れ個数": "仕入れ個数",
            "数量": "仕入れ個数",
            "quantity": "仕入れ個数",
            # 仕入れ価格
            "仕入価格": "仕入れ価格",
            "仕入れ価格": "仕入れ価格",
            "原価": "仕入れ価格",
            "cost": "仕入れ価格",
            "purchasePrice": "仕入れ価格",
            # 販売予定価格
            "販売予定価格": "販売予定価格",
            "価格": "販売予定価格",
            "price": "販売予定価格",
            "plannedPrice": "販売予定価格",
            # 見込み利益
            "見込み利益": "見込み利益",
            "利益": "見込み利益",
            "profit": "見込み利益",
            "expectedProfit": "見込み利益",
            # 損益分岐点
            "損益分岐点": "損益分岐点",
            "akaji": "損益分岐点",
            "breakEven": "損益分岐点",
            # コメント
            "コメント": "コメント",
            "備考": "コメント",
            "comment": "コメント",
            "notes": "コメント",
            # 発送方法
            "発送方法": "発送方法",
            "配送方法": "発送方法",
            "shippingMethod": "発送方法",
            "shipping_method": "発送方法",
            "発送": "発送方法",
            # 仕入先
            "仕入先": "仕入先",
            "仕入元": "仕入先",
            "店舗": "仕入先",
            "supplier": "仕入先",
            # コンディション説明（後で処理予定、一旦空）
            "コンディション説明": "コンディション説明",
            "conditionNote": "コンディション説明",
            # SKU（取込時は空でもOK）
            "SKU": "SKU",
            "sku": "SKU",
        }
        
        # 新しいDataFrameを作成
        new_df = pd.DataFrame()
        
        # 指定順序で列を作成
        for new_column in self.column_headers:
            # 元のDataFrameから該当する列を探す
            found = False
            for old_column in df.columns:
                # 列名の正規化（空白除去、大文字小文字統一）
                old_col_normalized = str(old_column).strip()
                
                # マッピングから探す
                if old_col_normalized in column_mapping:
                    if column_mapping[old_col_normalized] == new_column:
                        new_df[new_column] = df[old_column]
                        found = True
                        break
                
                # 直接一致する場合
                if old_col_normalized == new_column:
                    new_df[new_column] = df[old_column]
                    found = True
                    break
            
            # 列が見つからない場合は空の列を作成
            if not found:
                new_df[new_column] = ""
        
        # コンディション説明欄を空にする
        if "コンディション説明" in new_df.columns:
            new_df["コンディション説明"] = ""
        
        # SKUが空の場合は「未実装」にする
        if "SKU" in new_df.columns:
            new_df["SKU"] = new_df["SKU"].fillna("").astype(str)
            new_df["SKU"] = new_df["SKU"].replace("nan", "")
            # 空の場合は「未実装」に設定
            new_df["SKU"] = new_df["SKU"].apply(lambda x: "未実装" if x == "" or pd.isna(x) else x)
        
        return new_df
                
    def update_table(self):
        """テーブルの更新"""
        if self.filtered_data is None:
            return
            
        # テーブルの設定
        row_count = len(self.filtered_data)
        print(f"[DEBUG] update_table: filtered_data行数={row_count}, inventory_data行数={len(self.inventory_data) if self.inventory_data is not None else 0}")
        self.data_table.setRowCount(row_count)
        
        # データの設定（テーブルの行番号は0から始まる連続した番号にする）
        processed_rows = 0
        try:
            # iterrows()の代わりに、インデックスで直接アクセス
            for table_row_idx in range(row_count):
                if table_row_idx >= len(self.filtered_data):
                    break
                row = self.filtered_data.iloc[table_row_idx]
                for j, column in enumerate(self.column_headers):
                    # Seriesから値を取得（get()ではなく直接アクセス）
                    if column in row.index:
                        value = row[column]
                    else:
                        value = ""
                    value = str(value) if pd.notna(value) else ""
                    
                    # SKU列の特別処理（空の場合は「未実装」と表示）
                    if column == "SKU":
                        if not value or value == "" or value == "nan" or pd.isna(value):
                            item = QTableWidgetItem("未実装")
                        else:
                            item = QTableWidgetItem(str(value))
                    # 商品名列の特別処理（50文字制限+ツールチップ）
                    elif column == "商品名":
                        original_value = value
                        display_value = original_value[:50] + '...' if len(original_value) > 50 else original_value
                        item = QTableWidgetItem(display_value)
                        # 常にフルテキストをツールチップ/UserRoleに保持（保存時はこれを使う）
                        item.setToolTip(original_value)
                        item.setData(Qt.UserRole, original_value)
                    else:
                        item = QTableWidgetItem(value)
                    
                    # 価格列の数値フォーマット
                    if column in ["仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点"]:
                        try:
                            # 数値に変換できるかチェック
                            if value and str(value).replace(".", "").replace("-", "").replace(",", "").isdigit():
                                num_value = float(str(value).replace(",", ""))
                                item.setText(f"{num_value:,.0f}")
                            else:
                                item.setText(str(value))
                        except:
                            item.setText(str(value))
                    
                    self.data_table.setItem(table_row_idx, j, item)
                processed_rows = max(processed_rows, table_row_idx + 1)
        except Exception as e:
            print(f"[ERROR] update_table: データ設定中にエラー発生: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"[DEBUG] update_table: 処理完了。設定した行数={processed_rows}, テーブルの行数={self.data_table.rowCount()}, filtered_data行数={row_count}")
        
        # 行数が一致しない場合は再設定
        if self.data_table.rowCount() != row_count:
            print(f"[WARNING] update_table: テーブルの行数が不一致。再設定します。現在={self.data_table.rowCount()}, 期待値={row_count}")
            self.data_table.setRowCount(row_count)
        
        # 列幅の自動調整
        self.data_table.resizeColumnsToContents()
        
        # 最終確認: テーブルの行数を再度確認
        final_row_count = self.data_table.rowCount()
        if final_row_count != row_count:
            print(f"[ERROR] update_table: 最終確認で行数が不一致。テーブル={final_row_count}, 期待値={row_count}")

        # 除外ハイライトがONなら適用
        if self.excluded_highlight_on:
            self.update_excluded_highlight()

    def _is_excluded_row(self, row: dict) -> bool:
        """除外条件の判定: コメントに『除外』または 発送方法がFBA以外"""
        try:
            comment = str(row.get('コメント', '') or '')
            if '除外' in comment:
                return True
            ship = str(row.get('発送方法', '') or '').strip().upper()
            if ship == '':
                return True
            return ship != 'FBA'
        except Exception:
            return True

    def toggle_excluded_highlight(self):
        self.excluded_highlight_on = not self.excluded_highlight_on
        if self.excluded_highlight_on:
            self.update_excluded_highlight()
            self.toggle_excluded_btn.setText("除外ハイライト解除")
        else:
            self.clear_excluded_highlight()
            self.toggle_excluded_btn.setText("除外商品確認")

    def update_excluded_highlight(self):
        """除外ではない商品を明確にハイライト（背景＋太字）"""
        try:
            if self.filtered_data is None:
                return
            rows = self.data_table.rowCount()
            for i in range(rows):
                # 現在行の辞書を作成
                row_dict = {}
                for j, column in enumerate(self.column_headers):
                    item = self.data_table.item(i, j)
                    row_dict[column] = item.text() if item else ''
                is_ex = self._is_excluded_row(row_dict)
                for j in range(self.data_table.columnCount()):
                    cell = self.data_table.item(i, j)
                    if not cell:
                        continue
                    if not is_ex:
                        # 除外ではない行を強調（淡い青系）
                        cell.setData(Qt.BackgroundRole, QColor(200, 225, 255))
                        cell.setData(Qt.ForegroundRole, QColor(0, 0, 0))
                        f = cell.font(); f.setBold(True); cell.setFont(f)
                    else:
                        # 除外行は通常表示（交互行色）
                        cell.setData(Qt.BackgroundRole, None)
                        cell.setData(Qt.ForegroundRole, None)
                        f = cell.font(); f.setBold(False); cell.setFont(f)
                        if i % 2 == 0:
                            cell.setBackground(QColor(255, 255, 255))
                        else:
                            cell.setBackground(QColor(240, 240, 240))
        except Exception as e:
            print(f"除外ハイライト更新エラー: {e}")

    def clear_excluded_highlight(self):
        try:
            rows = self.data_table.rowCount()
            for i in range(rows):
                for j in range(self.data_table.columnCount()):
                    cell = self.data_table.item(i, j)
                    if not cell:
                        continue
                    cell.setData(Qt.BackgroundRole, None)
                    cell.setData(Qt.ForegroundRole, None)
                    f = cell.font(); f.setBold(False); cell.setFont(f)
                    if i % 2 == 0:
                        cell.setBackground(QColor(255, 255, 255))
                    else:
                        cell.setBackground(QColor(240, 240, 240))
        except Exception as e:
            print(f"除外ハイライト解除エラー: {e}")
        
    def apply_filters(self):
        """フィルタの適用"""
        if self.inventory_data is None:
            return
            
        # 検索条件
        search_text = self.search_edit.text().lower()
        
        # Q列フィルタ（存在する場合のみ）
        q_filter = ""
        if hasattr(self, 'q_filter_combo') and self.q_filter_combo:
            q_filter = self.q_filter_combo.currentText()
        
        # 価格範囲フィルタ
        min_price = self.min_price_spin.value()
        max_price = self.max_price_spin.value()
        
        # フィルタの適用
        mask = pd.Series([True] * len(self.inventory_data))
        
        # 検索フィルタ
        if search_text:
            search_mask = (
                self.inventory_data.get("商品名", "").str.lower().str.contains(search_text, na=False) |
                self.inventory_data.get("ASIN", "").str.lower().str.contains(search_text, na=False) |
                self.inventory_data.get("JAN", "").str.lower().str.contains(search_text, na=False)
            )
            mask &= search_mask
        
        # Q列フィルタ（Q列は現在の列構成に含まれていないため、一旦コメントアウト）
        # if q_filter != "すべて":
        #     if q_filter == "Qなし":
        #         q_mask = self.inventory_data.get("Q列", "").isna() | (self.inventory_data.get("Q列", "") == "")
        #     else:
        #         q_mask = self.inventory_data.get("Q列", "") == q_filter
        #     mask &= q_mask
        
        # 価格範囲フィルタ（販売予定価格でフィルタ）
        if "販売予定価格" in self.inventory_data.columns:
            try:
                price_series = pd.to_numeric(self.inventory_data["販売予定価格"], errors='coerce')
                price_mask = (price_series >= min_price) & (price_series <= max_price)
                mask &= price_mask
            except:
                pass
        
        # フィルタ結果の適用
        self.filtered_data = self.inventory_data[mask].copy()
        
        # テーブルの更新
        self.update_table()
        self.update_data_count()
        
    def clear_search(self):
        """検索のクリア"""
        self.search_edit.clear()
        
    def reset_filters(self):
        """フィルタのリセット"""
        self.search_edit.clear()
        # self.q_filter_combo.setCurrentText("すべて")  # Q列フィルタは非表示
        self.min_price_spin.setValue(0)
        self.max_price_spin.setValue(999999)
    
    def on_data_selection_changed(self):
        """データテーブルの選択変更時の処理（商品名列のハイライト）"""
        try:
            # 選択された行を取得
            selected_items = self.data_table.selectedItems()
            if not selected_items:
                return
            
            # 最初の選択されたアイテムの行番号を取得
            current_row = selected_items[0].row()
            
            # 商品名列を探す
            product_name_column = -1
            for j in range(self.data_table.columnCount()):
                header_item = self.data_table.horizontalHeaderItem(j)
                if header_item and header_item.text() == '商品名':
                    product_name_column = j
                    break
            
            # 商品名列が見つかった場合、その列にスクロール・ハイライト
            if product_name_column >= 0:
                # 水平スクロールで商品名列を表示
                item = self.data_table.item(current_row, product_name_column)
                if item:
                    self.data_table.scrollToItem(
                        item,
                        QTableWidget.PositionAtCenter
                    )
                    
                    # 商品名列のセルをハイライト
                    for j in range(self.data_table.columnCount()):
                        row_item = self.data_table.item(current_row, j)
                        if row_item:
                            if j == product_name_column:
                                # 商品名列は黄色でハイライト
                                row_item.setBackground(QColor(255, 255, 200))
                            else:
                                # 他の列は通常の背景色（交互行色を維持）
                                if current_row % 2 == 0:
                                    row_item.setBackground(QColor(255, 255, 255))
                                else:
                                    row_item.setBackground(QColor(240, 240, 240))
                                    
        except Exception as e:
            print(f"選択変更処理エラー: {e}")
        
    def update_data_count(self):
        """データ件数の更新"""
        if self.filtered_data is not None:
            total_count = len(self.inventory_data) if self.inventory_data is not None else 0
            filtered_count = len(self.filtered_data)
            self.data_count_label.setText(f"データ件数: {filtered_count}/{total_count}")
            
            # 統計情報の更新
            self.update_stats()
        else:
            self.data_count_label.setText("データ件数: 0")
            
    def update_stats(self):
        """統計情報の更新"""
        if self.filtered_data is None or len(self.filtered_data) == 0:
            self.stats_label.setText("統計: なし")
            return
            
        # 基本統計
        total_items = len(self.filtered_data)
        
        # コンディション統計
        try:
            if "コンディション" in self.filtered_data.columns:
                condition_counts = self.filtered_data["コンディション"].value_counts()
                condition_stats = ", ".join([f"{cond}: {count}" for cond, count in condition_counts.items() if cond])
            else:
                condition_stats = "コンディション: なし"
        except Exception as e:
            print(f"コンディション統計エラー: {e}")
            condition_stats = "コンディション: エラー"
        
        # 価格統計（販売予定価格で統計）
        try:
            if "販売予定価格" in self.filtered_data.columns:
                prices = pd.to_numeric(self.filtered_data["販売予定価格"], errors='coerce')
                avg_price = prices.mean()
                total_value = prices.sum()
                price_stats = f"平均価格: {avg_price:,.0f}円, 合計: {total_value:,.0f}円"
            else:
                price_stats = "価格統計: なし"
        except Exception as e:
            print(f"価格統計エラー: {e}")
            price_stats = "価格統計: エラー"
        
        stats_text = f"統計: {total_items}件, {condition_stats}, {price_stats}"
        self.stats_label.setText(stats_text)
        
    def clear_data(self):
        """データのクリア"""
        self.inventory_data = None
        self.filtered_data = None
        self.data_table.setRowCount(0)
        
        # ボタンの無効化
        self.export_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.generate_sku_btn.setEnabled(False)
        self.export_listing_btn.setEnabled(False)
        self.antique_register_btn.setEnabled(False)
        
        # 表示のクリア
        self.data_count_label.setText("データ件数: 0")
        self.stats_label.setText("統計: なし")
        
    def generate_sku(self):
        """SKU生成（店舗マスタ連携対応）"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
            
        try:
            # データを辞書形式に変換（除外商品を除く）
            all_list = self.filtered_data.to_dict('records')
            data_list = [r for r in all_list if not self._is_excluded_row(r)]
            excluded_count = len(all_list) - len(data_list)
            
            # 各商品データに店舗情報を追加
            enriched_data = []
            store_not_found_warnings = []
            
            for item in data_list:
                enriched_item = item.copy()
                
                # 「仕入先」列から仕入れ先コードを取得
                supplier_code = item.get('仕入先', '').strip()
                
                if supplier_code:
                    # 店舗マスタから店舗情報を取得
                    store_info = self.store_db.get_store_by_supplier_code(supplier_code)
                    
                    if store_info:
                        # 店舗情報を追加
                        enriched_item['supplier_code'] = supplier_code
                        enriched_item['store_name'] = store_info.get('store_name', '')
                        enriched_item['store_id'] = store_info.get('id')
                    else:
                        # 店舗が見つからない場合の警告を記録
                        store_not_found_warnings.append(supplier_code)
                        enriched_item['supplier_code'] = supplier_code
                        enriched_item['store_name'] = ''
                        enriched_item['store_id'] = None
                else:
                    # 仕入先コードが空の場合は警告を記録
                    enriched_item['supplier_code'] = ''
                    enriched_item['store_name'] = ''
                    enriched_item['store_id'] = None
                
                enriched_data.append(enriched_item)
            
            # 警告メッセージの表示（店舗が見つからない場合）
            unique_warnings = []
            if store_not_found_warnings:
                unique_warnings = list(set(store_not_found_warnings))
                warning_msg = f"以下の仕入れ先コードに対応する店舗が見つかりませんでした:\n{', '.join(unique_warnings[:5])}"
                if len(unique_warnings) > 5:
                    warning_msg += f"\n他 {len(unique_warnings) - 5}件..."
                QMessageBox.warning(self, "店舗情報警告", warning_msg)
            
            # APIクライアントでSKU生成
            result = self.api_client.inventory_generate_sku(enriched_data)
            
            if result['status'] == 'success':
                # 生成されたSKUをテーブルに反映
                self.update_table_with_sku(result['results'])
                
                # 統計情報の更新
                self.update_stats()
                
                generated_count = result['generated_count']
                success_msg = f"SKU生成が完了しました\n生成数: {generated_count}件"
                if unique_warnings:
                    success_msg += f"\n（店舗未登録: {len(unique_warnings)}件）"
                
                QMessageBox.information(
                    self, 
                    "SKU生成完了", 
                    success_msg
                )
                
                # シグナル発火
                self.sku_generated.emit(result['generated_count'])
            else:
                QMessageBox.warning(self, "SKU生成失敗", "SKU生成に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"SKU生成中にエラーが発生しました:\n{str(e)}")
    
    def update_table_with_sku(self, sku_results):
        """SKU生成結果をテーブルに反映"""
        try:
            # 元データにSKU情報を追加
            used_rows = set()
            for idx_result, result in enumerate(sku_results):
                if result['status'] == 'success':
                    # 元データの該当行を特定（ASINや商品名でマッチング）
                    original_data = result['original_data']
                    generated_sku = result['generated_sku']
                    q_tag = result['q_tag']
                    
                    # 元データの該当行を更新
                    def _norm(s: str) -> str:
                        return str(s or '').strip().replace('\u3000', ' ')

                    asin = _norm(original_data.get('ASIN') or original_data.get('asin'))
                    jan = _norm(original_data.get('JAN') or original_data.get('jan'))
                    name = _norm(original_data.get('商品名') or original_data.get('product_name'))

                    matched_index = None
                    # 1) ASIN一致
                    if asin:
                        for i, row in self.inventory_data.iterrows():
                            if i in used_rows:
                                continue
                            if _norm(row.get('ASIN')) == asin:
                                matched_index = i; break
                    # 2) JAN一致
                    if matched_index is None and jan:
                        for i, row in self.inventory_data.iterrows():
                            if i in used_rows:
                                continue
                            if _norm(row.get('JAN')) == jan:
                                matched_index = i; break
                    # 3) 商品名（ゆるめ）
                    if matched_index is None and name:
                        for i, row in self.inventory_data.iterrows():
                            if i in used_rows:
                                continue
                            if _norm(row.get('商品名')).lower() == name.lower():
                                matched_index = i; break
                    # 4) 表示順で最初の未実装
                    if matched_index is None:
                        for i, row in self.inventory_data.iterrows():
                            if i in used_rows:
                                continue
                            if str(row.get('SKU', '')) in ('', '未実装'):
                                matched_index = i; break
                    # 5) 最後の保険: インデックス
                    if matched_index is None and idx_result < len(self.inventory_data):
                        matched_index = idx_result

                    if matched_index is not None:
                        self.inventory_data.at[matched_index, 'SKU'] = generated_sku
                        used_rows.add(matched_index)
            
            # フィルタデータも更新
            self.filtered_data = self.inventory_data.copy()
            
            # テーブルの再描画
            self.update_table()
            
        except Exception as e:
            print(f"テーブル更新エラー: {e}")
        
    def export_csv(self):
        """CSV出力"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "出力するデータがありません")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "CSVファイルを保存",
            "inventory_preview.csv",
            "CSVファイル (*.csv)"
        )
        
        if file_path:
            try:
                from pathlib import Path
                from desktop.utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(file_path))
                self.filtered_data.to_csv(str(target), index=False, encoding='utf-8')
                QMessageBox.information(self, "出力完了", f"プレビュー用CSVを保存しました（UTF-8）。出品用は『出品CSV生成』をご利用ください。\n{str(target)}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")
                
    def get_table_data(self) -> pd.DataFrame:
        """テーブルから現在のデータを取得してDataFrameに変換"""
        try:
            row_count = self.data_table.rowCount()
            if row_count == 0:
                return pd.DataFrame()
            
            # テーブルのデータをリストに収集
            data_rows = []
            for i in range(row_count):
                row_data = {}
                for j, column in enumerate(self.column_headers):
                    item = self.data_table.item(i, j)
                    value = item.text() if item else ""
                    # 商品名はUserRoleに保持したフルテキストを優先
                    if column == "商品名" and item is not None:
                        full = item.data(Qt.UserRole)
                        if full is not None and str(full).strip():
                            value = str(full)
                        # UserRoleが空の場合は、表示テキストから「...」を除去して使用（既存データ対応）
                        elif value.endswith('...'):
                            # 表示テキストが50文字+「...」の場合は、元のデータを探す
                            # ただし、既に切られている場合は復元できない
                            pass
                    
                    # 数値列の特別処理（カンマ区切りを除去）
                    if column in ["仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "仕入れ個数"]:
                        try:
                            # カンマを除去して数値に変換
                            value_str = str(value).replace(",", "").strip()
                            if value_str == "" or value_str == "未実装" or value_str == "nan" or pd.isna(value):
                                row_data[column] = None
                            else:
                                # 数値に変換を試みる
                                if "." in value_str:
                                    row_data[column] = float(value_str)
                                else:
                                    row_data[column] = int(value_str)
                        except (ValueError, TypeError) as e:
                            # 変換に失敗した場合は元の値をそのまま使用
                            row_data[column] = value
                    # SKU列の特別処理（「未実装」は空文字に変換）
                    elif column == "SKU":
                        if value == "未実装":
                            row_data[column] = ""
                        else:
                            row_data[column] = value
                    else:
                        row_data[column] = value
                
                data_rows.append(row_data)
            
            # DataFrameに変換
            df = pd.DataFrame(data_rows)
            
            # 列の順序を維持
            if len(df) > 0:
                df = df[self.column_headers]
            
            return df
            
        except Exception as e:
            print(f"テーブルデータ取得エラー: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def sync_inventory_data_from_table(self):
        """テーブルの内容をinventory_dataに同期"""
        try:
            # テーブルからデータを取得
            table_df = self.get_table_data()
            
            if len(table_df) == 0:
                return False
            
            # フィルタが適用されていない場合は、テーブルのデータをそのまま使用
            # フィルタが適用されている場合も、テーブルに表示されているデータを
            # inventory_dataとして使用する（照合再計算では表示されているデータのみを対象とする）
            self.inventory_data = table_df.copy()
            self.filtered_data = table_df.copy()
            
            return True
            
        except Exception as e:
            print(f"inventory_data同期エラー: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def export_listing_csv(self):
        """出品CSV生成"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
            
        try:
            # データを辞書形式に変換
            data_list = self.filtered_data.to_dict('records')
            # 除外商品を除く
            included_list = [r for r in data_list if not self._is_excluded_row(r)]
            excluded_count = len(data_list) - len(included_list)
            
            # 列名をマッピング（日本語→英語）
            mapped_data = []
            for row in included_list:
                # takane 設定が有効なら価格の〇%上で算出
                takane_val = ''
                try:
                    if self.chk_enable_takane.isChecked():
                        pct = int(self.spin_takane_pct.value())
                        base_price = row.get('販売予定価格', 0) or 0
                        # 数値化
                        if isinstance(base_price, str):
                            base_price = float(base_price.replace(',', '')) if base_price else 0
                        takane_val = int(round(float(base_price) * (1.0 + float(pct) / 100.0)))
                except Exception:
                    takane_val = ''

                # タイトル出力の有無
                product_name_val = row.get('商品名', '')
                try:
                    if hasattr(self, 'chk_include_title') and not self.chk_include_title.isChecked():
                        product_name_val = ''
                except Exception:
                    pass

                mapped_row = {
                    'sku': row.get('SKU', ''),
                    'asin': row.get('ASIN', ''),
                    'jan': row.get('JAN', ''),
                    'product_name': product_name_val,
                    'quantity': row.get('仕入れ個数', 1),
                    'plannedPrice': row.get('販売予定価格', 0),
                    'purchasePrice': row.get('仕入れ価格', 0),
                    'breakEven': row.get('損益分岐点', 0),
                    'takane': takane_val,
                    'condition': row.get('コンディション', ''),
                    'conditionNote': row.get('コンディション説明', ''),
                    'priceTrace': row.get('priceTrace', 0)
                }
                mapped_data.append(mapped_row)
            
            # APIクライアントで出品CSV生成
            result = self.api_client.inventory_export_listing(mapped_data)
            
            if result['status'] == 'success':
                # 既定の保存ファイル名（仕入れ日から YYYYMMDD_出品用CSV.csv を生成）
                default_name = "listing_export.csv"
                try:
                    if len(self.filtered_data) > 0:
                        first_date = str(self.filtered_data.iloc[0].get('仕入れ日', '')).strip()
                        from datetime import datetime
                        for fmt in ['%Y/%m/%d', '%Y-%m-%d', '%Y.%m.%d', '%Y%m%d']:
                            try:
                                dt = datetime.strptime(first_date, fmt)
                                default_name = f"{dt.strftime('%Y%m%d')}_出品用CSV.csv"
                                break
                            except ValueError:
                                continue
                except Exception:
                    pass

                # 確認・デバッグ用: 保存先を一時的に固定
                try:
                    from pathlib import Path
                    from desktop.utils.file_naming import resolve_unique_path
                    fixed_dir = Path(r"D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\20251102つくばルート")
                    fixed_dir.mkdir(parents=True, exist_ok=True)
                    target = resolve_unique_path(fixed_dir / default_name)
                    csv_content = result['csv_content']
                    with open(str(target), 'wb') as f:
                        f.write(csv_content)
                    QMessageBox.information(
                        self,
                        "出品CSV生成完了",
                        f"出品CSV生成が完了しました\n出力数: {result['exported_count']}件 (除外 {excluded_count}件)\n保存先: {str(target)}\n(一時的に固定保存フォルダを使用)"
                    )
                except Exception:
                    # フォールバック: 通常の保存ダイアログ
                    file_path, _ = QFileDialog.getSaveFileName(
                        self,
                        "出品CSVファイルを保存",
                        default_name,
                        "CSVファイル (*.csv)"
                    )
                    if file_path:
                        from pathlib import Path
                        from desktop.utils.file_naming import resolve_unique_path
                        target = resolve_unique_path(Path(file_path))
                        csv_content = result['csv_content']
                        with open(str(target), 'wb') as f:
                            f.write(csv_content)
                        QMessageBox.information(
                            self,
                            "出品CSV生成完了",
                            f"出品CSV生成が完了しました\n出力数: {result['exported_count']}件\n保存先: {str(target)}"
                        )
            else:
                QMessageBox.warning(self, "出品CSV生成失敗", "出品CSV生成に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"出品CSV生成中にエラーが発生しました:\n{str(e)}")
    
    def save_inventory_data(self):
        """仕入データを保存"""
        if self.filtered_data is None or len(self.filtered_data) == 0:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
        
        try:
            from PySide6.QtWidgets import QInputDialog
            from datetime import datetime
            
            # まずテーブルの編集内容を DataFrame に同期（手入力の変更を反映）
            self.sync_inventory_data_from_table()
            
            # 仕入れ日の取得（最初の行から）
            first_row = self.filtered_data.iloc[0]
            purchase_date = first_row.get('仕入れ日', '')
            
            # 日付のフォーマット変換
            date_str = ""
            if purchase_date:
                try:
                    # 日付文字列をパース（複数のフォーマットに対応）
                    if isinstance(purchase_date, str):
                        # "2025/11/02" や "2025-11-02" など
                        for fmt in ['%Y/%m/%d', '%Y-%m-%d', '%Y.%m.%d']:
                            try:
                                dt = datetime.strptime(purchase_date, fmt)
                                date_str = dt.strftime('%Y/%m/%d')
                                break
                            except ValueError:
                                continue
                    
                    # パースできなかった場合はそのまま使用
                    if not date_str:
                        date_str = str(purchase_date)
                except Exception:
                    date_str = str(purchase_date)
            
            # ルート名の取得
            route_name = ""
            if self.route_summary_widget:
                try:
                    route_name = self.route_summary_widget.route_code_combo.currentText()
                except Exception:
                    pass
            
            # 保存名の生成
            if date_str and route_name:
                default_name = f"{date_str} {route_name}"
            elif date_str:
                default_name = f"{date_str} 仕入リスト"
            else:
                default_name = f"仕入リスト {len(self.filtered_data)}件"
            
            # スナップショット名の入力ダイアログ
            snapshot_name, ok = QInputDialog.getText(
                self,
                "データ保存",
                f"この名称で保存してよろしいですか？\n編集も可能です:",
                text=default_name
            )
            
            if not ok or not snapshot_name.strip():
                return
            
            # データを辞書形式に変換（同期後の最新データ）
            # 商品名が50文字で切られていないか確認（デバッグ用）
            sample_product_name = None
            for row in self.filtered_data.itertuples():
                if hasattr(row, '商品名') and row.商品名:
                    sample_product_name = str(row.商品名)
                    if len(sample_product_name) > 50:
                        print(f"保存前の商品名（全文）: {sample_product_name[:100]}...")
                    break
            
            data_list = self.filtered_data.to_dict('records')
            
            # データベースに保存
            snapshot_id = self.inventory_db.save_inventory_data(
                snapshot_name.strip(),
                data_list
            )
            
            QMessageBox.information(
                self,
                "保存完了",
                f"データを保存しました\nID: {snapshot_id}\n件数: {len(data_list)}件"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"データ保存中にエラーが発生しました:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    def load_saved_data(self, snapshot_id: int):
        """指定IDの保存データを読み込む"""
        try:
            snapshot = self.inventory_db.get_snapshot_by_id(snapshot_id)
            if not snapshot:
                QMessageBox.information(self, "情報", "保存済みデータが見つかりませんでした")
                return
            
            # データをDataFrameに変換
            data_list = snapshot.get('data', [])
            if not data_list:
                QMessageBox.warning(self, "警告", "データが空です")
                return
            
            # DataFrameとして読み込み
            self.inventory_data = pd.DataFrame(data_list)
            self.filtered_data = self.inventory_data.copy()
            
            # テーブル更新
            self.update_table()
            
            # ボタンの有効化
            self.export_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
            self.save_btn.setEnabled(True)
            self.generate_sku_btn.setEnabled(True)
            self.export_listing_btn.setEnabled(True)
            self.antique_register_btn.setEnabled(True)
            
            # データ件数更新
            self.update_data_count()
            
            QMessageBox.information(
                self,
                "読み込み完了",
                f"データを読み込みました\n件数: {len(self.filtered_data)}件"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"データ読み込み中にエラーが発生しました:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    def delete_saved_data(self, snapshot_id: int):
        """指定IDの保存済みデータを削除"""
        try:
            reply = QMessageBox.question(
                self,
                "削除確認",
                "この保存データを削除しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
            
            ok = self.inventory_db.delete_snapshot(snapshot_id)
            if ok:
                QMessageBox.information(self, "完了", "保存データを削除しました")
            else:
                QMessageBox.warning(self, "警告", "削除できませんでした")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存データの削除に失敗しました:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    def open_saved_history(self):
        """保存履歴ダイアログを開き、読み込み/削除を実行"""
        from typing import Optional
        
        dlg = SavedInventoryDialog(self.inventory_db, self)
        res = dlg.exec()
        if res == QDialog.Accepted:
            action, snapshot_id = dlg.get_result()
            if action == 'load' and snapshot_id:
                self.load_saved_data(snapshot_id)
            elif action == 'delete' and snapshot_id:
                self.delete_saved_data(snapshot_id)
        
    def run_matching(self):
        """照合処理実行（仕入管理タブから実行）"""
        try:
            # ルートサマリーウィジェットの確認
            if not self.route_summary_widget:
                QMessageBox.warning(self, "警告", "ルート機能が未初期化です。ルータブが有効か確認してください。")
                return
            
            # 現在のルートIDを取得
            route_id = self.route_summary_widget.current_route_id
            temp_saved = False
            
            # ルートIDがない場合、ルートテンプレートが読み込まれているか確認
            if not route_id:
                # ルートテンプレートのデータを確認
                route_data = self.route_summary_widget.get_route_data()
                store_visits = self.route_summary_widget.get_store_visits_data()
                
                # ルートテンプレートが読み込まれている場合、一時保存を試みる
                if route_data.get('route_code') and len(store_visits) > 0:
                    reply = QMessageBox.question(
                        self,
                        "ルートの一時保存",
                        "照合処理を実行するにはルートの保存が必要です。\nルートテンプレートの情報を一時的に保存してから照合処理を実行しますか？\n（後で削除することもできます）",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes
                    )
                    if reply == QMessageBox.Yes:
                        try:
                            # 一時保存を実行
                            self.route_summary_widget.save_data()
                            route_id = self.route_summary_widget.current_route_id
                            if route_id:
                                temp_saved = True
                                QMessageBox.information(self, "保存完了", "ルートを一時保存しました。照合処理を実行します。")
                            else:
                                QMessageBox.warning(self, "エラー", "ルートの保存に失敗しました。")
                                return
                        except Exception as e:
                            QMessageBox.warning(self, "エラー", f"ルートの保存中にエラーが発生しました:\n{str(e)}")
                            return
                    else:
                        return
                else:
                    # ルートテンプレートが読み込まれていない場合
                    QMessageBox.warning(
                        self,
                        "ルート情報なし",
                        "照合処理を実行するにはルート情報が必要です。\n"
                        "以下のいずれかを実行してください：\n"
                        "1. ルート登録タブでルートを保存する\n"
                        "2. ルートテンプレートを読み込む"
                    )
                    return
            
            # 仕入管理データの確認
            if self.inventory_data is None or len(self.inventory_data) == 0:
                # データがない場合、CSVファイル選択にフォールバック
                reply = QMessageBox.question(
                    self,
                    "データなし",
                    "仕入管理にデータがありません。\nCSVファイルを選択して処理しますか？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    # ルートサマリーウィジェットのCSVファイル選択処理を呼び出し
                    if hasattr(self.route_summary_widget, 'execute_matching_from_csv'):
                        self.route_summary_widget.execute_matching_from_csv()
                return
            
            # 時間許容誤差の設定
            tolerance, ok = QInputDialog.getInt(
                self,
                "時間許容誤差",
                "時間許容誤差（分）:",
                30, 0, 120, 1
            )
            if not ok:
                return
            
            # データをJSON形式に変換（NaN値を事前に処理）
            # テーブルから最新データを取得（手入力の変更を反映）
            self.sync_inventory_data_from_table()
            
            # NaN値を空文字列に置換してからJSON化
            clean_data = self.inventory_data.fillna('')
            purchase_data = clean_data.to_dict(orient="records")
            
            # APIクライアント確認
            if not self.api_client:
                QMessageBox.warning(self, "エラー", "APIクライアントが初期化されていません")
                return
            
            # API呼び出し
            QMessageBox.information(self, "処理中", "照合処理を実行しています...")
            result = self.api_client.inventory_match_stores_from_data(
                purchase_data=purchase_data,
                route_summary_id=route_id,
                time_tolerance_minutes=tolerance
            )
            
            # 結果を仕入管理ウィジェットに反映
            if result.get('status') == 'success':
                # 照合後のデータで仕入管理データを更新
                result_data = result.get('data', [])
                if result_data:
                    import pandas as pd
                    updated_df = pd.DataFrame(result_data)
                    
                    # 仕入管理ウィジェットのデータを更新
                    self.inventory_data = updated_df
                    self.filtered_data = updated_df.copy()
                    self.update_table()
                    self.update_data_count()
                
                # 店舗コード別の粗利を集計してルートサマリーを更新
                if hasattr(self.route_summary_widget, '_update_route_gross_profit_from_inventory'):
                    self.route_summary_widget._update_route_gross_profit_from_inventory(result_data)
                
                # ルートテンプレート読み込みエリアの表示を更新
                # データベースが更新された後、最新データを表示に反映
                self.refresh_route_template_view()
                
                # 結果表示
                stats = result.get('stats', {})
                matched_rows = stats.get('matched_rows', 0)
                total_rows = stats.get('total_rows', 0)
                
                msg = f"照合処理完了\n\n総行数: {total_rows}\nマッチした行数: {matched_rows}"
                msg += "\n\n仕入管理タブのデータが更新され、\nルートサマリーの想定粗利も自動計算されました。"
                QMessageBox.information(self, "照合処理完了", msg)
                
                # ルートサマリーの計算結果を更新
                if hasattr(self.route_summary_widget, 'update_calculation_results'):
                    self.route_summary_widget.update_calculation_results()
            else:
                QMessageBox.warning(self, "エラー", "照合処理に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"照合処理中にエラーが発生しました:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    def generate_antique_register(self):
        """古物台帳生成"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
            
        try:
            # 日付範囲の入力ダイアログ（簡易版）
            from PySide6.QtWidgets import QInputDialog
            start_date, ok1 = QInputDialog.getText(
                self, 
                "古物台帳生成", 
                "開始日を入力してください (YYYY-MM-DD):",
                text="2025-01-01"
            )
            
            if not ok1:
                return
                
            end_date, ok2 = QInputDialog.getText(
                self, 
                "古物台帳生成", 
                "終了日を入力してください (YYYY-MM-DD):",
                text="2025-01-31"
            )
            
            if not ok2:
                return
            
            # APIクライアントで古物台帳生成
            result = self.api_client.antique_register_generate(start_date, end_date)
            
            if result['status'] == 'success':
                # ファイル保存ダイアログ
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "古物台帳ファイルを保存",
                    f"antique_register_{start_date}_{end_date}.csv",
                    "CSVファイル (*.csv)"
                )
                
                if file_path:
                    # 生成されたデータをCSVファイルに保存
                    import pandas as pd
                    df = pd.DataFrame(result['items'])
                    df.to_csv(file_path, index=False, encoding='utf-8')
                    
                    QMessageBox.information(
                        self, 
                        "古物台帳生成完了", 
                        f"古物台帳生成が完了しました\n期間: {result['period']}\n件数: {result['total_items']}件\n合計金額: {result['total_value']:,}円\n保存先: {file_path}"
                    )
            else:
                QMessageBox.warning(self, "古物台帳生成失敗", "古物台帳生成に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"古物台帳生成中にエラーが発生しました:\n{str(e)}")
    
    def setup_workflow_panel(self):
        """ワークフローパネルの設定（改良版）"""
        # 作業フローグループ
        workflow_group = QGroupBox("作業フロー")
        workflow_layout = QVBoxLayout(workflow_group)
        
        # 作業フローを横展開で表示
        workflow_steps_layout = QHBoxLayout()
        
        # 各ステップのボタンを作成
        steps = [
            ("1. 仕入データ取込", "CSVファイルから仕入データを読み込み", "待機中"),
            ("2. SKU生成", "商品にSKUを自動生成・重複チェック", "待機中"),
            ("3. 出品CSV生成", "プライスター形式の出品CSVを生成", "待機中"),
            ("4. ドッキングリスト生成", "倉庫作業用ピッキングリストを生成", "待機中"),
            ("5. 古物台帳生成", "法定要件に準拠した古物台帳を生成", "待機中")
        ]
        
        self.workflow_buttons = []
        for i, (title, description, status) in enumerate(steps):
            step_widget = QWidget()
            step_layout = QVBoxLayout(step_widget)
            step_layout.setContentsMargins(5, 5, 5, 5)
            
            # ステップボタン
            step_btn = QPushButton(title)
            step_btn.setEnabled(False)
            step_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6c757d;
                    color: white;
                    border: none;
                    padding: 8px 12px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:enabled {
                    background-color: #28a745;
                }
            """)
            step_layout.addWidget(step_btn)
            
            # 説明ラベル
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("font-size: 10px; color: #666;")
            step_layout.addWidget(desc_label)
            
            # ステータスラベル
            status_label = QLabel(status)
            status_label.setStyleSheet("font-size: 10px; color: #666;")
            step_layout.addWidget(status_label)
            
            self.workflow_buttons.append((step_btn, status_label))
            workflow_steps_layout.addWidget(step_widget)
        
        workflow_layout.addLayout(workflow_steps_layout)
        
        # 進捗状況
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("進捗状況:"))
        progress_layout.addWidget(QLabel("0%"))
        progress_layout.addWidget(QLabel("0%"))
        progress_layout.addWidget(QLabel("準備完了"))
        progress_layout.addStretch()
        workflow_layout.addLayout(progress_layout)
        
        # 一括実行コントロール
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("一括実行コントロール:"))
        
        auto_exec_btn = QPushButton("全自動実行")
        auto_exec_btn.setStyleSheet("background-color: #28a745; color: white;")
        control_layout.addWidget(auto_exec_btn)
        
        pause_btn = QPushButton("一時停止")
        pause_btn.setStyleSheet("background-color: #6c757d; color: white;")
        control_layout.addWidget(pause_btn)
        
        reset_btn = QPushButton("リセット")
        reset_btn.setStyleSheet("background-color: #dc3545; color: white;")
        control_layout.addWidget(reset_btn)
        
        control_layout.addStretch()
        workflow_layout.addLayout(control_layout)
        
        # ワークフローグループをレイアウトに追加
        self.layout().addWidget(workflow_group)

    # ===== SKUテンプレ設定パネル =====
    def setup_settings_panel(self):
        self.settings_group = QGroupBox("SKUテンプレート設定")
        self.settings_group.setCheckable(False)
        self.settings_group.setVisible(False)

        lay = QGridLayout(self.settings_group)
        lay.addWidget(QLabel("テンプレート:"), 0, 0)
        self.tpl_edit = QLineEdit()
        self.tpl_edit.setPlaceholderText("{date:YYYYMMDD}-{ASIN|JAN}-{supplier}-{seq:3}-{condNum}")
        self.tpl_edit.setFixedHeight(30)
        lay.addWidget(self.tpl_edit, 0, 1, 1, 3)

        lay.addWidget(QLabel("連番開始:"), 1, 0)
        self.seq_start_spin = QSpinBox()
        self.seq_start_spin.setRange(1, 9999)
        self.seq_start_spin.setValue(1)
        self.seq_start_spin.setFixedHeight(30)
        lay.addWidget(self.seq_start_spin, 1, 1)

        lay.addWidget(QLabel("スコープ:"), 1, 2)
        self.seq_scope_combo = QComboBox()
        self.seq_scope_combo.addItems(["day"])  # まずはdayのみ
        self.seq_scope_combo.setFixedHeight(30)
        lay.addWidget(self.seq_scope_combo, 1, 3)

        self.btn_load_settings = QPushButton("読込")
        self.btn_load_settings.setFixedHeight(30)
        self.btn_load_settings.clicked.connect(self.load_sku_settings)
        lay.addWidget(self.btn_load_settings, 2, 2)

        self.btn_save_settings = QPushButton("保存")
        self.btn_save_settings.setFixedHeight(30)
        self.btn_save_settings.clicked.connect(self.save_sku_settings)
        lay.addWidget(self.btn_save_settings, 2, 3)

        # 8スロットのプルダウン式ビルダー
        token_choices = [
            "(空)",
            "日付",
            "asin",
            "商品コンディション番号",
            "商品コンディション記号",
            "発送方法",
            "仕入先コード",
            "連番",
            "任意の文字列",
        ]
        self.slot_types = []
        self.slot_values = []
        self.slot_seq_widths = []
        for i in range(8):
            row = 3 + i
            lay.addWidget(QLabel(f"{i+1}"), row, 0)
            cb = QComboBox()
            cb.addItems(token_choices)
            cb.setFixedHeight(30)
            self.slot_types.append(cb)
            lay.addWidget(cb, row, 1)

            val = QLineEdit()
            val.setPlaceholderText("(任意文字列 / 連番桁数) ※選択により使用")
            val.setFixedHeight(30)
            self.slot_values.append(val)
            lay.addWidget(val, row, 2)

            seqw = QSpinBox()
            seqw.setRange(1, 8)
            seqw.setValue(3)
            seqw.setFixedHeight(30)
            self.slot_seq_widths.append(seqw)
            lay.addWidget(seqw, row, 3)

        self.btn_build_tpl = QPushButton("テンプレ生成")
        self.btn_build_tpl.setFixedHeight(30)
        self.btn_build_tpl.clicked.connect(self.build_template_from_slots)
        lay.addWidget(self.btn_build_tpl, 11, 3)

        # 画面に追加（検索フィルタの直下）
        self.layout().addWidget(self.settings_group)

    def toggle_settings_panel(self):
        self.settings_group.setVisible(not self.settings_group.isVisible())
        if self.settings_group.isVisible():
            self.load_sku_settings()

    def load_sku_settings(self):
        try:
            s = self.api_client.inventory_get_sku_template()
            self.tpl_edit.setText(s.get("skuTemplate", ""))
            self.seq_start_spin.setValue(int(s.get("seqStart", 1)))
            scope = s.get("seqScope", "day")
            idx = self.seq_scope_combo.findText(scope)
            if idx >= 0:
                self.seq_scope_combo.setCurrentIndex(idx)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "エラー", f"設定の読込に失敗しました:\n{e}")

    def save_sku_settings(self):
        try:
            # 現在のスロット構成からテンプレを再生成して反映
            self.build_template_from_slots()
            ok = self.api_client.inventory_update_sku_template({
                "skuTemplate": self.tpl_edit.text().strip(),
                "seqScope": self.seq_scope_combo.currentText(),
                "seqStart": int(self.seq_start_spin.value())
            })
            from PySide6.QtWidgets import QMessageBox
            if ok:
                QMessageBox.information(self, "保存", "SKUテンプレート設定を保存しました")
            else:
                QMessageBox.warning(self, "保存", "SKUテンプレート設定の保存に失敗しました")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "エラー", f"設定の保存に失敗しました:\n{e}")

    def build_template_from_slots(self):
        # スロットの選択からテンプレ文字列を生成
        parts = []
        for cb, val, seqw in zip(self.slot_types, self.slot_values, self.slot_seq_widths):
            t = cb.currentText()
            if t == "(空)":
                continue
            if t == "日付":
                parts.append("{date:YYYYMMDD}")
            elif t == "asin":
                parts.append("{asin}")
            elif t == "商品コンディション番号":
                parts.append("{condNum}")
            elif t == "商品コンディション記号":
                parts.append("{condCode}")
            elif t == "発送方法":
                parts.append("{ship}")
            elif t == "仕入先コード":
                parts.append("{supplier}")
            elif t == "連番":
                width = int(seqw.value()) if seqw else 3
                parts.append(f"{{seq:{width}}}")
            elif t == "任意の文字列":
                text = val.text().strip()
                if text:
                    parts.append(f"{{custom:{text}}}")
        tpl = "-".join(parts) if parts else self.tpl_edit.text().strip()
        self.tpl_edit.setText(tpl)


class CombinedSnapshotDialog(QDialog):
    """統合スナップショットの一覧から選択して読込するダイアログ"""
    
    def __init__(self, route_snapshot_db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("統合スナップショット読込")
        self.resize(720, 420)
        self.route_snapshot_db = route_snapshot_db
        self._selected_snapshot_id = None
        
        layout = QVBoxLayout(self)
        
        # 説明ラベル
        info_label = QLabel("読み込むスナップショットを選択してください:")
        layout.addWidget(info_label)
        
        # 一覧テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["ID", "保存名", "作成日時"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)
        
        # ボタン
        btns = QDialogButtonBox()
        self.load_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("Cancel")
        btns.addButton(self.load_btn, QDialogButtonBox.AcceptRole)
        btns.addButton(self.cancel_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(btns)
        
        self.load_btn.clicked.connect(self._on_load)
        self.cancel_btn.clicked.connect(self.reject)
        
        self._reload()
    
    def _reload(self):
        """一覧を再読み込み"""
        try:
            snapshots = self.route_snapshot_db.list_snapshots()
            
            self.table.setRowCount(len(snapshots))
            for i, snap in enumerate(snapshots):
                snapshot_id = str(snap.get('id', ''))
                snapshot_name = str(snap.get('snapshot_name', ''))
                created_at = str(snap.get('created_at', ''))
                
                self.table.setItem(i, 0, QTableWidgetItem(snapshot_id))
                self.table.setItem(i, 1, QTableWidgetItem(snapshot_name))
                self.table.setItem(i, 2, QTableWidgetItem(created_at))
            
            self.table.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"一覧の読み込みに失敗しました:\n{str(e)}")
    
    def _selected_id(self):
        """選択されている行のIDを取得"""
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not sel:
            return None
        r = sel[0].row()
        item = self.table.item(r, 0)
        try:
            return int(item.text()) if item else None
        except Exception:
            return None
    
    def _on_load(self):
        """読み込みボタンクリック"""
        snapshot_id = self._selected_id()
        if snapshot_id is None:
            QMessageBox.information(self, "情報", "読み込むスナップショットを選択してください")
            return
        self._selected_snapshot_id = snapshot_id
        self.accept()
    
    def get_selected_snapshot_id(self):
        """選択されたスナップショットIDを取得"""
        return self._selected_snapshot_id


class SavedInventoryDialog(QDialog):
    """保存済み仕入データの一覧から選択して読込/削除するダイアログ"""
    
    def __init__(self, inventory_db: 'InventoryDatabase', parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存履歴")
        self.resize(720, 420)
        self.inventory_db = inventory_db
        self._result_action = None  # 'load' or 'delete'
        self._result_id = None
        
        layout = QVBoxLayout(self)
        
        # 検索行
        filt = QHBoxLayout()
        from PySide6.QtWidgets import QDateEdit
        self.chk_name = QCheckBox("名前")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("保存名で検索")
        search_btn = QPushButton("検索")
        search_btn.clicked.connect(self._reload)
        filt.addWidget(self.chk_name)
        filt.addWidget(self.name_edit)
        filt.addWidget(search_btn)
        filt.addStretch()
        layout.addLayout(filt)
        
        # 一覧テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "保存名", "件数", "作成日時"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)
        
        # ボタン
        btns = QDialogButtonBox()
        self.load_btn = QPushButton("読み込み")
        self.del_btn = QPushButton("削除")
        self.cancel_btn = QPushButton("閉じる")
        btns.addButton(self.load_btn, QDialogButtonBox.AcceptRole)
        btns.addButton(self.del_btn, QDialogButtonBox.ActionRole)
        btns.addButton(self.cancel_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(btns)
        
        self.load_btn.clicked.connect(self._on_load)
        self.del_btn.clicked.connect(self._on_delete)
        self.cancel_btn.clicked.connect(self.reject)
        
        self._reload()
    
    def _reload(self):
        """一覧を再読み込み"""
        try:
            if self.chk_name.isChecked():
                name_keyword = self.name_edit.text().strip()
                rows = self.inventory_db.search_snapshots(name_keyword)
            else:
                rows = self.inventory_db.get_all_snapshots()
            
            self.table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                rid = str(r.get('id', ''))
                name = str(r.get('snapshot_name', ''))
                count = str(r.get('item_count', ''))
                created_at = str(r.get('created_at', ''))
                
                self.table.setItem(i, 0, QTableWidgetItem(rid))
                self.table.setItem(i, 1, QTableWidgetItem(name))
                self.table.setItem(i, 2, QTableWidgetItem(count))
                self.table.setItem(i, 3, QTableWidgetItem(created_at))
            
            self.table.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"一覧の読み込みに失敗しました:\n{str(e)}")
    
    def _selected_id(self):
        """選択されている行のIDを取得"""
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not sel:
            return None
        r = sel[0].row()
        item = self.table.item(r, 0)
        try:
            return int(item.text()) if item else None
        except Exception:
            return None
    
    def _on_load(self):
        """読み込みボタンクリック"""
        rid = self._selected_id()
        if rid is None:
            QMessageBox.information(self, "情報", "読み込む行を選択してください")
            return
        self._result_action = 'load'
        self._result_id = rid
        self.accept()
    
    def _on_delete(self):
        """削除ボタンクリック"""
        rid = self._selected_id()
        if rid is None:
            QMessageBox.information(self, "情報", "削除する行を選択してください")
            return
        self._result_action = 'delete'
        self._result_id = rid
        # 削除後もダイアログは開いたまま
        self._reload()
    
    def get_result(self):
        """結果を取得"""
        return self._result_action, self._result_id
