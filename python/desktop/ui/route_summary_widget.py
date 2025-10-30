#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルートサマリー入力ウィジェット

ルートサマリーの入力・編集機能
- テンプレートファイルの読み込み
- ルート情報の入力・編集
- 店舗別情報の入力・編集
- 照合処理・店舗コード自動挿入
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QMessageBox, QFileDialog, QDateTimeEdit, QLineEdit,
    QTextEdit, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QDialog, QFormLayout, QDialogButtonBox, QTabWidget, QStyledItemDelegate, QStyle
)
from ui.star_rating_widget import StarRatingWidget
from PySide6.QtCore import Qt, QDateTime, QTime, Signal
from PySide6.QtGui import QColor, QShortcut, QKeySequence
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import sys
import os
from datetime import time as dt_time
import openpyxl

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.route_db import RouteDatabase
from database.store_db import StoreDatabase

# サービス・ユーティリティのインポート（相対パス）
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from services.route_matching_service import RouteMatchingService
except ImportError:
    RouteMatchingService = None  # オプション機能として扱う

try:
    from services.calculation_service import CalculationService
except ImportError:
    CalculationService = None

try:
    from utils.template_generator import TemplateGenerator
except ImportError:
    TemplateGenerator = None


class RouteSummaryWidget(QWidget):
    """ルートサマリー入力ウィジェット"""
    
    data_saved = Signal(int)  # データ保存完了
    
    def __init__(self):
        super().__init__()
        self.route_db = RouteDatabase()
        self.store_db = StoreDatabase()
        self.matching_service = RouteMatchingService() if RouteMatchingService else None
        self.calc_service = CalculationService() if CalculationService else None
        
        self.current_route_id = None
        self.route_data = {}
        self.store_visits = []
        
        # Undo/Redoスタック
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo_history = 50  # 最大履歴数
        
        self.setup_ui()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：操作ボタン
        self.setup_action_buttons(layout)
        
        # 中央：タブ（ルート情報・店舗訪問詳細）
        self.setup_tabs(layout)
        
        # 下部：計算結果表示
        self.setup_calculation_results(layout)
    
    def setup_action_buttons(self, parent_layout):
        """操作ボタンの設定"""
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        
        # テンプレート生成ボタン
        template_btn = QPushButton("テンプレート生成")
        template_btn.clicked.connect(self.generate_template)
        template_btn.setStyleSheet("background-color: #28a745; color: white;")
        button_layout.addWidget(template_btn)
        
        # テンプレート読み込みボタン
        load_template_btn = QPushButton("テンプレート読み込み")
        load_template_btn.clicked.connect(self.load_template)
        button_layout.addWidget(load_template_btn)
        
        # 照合処理ボタン
        matching_btn = QPushButton("照合処理実行")
        matching_btn.clicked.connect(self.run_matching)
        matching_btn.setStyleSheet("background-color: #007bff; color: white;")
        button_layout.addWidget(matching_btn)
        
        # 店舗自動追加ボタン
        auto_add_btn = QPushButton("選択ルートの店舗を自動追加")
        auto_add_btn.clicked.connect(self.auto_add_stores)
        auto_add_btn.setStyleSheet("background-color: #17a2b8; color: white;")
        button_layout.addWidget(auto_add_btn)
        
        # 保存ボタン
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(lambda: getattr(self, 'save_data', lambda: None)())
        save_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        button_layout.addWidget(save_btn)
        
        # 新規作成ボタン
        new_btn = QPushButton("新規作成")
        new_btn.clicked.connect(lambda: getattr(self, 'new_route', lambda: None)())
        button_layout.addWidget(new_btn)
        
        button_layout.addStretch()
        
        parent_layout.addWidget(button_group)
    
    def setup_tabs(self, parent_layout):
        """タブの設定（統合版）"""
        # 単一のウィジェットに統合
        unified_widget = self.create_unified_widget()
        parent_layout.addWidget(unified_widget)
    
    def create_unified_widget(self) -> QWidget:
        """ルート情報と店舗訪問詳細を統合したウィジェット"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # 上部：ルート情報セクション（サイズを小さく設定）
        route_group = QGroupBox("ルート情報")
        route_group.setMaximumHeight(300)  # 最大高さを制限
        route_layout = QFormLayout(route_group)
        route_layout.setSpacing(8)  # スペーシングを詰める
        
        # ルート日付
        self.route_date_edit = QDateTimeEdit()
        self.route_date_edit.setCalendarPopup(True)
        self.route_date_edit.setDateTime(QDateTime.currentDateTime())
        self.route_date_edit.setDisplayFormat("yyyy-MM-dd")
        route_layout.addRow("ルート日付:", self.route_date_edit)
        
        # ルートコード（プルダウン）
        self.route_code_combo = QComboBox()
        self.route_code_combo.setEditable(True)
        self.route_code_combo.currentTextChanged.connect(self.on_route_code_changed)
        route_layout.addRow("ルートコード:", self.route_code_combo)
        self.update_route_codes()
        
        # 出発時間（自由入力のテキスト: HH:MM）
        self.departure_time_edit = QLineEdit()
        self.departure_time_edit.setPlaceholderText("HH:MM")
        self.departure_time_edit.setText(QTime.currentTime().toString('HH:mm'))
        route_layout.addRow("出発時間:", self.departure_time_edit)
        
        # 帰宅時間（自由入力のテキスト: HH:MM）
        self.return_time_edit = QLineEdit()
        self.return_time_edit.setPlaceholderText("HH:MM")
        self.return_time_edit.setText(QTime.currentTime().toString('HH:mm'))
        route_layout.addRow("帰宅時間:", self.return_time_edit)
        
        # 経費（駐車場代・食費・その他を削除）
        cost_layout = QHBoxLayout()
        self.toll_fee_outbound_spin = QDoubleSpinBox()
        self.toll_fee_outbound_spin.setMaximum(999999)
        self.toll_fee_outbound_spin.setSuffix(" 円")
        self.toll_fee_outbound_spin.setDecimals(0)  # 小数不要
        cost_layout.addWidget(QLabel("往路高速代:"))
        cost_layout.addWidget(self.toll_fee_outbound_spin)
        
        self.toll_fee_return_spin = QDoubleSpinBox()
        self.toll_fee_return_spin.setMaximum(999999)
        self.toll_fee_return_spin.setSuffix(" 円")
        self.toll_fee_return_spin.setDecimals(0)  # 小数不要
        cost_layout.addWidget(QLabel("復路高速代:"))
        cost_layout.addWidget(self.toll_fee_return_spin)
        route_layout.addRow("経費:", cost_layout)
        
        # 備考
        self.remarks_edit = QTextEdit()
        self.remarks_edit.setMaximumHeight(50)
        route_layout.addRow("備考:", self.remarks_edit)
        
        layout.addWidget(route_group, 0)  # stretch=0で最小サイズに
        
        # 下部：店舗訪問詳細セクション（残りのスペースを全て使用）
        visits_group = QGroupBox("店舗訪問詳細")
        visits_layout = QVBoxLayout(visits_group)
        
        # テーブル
        self.store_visits_table = QTableWidget()
        self.store_visits_table.setAlternatingRowColors(True)
        # 行ドラッグ＆ドロップに必要な行単位選択＋単一選択
        self.store_visits_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.store_visits_table.setSelectionMode(QTableWidget.SingleSelection)
        self.store_visits_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        
        # ドラッグ＆ドロップを有効化（行間に挿入する設定）
        self.store_visits_table.setDragEnabled(True)
        self.store_visits_table.setAcceptDrops(True)
        self.store_visits_table.setDropIndicatorShown(True)
        self.store_visits_table.setDragDropMode(QTableWidget.InternalMove)
        self.store_visits_table.setDragDropOverwriteMode(False)
        self.store_visits_table.setDefaultDropAction(Qt.MoveAction)
        
        headers = [
            "訪問順序", "店舗コード", "店舗名", "店舗IN時間", "店舗OUT時間",
            "店舗滞在時間", "移動時間（分）", "想定粗利", "仕入れ点数",
            "店舗評価", "店舗メモ"
        ]
        self.store_visits_table.setColumnCount(len(headers))
        self.store_visits_table.setHorizontalHeaderLabels(headers)
        
        header = self.store_visits_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        # 店舗名列をコンテンツに合わせて自動調整
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # 店舗名列（インデックス2）
        
        # デフォルトの行高を調整（星評価が綺麗に収まるように）
        self.store_visits_table.verticalHeader().setDefaultSectionSize(24)
        
        # 訪問順序の変更を監視
        self.store_visits_table.model().rowsMoved.connect(self.on_rows_moved)
        
        # データ変更を監視してUndoスタックに保存
        self.store_visits_table.itemChanged.connect(self.on_table_item_changed)
        
        # ショートカットキーの設定
        self.setup_shortcuts()
        
        # メモ列のフォーカス・選択の強調を最小化（実質非表示）
        class MinimalFocusDelegate(QStyledItemDelegate):
            def paint(self, painter, option, index):
                if option.state & QStyle.State_HasFocus:
                    option.state &= ~QStyle.State_HasFocus
                if option.state & QStyle.State_Selected:
                    option.state &= ~QStyle.State_Selected
                super().paint(painter, option, index)
            
            def createEditor(self, parent, option, index):
                # メモ入力用のエディタ（枠線なし・背景そのまま）
                from PySide6.QtWidgets import QLineEdit
                editor = QLineEdit(parent)
                editor.setFrame(False)
                # 入力中の視認性を上げるため、セル内に小さな編集ボックス風の装飾を適用
                # 背景は不透明にして下地テキストが透けないようにする（ゴースト文字対策）
                editor.setStyleSheet(
                    "QLineEdit{"
                    "background-color: #2b2b2b;"
                    "color: #ffffff;"
                    "border: 1px solid #5aa2ff;"
                    "border-radius: 3px;"
                    "padding: 2px 6px;"
                    "}"
                )
                try:
                    editor.setAutoFillBackground(True)
                except Exception:
                    pass
                try:
                    editor.setTextMargins(4, 0, 4, 0)
                except Exception:
                    pass
                return editor

        self.store_visits_table.setItemDelegateForColumn(10, MinimalFocusDelegate(self.store_visits_table))

        # 選択時の可視性を上げつつ、強すぎないハイライトに調整
        self.store_visits_table.setStyleSheet(
            "QTableView::item:focus{outline: none;}"
            "QTableView::item:selected{background-color: rgba(90,162,255,0.18); color: #ffffff; border: none;}"
            "QTableView::item{border: none;}"
        )

        # ドラッグ＆ドロップのため選択は有効（単一行）

        visits_layout.addWidget(self.store_visits_table)
        
        # 行追加・削除・全クリア・Undo/Redoボタン
        button_layout = QHBoxLayout()
        # 店舗マスタから追加ボタン
        add_from_master_btn = QPushButton("店舗追加（店舗マスタから）")
        add_from_master_btn.clicked.connect(self.add_store_from_master)
        button_layout.addWidget(add_from_master_btn)
        add_row_btn = QPushButton("行追加")
        add_row_btn.clicked.connect(lambda: getattr(self, 'add_store_visit_row', lambda: None)())
        button_layout.addWidget(add_row_btn)
        
        delete_row_btn = QPushButton("行削除")
        delete_row_btn.clicked.connect(lambda: getattr(self, 'delete_store_visit_row', lambda: None)())
        button_layout.addWidget(delete_row_btn)
        
        clear_all_btn = QPushButton("全行クリア")
        clear_all_btn.clicked.connect(lambda: getattr(self, 'clear_all_rows', lambda: None)())
        clear_all_btn.setStyleSheet("background-color: #dc3545; color: white;")
        button_layout.addWidget(clear_all_btn)
        
        button_layout.addStretch()
        
        # Undo/Redoボタン
        undo_btn = QPushButton("元に戻す (Ctrl+Z)")
        undo_btn.clicked.connect(self.undo_action)
        undo_btn.setStyleSheet("background-color: #6c757d; color: white;")
        button_layout.addWidget(undo_btn)
        
        redo_btn = QPushButton("やり直す (Ctrl+Y)")
        redo_btn.clicked.connect(self.redo_action)
        redo_btn.setStyleSheet("background-color: #6c757d; color: white;")
        button_layout.addWidget(redo_btn)
        
        visits_layout.addLayout(button_layout)
        layout.addWidget(visits_group, 1)  # stretch=1で残りのスペースを全て使用
        
        return widget

    def add_store_from_master(self):
        """店舗マスタ一覧から選択して店舗を追加"""
        try:
            dialog = StoreSelectDialog(self.store_db, self)
            if dialog.exec() == QDialog.Accepted:
                selected = dialog.get_selected_stores()
                if not selected:
                    return
                # 変更前の状態保存
                self.save_table_state()
                base_rows = self.store_visits_table.rowCount()
                for i, store in enumerate(selected):
                    row = base_rows + i
                    self.store_visits_table.insertRow(row)
                    order_item = QTableWidgetItem(str(row + 1))
                    order_item.setFlags(order_item.flags() & ~Qt.ItemIsEditable)
                    self.store_visits_table.setItem(row, 0, order_item)
                    self.store_visits_table.setItem(row, 1, QTableWidgetItem(store.get('supplier_code', '')))
                    self.store_visits_table.setItem(row, 2, QTableWidgetItem(store.get('store_name', '')))
                    # 星評価初期化
                    star_widget = StarRatingWidget(self.store_visits_table, rating=0, star_size=14)
                    star_widget.rating_changed.connect(lambda rating, r=row: self.on_star_rating_changed(r, rating))
                    self.store_visits_table.setCellWidget(row, 9, star_widget)
                self.update_visit_order()
                self.save_store_order()
                self.recalc_travel_times()
                self.save_table_state()
                # 計算結果更新（存在しない環境でも落ちないように）
                getattr(self, 'update_calculation_results', lambda: None)()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"店舗追加中にエラーが発生しました:\n{str(e)}")
    
    def create_route_info_widget(self) -> QWidget:
        """ルート情報入力ウィジェットの作成"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # ルート日付
        self.route_date_edit = QDateTimeEdit()
        self.route_date_edit.setCalendarPopup(True)
        self.route_date_edit.setDateTime(QDateTime.currentDateTime())
        self.route_date_edit.setDisplayFormat("yyyy-MM-dd")
        layout.addRow("ルート日付:", self.route_date_edit)
        
        # ルートコード（プルダウン）
        self.route_code_combo = QComboBox()
        self.route_code_combo.setEditable(True)  # 手動入力も可能
        self.route_code_combo.currentTextChanged.connect(self.on_route_code_changed)
        layout.addRow("ルートコード:", self.route_code_combo)
        
        # ルートコード一覧を更新
        self.update_route_codes()
        
        # 出発時間（自由入力のテキスト: HH:MM）
        self.departure_time_edit = QLineEdit()
        self.departure_time_edit.setPlaceholderText("HH:MM")
        self.departure_time_edit.setText(QTime.currentTime().toString('HH:mm'))
        layout.addRow("出発時間:", self.departure_time_edit)
        
        # 帰宅時間（自由入力のテキスト: HH:MM）
        self.return_time_edit = QLineEdit()
        self.return_time_edit.setPlaceholderText("HH:MM")
        self.return_time_edit.setText(QTime.currentTime().toString('HH:mm'))
        layout.addRow("帰宅時間:", self.return_time_edit)
        
        # 経費
        cost_layout = QHBoxLayout()
        self.toll_fee_outbound_spin = QDoubleSpinBox()
        self.toll_fee_outbound_spin.setMaximum(999999)
        self.toll_fee_outbound_spin.setSuffix(" 円")
        cost_layout.addWidget(QLabel("往路高速代:"))
        cost_layout.addWidget(self.toll_fee_outbound_spin)
        
        self.toll_fee_return_spin = QDoubleSpinBox()
        self.toll_fee_return_spin.setMaximum(999999)
        self.toll_fee_return_spin.setSuffix(" 円")
        cost_layout.addWidget(QLabel("復路高速代:"))
        cost_layout.addWidget(self.toll_fee_return_spin)
        
        self.parking_fee_spin = QDoubleSpinBox()
        self.parking_fee_spin.setMaximum(999999)
        self.parking_fee_spin.setSuffix(" 円")
        cost_layout.addWidget(QLabel("駐車場代:"))
        cost_layout.addWidget(self.parking_fee_spin)
        layout.addRow("経費:", cost_layout)
        
        expense_layout = QHBoxLayout()
        self.meal_cost_spin = QDoubleSpinBox()
        self.meal_cost_spin.setMaximum(999999)
        self.meal_cost_spin.setSuffix(" 円")
        expense_layout.addWidget(QLabel("食費:"))
        expense_layout.addWidget(self.meal_cost_spin)
        
        self.other_expenses_spin = QDoubleSpinBox()
        self.other_expenses_spin.setMaximum(999999)
        self.other_expenses_spin.setSuffix(" 円")
        expense_layout.addWidget(QLabel("その他:"))
        expense_layout.addWidget(self.other_expenses_spin)
        layout.addRow("", expense_layout)
        
        # 備考
        self.remarks_edit = QTextEdit()
        self.remarks_edit.setMaximumHeight(60)
        layout.addRow("備考:", self.remarks_edit)
        
        return widget
    
    def create_store_visits_widget(self) -> QWidget:
        """店舗訪問詳細テーブルウィジェットの作成"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # テーブル
        self.store_visits_table = QTableWidget()
        self.store_visits_table.setAlternatingRowColors(True)
        self.store_visits_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.store_visits_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        
        # ドラッグ＆ドロップを有効化（行間に挿入する設定）
        self.store_visits_table.setDragEnabled(True)
        self.store_visits_table.setAcceptDrops(True)
        self.store_visits_table.setDropIndicatorShown(True)
        self.store_visits_table.setDragDropMode(QTableWidget.InternalMove)
        self.store_visits_table.setDragDropOverwriteMode(False)
        self.store_visits_table.setDefaultDropAction(Qt.MoveAction)
        
        headers = [
            "訪問順序", "店舗コード", "店舗名", "店舗IN時間", "店舗OUT時間",
            "店舗滞在時間", "移動時間（分）", "想定粗利", "仕入れ点数",
            "店舗評価", "店舗メモ"
        ]
        self.store_visits_table.setColumnCount(len(headers))
        self.store_visits_table.setHorizontalHeaderLabels(headers)
        
        header = self.store_visits_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        # 店舗名列をコンテンツに合わせて自動調整
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # 店舗名列（インデックス2）
        
        # デフォルトの行高を調整（星評価が綺麗に収まるように）
        self.store_visits_table.verticalHeader().setDefaultSectionSize(24)
        
        # 訪問順序の変更を監視
        self.store_visits_table.model().rowsMoved.connect(self.on_rows_moved)
        
        # データ変更を監視してUndoスタックに保存
        self.store_visits_table.itemChanged.connect(self.on_table_item_changed)
        
        # ショートカットキーの設定
        self.setup_shortcuts()
        
        layout.addWidget(self.store_visits_table)
        
        # 行追加・削除・全クリア・Undo/Redoボタン
        button_layout = QHBoxLayout()
        add_row_btn = QPushButton("行追加")
        add_row_btn.clicked.connect(lambda: getattr(self, 'add_store_visit_row', lambda: None)())
        button_layout.addWidget(add_row_btn)
        
        delete_row_btn = QPushButton("行削除")
        delete_row_btn.clicked.connect(lambda: getattr(self, 'delete_store_visit_row', lambda: None)())
        button_layout.addWidget(delete_row_btn)
        
        clear_all_btn = QPushButton("全行クリア")
        clear_all_btn.clicked.connect(lambda: getattr(self, 'clear_all_rows', lambda: None)())
        clear_all_btn.setStyleSheet("background-color: #dc3545; color: white;")
        button_layout.addWidget(clear_all_btn)
        
        button_layout.addStretch()
        
        # Undo/Redoボタン
        undo_btn = QPushButton("元に戻す (Ctrl+Z)")
        undo_btn.clicked.connect(self.undo_action)
        undo_btn.setStyleSheet("background-color: #6c757d; color: white;")
        button_layout.addWidget(undo_btn)
        
        redo_btn = QPushButton("やり直す (Ctrl+Y)")
        redo_btn.clicked.connect(self.redo_action)
        redo_btn.setStyleSheet("background-color: #6c757d; color: white;")
        button_layout.addWidget(redo_btn)
        
        layout.addLayout(button_layout)
        
        return widget
    
    def setup_calculation_results(self, parent_layout):
        """計算結果表示の設定"""
        result_group = QGroupBox("計算結果")
        result_layout = QVBoxLayout(result_group)
        
        self.calculation_label = QLabel("計算結果: データ未入力")
        result_layout.addWidget(self.calculation_label)
        
        parent_layout.addWidget(result_group)
    
    def update_route_codes(self):
        """ルートコード一覧を更新"""
        try:
            # 既存のルート名を取得
            route_names = self.store_db.get_route_names()
            
            # コンボボックスをクリア
            self.route_code_combo.clear()
            
            # ルート名を追加
            for route_name in route_names:
                self.route_code_combo.addItem(route_name)
            
            # 空の選択肢も追加（手動入力用）
            if not self.route_code_combo.findText("") >= 0:
                self.route_code_combo.addItem("")
                
        except Exception as e:
            print(f"ルートコード一覧更新エラー: {e}")
    
    def on_route_code_changed(self, route_name: str):
        """ルートコード変更時の処理"""
        try:
            if route_name:
                # ルート名からルートコードを取得
                route_code = self.store_db.get_route_code_by_name(route_name)
                if route_code:
                    # ルートコードを表示用に更新（必要に応じて）
                    pass
        except Exception as e:
            print(f"ルートコード変更処理エラー: {e}")
    
    def get_selected_route_code(self) -> str:
        """選択されたルートコードを取得"""
        route_name = self.route_code_combo.currentText().strip()
        if route_name:
            # ルート名からルートコードを取得
            route_code = self.store_db.get_route_code_by_name(route_name)
            return route_code or route_name  # ルートコードが見つからない場合はルート名を返す
        return ""
    
    def get_stores_for_route(self, route_name: str) -> List[Dict[str, Any]]:
        """指定されたルートの店舗一覧を取得（表示順序でソート）"""
        try:
            # 表示順序でソートされた店舗一覧を取得
            if hasattr(self.store_db, 'get_stores_for_route_ordered'):
                return self.store_db.get_stores_for_route_ordered(route_name)
            else:
                # 後方互換性のため、表示順序がない場合は従来の方法
                stores = self.store_db.list_stores()
                route_stores = [
                    store for store in stores
                    if store.get('affiliated_route_name') == route_name
                ]
                # display_orderでソート（存在しない場合は0）
                route_stores.sort(key=lambda x: (x.get('display_order', 0), x.get('store_name', '')))
                return route_stores
        except Exception as e:
            print(f"店舗一覧取得エラー: {e}")
            return []
    
    def setup_shortcuts(self):
        """ショートカットキーの設定"""
        # Ctrl+Z: Undo
        undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(self.undo_action)
        
        # Ctrl+Y: Redo
        redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        redo_shortcut.activated.connect(self.redo_action)
    
    def save_table_state(self):
        """テーブルの現在の状態を保存（Undo用）"""
        state = []
        for row in range(self.store_visits_table.rowCount()):
            row_data = {}
            for col in range(self.store_visits_table.columnCount()):
                # 星評価列の場合はウィジェットから取得
                if col == 9:
                    star_widget = self.store_visits_table.cellWidget(row, col)
                    row_data[col] = star_widget.rating() if star_widget else 0
                else:
                    item = self.store_visits_table.item(row, col)
                    row_data[col] = item.text() if item else ''
            state.append(row_data)
        
        # Undoスタックに追加
        self.undo_stack.append(state)
        if len(self.undo_stack) > self.max_undo_history:
            self.undo_stack.pop(0)
        
        # Redoスタックをクリア（新しい操作が行われたため）
        self.redo_stack.clear()
    
    def restore_table_state(self, state):
        """テーブルの状態を復元"""
        # 変更イベントを一時的に無効化
        self.store_visits_table.blockSignals(True)
        
        try:
            self.store_visits_table.setRowCount(len(state))
            for row_idx, row_data in enumerate(state):
                for col_idx, value in row_data.items():
                    col_idx_int = int(col_idx)
                    # 星評価列の場合はウィジェットを設定
                    if col_idx_int == 9:
                        rating = self._safe_int(str(value)) or 0
                        star_widget = StarRatingWidget(self.store_visits_table, rating=rating)
                        star_widget.rating_changed.connect(lambda rating, r=row_idx: self.on_star_rating_changed(r, rating))
                        self.store_visits_table.setCellWidget(row_idx, col_idx_int, star_widget)
                    else:
                        item = QTableWidgetItem(str(value))
                        self.store_visits_table.setItem(row_idx, col_idx_int, item)
            
            # 訪問順序を再設定
            self.update_visit_order()
            getattr(self, 'update_calculation_results', lambda: None)()
        finally:
            # 変更イベントを再有効化
            self.store_visits_table.blockSignals(False)
    
    def undo_action(self):
        """Undo操作"""
        if not self.undo_stack:
            QMessageBox.information(self, "情報", "元に戻す操作がありません")
            return
        
        # 現在の状態をRedoスタックに保存
        current_state = []
        for row in range(self.store_visits_table.rowCount()):
            row_data = {}
            for col in range(self.store_visits_table.columnCount()):
                item = self.store_visits_table.item(row, col)
                row_data[col] = item.text() if item else ''
            current_state.append(row_data)
        self.redo_stack.append(current_state)
        
        # Undoスタックから前の状態を復元
        previous_state = self.undo_stack.pop()
        self.restore_table_state(previous_state)
        
        # 訪問順序を保存
        self.save_store_order()
        
        QMessageBox.information(self, "完了", "操作を元に戻しました")
    
    def redo_action(self):
        """Redo操作"""
        if not self.redo_stack:
            QMessageBox.information(self, "情報", "やり直す操作がありません")
            return
        
        # 現在の状態をUndoスタックに保存
        current_state = []
        for row in range(self.store_visits_table.rowCount()):
            row_data = {}
            for col in range(self.store_visits_table.columnCount()):
                item = self.store_visits_table.item(row, col)
                row_data[col] = item.text() if item else ''
            current_state.append(row_data)
        self.undo_stack.append(current_state)
        
        # Redoスタックから次の状態を復元
        next_state = self.redo_stack.pop()
        self.restore_table_state(next_state)
        
        # 訪問順序を保存
        self.save_store_order()
        
        QMessageBox.information(self, "完了", "操作をやり直しました")
    
    def on_table_item_changed(self, item):
        """テーブルのアイテムが変更されたときの処理"""
        # 頻繁に呼ばれるので、少し遅延させてから保存（連続変更を1回として扱う）
        if not hasattr(self, '_change_timer'):
            from PySide6.QtCore import QTimer
            self._change_timer = QTimer()
            self._change_timer.setSingleShot(True)
            def _batched_update():
                self.save_table_state()
                self.recalc_travel_times()
            self._change_timer.timeout.connect(_batched_update)
        
        # タイマーをリセット（500ms後に保存）
        self._change_timer.stop()
        self._change_timer.start(500)
    
    def on_rows_moved(self, parent, start, end, destination, row):
        """行移動時の処理（訪問順序を再設定）"""
        # 変更イベントを一時的に無効化
        self.store_visits_table.blockSignals(True)
        
        try:
            # 訪問順序を再設定
            for i in range(self.store_visits_table.rowCount()):
                order_item = self.store_visits_table.item(i, 0)
                if order_item:
                    order_item.setText(str(i + 1))
            
            # 状態を保存
            self.save_table_state()
            
            # 訪問順序を保存
            self.save_store_order()
            getattr(self, 'update_calculation_results', lambda: None)()
        finally:
            # 変更イベントを再有効化
            self.store_visits_table.blockSignals(False)
    
    def save_store_order(self):
        """現在の訪問順序をデータベースに保存"""
        try:
            route_name = self.route_code_combo.currentText().strip()
            if not route_name:
                return
            
            # 現在の訪問順序を取得
            store_orders = {}
            for row in range(self.store_visits_table.rowCount()):
                code_item = self.store_visits_table.item(row, 1)  # 店舗コード列
                if code_item:
                    supplier_code = code_item.text().strip()
                    if supplier_code:
                        store_orders[supplier_code] = row + 1  # 1始まりの順序
            
            if store_orders:
                # データベースに保存
                if hasattr(self.store_db, 'update_store_display_order'):
                    self.store_db.update_store_display_order(route_name, store_orders)
        except Exception as e:
            print(f"訪問順序保存エラー: {e}")
    
    def generate_template(self):
        """テンプレート生成"""
        try:
            route_name = self.route_code_combo.currentText().strip()
            route_code = self.get_selected_route_code()
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "テンプレートファイルを保存",
                f"route_template_{route_name or 'new'}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                "Excelファイル (*.xlsx);;CSVファイル (*.csv)"
            )
            
            if not file_path:
                return
            
            # 選択されたルートの店舗一覧を取得
            stores = []
            store_codes = []
            if route_name:
                stores = self.get_stores_for_route(route_name)
                store_codes = [
                    store.get('supplier_code')
                    for store in stores
                    if store.get('supplier_code')
                ]
            
            if not TemplateGenerator:
                QMessageBox.warning(self, "エラー", "テンプレート生成機能が利用できません")
                return
            
            if file_path.endswith('.xlsx'):
                # ルート名（日本語名）を渡してテンプレートに表示
                success = TemplateGenerator.generate_excel_template(file_path, route_name, store_codes, stores)
            else:
                success = TemplateGenerator.generate_csv_template(file_path, route_code, store_codes)
            
            if success:
                QMessageBox.information(self, "成功", f"テンプレートを生成しました:\n{file_path}")
            else:
                QMessageBox.warning(self, "エラー", "テンプレートの生成に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"テンプレート生成中にエラーが発生しました:\n{str(e)}")
    
    def load_template(self):
        """テンプレート読み込み"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "テンプレートファイルを選択",
                "",
                "Excelファイル (*.xlsx *.xlsm);;CSVファイル (*.csv);;すべてのファイル (*)"
            )
            
            if not file_path:
                return
            
            # Excel読み込み
            if file_path.endswith(('.xlsx', '.xlsm')):
                df_route = None
                # 単一シート構成にも対応
                try:
                    df_route = pd.read_excel(file_path, sheet_name='ルート情報')
                except Exception:
                    df_route = None
                try:
                    df_visits = pd.read_excel(file_path, sheet_name='店舗訪問詳細')
                except Exception as e:
                    QMessageBox.warning(self, "エラー", f"Excelファイルの読み込みに失敗しました:\n{str(e)}")
                    return
            else:
                # CSV読み込み（簡易実装）
                QMessageBox.warning(self, "注意", "CSV形式の読み込みは開発中です")
                return
            
            # ルート情報を読み込み（2シート構成の場合）
            route_values = {}
            if df_route is not None and '値' in df_route.columns and '項目' in df_route.columns:
                for _, row in df_route.iterrows():
                    item = row.get('項目', '')
                    value = row.get('値', '')
                    if item == 'ルート日付':
                        try:
                            dt = pd.to_datetime(value)
                            self.route_date_edit.setDateTime(QDateTime.fromString(dt.strftime('%Y-%m-%d'), 'yyyy-MM-dd'))
                        except:
                            pass
                    elif item == 'ルートコード':
                        # ルートコードをコンボボックスに設定
                        route_code_text = str(value)
                        # 既存のルート名から該当するものを探す
                        index = self.route_code_combo.findText(route_code_text)
                        if index >= 0:
                            self.route_code_combo.setCurrentIndex(index)
                        else:
                            # 見つからない場合は手動入力として設定
                            self.route_code_combo.setCurrentText(route_code_text)
                    elif item == '出発時間':
                        try:
                            dt = pd.to_datetime(value)
                            self.departure_time_edit.setText(dt.strftime('%H:%M'))
                        except Exception:
                            pass
                    elif item == '帰宅時間':
                        try:
                            dt = pd.to_datetime(value)
                            self.return_time_edit.setText(dt.strftime('%H:%M'))
                        except Exception:
                            pass
                    elif item == '往路高速代':
                        self.toll_fee_outbound_spin.setValue(float(value) if value else 0)
                    elif item == '復路高速代':
                        self.toll_fee_return_spin.setValue(float(value) if value else 0)
                    elif item == '駐車場代':
                        # 削除済みのため無視
                        pass
                    elif item == '食費':
                        # 削除済みのため無視
                        pass
                    elif item == 'その他経費':
                        # 削除済みのため無視
                        pass
                    elif item == '備考（天候等）' or item == '備考':
                        self.remarks_edit.setPlainText(str(value) if value else '')

            # 単一シート構成（1枚目の生成テンプレ形式）に対応：openpyxlでセル値も取得
            try:
                wb = openpyxl.load_workbook(file_path, data_only=True)
                ws = wb['店舗訪問詳細'] if '店舗訪問詳細' in wb.sheetnames else wb.active

                def _to_time_str(v: Any) -> str:
                    if v is None or v == '':
                        return ''
                    if isinstance(v, dt_time):
                        return QTime(v.hour, v.minute).toString('HH:mm')
                    if isinstance(v, datetime):
                        return QTime(v.hour, v.minute).toString('HH:mm')
                    # Excel数値(1日=1) の場合
                    try:
                        num = float(v)
                        total_minutes = int(round(num * 24 * 60))
                        hh = total_minutes // 60
                        mm = total_minutes % 60
                        return f"{hh:02d}:{mm:02d}"
                    except Exception:
                        s = str(v).strip()
                        # 既にHH:MMの文字列
                        return s

                # 上部情報の読み込み
                top_date = ws['B1'].value
                if top_date:
                    try:
                        if isinstance(top_date, datetime):
                            d_str = top_date.strftime('%Y-%m-%d')
                        else:
                            d_str = pd.to_datetime(str(top_date)).strftime('%Y-%m-%d')
                        self.route_date_edit.setDateTime(QDateTime.fromString(d_str, 'yyyy-MM-dd'))
                    except Exception:
                        pass

                route_name = (ws['B2'].value or '').strip()
                if route_name:
                    idx = self.route_code_combo.findText(route_name)
                    if idx >= 0:
                        self.route_code_combo.setCurrentIndex(idx)
                    else:
                        self.route_code_combo.setCurrentText(route_name)

                # データ行（4行目以降、A列が空で終了）
                rows_data: List[Dict[str, Any]] = []
                r = 4
                while True:
                    code = ws[f'A{r}'].value
                    name = ws[f'B{r}'].value
                    if (code is None or str(code).strip() == '') and (name is None or str(name).strip() == ''):
                        break
                    arrival = _to_time_str(ws[f'C{r}'].value)
                    depart = _to_time_str(ws[f'D{r}'].value)
                    stay_val = ws[f'E{r}'].value
                    try:
                        stay_minutes = int(round(float(stay_val))) if stay_val not in (None, '') else 0
                    except Exception:
                        stay_minutes = 0
                    memo = ws[f'F{r}'].value or ''
                    rows_data.append({
                        'code': str(code or ''),
                        'name': str(name or ''),
                        'in': arrival,
                        'out': depart,
                        'stay': stay_minutes,
                        'memo': str(memo)
                    })
                    r += 1

                # テーブルへ反映
                self.store_visits_table.setRowCount(len(rows_data))
                for i, rd in enumerate(rows_data):
                    # 訪問順序
                    order_item = QTableWidgetItem(str(i + 1))
                    order_item.setFlags(order_item.flags() & ~Qt.ItemIsEditable)
                    self.store_visits_table.setItem(i, 0, order_item)

                    self.store_visits_table.setItem(i, 1, QTableWidgetItem(rd['code']))
                    self.store_visits_table.setItem(i, 2, QTableWidgetItem(rd['name']))
                    self.store_visits_table.setItem(i, 3, QTableWidgetItem(rd['in']))
                    self.store_visits_table.setItem(i, 4, QTableWidgetItem(rd['out']))
                    self.store_visits_table.setItem(i, 5, QTableWidgetItem(str(rd['stay'])))
                    # 店舗メモ（備考）
                    self.store_visits_table.setItem(i, 10, QTableWidgetItem(rd['memo']))

                    # 店舗評価は0で初期化
                    star_widget = StarRatingWidget(self.store_visits_table, rating=0, star_size=14)
                    star_widget.rating_changed.connect(lambda rating, r=i: self.on_star_rating_changed(r, rating))
                    self.store_visits_table.setCellWidget(i, 9, star_widget)

                # 下部情報（17行目以降）
                try:
                    bottom_map = {}
                    for rr in range(17, 17 + 10):
                        key = ws[f'A{rr}'].value
                        val = ws[f'B{rr}'].value
                        if key:
                            bottom_map[str(key).strip()] = val

                    # 出発時刻・帰宅時刻
                    dep_str = _to_time_str(bottom_map.get('出発時刻'))
                    ret_str = _to_time_str(bottom_map.get('帰宅時刻'))
                    if dep_str:
                        self.departure_time_edit.setText(dep_str)
                    if ret_str:
                        self.return_time_edit.setText(ret_str)

                    # 高速代
                    try:
                        self.toll_fee_outbound_spin.setValue(float(bottom_map.get('往路高速代') or 0))
                    except Exception:
                        pass
                    try:
                        self.toll_fee_return_spin.setValue(float(bottom_map.get('復路高速代') or 0))
                    except Exception:
                        pass
                except Exception as _:
                    pass
            except Exception:
                # 旧ロジック（pandas）にフォールバック
                pass
            
            QMessageBox.information(self, "完了", "テンプレートを読み込みました")
            # 移動時間（分）を自動計算
            self.recalc_travel_times()
            getattr(self, 'update_calculation_results', lambda: None)()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"テンプレート読み込み中にエラーが発生しました:\n{str(e)}")
    
    def run_matching(self):
        """照合処理実行"""
        QMessageBox.information(self, "照合処理", "照合処理機能は仕入リストと連携する必要があります")
    
    def auto_add_stores(self):
        """選択されたルートの店舗を自動追加（重複チェック付き）"""
        # 変更前の状態を保存
        self.save_table_state()
        
        try:
            route_name = self.route_code_combo.currentText().strip()
            if not route_name:
                QMessageBox.warning(self, "警告", "ルートを選択してください")
                return
            
            # 選択されたルートの店舗一覧を取得
            stores = self.get_stores_for_route(route_name)
            if not stores:
                QMessageBox.information(self, "情報", f"ルート「{route_name}」に登録されている店舗がありません")
                return
            
            # 既存の店舗コード一覧を取得（重複チェック用）
            existing_codes = set()
            for row in range(self.store_visits_table.rowCount()):
                code_item = self.store_visits_table.item(row, 1)  # 店舗コード列
                if code_item:
                    code = code_item.text().strip()
                    if code:
                        existing_codes.add(code)
            
            # 追加する店舗をフィルタリング（重複を除外）
            stores_to_add = [
                store for store in stores
                if store.get('supplier_code') and store.get('supplier_code') not in existing_codes
            ]
            
            if not stores_to_add:
                QMessageBox.information(self, "情報", "追加可能な店舗がありません（すべて既に追加済みです）")
                return
            
            # 既存の行数を取得
            current_rows = self.store_visits_table.rowCount()
            
            # 店舗をテーブルに追加
            for i, store in enumerate(stores_to_add):
                row = current_rows + i
                self.store_visits_table.insertRow(row)
                
                # 訪問順序
                order_item = QTableWidgetItem(str(row + 1))
                order_item.setFlags(order_item.flags() & ~Qt.ItemIsEditable)
                self.store_visits_table.setItem(row, 0, order_item)
                
                # 店舗コード
                code_item = QTableWidgetItem(store.get('supplier_code', ''))
                self.store_visits_table.setItem(row, 1, code_item)
                
                # 店舗名
                name_item = QTableWidgetItem(store.get('store_name', ''))
                self.store_visits_table.setItem(row, 2, name_item)
                
                # 星評価ウィジェットをセルに配置
                star_widget = StarRatingWidget(self.store_visits_table, rating=0, star_size=14)
                star_widget.rating_changed.connect(lambda rating, r=row: self.on_star_rating_changed(r, rating))
                self.store_visits_table.setCellWidget(row, 9, star_widget)
            
            # 訪問順序を再設定
            self.update_visit_order()
            
            # 訪問順序を保存
            self.save_store_order()
            
            # 変更後の状態を保存
            self.save_table_state()
            
            QMessageBox.information(self, "完了", f"{len(stores_to_add)}件の店舗を追加しました")
            getattr(self, 'update_calculation_results', lambda: None)()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"店舗自動追加中にエラーが発生しました:\n{str(e)}")
    
    def update_visit_order(self):
        """訪問順序を再設定"""
        for i in range(self.store_visits_table.rowCount()):
            order_item = self.store_visits_table.item(i, 0)
            if order_item:
                order_item.setText(str(i + 1))
        # 順序が変わったら移動時間も更新
        self.recalc_travel_times()

    def recalc_travel_times(self):
        """移動時間（分）を自動計算して6列目に反映"""
        try:
            row_count = self.store_visits_table.rowCount()
            if row_count == 0:
                return

            def parse_hhmm(text: str) -> Optional[QTime]:
                text = (text or '').strip()
                if not text:
                    return None
                # HH:mm または H:mm を許容
                parts = text.split(':')
                if len(parts) != 2:
                    return None
                try:
                    h = int(parts[0])
                    m = int(parts[1])
                    if 0 <= h < 24 and 0 <= m < 60:
                        return QTime(h, m)
                except ValueError:
                    return None
                return None

            def get_text(row: int, col: int) -> str:
                item = self.store_visits_table.item(row, col)
                return item.text() if item else ''

            # 1店舗目: 出発時間 から IN時間
            first_in = parse_hhmm(get_text(0, 3))
            dep_time = parse_hhmm(self.departure_time_edit.text())
            if first_in and dep_time:
                mins = dep_time.secsTo(first_in) // 60
                mins = max(0, int(mins))
                self.store_visits_table.setItem(0, 6, QTableWidgetItem(str(mins)))
            else:
                self.store_visits_table.setItem(0, 6, QTableWidgetItem(''))

            # 2店舗目以降: 前店舗OUT → 現在IN
            for r in range(1, row_count):
                prev_out = parse_hhmm(get_text(r - 1, 4))
                cur_in = parse_hhmm(get_text(r, 3))
                if prev_out and cur_in:
                    mins = prev_out.secsTo(cur_in) // 60
                    mins = max(0, int(mins))
                    self.store_visits_table.setItem(r, 6, QTableWidgetItem(str(mins)))
                else:
                    self.store_visits_table.setItem(r, 6, QTableWidgetItem(''))
        except Exception as e:
            print(f"移動時間計算エラー: {e}")


    def add_store_visit_row(self):
        """店舗訪問行を追加"""
        # 変更前の状態を保存
        self.save_table_state()
        
        row = self.store_visits_table.rowCount()
        self.store_visits_table.insertRow(row)
        
        # 訪問順序を自動設定
        order_item = QTableWidgetItem(str(row + 1))
        order_item.setFlags(order_item.flags() & ~Qt.ItemIsEditable)
        self.store_visits_table.setItem(row, 0, order_item)
        
        # 星評価ウィジェットをセルに配置
        star_widget = StarRatingWidget(self.store_visits_table, rating=0, star_size=14)
        star_widget.rating_changed.connect(lambda rating, r=row: self.on_star_rating_changed(r, rating))
        self.store_visits_table.setCellWidget(row, 9, star_widget)
        
        # 変更後の状態を保存
        self.save_table_state()

    def on_star_rating_changed(self, row: int, rating: int):
        """星評価が変更されたときの処理"""
        # データ変更をUndoスタックに保存
        self.on_table_item_changed(None)

    def clear_all_rows(self):
        """すべての行をクリア"""
        reply = QMessageBox.question(
            self,
            "確認",
            "すべての行を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 変更前の状態を保存
            self.save_table_state()
            
            self.store_visits_table.setRowCount(0)
            # 訪問順序を保存（クリア状態）
            self.save_store_order()
            getattr(self, 'update_calculation_results', lambda: None)()
            
            # 変更後の状態を保存
            self.save_table_state()
            
            QMessageBox.information(self, "完了", "すべての行を削除しました")

    def delete_store_visit_row(self):
        """選択された店舗訪問行を削除"""
        # 選択行の取得（行選択/セル選択の両対応）
        selected_indexes = self.store_visits_table.selectionModel().selectedRows()
        selected_rows = {idx.row() for idx in selected_indexes}
        if not selected_rows:
            current = self.store_visits_table.currentRow()
            if current >= 0:
                selected_rows = {current}
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除する行を選択してください")
            return
        
        # 変更前の状態を保存
        self.save_table_state()
        
        # 行番号を降順でソート（後ろから削除することでインデックスがずれない）
        for row in sorted(selected_rows, reverse=True):
            self.store_visits_table.removeRow(row)
        
        # 訪問順序を再設定
        self.update_visit_order()
        
        # 訪問順序を保存
        self.save_store_order()
        
        # 変更後の状態を保存
        self.save_table_state()
        
        getattr(self, 'update_calculation_results', lambda: None)()

class StoreSelectDialog(QDialog):
    """店舗マスタ一覧を表示して選択させるダイアログ"""
    def __init__(self, store_db: StoreDatabase, parent=None):
        super().__init__(parent)
        self.setWindowTitle("店舗マスタから追加")
        self.resize(700, 480)
        self.store_db = store_db
        self.selected_rows: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("コード/店舗名で検索")
        search_btn = QPushButton("検索")
        search_btn.clicked.connect(self.filter_rows)
        search_layout.addWidget(self.search_edit)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["ルート名", "店舗コード", "店舗名"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.MultiSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.load_rows()

    def load_rows(self):
        try:
            stores = self.store_db.list_stores()
        except Exception:
            stores = []
        self.all_rows = stores
        self.populate(stores)

    def populate(self, stores: List[Dict[str, Any]]):
        self.table.setRowCount(len(stores))
        for i, s in enumerate(stores):
            self.table.setItem(i, 0, QTableWidgetItem(str(s.get('affiliated_route_name', ''))))
            self.table.setItem(i, 1, QTableWidgetItem(str(s.get('supplier_code', ''))))
            self.table.setItem(i, 2, QTableWidgetItem(str(s.get('store_name', ''))))

    def filter_rows(self):
        q = self.search_edit.text().strip().lower()
        if not q:
            self.populate(self.all_rows)
            return
        filtered = [s for s in self.all_rows if q in str(s.get('supplier_code','')).lower() or q in str(s.get('store_name','')).lower()]
        self.populate(filtered)

    def get_selected_stores(self) -> List[Dict[str, Any]]:
        rows = []
        for idx in self.table.selectionModel().selectedRows():
            r = idx.row()
            code = self.table.item(r, 1).text() if self.table.item(r, 1) else ''
            name = self.table.item(r, 2).text() if self.table.item(r, 2) else ''
            route = self.table.item(r, 0).text() if self.table.item(r, 0) else ''
            rows.append({'supplier_code': code, 'store_name': name, 'affiliated_route_name': route})
        return rows
    
    def get_route_data(self) -> Dict[str, Any]:
        """入力データを取得"""
        route_date = self.route_date_edit.dateTime().toString('yyyy-MM-dd')
        # 時刻は編集欄から取得し、ルート日付と結合
        dep_text = (self.departure_time_edit.text() or '').strip()
        ret_text = (self.return_time_edit.text() or '').strip()
        # 簡易バリデーション（不正時は空として扱う）
        def to_sec(text: str) -> str:
            try:
                parts = text.split(':')
                if len(parts) != 2:
                    return ''
                h = int(parts[0]); m = int(parts[1])
                if 0 <= h <= 23 and 0 <= m <= 59:
                    return f"{h:02d}:{m:02d}:00"
            except Exception:
                return ''
            return ''
        dep_time = to_sec(dep_text) or '00:00:00'
        ret_time = to_sec(ret_text) or '00:00:00'
        departure_time = f"{route_date} {dep_time}"
        return_time = f"{route_date} {ret_time}"
        
        return {
            'route_date': route_date,
            'route_code': self.get_selected_route_code(),
            'departure_time': departure_time,
            'return_time': return_time,
            'toll_fee_outbound': self.toll_fee_outbound_spin.value(),
            'toll_fee_return': self.toll_fee_return_spin.value(),
            'parking_fee': 0,  # 削除済み
            'meal_cost': 0,  # 削除済み
            'other_expenses': 0,  # 削除済み
            'remarks': self.remarks_edit.toPlainText()
        }
    
    def get_store_visits_data(self) -> List[Dict[str, Any]]:
        """店舗訪問詳細データを取得"""
        visits = []
        
        for i in range(self.store_visits_table.rowCount()):
            # 星評価を取得
            star_widget = self.store_visits_table.cellWidget(i, 9)
            rating = star_widget.rating() if star_widget else 0
            
            visit = {
                'visit_order': i + 1,
                'store_code': self._get_table_item(i, 1),
                'store_name': self._get_table_item(i, 2),
                'store_in_time': self._get_table_item(i, 3),
                'store_out_time': self._get_table_item(i, 4),
                'stay_duration': self._safe_float(self._get_table_item(i, 5)),  # 店舗滞在時間
                'travel_time_from_prev': self._safe_float(self._get_table_item(i, 6)),
                'store_gross_profit': self._safe_float(self._get_table_item(i, 7)),
                'store_item_count': self._safe_int(self._get_table_item(i, 8)),
                'store_rating': rating,  # 星評価
                'store_notes': self._get_table_item(i, 10)  # 店舗メモ
            }
            visits.append(visit)
        
        return visits
    
    def _get_table_item(self, row: int, col: int) -> str:
        """テーブルのアイテムを取得"""
        item = self.store_visits_table.item(row, col)
        return item.text() if item else ''
    
    def _safe_float(self, value: str) -> Optional[float]:
        """安全にfloatに変換"""
        try:
            return float(value) if value else None
        except (ValueError, TypeError):
            return None
    
    def _safe_int(self, value: str) -> Optional[int]:
        """安全にintに変換"""
        try:
            return int(float(value)) if value else None
        except (ValueError, TypeError):
            return None
    
    def update_calculation_results(self):
        """計算結果を更新"""
        try:
            route_data = self.get_route_data()
            store_visits = self.get_store_visits_data()
            
            # 計算実行
            stats = self.calc_service.calculate_route_statistics(route_data, store_visits)
            
            # 結果表示
            result_text = f"""
計算結果:
- 実働時間: {stats.get('total_working_hours', 0):.2f} 時間
- 総粗利: {stats.get('total_gross_profit', 0):,.0f} 円
- 総仕入れ点数: {stats.get('total_item_count', 0)} 点
- 想定時給: {stats.get('estimated_hourly_rate', 0):,.0f} 円/時間
- 仕入れ成功率: {stats.get('purchase_success_rate', 0) * 100:.1f}%
- 平均仕入れ単価: {stats.get('avg_purchase_price', 0):,.0f} 円/点
            """.strip()
            
            self.calculation_label.setText(result_text)
            
        except Exception as e:
            self.calculation_label.setText(f"計算エラー: {str(e)}")
    
    def save_data(self):
        """データを保存"""
        try:
            route_data = self.get_route_data()
            store_visits = self.get_store_visits_data()
            
            # バリデーション
            if not route_data.get('route_code'):
                QMessageBox.warning(self, "警告", "ルートコードを入力してください")
                return
            
            # 訪問順序を保存
            self.save_store_order()
            
            # 計算実行
            if not self.calc_service:
                QMessageBox.warning(self, "エラー", "計算サービスが利用できません")
                return
            
            stats = self.calc_service.calculate_route_statistics(route_data, store_visits)
            
            # 計算結果をroute_dataに追加
            route_data.update(stats)
            
            # データベースに保存
            if self.current_route_id:
                # 更新
                self.route_db.update_route_summary(self.current_route_id, route_data)
                # 既存の店舗訪問詳細を削除
                existing_visits = self.route_db.get_store_visits_by_route(self.current_route_id)
                for visit in existing_visits:
                    self.route_db.delete_store_visit(visit['id'])
            else:
                # 新規作成
                self.current_route_id = self.route_db.add_route_summary(route_data)
            
            # 店舗訪問詳細を保存
            for visit in store_visits:
                visit['route_summary_id'] = self.current_route_id
                self.route_db.add_store_visit(visit)
            
            QMessageBox.information(self, "完了", "データを保存しました")
            self.data_saved.emit(self.current_route_id)
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"データ保存中にエラーが発生しました:\n{str(e)}")
    
    def new_route(self):
        """新規ルート作成"""
        self.current_route_id = None
        self.route_code_combo.setCurrentText("")
        self.route_date_edit.setDateTime(QDateTime.currentDateTime())
        self.departure_time_edit.setText(QTime.currentTime().toString('HH:mm'))
        self.return_time_edit.setText(QTime.currentTime().toString('HH:mm'))
        self.toll_fee_outbound_spin.setValue(0)
        self.toll_fee_return_spin.setValue(0)
        self.remarks_edit.clear()
        self.store_visits_table.setRowCount(0)
        self.calculation_label.setText("計算結果: データ未入力")

