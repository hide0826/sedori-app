#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像登録テーブル mixin。"""
from __future__ import annotations

import sys
import os
import json
import re
import io
import uuid
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import logging
from html import escape
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QMimeData, QUrl, QSettings, QFileInfo
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QSplitter, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QSizePolicy, QTextEdit, QProgressDialog,
    QInputDialog, QMenu, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QTabWidget, QSpinBox, QComboBox, QFrame, QFileIconProvider, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem,
)
from PySide6.QtGui import (
    QPixmap, QFont, QDrag, QDropEvent, QImageReader, QImage, QDesktopServices, QCursor,
    QColor, QBrush, QPainter,
)
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_flags_from_folder
from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget
from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front

try:
    from utils.amazon_image_naming import (
        extract_sku_from_image_path as _amazon_extract_sku_from_path,
        infer_sku_from_sorted_images,
        needs_amazon_sequence_rerename,
        plan_amazon_rename_targets,
        plan_amazon_rerename_targets,
    )
except ImportError:
    from desktop.utils.amazon_image_naming import (
        extract_sku_from_image_path as _amazon_extract_sku_from_path,
        infer_sku_from_sorted_images,
        needs_amazon_sequence_rerename,
        plan_amazon_rename_targets,
        plan_amazon_rerename_targets,
    )

try:
    from utils.settings_helper import get_amazon_inventory_loader_upload_url
except ImportError:
    from desktop.utils.settings_helper import (  # type: ignore
        get_amazon_inventory_loader_upload_url,
    )

try:
    from services.image_service import (
        ImageService,
        ImageRecord,
        JanGroup,
        DEFAULT_AUTO_CORRECT_PRESET,
    )
    from services.ocr_service import OCRService
except Exception:
    from desktop.services.image_service import (
        ImageService,
        ImageRecord,
        JanGroup,
        DEFAULT_AUTO_CORRECT_PRESET,
    )
    from desktop.services.ocr_service import OCRService

from database.image_db import ImageDatabase


from .support import (
    ScanCancelledError,
    CandidateSelectionDialog,
    PurchaseCandidateDialog,
    JanGroupTreeWidget,
    ImageListWidget,
    RegistrationTableWidget,
    ImageLoadThread,
    _WORKFLOW_PIPELINE_SEGMENTS,
    _WORKFLOW_PIPELINE_SEP,
    _ACTION_TO_PIPELINE_STEP,
    _REGISTRATION_WORKFLOW_PIPELINE_SEGMENTS,
    _REGISTRATION_ACTION_TO_PIPELINE_STEP,
    _AMAZON_UPLOAD_BROWSER_TITLE_KEYWORDS,
    _UNLINKED_HIGHLIGHT_BG,
    _UNLINKED_HIGHLIGHT_FG,
    _PURCHASE_IMAGE_COLUMNS,
    _normalize_jan_for_match,
    _normalize_image_path,
    _record_has_any_image_paths,
    _apply_unlinked_item_style,
    _record_jan_matches_group,
    _candidate_is_known_linked_product,
    _candidate_should_highlight_in_dialog,
    _format_status_prefix_html,
    _format_workflow_pipeline_html,
)

class ImageManagerRegistrationMixin:
    def _get_record_value(self, record: Dict[str, Any], keys: List[str], default: str = "") -> str:
        """複数の候補キーから値を取得"""
        for key in keys:
            value = record.get(key)
            if value not in (None, ""):
                return str(value)
        return default


    def add_registration_entry(
        self, record: Dict[str, Any], skip_barcode_classification: bool = False
    ):
        """仕入DBレコード情報を画像登録タブに追加（画像を商品画像とバーコード画像に分類）"""
        entry = {
            "condition": self._get_record_value(record, ["コンディション", "condition"]),
            "sku": self._get_record_value(record, ["SKU", "sku"]),
            "asin": self._get_record_value(record, ["ASIN", "asin"]),
            "jan": self._get_record_value(record, ["JAN", "jan"]),
            "product_name": self._get_record_value(record, ["商品名", "product_name", "title"]),
            "images": [],  # 元の画像パス（表示用）
            "product_images": [],  # 商品画像（Amazon Lファイル用、最大5枚）
            "barcode_image": None,  # バーコード画像（識別用）
            # Amazon Lファイル用フィールド
            "price": self._get_record_value(record, ["販売価格", "price", "plannedPrice"]),
            "quantity": self._get_record_value(record, ["在庫数", "quantity", "add_number"], default="0"),
            "condition_type": self._get_record_value(record, ["コンディション番号", "condition_type", "condition-type"]),
            "condition_note": self._get_record_value(record, ["コンディション説明", "condition_note", "conditionNote"]),
            "image_urls": []  # GCSアップロード後のURL（最大5枚）
        }
        
        # 元の画像パスを取得
        for i in range(1, 7):
            img_path = self._get_record_value(
                record,
                [f"画像{i}", f"image_{i}", f"画像 {i}"]
            )
            if img_path:
                entry["images"].append(img_path)
        
        # 画像を商品画像とバーコード画像に分類
        product_images = []
        barcode_image = None

        if skip_barcode_classification:
            # 1枚目除外ON運用時: 仕入DBに載った画像は商品写真のみ想定（バーコード読取・OCRを省略）
            for img_path in entry["images"]:
                if not img_path:
                    continue
                if len(product_images) < 5:
                    product_images.append(img_path)
        else:
            for img_path in entry["images"]:
                if not img_path:
                    continue

                # バーコード画像判定
                try:
                    if self.image_service.is_barcode_only_image(img_path):
                        # バーコード画像（最初の1枚のみ保存）
                        if not barcode_image:
                            barcode_image = img_path
                    else:
                        # 商品画像（最大5枚）
                        if len(product_images) < 5:
                            product_images.append(img_path)
                except Exception as e:
                    logger.warning(f"Failed to check if image is barcode-only: {e}, treating as product image")
                    # エラー時は商品画像として扱う
                    if len(product_images) < 5:
                        product_images.append(img_path)
        
        entry["product_images"] = product_images
        entry["barcode_image"] = barcode_image
        
        # 画像URLを取得（優先順位: record > 仕入DB）
        # 1. まずrecordから画像URLを取得（確定処理直後の場合）
        image_urls_from_record = []
        for i in range(1, 7):
            img_url_key = f"画像URL{i}"
            img_url_alt_key = f"image_url_{i}"
            img_url = record.get(img_url_key) or record.get(img_url_alt_key)
            image_urls_from_record.append(img_url if img_url else "")
        
        # 2. recordに画像URLがない場合は、仕入DBから取得
        if not any(image_urls_from_record) and entry["sku"]:
            try:
                from database.purchase_db import PurchaseDatabase
                purchase_db = PurchaseDatabase()
                purchase_record = purchase_db.get_by_sku(entry["sku"])
                if purchase_record:
                    # image_url_1からimage_url_6まで取得
                    for i in range(1, 7):
                        img_url = purchase_record.get(f"image_url_{i}")
                        if img_url:
                            image_urls_from_record[i - 1] = img_url
            except Exception as e:
                logger.debug(f"Failed to get image URLs from purchase DB: {e}")
        
        # 画像URLリストを設定（空文字列を除く）
        entry["image_urls"] = [url for url in image_urls_from_record if url]

        # 既に同じSKUが登録されている場合は更新、なければ追加
        entry_sku = entry.get("sku", "").strip()
        existing_index = -1
        if entry_sku:
            for idx, existing_entry in enumerate(self.registration_records):
                existing_sku = existing_entry.get("sku", "").strip()
                if existing_sku == entry_sku:
                    existing_index = idx
                    break
        
        if existing_index >= 0:
            # 既存エントリを更新（最新の情報を反映）
            self.registration_records[existing_index] = entry
        else:
            # 新規追加
            self.registration_records.append(entry)
        
        self.update_registration_table()


    def update_registration_table(self):
        """画像登録タブのテーブルを更新"""
        self.registration_table.setRowCount(len(self.registration_records))

        for row, entry in enumerate(self.registration_records):
            # 基本情報（既存カラム）
            values = [
                entry.get("condition", ""),
                entry.get("sku", ""),
                entry.get("asin", ""),
                entry.get("jan", ""),
                entry.get("product_name", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                # JANのみ編集可
                if col == 3:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.registration_table.setItem(row, col, item)

            # 元の画像パス（既存カラム、表示用）
            for idx, image_path in enumerate(entry.get("images", [])):
                col = 5 + idx
                if col >= len(self.registration_columns):
                    break
                display_text = Path(image_path).name if image_path else ""
                item = QTableWidgetItem(display_text)
                if image_path:
                    item.setData(Qt.UserRole, image_path)
                    item.setToolTip(image_path)
                    item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)
                self.registration_table.setItem(row, col, item)
            
            # 画像URL1～5（編集可能、GCSアップロード後のURL）
            col_offset = 11  # 既存カラム数（コンディション、SKU、ASIN、JAN、商品名、画像1～6）
            for idx in range(5):
                col = col_offset + idx
                img_url = entry.get("image_urls", [])[idx] if idx < len(entry.get("image_urls", [])) else ""
                item = QTableWidgetItem(img_url)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.registration_table.setItem(row, col, item)


    def clear_registration_records(self):
        """画像登録リストをクリア"""
        if not self.registration_records:
            return
        reply = QMessageBox.question(
            self,
            "確認",
            "画像登録リストをクリアしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.registration_records = []
            self.registration_table.setRowCount(0)
            self._set_registration_preview(None)
            self._update_registration_workflow_status("ワークフロー: 未実行", emphasize=False)


    def delete_selected_registration_rows(self):
        """選択されている行だけを画像登録リストから削除"""
        if not self.registration_records:
            QMessageBox.information(self, "情報", "削除する行がありません。")
            return

        selected_rows = set()
        for item in self.registration_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.information(self, "情報", "削除する行が選択されていません。")
            return

        reply = QMessageBox.question(
            self,
            "確認",
            f"選択されている {len(selected_rows)} 行を画像登録リストから削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # インデックスがずれないように降順で削除
        for row in sorted(selected_rows, reverse=True):
            if row < len(self.registration_records):
                del self.registration_records[row]

        # テーブルを再描画
        self.update_registration_table()
        self._set_registration_preview(None)


    def save_registration_to_purchase_db(self):
        """
        画像登録タブの内容を仕入DB（PurchaseDatabase）に保存する。

        - SKUごとに image_url_1〜image_url_6 を更新（PurchaseDatabase）
        - さらに、最新の仕入DBスナップショット（ProductPurchaseDatabase）にも
          画像URL1〜6を反映し、新しいスナップショットとして保存する
        """
        if not self.registration_records:
            QMessageBox.information(self, "情報", "保存するデータがありません。")
            return

        try:
            from database.purchase_db import PurchaseDatabase
        except Exception as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"仕入DBモジュールの読み込みに失敗しました:\n{e}",
            )
            return

        purchase_db = PurchaseDatabase()

        # 商品マスタ（products）にも画像パス・URLを保存するためにProductDatabaseを使用
        try:
            from database.product_db import ProductDatabase
            product_db = ProductDatabase()
        except Exception as e:
            product_db = None
            logger.warning(f"ProductDatabaseの初期化に失敗しました（商品DBへの画像保存はスキップされます）: {e}")
        updated_count = 0
        skipped_count = 0

        # SKU -> image_urls / image_paths のマップを作成（後でスナップショットにも反映）
        sku_to_image_urls: Dict[str, List[str]] = {}
        sku_to_image_paths: Dict[str, List[str]] = {}

        for entry in self.registration_records:
            sku = (entry.get("sku") or "").strip()
            if not sku:
                skipped_count += 1
                continue

            # 画像URLリストを構築
            # 1. まず現在のエントリ（画面で編集された内容）を優先
            image_urls: List[str] = list(entry.get("image_urls", []) or [])

            # 2. purchase_db側に既存のURLがあれば、空欄だけ補完する
            try:
                purchase_record = purchase_db.get_by_sku(sku)
                if purchase_record:
                    for i in range(1, 7):
                        img_url = purchase_record.get(f"image_url_{i}") or ""
                        idx = i - 1
                        if idx < len(image_urls):
                            # 画面側が空でDBに値がある場合だけ補完
                            if (not image_urls[idx]) and img_url:
                                image_urls[idx] = img_url
                        else:
                            image_urls.append(img_url)
            except Exception as e:
                logger.debug(f"Failed to get image URLs from purchase DB for SKU {sku}: {e}")
                # 取得に失敗しても、画面側のimage_urlsはそのまま使う

            # 長さを6に正規化（不足分は空文字）
            while len(image_urls) < 6:
                image_urls.append("")

            # 商品画像パス（バーコード以外の画像1〜6）
            image_paths_raw = entry.get("product_images") or entry.get("images") or []
            # 最大6件に正規化
            norm_paths: List[str] = []
            for i in range(6):
                norm_paths.append(image_paths_raw[i] if i < len(image_paths_raw) else "")

            # image_url_1〜6 を構築（不足分は空文字）
            update_data: Dict[str, Any] = {"sku": sku}
            for i in range(6):
                key = f"image_url_{i + 1}"
                update_data[key] = image_urls[i] if i < len(image_urls) else ""

            sku_to_image_urls[sku] = [update_data[f"image_url_{i+1}"] for i in range(6)]
            sku_to_image_paths[sku] = norm_paths

            try:
                purchase_db.upsert(update_data)
                updated_count += 1
            except Exception as e:
                logger.warning(f"Failed to save image URLs to purchase DB for SKU {sku}: {e}")
                skipped_count += 1

            # products テーブルの image_1〜6 / image_url_1〜6 も更新
            if product_db is not None:
                try:
                    product_db.update_images_and_urls(sku, sku_to_image_paths[sku], sku_to_image_urls[sku])
                except Exception as e:
                    logger.warning(f"Failed to update products table images for SKU {sku}: {e}")

        # 商品DBタブの仕入DBスナップショットにも反映
        snapshot_updated = False
        try:
            from database.product_purchase_db import ProductPurchaseDatabase

            pp_db = ProductPurchaseDatabase()
            snapshots = pp_db.list_snapshots()
            if snapshots:
                latest_id = snapshots[0]["id"]
                snapshot = pp_db.get_snapshot(latest_id)
                if snapshot and isinstance(snapshot.get("data"), list):
                    data = snapshot["data"]
                    for row in data:
                        sku = (row.get("SKU") or row.get("sku") or "").strip()
                        if not sku:
                            continue

                        # 画像URL1〜6
                        urls = sku_to_image_urls.get(sku)
                        if urls:
                            for i in range(6):
                                col_name = f"画像URL{i + 1}"
                                url_val = urls[i] if i < len(urls) else ""
                                row[col_name] = url_val

                        # 画像1〜6（ファイル名）もスナップショットに直接保存
                        paths = sku_to_image_paths.get(sku)
                        if paths:
                            for i in range(6):
                                col_name = f"画像{i + 1}"
                                path_val = paths[i] if i < len(paths) else ""
                                row[col_name] = path_val

                    # 新しいスナップショットとして保存（最新が自動的に使われる）
                    pp_db.save_snapshot("image_urls_synced", data)
                    snapshot_updated = True
        except Exception as e:
            logger.warning(f"Failed to update purchase snapshot DB with image URLs: {e}")

        # 画面上の仕入DBキャッシュにも即時反映（この後のスナップ保存で逆上書きされるのを防ぐ）
        try:
            if self.product_widget and sku_to_image_urls:
                touched = 0
                for lst_name in ("purchase_all_records", "purchase_all_records_master", "purchase_records"):
                    records = getattr(self.product_widget, lst_name, None)
                    if not isinstance(records, list):
                        continue
                    for row in records:
                        sku = (row.get("SKU") or row.get("sku") or "").strip()
                        if not sku:
                            continue
                        urls = sku_to_image_urls.get(sku)
                        if not urls:
                            continue
                        for i in range(1, 7):
                            row[f"画像URL{i}"] = urls[i - 1] if i - 1 < len(urls) else ""
                        touched += 1
                if touched > 0 and hasattr(self.product_widget, "populate_purchase_table"):
                    current_rows = getattr(self.product_widget, "purchase_records", []) or []
                    self.product_widget.populate_purchase_table(current_rows)
        except Exception as e:
            logger.warning(f"Failed to sync image URLs to ProductWidget cache: {e}")

        QMessageBox.information(
            self,
            "DBに保存",
            f"仕入DBへの保存が完了しました。\n\n"
            f"更新されたSKU: {updated_count}件\n"
            f"スキップ/エラー: {skipped_count}件\n"
            f"スナップショット更新: {'あり' if snapshot_updated else 'なし'}",
        )


    def save_registration_snapshot(self):
        """画像登録タブの現在の一覧をJSONファイルにスナップ保存（テスト用）"""
        if not self.registration_records:
            QMessageBox.information(self, "スナップ保存", "保存するデータがありません。")
            return

        try:
            self.registration_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "record_count": len(self.registration_records),
                "records": self.registration_records,
            }
            with open(self.registration_snapshot_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            QMessageBox.information(
                self,
                "スナップ保存",
                f"画像登録一覧をスナップ保存しました。\n"
                f"ファイル: {self.registration_snapshot_path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "スナップ保存エラー", f"スナップ保存に失敗しました:\n{e}")


    def load_registration_snapshot(self):
        """前回保存したスナップショットを読み込んで一覧に復元"""
        if not self.registration_snapshot_path.exists():
            QMessageBox.information(
                self,
                "スナップ読込",
                "スナップショットファイルが見つかりませんでした。\n"
                "先に「スナップ保存」を実行してください。",
            )
            return

        try:
            with open(self.registration_snapshot_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            records = payload.get("records", [])
            if not isinstance(records, list):
                raise ValueError("records フィールドの形式が不正です。")

            self.registration_records = records
            self.update_registration_table()
            self._set_registration_preview(None)

            saved_at = payload.get("saved_at", "不明な日時")
            QMessageBox.information(
                self,
                "スナップ読込",
                f"スナップショットを読み込みました。\n"
                f"保存日時: {saved_at}\n"
                f"件数: {len(self.registration_records)}件",
            )
        except Exception as e:
            QMessageBox.critical(self, "スナップ読込エラー", f"スナップ読込に失敗しました:\n{e}")


    def on_registration_cell_double_clicked(self, row: int, column: int):
        """画像列ダブルクリックでファイルを開く"""
        col_offset = 11
        # 画像URL1～5 はダブルクリックで別窓表示
        if col_offset <= column <= col_offset + 4:
            item = self.registration_table.item(row, column)
            if not item:
                return
            url = (item.text() or "").strip()
            if url.startswith("http://") or url.startswith("https://"):
                self._show_remote_image_dialog(url)
            return

        if column < 4:
            return
        item = self.registration_table.item(row, column)
        if not item:
            return
        image_path = item.data(Qt.UserRole)
        if not image_path:
            return
        file_path = Path(image_path)
        if not file_path.exists():
            QMessageBox.warning(self, "エラー", f"画像ファイルが見つかりません:\n{image_path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))


    def on_registration_cell_clicked(self, row: int, column: int):
        """画像選択時にプレビュー表示"""
        col_offset = 11
        # 画像URL1～5 はクリックでプレビュー表示（リモート画像）
        if col_offset <= column <= col_offset + 4:
            item = self.registration_table.item(row, column)
            if not item:
                return
            url = (item.text() or "").strip()
            if url.startswith("http://") or url.startswith("https://"):
                self._set_registration_preview_url(url)
            return

        if column < 4:
            self._set_registration_preview(None)
            return
        item = self.registration_table.item(row, column)
        if not item:
            self._set_registration_preview(None)
            return
        image_path = item.data(Qt.UserRole)
        self._set_registration_preview(image_path)


    def on_registration_current_cell_changed(self, current_row: int, current_col: int, prev_row: int, prev_col: int):
        """カレントセル変更時にもプレビュー更新（クリックが取れない環境の保険）"""
        if current_row < 0 or current_col < 0:
            return
        self.on_registration_cell_clicked(current_row, current_col)


    def on_registration_item_clicked(self, item: QTableWidgetItem):
        """itemClicked/itemPressed用（行選択でも確実に拾う）"""
        try:
            row = item.row()
            col = item.column()
        except Exception:
            return
        self.on_registration_cell_clicked(row, col)


    def on_registration_cell_changed(self, row: int, column: int):
        """テーブルセル編集時にregistration_recordsを更新"""
        if row >= len(self.registration_records):
            return
        
        entry = self.registration_records[row]
        item = self.registration_table.item(row, column)
        if not item:
            return
        
        col_offset = 11  # 既存カラム数（コンディション、SKU、ASIN、JAN、商品名、画像1～6）
        
        # 編集可能なカラムのみ更新
        if column == 1:  # SKU（将来の直接編集にも対応）
            entry["sku"] = item.text()
        elif column == 3:  # JAN
            entry["jan"] = item.text()
        elif col_offset <= column <= col_offset + 4:  # 画像URL1～5
            idx = column - col_offset
            if "image_urls" not in entry:
                entry["image_urls"] = [""] * 5
            while len(entry["image_urls"]) <= idx:
                entry["image_urls"].append("")
            entry["image_urls"][idx] = item.text()


    def on_registration_table_context_menu(self, pos):
        """画像登録テーブルの右クリックメニュー"""
        item = self.registration_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        column = item.column()

        # SKU列（1）: JANから仕入DB検索してSKU候補を選択
        if column == 1:
            self.change_sku_for_registration_row(row)
            return

        # 画像1～6の列（5～10）: 右クリックでローカル画像操作メニュー
        if 5 <= column <= 10:
            image_idx = column - 5  # 0～5
            menu = QMenu(self)
            delete_local_action = menu.addAction("この画像を削除（後続の画像をスライド）")
            force_action = menu.addAction("この画像をGCSに強制アップロード（バーコード判定を無視）")
            action = menu.exec_(self.registration_table.viewport().mapToGlobal(pos))
            if action == delete_local_action:
                self.delete_and_slide_local_image(row, image_idx)
            elif action == force_action:
                self.force_upload_single_image_to_gcs(row, image_idx)
            return

        # 画像URL1～5の列（11～15）のみURL編集メニュー表示
        col_offset = 11  # 画像URL1の列インデックス
        if not (col_offset <= column <= col_offset + 4):
            return

        url_idx = column - col_offset  # 0～4
        url_label = f"画像URL{url_idx + 1}"

        menu = QMenu(self)
        delete_action = menu.addAction(f"{url_label} を削除（後続URLをスライド）")
        clear_action = menu.addAction(f"{url_label} をクリア（スライドなし）")

        action = menu.exec_(self.registration_table.viewport().mapToGlobal(pos))

        if action == delete_action:
            self._delete_and_slide_image_url(row, url_idx)
        elif action == clear_action:
            self._clear_image_url(row, url_idx)


    def delete_and_slide_local_image(self, row: int, image_idx: int):
        """
        画像1〜6のセルで選択された画像を削除し、
        後ろの画像を左にスライドさせる。

        - registration_records.product_images を編集
        - 対応する image_urls もスライド
        - テーブルの画像1〜6 / 画像URL1〜5 を更新
        - 仕入DB（purchase_db）の image_url_n も反映
        """
        if row >= len(self.registration_records):
            return

        entry = self.registration_records[row]
        product_images = entry.get("product_images", [])

        if image_idx >= len(product_images):
            QMessageBox.information(self, "情報", "削除対象の画像がありません。")
            return

        target_path = product_images[image_idx]
        file_name = Path(target_path).name if target_path else f"画像{image_idx + 1}"

        reply = QMessageBox.question(
            self,
            "画像削除の確認",
            f"画像{image_idx + 1} を削除して、後ろの画像を左に詰めますか？\n\n"
            f"対象: {file_name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # product_images をスライド
        if product_images:
            del product_images[image_idx]
        # 最大6枚に制限しておく
        while len(product_images) < 6:
            product_images.append("")
        entry["product_images"] = product_images[:6]

        # image_urls も同じようにスライド
        image_urls = entry.get("image_urls", [])
        if image_idx < len(image_urls):
            del image_urls[image_idx]
        while len(image_urls) < 5:
            image_urls.append("")
        entry["image_urls"] = image_urls[:5]

        # テーブル上の画像1〜6 / 画像URL1〜5 を更新
        # 画像1〜6列は5〜10、画像URL1〜5列は11〜15
        for idx in range(6):
            col = 5 + idx
            if col >= self.registration_table.columnCount():
                continue
            img_path = entry["product_images"][idx] if idx < len(entry["product_images"]) else ""
            item = self.registration_table.item(row, col)
            if img_path:
                file_name = Path(img_path).name
                if not item:
                    item = QTableWidgetItem(file_name)
                    self.registration_table.setItem(row, col, item)
                else:
                    item.setText(file_name)
                item.setData(Qt.UserRole, img_path)
                item.setToolTip(img_path)
            else:
                if item:
                    item.setText("")
                    item.setData(Qt.UserRole, "")
                    item.setToolTip("")

        for idx in range(5):
            col = 11 + idx
            if col >= self.registration_table.columnCount():
                continue
            url = entry["image_urls"][idx] if idx < len(entry["image_urls"]) else ""
            item = self.registration_table.item(row, col)
            if url:
                if not item:
                    item = QTableWidgetItem(url)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    self.registration_table.setItem(row, col, item)
                else:
                    item.setText(url)
            else:
                if item:
                    item.setText("")

        # 仕入DBの image_url_n を更新
        try:
            sku = entry.get("sku")
            if sku:
                from database.purchase_db import PurchaseDatabase

                purchase_db = PurchaseDatabase()
                purchase_record = purchase_db.get_by_sku(sku)
                update_data = {}

                # 現在の image_urls から image_url_1〜6 を再構築
                for i in range(6):
                    key = f"image_url_{i + 1}"
                    if i < len(entry["image_urls"]) and entry["image_urls"][i]:
                        update_data[key] = entry["image_urls"][i]
                    else:
                        update_data[key] = ""

                if purchase_record:
                    base = dict(purchase_record)
                    base.update(update_data)
                    base["sku"] = sku
                    purchase_db.upsert(base)
                else:
                    update_data["sku"] = sku
                    purchase_db.upsert(update_data)
        except Exception as e:
            logger.warning(f"Failed to update purchase DB after local image delete for SKU {entry.get('sku', 'N/A')}: {e}")

        QMessageBox.information(self, "削除完了", "画像を削除し、後続の画像をスライドしました。")


    def change_sku_for_registration_row(self, row: int):
        """
        SKU列を右クリックしたときに、JANから仕入DBを検索して
        SKU候補を一覧表示し、選択または直接入力できるようにする。
        """
        if row >= len(self.registration_records):
            return

        entry = self.registration_records[row]
        jan = (entry.get("jan") or "").strip()
        if not jan:
            # テーブルのJANセルからも試す
            item = self.registration_table.item(row, 3)
            if item:
                jan = (item.text() or "").strip()

        if not jan:
            QMessageBox.warning(self, "エラー", "JANコードが設定されていないため、SKU候補を検索できません。")
            return

        # 仕入DBからJANで候補検索
        sku_candidates = self._search_sku_candidates_by_jan(jan)
        if not sku_candidates:
            # 候補がない場合は手入力のみ
            sku, ok = QInputDialog.getText(
                self,
                "SKU変更",
                f"JAN {jan} に対応するSKU候補が見つかりませんでした。\n"
                f"手動でSKUを入力してください：",
            )
            if not ok or not sku:
                return
            sku = sku.strip()
        else:
            # 「SKU - 商品名」を一覧表示
            items = []
            sku_map: Dict[str, Dict[str, Any]] = {}
            for record in sku_candidates:
                cand_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                if not cand_sku:
                    continue
                name = (
                    record.get("商品名")
                    or record.get("product_name")
                    or record.get("title")
                    or ""
                )
                label = cand_sku if not name else f"{cand_sku} - {name}"
                if label not in sku_map:
                    items.append(label)
                    sku_map[label] = record

            dlg = QInputDialog(self)
            dlg.setWindowTitle("SKU変更")
            dlg.setLabelText(
                f"JAN {jan} に対応するSKU候補を選択するか、直接SKUを入力してください："
            )
            dlg.setComboBoxEditable(True)
            dlg.setComboBoxItems(items)
            dlg.setStyleSheet(
                "QComboBox, QLineEdit, QListView {"
                "  color: black;"
                "  background-color: white;"
                "}"
                "QListView::item:selected {"
                "  color: black;"
                "  background-color: #cce4ff;"
                "}"
            )

            if dlg.exec_() != QDialog.Accepted:
                return

            selected_text = dlg.textValue().strip()
            if selected_text in sku_map:
                sku = str(sku_map[selected_text].get("SKU") or sku_map[selected_text].get("sku") or "").strip()
                # 商品名が空なら、候補の名称を登録しておく
                if not entry.get("product_name"):
                    name = (
                        sku_map[selected_text].get("商品名")
                        or sku_map[selected_text].get("product_name")
                        or sku_map[selected_text].get("title")
                        or ""
                    )
                    entry["product_name"] = name
                    name_item = self.registration_table.item(row, 4)
                    if name_item:
                        name_item.setText(name)
            else:
                # 直接入力されたとみなす
                sku = selected_text.split()[0] if selected_text else ""

        if not sku:
            QMessageBox.warning(self, "エラー", "有効なSKUが入力されませんでした。")
            return

        # registration_records と テーブルを更新
        entry["sku"] = sku
        sku_item = self.registration_table.item(row, 1)
        if sku_item:
            sku_item.setText(sku)
        else:
            self.registration_table.setItem(row, 1, QTableWidgetItem(sku))

        QMessageBox.information(
            self,
            "SKU変更",
            f"SKUを「{sku}」に変更しました。",
        )


    def _delete_and_slide_image_url(self, row: int, url_idx: int):
        """指定した画像URLを削除し、後続URLを前にスライド"""
        if row >= len(self.registration_records):
            return
        
        entry = self.registration_records[row]
        if "image_urls" not in entry:
            entry["image_urls"] = [""] * 5
        
        # URLリストを5要素に揃える
        while len(entry["image_urls"]) < 5:
            entry["image_urls"].append("")
        
        # 指定インデックス以降を前にスライド
        for i in range(url_idx, 4):
            entry["image_urls"][i] = entry["image_urls"][i + 1]
        entry["image_urls"][4] = ""  # 最後は空に
        
        # テーブルUIを更新
        self._update_image_url_cells(row, entry)


    def _clear_image_url(self, row: int, url_idx: int):
        """指定した画像URLをクリア（スライドなし）"""
        if row >= len(self.registration_records):
            return
        
        entry = self.registration_records[row]
        if "image_urls" not in entry:
            entry["image_urls"] = [""] * 5
        
        while len(entry["image_urls"]) <= url_idx:
            entry["image_urls"].append("")
        
        entry["image_urls"][url_idx] = ""
        
        # テーブルUIを更新
        self._update_image_url_cells(row, entry)


    def _update_image_url_cells(self, row: int, entry: Dict[str, Any]):
        """画像URL1～5のセルを更新"""
        col_offset = 11  # 画像URL1の列インデックス
        self.registration_table.blockSignals(True)
        try:
            for idx in range(5):
                col = col_offset + idx
                url = entry.get("image_urls", [])[idx] if idx < len(entry.get("image_urls", [])) else ""
                item = self.registration_table.item(row, col)
                if item:
                    item.setText(url)
                else:
                    item = QTableWidgetItem(url)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    self.registration_table.setItem(row, col, item)
        finally:
            self.registration_table.blockSignals(False)


    def _set_registration_preview(self, image_path: Optional[str]):
        """プレビュー画像の更新"""
        if not image_path:
            self.registration_preview_label.setText("画像を選択してください")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        file_path = Path(image_path)
        if not file_path.exists():
            self.registration_preview_label.setText("画像ファイルが見つかりません")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        pixmap = QPixmap(str(file_path))
        if pixmap.isNull():
            self.registration_preview_label.setText("画像を読み込めませんでした")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        max_width = self.registration_preview_label.width() - 20
        max_height = self.registration_preview_label.height() - 20
        scaled = pixmap.scaled(
            max_width,
            max_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.registration_preview_label.setPixmap(scaled)
        self.registration_preview_label.setAlignment(Qt.AlignCenter)
        self.registration_preview_label.setText("")


    def _set_registration_preview_url(self, url: str):
        """URL画像を下のプレビュー枠に表示（非同期・シグナル経由でメインスレッドに通知）"""
        url = (url or "").strip()
        if not url:
            self.registration_preview_label.setText("画像URLが空です")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        # よくある誤入力（https://...）を検出
        if url.endswith("...") or url.endswith("…") or url == "https://..." or url == "http://...":
            self.registration_preview_label.setText("画像URLが省略表示のままです（https://...）。\n実際のURLを入力してください。")
            self.registration_preview_label.setPixmap(QPixmap())
            return

        self._registration_preview_pending_url = url
        self.registration_preview_label.setPixmap(QPixmap())
        self.registration_preview_label.setText("画像を読み込み中...")

        token = url

        def _fetch_and_emit():
            """バックグラウンドで画像取得してシグナルで通知"""
            try:
                req = Request(url, headers={"User-Agent": "HIRIO-DesktopApp/1.0"})
                with urlopen(req, timeout=15) as resp:
                    data = resp.read()
                self._preview_image_ready.emit(token, data)
            except HTTPError as e:
                self._preview_image_error.emit(token, f"画像取得に失敗しました（HTTP {e.code}）")
            except URLError as e:
                self._preview_image_error.emit(token, f"画像取得に失敗しました（通信エラー）\n{e}")
            except Exception as e:
                self._preview_image_error.emit(token, f"画像取得に失敗しました\n{e}")

        try:
            self._registration_preview_executor.submit(_fetch_and_emit)
        except Exception as e:
            self.registration_preview_label.setText(f"URLの読み込みに失敗しました:\n{e}")
            self.registration_preview_label.setPixmap(QPixmap())


    def _on_preview_image_ready(self, token: str, data: bytes):
        """シグナル受信: 画像データをプレビューに表示（メインスレッド）"""
        if token != self._registration_preview_pending_url:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self.registration_preview_label.setText("画像を読み込めませんでした（形式不明）")
            self.registration_preview_label.setPixmap(QPixmap())
            return
        max_width = self.registration_preview_label.width() - 20
        max_height = self.registration_preview_label.height() - 20
        if max_width < 10:
            max_width = 400
        if max_height < 10:
            max_height = 200
        scaled = pixmap.scaled(
            max_width,
            max_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.registration_preview_label.setPixmap(scaled)
        self.registration_preview_label.setAlignment(Qt.AlignCenter)
        self.registration_preview_label.setText("")


    def _on_preview_image_error(self, token: str, error_message: str):
        """シグナル受信: エラーメッセージを表示（メインスレッド）"""
        if token != self._registration_preview_pending_url:
            return
        self.registration_preview_label.setText(error_message)
        self.registration_preview_label.setPixmap(QPixmap())


    def _show_remote_image_dialog(self, url: str):
        """URLの画像をダイアログ表示"""
        if not url:
            return
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = resp.read()
            pixmap = QPixmap()
            if not pixmap.loadFromData(data):
                QMessageBox.warning(self, "エラー", f"画像を読み込めませんでした:\n{url}")
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("画像プレビュー")
            layout = QVBoxLayout(dialog)
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)

            # 最大表示サイズ
            scaled = pixmap.scaled(1000, 800, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(scaled)
            dialog.resize(min(1100, scaled.width() + 40), min(900, scaled.height() + 60))
            dialog.exec()
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"画像の取得に失敗しました:\n{url}\n\n{e}")


