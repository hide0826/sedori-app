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
from datetime import datetime

# プロジェクトルートをパスに追加（相対インポート用）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.store_db import StoreDatabase
from database.inventory_db import InventoryDatabase
from database.inventory_route_snapshot_db import InventoryRouteSnapshotDatabase
from database.product_db import ProductDatabase
from database.product_purchase_db import ProductPurchaseDatabase
from database.route_visit_db import RouteVisitDatabase
from database.warranty_db import WarrantyDatabase
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
        # ワークフロー状態（工程6まで完了して一時停止中かどうか）
        self.workflow_paused_after_step6 = False
        
        # ルートサマリーウィジェットへの参照（後で設定される）
        self.route_summary_widget = None
        self.antique_widget = None  # 古物台帳ウィジェットへの参照
        self.product_widget = None  # 商品DBウィジェットへの参照
        
        # データベースの初期化
        self.store_db = StoreDatabase()
        self.inventory_db = InventoryDatabase()
        self.route_snapshot_db = InventoryRouteSnapshotDatabase()
        self.product_db = ProductDatabase()
        self.product_purchase_db = ProductPurchaseDatabase()
        self.route_visit_db = RouteVisitDatabase()
        self.warranty_db = WarrantyDatabase()
        from database.condition_template_db import ConditionTemplateDatabase
        self.condition_template_db = ConditionTemplateDatabase()
        
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
    
    def set_antique_widget(self, widget):
        """古物台帳ウィジェットへの参照を設定"""
        self.antique_widget = widget
    
    def set_product_widget(self, widget):
        """商品DBウィジェットへの参照を設定"""
        self.product_widget = widget
        
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
        
        # スプリッターでエリアの高さを調整可能にする
        self.setup_splitter()
        
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
        
        # オールクリアボタン
        self.clear_btn = QPushButton("オールクリア")
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setEnabled(False)
        file_ops_layout.addWidget(self.clear_btn)
        
        # 統合保存ボタン
        self.combined_save_btn = QPushButton("統合保存")
        self.combined_save_btn.clicked.connect(self.save_combined_snapshot)
        file_ops_layout.addWidget(self.combined_save_btn)
        
        # 統合読込ボタン
        self.combined_load_btn = QPushButton("統合読込")
        self.combined_load_btn.clicked.connect(self.open_combined_snapshot_history)
        file_ops_layout.addWidget(self.combined_load_btn)
        
        # DB保存ボタン
        self.db_save_btn = QPushButton("DB保存")
        self.db_save_btn.clicked.connect(self.save_to_databases)
        self.db_save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        file_ops_layout.addWidget(self.db_save_btn)
        
        file_layout.addLayout(file_ops_layout)
        
        # アクションボタンセクション
        action_ops_layout = QHBoxLayout()
        
        # スタートボタン（一括処理）※色はワークフロー状態で _apply_start_button_style により更新
        self.start_workflow_btn = QPushButton("スタート")
        self.start_workflow_btn.clicked.connect(self.start_inventory_workflow)
        self.start_workflow_btn.setToolTip("ワークフローを開始。一時停止中は押すと再開/終了を選択できます。")
        self._apply_start_button_style("idle")
        action_ops_layout.addWidget(self.start_workflow_btn)

        # スタート時の実行モード（1工程ずつ確認するか）
        self.step_by_step_checkbox = QCheckBox("1工程ずつ確認")
        self.step_by_step_checkbox.setToolTip("チェックすると、スタート実行時に各工程ごとに実行確認ダイアログを表示します。")
        action_ops_layout.addWidget(self.step_by_step_checkbox)
        
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

        # デフォルトフォルダ設定エリア
        default_folder_layout = QHBoxLayout()
        default_folder_label = QLabel("デフォルトフォルダ:")
        default_folder_label.setStyleSheet("color: #cccccc;")
        default_folder_layout.addWidget(default_folder_label)

        from PySide6.QtWidgets import QSizePolicy as _QSizePolicyForDefaultFolder
        self.default_base_folder_edit = QLineEdit()
        self.default_base_folder_edit.setReadOnly(True)
        self.default_base_folder_edit.setPlaceholderText("未設定")
        self.default_base_folder_edit.setMinimumWidth(220)
        self.default_base_folder_edit.setSizePolicy(_QSizePolicyForDefaultFolder.Expanding, _QSizePolicyForDefaultFolder.Fixed)
        default_folder_layout.addWidget(self.default_base_folder_edit)

        self.default_base_folder_btn = QPushButton("参照…")
        self.default_base_folder_btn.clicked.connect(self.browse_default_base_folder)
        default_folder_layout.addWidget(self.default_base_folder_btn)

        file_layout.addLayout(default_folder_layout)

        # SKU設定トグルボタン
        self.toggle_settings_btn = QPushButton("SKU設定")
        self.toggle_settings_btn.clicked.connect(self.toggle_settings_panel)
        file_layout.addWidget(self.toggle_settings_btn)
        
        file_layout.addStretch()
        
        # データ件数表示
        self.data_count_label = QLabel("データ件数: 0")
        file_layout.addWidget(self.data_count_label)
        file_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        # グループボックスをメインレイアウトに追加
        self.layout().addWidget(file_group)

        # ワークフロー状態表示（ファイル操作・アクションエリアの下の行に配置）
        self.workflow_status_label = QLabel("ワークフロー: 未実行")
        self.workflow_status_label.setStyleSheet("color: #cccccc;")
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.workflow_status_label)
        status_layout.addStretch()
        self.layout().addLayout(status_layout)

        # デフォルトフォルダ設定をロード
        self._load_default_base_folder()

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

        # 自己発送SKU末尾M挿入設定（タイトルの次に配置）
        self.chk_append_m_for_self_ship = QCheckBox("自己発送末尾にMを挿入")
        self.chk_append_m_for_self_ship.setToolTip("有効にすると、発送方法が『自己発送』の商品は生成されたSKUの末尾にMを付けます")
        layout.addWidget(self.chk_append_m_for_self_ship)
        
        # 高値設定と +% は隣り合わせで配置
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
        self.chk_append_m_for_self_ship.toggled.connect(self.save_listing_settings)
        self.spin_takane_pct.valueChanged.connect(self.save_listing_settings)
        self.load_listing_settings()
        
        return container

    def _get_qsettings(self) -> QSettings:
        # 会社名/アプリ名は任意の固定値で統一
        return QSettings("HIRIO", "SedoriDesktopApp")

    def _load_default_base_folder(self):
        """仕入処理用のデフォルトフォルダを設定から読み込んで表示"""
        try:
            s = self._get_qsettings()
            base = s.value("inventory/default_base_folder", "", type=str)
            if hasattr(self, "default_base_folder_edit"):
                self.default_base_folder_edit.setText(base or "")
        except Exception as e:
            print(f"デフォルトフォルダ設定ロード失敗: {e}")

    def browse_default_base_folder(self):
        """デフォルトフォルダをユーザーに選択させて保存"""
        try:
            from pathlib import Path
            s = self._get_qsettings()
            current = s.value("inventory/default_base_folder", "", type=str)
            start_dir = current if current and Path(current).exists() else str(Path.home())
            folder = QFileDialog.getExistingDirectory(
                self,
                "仕入処理用のデフォルトフォルダを選択",
                start_dir
            )
            if folder:
                s.setValue("inventory/default_base_folder", folder)
                if hasattr(self, "default_base_folder_edit"):
                    self.default_base_folder_edit.setText(folder)
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"デフォルトフォルダの設定に失敗しました:\n{str(e)}")

    def load_listing_settings(self):
        try:
            s = self._get_qsettings()
            include_title = s.value("listing/include_title", True, type=bool)
            enable_takane = s.value("listing/enable_takane", False, type=bool)
            takane_pct = s.value("listing/takane_pct", 5, type=int)
            self.chk_include_title.setChecked(bool(include_title))
            self.chk_enable_takane.setChecked(bool(enable_takane))
            # 自己発送末尾M設定（デフォルトはFalse）
            append_m = s.value("listing/append_m_for_self_ship", False, type=bool)
            self.chk_append_m_for_self_ship.setChecked(bool(append_m))
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
            s.setValue("listing/append_m_for_self_ship", self.chk_append_m_for_self_ship.isChecked())
            s.setValue("listing/takane_pct", int(self.spin_takane_pct.value()))
        except Exception as e:
            print(f"出品設定セーブ失敗: {e}")
        
    def setup_data_table(self):
        """データテーブルエリアの設定（折りたたみ対応）"""
        self.data_group = QGroupBox("仕入データ一覧")
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
        
        # 列の定義（17列対応・指定順序）
        # DataFrame上の実際の列名は従来どおり「仕入先」を使用しつつ、
        # 表示ラベルだけ「店舗コード」に差し替える（バックエンドとの互換性維持のため）
        self.column_headers = [
            "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
            "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "想定利益率", "想定ROI", "コメント",
            "発送方法", "仕入先", "コンディション説明"
        ]
        
        self.data_table.setColumnCount(len(self.column_headers))
        # 表示用のヘッダーラベルを作成（「仕入先」→「店舗コード」に置き換え）
        display_headers = list(self.column_headers)
        try:
            idx = display_headers.index("仕入先")
            display_headers[idx] = "店舗コード"
        except ValueError:
            pass
        self.data_table.setHorizontalHeaderLabels(display_headers)
        
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
        
        # クリアボタン
        self.data_clear_btn = QPushButton("クリア")
        self.data_clear_btn.clicked.connect(self.clear_inventory_data)
        self.data_clear_btn.setEnabled(False)
        stats_layout.addWidget(self.data_clear_btn)
        
        # 行削除ボタン
        self.data_delete_row_btn = QPushButton("行削除")
        self.data_delete_row_btn.clicked.connect(self.delete_selected_inventory_rows)
        self.data_delete_row_btn.setEnabled(False)
        stats_layout.addWidget(self.data_delete_row_btn)
        
        stats_layout.addStretch()
        data_layout.addLayout(stats_layout)
        
        # コンテンツエリアのサイズポリシー（Expandingでスクロール可能に）
        self.data_group_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer_layout.addWidget(self.data_group_content, 1)  # stretch factorを1に設定
        
        def _on_toggle(checked: bool):
            self.data_group_content.setVisible(checked)
            # スプリッターを使用している場合は、スプリッターが高さを管理する
            # 折りたたみ時は最小高さに、展開時はスプリッターの設定に従う
            if hasattr(self, 'area_splitter'):
                if checked:
                    # 展開時：スプリッターの設定に従う（制限を解除）
                    self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                    self.data_group.setMaximumHeight(16777215)
                else:
                    # 折りたたみ時：最小高さに制限
                    self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    header_height = self.data_group.sizeHint().height()
                    self.data_group.setMaximumHeight(header_height)
                # スプリッターのサイズを再計算
                self.area_splitter.updateGeometry()
            else:
                # スプリッターがない場合の従来の処理（後方互換性のため）
                if checked:
                    self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                    self.data_group.setMaximumHeight(16777215)
                else:
                    self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    header_height = self.data_group.sizeHint().height()
                    self.data_group.setMaximumHeight(header_height)
            # レイアウトを再計算
            self.data_group.updateGeometry()
            if self.data_group.parent():
                self.data_group.parent().updateGeometry()
        self.data_group.toggled.connect(_on_toggle)
        self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        
        # スプリッターで管理するため、ここではレイアウトに追加しない
        # setup_splitter()で追加される

    def setup_route_template_panel(self):
        """ルートテンプレート読み込みエリア（レイアウト先行の仮実装）"""
        self.route_template_group = QGroupBox("ルート情報")
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
        # 選択変更時のイベントハンドラ
        self.route_template_table.itemSelectionChanged.connect(self.on_route_selection_changed)
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
        
        # 店舗評価の計算ロジック案内
        rating_info_layout = QHBoxLayout()
        rating_info_layout.addStretch()
        self.rating_info_button = QPushButton("※ 店舗評価の計算ロジック")
        self.rating_info_button.setCursor(Qt.PointingHandCursor)
        self.rating_info_button.setFlat(True)
        self.rating_info_button.setStyleSheet(
            "QPushButton { color: #5aa2ff; text-decoration: underline; border: none; font-size: 10pt; }"
            "QPushButton:hover { color: #8fc4ff; }"
        )
        self.rating_info_button.clicked.connect(self.show_rating_logic_popup)
        rating_info_layout.addWidget(self.rating_info_button)
        content_layout.addLayout(rating_info_layout)
        
        # ルート情報の操作ボタン
        route_ops_layout = QHBoxLayout()
        self.route_clear_btn = QPushButton("クリア")
        self.route_clear_btn.clicked.connect(self.clear_route_data)
        self.route_clear_btn.setEnabled(False)
        route_ops_layout.addWidget(self.route_clear_btn)
        
        self.route_delete_row_btn = QPushButton("行削除")
        self.route_delete_row_btn.clicked.connect(self.delete_selected_route_rows)
        self.route_delete_row_btn.setEnabled(False)
        route_ops_layout.addWidget(self.route_delete_row_btn)
        
        route_ops_layout.addStretch()
        content_layout.addLayout(route_ops_layout)
        
        # 前回読込表示を削除（取り込んだデータ一覧エリアの高さを確保）
        # self.route_template_status は削除
        
        outer_layout.addWidget(self.route_template_content)
        
        def _on_toggle(checked: bool):
            self.route_template_content.setVisible(checked)
            # スプリッターを使用している場合は、スプリッターが高さを管理する
            if hasattr(self, 'area_splitter'):
                if checked:
                    # 展開時：スプリッターの設定に従う（制限を解除）
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                    self.route_template_group.setMaximumHeight(16777215)
                else:
                    # 折りたたみ時：最小高さに制限
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    header_height = self.route_template_group.sizeHint().height()
                    self.route_template_group.setMaximumHeight(header_height)
                # スプリッターのサイズを再計算
                self.area_splitter.updateGeometry()
            else:
                # スプリッターがない場合の従来の処理（後方互換性のため）
                if checked:
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    self.route_template_group.setMaximumHeight(16777215)
                else:
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
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
        
        # スプリッターで管理するため、ここではレイアウトに追加しない
        # setup_splitter()で追加される
        self.refresh_route_template_view()

    def setup_splitter(self):
        """スプリッターでエリアの高さを調整可能にする"""
        # スプリッターを作成（縦方向）
        self.area_splitter = QSplitter(Qt.Vertical)
        
        # エリアをスプリッターに追加
        self.area_splitter.addWidget(self.data_group)
        self.area_splitter.addWidget(self.route_template_group)
        
        # 初期の高さ比率を設定（データエリア: ルートエリア = 3:1）
        self.area_splitter.setStretchFactor(0, 3)  # データエリア
        self.area_splitter.setStretchFactor(1, 1)  # ルートエリア
        
        # スプリッターの状態変更を監視して保存
        self.area_splitter.splitterMoved.connect(self.save_splitter_state)
        
        # レイアウトに追加
        self.layout().addWidget(self.area_splitter, 1)  # stretch factor = 1
        
        # ウィンドウが表示された後にスプリッターの状態を復元
        # showEventまたはタイマーで遅延復元
        from PySide6.QtCore import QTimer
        restore_timer = QTimer()
        restore_timer.setSingleShot(True)
        restore_timer.timeout.connect(self.restore_splitter_state)
        restore_timer.start(100)  # 100ms後に復元
    
    def save_splitter_state(self):
        """スプリッターの状態を保存（デバウンス処理付き）"""
        # 頻繁に呼ばれるので、少し遅延させてから保存
        if not hasattr(self, '_splitter_save_timer'):
            from PySide6.QtCore import QTimer
            self._splitter_save_timer = QTimer()
            self._splitter_save_timer.setSingleShot(True)
            def _batched_save():
                try:
                    s = self._get_qsettings()
                    # スプリッターの各エリアのサイズを保存
                    sizes = self.area_splitter.sizes()
                    if len(sizes) >= 2:
                        s.setValue("inventory/splitter_data_height", sizes[0])
                        s.setValue("inventory/splitter_route_height", sizes[1])
                except Exception as e:
                    print(f"スプリッター状態保存エラー: {e}")
            self._splitter_save_timer.timeout.connect(_batched_save)
        
        # タイマーをリセット（500ms後に保存）
        self._splitter_save_timer.stop()
        self._splitter_save_timer.start(500)
    
    def restore_splitter_state(self):
        """スプリッターの状態を復元"""
        try:
            s = self._get_qsettings()
            data_height = s.value("inventory/splitter_data_height", None, type=int)
            route_height = s.value("inventory/splitter_route_height", None, type=int)
            
            if data_height is not None and route_height is not None and data_height > 0 and route_height > 0:
                # 保存されたサイズを復元
                self.area_splitter.setSizes([data_height, route_height])
            else:
                # デフォルトの比率を設定（データエリア: ルートエリア = 3:1）
                # 実際のサイズはウィンドウサイズに応じて自動調整される
                pass
        except Exception as e:
            print(f"スプリッター状態復元エラー: {e}")
    
    def save_settings(self):
        """ウィジェットの設定を保存（スプリッターの状態も含む）"""
        # スプリッターの状態を即座に保存（タイマーを待たずに）
        if hasattr(self, 'area_splitter'):
            try:
                s = self._get_qsettings()
                sizes = self.area_splitter.sizes()
                if len(sizes) >= 2:
                    s.setValue("inventory/splitter_data_height", sizes[0])
                    s.setValue("inventory/splitter_route_height", sizes[1])
            except Exception as e:
                print(f"スプリッター状態保存エラー: {e}")

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
                            # 店舗マスタから店舗名を取得（store_code優先、互換性のため仕入れ先コードも許容）
                            store_info = self.store_db.get_store_by_code(store_code)
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
            
            # 出発時刻・帰宅時間・往路高速代・復路高速代を店舗訪問情報から除外
            # これらの情報はルート全体の情報であり、個別の店舗訪問情報として扱うべきではない
            filtered_visits = []
            exclude_store_codes = ['出発時刻', '帰宅時刻', '往路高速代', '復路高速代']
            for visit in visits:
                store_code = visit.get('store_code', '')
                # 店舗コードが除外対象でない場合のみ追加
                if store_code not in exclude_store_codes:
                    filtered_visits.append(visit)
            
            # メモ欄があれば店舗マスタの備考欄に保存・追記
            self._save_memos_to_store_master(filtered_visits)
            
            self.populate_route_template_table(filtered_visits)
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
                # ルートコードを日本語名に変換
                route_name = self.store_db.get_route_name_by_code(route_code)
                if route_name:
                    summary_parts.append(route_name)
                else:
                    # 日本語名が取得できない場合はコードをそのまま表示
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
            
            # ボタンの有効/無効を更新
            has_route_data = self.route_template_table.rowCount() > 0
            if hasattr(self, 'route_clear_btn'):
                self.route_clear_btn.setEnabled(has_route_data)
        except Exception as e:
            self.route_template_table.setRowCount(0)
            self.route_template_summary_label.setText("ルート情報: ー")
            # ボタンの無効化
            if hasattr(self, 'route_clear_btn'):
                self.route_clear_btn.setEnabled(False)
            if hasattr(self, 'route_delete_row_btn'):
                self.route_delete_row_btn.setEnabled(False)
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
                # 店舗マスタから備考を取得（store_code優先、互換性のため仕入れ先コードも許容）
                store_info = self.store_db.get_store_by_code(store_code)
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
        
        # ボタンの有効/無効を更新
        has_route_data = self.route_template_table.rowCount() > 0
        if hasattr(self, 'route_clear_btn'):
            self.route_clear_btn.setEnabled(has_route_data)

    def _save_memos_to_store_master(self, visits: List[Dict[str, Any]]):
        """ルートテンプレート読み込み時にメモ欄があれば店舗マスタの備考欄に保存・追記"""
        for visit in visits:
            store_code = visit.get('store_code', '')
            memo_text = visit.get('store_notes', '').strip()
            
            # メモ欄が空の場合はスキップ
            if not store_code or not memo_text:
                continue
            
            # 店舗マスタから現在の備考を取得（store_code優先、互換性のため仕入れ先コードも許容）
            store_info = self.store_db.get_store_by_code(store_code)
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
        
        # ルートコードを日本語名に変換
        route_name = None
        if route_code:
            route_name = self.store_db.get_route_name_by_code(route_code)
        
        # 保存名を生成（日付 + 日本語ルート名）
        snapshot_name = (route_date or "未設定").strip()
        if route_name:
            snapshot_name = f"{snapshot_name} {route_name}".strip()
        elif route_code:
            # 日本語名が取得できない場合はコードをそのまま使用
            snapshot_name = f"{snapshot_name} {route_code}".strip()
        
        if not snapshot_name or snapshot_name == "未設定":
            from datetime import datetime
            snapshot_name = datetime.now().strftime("Snapshot %Y-%m-%d %H:%M:%S")
        
        # 日付とルートが同じ場合は上書き保存、それ以外は新規保存
        self.route_snapshot_db.save_snapshot(
            snapshot_name, 
            purchase_records, 
            payload,
            route_date=route_date,
            route_code=route_code
        )
        QMessageBox.information(self, "統合保存", f"統合スナップショットを保存しました。\n{snapshot_name}")
    
    def save_to_databases(self):
        """仕入データ一覧とルート情報をそれぞれのDBに保存"""
        import json
        
        messages = []
        purchase_saved = False
        route_saved = False
        
        # 1. 仕入データ一覧を商品DBの仕入DBに保存（仕入DBタブの取り込みと同じ処理）
        try:
            # テーブルから最新データを取得（手入力商品も含む）
            df = self.get_table_data()
            if df is None or len(df) == 0:
                df = self.inventory_data
            if df is None or len(df) == 0:
                messages.append("仕入データ: データがありません")
            else:
                # DataFrameを辞書形式に変換
                df = df.fillna("")
                purchase_records = df.to_dict(orient="records")
                
                # 保証・レシート情報を付与
                purchase_records = self._augment_purchase_records_for_db(purchase_records)
                
                # 最新スナップショットから既存データを取得
                snapshots = self.product_purchase_db.list_snapshots()
                existing_all_records: List[Dict[str, Any]] = []
                if snapshots:
                    latest_snapshot = self.product_purchase_db.get_snapshot(snapshots[0]["id"])
                    if latest_snapshot:
                        existing_all_records = latest_snapshot.get("data", [])
                
                # 既存データとマージ（重複チェック）
                # 同じ仕入時間・同じASINが既に仕入DBにある場合はスキップ（更新しない）
                existing_datetime_asin_keys: set = set()
                for rec in existing_all_records:
                    k = self._get_datetime_asin_key(rec)
                    if k:
                        existing_datetime_asin_keys.add(k)
                
                # キーは SKU があれば SKU、それ以外は「仕入れ日 + ASIN/JAN + 商品名 + 店舗コード」で判定
                existing_index: Dict[str, int] = {}
                for idx, rec in enumerate(existing_all_records):
                    key = self._get_purchase_record_key(rec)
                    if key:
                        existing_index[key] = idx

                updated_count = 0
                new_count = 0
                skipped_count = 0
                
                for record in purchase_records:
                    dt_asin_key = self._get_datetime_asin_key(record)
                    if dt_asin_key and dt_asin_key in existing_datetime_asin_keys:
                        # 同じ仕入時間・同じASINが既存にある場合はスキップ（重複登録・上書き防止）
                        skipped_count += 1
                        continue
                    
                    key = self._get_purchase_record_key(record)
                    if key and key in existing_index:
                        # 既存データを更新（同じキーの既存レコードを置き換え）
                        existing_all_records[existing_index[key]] = record
                        updated_count += 1
                    else:
                        # 新規データを追加
                        existing_all_records.append(record)
                        if key:
                            existing_index[key] = len(existing_all_records) - 1
                        if dt_asin_key:
                            existing_datetime_asin_keys.add(dt_asin_key)
                        new_count += 1
                
                # スナップショットに保存
                self.product_purchase_db.save_snapshot("自動保存(仕入DB)", existing_all_records)
                purchase_saved = True
                
                # 仕入DBタブの表示を更新（参照があれば）
                if self.product_widget:
                    try:
                        # 最新スナップショットを読み込んで表示を更新
                        self.product_widget.restore_latest_purchase_snapshot()
                        self.product_widget.load_purchase_data(existing_all_records)
                    except Exception as e:
                        print(f"仕入DBタブの表示更新エラー: {e}")
                
                message = f"仕入データ: {new_count}件の新規データを追加"
                if updated_count > 0:
                    message += f"、{updated_count}件を更新"
                if skipped_count > 0:
                    message += f"、{skipped_count}件をスキップ（同一仕入時間・ASINの既存あり）"
                message += f"しました。（合計: {len(existing_all_records)}件）"
                messages.append(message)
        except Exception as e:
            messages.append(f"仕入データ保存エラー: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # 2. ルート情報をルート訪問DBに保存
        if self.route_summary_widget:
            try:
                route_data = self.route_summary_widget.get_route_data()
                visits = self.route_summary_widget.get_store_visits_data()
                
                route_date = route_data.get('route_date', '')
                route_code = route_data.get('route_code', '')
                
                if route_date and route_code and len(visits) > 0:
                    # ルートコードを日本語名に変換
                    route_name = self.store_db.get_route_name_by_code(route_code)
                    if not route_name:
                        route_name = route_code
                    
                    # 既存データを取得
                    existing_visits = self.route_visit_db.list_route_visits(
                        route_date=route_date,
                        route_code=route_code
                    )
                    
                    if existing_visits:
                        # 既存データと比較
                        # 訪問データを正規化して比較
                        existing_visits_normalized = [
                            {
                                'visit_order': v.get('visit_order'),
                                'store_code': v.get('store_code'),
                                'store_name': v.get('store_name'),
                                'store_in_time': v.get('store_in_time'),
                                'store_out_time': v.get('store_out_time'),
                                'stay_duration': v.get('stay_duration'),
                                'travel_time_from_prev': v.get('travel_time_from_prev'),
                                'store_gross_profit': v.get('store_gross_profit'),
                                'store_item_count': v.get('store_item_count'),
                                'store_rating': v.get('store_rating'),
                                'store_notes': v.get('store_notes'),
                            }
                            for v in existing_visits
                        ]
                        current_visits_normalized = [
                            {
                                'visit_order': v.get('visit_order'),
                                'store_code': v.get('store_code'),
                                'store_name': v.get('store_name'),
                                'store_in_time': v.get('store_in_time'),
                                'store_out_time': v.get('store_out_time'),
                                'stay_duration': v.get('stay_duration'),
                                'travel_time_from_prev': v.get('travel_time_from_prev'),
                                'store_gross_profit': v.get('store_gross_profit'),
                                'store_item_count': v.get('store_item_count'),
                                'store_rating': v.get('store_rating'),
                                'store_notes': v.get('store_notes'),
                            }
                            for v in visits
                        ]
                        
                        existing_json = json.dumps(existing_visits_normalized, ensure_ascii=False, sort_keys=True, default=str)
                        current_json = json.dumps(current_visits_normalized, ensure_ascii=False, sort_keys=True, default=str)
                        
                        if existing_json == current_json:
                            messages.append(f"ルート情報 ({route_date} {route_name}): 変更なし（スキップ）")
                        else:
                            # 差分がある場合は上書き保存
                            self.route_visit_db.replace_route_visits(route_date, route_code, route_name, visits)
                            route_saved = True
                            messages.append(f"ルート情報 ({route_date} {route_name}): {len(visits)}件を保存しました")
                    else:
                        # 既存データがない場合は新規保存
                        self.route_visit_db.replace_route_visits(route_date, route_code, route_name, visits)
                        route_saved = True
                        messages.append(f"ルート情報 ({route_date} {route_name}): {len(visits)}件を保存しました")
                else:
                    messages.append("ルート情報: ルートデータが不完全です（日付・ルートコード・訪問データが必要）")
            except Exception as e:
                messages.append(f"ルート情報保存エラー: {str(e)}")
                import traceback
                traceback.print_exc()
        else:
            messages.append("ルート情報: ルートテンプレートが未ロードです")
        
        # 結果メッセージを表示
        if purchase_saved or route_saved:
            QMessageBox.information(
                self,
                "DB保存完了",
                "DB保存が完了しました。\n\n" + "\n".join(messages),
                QMessageBox.Ok
            )
        else:
            QMessageBox.information(
                self,
                "DB保存",
                "DB保存を実行しました。\n\n" + "\n".join(messages),
                QMessageBox.Ok
            )
    
    def _augment_purchase_records_for_db(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """保証・レシート情報を付与（仕入DBタブの_augment_purchase_recordsと同じ処理）"""
        import re
        import unicodedata
        import calendar
        
        augmented: List[Dict[str, Any]] = []
        for record in records:
            row = dict(record)
            sku = row.get("SKU") or row.get("sku")
            
            # コメントから保証期間を算出
            comment_warranty = self._infer_warranty_from_comment_for_db(row)
            if comment_warranty:
                row["保証期間"] = comment_warranty
            
            if sku:
                try:
                    product = self.product_db.get_by_sku(sku)
                except Exception:
                    product = None
                if product:
                    if ("保証期間" not in row or not row.get("保証期間")) and product.get("warranty_until"):
                        row["保証期間"] = product.get("warranty_until")
                    if "レシートID" not in row and product.get("receipt_id") is not None:
                        row["レシートID"] = product.get("receipt_id")
                
                # 保証書情報は warranties テーブルを参照
                try:
                    warranties = self.warranty_db.list_by_sku(sku)
                except Exception:
                    warranties = []
                warranty_id = warranties[0]["id"] if warranties else None
                if "保証書ID" not in row and warranty_id is not None:
                    row["保証書ID"] = warranty_id
            augmented.append(row)
        return augmented

    def _get_purchase_record_key(self, record: Dict[str, Any]) -> Optional[str]:
        """
        仕入レコードを一意に識別するためのキーを生成する。
        - SKU があれば SKU を優先（SKU単位で一意）
        - SKU が無い場合は「仕入れ日 + ASIN or JAN + 商品名 + 店舗コード」で判定
          → これにより、同じ仕入データを何度DB保存しても更新扱いになり、重複登録を防ぐ
        """
        sku = str(record.get("SKU") or record.get("sku") or "").strip()
        if sku:
            return f"SKU:{sku}"

        # SKUが無い場合のフォールバックキー
        purchase_date = str(record.get("仕入れ日") or record.get("purchase_date") or "").strip()
        asin = str(record.get("ASIN") or record.get("asin") or "").strip()
        jan = str(record.get("JAN") or record.get("jan") or "").strip()
        asin_or_jan = asin or jan
        title = str(record.get("商品名") or record.get("title") or record.get("product_name") or "").strip()
        store_code = str(
            record.get("仕入先")
            or record.get("店舗コード")
            or record.get("store_code")
            or ""
        ).strip()

        # ほとんど情報が無い場合はキーを作らない（安全のため）
        if not (purchase_date or asin_or_jan or title or store_code):
            return None

        return f"NO-SKU:{purchase_date}|{asin_or_jan}|{store_code}|{title}"
    
    def _infer_warranty_from_comment_for_db(self, row: Dict[str, Any]) -> Optional[str]:
        """コメント欄から保証期間（月）を推定し、仕入日からの満了日を返す"""
        comment = row.get("コメント") or row.get("comment")
        if not comment:
            return None
        
        import re
        import unicodedata
        import calendar
        
        normalized = unicodedata.normalize("NFKC", str(comment))
        months = self._extract_warranty_months_for_db(normalized)
        if months is None:
            return None
        
        purchase_date_str = row.get("仕入れ日") or row.get("purchase_date")
        purchase_date = self._parse_purchase_date_for_db(purchase_date_str)
        if not purchase_date:
            return None
        
        end_date = self._add_months_for_db(purchase_date, months)
        return end_date.strftime("%Y-%m-%d")
    
    @staticmethod
    def _extract_warranty_months_for_db(text: str) -> Optional[int]:
        """コメントから保証期間（月数）を抽出"""
        import re
        patterns = [
            r'(\d+)\s*[ヶヵケかカｶ]?\s*(?:月|ヶ月|か月|カ月)\s*保証',
            r'保証\s*(\d+)\s*[ヶヵケかカｶ]?\s*(?:月|ヶ月|か月|カ月)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    continue
        
        # 特殊表現
        if "半年保証" in text or "半年の保証" in text:
            return 6
        if "1年保証" in text or "一年保証" in text:
            return 12
        
        return None
    
    @staticmethod
    def _parse_purchase_date_for_db(value: Optional[str]) -> Optional[datetime]:
        """仕入日をdatetimeに変換"""
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        
        # 一部フォーマット（年月日）を変換
        text = (
            text.replace("年", "/")
                .replace("月", "/")
                .replace("日", "")
        )
        text = text.replace("-", "/")
        text = text.replace(".", "/")
        
        # 時刻を分離
        candidates = [text]
        if " " in text:
            date_part, time_part = text.split(" ", 1)
            candidates = [
                f"{date_part} {time_part}",
                date_part
            ]
        else:
            candidates = [text]
        
        fmts = [
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
        ]
        
        for candidate in candidates:
            for fmt in fmts:
                try:
                    return datetime.strptime(candidate, fmt)
                except ValueError:
                    continue
        return None
    
    @staticmethod
    def _add_months_for_db(base_date: datetime, months: int) -> datetime:
        """月数を加算"""
        import calendar
        from datetime import datetime
        month = base_date.month - 1 + months
        year = base_date.year + month // 12
        month = month % 12 + 1
        day = min(base_date.day, calendar.monthrange(year, month)[1])
        return datetime(year, month, day)

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
                
                # コンディション説明を自動入力（コメント欄に欠品情報がある場合）
                self.inventory_data = self._auto_fill_condition_notes(self.inventory_data)
                self.filtered_data = self.inventory_data.copy()
                
                self.update_table()
                self.update_data_count()
                
                # ボタンの有効化（データが読み込まれた場合）
                if len(self.inventory_data) > 0:
                    self.export_btn.setEnabled(True)
                    self.clear_btn.setEnabled(True)
                    self.generate_sku_btn.setEnabled(True)
                    self.export_listing_btn.setEnabled(True)
                    self.antique_register_btn.setEnabled(True)
            else:
                self.inventory_data = pd.DataFrame()
                self.filtered_data = self.inventory_data
                self.update_table()
                self.update_data_count()
                
                # ボタンの無効化（データが空の場合）
                self.export_btn.setEnabled(False)
                self.clear_btn.setEnabled(False)
                self.generate_sku_btn.setEnabled(False)
                self.export_listing_btn.setEnabled(False)
                self.antique_register_btn.setEnabled(False)
            
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
                # 同じ仕入時間・同じASINのレコードからSKUを取得（重複登録防止）
                if purchase_records:
                    normalized_target_datetime = self._normalize_datetime_for_match(purchase_date)
                    for purchase_record in purchase_records:
                        record_datetime = str(purchase_record.get('仕入れ日', '') or purchase_record.get('purchase_date', '')).strip()
                        record_asin = str(purchase_record.get('ASIN', '') or purchase_record.get('asin', '')).strip()
                        record_sku = str(purchase_record.get('SKU', '') or purchase_record.get('sku', '')).strip()
                        
                        normalized_record_datetime = self._normalize_datetime_for_match(record_datetime)
                        
                        # 仕入時間（日付+時刻）+ ASINで比較
                        if normalized_record_datetime == normalized_target_datetime:
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
    
    def _normalize_datetime_for_match(self, date_str: str) -> str:
        """
        仕入れ日文字列を正規化（日付+時刻を含む場合も含める）
        同じ仕入時間・同じASINの判定に使用する。
        
        例:
        - "2025/11/8 10:22" -> "2025-11-08 10:22"
        - "2025-11-08 10:22:00" -> "2025-11-08 10:22"
        - "2025/11/8" -> "2025-11-08"
        """
        if not date_str or str(date_str).strip() == '' or str(date_str) == 'nan':
            return ''
        
        s = str(date_str).strip()
        # スラッシュをハイフンに変換
        s = s.replace('/', '-').replace('.', '-')
        
        date_part = s
        time_part = ''
        if ' ' in s:
            parts = s.split(' ', 1)
            date_part = parts[0]
            time_part = (parts[1] or '').strip()
            # 時刻を HH:MM に正規化（秒を削除）
            if time_part and ':' in time_part:
                t_parts = time_part.split(':')
                if len(t_parts) >= 2:
                    try:
                        h, m = int(t_parts[0]), int(t_parts[1])
                        time_part = f"{h:02d}:{m:02d}"
                    except (ValueError, IndexError):
                        time_part = ''
        
        # 日付部分を正規化
        d_parts = date_part.split('-')
        if len(d_parts) >= 3:
            try:
                y, m, d = int(d_parts[0]), int(d_parts[1]), int(d_parts[2])
                date_part = f"{y:04d}-{m:02d}-{d:02d}"
            except (ValueError, IndexError):
                pass
        
        if time_part:
            return f"{date_part} {time_part}"
        return date_part
    
    def _get_datetime_asin_key(self, record: Dict[str, Any]) -> Optional[str]:
        """
        仕入時間+ASINによる一意キーを生成する。
        同じ仕入時間・同じASIN = 同一レコードとみなす。
        """
        purchase_datetime = self._normalize_datetime_for_match(
            str(record.get("仕入れ日") or record.get("purchase_date") or "").strip()
        )
        asin = str(record.get("ASIN") or record.get("asin") or "").strip()
        if not purchase_datetime or not asin:
            return None
        return f"DT_ASIN:{purchase_datetime}|{asin.upper()}"
        
    def _get_default_batch_root_dir(self) -> str:
        """
        仕入処理用のフォルダ選択で使用する基準フォルダを取得
        優先順位:
        1. inventory/default_base_folder（ユーザー指定のデフォルトフォルダ）
        2. inventory/last_csv_folder（最後に読み込んだCSVのフォルダ）
        3. 固定のフォールバックパス / ホームディレクトリ
        """
        from pathlib import Path
        try:
            s = self._get_qsettings()
            base = s.value("inventory/default_base_folder", "", type=str)
            if base and Path(base).exists():
                return base
            last_folder = s.value("inventory/last_csv_folder", "", type=str)
            if last_folder and Path(last_folder).exists():
                return last_folder
        except Exception as e:
            print(f"デフォルトフォルダ取得エラー: {e}")
        # 以前のハードコードされたフォルダをフォールバックとして残す
        fallback = r"D:\せどり総合\店舗せどり仕入リスト入れ"
        if Path(fallback).exists():
            return fallback
        return str(Path.home())

    def _update_workflow_status(self, text: str, emphasize: bool = False):
        """ワークフロー状態ラベルを更新"""
        if not hasattr(self, "workflow_status_label") or self.workflow_status_label is None:
            return
        self.workflow_status_label.setText(text)
        if emphasize:
            # 強調表示（黄色っぽい色）
            self.workflow_status_label.setStyleSheet("color: #ffd54f; font-weight: bold;")
        else:
            # 通常表示
            self.workflow_status_label.setStyleSheet("color: #cccccc; font-weight: normal;")

    def _apply_start_button_style(self, state: str):
        """
        ワークフロー状態に応じてスタートボタンの色を変更
        state: "idle"=通常, "paused"=一時停止（再開可能）, "completed"=工程8まで完了
        """
        if not hasattr(self, "start_workflow_btn") or self.start_workflow_btn is None:
            return
        if state == "paused":
            # 一時停止中（緑系＝再開可能）
            self.start_workflow_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1976d2;
                }
            """)
            self.start_workflow_btn.setText("スタート（再開）")
        elif state == "completed":
            # 工程8まで完了（グレー系）
            self.start_workflow_btn.setStyleSheet("""
                QPushButton {
                    background-color: #607d8b;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #546e7a;
                }
            """)
            self.start_workflow_btn.setText("スタート")
        else:
            # idle: 通常（オレンジ）
            self.start_workflow_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ff9800;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #fb8c00;
                }
            """)
            self.start_workflow_btn.setText("スタート")

    def _stop_workflow_paused_state(self):
        """ワークフロー一時停止状態を解除し、スタートボタンを通常表示に戻す"""
        self.workflow_paused_after_step6 = False
        self._update_workflow_status("ワークフロー: 未実行")
        self._apply_start_button_style("idle")

    def _should_run_step(self, title: str, description: str) -> bool:
        """
        スタートワークフローの各工程を実行するかどうかを判定
        
        「1工程ずつ確認」がOFFのときは常にTrueを返し、そのまま進める。
        ONのときは、ユーザーに確認ダイアログを表示し、Yesのときだけ実行を続行する。
        """
        # チェックボックスが無い、または未チェックなら確認なしで進む
        if not hasattr(self, "step_by_step_checkbox") or not self.step_by_step_checkbox.isChecked():
            return True
        
        reply = QMessageBox.question(
            self,
            title,
            f"{description}\n\nこの工程を実行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        return reply == QMessageBox.Yes

    def start_inventory_workflow(self):
        """
        スタートボタンから仕入管理の一連の処理を自動実行する
        
        フロー:
        1. デフォルトフォルダを基準に仕入処理フォルダを選択
        2. 選択フォルダ内の StockList_*.csv を読み込み（CSV取込と同等）
        3. 同じフォルダ内の route_template_*.xlsx を読み込み（ルートテンプレ読込と同等）
        4. 照合処理実行
        5. SKU生成
        6. 統合保存
        7. DB保存
        8. 出品CSV生成（保存先は選択フォルダまたは既定設定）
        9. 古物台帳生成
        """
        from pathlib import Path

        # すでに工程6まで完了してコンディション説明編集待ちの場合は、再開 or ワークフロー終了を選択
        if self.workflow_paused_after_step6:
            # データが残っているか確認
            if self.filtered_data is None or len(self.filtered_data) == 0:
                QMessageBox.warning(
                    self,
                    "再開不可",
                    "仕入データが存在しないため、作業を再開できません。\n最初からワークフローを実行してください。"
                )
                self._stop_workflow_paused_state()
                return

            # 再開 / ワークフロー終了 の2択ダイアログ
            box = QMessageBox(self)
            box.setWindowTitle("スタート")
            box.setText(
                "工程6（DB保存）まで完了し、コンディション説明編集待ちの状態です。\n\n"
                "工程7から再開するか、ワークフローを終了するか選んでください。"
            )
            btn_resume = box.addButton("工程7から再開", QMessageBox.YesRole)
            btn_stop = box.addButton("ワークフロー終了", QMessageBox.NoRole)
            box.exec()
            if box.clickedButton() == btn_stop:
                self._stop_workflow_paused_state()
                QMessageBox.information(
                    self,
                    "ワークフロー終了",
                    "ワークフローを終了しました。\n再度スタートボタンで最初から実行できます。"
                )
                return

            # 出品CSV生成（保存ダイアログは従来どおり表示）
            if not self._should_run_step(
                "工程7: 出品CSV生成",
                "Amazon出品用のCSVファイルを生成します。"
            ):
                return
            self.export_listing_csv()
            
            # 古物台帳生成
            if not self._should_run_step(
                "工程8: 古物台帳生成",
                "現在の仕入データとルート情報を古物台帳タブに転送します。"
            ):
                return
            self.generate_antique_register()

            # 再開完了
            self.workflow_paused_after_step6 = False
            self._update_workflow_status("ワークフロー: 工程8まで完了")
            self._apply_start_button_style("completed")
            QMessageBox.information(self, "作業再開完了", "工程7および工程8の処理が完了しました。")
            return
        
        # 1. 仕入処理フォルダを選択（デフォルトフォルダを基準にする）
        base_dir = self._get_default_batch_root_dir()
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "仕入処理フォルダを選択（StockList_ と route_template_ を含むフォルダ）",
            base_dir
        )
        if not selected_dir:
            # キャンセル
            return
        
        folder_path = Path(selected_dir)
        
        # 選択フォルダを last_csv_folder として保存（出品CSVの初期フォルダにも利用）
        try:
            s = self._get_qsettings()
            s.setValue("inventory/last_csv_folder", str(folder_path))
        except Exception:
            pass
        
        # 2. StockList_ で始まる CSV を探して読み込み
        csv_candidates = sorted(folder_path.glob("StockList_*.csv"))
        if not csv_candidates:
            QMessageBox.warning(
                self,
                "CSVファイル未検出",
                f"選択したフォルダ内に『StockList_』で始まるCSVファイルが見つかりませんでした。\n\nフォルダ: {selected_dir}"
            )
            return
        
        # 最も新しいファイルを優先
        try:
            csv_path = max(csv_candidates, key=lambda p: p.stat().st_mtime)
        except Exception:
            csv_path = csv_candidates[0]
        
        # 工程1: CSV取込
        if not self._should_run_step(
            "工程1: CSV取込",
            f"選択フォルダ内の仕入リストCSVを読み込みます。\n対象ファイル: {csv_path.name}"
        ):
            return
        self._import_csv_from_path(str(csv_path))
        
        # 3. route_template_ で始まる xlsx/xls を探して読み込み
        if not self.route_summary_widget:
            QMessageBox.warning(
                self,
                "ルート機能未初期化",
                "ルート登録タブ（ルートサマリー）が初期化されていないため、ルートテンプレートを読み込めません。"
            )
            return
        
        route_candidates = sorted(
            list(folder_path.glob("route_template_*.xlsx")) +
            list(folder_path.glob("route_template_*.xls"))
        )
        if not route_candidates:
            QMessageBox.warning(
                self,
                "ルートテンプレート未検出",
                f"選択したフォルダ内に『route_template_』で始まるExcelファイルが見つかりませんでした。\n\nフォルダ: {selected_dir}"
            )
            return
        
        try:
            route_path = max(route_candidates, key=lambda p: p.stat().st_mtime)
        except Exception:
            route_path = route_candidates[0]
        
        # 工程2: ルートテンプレート読込
        if not self._should_run_step(
            "工程2: ルートテンプレ読込",
            f"選択フォルダ内のルートテンプレートを読み込みます。\n対象ファイル: {route_path.name}"
        ):
            return
        
        # ルートテンプレ読込と同等の処理（ダイアログを出さずに直接読み込み）
        try:
            loaded_path = self.route_summary_widget.load_template(str(route_path))
            if not loaded_path:
                QMessageBox.warning(
                    self,
                    "ルートテンプレート読込失敗",
                    "ルートテンプレートの読み込みに失敗したため、後続の処理を中止します。"
                )
                return
            # 仕入管理タブ側のルート情報エリアも更新
            self.refresh_route_template_view()
        except Exception as e:
            QMessageBox.critical(
                self,
                "ルートテンプレート読込エラー",
                f"ルートテンプレートの読み込み中にエラーが発生しました:\n{str(e)}"
            )
            return
        
        # 4. 照合処理実行
        if not self._should_run_step(
            "工程3: 照合処理実行",
            "仕入データとルート情報の照合処理を実行します。"
        ):
            return
        self.run_matching()
        
        # 照合処理で inventory_data が更新されている前提で後続処理を実行
        if self.inventory_data is None or len(self.inventory_data) == 0:
            QMessageBox.warning(
                self,
                "データなし",
                "照合処理後の仕入データが存在しないため、後続の処理を中止します。"
            )
            return
        
        # 5. SKU生成
        if not self._should_run_step(
            "工程4: SKU生成",
            "仕入データにSKUを自動生成します。"
        ):
            return
        self.generate_sku()
        
        # 6. 統合保存
        if not self._should_run_step(
            "工程5: 統合保存",
            "現在の仕入データとルート情報を統合スナップショットとして保存します。"
        ):
            return
        self.save_combined_snapshot()
        
        # 7. DB保存
        if not self._should_run_step(
            "工程6: DB保存",
            "統合された仕入データをデータベースに保存します。"
        ):
            return
        self.save_to_databases()

        # 工程6完了後、工程7に進む前にコンディション説明編集の確認（1工程ずつ確認モード時のみ）
        if hasattr(self, "step_by_step_checkbox") and self.step_by_step_checkbox.isChecked():
            reply = QMessageBox.question(
                self,
                "コンディション説明の編集",
                "工程6（DB保存）が完了しました。\n\n"
                "出品CSV生成の前に、仕入データ一覧の「コンディション説明」を編集しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # ワークフローを一時停止状態にし、ステータスとボタン色を更新
                self.workflow_paused_after_step6 = True
                self._update_workflow_status("ワークフロー: 工程6まで完了（コンディション説明編集中。スタートで工程7から再開できます）", emphasize=True)
                self._apply_start_button_style("paused")
                QMessageBox.information(
                    self,
                    "コンディション説明を編集してください",
                    "このダイアログを閉じたあとで、仕入データ一覧の「コンディション説明」列を自由に編集してください。\n\n"
                    "編集が終わったら、もう一度「スタート」ボタンを押すと、\n"
                    "工程7（出品CSV生成）と工程8（古物台帳生成）を自動で続きから実行できます。"
                )
                # ユーザーがコンディション説明を編集できるように、ここでスタートワークフローを一旦終了する
                return
        
        # 8. 出品CSV生成（保存ダイアログは従来どおり表示）
        if not self._should_run_step(
            "工程7: 出品CSV生成",
            "Amazon出品用のCSVファイルを生成します。"
        ):
            return
        self.export_listing_csv()
        
        # 9. 古物台帳生成
        if not self._should_run_step(
            "工程8: 古物台帳生成",
            "現在の仕入データとルート情報を古物台帳タブに転送します。"
        ):
            return
        self.generate_antique_register()

        # 全工程完了
        self._update_workflow_status("ワークフロー: 工程8まで完了")
        self._apply_start_button_style("completed")

    def import_csv(self):
        """CSVファイルの取込"""
        default_dir = self._get_default_batch_root_dir()
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "CSVファイルを選択",
            default_dir,
            "CSVファイル (*.csv);;すべてのファイル (*)"
        )
        
        if file_path:
            self._import_csv_from_path(file_path)

    def _import_csv_from_path(self, file_path: str):
        """指定パスのCSVファイルを読み込んで仕入データに展開する共通処理"""
        try:
            # CSVファイルの読み込み（複数エンコーディング対応）
            df = self._read_csv_with_encoding_fallback(file_path)
            
            # 選択したフォルダを保存（次回の出品CSV生成時に使用）
            try:
                from pathlib import Path
                selected_folder = str(Path(file_path).parent)
                s = self._get_qsettings()
                s.setValue("inventory/last_csv_folder", selected_folder)
            except Exception:
                pass
            
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
        
        # JANコードの.0を削除（数値として読み込まれた場合の正規化）
        if "JAN" in new_df.columns:
            def normalize_jan(value):
                """JANコードから.0を削除して文字列に変換"""
                if pd.isna(value) or value == "":
                    return ""
                # 文字列に変換
                jan_str = str(value).strip()
                # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
                if jan_str.endswith(".0"):
                    jan_str = jan_str[:-2]
                # 数字以外の文字を除去（念のため）
                jan_str = ''.join(c for c in jan_str if c.isdigit())
                return jan_str
            new_df["JAN"] = new_df["JAN"].apply(normalize_jan)
        
        # 利益率とROIを計算
        new_df = self._calculate_margin_and_roi(new_df)
        
        # コンディション説明を自動入力（コメント欄に欠品情報がある場合）
        new_df = self._auto_fill_condition_notes(new_df)
        
        return new_df
    
    def _calculate_margin_and_roi(self, df: pd.DataFrame) -> pd.DataFrame:
        """利益率とROIを計算してDataFrameに追加"""
        # 数値列を数値型に変換（エラー時はNaN）
        def safe_float(x):
            try:
                if pd.isna(x) or x == "" or str(x).strip() == "":
                    return 0.0
                # カンマ区切りを除去
                x_str = str(x).replace(",", "").strip()
                return float(x_str)
            except (ValueError, TypeError):
                return 0.0
        
        # 必要な列を数値型に変換
        purchase_price = df.get("仕入れ価格", pd.Series([0.0] * len(df))).apply(safe_float)
        planned_price = df.get("販売予定価格", pd.Series([0.0] * len(df))).apply(safe_float)
        expected_profit = df.get("見込み利益", pd.Series([0.0] * len(df))).apply(safe_float)
        
        # 利益率 = (見込み利益 / 販売予定価格) * 100
        # ゼロ除算を防ぐ
        margin = pd.Series([0.0] * len(df), dtype=float)
        for i in range(len(df)):
            if planned_price.iloc[i] > 0:
                margin.iloc[i] = (expected_profit.iloc[i] / planned_price.iloc[i]) * 100
            else:
                margin.iloc[i] = 0.0
        
        # ROI = (見込み利益 / 仕入れ価格) * 100
        # ゼロ除算を防ぐ
        roi = pd.Series([0.0] * len(df), dtype=float)
        for i in range(len(df)):
            if purchase_price.iloc[i] > 0:
                roi.iloc[i] = (expected_profit.iloc[i] / purchase_price.iloc[i]) * 100
            else:
                roi.iloc[i] = 0.0
        
        # 小数点第2位で四捨五入
        margin = margin.round(2)
        roi = roi.round(2)
        
        # DataFrameに追加
        df["想定利益率"] = margin
        df["想定ROI"] = roi
        
        return df
                
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
                    # 利益率とROIの数値フォーマット（小数点第2位まで表示）
                    elif column in ["想定利益率", "想定ROI"]:
                        try:
                            if value and str(value).replace(".", "").replace("-", "").replace(",", "").replace("nan", "").strip():
                                num_value = float(str(value).replace(",", ""))
                                item.setText(f"{num_value:.2f}")
                            else:
                                item.setText("0.00")
                        except:
                            item.setText("0.00")
                    
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
        
        # ボタンの有効/無効を更新
        has_data = self.data_table.rowCount() > 0
        if hasattr(self, 'data_clear_btn'):
            self.data_clear_btn.setEnabled(has_data)

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

    def _is_excluded_for_sku(self, row: dict) -> bool:
        """
        SKU生成時の除外条件
        
        - コメントに『除外』が含まれる行は除外
        - 発送方法が空欄の行は除外
        - FBA 以外（自己発送など）は SKU 生成対象に含める
        """
        try:
            comment = str(row.get('コメント', '') or '')
            if '除外' in comment:
                return True
            ship = str(row.get('発送方法', '') or '').strip()
            # 発送方法が空欄の行は除外
            if ship == '':
                return True
            return False
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
            
            # 行削除ボタンの有効/無効を制御
            has_selection = len(selected_items) > 0
            if hasattr(self, 'data_delete_row_btn'):
                self.data_delete_row_btn.setEnabled(has_selection)
            
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
            
            # 商品名列が見つかった場合、その列をハイライト
            if product_name_column >= 0:
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
        """データのクリア（仕入データ一覧とルート情報の両方をクリア）"""
        # 仕入データのクリア
        self.inventory_data = None
        self.filtered_data = None
        self.data_table.setRowCount(0)
        
        # ルート情報のクリア
        self.route_template_table.setRowCount(0)
        self.route_template_summary_label.setText("ルート情報: ー")
        
        # ルートサマリーウィジェットのデータもクリア（可能であれば）
        if self.route_summary_widget:
            try:
                # ルートサマリーウィジェットのデータをクリア
                if hasattr(self.route_summary_widget, 'clear_route_data'):
                    self.route_summary_widget.clear_route_data()
                elif hasattr(self.route_summary_widget, 'current_route_id'):
                    self.route_summary_widget.current_route_id = None
            except Exception as e:
                print(f"ルート情報のクリア中にエラー: {e}")
        
        # ボタンの無効化
        self.export_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.generate_sku_btn.setEnabled(False)
        self.export_listing_btn.setEnabled(False)
        self.antique_register_btn.setEnabled(False)
        
        # 表示のクリア
        self.data_count_label.setText("データ件数: 0")
        self.stats_label.setText("統計: なし")
        
        # 各エリアのボタンも無効化
        if hasattr(self, 'data_clear_btn'):
            self.data_clear_btn.setEnabled(False)
        if hasattr(self, 'data_delete_row_btn'):
            self.data_delete_row_btn.setEnabled(False)
        if hasattr(self, 'route_clear_btn'):
            self.route_clear_btn.setEnabled(False)
        if hasattr(self, 'route_delete_row_btn'):
            self.route_delete_row_btn.setEnabled(False)
    
    def clear_inventory_data(self):
        """仕入データ一覧のみをクリア"""
        reply = QMessageBox.question(
            self,
            "確認",
            "仕入データ一覧をクリアしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.inventory_data = None
            self.filtered_data = None
            self.data_table.setRowCount(0)
            
            # ボタンの無効化
            self.export_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
            self.generate_sku_btn.setEnabled(False)
            self.export_listing_btn.setEnabled(False)
            self.antique_register_btn.setEnabled(False)
            if hasattr(self, 'data_clear_btn'):
                self.data_clear_btn.setEnabled(False)
            if hasattr(self, 'data_delete_row_btn'):
                self.data_delete_row_btn.setEnabled(False)
            
            # 表示のクリア
            self.data_count_label.setText("データ件数: 0")
            self.stats_label.setText("統計: なし")
    
    def delete_selected_inventory_rows(self):
        """選択された仕入データの行を削除"""
        selected_rows = set()
        for item in self.data_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除する行を選択してください")
            return
        
        reply = QMessageBox.question(
            self,
            "確認",
            f"{len(selected_rows)}行を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 行番号を降順にソート（後ろから削除することでインデックスがずれない）
            sorted_rows = sorted(selected_rows, reverse=True)
            
            # filtered_dataから削除
            if self.filtered_data is not None:
                indices_to_drop = [self.filtered_data.index[i] for i in sorted_rows if i < len(self.filtered_data)]
                self.filtered_data = self.filtered_data.drop(indices_to_drop)
                self.filtered_data = self.filtered_data.reset_index(drop=True)
            
            # inventory_dataからも削除（該当する行を探して削除）
            if self.inventory_data is not None:
                # テーブルの行番号とinventory_dataのインデックスを対応させる
                for row_idx in sorted_rows:
                    if row_idx < len(self.filtered_data) if self.filtered_data is not None else False:
                        # filtered_dataのインデックスを使ってinventory_dataからも削除
                        if self.filtered_data is not None and row_idx < len(self.filtered_data):
                            # 実際のデータはupdate_tableで再構築されるので、ここではテーブルから削除のみ
                            pass
            
            # テーブルから行を削除
            for row_idx in sorted_rows:
                self.data_table.removeRow(row_idx)
            
            # テーブルを更新
            self.update_table()
            self.update_stats()
            
            # ボタンの有効/無効を更新
            if self.data_table.rowCount() == 0:
                if hasattr(self, 'data_clear_btn'):
                    self.data_clear_btn.setEnabled(False)
                if hasattr(self, 'data_delete_row_btn'):
                    self.data_delete_row_btn.setEnabled(False)
    
    def clear_route_data(self):
        """ルート情報のみをクリア"""
        reply = QMessageBox.question(
            self,
            "確認",
            "ルート情報をクリアしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.route_template_table.setRowCount(0)
            self.route_template_summary_label.setText("ルート情報: ー")
            
            # ルートサマリーウィジェットのデータもクリア（可能であれば）
            if self.route_summary_widget:
                try:
                    if hasattr(self.route_summary_widget, 'clear_route_data'):
                        self.route_summary_widget.clear_route_data()
                    elif hasattr(self.route_summary_widget, 'current_route_id'):
                        self.route_summary_widget.current_route_id = None
                except Exception as e:
                    print(f"ルート情報のクリア中にエラー: {e}")
            
            # ボタンの無効化
            if hasattr(self, 'route_clear_btn'):
                self.route_clear_btn.setEnabled(False)
            if hasattr(self, 'route_delete_row_btn'):
                self.route_delete_row_btn.setEnabled(False)
    
    def show_rating_logic_popup(self):
        """店舗評価の計算ロジックを表示"""
        detail_text = (
            "【店舗評価の自動計算】\n\n"
            "1. 基礎星スコア（仕入れ点数）\n"
            "   1〜2点: ★1 / 3〜4点: ★2 / 5〜6点: ★3 / 7〜9点: ★4 / 10点以上: ★5\n\n"
            "2. 粗利係数（想定粗利）\n"
            "   〜5,000円:0.8 / 5,001〜10,000円:1.0 / 10,001〜20,000円:1.2 /\n"
            "   20,001〜40,000円:1.4 / 40,001円以上:1.6\n\n"
            "3. 最終スコア\n"
            "   最終スコア = (基礎星スコア × 粗利係数) × (想定粗利 ÷ 滞在時間)\n"
            "   ※滞在時間が1分未満の場合は1分として計算します。\n\n"
            "4. 星への変換\n"
            "   〜1.5→★1 / 1.6〜2.5→★2 / 2.6〜3.5→★3 /\n"
            "   3.6〜4.5→★4 / 4.6以上→★5\n\n"
            "仕入れ点数または想定粗利が未入力の場合は★0を設定します。"
        )
        QMessageBox.information(self, "店舗評価の計算ロジック", detail_text)
    
    def delete_selected_route_rows(self):
        """選択されたルート情報の行を削除"""
        selected_rows = set()
        for item in self.route_template_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除する行を選択してください")
            return
        
        reply = QMessageBox.question(
            self,
            "確認",
            f"{len(selected_rows)}行を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 行番号を降順にソート（後ろから削除することでインデックスがずれない）
            sorted_rows = sorted(selected_rows, reverse=True)
            
            # テーブルから行を削除
            for row_idx in sorted_rows:
                self.route_template_table.removeRow(row_idx)
            
            # ルートサマリーウィジェットのデータも更新（可能であれば）
            if self.route_summary_widget:
                try:
                    # テーブルから現在のデータを取得してルートサマリーウィジェットに反映
                    visits = []
                    for i in range(self.route_template_table.rowCount()):
                        visit = {
                            'visit_order': int(self.route_template_table.item(i, 0).text()) if self.route_template_table.item(i, 0) else i + 1,
                            'store_code': self.route_template_table.item(i, 1).text() if self.route_template_table.item(i, 1) else '',
                            'store_name': self.route_template_table.item(i, 2).text() if self.route_template_table.item(i, 2) else '',
                            'in_time': self.route_template_table.item(i, 3).text() if self.route_template_table.item(i, 3) else '',
                            'out_time': self.route_template_table.item(i, 4).text() if self.route_template_table.item(i, 4) else '',
                        }
                        visits.append(visit)
                    
                    # ルートサマリーウィジェットに反映（メソッドがあれば）
                    if hasattr(self.route_summary_widget, 'update_store_visits_from_list'):
                        self.route_summary_widget.update_store_visits_from_list(visits)
                except Exception as e:
                    print(f"ルート情報の更新中にエラー: {e}")
            
            # ボタンの有効/無効を更新
            if self.route_template_table.rowCount() == 0:
                if hasattr(self, 'route_clear_btn'):
                    self.route_clear_btn.setEnabled(False)
                if hasattr(self, 'route_delete_row_btn'):
                    self.route_delete_row_btn.setEnabled(False)
    
    def on_route_selection_changed(self):
        """ルート情報テーブルの選択変更時の処理"""
        selected_items = self.route_template_table.selectedItems()
        has_selection = len(selected_items) > 0
        if hasattr(self, 'route_delete_row_btn'):
            self.route_delete_row_btn.setEnabled(has_selection)
        
    def generate_sku(self):
        """SKU生成（店舗マスタ連携対応）"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
            
        try:
            # 仕入DBに同じ仕入時間・同じASINがある場合はそこからSKUを入力（重複登録防止）
            self.match_purchase_records_from_product_db()
            
            # データを辞書形式に変換（除外商品を除く）
            all_list = self.filtered_data.to_dict('records')
            # SKU生成専用の除外条件（自己発送も含める）
            data_list = [r for r in all_list if not self._is_excluded_for_sku(r)]
            excluded_count = len(all_list) - len(data_list)
            
            # 各商品データに店舗情報を追加
            enriched_data = []
            store_not_found_warnings = []
            
            for item in data_list:
                enriched_item = item.copy()
                
                # 「仕入先」列から仕入れ先コードを取得
                supplier_code = item.get('仕入先', '').strip()
                
                if supplier_code:
                    # 店舗マスタから店舗情報を取得（store_code優先、互換性のため仕入れ先コードも許容）
                    store_info = self.store_db.get_store_by_code(supplier_code)
                    
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
                        # 必要であれば自己発送用に末尾Mを付与
                        if self.chk_append_m_for_self_ship.isChecked():
                            try:
                                ship_method = str(self.inventory_data.at[matched_index, '発送方法'] or '')
                            except Exception:
                                ship_method = ''
                            # 発送方法に「自己発送」が含まれる行だけ対象
                            if '自己発送' in ship_method:
                                if isinstance(generated_sku, str) and not generated_sku.endswith('M'):
                                    generated_sku = f"{generated_sku}M"

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
                from utils.file_naming import resolve_unique_path
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
                    # 利益率とROIの特別処理（小数点第2位まで）
                    elif column in ["想定利益率", "想定ROI"]:
                        try:
                            value_str = str(value).replace(",", "").strip()
                            if value_str == "" or value_str == "nan" or pd.isna(value):
                                row_data[column] = 0.0
                            else:
                                row_data[column] = round(float(value_str), 2)
                        except (ValueError, TypeError):
                            row_data[column] = 0.0
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
    
    def _extract_missing_info(self, comment: str) -> Optional[str]:
        """
        コメントから欠品情報を抽出・変換
        
        【付属品】以降の文言を抽出し、欠品キーワード辞書にマッチするものを変換後の文章に置き換え
        【付属品】がない場合はコメント全体をチェック
        複数の欠品情報がある場合はカンマ区切りでキーワード順に並べる
        
        Returns:
            - 辞書にマッチ（複数可）: カンマ区切りの変換後の文章
            - 辞書にないが「欠品」キーワードあり: 空文字列（見出しのみ用）
            - どちらでもない: None
        """
        if not comment or not comment.strip():
            return None
        
        comment = comment.strip()
        
        try:
            # 【付属品】以降の文言を抽出（なければコメント全体を使用）
            if "【付属品】" in comment:
                # 【付属品】以降の部分を取得
                after_attachments = comment.split("【付属品】", 1)[1].strip()
                if not after_attachments:
                    return None
            else:
                # 【付属品】がない場合はコメント全体を使用
                after_attachments = comment
            
            # 欠品キーワード辞書を読み込み
            missing_keywords = self.condition_template_db.load_missing_keywords()
            keywords_dict = missing_keywords.get('keywords', {})
            
            # マッチした変換後の文章をリストに格納（キーワード順）
            converted_list = []
            matched_keywords = []
            
            # 辞書のキーワード順にチェック（辞書の順序を保持）
            # コメント全体に対してチェック（部分一致でマッチ）
            for keyword, converted_text in keywords_dict.items():
                if keyword in after_attachments and keyword not in matched_keywords:
                    converted_list.append(converted_text)
                    matched_keywords.append(keyword)
            
            # マッチした変換後の文章がある場合
            if converted_list:
                # カンマ区切りで結合
                return ",".join(converted_list)
            
            # 辞書にないが「欠品」キーワードが含まれているかチェック
            detection_keywords = missing_keywords.get('detection_keywords', ['欠品', 'なし', '無し', '欠'])
            for keyword in detection_keywords:
                if keyword in after_attachments:
                    # 見出しのみ（内容は空）
                    return ""
            
            # どちらでもない
            return None
        except Exception:
            # エラー時はNoneを返す
            return None
    
    def _auto_fill_condition_notes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        コンディション説明を自動入力（コメント欄に欠品情報がある場合）
        
        Args:
            df: 仕入データのDataFrame
        
        Returns:
            コンディション説明が自動入力されたDataFrame
        """
        if df is None or len(df) == 0:
            return df
        
        # コンディション説明カラムが存在しない場合は作成
        if "コンディション説明" not in df.columns:
            df["コンディション説明"] = ""
        
        # 各行に対してコンディション説明を自動生成
        for idx in df.index:
            # 既にコンディション説明が入力されている場合はスキップ
            existing_note = df.at[idx, "コンディション説明"]
            if existing_note and str(existing_note).strip():
                continue
            
            # コンディションとコメントを取得
            condition_text = df.at[idx, "コンディション"] if "コンディション" in df.columns else "新品"
            comment = df.at[idx, "コメント"] if "コメント" in df.columns else ""
            
            # コンディションが空の場合はスキップ
            if not condition_text or pd.isna(condition_text) or str(condition_text).strip() == "":
                continue
            
            # コメントが空の場合はスキップ
            if not comment or pd.isna(comment) or str(comment).strip() == "":
                continue
            
            # 欠品情報が含まれているかチェック（【付属品】または欠品キーワード）
            comment_str = str(comment).strip()
            has_missing_info = False
            
            # 【付属品】が含まれているかチェック
            if "【付属品】" in comment_str:
                has_missing_info = True
            else:
                # 【付属品】がなくても、欠品キーワード辞書にマッチするかチェック
                try:
                    missing_keywords = self.condition_template_db.load_missing_keywords()
                    keywords_dict = missing_keywords.get('keywords', {})
                    detection_keywords = missing_keywords.get('detection_keywords', ['欠品', 'なし', '無し', '欠'])
                    
                    # 辞書のキーワードをチェック
                    for keyword in keywords_dict.keys():
                        if keyword in comment_str:
                            has_missing_info = True
                            break
                    
                    # 検出キーワードをチェック
                    if not has_missing_info:
                        for keyword in detection_keywords:
                            if keyword in comment_str:
                                has_missing_info = True
                                break
                except Exception:
                    pass
            
            # 欠品情報がない場合はスキップ
            if not has_missing_info:
                continue
            
            try:
                # コンディションキーを取得
                condition_key = self._get_condition_key(str(condition_text))
                
                # 欠品情報を抽出して確認
                missing_info = self._extract_missing_info(str(comment))
                
                # 欠品情報がある場合のみコンディション説明を生成
                if missing_info is not None:
                    # コンディション説明を生成（アプリ内表示用: 改行あり）
                    condition_note = self._build_condition_note(condition_key, str(comment), for_csv=False)
                    
                    # 生成されたコンディション説明を設定
                    if condition_note:
                        df.at[idx, "コンディション説明"] = condition_note
            except Exception as e:
                # エラー時はスキップ（ログ出力はしない）
                continue
        
        return df
    
    def _get_condition_key(self, condition_text: str) -> str:
        """
        コンディション文字列からキーを取得
        
        Args:
            condition_text: コンディション文字列（「新品」「ほぼ新品」「中古(ほぼ新品)」など）
        
        Returns:
            コンディションキー（'new', 'like_new', etc.）
        """
        condition_map = {
            '新品': 'new',
            'ほぼ新品': 'like_new',
            '中古(ほぼ新品)': 'like_new',
            '非常に良い': 'very_good',
            '中古(非常に良い)': 'very_good',
            '良い': 'good',
            '中古(良い)': 'good',
            '可': 'acceptable',
            '中古(可)': 'acceptable',
        }
        return condition_map.get(condition_text, 'new')  # デフォルトは新品
    
    def _build_condition_note(self, condition_key: str, comment: str, for_csv: bool = False) -> str:
        """
        conditionNoteを生成（【付属品】の後ろを欠品情報に置き換え）
        
        Args:
            condition_key: コンディションキー（'new', 'like_new', etc.）
            comment: 仕入データのコメント欄
            for_csv: CSV出力用の場合True（改行を削除）
        
        Returns:
            生成されたconditionNote（改行なし、1行）
        """
        try:
            import re
            
            # テンプレート説明文を取得
            template_text = self.condition_template_db.get_condition_description_text(condition_key)
            if not template_text:
                template_text = ""
            
            # 欠品情報を抽出
            missing_info = self._extract_missing_info(comment)
            
            # 欠品情報がある場合のみ処理
            if missing_info is not None and missing_info:
                # 【付属品】の行を見つけて、その後の部分を欠品情報に置き換え
                # パターン: 【付属品】で始まる行の【付属品】より後ろを置き換え
                lines = template_text.split('\n')
                replaced = False
                
                for i, line in enumerate(lines):
                    if line.strip().startswith('【付属品】'):
                        # 【付属品】の後ろの部分を欠品情報に置き換え
                        # 「【付属品】」の部分は残して、その後の部分を削除して欠品情報を追加
                        lines[i] = f"【付属品】{missing_info}"
                        replaced = True
                        break
                
                # 【付属品】の行が見つからない場合は、先頭に追加
                if not replaced:
                    # テンプレートの先頭に【付属品】行を追加
                    if template_text.strip():
                        template_text = f"【付属品】{missing_info}\n{template_text}"
                    else:
                        template_text = f"【付属品】{missing_info}"
                else:
                    # 置き換えが成功したので、linesを結合してtemplate_textを更新
                    template_text = '\n'.join(lines)
            else:
                # 欠品情報がない場合はテンプレートをそのまま使用
                pass
            
            # 改行を削除して1行にする
            result = template_text.strip()
            # 改行を空白に置換（連続する改行も1つの空白に）
            result = re.sub(r'\n+', ' ', result)
            # 連続する空白を1つに
            result = re.sub(r' +', ' ', result)
            result = result.strip()
            
            return result
        except Exception as e:
            # エラー時はコメントをそのまま返す（改行削除）
            result = comment if comment else ""
            import re
            result = re.sub(r'\n+', ' ', result)
            result = re.sub(r' +', ' ', result).strip()
            return result
    
    def _normalize_asin_jan(self, value):
        """
        ASIN/JANコードの科学的記数法を正規化
        
        ASIN: 10桁の数字または10文字の英数字（例: 4048965379, B0085PIHM0）
        JAN: 13桁の数字（例: 4901234567890）
        
        Args:
            value: ASINまたはJANの値（文字列、数値、科学的記数法など）
            
        Returns:
            正規化されたASIN/JANコード（文字列）
        """
        if not value or pd.isna(value):
            return ''
        
        # 文字列に変換
        str_value = str(value).strip()
        if not str_value:
            return ''
        
        # 科学的記数法のパターンをチェック（例: 4.05E+09, 4.8E+09）
        import re
        scientific_pattern = r'^(\d+\.?\d*)[eE][\+\-]?(\d+)$'
        match = re.match(scientific_pattern, str_value)
        
        if match:
            try:
                # 科学的記数法を数値に変換
                num_value = float(str_value)
                # 整数に変換
                int_value = int(num_value)
                # 文字列に変換（先頭0は保持）
                normalized = str(int_value)
                
                # 桁数でASINかJANかを判定
                # ASINは10桁、JANは13桁
                if len(normalized) == 10:
                    # 10桁の場合はASINとして扱う（そのまま返す）
                    return normalized
                elif len(normalized) == 13:
                    # 13桁の場合はJANとして扱う（そのまま返す）
                    return normalized
                elif len(normalized) < 10:
                    # 10桁未満の場合は、10桁のASINとして先頭0埋め
                    return normalized.zfill(10)
                elif len(normalized) < 13:
                    # 10桁以上13桁未満の場合は、13桁のJANとして先頭0埋め
                    return normalized.zfill(13)
                else:
                    # 13桁を超える場合はそのまま返す
                    return normalized
            except (ValueError, OverflowError):
                # 変換に失敗した場合は元の値を返す
                return str_value
        
        # 科学的記数法でない場合は、そのまま返す（ただし文字列として）
        return str_value
    
    def export_listing_csv(self):
        """出品CSV生成（conditionNote統合版）"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
            
        try:
            # データを辞書形式に変換
            data_list = self.filtered_data.to_dict('records')
            # 除外商品を除く
            included_list = [r for r in data_list if not self._is_excluded_row(r)]
            
            # ステータスで除外（ready以外のステータスを除外）
            status_excluded_count = 0
            status_included_list = []
            for r in included_list:
                status = str(r.get('ステータス') or r.get('status') or 'ready').lower()
                if status == 'ready':
                    status_included_list.append(r)
                else:
                    status_excluded_count += 1
            
            included_list = status_included_list
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

                # コンディション文字列を取得（そのままcondition列に出力）
                condition_text = row.get('コンディション', '新品')

                # 仕入データ一覧の「コンディション説明」カラムの内容をそのまま使用
                # ※ユーザーが画面で確認している文章をそのままCSVに出したい要件
                import re
                existing_condition_note = row.get('コンディション説明', '')
                condition_note = str(existing_condition_note or "").strip()
                # 改行はCSV上では1行にしたいので空白に変換
                if condition_note:
                    condition_note = re.sub(r'\r\n|\r|\n', ' ', condition_note)
                    # 連続する空白を1つに
                    condition_note = re.sub(r' +', ' ', condition_note).strip()
                
                # ASIN/JANコードの科学的記数法を正規化
                asin_value = self._normalize_asin_jan(row.get('ASIN', ''))
                jan_value = self._normalize_asin_jan(row.get('JAN', ''))
                
                mapped_row = {
                    'sku': row.get('SKU', ''),
                    'asin': asin_value,
                    'jan': jan_value,
                    'product_name': product_name_val,
                    'quantity': row.get('仕入れ個数', 1),
                    'plannedPrice': row.get('販売予定価格', 0),
                    'purchasePrice': row.get('仕入れ価格', 0),
                    'breakEven': row.get('損益分岐点', 0),
                    'expectedMargin': row.get('想定利益率', 0.0),
                    'expectedROI': row.get('想定ROI', 0.0),
                    'takane': takane_val,
                    'condition': condition_text,
                    'conditionNote': condition_note if condition_note else '',  # 空文字列を明示的に設定
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

                # 保存先フォルダを取得（CSV取込時に選択したフォルダ、なければデフォルト）
                from pathlib import Path
                from utils.file_naming import resolve_unique_path
                
                default_dir = None
                try:
                    s = self._get_qsettings()
                    saved_folder = s.value("inventory/last_csv_folder", None, type=str)
                    if saved_folder and Path(saved_folder).exists():
                        default_dir = saved_folder
                except Exception:
                    pass
                
                # デフォルトフォルダが設定されていない場合は、仕入処理用の基準フォルダを使用
                if default_dir is None:
                    default_dir = self._get_default_batch_root_dir()
                
                # ファイル保存ダイアログを表示
                default_path = str(Path(default_dir) / default_name)
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "出品CSVファイルを保存",
                    default_path,
                    "CSVファイル (*.csv)"
                )
                
                if file_path:
                    target = resolve_unique_path(Path(file_path))
                    csv_content = result['csv_content']
                    with open(str(target), 'wb') as f:
                        f.write(csv_content)
                    
                    # 選択したフォルダを保存（次回の初期フォルダとして使用）
                    try:
                        selected_folder = str(Path(file_path).parent)
                        s = self._get_qsettings()
                        s.setValue("inventory/last_csv_folder", selected_folder)
                    except Exception:
                        pass
                    
                    QMessageBox.information(
                        self,
                        "出品CSV生成完了",
                        f"出品CSV生成が完了しました\n出力数: {result['exported_count']}件 (除外 {excluded_count}件)\n保存先: {str(target)}"
                    )
            else:
                QMessageBox.warning(self, "出品CSV生成失敗", "出品CSV生成に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"出品CSV生成中にエラーが発生しました:\n{str(e)}")
    
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
        """古物台帳生成：仕入データ＋ルート情報を古物台帳タブへ転送"""
        if self.filtered_data is None or len(self.filtered_data) == 0:
            QMessageBox.warning(self, "エラー", "データがありません。先に仕入データを取り込んでください。")
            return
        
        # 古物台帳ウィジェットの参照確認
        if not self.antique_widget:
            QMessageBox.warning(
                self, 
                "エラー", 
                "古物台帳タブが初期化されていません。\nアプリケーションを再起動してください。"
            )
            return
        
        try:
            # 仕入データを辞書形式に変換
            data_list = self.filtered_data.to_dict('records')
            
            # ルート情報を取得（あれば）
            route_info = None
            if self.route_summary_widget:
                try:
                    route_data = self.route_summary_widget.get_route_data()
                    store_visits = self.route_summary_widget.get_store_visits_data()
                    if route_data and len(store_visits) > 0:
                        route_info = {
                            'route': route_data,
                            'visits': store_visits
                        }
                except Exception:
                    # ルート情報の取得に失敗しても処理は継続
                    pass
            
            # 古物台帳タブにデータを転送
            self.antique_widget.import_inventory_data(data_list, route_info)
            
            # 古物台帳タブに切り替え
            # 親ウィジェット（MainWindow）のタブウィジェットを取得
            parent = self.parent()
            while parent:
                if hasattr(parent, 'tab_widget'):
                    # MainWindowのtab_widgetを取得
                    tab_widget = parent.tab_widget
                    # 古物台帳タブのインデックスを探す
                    for i in range(tab_widget.count()):
                        if tab_widget.widget(i) == self.antique_widget:
                            tab_widget.setCurrentIndex(i)
                            break
                    break
                parent = parent.parent()
            
            # ユーザーに案内メッセージを表示
            QMessageBox.information(
                self,
                "古物台帳タブへ転送完了",
                f"仕入データ {len(data_list)} 件を古物台帳タブへ転送しました。\n"
                "古物台帳タブで内容を確認・編集してから、台帳登録・出力を行ってください。"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"古物台帳タブへのデータ転送中にエラーが発生しました:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
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
            "仕入れ価格",
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
            elif t == "仕入れ価格":
                # 仕入れ価格（purchase_price）をそのまま数値文字列として使用
                parts.append("{purchasePrice}")
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


