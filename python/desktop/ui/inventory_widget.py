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
    QCheckBox, QSpinBox, QDateEdit
)
from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtGui import QFont, QColor, QPalette
import pandas as pd
from pathlib import Path
import re


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
        
        # UIの初期化
        self.setup_ui()
        
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：ファイル操作エリア
        self.setup_file_operations()
        
        # 中央：検索・フィルタエリア
        self.setup_search_filters()
        
        # 下部：データテーブルエリア
        self.setup_data_table()
        
        # 最下部：アクションボタンエリア
        self.setup_action_buttons()
        
    def setup_file_operations(self):
        """ファイル操作エリアの設定"""
        file_group = QGroupBox("ファイル操作")
        file_layout = QHBoxLayout(file_group)
        
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
        file_layout.addWidget(self.import_btn)
        
        # エクスポートボタン
        self.export_btn = QPushButton("CSV出力")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        file_layout.addWidget(self.export_btn)
        
        # データクリアボタン
        self.clear_btn = QPushButton("データクリア")
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setEnabled(False)
        file_layout.addWidget(self.clear_btn)
        
        file_layout.addStretch()
        
        # データ件数表示
        self.data_count_label = QLabel("データ件数: 0")
        file_layout.addWidget(self.data_count_label)
        
        self.layout().addWidget(file_group)
        
    def setup_search_filters(self):
        """検索・フィルタエリアの設定"""
        filter_group = QGroupBox("検索・フィルタ")
        filter_layout = QVBoxLayout(filter_group)
        
        # 検索行
        search_layout = QHBoxLayout()
        
        # 検索ボックス
        search_label = QLabel("検索:")
        search_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("商品名、ASIN、JANコードで検索...")
        self.search_edit.textChanged.connect(self.apply_filters)
        search_layout.addWidget(self.search_edit)
        
        # 検索クリアボタン
        self.clear_search_btn = QPushButton("クリア")
        self.clear_search_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(self.clear_search_btn)
        
        filter_layout.addLayout(search_layout)
        
        # フィルタ行
        filter_row_layout = QHBoxLayout()
        
        # Q列フィルタ
        q_filter_label = QLabel("Q列:")
        filter_row_layout.addWidget(q_filter_label)
        
        self.q_filter_combo = QComboBox()
        self.q_filter_combo.addItems(["すべて", "Q1", "Q2", "Q3", "Q4", "Qなし"])
        self.q_filter_combo.currentTextChanged.connect(self.apply_filters)
        filter_row_layout.addWidget(self.q_filter_combo)
        
        # 価格範囲フィルタ
        price_label = QLabel("価格範囲:")
        filter_row_layout.addWidget(price_label)
        
        self.min_price_spin = QSpinBox()
        self.min_price_spin.setRange(0, 999999)
        self.min_price_spin.setValue(0)
        self.min_price_spin.valueChanged.connect(self.apply_filters)
        filter_row_layout.addWidget(self.min_price_spin)
        
        price_to_label = QLabel("〜")
        filter_row_layout.addWidget(price_to_label)
        
        self.max_price_spin = QSpinBox()
        self.max_price_spin.setRange(0, 999999)
        self.max_price_spin.setValue(999999)
        self.max_price_spin.valueChanged.connect(self.apply_filters)
        filter_row_layout.addWidget(self.max_price_spin)
        
        filter_row_layout.addStretch()
        
        # フィルタリセットボタン
        self.reset_filters_btn = QPushButton("フィルタリセット")
        self.reset_filters_btn.clicked.connect(self.reset_filters)
        filter_row_layout.addWidget(self.reset_filters_btn)
        
        filter_layout.addLayout(filter_row_layout)
        
        self.layout().addWidget(filter_group)
        
    def setup_data_table(self):
        """データテーブルエリアの設定"""
        # テーブルウィジェットの作成
        self.data_table = QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.data_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        
        # ヘッダーの設定
        header = self.data_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        # 列の定義（17列対応）
        self.column_headers = [
            "SKU", "ASIN", "JAN", "商品名", "状態", "Q列", "仕入日",
            "店舗", "価格", "原価", "利益", "出品日", "売上日",
            "備考", "写真", "URL", "メモ"
        ]
        
        self.data_table.setColumnCount(len(self.column_headers))
        self.data_table.setHorizontalHeaderLabels(self.column_headers)
        
        # テーブルをレイアウトに追加
        self.layout().addWidget(self.data_table)
        
    def setup_action_buttons(self):
        """アクションボタンエリアの設定"""
        action_layout = QHBoxLayout()
        
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
        action_layout.addWidget(self.generate_sku_btn)
        
        # 出品CSV生成ボタン
        self.export_listing_btn = QPushButton("出品CSV生成")
        self.export_listing_btn.clicked.connect(self.export_listing_csv)
        self.export_listing_btn.setEnabled(False)
        action_layout.addWidget(self.export_listing_btn)
        
        # 古物台帳生成ボタン
        self.antique_register_btn = QPushButton("古物台帳生成")
        self.antique_register_btn.clicked.connect(self.generate_antique_register)
        self.antique_register_btn.setEnabled(False)
        action_layout.addWidget(self.antique_register_btn)
        
        action_layout.addStretch()
        
        # 統計情報表示
        self.stats_label = QLabel("統計: なし")
        action_layout.addWidget(self.stats_label)
        
        self.layout().addLayout(action_layout)
        
    def import_csv(self):
        """CSVファイルの取込"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "CSVファイルを選択",
            "",
            "CSVファイル (*.csv);;すべてのファイル (*)"
        )
        
        if file_path:
            try:
                # CSVファイルの読み込み
                self.inventory_data = pd.read_csv(file_path, encoding='utf-8')
                self.filtered_data = self.inventory_data.copy()
                
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
                
    def update_table(self):
        """テーブルの更新"""
        if self.filtered_data is None:
            return
            
        # テーブルの設定
        self.data_table.setRowCount(len(self.filtered_data))
        
        # データの設定
        for i, row in self.filtered_data.iterrows():
            for j, column in enumerate(self.column_headers):
                value = str(row.get(column, ""))
                item = QTableWidgetItem(value)
                
                # Q列のハイライト
                if column == "Q列" and value in ["Q1", "Q2", "Q3", "Q4"]:
                    item.setBackground(QColor(255, 255, 200))  # 薄い黄色
                
                # 価格列の数値フォーマット
                if column in ["価格", "原価", "利益"] and value.replace(".", "").isdigit():
                    try:
                        num_value = float(value)
                        item.setText(f"{num_value:,.0f}")
                    except:
                        pass
                
                self.data_table.setItem(i, j, item)
        
        # 列幅の自動調整
        self.data_table.resizeColumnsToContents()
        
    def apply_filters(self):
        """フィルタの適用"""
        if self.inventory_data is None:
            return
            
        # 検索条件
        search_text = self.search_edit.text().lower()
        
        # Q列フィルタ
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
        
        # Q列フィルタ
        if q_filter != "すべて":
            if q_filter == "Qなし":
                q_mask = self.inventory_data.get("Q列", "").isna() | (self.inventory_data.get("Q列", "") == "")
            else:
                q_mask = self.inventory_data.get("Q列", "") == q_filter
            mask &= q_mask
        
        # 価格範囲フィルタ
        if "価格" in self.inventory_data.columns:
            try:
                price_series = pd.to_numeric(self.inventory_data["価格"], errors='coerce')
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
        self.q_filter_combo.setCurrentText("すべて")
        self.min_price_spin.setValue(0)
        self.max_price_spin.setValue(999999)
        
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
        
        # Q列の統計
        q_counts = self.filtered_data.get("Q列", "").value_counts()
        q_stats = ", ".join([f"{q}: {count}" for q, count in q_counts.items() if q])
        
        # 価格統計
        if "価格" in self.filtered_data.columns:
            try:
                prices = pd.to_numeric(self.filtered_data["価格"], errors='coerce')
                avg_price = prices.mean()
                total_value = prices.sum()
                price_stats = f"平均価格: {avg_price:,.0f}円, 合計: {total_value:,.0f}円"
            except:
                price_stats = "価格統計: エラー"
        else:
            price_stats = "価格統計: なし"
        
        stats_text = f"統計: {total_items}件, {q_stats}, {price_stats}"
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
        """SKU生成"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
            
        QMessageBox.information(self, "SKU生成", "SKU生成機能（開発予定）")
        # TODO: 実際のSKU生成ロジックを実装
        
    def export_csv(self):
        """CSV出力"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "出力するデータがありません")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "CSVファイルを保存",
            "inventory_export.csv",
            "CSVファイル (*.csv)"
        )
        
        if file_path:
            try:
                self.filtered_data.to_csv(file_path, index=False, encoding='utf-8')
                QMessageBox.information(self, "出力完了", f"CSVファイルを保存しました:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")
                
    def export_listing_csv(self):
        """出品CSV生成"""
        QMessageBox.information(self, "出品CSV生成", "出品CSV生成機能（開発予定）")
        # TODO: 実際の出品CSV生成ロジックを実装
        
    def generate_antique_register(self):
        """古物台帳生成"""
        QMessageBox.information(self, "古物台帳生成", "古物台帳生成機能（開発予定）")
        # TODO: 実際の古物台帳生成ロジックを実装
