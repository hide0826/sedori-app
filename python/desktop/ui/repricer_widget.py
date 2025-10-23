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
    
    def __init__(self, csv_path, api_client, is_preview=True):
        super().__init__()
        self.csv_path = csv_path
        self.api_client = api_client
        self.is_preview = is_preview
        
    def run(self):
        """価格改定処理の実行"""
        try:
            # 進捗更新
            self.progress_updated.emit(10)
            
            # API接続確認
            if not self.api_client.test_connection():
                raise Exception("FastAPIサーバーに接続できません。サーバーが起動しているか確認してください。")
            
            self.progress_updated.emit(20)
            
            # 実際のAPI呼び出し
            if self.is_preview:
                result = self.api_client.repricer_preview(self.csv_path)
            else:
                result = self.api_client.repricer_apply(self.csv_path)
            
            self.progress_updated.emit(100)
            
            # 結果を返す
            self.result_ready.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(str(e))


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
        file_group.setMaximumHeight(80)  # 高さを制限
        file_layout = QHBoxLayout(file_group)
        file_layout.setContentsMargins(5, 5, 5, 5)  # マージンを小さく
        
        # ファイルパス表示
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("CSVファイルを選択してください")
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setMaximumHeight(30)  # 高さを制限
        file_layout.addWidget(self.file_path_edit)
        
        # ファイル選択ボタン
        self.select_file_btn = QPushButton("ファイル選択")
        self.select_file_btn.clicked.connect(self.select_csv_file)
        self.select_file_btn.setMaximumHeight(30)  # 高さを制限
        file_layout.addWidget(self.select_file_btn)
        
        # CSV内容プレビューボタン
        self.csv_preview_btn = QPushButton("CSV内容表示")
        self.csv_preview_btn.clicked.connect(self.show_csv_preview)
        self.csv_preview_btn.setEnabled(False)
        self.csv_preview_btn.setMaximumHeight(30)  # 高さを制限
        file_layout.addWidget(self.csv_preview_btn)
        
        # 価格改定プレビューボタン
        self.preview_btn = QPushButton("価格改定プレビュー")
        self.preview_btn.clicked.connect(self.preview_csv)
        self.preview_btn.setEnabled(False)
        self.preview_btn.setMaximumHeight(30)  # 高さを制限
        file_layout.addWidget(self.preview_btn)
        
        self.layout().addWidget(file_group)
        
    def setup_content_area(self):
        """コンテンツエリアの設定"""
        # 3段構成：CSVプレビュー（上段）→ 価格改定結果（下段）
        
        # 上段：CSVプレビュー（横に大きく）
        self.setup_preview_area_full_width()
        
        # 下段：価格改定結果
        self.setup_result_area_full_width()
    
    def setup_preview_area_full_width(self):
        """CSVプレビューエリアの設定（全幅）"""
        preview_group = QGroupBox("CSVプレビュー")
        preview_layout = QVBoxLayout(preview_group)
        
        # プレビューテーブル
        self.preview_table = QTableWidget()
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setMinimumHeight(200)  # 適度な高さを設定
        preview_layout.addWidget(self.preview_table)
        
        self.layout().addWidget(preview_group)
    
    def setup_result_area_full_width(self):
        """価格改定結果エリアの設定（全幅）"""
        result_group = QGroupBox("価格改定結果")
        result_layout = QVBoxLayout(result_group)
        
        # 結果テーブル
        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.setMinimumHeight(200)  # 適度な高さを設定
        result_layout.addWidget(self.result_table)
        
        self.layout().addWidget(result_group)
        
        
    def setup_action_buttons(self):
        """アクションボタンエリアの設定"""
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(5, 5, 5, 5)  # マージンを小さく
        
        # 価格改定実行ボタン
        self.execute_btn = QPushButton("価格改定実行")
        self.execute_btn.clicked.connect(self.execute_repricing)
        self.execute_btn.setEnabled(False)
        self.execute_btn.setMaximumHeight(35)  # 高さを制限
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
        self.progress_bar.setMaximumHeight(25)  # 高さを制限
        button_layout.addWidget(self.progress_bar)
        
        # 結果保存ボタン
        self.save_btn = QPushButton("結果をCSV保存")
        self.save_btn.clicked.connect(self.save_results)
        self.save_btn.setEnabled(False)
        self.save_btn.setMaximumHeight(35)  # 高さを制限
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
            self.csv_preview_btn.setEnabled(True)
            self.preview_btn.setEnabled(True)
            self.execute_btn.setEnabled(True)
            
    def preview_csv(self):
        """CSVファイルのプレビュー（価格改定プレビュー）"""
        if not self.csv_path:
            return
            
        # 進捗バーの表示
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.preview_btn.setEnabled(False)
        
        # ワーカースレッドの作成と実行（プレビューモード）
        self.worker = RepricerWorker(self.csv_path, self.api_client, is_preview=True)
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.result_ready.connect(self.on_preview_completed)
        self.worker.error_occurred.connect(self.on_preview_error)
        self.worker.start()
        
    def show_csv_preview(self):
        """CSVファイルの内容プレビュー"""
        if not self.csv_path:
            return
            
        try:
            # CSVファイルの読み込み
            from utils.csv_io import csv_io
            df = csv_io.read_csv(self.csv_path)
            
            if df is None:
                QMessageBox.warning(self, "エラー", "CSVファイルの読み込みに失敗しました")
                return
            
            # テーブルの設定
            self.preview_table.setRowCount(len(df))
            self.preview_table.setColumnCount(len(df.columns))
            self.preview_table.setHorizontalHeaderLabels(df.columns.tolist())
            
            # データの設定（最初の100行のみ表示）
            display_rows = min(100, len(df))
            for i in range(display_rows):
                row = df.iloc[i]
                for j, value in enumerate(row):
                    item = QTableWidgetItem(str(value))
                    self.preview_table.setItem(i, j, item)
            
            # 列幅の自動調整
            self.preview_table.resizeColumnsToContents()
            
            QMessageBox.information(
                self, 
                "CSVプレビュー完了", 
                f"CSVファイルを読み込みました\n行数: {len(df)}, 列数: {len(df.columns)}\n（表示: 最初の{display_rows}行）"
            )
            
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"CSVファイルの読み込みに失敗しました:\n{str(e)}")
        
    def on_preview_completed(self, result):
        """プレビュー完了時の処理"""
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        
        # 結果テーブルの更新
        self.update_result_table(result)
        
        QMessageBox.information(
            self, 
            "プレビュー完了", 
            f"価格改定プレビューが完了しました\n更新予定行数: {result['summary']['updated_rows']}"
        )
        
    def on_preview_error(self, error_message):
        """プレビューエラー時の処理"""
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        
        QMessageBox.critical(self, "エラー", f"プレビューに失敗しました:\n{error_message}")
            
    def execute_repricing(self):
        """価格改定の実行"""
        if not self.csv_path:
            QMessageBox.warning(self, "エラー", "CSVファイルを選択してください")
            return
            
        # 確認ダイアログ
        reply = QMessageBox.question(
            self, 
            "価格改定実行確認", 
            "価格改定を実行しますか？\nこの操作は元のCSVファイルを変更します。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
            
        # 進捗バーの表示
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.execute_btn.setEnabled(False)
        
        # ワーカースレッドの作成と実行（実行モード）
        self.worker = RepricerWorker(self.csv_path, self.api_client, is_preview=False)
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
            # 既存APIレスポンスのキー名に合わせて取得
            sku = item.get('sku', '')
            days = item.get('days', 0)
            action = item.get('action', '')
            reason = item.get('reason', '')
            price = item.get('price', 0)
            new_price = item.get('new_price', 0)
            price_trace_change = item.get('priceTraceChange', item.get('price_trace_change', 0))
            
            self.result_table.setItem(i, 0, QTableWidgetItem(str(sku)))
            self.result_table.setItem(i, 1, QTableWidgetItem(str(days)))
            self.result_table.setItem(i, 2, QTableWidgetItem(str(action)))
            self.result_table.setItem(i, 3, QTableWidgetItem(str(reason)))
            self.result_table.setItem(i, 4, QTableWidgetItem(str(price)))
            self.result_table.setItem(i, 5, QTableWidgetItem(str(new_price)))
            self.result_table.setItem(i, 6, QTableWidgetItem(str(price_trace_change)))
            
            # 価格変更に応じて色分け
            if new_price > price:
                # 価格上昇：緑色
                for j in range(7):
                    self.result_table.item(i, j).setBackground(QColor(200, 255, 200))
            elif new_price < price:
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
                items = self.repricing_result['items']
                
                # 既存APIレスポンス形式に合わせたデータフレーム作成
                data = []
                for item in items:
                    data.append({
                        'SKU': item.get('sku', ''),
                        '日数': item.get('days', 0),
                        'アクション': item.get('action', ''),
                        '理由': item.get('reason', ''),
                        '現在価格': item.get('price', 0),
                        '改定後価格': item.get('new_price', 0),
                        'Trace変更': item.get('priceTraceChange', item.get('price_trace_change', 0))
                    })
                
                df = pd.DataFrame(data)
                df.to_csv(file_path, index=False, encoding='utf-8')
                
                QMessageBox.information(self, "保存完了", f"結果を保存しました:\n{file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")
