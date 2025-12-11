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
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings
from PySide6.QtGui import QFont, QColor
import pandas as pd
from pathlib import Path
from utils.error_handler import ErrorHandler, validate_csv_file, safe_execute


class NumericTableWidgetItem(QTableWidgetItem):
    """数値ソート用のカスタムTableWidgetItem"""
    
    def __init__(self, value):
        super().__init__()
        self.numeric_value = float(value) if value else 0.0
    
    def __lt__(self, other):
        """小なり演算子をオーバーライドして数値比較を実装"""
        if isinstance(other, NumericTableWidgetItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


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
        self.error_handler = ErrorHandler(self)
        self.settings = QSettings("HIRIO", "DesktopApp")
        
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
        
        # 大量データ対応の最適化
        self.preview_table.setSortingEnabled(True)  # ソート機能を有効化
        self.preview_table.setSelectionBehavior(QTableWidget.SelectRows)  # 行選択
        
        # パフォーマンス向上のための設定
        self.preview_table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.preview_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        
        # 選択変更時の自動スクロール機能
        self.preview_table.itemSelectionChanged.connect(self.on_preview_selection_changed)
        
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
        
        # 大量データ対応の最適化
        self.result_table.setSortingEnabled(True)  # ソート機能を有効化
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)  # 行選択
        
        # パフォーマンス向上のための設定
        self.result_table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.result_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        
        # 選択変更時の自動スクロール機能
        self.result_table.itemSelectionChanged.connect(self.on_result_selection_changed)
        
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
        try:
            # 設定からデフォルトディレクトリを取得
            default_dir = self.settings.value("directories/csv", "")
            
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "CSVファイルを選択",
                default_dir,  # 設定から取得したデフォルトディレクトリを指定
                "CSVファイル (*.csv);;すべてのファイル (*)"
            )
            
            if file_path:
                # CSVファイルのバリデーション
                try:
                    validate_csv_file(file_path)
                    self.csv_path = file_path
                    self.file_path_edit.setText(file_path)
                    self.csv_preview_btn.setEnabled(True)
                    self.preview_btn.setEnabled(True)
                    self.execute_btn.setEnabled(True)
                    
                    # ファイル選択完了後、自動的にCSVプレビューを表示
                    QTimer.singleShot(100, self.show_csv_preview)
                    
                except Exception as e:
                    user_message = self.error_handler.handle_exception(e, "CSVファイル選択")
                    self.error_handler.show_error_dialog(
                        self, 
                        "ファイル選択エラー", 
                        user_message
                    )
                    
        except Exception as e:
            user_message = self.error_handler.handle_exception(e, "ファイル選択ダイアログ")
            self.error_handler.show_error_dialog(
                self, 
                "ファイル選択エラー", 
                user_message
            )
            
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
            # 進捗バーの表示
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.csv_preview_btn.setEnabled(False)
            
            # CSVファイルの読み込み
            from utils.csv_io import csv_io
            df = csv_io.read_csv(self.csv_path)
            
            if df is None:
                QMessageBox.warning(self, "エラー", "CSVファイルの読み込みに失敗しました")
                return
            
            self.progress_bar.setValue(30)
            
            # ソート機能を一時的に無効化（データ投入中はソートしない）
            self.preview_table.setSortingEnabled(False)
            
            # テーブルの設定
            self.preview_table.setRowCount(len(df))
            self.preview_table.setColumnCount(len(df.columns))
            self.preview_table.setHorizontalHeaderLabels(df.columns.tolist())
            
            self.progress_bar.setValue(50)
            
            # データの設定（全行表示）
            for i in range(len(df)):
                row = df.iloc[i]
                for j, value in enumerate(row):
                    # conditionNote列の場合は空文字列にする
                    if df.columns[j].lower() == 'conditionnote':
                        clean_value = ''
                    else:
                        # Excel数式記法のクリーンアップ
                        clean_value = self.clean_excel_formula(str(value))
                        
                        # title列の場合は50文字に制限
                        if df.columns[j].lower() == 'title' and len(clean_value) > 50:
                            clean_value = clean_value[:50] + '...'
                    
                    item = QTableWidgetItem(clean_value)
                    
                    # title列の場合はツールチップで全文を表示
                    if df.columns[j].lower() == 'title':
                        original_value = self.clean_excel_formula(str(value))
                        if len(original_value) > 50:
                            item.setToolTip(original_value)
                    
                    self.preview_table.setItem(i, j, item)
                
                # 大量データの場合、進捗を更新
                if i % 50 == 0:  # 50行ごとに進捗更新
                    progress = 50 + int((i / len(df)) * 40)  # 50-90%の範囲
                    self.progress_bar.setValue(progress)
            
            self.progress_bar.setValue(90)
            
            # データ投入完了後、ソート機能を再有効化
            self.preview_table.setSortingEnabled(True)
            
            # 列幅の自動調整
            self.preview_table.resizeColumnsToContents()
            
            self.progress_bar.setValue(100)
            self.progress_bar.setVisible(False)
            self.csv_preview_btn.setEnabled(True)
            
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.csv_preview_btn.setEnabled(True)
            QMessageBox.warning(self, "エラー", f"CSVファイルの読み込みに失敗しました:\n{str(e)}")
    
    def on_preview_selection_changed(self):
        """プレビューテーブルの選択変更時の処理"""
        try:
            # 選択された行を取得
            selected_items = self.preview_table.selectedItems()
            if not selected_items:
                return
            
            # 最初の選択されたアイテムの行番号を取得
            current_row = selected_items[0].row()
            
            # title列を探す
            title_column = -1
            for j in range(self.preview_table.columnCount()):
                header_item = self.preview_table.horizontalHeaderItem(j)
                if header_item and header_item.text().lower() == 'title':
                    title_column = j
                    break
            
            # title列が見つかった場合、その列にスクロール
            if title_column >= 0:
                # 水平スクロールでtitle列を表示
                self.preview_table.scrollToItem(
                    self.preview_table.item(current_row, title_column),
                    QTableWidget.PositionAtCenter
                )
                
                # title列のセルをハイライト
                for j in range(self.preview_table.columnCount()):
                    item = self.preview_table.item(current_row, j)
                    if item:
                        if j == title_column:
                            # title列は黄色でハイライト
                            item.setBackground(QColor(255, 255, 200))
                        else:
                            # 他の列は通常の背景色
                            item.setBackground(QColor(255, 255, 255))
                            
        except Exception as e:
            print(f"選択変更処理エラー: {e}")
    
    def on_result_selection_changed(self):
        """価格改定結果テーブルの選択変更時の処理"""
        try:
            # 選択された行を取得
            selected_items = self.result_table.selectedItems()
            if not selected_items:
                return
            
            # 最初の選択されたアイテムの行番号を取得
            current_row = selected_items[0].row()
            
            # Title列を探す（価格改定結果では「Title」列）
            title_column = -1
            for j in range(self.result_table.columnCount()):
                header_item = self.result_table.horizontalHeaderItem(j)
                if header_item and header_item.text() == 'Title':
                    title_column = j
                    break
            
            # Title列が見つかった場合、その列にスクロール
            if title_column >= 0:
                # 水平スクロールでTitle列を表示
                self.result_table.scrollToItem(
                    self.result_table.item(current_row, title_column),
                    QTableWidget.PositionAtCenter
                )
                
                # Title列のセルをハイライト
                for j in range(self.result_table.columnCount()):
                    item = self.result_table.item(current_row, j)
                    if item:
                        if j == title_column:
                            # Title列は黄色でハイライト
                            item.setBackground(QColor(255, 255, 200))
                        else:
                            # 他の列は通常の背景色
                            item.setBackground(QColor(255, 255, 255))
                            
        except Exception as e:
            print(f"結果選択変更処理エラー: {e}")
    
    def clean_excel_formula(self, value: str) -> str:
        """Excel数式記法のクリーンアップ"""
        if not value:
            return value
            
        # ="○○" 形式を ○○ に変換
        if value.startswith('="') and value.endswith('"'):
            return value[2:-1]  # =" と " を削除
        
        # ="○○ 形式（終了の"がない場合）を ○○ に変換
        if value.startswith('="'):
            return value[2:]  # =" を削除
        
        # ○○" 形式（開始の="がない場合）を ○○ に変換
        if value.endswith('"') and not value.startswith('="'):
            return value[:-1]  # " を削除
            
        return value
    
    def _format_trace_change(self, price_trace_change):
        """Trace変更の日本語化
        
        マッピング:
        0 = 維持
        1 = FBA状態合わせ
        2 = 状態合わせ
        3 = FBA最安値
        4 = 最安値
        5 = カート価格
        """
        trace_value = int(price_trace_change) if price_trace_change else 0
        
        if trace_value == 0:
            return "維持"
        elif trace_value == 1:
            return "FBA状態合わせ"
        elif trace_value == 2:
            return "状態合わせ"
        elif trace_value == 3:
            return "FBA最安値"
        elif trace_value == 4:
            return "最安値"
        elif trace_value == 5:
            return "カート価格"
        else:
            return f"不明 ({trace_value})"
        
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
            "価格改定を実行しますか？\n※元のCSVファイルは変更されません。結果は別途保存できます。",
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
        
        # 自動保存は行わず、手動保存のみとする
        auto_save_message = "\n自動保存は行っていません。「結果をCSV保存」から手動保存してください。"
        
        QMessageBox.information(
            self, 
            "価格改定完了", 
            f"価格改定が完了しました\n更新行数: {result['summary']['updated_rows']}{auto_save_message}"
        )
        
    def on_repricing_error(self, error_message):
        """価格改定エラー時の処理"""
        self.progress_bar.setVisible(False)
        self.execute_btn.setEnabled(True)
        
        QMessageBox.critical(self, "エラー", f"価格改定に失敗しました:\n{error_message}")
        
    def update_result_table(self, result):
        """結果テーブルの更新"""
        items = result['items']
        
        # ソート機能を一時的に無効化（データ投入中はソートしない）
        self.result_table.setSortingEnabled(False)
        
        # テーブルの設定（必要な列のみ）
        self.result_table.setRowCount(len(items))
        columns = ['SKU', 'ASIN', 'Title', '日数', 'アクション', '理由', '現在価格', '改定価格', 'Trace変更']
        self.result_table.setColumnCount(len(columns))
        self.result_table.setHorizontalHeaderLabels(columns)
        
        # データの設定
        for i, item in enumerate(items):
            # 既存APIレスポンスのキー名に合わせて取得（型変換を追加）
            sku = str(item.get('sku', ''))
            asin = str(item.get('asin', ''))
            title = str(item.get('title', ''))
            days = int(item.get('days', 0)) if item.get('days') is not None else 0
            action = str(item.get('action', ''))
            reason = str(item.get('reason', ''))
            price = float(item.get('price', 0)) if item.get('price') is not None else 0
            new_price = float(item.get('new_price', 0)) if item.get('new_price') is not None else 0
            # priceTraceChangeの安全な型変換
            price_trace_change = 0
            try:
                trace_value = item.get('priceTraceChange', item.get('price_trace_change', 0))
                if trace_value is not None and str(trace_value).strip():
                    # 数値文字列の場合のみfloat変換
                    if str(trace_value).replace('.', '').replace('-', '').isdigit():
                        price_trace_change = float(trace_value)
                    else:
                        # 文字列の場合は0として扱う
                        price_trace_change = 0
            except (ValueError, TypeError):
                price_trace_change = 0
            
            # Trace変更の日本語化
            trace_change_text = self._format_trace_change(price_trace_change)
            
            # Excel数式記法のクリーンアップ
            self.result_table.setItem(i, 0, QTableWidgetItem(self.clean_excel_formula(str(sku))))
            self.result_table.setItem(i, 1, QTableWidgetItem(self.clean_excel_formula(str(asin))))
            
            # Title列の特別処理（50文字制限+ツールチップ）
            title_clean = self.clean_excel_formula(str(title))
            title_display = title_clean[:50] + '...' if len(title_clean) > 50 else title_clean
            title_item = QTableWidgetItem(title_display)
            if len(title_clean) > 50:
                title_item.setToolTip(title_clean)  # ツールチップで全文表示
            self.result_table.setItem(i, 2, title_item)
            
            # 日数列：数値としてソートするためにQt.UserRoleに数値を設定
            days_item = NumericTableWidgetItem(days)
            days_item.setText(self.clean_excel_formula(str(days)))
            self.result_table.setItem(i, 3, days_item)
            
            self.result_table.setItem(i, 4, QTableWidgetItem(self.clean_excel_formula(str(action))))
            self.result_table.setItem(i, 5, QTableWidgetItem(self.clean_excel_formula(str(reason))))
            
            # 価格列：数値としてソートするためにQt.UserRoleに数値を設定
            price_item = NumericTableWidgetItem(price)
            price_item.setText(self.clean_excel_formula(str(price)))
            self.result_table.setItem(i, 6, price_item)
            
            new_price_item = NumericTableWidgetItem(new_price)
            new_price_item.setText(self.clean_excel_formula(str(new_price)))
            self.result_table.setItem(i, 7, new_price_item)
            
            self.result_table.setItem(i, 8, QTableWidgetItem(trace_change_text))
            
            # 価格変更に応じて色分け（型変換を追加）
            try:
                price_float = float(price) if price else 0
                new_price_float = float(new_price) if new_price else 0
                
                if new_price_float > price_float:
                    # 価格上昇：緑色
                    for j in range(9):
                        self.result_table.item(i, j).setBackground(QColor(200, 255, 200))
                elif new_price_float < price_float:
                    # 価格下降：赤色
                    for j in range(9):
                        self.result_table.item(i, j).setBackground(QColor(255, 200, 200))
            except (ValueError, TypeError):
                # 型変換に失敗した場合は色分けをスキップ
                pass
        
        # データ投入完了後、ソート機能を再有効化
        self.result_table.setSortingEnabled(True)
        
        # 列幅の自動調整
        self.result_table.resizeColumnsToContents()
    
    def _get_unique_file_path(self, directory: str, filename: str) -> str:
        """重複しないファイルパスを生成"""
        import os
        
        # ディレクトリとファイル名を分離
        name, ext = os.path.splitext(filename)
        
        # 最初のファイルパス
        file_path = os.path.join(directory, filename)
        
        # ファイルが存在しない場合はそのまま返す
        if not os.path.exists(file_path):
            return file_path
        
        # 重複する場合は番号を付ける
        counter = 1
        while True:
            new_filename = f"{name}({counter}){ext}"
            new_file_path = os.path.join(directory, new_filename)
            
            if not os.path.exists(new_file_path):
                return new_file_path
            
            counter += 1
            
            # 無限ループ防止（最大999まで）
            if counter > 999:
                return file_path
    
    def auto_save_results_to_source_dir(self):
        """元CSVと同じフォルダに自動保存"""
        if not self.repricing_result or not self.csv_path:
            return None
        
        source_path = Path(self.csv_path)
        source_dir = str(source_path.parent)
        auto_filename = f"{source_path.stem}_repriced.csv"
        target_path = self._get_unique_file_path(source_dir, auto_filename)
        return self._write_results_to_csv(target_path)
    
    def save_results(self):
        """結果のCSV保存"""
        if not self.repricing_result:
            QMessageBox.warning(self, "エラー", "保存する結果がありません")
            return
            
        # 設定からデフォルトディレクトリを取得（結果保存用）
        default_dir = self.settings.value("directories/result", "")
        default_filename = "repricing_result.csv"
        
        # 自動リネーム機能付きでファイルパスを生成
        file_path = self._get_unique_file_path(default_dir, default_filename)
        
        # ユーザーに確認（手動選択のオプション付き）
        if file_path:
            reply = QMessageBox.question(
                self,
                "ファイル保存確認",
                f"以下のファイル名で保存しますか？\n{file_path}\n\n「いいえ」を選択すると手動でファイル名を指定できます。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.No:
                # 手動でファイル名を選択
                manual_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "結果をCSV保存（手動選択）",
                    file_path,
                    "CSVファイル (*.csv)"
                )
                if manual_path:
                    file_path = manual_path
                else:
                    return
        
        if file_path:
            try:
                saved_path = self._write_results_to_csv(file_path)
                print(f"[DEBUG CSV保存] 保存完了: {saved_path}")
                QMessageBox.information(self, "保存完了", f"結果を保存しました:\n{saved_path}")
            except Exception as e:
                print(f"[ERROR CSV保存] 保存エラー: {str(e)}")
                print(f"[ERROR CSV保存] エラータイプ: {type(e).__name__}")
                import traceback
                print(f"[ERROR CSV保存] トレースバック: {traceback.format_exc()}")
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")

    def _write_results_to_csv(self, file_path: str) -> str:
        """価格改定結果を指定パスに保存して保存先パスを返す"""
        if not self.repricing_result:
            raise ValueError("保存対象の結果がありません。")
        
        items = self.repricing_result['items']
        print(f"[DEBUG CSV保存] 保存開始: {len(items)}件のアイテム")
        
        # 元ファイルのデータを読み込んで、priceとpriceTraceのみを変更
        from utils.csv_io import csv_io
        original_df = csv_io.read_csv(self.csv_path)
        
        if original_df is None:
            raise RuntimeError("元のCSVファイルを読み込めませんでした")
        
        # 価格改定結果を辞書に変換（SKUをキーとして）
        repricing_dict = {}
        for item in items:
            sku = self.clean_excel_formula(str(item.get('sku', '')))
            
            # 安全な型変換
            try:
                new_price = float(item.get('new_price', 0)) if item.get('new_price') is not None else 0
                new_price = int(new_price) if new_price > 0 else 0
            except (ValueError, TypeError):
                new_price = 0
            
            try:
                trace_value = item.get('priceTraceChange', item.get('price_trace_change', 0))
                if trace_value is not None and str(trace_value).strip():
                    # 数値文字列の場合のみint変換
                    if str(trace_value).replace('.', '').replace('-', '').isdigit():
                        price_trace = int(float(trace_value))
                    else:
                        # 文字列の場合は0として扱う
                        price_trace = 0
                else:
                    price_trace = 0
            except (ValueError, TypeError):
                price_trace = 0
            
            repricing_dict[sku] = {
                'new_price': new_price,
                'price_trace': price_trace
            }
        
        # 元ファイルのデータをコピーして、該当する行のみpriceとpriceTraceを更新
        # 価格やpriceTraceに変更がない場合は除外する
        data = []
        for _, row in original_df.iterrows():
            sku = self.clean_excel_formula(str(row.get('SKU', '')))
            
            # 元の価格とpriceTraceを取得
            original_price = float(row.get('price', 0)) if pd.notna(row.get('price')) else 0
            original_price_trace = float(row.get('priceTrace', 0)) if pd.notna(row.get('priceTrace')) else 0
            
            # 価格改定対象の場合はpriceとpriceTraceを更新
            if sku in repricing_dict:
                new_price = repricing_dict[sku]['new_price']
                new_price_trace = repricing_dict[sku]['price_trace']
                
                # 価格とpriceTraceの両方が変更されていない場合はスキップ（CSVに保存しない）
                if new_price == original_price and new_price_trace == original_price_trace:
                    print(f"[DEBUG CSV保存] スキップ: {sku} (変更なし)")
                    continue
                
                row_data = row.to_dict()
                row_data['price'] = new_price
                row_data['priceTrace'] = new_price_trace
                # conditionNoteは空にする
                row_data['conditionNote'] = ""
                data.append(row_data)
            else:
                # 対象外の場合は元のデータをそのまま使用
                row_data = row.to_dict()
                data.append(row_data)
        
        df = pd.DataFrame(data)
        
        # 元ファイルの書式に完全に合わせるための処理
        # 0. 空の値を保持（nanを空文字に変換）
        df = df.fillna('')  # 全てのnan値を空文字に変換
        # 1. 数値列を文字列として出力（クォート付き）
        numeric_columns = ['number', 'price', 'cost', 'akaji', 'takane', 'condition', 'priceTrace', 'amazon-fee', 'shipping-price', 'profit']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = df[col].astype(str)
                # 文字列変換後もnan値を空文字に変換
                df[col] = df[col].replace('nan', '')
        
        # 2. Excel数式記法の修正（プライスター対応）
        text_columns = ['SKU', 'ASIN', 'title', 'conditionNote', 'leadtime', 'add-delete']
        for col in text_columns:
            if col in df.columns:
                try:
                    # 文字列型に変換
                    df[col] = df[col].astype(str)
                    # nan値を空文字に変換
                    df[col] = df[col].replace('nan', '')
                    # Excel数式記法をプライスター形式に変換
                    df[col] = df[col].str.replace(r'^"(.+)"$', r'=\1', regex=True)  # "値" → =値
                except Exception as e:
                    print(f"[WARNING CSV保存] 列 {col} の処理でエラー: {e}")
                    # エラーが発生した場合は文字列型に変換するだけ
                    df[col] = df[col].astype(str)
                    df[col] = df[col].replace('nan', '')
        
        # 3. Shift-JISでエンコードできない文字の置換処理
        def clean_for_shift_jis(text):
            """Shift-JISでエンコードできない文字を置換"""
            if pd.isna(text) or text == '':
                return text
            
            # 文字列に変換
            text = str(text)
            
            # Shift-JISでエンコードできない文字の置換
            replacements = {
                '\uff5e': '~',  # 全角チルダ → 半角チルダ
                '\uff0d': '-',  # 全角ハイフン → 半角ハイフン
                '\uff0c': ',',  # 全角カンマ → 半角カンマ
                '\uff1a': ':',  # 全角コロン → 半角コロン
                '\uff1b': ';',  # 全角セミコロン → 半角セミコロン
                '\uff01': '!',  # 全角エクスクラメーション → 半角
                '\uff1f': '?',  # 全角クエスチョン → 半角
                '\uff08': '(',  # 全角括弧 → 半角括弧
                '\uff09': ')',  # 全角括弧 → 半角括弧
                '\uff3b': '[',  # 全角角括弧 → 半角角括弧
                '\uff3d': ']',  # 全角角括弧 → 半角角括弧
                '\uff5b': '{',  # 全角波括弧 → 半角波括弧
                '\uff5d': '}',  # 全角波括弧 → 半角波括弧
                '\uff0a': '\n',  # 全角改行 → 半角改行
                '\uff20': '@',  # 全角アットマーク → 半角アットマーク
                '\uff23': '#',  # 全角シャープ → 半角シャープ
                '\uff24': '$',  # 全角ドル → 半角ドル
                '\uff25': '%',  # 全角パーセント → 半角パーセント
                '\uff26': '&',  # 全角アンパサンド → 半角アンパサンド
                '\uff2a': '*',  # 全角アスタリスク → 半角アスタリスク
                '\uff2b': '+',  # 全角プラス → 半角プラス
                '\uff2e': '.',  # 全角ピリオド → 半角ピリオド
                '\uff2f': '/',  # 全角スラッシュ → 半角スラッシュ
                '\uff3c': '<',  # 全角小なり → 半角小なり
                '\uff3e': '>',  # 全角大なり → 半角大なり
                '\uff3f': '_',  # 全角アンダースコア → 半角アンダースコア
                '\uff40': '`',  # 全角バッククォート → 半角バッククォート
                '\uff5c': '|',  # 全角パイプ → 半角パイプ
            }
            
            for full_width, half_width in replacements.items():
                text = text.replace(full_width, half_width)
            
            return text
        
        # テキスト列の文字置換処理
        text_columns = ['SKU', 'ASIN', 'title', 'conditionNote', 'leadtime', 'add-delete']
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].apply(clean_for_shift_jis)
        
        # 4. 元ファイルと同じ形式でCSV保存（プライスター対応）
        from desktop.utils.file_naming import resolve_unique_path
        target = resolve_unique_path(Path(file_path))
        try:
            df.to_csv(str(target), index=False, encoding='shift_jis', quoting=0)  # Shift-JIS、クォートなし
        except UnicodeEncodeError as e:
            # Shift-JISでエンコードできない文字が残っている場合の追加処理
            print(f"[WARNING CSV保存] Shift-JISエンコードエラー: {e}")
            print(f"[WARNING CSV保存] エラー文字を除去して再試行...")
            
            # エラーが発生した列を特定して処理
            for col in df.columns:
                try:
                    # 各列をShift-JISでエンコードテスト
                    df[col].astype(str).str.encode('shift_jis')
                except UnicodeEncodeError:
                    # エラーが発生した列の文字を安全な文字に置換
                    df[col] = df[col].astype(str).str.encode('shift_jis', errors='replace').str.decode('shift_jis')
            
            # 再試行（連番解決後のパスで）
            target = resolve_unique_path(Path(file_path))
            df.to_csv(str(target), index=False, encoding='shift_jis', quoting=0)
        
        return str(target)
