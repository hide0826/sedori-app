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
    QProgressBar, QTextEdit, QGroupBox, QSplitter, QApplication,
    QMessageBox, QFrame, QMenu
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices
import pandas as pd
from pathlib import Path
from datetime import datetime
import re
from typing import Any, Dict, Optional
from utils.error_handler import ErrorHandler, validate_csv_file, safe_execute
try:
    from desktop.services.keepa_service import KeepaService
except ImportError:
    from services.keepa_service import KeepaService  # type: ignore


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
    
    def __init__(self, csv_path, api_client, is_preview=True, mode="standard"):
        super().__init__()
        self.csv_path = csv_path
        self.api_client = api_client
        self.is_preview = is_preview
        self.mode = mode
        
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
                result = self.api_client.repricer_preview(self.csv_path, mode=self.mode)
            else:
                result = self.api_client.repricer_apply(self.csv_path, mode=self.mode)
            
            self.progress_updated.emit(100)
            
            # 結果を返す
            self.result_ready.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(str(e))


class RepricerWidget(QWidget):
    """価格改定ウィジェット"""
    
    def __init__(self, api_client, mode="standard"):
        super().__init__()
        self.api_client = api_client
        self.mode = mode if mode in ("standard", "369") else "standard"
        self.product_widget = None
        self.csv_path = None
        self.repricing_result = None
        self.error_handler = ErrorHandler(self)
        self.settings = QSettings("HIRIO", "DesktopApp")
        # プレビュー／結果エリア状態
        self.preview_collapsed = False
        self.result_collapsed = False
        # CSVプレビュー用の元データとSKU日数
        self.preview_df = None
        self.preview_days = None
        # 日数フィルタの現在値（90/180/270/340 または None）
        self.active_days_filter = None
        self.active_result_days_filter = None
        self.keepa_cache = {}
        self._purchase_edit_dialogs = []
        
        # UIの初期化
        self.setup_ui()

    @staticmethod
    def _normalize_sku_text(raw_value: Any) -> str:
        """CSVセル値からSKU文字列を安全に正規化する。"""
        if raw_value is None:
            return ""
        text = str(raw_value).strip()
        if not text or text.lower() in ("nan", "none"):
            return ""
        # Excel由来の ="SKU" を通常文字列に戻す
        if text.startswith('="') and text.endswith('"'):
            text = text[2:-1].strip()
        return text

    def _extract_skus_for_status_sync(self, df: pd.DataFrame) -> list[str]:
        """価格改定CSVからSKU一覧（重複除去）を抽出する。"""
        if df is None or df.empty:
            return []

        def _norm_col(col_name: Any) -> str:
            return str(col_name).strip().lower().replace(" ", "").replace("_", "").replace("-", "")

        sku_col_candidates = {
            "sku", "sellersku", "merchantsku", "出品者sku", "出品sku", "商品sku", "商品管理番号"
        }
        sku_col = None
        for col in df.columns:
            if _norm_col(col) in sku_col_candidates:
                sku_col = col
                break
        if sku_col is None:
            return []

        seen = set()
        unique_skus: list[str] = []
        for raw_sku in df[sku_col].tolist():
            sku = self._normalize_sku_text(raw_sku)
            if not sku or sku in seen:
                continue
            seen.add(sku)
            unique_skus.append(sku)
        return unique_skus

    def _sync_purchase_status_to_selling_from_csv(self, csv_path: str) -> tuple[int, int, int]:
        """
        CSV内SKUと仕入DBを照合し、statusが未設定/readyの行だけsellingへ更新する。

        Returns:
            (updated_count, matched_count, csv_sku_count)
        """
        try:
            from utils.csv_io import csv_io
            try:
                from database.purchase_db import PurchaseDatabase
            except Exception:
                from desktop.database.purchase_db import PurchaseDatabase  # type: ignore

            df = csv_io.read_csv(csv_path)
            skus = self._extract_skus_for_status_sync(df)
            if not skus:
                return (0, 0, 0)

            purchase_db = PurchaseDatabase()
            updated_count = 0
            matched_count = 0
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for sku in skus:
                purchase = purchase_db.get_by_sku(sku)
                if not purchase:
                    continue
                matched_count += 1
                current_status = str(purchase.get("status") or "").strip().lower()
                if not current_status or current_status == "ready":
                    purchase_db.upsert({
                        "sku": sku,
                        "status": "selling",
                        "status_set_at": now_str,
                    })
                    updated_count += 1

            return (updated_count, matched_count, len(skus))
        except Exception as e:
            # 価格改定フローを止めないため、同期失敗はログのみ
            print(f"[RepricerWidget] ステータス同期エラー: {e}")
            return (0, 0, 0)
        
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

    def set_product_widget(self, product_widget):
        """商品DBウィジェット参照を受け取り、仕入行編集ダイアログ連携に使う"""
        self.product_widget = product_widget
        
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

        # ファイル選択クリアボタン
        self.clear_file_btn = QPushButton("クリア")
        self.clear_file_btn.clicked.connect(self.clear_csv_selection)
        self.clear_file_btn.setMaximumHeight(30)  # 高さを制限
        self.clear_file_btn.setEnabled(False)
        file_layout.addWidget(self.clear_file_btn)
        
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
    
    def setup_result_area_full_width(self):
        """価格改定結果エリアの設定（全幅）"""
        result_group = QGroupBox()
        result_layout = QVBoxLayout(result_group)
        
        # ヘッダー（「価格改定結果 ＋／－」ボタン）
        header_layout = QHBoxLayout()
        self.result_toggle_btn = QPushButton("価格改定結果 －")
        self.result_toggle_btn.setFlat(True)
        self.result_toggle_btn.clicked.connect(self.toggle_result_area)
        header_layout.addWidget(self.result_toggle_btn)
        header_layout.addStretch()
        result_layout.addLayout(header_layout)

        # 日数フィルタボタン行（価格改定結果用）
        result_filter_layout = QHBoxLayout()
        self.result_filter_90_btn = QPushButton("90")
        self.result_filter_180_btn = QPushButton("180")
        self.result_filter_270_btn = QPushButton("270")
        self.result_filter_340_btn = QPushButton("340")
        self.result_filter_clear_btn = QPushButton("クリア")
        self.result_filter_90_btn.clicked.connect(lambda _=False, d=90: self.apply_result_days_filter(d))
        self.result_filter_180_btn.clicked.connect(lambda _=False, d=180: self.apply_result_days_filter(d))
        self.result_filter_270_btn.clicked.connect(lambda _=False, d=270: self.apply_result_days_filter(d))
        self.result_filter_340_btn.clicked.connect(lambda _=False, d=340: self.apply_result_days_filter(d))
        self.result_filter_clear_btn.clicked.connect(self.clear_result_days_filter)
        for btn in [
            self.result_filter_90_btn,
            self.result_filter_180_btn,
            self.result_filter_270_btn,
            self.result_filter_340_btn,
            self.result_filter_clear_btn,
        ]:
            result_filter_layout.addWidget(btn)
        result_filter_layout.addStretch()
        result_layout.addLayout(result_filter_layout)
        self._update_result_days_filter_styles()
        
        # 結果テーブル
        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.horizontalHeader().setSectionsClickable(True)
        self.result_table.horizontalHeader().setSortIndicatorShown(True)
        self.result_table.setMinimumHeight(200)  # 適度な高さを設定
        # 選択時にQSSのselected色で行背景が上書きされるのを防ぐ
        # （TP下限の黄色ハイライトを常に視認できるようにする）
        self.result_table.setStyleSheet(
            "QTableWidget::item:selected {"
            "background-color: transparent;"
            "}"
        )
        
        # 大量データ対応の最適化
        self.result_table.setSortingEnabled(True)  # ソート機能を有効化
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)  # 行選択
        
        # パフォーマンス向上のための設定
        self.result_table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.result_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        
        # 選択変更時の自動スクロール機能
        self.result_table.itemSelectionChanged.connect(self.on_result_selection_changed)
        # 行ダブルクリックで仕入行編集（Keepa）ダイアログを開く
        self.result_table.cellDoubleClicked.connect(self.on_result_table_double_clicked)
        
        result_layout.addWidget(self.result_table)
        
        self.layout().addWidget(result_group)
        
    def toggle_preview_area(self):
        """CSVプレビューエリアの折りたたみ切り替え"""
        self.preview_collapsed = not self.preview_collapsed
        self.preview_table.setVisible(not self.preview_collapsed)
        self.preview_toggle_btn.setText("CSVプレビュー ＋" if self.preview_collapsed else "CSVプレビュー －")
        
    def toggle_result_area(self):
        """価格改定結果エリアの折りたたみ切り替え"""
        self.result_collapsed = not self.result_collapsed
        self.result_table.setVisible(not self.result_collapsed)
        self.result_toggle_btn.setText("価格改定結果 ＋" if self.result_collapsed else "価格改定結果 －")

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

        # Keepa取得ボタン（対象行のみ）
        self.keepa_fetch_btn = QPushButton("Keepa取得")
        self.keepa_fetch_btn.clicked.connect(self.fetch_keepa_for_target_rows)
        self.keepa_fetch_btn.setEnabled(False)
        self.keepa_fetch_btn.setMaximumHeight(35)
        button_layout.addWidget(self.keepa_fetch_btn)
        
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
                    self.clear_file_btn.setEnabled(True)
                    
                    # 選択したファイルのディレクトリを保存（次回同じフォルダから開く）
                    selected_dir = str(Path(file_path).parent)
                    self.settings.setValue("directories/csv", selected_dir)

                    # 在庫CSVのSKUが仕入DBにある場合、ready/未設定のみ販売中へ同期
                    updated, matched, csv_sku_count = self._sync_purchase_status_to_selling_from_csv(file_path)
                    if csv_sku_count > 0:
                        print(
                            f"[RepricerWidget] ステータス同期: CSV SKU={csv_sku_count}, "
                            f"DB一致={matched}, 販売中へ更新={updated}"
                        )
                        QMessageBox.information(
                            self,
                            "ステータス同期結果",
                            "在庫リスト読み込み時のステータス同期が完了しました。\n\n"
                            f"CSV内SKU数: {csv_sku_count} 件\n"
                            f"仕入DB一致: {matched} 件\n"
                            f"販売中へ更新: {updated} 件\n\n"
                            "※ 更新対象はステータスが未設定/出品可能(ready)のSKUのみです。"
                        )
                    else:
                        QMessageBox.information(
                            self,
                            "ステータス同期結果",
                            "ステータス同期は実行しましたが、CSV内にSKU列または有効なSKUが見つかりませんでした。"
                        )
                    
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

    def clear_csv_selection(self):
        """選択中のCSVファイルをクリアしてUI状態を初期化"""
        self.csv_path = None
        self.repricing_result = None
        self.preview_df = None
        self.preview_days = None
        self.active_days_filter = None
        self.file_path_edit.clear()

        # ボタン状態を初期化
        self.csv_preview_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.execute_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.keepa_fetch_btn.setEnabled(False)
        self.clear_file_btn.setEnabled(False)

        # テーブル・進捗表示を初期化
        self.preview_table.clear()
        self.preview_table.setRowCount(0)
        self.preview_table.setColumnCount(0)
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

        # フィルタボタンの見た目を通常に戻す
        self._update_days_filter_styles()
            
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
    
    def on_result_selection_changed(self):
        """価格改定結果テーブルの選択変更時の処理"""
        try:
            # NOTE:
            # 過去は選択行の背景色をここで上書きしていたが、
            # 価格改定結果の行色（TP下限の黄色・上昇/下降色）を潰してしまうため
            # 背景変更は行わない。
            pass
        except Exception as e:
            print(f"結果選択変更処理エラー: {e}")

    def _repricer_csv_snapshot_for_sku(self, sku: str, asin: str) -> Optional[Dict[str, Any]]:
        """3-6-9モードのプレビュー/実行結果から、日数・在庫CSV由来の現在価格・profit を取得。"""
        if str(self.mode) != "369" or not self.repricing_result:
            return None
        items = self.repricing_result.get("items") or []
        for it in items:
            if str(it.get("sku", "")).strip() != sku:
                continue
            it_asin = str(it.get("asin", "")).strip()
            if asin and it_asin and it_asin != asin:
                continue
            try:
                p = float(it.get("price", 0) or 0)
            except (TypeError, ValueError):
                p = 0.0
            raw_profit = it.get("csv_profit", it.get("profit", 0))
            try:
                prof = float(raw_profit or 0)
            except (TypeError, ValueError):
                prof = 0.0
            days_val: Optional[int] = None
            raw_days = it.get("days")
            if raw_days is not None and str(raw_days).strip() != "":
                try:
                    days_val = int(float(raw_days))
                except (TypeError, ValueError):
                    days_val = None
            return {"price": p, "profit": prof, "days": days_val}
        return None

    def on_result_table_double_clicked(self, row: int, col: int):
        """価格改定結果行のダブルクリックで仕入行編集ダイアログを開く"""
        try:
            sku_item = self.result_table.item(row, 0)  # SKU列
            asin_item = self.result_table.item(row, 1)  # ASIN列
            title_item = self.result_table.item(row, 2)  # Title列
            current_price_item = self.result_table.item(row, 7)  # 現在価格列
            new_price_item = self.result_table.item(row, 8)  # 改定価格列
            sku = sku_item.text().strip() if sku_item else ""
            asin = asin_item.text().strip() if asin_item else ""
            title = title_item.text().strip() if title_item else ""
            current_price = current_price_item.text().strip() if current_price_item else ""
            new_price = new_price_item.text().strip() if new_price_item else ""
            if not sku:
                return

            # ProductWidget はタブ初表示まで仕入スナップショットを読まない。
            # データベース管理を開かないと purchase_all_records が空のままになり、
            # 仕入行の編集で価格・利益が空振りするため、ここで先に読み込む。
            pw = self.product_widget
            if pw is not None and hasattr(pw, "ensure_initial_data_loaded"):
                try:
                    pw.ensure_initial_data_loaded()
                except Exception:
                    pass

            record = None
            if pw is not None:
                records = getattr(pw, "purchase_all_records", None) or getattr(pw, "purchase_records", None) or []
                for rec in records:
                    rec_sku = str(rec.get("SKU") or rec.get("sku") or "").strip()
                    rec_asin = str(rec.get("ASIN") or rec.get("asin") or "").strip()
                    if rec_sku == sku and (not asin or not rec_asin or rec_asin == asin):
                        record = rec
                        break
                if record is None:
                    for rec in records:
                        rec_sku = str(rec.get("SKU") or rec.get("sku") or "").strip()
                        if rec_sku == sku:
                            record = rec
                            break

            # ProductWidgetのキャッシュに無い場合は仕入DBから最低限取得して開く
            if record is None and pw is not None and hasattr(pw, "purchase_history_db"):
                db_rec = pw.purchase_history_db.get_by_sku(sku)
                if db_rec:
                    record = {
                        "SKU": sku,
                        "ASIN": asin or str(db_rec.get("asin") or ""),
                        "商品名": title or str(db_rec.get("product_name") or db_rec.get("title") or ""),
                        "コンディション": str(db_rec.get("condition_note") or db_rec.get("condition") or ""),
                        "仕入れ価格": db_rec.get("purchase_price") or db_rec.get("仕入れ価格") or db_rec.get("仕入価格") or 0,
                        "purchase_price": db_rec.get("purchase_price") or db_rec.get("仕入れ価格") or db_rec.get("仕入価格") or 0,
                        "販売予定価格": db_rec.get("expected_price") or db_rec.get("planned_price") or current_price or new_price or 0,
                        "見込み利益": db_rec.get("expected_profit") or db_rec.get("profit") or 0,
                        "TP0": db_rec.get("tp0", ""),
                        "TP1": db_rec.get("tp1", ""),
                        "TP2": db_rec.get("tp2", ""),
                        "TP3": db_rec.get("tp3", ""),
                        "tp0": db_rec.get("tp0", ""),
                        "tp1": db_rec.get("tp1", ""),
                        "tp2": db_rec.get("tp2", ""),
                        "tp3": db_rec.get("tp3", ""),
                    }

            # ProductDBも参照して、商品名/ASINなど不足情報を補完
            if pw is not None and hasattr(pw, "db"):
                try:
                    product_rec = pw.db.get_by_sku(sku)
                except Exception:
                    product_rec = None
                if product_rec:
                    if record is None:
                        record = {}
                    record.setdefault("SKU", sku)
                    if not record.get("ASIN"):
                        record["ASIN"] = asin or str(product_rec.get("asin") or "")
                    if not record.get("商品名"):
                        record["商品名"] = title or str(product_rec.get("product_name") or "")
                    if not record.get("販売予定価格"):
                        record["販売予定価格"] = current_price or new_price or 0
                    if "見込み利益" not in record or record.get("見込み利益") in (None, ""):
                        record["見込み利益"] = 0

            # 最終フォールバック: 結果テーブルの値で最低限の表示項目を埋める
            if record is not None:
                record.setdefault("SKU", sku)
                record.setdefault("ASIN", asin)
                if not record.get("商品名"):
                    record["商品名"] = title
                if not record.get("コンディション"):
                    record["コンディション"] = ""
                if not record.get("販売予定価格"):
                    record["販売予定価格"] = current_price or new_price or 0
                if "見込み利益" not in record or record.get("見込み利益") in (None, ""):
                    record["見込み利益"] = 0
                # ダイアログ側の互換キー
                if "expected_price" not in record:
                    record["expected_price"] = record.get("販売予定価格", 0)
                if "expected_profit" not in record:
                    record["expected_profit"] = record.get("見込み利益", 0)

            if record is None:
                QMessageBox.information(self, "仕入行の編集", f"SKU {sku} の仕入データが見つかりません。")
                return

            csv_snap = self._repricer_csv_snapshot_for_sku(sku, asin)

            try:
                from ui.purchase_row_edit_dialog import PurchaseRowEditDialog
            except ImportError:
                from desktop.ui.purchase_row_edit_dialog import PurchaseRowEditDialog
            dialog = PurchaseRowEditDialog(record, product_widget=pw, csv_inventory_snapshot=csv_snap)
            dialog.setModal(False)
            dialog.setWindowModality(Qt.NonModal)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            self._purchase_edit_dialogs.append(dialog)
            dialog.destroyed.connect(lambda _=None, d=dialog: self._purchase_edit_dialogs.remove(d) if d in self._purchase_edit_dialogs else None)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception as e:
            QMessageBox.warning(self, "仕入行の編集", f"ダイアログ表示に失敗しました:\n{e}")
    
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

    def apply_result_days_filter(self, threshold: int):
        """価格改定結果の日数フィルタを適用"""
        if not self.repricing_result or "items" not in self.repricing_result:
            return
        self.active_result_days_filter = threshold
        self._update_result_days_filter_styles()
        self.update_result_table(self.repricing_result)

    def clear_result_days_filter(self):
        """価格改定結果の日数フィルタを解除"""
        self.active_result_days_filter = None
        self._update_result_days_filter_styles()
        if self.repricing_result and "items" in self.repricing_result:
            self.update_result_table(self.repricing_result)

    def _update_result_days_filter_styles(self):
        """価格改定結果用の日数フィルタボタンのスタイル更新"""
        base_style = ""
        active_style = (
            "QPushButton {"
            "  background-color: #28a745;"
            "  color: white;"
            "  font-weight: bold;"
            "}"
        )
        button_map = {
            90: getattr(self, "result_filter_90_btn", None),
            180: getattr(self, "result_filter_180_btn", None),
            270: getattr(self, "result_filter_270_btn", None),
            340: getattr(self, "result_filter_340_btn", None),
        }
        for days, btn in button_map.items():
            if btn is None:
                continue
            if self.active_result_days_filter == days:
                btn.setStyleSheet(active_style)
            else:
                btn.setStyleSheet(base_style)
        if hasattr(self, "result_filter_clear_btn"):
            self.result_filter_clear_btn.setStyleSheet(base_style)
    
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
        self.repricing_result = result
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        self.keepa_fetch_btn.setEnabled(True)
        
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
        self.worker = RepricerWorker(self.csv_path, self.api_client, is_preview=False, mode=self.mode)
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
        self.keepa_fetch_btn.setEnabled(True)
        
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
        if self.active_result_days_filter is not None:
            threshold = int(self.active_result_days_filter)
            filtered_items = []
            for it in items:
                try:
                    d = int(it.get("days", -1))
                except (TypeError, ValueError):
                    d = -1
                if d >= threshold:
                    filtered_items.append(it)
            items = filtered_items
        
        # ソート機能を一時的に無効化（データ投入中はソートしない）
        self.result_table.setSortingEnabled(False)
        
        # テーブルの設定（必要な列のみ）
        self.result_table.setRowCount(len(items))
        columns = ['SKU', 'ASIN', 'Title', '日数', 'TP下限', 'アクション', '理由', '現在価格', '改定価格', 'akaji', 'takane', 'Trace変更', 'Keepa価格(参考)']
        self.result_table.setColumnCount(len(columns))
        self.result_table.setHorizontalHeaderLabels(columns)
        total_columns = len(columns)
        
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
            akaji_value = item.get('akaji', '')
            takane_value = item.get('takane', '')
            tp_floor_raw = item.get('tp_floor', None)
            try:
                tp_floor = float(tp_floor_raw) if tp_floor_raw not in (None, "") else None
            except (TypeError, ValueError):
                tp_floor = None
            is_tp_floor_or_below = bool(item.get('is_tp_floor_or_below', False))
            tp_reach_status = str(item.get('tp_reach_status', '') or '')
            # priceTraceChangeDisplayを優先的に使用（表示用文字列）
            trace_change_text = item.get('priceTraceChangeDisplay', None)
            
            # priceTraceChangeDisplayがない場合は、従来の処理でフォールバック
            if trace_change_text is None:
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
            
            # 文字列に変換（Noneの場合は空文字列）
            trace_change_text = str(trace_change_text) if trace_change_text is not None else ""
            keepa_ref = item.get("keepa_ref_price", "")
            keepa_ref_text = "" if keepa_ref in (None, "") else str(keepa_ref)
            
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
            
            # TP下限到達マーカー（色に依存しない視認性向上）
            tp_flag_text = ""
            akaji_equal_price = False
            if akaji_value not in (None, ""):
                try:
                    akaji_equal_price = abs(price - float(akaji_value)) <= 1e-9
                except (TypeError, ValueError):
                    akaji_equal_price = False
            if tp_reach_status in ("期間到達", "期間外到達"):
                tp_flag_text = tp_reach_status
            elif is_tp_floor_or_below:
                tp_flag_text = "到達"
            elif akaji_equal_price:
                # 在庫CSVのpriceとakajiが同額の場合は要チェックとして明示
                tp_flag_text = "akaji到達"
            elif "TP下限" in reason:
                tp_flag_text = "近接"
            tp_flag_item = QTableWidgetItem(tp_flag_text)
            if tp_flag_text:
                tp_flag_item.setToolTip("TP下限到達/下限以下の行です")
                if tp_flag_text == "期間到達":
                    tp_flag_item.setForeground(QColor(80, 220, 120))  # 緑
                elif tp_flag_text == "期間外到達":
                    tp_flag_item.setForeground(QColor(255, 80, 80))  # 赤
                elif tp_flag_text == "akaji到達":
                    tp_flag_item.setForeground(QColor(255, 230, 0))  # 黄色
                else:
                    tp_flag_item.setForeground(QColor(255, 80, 80))
            self.result_table.setItem(i, 4, tp_flag_item)

            self.result_table.setItem(i, 5, QTableWidgetItem(self.clean_excel_formula(str(action))))
            self.result_table.setItem(i, 6, QTableWidgetItem(self.clean_excel_formula(str(reason))))
            
            # 価格列：数値としてソートするためにQt.UserRoleに数値を設定
            price_item = NumericTableWidgetItem(price)
            price_item.setText(self.clean_excel_formula(str(price)))
            self.result_table.setItem(i, 7, price_item)
            
            new_price_item = NumericTableWidgetItem(new_price)
            new_price_item.setText(self.clean_excel_formula(str(new_price)))
            self.result_table.setItem(i, 8, new_price_item)

            # akaji / takane は3-6-9実行時の入力値確認用にそのまま表示
            akaji_text = "" if akaji_value in (None, "") else self.clean_excel_formula(str(akaji_value))
            takane_text = "" if takane_value in (None, "") else self.clean_excel_formula(str(takane_value))
            self.result_table.setItem(i, 9, QTableWidgetItem(akaji_text))
            self.result_table.setItem(i, 10, QTableWidgetItem(takane_text))
            
            self.result_table.setItem(i, 11, QTableWidgetItem(trace_change_text))
            self.result_table.setItem(i, 12, QTableWidgetItem(keepa_ref_text))
            
            # 日付不明の行を識別（daysが-1、または理由に「日付不明」が含まれる）
            is_date_unknown = (days == -1) or ("日付不明" in reason)
            
            # 日付不明の場合は灰色で表示
            if is_date_unknown:
                for j in range(total_columns):
                    item = self.result_table.item(i, j)
                    if item:
                        item.setBackground(QColor(150, 150, 150))  # グレー背景
                        item.setForeground(QColor(255, 255, 255))  # 白文字
            else:
                # 価格変更に応じて色分け（型変換を追加）
                try:
                    price_float = float(price) if price else 0
                    new_price_float = float(new_price) if new_price else 0
                    
                    if new_price_float > price_float:
                        # 価格上昇：緑色
                        for j in range(total_columns):
                            item = self.result_table.item(i, j)
                            if item:
                                item.setBackground(QColor(200, 255, 200))
                    elif new_price_float < price_float:
                        # 価格下降：赤色
                        for j in range(total_columns):
                            item = self.result_table.item(i, j)
                            if item:
                                item.setBackground(QColor(255, 200, 200))

                    # TP下限ちょうど/以下は最優先で黄色表示
                    # バックエンド判定フラグを最優先で使用し、必要時のみフォールバック判定
                    akaji_float = None
                    try:
                        akaji_float = float(akaji_value) if akaji_value not in (None, "") else None
                    except (TypeError, ValueError):
                        akaji_float = None

                    is_tp_floor_row = bool(
                        is_tp_floor_or_below
                        or (tp_floor is not None and tp_floor > 0 and (new_price_float <= tp_floor or price_float <= tp_floor))
                        or ("TP下限" in reason)
                        or (akaji_float is not None and akaji_float > 0 and (new_price_float <= akaji_float or price_float <= akaji_float))
                    )
                    if is_tp_floor_row:
                        for j in range(total_columns):
                            cell_item = self.result_table.item(i, j)
                            if cell_item:
                                # ダークテーマでも見える強めの黄色
                                cell_item.setBackground(QColor(255, 230, 0))
                        # TP下限マーカー列は常に赤で見せる（行色処理の後に再適用）
                        tp_marker_item = self.result_table.item(i, 4)
                        if tp_marker_item and tp_marker_item.text().strip():
                            marker_text = tp_marker_item.text().strip()
                            if marker_text == "期間到達":
                                tp_marker_item.setForeground(QColor(80, 220, 120))
                            elif marker_text == "akaji到達":
                                tp_marker_item.setForeground(QColor(255, 230, 0))
                            else:
                                tp_marker_item.setForeground(QColor(255, 80, 80))
                except (ValueError, TypeError):
                    # 型変換に失敗した場合は色分けをスキップ
                    pass
        
        # データ投入完了後、ソート機能を再有効化
        self.result_table.setSortingEnabled(True)
        
        # 列幅の自動調整
        self.result_table.resizeColumnsToContents()

    def _is_keepa_target_item(self, item: dict) -> bool:
        """Keepa取得対象行を判定する。"""
        raw_action = str(item.get("rule_action", "")).lower()
        try:
            current_price = float(item.get("new_price", item.get("price", 0)) or 0)
        except (TypeError, ValueError):
            current_price = 0.0
        try:
            akaji = float(item.get("akaji", 0) or 0)
        except (TypeError, ValueError):
            akaji = 0.0
        is_akaji_sticky = akaji > 0 and abs(current_price - akaji) <= 1.0
        return (raw_action == "tp_down") or (raw_action == "pricetrace" and is_akaji_sticky)

    def _pick_keepa_reference_price(self, info) -> str:
        """Keepa情報から参考価格文字列を作る（中古最安ベース）。"""
        candidates = [
            info.used_like_new,
            info.used_very_good,
            info.used_good,
            info.used_acceptable,
        ]
        prices = [float(v) for v in candidates if v is not None and float(v) > 0]
        if prices:
            return str(round(min(prices)))
        if info.new_price is not None and float(info.new_price) > 0:
            return str(round(float(info.new_price)))
        return ""

    def fetch_keepa_for_target_rows(self):
        """対象行だけKeepa価格(参考)を取得して結果テーブルに反映する。"""
        if not self.repricing_result or "items" not in self.repricing_result:
            QMessageBox.information(self, "Keepa取得", "先に価格改定プレビューまたは実行を行ってください。")
            return

        items = self.repricing_result.get("items", [])
        target_items = [it for it in items if self._is_keepa_target_item(it) and str(it.get("asin", "")).strip()]
        if not target_items:
            QMessageBox.information(self, "Keepa取得", "Keepa取得対象のSKUがありません。")
            return

        unique_asins = []
        seen = set()
        for it in target_items:
            asin = str(it.get("asin", "")).strip()
            if asin and asin not in seen:
                seen.add(asin)
                unique_asins.append(asin)

        reply = QMessageBox.question(
            self,
            "Keepa取得確認",
            f"対象SKU: {len(target_items)}件（ASIN重複除外: {len(unique_asins)}件）\nKeepa価格(参考)を取得しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.keepa_fetch_btn.setEnabled(False)

        success = 0
        failed = 0
        service = None
        try:
            service = KeepaService()
            total = len(unique_asins)
            asin_to_price = {}
            for idx, asin in enumerate(unique_asins, 1):
                if asin in self.keepa_cache:
                    asin_to_price[asin] = self.keepa_cache.get(asin, "")
                else:
                    try:
                        info = service.fetch_product_by_asin(asin)
                        keepa_price = self._pick_keepa_reference_price(info)
                        self.keepa_cache[asin] = keepa_price
                        asin_to_price[asin] = keepa_price
                    except Exception:
                        self.keepa_cache[asin] = ""
                        asin_to_price[asin] = ""
                        failed += 1
                self.progress_bar.setValue(round(idx * 100 / max(1, total)))
                QApplication.processEvents()

            for item in target_items:
                asin = str(item.get("asin", "")).strip()
                keepa_price = asin_to_price.get(asin, "")
                if keepa_price:
                    item["keepa_ref_price"] = keepa_price
                    success += 1

            self.update_result_table(self.repricing_result)
            QMessageBox.information(
                self,
                "Keepa取得完了",
                f"Keepa価格(参考)を更新しました。\n成功: {success}件 / 失敗: {failed}件",
            )
        except Exception as e:
            QMessageBox.warning(self, "Keepa取得エラー", f"Keepa取得に失敗しました:\n{e}")
        finally:
            self.progress_bar.setVisible(False)
            self.keepa_fetch_btn.setEnabled(True)
    
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
            
        # CSVファイル選択で指定したフォルダをデフォルトディレクトリとして使用
        default_dir = self.settings.value("directories/csv", "")
        if not default_dir and self.csv_path:
            # CSVファイルパスが設定されている場合はそのディレクトリを使用
            default_dir = str(Path(self.csv_path).parent)
        
        default_filename = "repricing_result.csv"
        
        # デフォルトディレクトリがある場合は、自動リネーム機能付きでファイルパスを生成
        if default_dir:
            default_path = self._get_unique_file_path(default_dir, default_filename)
        else:
            default_path = default_filename
        
        # 直接ファイル保存ダイアログを表示（確認ダイアログなし）
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "結果をCSV保存",
            default_path,  # デフォルトパスを指定（CSVファイル選択時のフォルダ）
            "CSVファイル (*.csv)"
        )
        
        if not file_path:
            return  # キャンセルされた場合
        
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
            
            # akajiの情報を取得（price_down_ignoreの場合は空白）
            akaji_value = item.get('akaji', None)
            
            repricing_dict[sku] = {
                'new_price': new_price,
                'price_trace': price_trace,
                'akaji': akaji_value  # Noneの場合は元の値を保持、空文字の場合は空白に設定
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
                akaji_value = repricing_dict[sku].get('akaji', None)
                
                # 価格とpriceTraceの両方が変更されていない場合はスキップ（CSVに保存しない）
                if new_price == original_price and new_price_trace == original_price_trace:
                    print(f"[DEBUG CSV保存] スキップ: {sku} (変更なし)")
                    continue
                
                row_data = row.to_dict()
                row_data['price'] = new_price
                row_data['priceTrace'] = new_price_trace
                # conditionNoteは空にする
                row_data['conditionNote'] = ""
                # 利益無視（price_down_ignore）の場合はakajiを空白にする
                if akaji_value is not None:
                    row_data['akaji'] = akaji_value  # 空文字の場合は空白に設定
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
            
            # 再試行（同じtargetパスを使用、resolve_unique_pathは呼ばない）
            df.to_csv(str(target), index=False, encoding='shift_jis', quoting=0)
        
        return str(target)
