
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

import pandas as pd
from pathlib import Path
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from utils.error_handler import ErrorHandler, safe_execute

from .support import (
    DraggableFileIconWidget,
    NumericTableWidgetItem,
    RepricerWorker,
    _PRICETAR_BROWSER_TITLE_KEYWORDS,
    _REPRICER_ACTION_TO_PIPELINE_STEP,
    _REPRICER_WORKFLOW_PIPELINE_SEGMENTS,
    _REPRICER_WORKFLOW_PIPELINE_SEP,
    _format_repricer_status_prefix_html,
    _format_repricer_workflow_pipeline_html,
    get_pricetar_repricing_url,
    schedule_bring_browser_to_front,
    validate_csv_file,
)


class RepricerFilePanelMixin:
    """価格改定ウィジェットの分割ミックスイン。"""

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
                if current_status == "inventory_only":
                    continue
                if not current_status or current_status == "ready":
                    purchase_db.upsert({
                        "sku": sku,
                        "status": "selling",
                        "status_reason": "在庫CSV連動:",
                        "status_set_at": now_str,
                    })
                    updated_count += 1

            return (updated_count, matched_count, len(skus))
        except Exception as e:
            # 価格改定フローを止めないため、同期失敗はログのみ
            print(f"[RepricerWidget] ステータス同期エラー: {e}")
            return (0, 0, 0)

    def setup_file_selection(self):
        """ファイル操作・アクション（ワークフロー付き）"""
        file_group = QGroupBox("ファイル操作・アクション")
        file_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        file_outer = QVBoxLayout(file_group)
        file_outer.setSpacing(4)
        file_outer.setContentsMargins(5, 5, 5, 5)

        green_button_style = """
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
        """

        file_layout = QHBoxLayout()
        file_layout.setSpacing(5)

        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("CSVファイルを選択してください")
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setMaximumHeight(30)
        file_layout.addWidget(self.file_path_edit, stretch=1)

        self.select_file_btn = QPushButton("ファイル選択")
        self.select_file_btn.clicked.connect(
            lambda: self._run_action_with_status("ファイル選択", self.select_csv_file)
        )
        self.select_file_btn.setStyleSheet(green_button_style)
        file_layout.addWidget(self.select_file_btn)

        self.preview_btn = QPushButton("価格改定プレビュー")
        self.preview_btn.clicked.connect(
            lambda: self._run_action_with_status("価格改定プレビュー", self.preview_csv)
        )
        self.preview_btn.setEnabled(False)
        self.preview_btn.setStyleSheet(green_button_style)
        file_layout.addWidget(self.preview_btn)

        self.execute_btn = QPushButton("価格改定実行")
        self.execute_btn.clicked.connect(
            lambda: self._run_action_with_status("価格改定実行", self.execute_repricing)
        )
        self.execute_btn.setEnabled(False)
        self.execute_btn.setStyleSheet(green_button_style)
        file_layout.addWidget(self.execute_btn)

        self.save_btn = QPushButton("結果をCSV保存")
        self.save_btn.clicked.connect(
            lambda: self._run_action_with_status("結果をCSV保存", self.save_results)
        )
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(green_button_style)
        file_layout.addWidget(self.save_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(25)
        self.progress_bar.setMaximumWidth(160)
        file_layout.addWidget(self.progress_bar)

        file_layout.addStretch()

        self.clear_file_btn = QPushButton("クリア")
        self.clear_file_btn.clicked.connect(self.clear_csv_selection)
        self.clear_file_btn.setEnabled(False)
        file_layout.addWidget(self.clear_file_btn)

        file_outer.addLayout(file_layout)

        self.workflow_status_label = QLabel()
        self.workflow_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.workflow_status_label.setWordWrap(True)
        self.workflow_status_label.setStyleSheet("padding: 2px 0px;")
        self._sync_workflow_status_label()
        file_outer.addWidget(self.workflow_status_label)

        aux_layout = QHBoxLayout()
        self.csv_preview_btn = QPushButton("CSV内容表示")
        self.csv_preview_btn.clicked.connect(self.show_csv_preview)
        self.csv_preview_btn.setEnabled(False)
        aux_layout.addWidget(self.csv_preview_btn)

        self.missing_skus_btn = QPushButton("仕入DB未登録SKU")
        self.missing_skus_btn.setToolTip(
            "読み込んだ在庫CSVのうち、仕入DBに無いSKU、\n"
            "または ASIN が未入力の SKU を一覧表示し、\n"
            "在庫CSVの内容で登録・上書きできます。"
        )
        self.missing_skus_btn.clicked.connect(self.show_missing_inventory_skus_dialog)
        self.missing_skus_btn.setEnabled(False)
        aux_layout.addWidget(self.missing_skus_btn)

        self.keepa_fetch_btn = QPushButton("Keepa取得")
        self.keepa_fetch_btn.clicked.connect(self.fetch_keepa_for_target_rows)
        self.keepa_fetch_btn.setEnabled(False)
        aux_layout.addWidget(self.keepa_fetch_btn)
        aux_layout.addStretch()
        file_outer.addLayout(aux_layout)

        self.pricerstar_drop_panel = QFrame()
        self.pricerstar_drop_panel.setObjectName("pricerstarDropPanel")
        self.pricerstar_drop_panel.setStyleSheet(
            """
            QFrame#pricerstarDropPanel {
                background-color: #1e2a36;
                border: 1px solid #4a6fa5;
                border-radius: 8px;
                margin-top: 4px;
            }
            """
        )
        pricerstar_drop_outer = QVBoxLayout(self.pricerstar_drop_panel)
        pricerstar_drop_outer.setContentsMargins(12, 10, 12, 10)
        pricerstar_drop_outer.setSpacing(8)

        pricerstar_top_row = QHBoxLayout()
        pricerstar_top_row.setSpacing(12)

        self.pricerstar_csv_drag_icon = DraggableFileIconWidget()
        self.pricerstar_csv_drag_icon.set_browser_title_keywords(_PRICETAR_BROWSER_TITLE_KEYWORDS)
        self.pricerstar_csv_drag_icon.set_tooltip_prefix(
            "①「ブラウザで開く」→ ②このアイコンをドラッグしてCSVのドロップ欄へ"
        )
        pricerstar_top_row.addWidget(self.pricerstar_csv_drag_icon)

        pricerstar_text_col = QVBoxLayout()
        pricerstar_text_col.setSpacing(4)
        pricerstar_title = QLabel("プライスター価格改定用CSV")
        pricerstar_title.setStyleSheet("font-size: 11pt; font-weight: bold; color: #b8d4f0;")
        pricerstar_text_col.addWidget(pricerstar_title)

        self._pricerstar_drop_hint_default = (
            "「ブラウザで開く」でプライスターを開き、在庫CSVを取得してください。"
            "改定CSV保存後は左のアイコンをドラッグして送信できます。"
        )
        self.pricerstar_drop_hint = QLabel(self._pricerstar_drop_hint_default)
        self.pricerstar_drop_hint.setWordWrap(True)
        self.pricerstar_drop_hint.setStyleSheet("color: #9eb8d0;")
        pricerstar_text_col.addWidget(self.pricerstar_drop_hint)

        self.pricerstar_drop_filename = QLabel("（CSV保存後に表示）")
        self.pricerstar_drop_filename.setWordWrap(True)
        self.pricerstar_drop_filename.setStyleSheet("color: #e8e8e8; font-family: monospace;")
        pricerstar_text_col.addWidget(self.pricerstar_drop_filename)

        pricerstar_btn_row = QHBoxLayout()
        self.pricerstar_open_browser_btn = QPushButton("ブラウザで開く")
        self.pricerstar_open_browser_btn.setToolTip(
            "プライスター価格改定画面を既定ブラウザで開きます"
        )
        self.pricerstar_open_browser_btn.clicked.connect(
            lambda: self._open_pricetar_repricing_in_browser()
        )
        self.pricerstar_open_browser_btn.setEnabled(True)
        pricerstar_btn_row.addWidget(self.pricerstar_open_browser_btn)

        self.pricerstar_open_folder_btn = QPushButton("保存フォルダを開く")
        self.pricerstar_open_folder_btn.setToolTip("保存したCSVがあるフォルダをエクスプローラーで開きます")
        self.pricerstar_open_folder_btn.clicked.connect(self._open_last_saved_csv_folder)
        self.pricerstar_open_folder_btn.setEnabled(False)
        pricerstar_btn_row.addWidget(self.pricerstar_open_folder_btn)

        pricerstar_btn_row.addStretch()
        pricerstar_text_col.addLayout(pricerstar_btn_row)

        pricerstar_top_row.addLayout(pricerstar_text_col, 1)
        pricerstar_drop_outer.addLayout(pricerstar_top_row)

        self.pricerstar_drop_panel.setVisible(True)
        file_outer.addWidget(self.pricerstar_drop_panel)

        self.layout().addWidget(file_group)

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
                    self.missing_skus_btn.setEnabled(True)
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
        self._manual_export_prices = {}
        self.active_days_filter = None
        self.file_path_edit.clear()

        # ボタン状態を初期化
        self.csv_preview_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.missing_skus_btn.setEnabled(False)
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
        self._update_workflow_status("ワークフロー: 未実行", emphasize=False)
        self._set_pricerstar_csv_file("")

    def _set_pricerstar_csv_file(self, file_path: str) -> None:
        """CSV保存後、プライスターへドラッグするファイルをパネルに表示する。"""
        path = str(file_path or "").strip()
        self._last_saved_csv_path = path if path and Path(path).is_file() else None
        if not self._last_saved_csv_path:
            if hasattr(self, "pricerstar_csv_drag_icon"):
                self.pricerstar_csv_drag_icon.clear_file()
            if hasattr(self, "pricerstar_drop_filename"):
                self.pricerstar_drop_filename.setText("（CSV保存後に表示）")
            if hasattr(self, "pricerstar_drop_hint"):
                self.pricerstar_drop_hint.setText(self._pricerstar_drop_hint_default)
            if hasattr(self, "pricerstar_open_folder_btn"):
                self.pricerstar_open_folder_btn.setEnabled(False)
            return

        self.pricerstar_csv_drag_icon.set_file_path(self._last_saved_csv_path)
        self.pricerstar_drop_filename.setText(self._last_saved_csv_path)
        self.pricerstar_drop_hint.setText(
            "「ブラウザで開く」後、左のCSVアイコンをドラッグしてプライスターへ送ってください"
        )
        self.pricerstar_open_folder_btn.setEnabled(True)

    def _get_pricetar_repricing_url(self) -> str:
        try:
            return get_pricetar_repricing_url()
        except Exception:
            return "https://jp3.pricetar.com/seller/product/csvproductedit"

    def _open_pricetar_repricing_in_browser(self) -> None:
        """プライスター価格改定画面を既定ブラウザで開く。"""
        repricing_url = self._get_pricetar_repricing_url()
        try:
            QDesktopServices.openUrl(QUrl(repricing_url))
        except Exception as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"ブラウザでプライスターを開けませんでした:\n{e}\n\n"
                f"手動で以下にアクセスしてください:\n{repricing_url}",
            )
            return

        self.pricerstar_drop_hint.setText(
            "ブラウザでプライスターを開きました。"
            "左のCSVアイコンをドラッグしてドロップ欄へ送ってください。"
            "（ドラッグ中はブラウザが最前面に出ます）"
        )
        schedule_bring_browser_to_front(
            _PRICETAR_BROWSER_TITLE_KEYWORDS,
            pin_topmost_until_ms=8000,
        )

    def _open_last_saved_csv_folder(self) -> None:
        """直近に保存した価格改定CSVのフォルダを開く。"""
        path = self._last_saved_csv_path
        if not path or not Path(path).is_file():
            QMessageBox.information(self, "情報", "保存済みのCSVがありません。\n先に「結果をCSV保存」を実行してください。")
            return
        folder = str(Path(path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
