
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QTextEdit, QGroupBox, QSplitter, QApplication,
    QMessageBox, QFrame, QMenu, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices

try:
    from ui.utils.draggable_file_icon import DraggableFileIconWidget
except ImportError:
    from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget  # type: ignore

try:
    from ui.utils.browser_front_scheduler import schedule_bring_browser_to_front
except ImportError:
    from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front  # type: ignore

import pandas as pd
from pathlib import Path
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from utils.error_handler import ErrorHandler, validate_csv_file, safe_execute
from utils.settings_helper import get_pricetar_repricing_url
try:
    from desktop.services.keepa_service import KeepaService
except ImportError:
    from services.keepa_service import KeepaService  # type: ignore

from .support import (
    NumericTableWidgetItem,
    RepricerWorker,
    _PRICETAR_BROWSER_TITLE_KEYWORDS,
    _REPRICER_ACTION_TO_PIPELINE_STEP,
    _REPRICER_WORKFLOW_PIPELINE_SEGMENTS,
    _REPRICER_WORKFLOW_PIPELINE_SEP,
    _format_repricer_status_prefix_html,
    _format_repricer_workflow_pipeline_html,
)


class RepricerPreviewMixin:
    """価格改定ウィジェットの分割ミックスイン。"""

    def setup_preview_area_full_width(self):
        """CSVプレビューエリアの設定（全幅）"""
        preview_group = QGroupBox()
        preview_layout = QVBoxLayout(preview_group)
    
        # ヘッダー（「CSVプレビュー ＋／－」ボタン）
        header_layout = QHBoxLayout()
        self.preview_toggle_btn = QPushButton("CSVプレビュー －")
        self.preview_toggle_btn.setFlat(True)
        self.preview_toggle_btn.clicked.connect(self.toggle_preview_area)
        header_layout.addWidget(self.preview_toggle_btn)
        header_layout.addStretch()
        preview_layout.addLayout(header_layout)

        # 日数フィルタボタン行
        filter_layout = QHBoxLayout()
        self.filter_90_btn = QPushButton("90")
        self.filter_180_btn = QPushButton("180")
        self.filter_270_btn = QPushButton("270")
        self.filter_340_btn = QPushButton("340")
        self.filter_clear_btn = QPushButton("クリア")
        self.filter_90_btn.clicked.connect(lambda _=False, d=90: self.apply_days_filter(d))
        self.filter_180_btn.clicked.connect(lambda _=False, d=180: self.apply_days_filter(d))
        self.filter_270_btn.clicked.connect(lambda _=False, d=270: self.apply_days_filter(d))
        self.filter_340_btn.clicked.connect(lambda _=False, d=340: self.apply_days_filter(d))
        self.filter_clear_btn.clicked.connect(self.clear_days_filter)
        for btn in [
            self.filter_90_btn,
            self.filter_180_btn,
            self.filter_270_btn,
            self.filter_340_btn,
            self.filter_clear_btn,
        ]:
            filter_layout.addWidget(btn)
        filter_layout.addStretch()
        preview_layout.addLayout(filter_layout)
        # 初期状態のボタンスタイルを適用
        self._update_days_filter_styles()
    
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

        # 右クリックメニュー（Keepa/Amazonページを開く）
        self.preview_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preview_table.customContextMenuRequested.connect(self.on_preview_context_menu)
    
        preview_layout.addWidget(self.preview_table)
    
        self.layout().addWidget(preview_group)

    def toggle_preview_area(self):
        """CSVプレビューエリアの折りたたみ切り替え"""
        self.preview_collapsed = not self.preview_collapsed
        self.preview_table.setVisible(not self.preview_collapsed)
        self.preview_toggle_btn.setText("CSVプレビュー ＋" if self.preview_collapsed else "CSVプレビュー －")

    def _populate_preview_table(self, df: pd.DataFrame):
        """プレビューテーブルを指定DataFrameで描画"""
        # ソート機能を一時的に無効化（データ投入中はソートしない）
        self.preview_table.setSortingEnabled(False)

        # テーブルの設定
        self.preview_table.clear()
        self.preview_table.setRowCount(len(df))
        self.preview_table.setColumnCount(len(df.columns))
        self.preview_table.setHorizontalHeaderLabels(df.columns.tolist())

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

        # データ投入完了後、ソート機能を再有効化
        self.preview_table.setSortingEnabled(True)

        # 列幅の自動調整
        self.preview_table.resizeColumnsToContents()

    def _compute_days_from_sku(self, df: pd.DataFrame):
        """SKUから日付を推定し、経過日数リストを返す（行数と同じ長さ）"""
        days_list = []
        today = datetime.now().date()

        # SKU列を探す
        sku_col_name = None
        for col in df.columns:
            if str(col).strip().upper() == "SKU":
                sku_col_name = col
                break

        if sku_col_name is None:
            return [None] * len(df)

        for _, row in df.iterrows():
            sku = row.get(sku_col_name, "")
            parsed_date = self._parse_date_from_sku(str(sku))
            if parsed_date is None:
                days_list.append(None)
            else:
                days_list.append((today - parsed_date).days)

        return days_list

    def _parse_date_from_sku(self, sku: str):
        """SKU文字列からYYYYMMDD形式の日付を推定して返す"""
        if not sku:
            return None

        # 例: 20251108B01AUKUZ3G337065780003F / hmk-20251108-new-047 など
        m = re.search(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", sku)
        if not m:
            return None
        y, mth, d = m.groups()
        try:
            return datetime(int(y), int(mth), int(d)).date()
        except ValueError:
            return None

    def on_preview_context_menu(self, position):
        """CSVプレビューテーブルの右クリックメニュー"""
        index = self.preview_table.indexAt(position)
        if not index.isValid():
            return

        # 行を選択状態にする
        row = index.row()
        self.preview_table.selectRow(row)

        menu = QMenu(self)
        keepa_action = menu.addAction("Keepaを開く")
        keepa_action.triggered.connect(self._open_keepa_from_preview)
        amazon_action = menu.addAction("Amazonを開く")
        amazon_action.triggered.connect(self._open_amazon_from_preview)
        menu.exec_(self.preview_table.viewport().mapToGlobal(position))

    def _get_asin_from_preview_row(self, row: int):
        """プレビュー行からASINを取得"""
        if row < 0:
            return None
        asin_col = -1
        for j in range(self.preview_table.columnCount()):
            header_item = self.preview_table.horizontalHeaderItem(j)
            if header_item and header_item.text().strip().lower() == "asin":
                asin_col = j
                break
        if asin_col < 0:
            return None
        item = self.preview_table.item(row, asin_col)
        if not item:
            return None
        asin = item.text().strip()
        return asin or None

    def _open_keepa_from_preview(self):
        """選択行のASINを使ってKeepa Amazonページを既定ブラウザで開く"""
        row = self.preview_table.currentRow()
        if row < 0:
            return
        asin = self._get_asin_from_preview_row(row)
        if not asin:
            QMessageBox.warning(self, "エラー", "ASINが見つかりません。")
            return
        # Amazon.co.jp 用の Keepa 商品ページ（ドメインコード 5）
        url = f"https://keepa.com/#!product/5-{asin}"
        QDesktopServices.openUrl(QUrl(url))

    def _open_amazon_from_preview(self):
        """選択行のASINを使ってAmazon商品ページを既定ブラウザで開く"""
        row = self.preview_table.currentRow()
        if row < 0:
            return
        asin = self._get_asin_from_preview_row(row)
        if not asin:
            QMessageBox.warning(self, "エラー", "ASINが見つかりません。")
            return
        url = f"https://www.amazon.co.jp/dp/{asin}"
        QDesktopServices.openUrl(QUrl(url))

    def preview_csv(self):
        """CSVファイルのプレビュー（価格改定プレビュー）"""
        if not self.csv_path:
            return
        
        # 進捗バーの表示
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.preview_btn.setEnabled(False)
    
        # ワーカースレッドの作成と実行（プレビューモード）
        self.worker = RepricerWorker(self.csv_path, self.api_client, is_preview=True, mode=self.mode)
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

            # プレビュー元データとSKU日数を保持
            self.preview_df = df
            self.preview_days = self._compute_days_from_sku(df)
            self._manual_export_prices = {}

            # テーブル描画
            self._populate_preview_table(df)

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
        
            # title列が見つかった場合、その列をハイライト
            if title_column >= 0:
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

    def apply_days_filter(self, threshold: int):
        """指定日数以上経過しているSKUのみ表示"""
        if self.preview_df is None or self.preview_days is None:
            QMessageBox.information(self, "情報", "先に「CSV内容表示」でCSVを読み込んでください。")
            return
        if not any(d is not None for d in self.preview_days):
            QMessageBox.information(self, "情報", "SKUから日付を取得できませんでした。")
            return

        mask = []
        for d in self.preview_days:
            if d is not None and d >= threshold:
                mask.append(True)
            else:
                mask.append(False)

        filtered_df = self.preview_df[mask]
        self._populate_preview_table(filtered_df)
        # アクティブなフィルタを更新
        self.active_days_filter = threshold
        self._update_days_filter_styles()

    def clear_days_filter(self):
        """日数フィルタを解除して全件表示"""
        if self.preview_df is None:
            return
        self._populate_preview_table(self.preview_df)
        # フィルタ状態をリセット
        self.active_days_filter = None
        self._update_days_filter_styles()

    def _update_days_filter_styles(self):
        """日数フィルタボタンのスタイルを現在の選択状態に合わせて更新"""
        # ベーススタイル（デフォルトのボタン）
        base_style = ""
        # アクティブスタイル（選択中のボタン）
        active_style = (
            "QPushButton {"
            "  background-color: #28a745;"
            "  color: white;"
            "  font-weight: bold;"
            "}"
        )

        button_map = {
            90: self.filter_90_btn,
            180: self.filter_180_btn,
            270: self.filter_270_btn,
            340: self.filter_340_btn,
        }

        for days, btn in button_map.items():
            if self.active_days_filter == days:
                btn.setStyleSheet(active_style)
            else:
                btn.setStyleSheet(base_style)

        # クリアボタンは常にベーススタイル
        if hasattr(self, "filter_clear_btn"):
            self.filter_clear_btn.setStyleSheet(base_style)

    def on_preview_completed(self, result):
        """プレビュー完了時の処理"""
        result = self._apply_manual_overrides_to_result(result)
        self.repricing_result = result
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        self.keepa_fetch_btn.setEnabled(True)
    
        # 結果テーブルの更新
        self.update_result_table(result)

        # プレビュー完了後は手動工程③（価格確認・目視）へ
        self._workflow_active_step = 3
        self._update_workflow_status("ワークフロー: 待機", emphasize=False)
    
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
