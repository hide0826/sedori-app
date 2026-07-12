#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フォルダ選択・OCR実行 mixin。"""
from __future__ import annotations

import os
import re
import sys
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QTextEdit, QDateEdit, QSpinBox,
    QScrollArea, QSizePolicy, QStyledItemDelegate,
    QSplitter, QListWidget, QListWidgetItem, QMenu,
    QFormLayout, QApplication, QCheckBox, QProgressDialog,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QSettings, QTimer, QUrl, QCoreApplication
from PySide6.QtGui import QPixmap, QTransform, QColor, QDesktopServices, QClipboard

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_evidence_completed

try:
    from services.receipt_service import ReceiptService
    from services.receipt_matching_service import ReceiptMatchingService
    from services.purchase_break_even import compute_break_even_for_record
    from services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
except Exception:
    from desktop.services.receipt_service import ReceiptService
    from desktop.services.receipt_matching_service import ReceiptMatchingService
    from desktop.services.purchase_break_even import compute_break_even_for_record
    from desktop.services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from desktop.services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
from database.receipt_db import ReceiptDatabase
from database.inventory_db import InventoryDatabase
from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from database.product_db import ProductDatabase
from database.route_db import RouteDatabase

from .support import (
    ReceiptOCRThread,
    ReceiptSnapshotDialog,
    _RECEIPT_ACTION_TO_PIPELINE_STEP,
    _RECEIPT_WORKFLOW_PIPELINE_SEGMENTS,
    _format_receipt_status_prefix_html,
    _format_receipt_workflow_pipeline_html,
    AccountTitleDelegate,
    StoreNameDelegate,
    WarrantyProductDelegate,
)


class ReceiptOcrMixin:
    def select_image(self):
        """画像ファイルを選択"""
        # デフォルトディレクトリを設定（暫定的）
        default_dir = str(self.current_folder) if self.current_folder else r"D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "レシート画像を選択",
            default_dir,
            "画像ファイル (*.jpg *.jpeg *.png *.bmp)"
        )
        if file_path:
            self.current_folder = Path(file_path).parent
            self.image_path_label.setText(f"選択: {Path(file_path).name}")
            self.process_image(file_path)

    def load_default_folder(self):
        """保存されたデフォルトフォルダを読み込む"""
        try:
            s = QSettings("HIRIO", "SedoriDesktopApp")
            default_folder_path = s.value("receipt/default_folder", "")
            if default_folder_path and Path(default_folder_path).exists():
                self.default_folder = Path(default_folder_path)
            else:
                self.default_folder = None
        except Exception as e:
            logger.error(f"デフォルトフォルダ読み込みエラー: {e}")
            self.default_folder = None
    
    def set_default_folder(self):
        """デフォルトフォルダを設定"""
        if self._is_batch_ocr_busy():
            QMessageBox.information(
                self, "デフォルトフォルダ設定", "全件OCR実行中は設定を変更できません。"
            )
            return
        # 現在のデフォルトフォルダまたは現在のフォルダを初期値として使用
        initial_dir = None
        if self.default_folder and self.default_folder.exists():
            initial_dir = str(self.default_folder)
        elif self.current_folder and self.current_folder.exists():
            initial_dir = str(self.current_folder)
        else:
            initial_dir = r"D:\せどり総合"
        
        folder = QFileDialog.getExistingDirectory(
            self,
            "デフォルトフォルダを選択",
            initial_dir,
        )
        
        if not folder:
            return
        
        folder_path = Path(folder)
        if not folder_path.exists():
            QMessageBox.warning(self, "エラー", "選択したフォルダが存在しません。")
            return
        
        # デフォルトフォルダを保存
        try:
            s = QSettings("HIRIO", "SedoriDesktopApp")
            s.setValue("receipt/default_folder", str(folder_path))
            self.default_folder = folder_path
            QMessageBox.information(
                self, "設定完了",
                f"デフォルトフォルダを設定しました:\n{str(folder_path)}"
            )
            # フォルダラベルを更新
            self.update_folder_label()
        except Exception as e:
            logger.error(f"デフォルトフォルダ保存エラー: {e}")
            QMessageBox.warning(self, "エラー", f"デフォルトフォルダの保存に失敗しました:\n{str(e)}")
    
    def update_folder_label(self):
        """フォルダラベルを更新"""
        if not hasattr(self, "folder_label"):
            return
        if self.current_folder and self.current_folder.exists():
            # 画像ファイル数をカウント
            image_paths = []
            try:
                for entry in sorted(self.current_folder.iterdir()):
                    if not entry.is_file():
                        continue
                    suffix = entry.suffix.lower()
                    if suffix in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"):
                        image_paths.append(str(entry))
            except Exception:
                pass
            self.folder_label.setText(f"{str(self.current_folder)} ({len(image_paths)}件)")
        elif self.default_folder and self.default_folder.exists():
            self.folder_label.setText(f"デフォルト: {str(self.default_folder)}")
        else:
            self.folder_label.setText("未選択")
    
    def select_folder_for_batch(self):
        """フォルダを選択して、フォルダ内の全画像をOCRキューに追加"""
        # デフォルトフォルダを優先的に使用
        if self.default_folder and self.default_folder.exists():
            default_dir = str(self.default_folder)
        elif self.current_folder and self.current_folder.exists():
            default_dir = str(self.current_folder)
        else:
            default_dir = r"D:\せどり総合"
        
        folder = QFileDialog.getExistingDirectory(
            self,
            "レシート画像フォルダを選択",
            default_dir,
        )
        if not folder:
            return
        self._reset_post_rename_workflow_gate()
        self.current_folder = Path(folder)
        
        # OCRキューを更新
        image_paths: List[str] = []
        for entry in sorted(self.current_folder.iterdir()):
            if not entry.is_file():
                continue
            suffix = entry.suffix.lower()
            if suffix in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"):
                image_paths.append(str(entry))
        
        self.ocr_queue = image_paths
        self.update_folder_label()
    
    def process_selected_file(self):
        """OCRキューから最初のファイルを処理（フォルダ選択後）"""
        if self._is_batch_ocr_busy():
            QMessageBox.information(
                self, "OCR処理", "全件OCR実行中は単体OCRを開始できません。"
            )
            return
        if not self.ocr_queue:
            QMessageBox.information(self, "情報", "処理する画像がありません。先に「フォルダ選択」を行ってください。")
            return
        # キューから最初のファイルを処理
        path = self.ocr_queue[0]
        self.process_image(path)

    def start_batch_ocr(self):
        """選択されたフォルダ内の画像を順番にOCR処理"""
        if not self.ocr_queue:
            QMessageBox.information(self, "情報", "一括処理する画像がありません。先に「フォルダ選択」を行ってください。")
            return
        if self.batch_running:
            QMessageBox.information(self, "情報", "すでに一括OCR処理を実行中です。")
            return
        self._reset_post_rename_workflow_gate()
        self.batch_running = True
        self.batch_total_count = len(self.ocr_queue)
        self.batch_processed_count = 0
        self._sync_action_buttons_state()
        self._update_workflow_status("ワークフロー: 全件OCR実行中", emphasize=True)
        self._process_next_in_queue()

    def _process_next_in_queue(self):
        """OCRキューから次の1枚を取り出して処理"""
        if not self.ocr_queue:
            self.batch_running = False
            self._sync_action_buttons_state()
            if hasattr(self, "folder_label"):
                self.folder_label.setText(f"{str(self.current_folder)} - 一括OCR完了")
            # 全件OCR完了後は次の工程③（一括マッチング）へ
            self._workflow_active_step = 3
            self._update_workflow_status("ワークフロー: 待機", emphasize=False)
            QMessageBox.information(self, "一括OCR完了", "選択されたフォルダ内のすべての画像の処理が完了しました。")
            return
        next_path = self.ocr_queue.pop(0)
        remaining = len(self.ocr_queue)
        # 進捗率を計算（処理済み件数 / 全体件数）
        # 現在処理中の画像を含めて計算（処理済み + 1）
        current_processed = self.batch_processed_count + 1
        progress_percent = int((current_processed / self.batch_total_count) * 100) if self.batch_total_count > 0 else 0
        if hasattr(self, "folder_label"):
            self.folder_label.setText(f"{str(self.current_folder)} - 処理中: {Path(next_path).name} （進捗: {progress_percent}% - {current_processed}/{self.batch_total_count}件、残り {remaining} 件）")
        self.process_image(next_path)
    
    def process_image(self, image_path: str):
        """画像を処理（OCR実行）"""
        if hasattr(self, 'process_btn'):
            self.process_btn.setEnabled(False)
            self.process_btn.setText("処理中...")
        
        self.ocr_thread = ReceiptOCRThread(self.receipt_service, image_path)
        self.ocr_thread.finished.connect(self.on_ocr_finished)
        self.ocr_thread.error.connect(self.on_ocr_error)
        self.ocr_thread.start()
    
    def on_ocr_finished(self, result: Dict[str, Any]):
        """OCR完了時の処理"""
        if hasattr(self, 'process_btn'):
            self.process_btn.setEnabled(True)
            self.process_btn.setText("OCR処理")
        
        self.current_receipt_id = result.get('id')
        self.current_receipt_data = result
        
        # OCR結果を表示（purchase_dateは yyyy/MM/dd で保存される想定だが、後方互換で両方対応）
        purchase_date = result.get('purchase_date')
        if purchase_date:
            try:
                # まず yyyy/MM/dd を試す
                date = QDate.fromString(purchase_date, "yyyy/MM/dd")
                if not date.isValid():
                    # 古いデータなど yyyy-MM-dd の場合も考慮
                    date = QDate.fromString(purchase_date.replace("/", "-"), "yyyy-MM-dd")
                if date.isValid():
                    if hasattr(self, 'date_edit'):
                        self.date_edit.setDate(date)
            except Exception:
                pass
        
        # 時刻を表示
        purchase_time = result.get('purchase_time')
        if hasattr(self, 'time_edit'):
            self.time_edit.setText(purchase_time or "")
        
        if hasattr(self, 'store_name_edit'):
            self.store_name_edit.setText(result.get('store_name_raw') or "")
        if hasattr(self, 'phone_edit'):
            self.phone_edit.setText(result.get('phone_number') or "")
        if hasattr(self, 'total_edit'):
            self.total_edit.setText(str(result.get('total_amount') or ""))
        if hasattr(self, 'discount_edit'):
            self.discount_edit.setText(str(result.get('discount_amount') or ""))
        
        # レジ袋金額を表示
        plastic_bag_amount = result.get('plastic_bag_amount')
        if hasattr(self, 'plastic_bag_edit'):
            self.plastic_bag_edit.setText(str(plastic_bag_amount) if plastic_bag_amount is not None else "")
        
        # 店舗コード候補を読み込み
        self.load_store_codes()
        
        # 仕入DBから自動検索・入力
        self.search_from_purchase_db()

        # 仕入データから自動マッチング候補を推定してDBにも反映
        try:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', []) if self.product_widget else []
            if purchase_records:
                candidates = self.matching_service.find_match_candidates(
                    self.current_receipt_data or result,
                    purchase_records,
                    preferred_store_code=self.store_code_combo.currentData() if hasattr(self, 'store_code_combo') else None,
                )
                if candidates:
                    cand = candidates[0]
                    updates = {}
                    if cand.store_code:
                        # 店舗コードをコンボにも反映
                        if hasattr(self, 'store_code_combo'):
                            idx = self.store_code_combo.findData(cand.store_code)
                            if idx >= 0:
                                self.store_code_combo.setCurrentIndex(idx)
                        updates["store_code"] = cand.store_code
                    if getattr(cand, 'account_title', None):
                        updates["account_title"] = cand.account_title
                    if updates and self.current_receipt_id:
                        self.receipt_db.update_receipt(self.current_receipt_id, updates)
                    # 経費先マッチ時：経費先一覧の登録番号が空ならレシートの登録番号を入力
                    if getattr(cand, 'account_title', None) and cand.store_code:
                        try:
                            dest = self.store_db.get_expense_destination_by_code(cand.store_code)
                            reg_from_receipt = (result.get("registration_number") or "").strip()
                            if dest and reg_from_receipt and not (dest.get("registration_number") or "").strip():
                                self.store_db.update_expense_destination_registration_number(dest["id"], reg_from_receipt)
                        except Exception:
                            pass
        except Exception as e:
            # 自動マッチング失敗は致命的ではないのでログのみにする
            try:
                from pathlib import Path
                log_path = Path(__file__).resolve().parents[2] / "desktop_error.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    from datetime import datetime
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ReceiptWidget auto-match error: {e}\n")
            except Exception:
                pass

        if hasattr(self, 'match_btn'):
            self.match_btn.setEnabled(True)
        if hasattr(self, 'view_image_btn'):
            self.view_image_btn.setEnabled(True)
        # 一括処理中でない場合のみ通知を表示
        if self.notifications_enabled and not self.batch_running:
            QMessageBox.information(self, "OCR完了", "レシート情報を抽出しました。")
        self.receipt_processed.emit(result)
        # レシート一覧にも即反映
        self.refresh_receipt_list()

        # 一括処理中であれば次の画像を処理
        if self.batch_running:
            self.batch_processed_count += 1
            self._process_next_in_queue()
    
    def on_ocr_error(self, error_msg: str):
        """OCRエラー時の処理"""
        if hasattr(self, 'process_btn'):
            self.process_btn.setEnabled(True)
            self.process_btn.setText("OCR処理")
        # 一括処理中でない場合のみ通知を表示
        if self.notifications_enabled and not self.batch_running:
            QMessageBox.critical(self, "OCRエラー", f"OCR処理に失敗しました:\n{error_msg}")
        # 一括処理中ならスキップして次へ
        if self.batch_running:
            self.batch_processed_count += 1
            self._process_next_in_queue()
    
    def reprocess_ocr_for_receipt(self, receipt_id: int, receipt: Dict[str, Any]):
        """選択されたレシートに対してOCR処理を再実行"""
        if self._is_batch_ocr_busy():
            QMessageBox.information(self, "OCR処理", "全件OCR実行中は再OCRできません。")
            return
        image_path = receipt.get('file_path') or receipt.get('original_file_path')
        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        # 既存のレシートデータを削除（OCR結果を上書きするため）
        try:
            self.receipt_db.delete_receipt(receipt_id)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"既存データの削除に失敗しました: {e}")
            return
        
        # OCR処理を実行
        self.process_image(image_path)
    
