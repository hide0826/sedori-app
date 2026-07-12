#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""レシート一覧・差額表示 mixin。"""
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


class ReceiptTableMixin:
    def _format_store_code_label(self, store_code: Optional[str], fallback_name: str = "") -> str:
        """店舗コードの表示ラベルを生成（新店舗コード + 店舗名）

        引数 store_code には旧仕入先コードが渡ってくる場合もあるため、
        DB から店舗情報を取得した際は stores.store_code を優先的に表示コードとして使用する。
        """
        original_code = (store_code or "").strip()
        code = original_code
        name = ""
        if code:
            if code not in self._store_name_cache:
                try:
                    # 店舗コード(store_code)を優先し、互換性のため仕入れ先コードも許容
                    store = self.store_db.get_store_by_code(code)
                    display_code = code
                    display_name = ""
                    if store:
                        # 表示用コードは stores.store_code を優先（なければ元のコード）
                        display_code = (store.get("store_code") or code).strip() or code
                        display_name = (store.get("store_name") or "").strip()
                    self._store_name_cache[code] = (display_code, display_name)
                except Exception:
                    self._store_name_cache[code] = (code, "")
            cached = self._store_name_cache.get(code)
            if isinstance(cached, tuple):
                code, name = cached
            else:
                name = cached or ""
        if not name:
            name = (fallback_name or "").strip()
        if code and name:
            return f"{code} {name}"
        return code or name

    @staticmethod
    def _format_price_difference_display(difference: Any) -> tuple[str, str]:
        """差額ラベル用の表示文言と色を返す（±30円以内は OK）"""
        try:
            diff_int = int(round(float(difference)))
        except (ValueError, TypeError):
            return "差額: —", "#666666"
        if is_acceptable_price_difference(diff_int):
            return "差額: OK", "#4CAF50"
        if diff_int == 0:
            return "差額: ¥0", "#666666"
        color = "#FF6B6B" if diff_int > 0 else "#4CAF50"
        return f"差額: ¥{diff_int:,}", color

    def _compute_linked_sku_total(
        self,
        linked_skus: List[str],
        purchase_records: List[Dict[str, Any]],
    ) -> int:
        """紐付けSKUの仕入金額合計（仕入れ個数 × 仕入れ価格）"""
        sku_total = 0
        for sku in linked_skus:
            for record in purchase_records:
                record_sku = record.get('SKU') or record.get('sku', '')
                if record_sku and record_sku.strip() == sku:
                    price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                    try:
                        price = float(price) if price else 0
                    except (ValueError, TypeError):
                        price = 0
                    quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                    try:
                        quantity = float(quantity) if quantity else 1
                    except (ValueError, TypeError):
                        quantity = 1
                    sku_total += price * quantity
                    break
        return int(round(sku_total))

    def _get_effective_price_difference(
        self,
        receipt: Dict[str, Any],
        updates: Dict[str, Any],
        purchase_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[int]:
        """updates / DB / 紐付けSKU から差額を取得"""
        if updates.get("price_difference") is not None:
            try:
                return int(round(float(updates["price_difference"])))
            except (ValueError, TypeError):
                pass
        if receipt.get("price_difference") is not None:
            try:
                return int(round(float(receipt["price_difference"])))
            except (ValueError, TypeError):
                pass
        if not purchase_records:
            return None
        linked_text = updates.get("linked_skus") or receipt.get("linked_skus") or ""
        linked_skus = [s.strip() for s in linked_text.split(",") if s.strip()]
        if not linked_skus:
            return None
        sku_total = self._compute_linked_sku_total(linked_skus, purchase_records)
        receipt_total = updates.get("total_amount")
        if receipt_total is None:
            receipt_total = receipt.get("total_amount") or 0
        try:
            receipt_total = int(receipt_total) if receipt_total else 0
        except (ValueError, TypeError):
            receipt_total = 0
        return int(sku_total - receipt_total)

    def _apply_store_name_for_acceptable_difference(
        self,
        receipt: Dict[str, Any],
        updates: Dict[str, Any],
        purchase_records: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """差額が許容範囲内のとき、店舗名を店舗コード列と同じラベルに DB 保存用に揃える"""
        diff = self._get_effective_price_difference(receipt, updates, purchase_records)
        if not is_acceptable_price_difference(diff):
            return

        store_code = updates.get("store_code") or receipt.get("store_code") or ""
        store_code = str(store_code).strip()
        if " " in store_code:
            store_code = store_code.split(" ")[0]
        if not store_code:
            return

        label = self._format_store_code_label(store_code, receipt.get("store_name_raw") or "")
        if label and updates.get("store_name_raw") != label:
            updates["store_name_raw"] = label

    @staticmethod
    def _normalize_purchase_date_text(value: Any) -> Optional[str]:
        """仕入日を yyyy/MM/dd 形式に正規化"""
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("年", "/").replace("月", "/").replace("日", "")
        text = text.replace(".", "/").replace("-", "/")
        if "T" in text:
            text = text.split("T", 1)[0]
        if " " in text:
            text = text.split(" ", 1)[0]
        match = re.search(r"(20\d{2})\D*(\d{1,2})\D*(\d{1,2})", text)
        if match:
            y, m, d = match.groups()
            return f"{int(y):04d}/{int(m):02d}/{int(d):02d}"
        return None

    def _store_code_from_item(self, item: Optional[QTableWidgetItem]) -> str:
        """店舗コードセルから実際のコードのみを取得"""
        if not item:
            return ""
        data = item.data(Qt.UserRole)
        if data:
            return str(data).strip()
        text = item.text().strip()
        return text.split(" ")[0] if text else ""
    
    @staticmethod
    def _is_receipt_document(receipt: Dict[str, Any]) -> bool:
        """OCRテキストからレシート（保証書以外）か判定"""
        ocr_text = receipt.get('ocr_text') or ""
        if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
            return False
        return True

    @staticmethod
    def _extract_purchase_date_key(purchase_date: str) -> Optional[str]:
        """仕入日文字列から yyyy/mm/dd キーを抽出（日付異常検出・修復用）"""
        if not purchase_date:
            return None
        date_only = str(purchase_date).strip()
        if " " in date_only:
            date_only = date_only.split(" ")[0]
        date_only = date_only.replace("-", "/")
        if not re.match(r"^\d{4}/\d{1,2}/\d{1,2}", date_only):
            return None
        parts = date_only.split("/")
        try:
            return f"{int(parts[0]):04d}/{int(parts[1]):02d}/{int(parts[2]):02d}"
        except (ValueError, IndexError):
            return None

    def _get_majority_purchase_date_key(self, date_counter, threshold: float) -> Optional[str]:
        """他レシートの多数派日付（50%以上）を返す。該当なしなら最多出現日"""
        if not date_counter:
            return None
        for date_key, count in date_counter.most_common():
            if count >= threshold:
                return date_key
        return date_counter.most_common(1)[0][0]

    def _offer_purchase_date_auto_repair(
        self,
        receipts: List[Dict[str, Any]],
        date_counter,
        threshold: float,
    ) -> bool:
        """
        日付が他レシートと大きく異なる行に修復確認を表示する。
        1件でも修復したら True（一覧の再読み込みが必要）。
        """
        if len(date_counter) < 2:
            return False

        recommended_key = self._get_majority_purchase_date_key(date_counter, threshold)
        if not recommended_key:
            return False

        rec_parts = recommended_key.split("/")
        repaired_display = f"{rec_parts[0]}/{int(rec_parts[1]):02d}/{int(rec_parts[2]):02d}"
        repaired_db_value = (
            f"{int(rec_parts[0]):04d}/{int(rec_parts[1]):02d}/{int(rec_parts[2]):02d}"
        )

        repaired_any = False
        for receipt in receipts:
            if not self._is_receipt_document(receipt):
                continue

            receipt_id = receipt.get('id')
            if not receipt_id or receipt_id in self._date_repair_declined_ids:
                continue

            purchase_date = receipt.get('purchase_date') or ""
            date_key = self._extract_purchase_date_key(purchase_date)
            if not date_key or date_counter.get(date_key, 0) >= threshold:
                continue

            purchase_time = (receipt.get('purchase_time') or "").strip()
            current_display = purchase_date
            if purchase_time:
                current_display = f"{purchase_date} {purchase_time}"
            after_display = repaired_display
            if purchase_time:
                after_display = f"{repaired_display} {purchase_time}"

            file_path = receipt.get('original_file_path') or receipt.get('file_path') or ""
            try:
                file_name = Path(file_path).name if file_path else f"ID {receipt_id}"
            except Exception:
                file_name = f"ID {receipt_id}"

            reply = QMessageBox.question(
                self,
                "日付の自動修復",
                (
                    f"レシート「{file_name}」の日付が他のレシートと異なります。\n\n"
                    f"現在: {current_display}\n"
                    f"修復後: {after_display}\n\n"
                    f"{repaired_display} に修復しますか？"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                try:
                    self.receipt_db.update_receipt(
                        int(receipt_id),
                        {"purchase_date": repaired_db_value},
                    )
                    repaired_any = True
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        "日付修復エラー",
                        f"日付の更新に失敗しました:\n{e}",
                    )
            else:
                self._date_repair_declined_ids.add(int(receipt_id))

        return repaired_any

    def refresh_receipt_list(self, offer_date_repair: bool = True):
        """レシート一覧を更新"""
        receipts = self.receipt_db.find_by_date_and_store(None)
        self.receipt_table.setRowCount(0)
        if hasattr(self, "warranty_table"):
            self.warranty_table.blockSignals(True)
            self.warranty_table.setRowCount(0)
            self.warranty_table.blockSignals(False)

        from pathlib import Path
        from collections import Counter
        receipt_row = 0
        warranty_row = 0

        # 勘定科目マスタを取得
        try:
            account_titles = [t.get("name", "") for t in self.account_title_db.list_titles()]
        except Exception:
            account_titles = []

        # デフォルト科目
        default_title = "仕入"
        if default_title not in account_titles:
            account_titles.insert(0, default_title)

        # 日付の異常検出用：レシート種別のみの日付（yyyy/mm/dd）を集計
        date_counter = Counter()
        receipt_only_list: List[Dict[str, Any]] = []
        for receipt in receipts:
            if not self._is_receipt_document(receipt):
                continue
            receipt_only_list.append(receipt)
            date_key = self._extract_purchase_date_key(receipt.get('purchase_date') or "")
            if date_key:
                date_counter[date_key] += 1

        total_receipts = len(receipt_only_list) if receipt_only_list else 1
        threshold = total_receipts * 0.5

        for receipt in receipts:
            # 種別判定（OCRテキストから簡易判定）
            doc_type = "レシート"
            ocr_text = receipt.get('ocr_text') or ""
            if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                doc_type = "保証書"

            file_path = receipt.get('original_file_path') or receipt.get('file_path') or ""
            file_name = ""
            if file_path:
                try:
                    file_name = Path(file_path).name
                except Exception:
                    file_name = file_path

            # レシート用テーブル: 種別=レシートのみ
            if doc_type == "レシート":
                row = receipt_row
                self.receipt_table.insertRow(row)
                receipt_id = receipt.get('id')
                self.receipt_table.setItem(row, 0, QTableWidgetItem(str(receipt_id)))
                self.receipt_table.setItem(row, 1, QTableWidgetItem(doc_type))

                # 科目（テキストとしてセット。編集時にデリゲートがプルダウンを出す）
                current_title = receipt.get('account_title') or default_title
                self.receipt_table.setItem(row, 2, QTableWidgetItem(current_title))

                # DBに既存科目がなければ、ここで一度だけデフォルトを保存
                if not receipt.get('account_title') and default_title:
                    try:
                        self.receipt_db.update_receipt(receipt_id, {"account_title": default_title})
                    except Exception:
                        pass

                # 画像ファイル名（識別子として使用）
                self.receipt_table.setItem(row, 3, QTableWidgetItem(file_name))

                # 日付（時刻も含める）
                purchase_date = receipt.get('purchase_date') or ""
                purchase_time = receipt.get('purchase_time') or ""
                date_display = purchase_date
                if purchase_time:
                    date_display = f"{purchase_date} {purchase_time}"
                
                # 日付の異常検出：他レシートの50%未満の日付は赤字
                date_item = QTableWidgetItem(date_display)
                date_key = self._extract_purchase_date_key(purchase_date)
                if date_key:
                    if date_counter.get(date_key, 0) < threshold:
                        date_item.setForeground(QColor("#FF6B6B"))
                    else:
                        date_item.setForeground(QColor("#FFFFFF"))
                
                self.receipt_table.setItem(row, 4, date_item)
                
                # 店舗名（初期値: OCRで取得した店舗名）
                initial_store_name = receipt.get('store_name_raw') or ""
                self.receipt_table.setItem(row, 5, QTableWidgetItem(initial_store_name))
                self.receipt_table.setItem(row, 6, QTableWidgetItem(receipt.get('phone_number') or ""))
                self.receipt_table.setItem(row, 7, QTableWidgetItem(str(receipt.get('total_amount') or "")))
                
                # 差額（8列目）- 紐付けSKUの合計金額とレシートの合計金額の差
                diff_val = None
                difference = receipt.get('price_difference')
                if difference is not None:
                    # 数値に変換（文字列やfloatにも対応）
                    try:
                        diff_val = int(round(float(difference)))
                    except (ValueError, TypeError):
                        diff_val = None

                    if diff_val is not None:
                        if is_acceptable_price_difference(diff_val):
                            difference_text = "OK"
                            difference_item = QTableWidgetItem(difference_text)
                            difference_item.setForeground(QColor("#4CAF50"))
                        else:
                            difference_text = f"¥{diff_val:,}"
                            difference_item = QTableWidgetItem(difference_text)
                            if diff_val > 0:
                                difference_item.setForeground(QColor("#FF6B6B"))
                            else:
                                difference_item.setForeground(QColor("#4CAF50"))
                        self.receipt_table.setItem(row, 8, difference_item)
                    else:
                        self.receipt_table.setItem(row, 8, QTableWidgetItem(""))
                else:
                    self.receipt_table.setItem(row, 8, QTableWidgetItem(""))

                # 店舗コード（9列目）
                store_code = receipt.get('store_code') or ""
                store_label = self._format_store_code_label(store_code, receipt.get('store_name_raw') or "")
                store_item = QTableWidgetItem(store_label)
                store_item.setData(Qt.UserRole, store_code)
                self.receipt_table.setItem(row, 9, store_item)

                # 差額OK（許容範囲内）の場合は、店舗名を店舗コードの正式名称で上書き
                if diff_val is not None and is_acceptable_price_difference(diff_val) and store_label:
                    self.receipt_table.setItem(row, 5, QTableWidgetItem(store_label))
                
                # 登録番号（10列目） - 適格請求書の登録番号 T + 13桁
                registration_number = receipt.get('registration_number') or ""
                self.receipt_table.setItem(row, 10, QTableWidgetItem(registration_number))
                
                # SKU（11列目）
                linked_skus_text = receipt.get('linked_skus', '') or ''
                linked_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()] if linked_skus_text else []
                sku_display = ', '.join(linked_skus) if linked_skus else ''
                self.receipt_table.setItem(row, 11, QTableWidgetItem(sku_display))
                
                # 画像URL（12列目）- GCSアップロード時のURLを表示
                gcs_url = receipt.get('gcs_url') or receipt.get('image_url') or ''
                image_url_item = QTableWidgetItem(gcs_url)
                if gcs_url:
                    image_url_item.setToolTip(f"画像URL: {gcs_url}\n（ダブルクリックでブラウザ表示）")
                    # URLのスタイル設定（画像URL列と同じ）
                    image_url_item.setForeground(Qt.white)
                    font = image_url_item.font()
                    font.setUnderline(True)
                    image_url_item.setFont(font)
                    # 編集不可にする
                    image_url_item.setFlags(image_url_item.flags() & ~Qt.ItemIsEditable)
                else:
                    image_url_item.setFlags(image_url_item.flags() & ~Qt.ItemIsEditable)
                self.receipt_table.setItem(row, 12, image_url_item)
                
                receipt_row += 1

            # 保証書用テーブル: 種別=保証書のみ
            if doc_type == "保証書" and hasattr(self, "warranty_table"):
                from PySide6.QtWidgets import QDateEdit

                self.warranty_table.blockSignals(True)
                row = warranty_row
                self.warranty_table.insertRow(row)
                self.warranty_table.setItem(row, 0, QTableWidgetItem(str(receipt.get('id'))))
                self.warranty_table.setItem(row, 1, QTableWidgetItem(doc_type))
                self.warranty_table.setItem(row, 2, QTableWidgetItem(file_name))
                self.warranty_table.setItem(row, 3, QTableWidgetItem(receipt.get('purchase_date') or ""))
                self.warranty_table.setItem(row, 4, QTableWidgetItem(receipt.get('store_name_raw') or ""))
                self.warranty_table.setItem(row, 5, QTableWidgetItem(receipt.get('phone_number') or ""))
                store_code = receipt.get('store_code') or ""
                store_label = self._format_store_code_label(store_code, receipt.get('store_name_raw') or "")
                store_item = QTableWidgetItem(store_label)
                store_item.setData(Qt.UserRole, store_code)
                self.warranty_table.setItem(row, 6, store_item)
                # SKU・商品名はプルダウンで候補をセット
                # 複数SKUが紐付けられている場合は、linked_skusから取得（カンマ区切り）
                linked_skus_text = receipt.get('linked_skus', '') or ''
                if linked_skus_text:
                    linked_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()]
                    sku = ', '.join(linked_skus) if linked_skus else (receipt.get('sku') or "")
                else:
                    sku = receipt.get('sku') or ""
                product_name = receipt.get('product_name') or ""
                self._populate_warranty_product_cell(row, receipt, sku, product_name)

                # 保証期間(日)
                self.warranty_table.setItem(row, 9, QTableWidgetItem(str(receipt.get('warranty_days') or "")))

                # 保証最終日（カレンダー付き日付入力）
                date_edit = QDateEdit()
                date_edit.setCalendarPopup(True)
                
                # デフォルト値の設定順序：
                # 1. 既存の保証最終日があればそれを優先
                # 2. 保証期間(日)があれば日付+保証期間で計算
                # 3. どちらもなければ日付（保証書の日付）をデフォルトにする
                final_str = receipt.get('warranty_until') or ""
                qdate = None
                
                # 日付を取得（receiptから、またはテーブルの日付列から）
                purchase_date_str = receipt.get('purchase_date') or receipt.get('date') or ""
                if purchase_date_str:
                    purchase_date_str = purchase_date_str.replace("/", "-").split(" ")[0]
                
                if final_str:
                    qdate = QDate.fromString(final_str, "yyyy-MM-dd")
                
                # 保証期間(日)があれば日付+保証期間で計算
                if (not qdate or not qdate.isValid()) and purchase_date_str:
                    warranty_days = receipt.get('warranty_days')
                    if warranty_days:
                        try:
                            from datetime import datetime, timedelta
                            base = datetime.strptime(purchase_date_str, "%Y-%m-%d")
                            qdate = QDate.fromString(
                                (base + timedelta(days=int(warranty_days))).strftime("%Y-%m-%d"),
                                "yyyy-MM-dd",
                            )
                        except Exception:
                            pass
                    
                    # 保証期間がない場合は、日付（保証書の日付）をデフォルトにする
                    if not qdate or not qdate.isValid():
                        try:
                            from datetime import datetime
                            qdate = QDate.fromString(purchase_date_str, "yyyy-MM-dd")
                        except Exception:
                            pass
                
                if qdate and qdate.isValid():
                    date_edit.setDate(qdate)
                self.warranty_table.setCellWidget(row, 10, date_edit)

                # 日付変更時の処理
                date_edit.dateChanged.connect(lambda qd, r=row: self.on_warranty_date_changed(r, qd))

                self.warranty_table.blockSignals(False)
                warranty_row += 1

        if offer_date_repair and receipt_only_list and len(date_counter) >= 2:
            if self._offer_purchase_date_auto_repair(receipt_only_list, date_counter, threshold):
                self.refresh_receipt_list(offer_date_repair=False)
                return

        self.on_receipt_selection_changed()

    def _find_receipt_table_row(self, receipt_id: int) -> Optional[int]:
        """レシート一覧テーブルで receipt_id に対応する行番号を返す。"""
        if not hasattr(self, "receipt_table") or receipt_id is None:
            return None
        id_str = str(receipt_id)
        for row in range(self.receipt_table.rowCount()):
            item = self.receipt_table.item(row, 0)
            if item and item.text() == id_str:
                return row
        return None

    def _apply_receipt_difference_cell(self, row: int, difference: Any) -> None:
        """差額列（8列目）だけを更新する。"""
        diff_val = None
        if difference is not None:
            try:
                diff_val = int(round(float(difference)))
            except (ValueError, TypeError):
                diff_val = None
        if diff_val is not None:
            if is_acceptable_price_difference(diff_val):
                difference_item = QTableWidgetItem("OK")
                difference_item.setForeground(QColor("#4CAF50"))
            else:
                difference_item = QTableWidgetItem(f"¥{diff_val:,}")
                if diff_val > 0:
                    difference_item.setForeground(QColor("#FF6B6B"))
                else:
                    difference_item.setForeground(QColor("#4CAF50"))
            self.receipt_table.setItem(row, 8, difference_item)
        else:
            self.receipt_table.setItem(row, 8, QTableWidgetItem(""))

    def _patch_receipt_table_row(self, receipt_id: int, updates: Dict[str, Any]) -> bool:
        """レシート一覧の該当行だけを更新（全件 refresh を避ける）。"""
        row = self._find_receipt_table_row(receipt_id)
        if row is None:
            return False
        existing = self.receipt_db.get_receipt(receipt_id) or {}
        merged = {**existing, **updates}
        self.receipt_table.blockSignals(True)
        try:
            if "purchase_date" in updates:
                self.receipt_table.setItem(
                    row, 4, QTableWidgetItem(str(merged.get("purchase_date") or ""))
                )
            if "store_name_raw" in updates or "store_code" in updates:
                store_code = merged.get("store_code") or ""
                store_label = self._format_store_code_label(
                    store_code, merged.get("store_name_raw") or ""
                )
                self.receipt_table.setItem(
                    row,
                    5,
                    QTableWidgetItem(store_label or (merged.get("store_name_raw") or "")),
                )
                store_item = QTableWidgetItem(store_label)
                store_item.setData(Qt.UserRole, store_code)
                self.receipt_table.setItem(row, 9, store_item)
            if "phone_number" in updates:
                self.receipt_table.setItem(
                    row, 6, QTableWidgetItem(str(merged.get("phone_number") or ""))
                )
            if "total_amount" in updates:
                self.receipt_table.setItem(
                    row, 7, QTableWidgetItem(str(merged.get("total_amount") or ""))
                )
            if "price_difference" in updates:
                self._apply_receipt_difference_cell(row, merged.get("price_difference"))
                diff = merged.get("price_difference")
                try:
                    diff_val = int(round(float(diff))) if diff is not None else None
                except (ValueError, TypeError):
                    diff_val = None
                if diff_val is not None and is_acceptable_price_difference(diff_val):
                    store_code = merged.get("store_code") or ""
                    store_label = self._format_store_code_label(
                        store_code, merged.get("store_name_raw") or ""
                    )
                    if store_label:
                        self.receipt_table.setItem(row, 5, QTableWidgetItem(store_label))
            if "registration_number" in updates:
                self.receipt_table.setItem(
                    row, 10, QTableWidgetItem(str(merged.get("registration_number") or ""))
                )
            if "linked_skus" in updates:
                linked_skus_text = merged.get("linked_skus") or ""
                linked_skus = (
                    [s.strip() for s in linked_skus_text.split(",") if s.strip()]
                    if linked_skus_text
                    else []
                )
                sku_display = ", ".join(linked_skus) if linked_skus else ""
                self.receipt_table.setItem(row, 11, QTableWidgetItem(sku_display))
        finally:
            self.receipt_table.blockSignals(False)
        return True

    def _build_purchase_sku_index(
        self, purchase_records: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """SKU → 仕入レコードの辞書（O(1) 参照用）。"""
        index: Dict[str, Dict[str, Any]] = {}
        for record in purchase_records or []:
            sku = str(record.get("SKU") or record.get("sku") or "").strip()
            if sku:
                index[sku] = record
        return index

    def _defer_after_receipt_manual_save(
        self,
        *,
        affected_skus: List[str],
        save_snapshot: bool,
    ) -> None:
        """保存後の仕入DB同期・テーブル部分更新・スナップショットを非同期で実行。"""
        skus = list(affected_skus)

        def _sync_and_refresh() -> None:
            pw = self.product_widget
            if not pw or not skus:
                return
            try:
                pw.sync_purchase_master_records_for_skus(skus)
                if getattr(pw, "_purchase_table_full_master_built", False):
                    for sku in skus:
                        record = pw._purchase_record_by_sku(sku)
                        if record:
                            pw._refresh_purchase_repricing_table_cells_for_record(record)
            except Exception as exc:
                logger.warning("レシート手動保存の遅延同期に失敗: %s", exc)

        def _save_snapshot() -> None:
            if not save_snapshot:
                return
            pw = self.product_widget
            if not pw:
                return
            try:
                pw.save_purchase_snapshot(skip_master_sync=True)
            except Exception as exc:
                logger.warning("レシート手動保存のスナップショット保存に失敗: %s", exc)

        QTimer.singleShot(0, _sync_and_refresh)
        if save_snapshot:
            QTimer.singleShot(50, _save_snapshot)

    def on_receipt_selection_changed(self):
        """レシート表の選択変更を監視"""
        if not hasattr(self, 'delete_row_btn'):
            return
        selection_model = self.receipt_table.selectionModel()
        has_selection = bool(selection_model and selection_model.selectedRows())
        self.delete_row_btn.setEnabled(has_selection)

    def delete_selected_receipts(self):
        """選択したレシートを削除（テスト用途）"""
        selection_model = self.receipt_table.selectionModel()
        if not selection_model:
            return
        rows = selection_model.selectedRows()
        if not rows:
            QMessageBox.information(self, "情報", "削除するレシートを選択してください。")
            return
        receipt_ids = []
        for idx in rows:
            item = self.receipt_table.item(idx.row(), 0)
            if item:
                try:
                    receipt_ids.append(int(item.text()))
                except ValueError:
                    continue
        if not receipt_ids:
            QMessageBox.warning(self, "警告", "選択された行に有効なIDがありません。")
            return
        if QMessageBox.question(
            self,
            "確認",
            f"選択された {len(receipt_ids)} 件のレシートを削除します。よろしいですか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        ) != QMessageBox.Yes:
            return
        deleted = 0
        for rid in receipt_ids:
            if self.receipt_db.delete_receipt_by_id(rid):
                deleted += 1
                if self.current_receipt_id == rid:
                    self.reset_form()
        self.refresh_receipt_list()
        QMessageBox.information(self, "削除完了", f"{deleted} 件のレシートを削除しました。")

    def delete_all_receipts(self):
        """レシート情報をクリア"""
        if self._is_batch_ocr_busy():
            QMessageBox.information(self, "クリア", "全件OCR実行中はクリアできません。")
            return
        if QMessageBox.warning(
            self,
            "確認",
            "レシート情報をクリアします。続行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        ) != QMessageBox.Yes:
            return
        deleted = self.receipt_db.delete_all_receipts()
        self.reset_form()
        self.refresh_receipt_list()
        self._reset_post_rename_workflow_gate()
        self._update_workflow_status("ワークフロー: 未実行", emphasize=False)
        QMessageBox.information(self, "クリア完了", f"{deleted} 件のレシートをクリアしました。")

    # ===== 一括処理 =====
    def on_receipt_table_context_menu(self, position):
        """レシートテーブルの右クリックメニュー"""
        item = self.receipt_table.itemAt(position)
        if not item:
            return
        
        row = item.row()
        id_item = self.receipt_table.item(row, 0)
        if not id_item:
            return
        
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return
        
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            return
        
        menu = QMenu(self)
        
        # もう一度OCR処理
        ocr_action = menu.addAction("もう一度OCR処理")
        ocr_action.triggered.connect(lambda: self.reprocess_ocr_for_receipt(receipt_id, receipt))
        
        menu.exec_(self.receipt_table.viewport().mapToGlobal(position))
    
    def on_receipt_double_clicked(self, item: QTableWidgetItem):
        """レシート一覧のダブルクリック動作を制御（詳細編集を開く、またはレシート画像URLを開く）"""
        row = item.row()
        col = item.column()
        
        # レシート画像URL列（12列目）をダブルクリックした場合はブラウザで開く
        if col == 12:
            url = item.text().strip()
            if url:
                qurl = QUrl(url)
                if qurl.isValid():
                    if not QDesktopServices.openUrl(qurl):
                        QMessageBox.warning(self, "警告", f"ブラウザでURLを開けませんでした:\n{url}")
                else:
                    QMessageBox.warning(self, "警告", f"URLが不正です:\n{url}")
            return
        
        # その他の列は詳細編集を開く
        self.load_receipt(item)

    def load_receipt(self, item: QTableWidgetItem):
        """レシートを読み込み（レシート情報編集ダイアログを表示）"""
        row = item.row()
        
        # ID列からreceipt_idを取得
        id_item = self.receipt_table.item(row, 0)
        if not id_item:
            return
        
        try:
            receipt_id = int(id_item.text())
        except (ValueError, TypeError):
            return
        
        # レシートデータを取得
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            QMessageBox.warning(self, "警告", "レシートデータが見つかりません。")
            return
        
        # 画像ファイルパスを取得
        image_path = receipt.get('file_path') or receipt.get('original_file_path')
        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        # レシート情報編集ダイアログを表示
        self._show_image_popup(image_path, receipt_id)
    
    def view_receipt_image(self):
        """レシート画像を別画面で表示"""
        if not self.current_receipt_data:
            QMessageBox.warning(self, "警告", "レシートデータがありません。")
            return
        
        # 画像パスを取得
        image_path = None
        if self.current_receipt_data:
            image_path = self.current_receipt_data.get('file_path') or self.current_receipt_data.get('original_file_path')
        if not image_path and self.current_receipt_id:
            receipt = self.receipt_db.get_receipt(self.current_receipt_id)
            if receipt:
                image_path = receipt.get('file_path') or receipt.get('original_file_path')

        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルが見つかりません。")
            return

        self._show_image_popup(image_path, self.current_receipt_id)

