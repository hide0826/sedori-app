#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一括リネーム mixin。"""
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


class ReceiptRenameMixin:
    def bulk_rename_receipts(self):
        """一括リネーム: 
        - レシート: yyyy-mm-dd-店舗コード-連番.jpg
        - 保証書: yyyy-mm-dd-war-店舗コード-連番.jpg
        """
        from pathlib import Path
        import shutil
        from datetime import datetime
        import re
        
        # 全レシートを取得
        receipts = self.receipt_db.find_by_date_and_store(None)
        if not receipts:
            QMessageBox.information(self, "一括リネーム", "リネームするレシートがありません。")
            return
        
        # レシートと保証書の件数をカウント
        receipt_count = 0
        warranty_count = 0
        for receipt in receipts:
            ocr_text = receipt.get('ocr_text') or ""
            if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                warranty_count += 1
            else:
                receipt_count += 1
        
        # 確認ダイアログ
        reply = QMessageBox.question(
            self,
            "一括リネーム",
            f"{len(receipts)} 件の画像を一括リネームします。\n"
            f"レシート: {receipt_count} 件 (形式: yyyy-mm-dd-店舗コード-連番.jpg)\n"
            f"保証書: {warranty_count} 件 (形式: yyyy-mm-dd-war-店舗コード-連番.jpg)\n\n"
            f"続行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        
        renamed_count = 0
        skipped_count = 0
        error_count = 0
        error_messages = []
        
        # 日付・店舗コード・種別ごとの連番を管理
        # {(date_str, store_code, doc_type): 連番}
        date_store_counter = {}
        
        for receipt in receipts:
            try:
                receipt_id = receipt.get('id')
                
                # 種別判定（レシートと保証書の両方を対象）
                ocr_text = receipt.get('ocr_text') or ""
                doc_type = "レシート"
                if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                    doc_type = "保証書"
                
                # 日付を取得
                purchase_date = receipt.get('purchase_date') or ""
                if not purchase_date:
                    skipped_count += 1
                    error_messages.append(f"{doc_type}ID {receipt_id}: 日付が設定されていません")
                    continue
                
                # 日付を yyyy-mm-dd 形式に正規化
                date_str = purchase_date.strip()
                if " " in date_str:
                    date_str = date_str.split(" ")[0]
                date_str = date_str.replace("/", "-")
                # yyyy-mm-dd 形式に変換
                try:
                    if "/" in date_str:
                        date_parts = date_str.split("/")
                        if len(date_parts) == 3:
                            date_str = f"{date_parts[0]}-{date_parts[1].zfill(2)}-{date_parts[2].zfill(2)}"
                    elif "-" in date_str:
                        date_parts = date_str.split("-")
                        if len(date_parts) == 3:
                            date_str = f"{date_parts[0]}-{date_parts[1].zfill(2)}-{date_parts[2].zfill(2)}"
                    # yyyy-mm-dd 形式か確認
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                        skipped_count += 1
                        error_messages.append(f"{doc_type}ID {receipt_id}: 日付形式が不正です: {purchase_date}")
                        continue
                except Exception:
                    skipped_count += 1
                    error_messages.append(f"{doc_type}ID {receipt_id}: 日付の解析に失敗しました: {purchase_date}")
                    continue
                
                # 店舗コードを取得
                store_code = receipt.get('store_code') or ""
                if not store_code:
                    skipped_count += 1
                    error_messages.append(f"{doc_type}ID {receipt_id}: 店舗コードが設定されていません")
                    continue
                
                # 店舗コードのみを取得（表示ラベルから抽出）
                store_code_clean = str(store_code).strip()
                if " " in store_code_clean:
                    store_code_clean = store_code_clean.split(" ")[0]
                
                if not store_code_clean:
                    skipped_count += 1
                    error_messages.append(f"{doc_type}ID {receipt_id}: 店舗コードが空です")
                    continue
                
                # 連番を決定（同じ日付・店舗コード・種別の連番を管理）
                key = (date_str, store_code_clean, doc_type)
                if key not in date_store_counter:
                    date_store_counter[key] = 0
                date_store_counter[key] += 1
                sequence_number = date_store_counter[key]
                
                # 画像ファイルパスを取得
                file_path = receipt.get('original_file_path') or receipt.get('file_path', '')
                if not file_path:
                    skipped_count += 1
                    error_messages.append(f"{doc_type}ID {receipt_id}: 画像ファイルパスが設定されていません")
                    continue
                
                old_image_file = Path(file_path)
                if not old_image_file.exists():
                    # ファイルが見つからない場合、既にリネームされている可能性がある
                    # 同じディレクトリ内で新しいファイル名パターンに一致するファイルを検索
                    directory = old_image_file.parent
                    if directory.exists():
                        # 新しいファイル名パターンを生成（連番は1から試行）
                        extension = old_image_file.suffix or '.jpg'
                        found_file = None
                        for seq in range(1, 100):  # 最大99まで試行
                            if doc_type == "保証書":
                                search_pattern = f"{date_str}-war-{store_code_clean}-{seq:02d}{extension}"
                            else:
                                search_pattern = f"{date_str}-{store_code_clean}-{seq:02d}{extension}"
                            candidate_file = directory / search_pattern
                            if candidate_file.exists():
                                found_file = candidate_file
                                break
                        
                        if found_file:
                            # 既にリネームされたファイルが見つかった場合、データベースを更新
                            update_data = {"file_path": str(found_file)}
                            if receipt.get('original_file_path'):
                                update_data["original_file_path"] = str(found_file)
                            self.receipt_db.update_receipt(receipt_id, update_data)
                            renamed_count += 1
                            continue
                    
                    # ファイルが見つからず、既にリネームされたファイルも見つからない場合
                    skipped_count += 1
                    error_messages.append(f"{doc_type}ID {receipt_id}: 画像ファイルが見つかりません: {file_path}")
                    continue
                
                # 新しいファイル名を生成
                extension = old_image_file.suffix or '.jpg'
                if doc_type == "保証書":
                    # 保証書: yyyy-mm-dd-war-店舗コード-連番.jpg
                    new_image_name = f"{date_str}-war-{store_code_clean}-{sequence_number:02d}{extension}"
                else:
                    # レシート: yyyy-mm-dd-店舗コード-連番.jpg
                    new_image_name = f"{date_str}-{store_code_clean}-{sequence_number:02d}{extension}"
                new_image_path = old_image_file.parent / new_image_name
                
                # 既に同じファイル名の場合はスキップ
                if new_image_path == old_image_file:
                    skipped_count += 1
                    continue
                
                # 同名ファイルが存在する場合は連番を増やす
                while new_image_path.exists():
                    date_store_counter[key] += 1
                    sequence_number = date_store_counter[key]
                    new_image_name = f"{date_str}-{store_code_clean}-{sequence_number:02d}{extension}"
                    new_image_path = old_image_file.parent / new_image_name
                
                # ファイルをリネーム
                try:
                    shutil.move(str(old_image_file), str(new_image_path))
                    
                    # 元のファイルパスも更新（original_file_pathがある場合）
                    original_file_path = receipt.get('original_file_path')
                    update_data = {"file_path": str(new_image_path)}
                    
                    if original_file_path:
                        original_file = Path(original_file_path)
                        if original_file.exists() and original_file != old_image_file:
                            # original_file_pathが存在し、file_pathと異なる場合は別途リネーム
                            new_original_path = original_file.parent / new_image_name
                            if new_original_path != original_file:
                                try:
                                    shutil.move(str(original_file), str(new_original_path))
                                    update_data["original_file_path"] = str(new_original_path)
                                except Exception:
                                    # 元のファイルのリネーム失敗は警告のみ（file_pathは更新済み）
                                    pass
                        elif original_file == old_image_file:
                            # original_file_pathとfile_pathが同じ場合は、同じ新しいパスに更新
                            update_data["original_file_path"] = str(new_image_path)
                        else:
                            # original_file_pathが存在しない場合は、file_pathと同じ新しいパスに更新
                            update_data["original_file_path"] = str(new_image_path)
                    else:
                        # original_file_pathが存在しない場合は、file_pathと同じ新しいパスに設定
                        update_data["original_file_path"] = str(new_image_path)
                    
                    # DBを更新（file_pathとoriginal_file_pathの両方を更新）
                    self.receipt_db.update_receipt(receipt_id, update_data)
                    
                    renamed_count += 1
                except Exception as e:
                    error_count += 1
                    error_messages.append(f"{doc_type}ID {receipt_id}: リネームエラー: {str(e)}")
                    continue
                    
            except Exception as e:
                error_count += 1
                doc_type_fallback = receipt.get('ocr_text', '')
                if "保証書" in doc_type_fallback or "保証期間" in doc_type_fallback or "保証規定" in doc_type_fallback:
                    doc_type_fallback = "保証書"
                else:
                    doc_type_fallback = "レシート"
                error_messages.append(f"{doc_type_fallback}ID {receipt.get('id', '不明')}: 処理エラー: {str(e)}")
                continue
        
        # 結果を表示
        result_message = f"一括リネーム完了\n\n"
        result_message += f"リネーム成功: {renamed_count} 件\n"
        result_message += f"スキップ: {skipped_count} 件\n"
        result_message += f"エラー: {error_count} 件"
        
        if error_messages:
            result_message += f"\n\nエラー詳細:\n" + "\n".join(error_messages[:10])
            if len(error_messages) > 10:
                result_message += f"\n... 他 {len(error_messages) - 10} 件"
        
        QMessageBox.information(self, "一括リネーム", result_message)
        
        # リネーム済みファイルを検出してデータベースを更新（スキップされたファイルがある場合）
        if skipped_count > 0:
            reply = QMessageBox.question(
                self,
                "リネーム済みファイルの検出",
                f"{skipped_count} 件のファイルが見つかりませんでした。\n"
                f"既にリネームされたファイルを検出してデータベースを更新しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.detect_and_update_renamed_files()
        
        # レシート一覧を更新
        self.refresh_receipt_list()
        self._mark_bulk_rename_completed()
    
    def detect_and_update_renamed_files(self):
        """リネーム済みファイルを検出してデータベースを更新"""
        from pathlib import Path
        import re
        
        # 現在のレシート一覧・保証書一覧に対応するレシートのみ取得
        receipts = self._get_current_receipts_from_tables()
        if not receipts:
            QMessageBox.information(self, "リネーム済みファイル検出", "対象のレシートがありません。")
            return
        
        updated_count = 0
        not_found_count = 0
        error_count = 0
        error_messages = []
        
        for receipt in receipts:
            try:
                receipt_id = receipt.get('id')
                
                # 種別判定
                ocr_text = receipt.get('ocr_text') or ""
                doc_type = "レシート"
                if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                    doc_type = "保証書"
                
                # 日付を取得
                purchase_date = receipt.get('purchase_date') or ""
                if not purchase_date:
                    continue
                
                # 日付を yyyy-mm-dd 形式に正規化
                date_str = purchase_date.strip()
                if " " in date_str:
                    date_str = date_str.split(" ")[0]
                date_str = date_str.replace("/", "-")
                try:
                    if "/" in date_str:
                        date_parts = date_str.split("/")
                        if len(date_parts) == 3:
                            date_str = f"{date_parts[0]}-{date_parts[1].zfill(2)}-{date_parts[2].zfill(2)}"
                    elif "-" in date_str:
                        date_parts = date_str.split("-")
                        if len(date_parts) == 3:
                            date_str = f"{date_parts[0]}-{date_parts[1].zfill(2)}-{date_parts[2].zfill(2)}"
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                        continue
                except Exception:
                    continue
                
                # 店舗コードを取得
                store_code = receipt.get('store_code') or ""
                if not store_code:
                    continue
                
                store_code_clean = str(store_code).strip()
                if " " in store_code_clean:
                    store_code_clean = store_code_clean.split(" ")[0]
                
                if not store_code_clean:
                    continue
                
                # 現在のファイルパスを取得
                file_path = receipt.get('original_file_path') or receipt.get('file_path', '')
                if not file_path:
                    continue
                
                old_image_file = Path(file_path)
                
                # ファイルが存在する場合はスキップ（既に正しいパス）
                if old_image_file.exists():
                    continue
                
                # 同じディレクトリ内でリネーム済みファイルを検索
                directory = old_image_file.parent
                if not directory.exists():
                    not_found_count += 1
                    continue
                
                # 新しいファイル名パターンで検索
                extension = old_image_file.suffix or '.jpg'
                found_file = None
                
                # 連番1から99まで試行
                for seq in range(1, 100):
                    if doc_type == "保証書":
                        search_pattern = f"{date_str}-war-{store_code_clean}-{seq:02d}{extension}"
                    else:
                        search_pattern = f"{date_str}-{store_code_clean}-{seq:02d}{extension}"
                    candidate_file = directory / search_pattern
                    if candidate_file.exists():
                        found_file = candidate_file
                        break
                
                if found_file:
                    # リネーム済みファイルが見つかった場合、データベースを更新
                    update_data = {"file_path": str(found_file)}
                    if receipt.get('original_file_path'):
                        update_data["original_file_path"] = str(found_file)
                    self.receipt_db.update_receipt(receipt_id, update_data)
                    updated_count += 1
                else:
                    not_found_count += 1
                    error_messages.append(f"{doc_type}ID {receipt_id}: リネーム済みファイルが見つかりません")
                    
            except Exception as e:
                error_count += 1
                doc_type_fallback = receipt.get('ocr_text', '')
                if "保証書" in doc_type_fallback or "保証期間" in doc_type_fallback or "保証規定" in doc_type_fallback:
                    doc_type_fallback = "保証書"
                else:
                    doc_type_fallback = "レシート"
                error_messages.append(f"{doc_type_fallback}ID {receipt.get('id', '不明')}: 処理エラー: {str(e)}")
                continue
        
        # 結果を表示
        result_message = f"リネーム済みファイル検出完了\n\n"
        result_message += f"データベース更新: {updated_count} 件\n"
        result_message += f"見つからなかった: {not_found_count} 件\n"
        result_message += f"エラー: {error_count} 件"
        
        if error_messages and len(error_messages) <= 10:
            result_message += f"\n\n詳細:\n" + "\n".join(error_messages)
        elif error_messages:
            result_message += f"\n\n詳細:\n" + "\n".join(error_messages[:10])
            result_message += f"\n... 他 {len(error_messages) - 10} 件"
        
        QMessageBox.information(self, "リネーム済みファイル検出", result_message)
        
        # レシート一覧を更新
        self.refresh_receipt_list()

