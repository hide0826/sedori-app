#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古物台帳ウィジェット

古物台帳の生成・表示・エクスポート機能
- 日付範囲選択
- フィルタ機能
- テーブル表示
- CSV/Excel出力
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QDateEdit, QSpinBox,
    QFileDialog, QProgressBar, QTextEdit
)
from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtGui import QFont, QColor
import pandas as pd
from pathlib import Path
import datetime


class AntiqueWorker(QThread):
    """古物台帳生成のワーカースレッド"""
    progress_updated = Signal(int)
    result_ready = Signal(dict)
    error_occurred = Signal(str)
    
    def __init__(self, start_date, end_date, api_client):
        super().__init__()
        self.start_date = start_date
        self.end_date = end_date
        self.api_client = api_client
        
    def run(self):
        """古物台帳生成処理の実行"""
        try:
            # 進捗更新
            self.progress_updated.emit(10)
            
            # API接続確認
            if not self.api_client.test_connection():
                raise Exception("FastAPIサーバーに接続できません。サーバーが起動しているか確認してください。")
            
            self.progress_updated.emit(30)
            
            # 古物台帳生成API呼び出し
            result = self.api_client.antique_register_generate(self.start_date, self.end_date)
            
            self.progress_updated.emit(100)
            
            # 結果を返す
            self.result_ready.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(str(e))


class AntiqueWidget(QWidget):
    """古物台帳ウィジェット"""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.antique_data = None
        
        # UIの初期化
        self.setup_ui()
        
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：日付範囲選択エリア
        self.setup_date_range_selection()
        
        # 中央：フィルタエリア
        self.setup_filter_area()
        
        # 下部：データテーブルエリア
        self.setup_data_table()
        
        # 最下部：アクションボタンエリア
        self.setup_action_buttons()
        
    def setup_date_range_selection(self):
        """日付範囲選択エリアの設定"""
        date_group = QGroupBox("日付範囲選択")
        date_layout = QHBoxLayout(date_group)
        
        # 開始日
        start_label = QLabel("開始日:")
        date_layout.addWidget(start_label)
        
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setDate(QDate.currentDate().addDays(-30))  # 30日前をデフォルト
        self.start_date_edit.setCalendarPopup(True)
        date_layout.addWidget(self.start_date_edit)
        
        # 終了日
        end_label = QLabel("終了日:")
        date_layout.addWidget(end_label)
        
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setDate(QDate.currentDate())  # 今日をデフォルト
        self.end_date_edit.setCalendarPopup(True)
        date_layout.addWidget(self.end_date_edit)
        
        # 古物台帳生成ボタン
        self.generate_btn = QPushButton("古物台帳生成")
        self.generate_btn.clicked.connect(self.generate_antique_register)
        self.generate_btn.setStyleSheet("""
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
        date_layout.addWidget(self.generate_btn)
        
        date_layout.addStretch()
        
        self.layout().addWidget(date_group)
        
    def setup_filter_area(self):
        """フィルタエリアの設定"""
        filter_group = QGroupBox("フィルタ")
        filter_layout = QHBoxLayout(filter_group)
        
        # 検索ボックス
        search_label = QLabel("検索:")
        filter_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("商品名、SKU、ASINで検索...")
        self.search_edit.textChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.search_edit)
        
        # 価格範囲フィルタ
        price_label = QLabel("価格範囲:")
        filter_layout.addWidget(price_label)
        
        self.min_price_spin = QSpinBox()
        self.min_price_spin.setRange(0, 999999)
        self.min_price_spin.setValue(0)
        self.min_price_spin.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.min_price_spin)
        
        price_to_label = QLabel("〜")
        filter_layout.addWidget(price_to_label)
        
        self.max_price_spin = QSpinBox()
        self.max_price_spin.setRange(0, 999999)
        self.max_price_spin.setValue(999999)
        self.max_price_spin.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.max_price_spin)
        
        # フィルタリセットボタン
        self.reset_filters_btn = QPushButton("フィルタリセット")
        self.reset_filters_btn.clicked.connect(self.reset_filters)
        filter_layout.addWidget(self.reset_filters_btn)
        
        filter_layout.addStretch()
        
        self.layout().addWidget(filter_group)
        
    def setup_data_table(self):
        """データテーブルエリアの設定"""
        # テーブルウィジェットの作成
        self.data_table = QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        # ヘッダーの設定
        header = self.data_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        # 古物台帳の列定義
        self.column_headers = [
            "SKU", "商品名", "ASIN", "JAN", "仕入日", "店舗", 
            "価格", "原価", "利益", "出品日", "売上日", "備考"
        ]
        
        self.data_table.setColumnCount(len(self.column_headers))
        self.data_table.setHorizontalHeaderLabels(self.column_headers)
        
        # テーブルをレイアウトに追加
        self.layout().addWidget(self.data_table)
        
    def setup_action_buttons(self):
        """アクションボタンエリアの設定"""
        action_layout = QHBoxLayout()
        
        # CSV出力ボタン
        self.export_csv_btn = QPushButton("CSV出力")
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.setStyleSheet("""
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
        action_layout.addWidget(self.export_csv_btn)
        
        # Excel出力ボタン
        self.export_excel_btn = QPushButton("Excel出力")
        self.export_excel_btn.clicked.connect(self.export_excel)
        self.export_excel_btn.setEnabled(False)
        action_layout.addWidget(self.export_excel_btn)
        
        # データクリアボタン
        self.clear_btn = QPushButton("データクリア")
        self.clear_btn.clicked.connect(self.clear_data)
        self.clear_btn.setEnabled(False)
        action_layout.addWidget(self.clear_btn)
        
        action_layout.addStretch()
        
        # 統計情報表示
        self.stats_label = QLabel("統計: なし")
        action_layout.addWidget(self.stats_label)
        
        # 進捗バー
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(25)
        action_layout.addWidget(self.progress_bar)
        
        self.layout().addLayout(action_layout)
        
    def generate_antique_register(self):
        """古物台帳の生成"""
        # 日付の取得
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        
        # 日付の妥当性チェック
        if start_date > end_date:
            QMessageBox.warning(self, "エラー", "開始日は終了日より前である必要があります")
            return
            
        # 進捗バーの表示
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.generate_btn.setEnabled(False)
        
        # ワーカースレッドの作成と実行
        self.worker = AntiqueWorker(start_date, end_date, self.api_client)
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.result_ready.connect(self.on_generation_completed)
        self.worker.error_occurred.connect(self.on_generation_error)
        self.worker.start()
        
    def on_generation_completed(self, result):
        """古物台帳生成完了時の処理"""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        
        if result['status'] == 'success':
            # データの保存
            self.antique_data = result['items']
            
            # テーブルの更新
            self.update_table()
            
            # ボタンの有効化
            self.export_csv_btn.setEnabled(True)
            self.export_excel_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
            
            # 統計情報の更新
            self.update_stats(result)
            
            QMessageBox.information(
                self, 
                "古物台帳生成完了", 
                f"古物台帳生成が完了しました\n期間: {result['period']}\n件数: {result['total_items']}件\n合計金額: {result['total_value']:,}円"
            )
        else:
            QMessageBox.warning(self, "古物台帳生成失敗", "古物台帳生成に失敗しました")
            
    def on_generation_error(self, error_message):
        """古物台帳生成エラー時の処理"""
        self.progress_bar.setVisible(False)
        self.generate_btn.setEnabled(True)
        
        QMessageBox.critical(self, "エラー", f"古物台帳生成に失敗しました:\n{error_message}")
        
    def update_table(self):
        """テーブルの更新"""
        if self.antique_data is None:
            return
            
        # テーブルの設定
        self.data_table.setRowCount(len(self.antique_data))
        
        # データの設定
        for i, item in enumerate(self.antique_data):
            for j, column in enumerate(self.column_headers):
                value = str(item.get(column, ""))
                item_widget = QTableWidgetItem(value)
                
                # 価格列の数値フォーマット
                if column in ["価格", "原価", "利益"] and value.replace(".", "").isdigit():
                    try:
                        num_value = float(value)
                        item_widget.setText(f"{num_value:,.0f}")
                    except:
                        pass
                
                self.data_table.setItem(i, j, item_widget)
        
        # 列幅の自動調整
        self.data_table.resizeColumnsToContents()
        
    def apply_filters(self):
        """フィルタの適用"""
        if self.antique_data is None:
            return
            
        # 検索条件
        search_text = self.search_edit.text().lower()
        
        # 価格範囲フィルタ
        min_price = self.min_price_spin.value()
        max_price = self.max_price_spin.value()
        
        # フィルタの適用
        filtered_data = []
        for item in self.antique_data:
            # 検索フィルタ
            if search_text:
                search_match = (
                    search_text in str(item.get("商品名", "")).lower() or
                    search_text in str(item.get("SKU", "")).lower() or
                    search_text in str(item.get("ASIN", "")).lower()
                )
                if not search_match:
                    continue
            
            # 価格範囲フィルタ
            try:
                price = float(item.get("価格", 0))
                if price < min_price or price > max_price:
                    continue
            except:
                pass
            
            filtered_data.append(item)
        
        # フィルタ結果でテーブルを更新
        self.update_table_with_filtered_data(filtered_data)
        
    def update_table_with_filtered_data(self, filtered_data):
        """フィルタ結果でテーブルを更新"""
        # テーブルの設定
        self.data_table.setRowCount(len(filtered_data))
        
        # データの設定
        for i, item in enumerate(filtered_data):
            for j, column in enumerate(self.column_headers):
                value = str(item.get(column, ""))
                item_widget = QTableWidgetItem(value)
                
                # 価格列の数値フォーマット
                if column in ["価格", "原価", "利益"] and value.replace(".", "").isdigit():
                    try:
                        num_value = float(value)
                        item_widget.setText(f"{num_value:,.0f}")
                    except:
                        pass
                
                self.data_table.setItem(i, j, item_widget)
        
        # 列幅の自動調整
        self.data_table.resizeColumnsToContents()
        
    def reset_filters(self):
        """フィルタのリセット"""
        self.search_edit.clear()
        self.min_price_spin.setValue(0)
        self.max_price_spin.setValue(999999)
        
        # 元のデータでテーブルを更新
        if self.antique_data:
            self.update_table()
            
    def update_stats(self, result=None):
        """統計情報の更新"""
        if self.antique_data is None:
            self.stats_label.setText("統計: なし")
            return
            
        # 基本統計
        total_items = len(self.antique_data)
        
        # 価格統計
        try:
            prices = [float(item.get("価格", 0)) for item in self.antique_data if item.get("価格")]
            if prices:
                avg_price = sum(prices) / len(prices)
                total_value = sum(prices)
                price_stats = f"平均価格: {avg_price:,.0f}円, 合計: {total_value:,.0f}円"
            else:
                price_stats = "価格統計: なし"
        except:
            price_stats = "価格統計: エラー"
        
        stats_text = f"統計: {total_items}件, {price_stats}"
        self.stats_label.setText(stats_text)
        
    def clear_data(self):
        """データのクリア"""
        self.antique_data = None
        self.data_table.setRowCount(0)
        
        # ボタンの無効化
        self.export_csv_btn.setEnabled(False)
        self.export_excel_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        
        # 表示のクリア
        self.stats_label.setText("統計: なし")
        
    def export_csv(self):
        """CSV出力"""
        if self.antique_data is None:
            QMessageBox.warning(self, "エラー", "出力するデータがありません")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "古物台帳CSVファイルを保存",
            f"antique_register_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSVファイル (*.csv)"
        )
        
        if file_path:
            try:
                # データフレームの作成
                df = pd.DataFrame(self.antique_data)
                from pathlib import Path
                from desktop.utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(file_path))
                df.to_csv(str(target), index=False, encoding='utf-8')
                
                QMessageBox.information(self, "出力完了", f"CSVファイルを保存しました:\n{str(target)}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")
                
    def export_excel(self):
        """Excel出力"""
        if self.antique_data is None:
            QMessageBox.warning(self, "エラー", "出力するデータがありません")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "古物台帳Excelファイルを保存",
            f"antique_register_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            "Excelファイル (*.xlsx)"
        )
        
        if file_path:
            try:
                # データフレームの作成
                df = pd.DataFrame(self.antique_data)
                from pathlib import Path
                from desktop.utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(file_path))
                df.to_excel(str(target), index=False, engine='openpyxl')
                
                QMessageBox.information(self, "出力完了", f"Excelファイルを保存しました:\n{str(target)}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")
