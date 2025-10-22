#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
価格改定ウィジェット

CSV選択 → プレビュー → 価格改定実行 → 結果表示
既存FastAPIの価格改定機能を活用
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QTextEdit, QGroupBox, QSplitter,
    QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor
import pandas as pd
from pathlib import Path


class RepricerWorker(QThread):
    """価格改定処理のワーカースレッド"""
    progress_updated = Signal(int)
    result_ready = Signal(dict)
    error_occurred = Signal(str)
    
    def __init__(self, csv_path, api_client):
        super().__init__()
        self.csv_path = csv_path
        self.api_client = api_client
        
    def run(self):
        """価格改定処理の実行"""
        try:
            # 進捗更新
            self.progress_updated.emit(10)
            
            # CSVファイルの読み込み
            df = pd.read_csv(self.csv_path, encoding='utf-8')
            self.progress_updated.emit(30)
            
            # ダミーの価格改定処理（実際はAPI呼び出し）
            result = self.simulate_repricing(df)
            self.progress_updated.emit(100)
            
            # 結果を返す
            self.result_ready.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(str(e))
    
    def simulate_repricing(self, df):
        """価格改定のシミュレーション（ダミー実装）"""
        import random
        import datetime
        
        items = []
        for i, row in df.iterrows():
            # ダミーデータの生成
            days = random.randint(30, 365)
            current_price = random.randint(1000, 10000)
            price_change = random.randint(-500, 500)
            new_price = max(100, current_price + price_change)
            
            item = {
                'sku': f"20250101-{row.get('ASIN', 'UNKNOWN')}-{i+1:04d}",
                'days': days,
                'action': 'price_down_1' if price_change < 0 else 'price_up_1',
                'reason': f"Rule for {days} days ({'price_down_1' if price_change < 0 else 'price_up_1'})",
                'price': current_price,
                'new_price': new_price,
                'priceTrace': 0,
                'new_priceTrace': 0
            }
            items.append(item)
        
        return {
            'summary': {
                'updated_rows': len(items),
                'excluded_rows': 0,
                'q4_switched': 0,
                'date_unknown': 0,
                'log_rows': len(items)
            },
            'items': items
        }


class RepricerWidget(QWidget):
    """価格改定ウィジェット"""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.csv_path = None
        self.repricing_result = None
        
        # UIの初期化
        self.setup_ui()
        
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：ファイル選択エリア
        self.setup_file_selection()
        
        # 中央：プレビューと結果表示エリア
        self.setup_content_area()
        
        # 下部：実行ボタンエリア
        self.setup_action_buttons()
        
    def setup_file_selection(self):
        """ファイル選択エリアの設定"""
        file_group = QGroupBox("CSVファイル選択")
        file_layout = QHBoxLayout(file_group)
        
        # ファイルパス表示
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("CSVファイルを選択してください")
        self.file_path_edit.setReadOnly(True)
        file_layout.addWidget(self.file_path_edit)
        
        # ファイル選択ボタン
        self.select_file_btn = QPushButton("ファイル選択")
        self.select_file_btn.clicked.connect(self.select_csv_file)
        file_layout.addWidget(self.select_file_btn)
        
        # プレビューボタン
        self.preview_btn = QPushButton("プレビュー")
        self.preview_btn.clicked.connect(self.preview_csv)
        self.preview_btn.setEnabled(False)
        file_layout.addWidget(self.preview_btn)
        
        self.layout().addWidget(file_group)
        
    def setup_content_area(self):
        """コンテンツエリアの設定"""
        # スプリッターでプレビューと結果を分割
        splitter = QSplitter(Qt.Horizontal)
        
        # 左側：プレビューエリア
        self.setup_preview_area(splitter)
        
        # 右側：結果表示エリア
        self.setup_result_area(splitter)
        
        # スプリッターの比率設定
        splitter.setSizes([400, 600])
        
        self.layout().addWidget(splitter)
        
    def setup_preview_area(self, parent):
        """プレビューエリアの設定"""
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        
        # プレビューラベル
        preview_label = QLabel("CSVプレビュー")
        preview_label.setFont(QFont("", 10, QFont.Bold))
        preview_layout.addWidget(preview_label)
        
        # プレビューテーブル
        self.preview_table = QTableWidget()
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        preview_layout.addWidget(self.preview_table)
        
        parent.addWidget(preview_widget)
        
    def setup_result_area(self, parent):
        """結果表示エリアの設定"""
        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        
        # 結果ラベル
        result_label = QLabel("価格改定結果")
        result_label.setFont(QFont("", 10, QFont.Bold))
        result_layout.addWidget(result_label)
        
        # 結果テーブル
        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        result_layout.addWidget(self.result_table)
        
        parent.addWidget(result_widget)
        
    def setup_action_buttons(self):
        """アクションボタンエリアの設定"""
        button_layout = QHBoxLayout()
        
        # 価格改定実行ボタン
        self.execute_btn = QPushButton("価格改定実行")
        self.execute_btn.clicked.connect(self.execute_repricing)
        self.execute_btn.setEnabled(False)
        self.execute_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        button_layout.addWidget(self.execute_btn)
        
        # 進捗バー
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        button_layout.addWidget(self.progress_bar)
        
        # 結果保存ボタン
        self.save_btn = QPushButton("結果をCSV保存")
        self.save_btn.clicked.connect(self.save_results)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        button_layout.addStretch()
        
        self.layout().addLayout(button_layout)
        
    def select_csv_file(self):
        """CSVファイルの選択"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "CSVファイルを選択",
            "",
            "CSVファイル (*.csv);;すべてのファイル (*)"
        )
        
        if file_path:
            self.csv_path = file_path
            self.file_path_edit.setText(file_path)
            self.preview_btn.setEnabled(True)
            self.execute_btn.setEnabled(True)
            
    def preview_csv(self):
        """CSVファイルのプレビュー"""
        if not self.csv_path:
            return
            
        try:
            # CSVファイルの読み込み
            df = pd.read_csv(self.csv_path, encoding='utf-8')
            
            # テーブルの設定
            self.preview_table.setRowCount(len(df))
            self.preview_table.setColumnCount(len(df.columns))
            self.preview_table.setHorizontalHeaderLabels(df.columns.tolist())
            
            # データの設定
            for i, row in df.iterrows():
                for j, value in enumerate(row):
                    item = QTableWidgetItem(str(value))
                    self.preview_table.setItem(i, j, item)
            
            # 列幅の自動調整
            self.preview_table.resizeColumnsToContents()
            
            QMessageBox.information(self, "プレビュー完了", f"CSVファイルを読み込みました（{len(df)}行）")
            
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"CSVファイルの読み込みに失敗しました:\n{str(e)}")
            
    def execute_repricing(self):
        """価格改定の実行"""
        if not self.csv_path:
            QMessageBox.warning(self, "エラー", "CSVファイルを選択してください")
            return
            
        # 進捗バーの表示
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.execute_btn.setEnabled(False)
        
        # ワーカースレッドの作成と実行
        self.worker = RepricerWorker(self.csv_path, self.api_client)
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.result_ready.connect(self.on_repricing_completed)
        self.worker.error_occurred.connect(self.on_repricing_error)
        self.worker.start()
        
    def on_repricing_completed(self, result):
        """価格改定完了時の処理"""
        self.repricing_result = result
        self.progress_bar.setVisible(False)
        self.execute_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        
        # 結果テーブルの更新
        self.update_result_table(result)
        
        QMessageBox.information(
            self, 
            "価格改定完了", 
            f"価格改定が完了しました\n更新行数: {result['summary']['updated_rows']}"
        )
        
    def on_repricing_error(self, error_message):
        """価格改定エラー時の処理"""
        self.progress_bar.setVisible(False)
        self.execute_btn.setEnabled(True)
        
        QMessageBox.critical(self, "エラー", f"価格改定に失敗しました:\n{error_message}")
        
    def update_result_table(self, result):
        """結果テーブルの更新"""
        items = result['items']
        
        # テーブルの設定
        self.result_table.setRowCount(len(items))
        columns = ['SKU', '日数', 'アクション', '理由', '現在価格', '改定後価格', 'Trace変更']
        self.result_table.setColumnCount(len(columns))
        self.result_table.setHorizontalHeaderLabels(columns)
        
        # データの設定
        for i, item in enumerate(items):
            self.result_table.setItem(i, 0, QTableWidgetItem(item['sku']))
            self.result_table.setItem(i, 1, QTableWidgetItem(str(item['days'])))
            self.result_table.setItem(i, 2, QTableWidgetItem(item['action']))
            self.result_table.setItem(i, 3, QTableWidgetItem(item['reason']))
            self.result_table.setItem(i, 4, QTableWidgetItem(str(item['price'])))
            self.result_table.setItem(i, 5, QTableWidgetItem(str(item['new_price'])))
            self.result_table.setItem(i, 6, QTableWidgetItem(str(item['new_priceTrace'])))
            
            # 価格変更に応じて色分け
            if item['new_price'] > item['price']:
                # 価格上昇：緑色
                for j in range(7):
                    self.result_table.item(i, j).setBackground(QColor(200, 255, 200))
            elif item['new_price'] < item['price']:
                # 価格下降：赤色
                for j in range(7):
                    self.result_table.item(i, j).setBackground(QColor(255, 200, 200))
        
        # 列幅の自動調整
        self.result_table.resizeColumnsToContents()
        
    def save_results(self):
        """結果のCSV保存"""
        if not self.repricing_result:
            QMessageBox.warning(self, "エラー", "保存する結果がありません")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "結果をCSV保存",
            "repricing_result.csv",
            "CSVファイル (*.csv)"
        )
        
        if file_path:
            try:
                # 結果をCSVファイルに保存
                df = pd.DataFrame(self.repricing_result['items'])
                df.to_csv(file_path, index=False, encoding='utf-8')
                
                QMessageBox.information(self, "保存完了", f"結果を保存しました:\n{file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")
