#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入DB 一覧・フィルタ・増分描画 mixin。"""
from __future__ import annotations

import sys
import os
import re
import unicodedata
import calendar
from datetime import datetime, date
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple, Iterable
import copy
import json
import logging

from PySide6.QtCore import Qt, QMimeData, QUrl, QSettings, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QDialog, QDialogButtonBox,
    QMessageBox, QLabel, QTabWidget, QHeaderView, QFileDialog, QMenu, QApplication,
    QAbstractItemView, QComboBox, QProgressDialog, QCheckBox, QToolButton, QScrollArea, QFrame,
    QSizePolicy, QStyledItemDelegate,
)
from PySide6.QtGui import QDrag, QPixmap, QDesktopServices, QCursor, QColor

from desktop.utils.ui_utils import (
    save_table_header_state, restore_table_header_state,
    save_table_column_widths, restore_table_column_widths
)

logger = logging.getLogger(__name__)

try:
    from utils._desktop_import_compat import (
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        SCROLL_LOAD_THRESHOLD_PX,
        apply_monthly_auto_ladder_to_record,
        augment_purchase_cost_records,
        backfill_condition_label_in_record,
        backfill_purchase_date_from_sku,
        calc_elapsed_days_for_purchase_record as _calc_elapsed_days_for_purchase_record,
        compute_break_even_for_record,
        fee_storage_value,
        fill_purchase_record_tp_from_369,
        get_augment_batch_size,
        get_page_size,
        is_amazon_sales_channel,
        is_eligible_for_monthly_auto,
        is_fee_amount_column,
        is_incremental_render_enabled,
        load_369_repricer_config,
        merge_purchase_history_db_into_display_records,
        normalize_status_code,
        purchase_record_purchase_timestamp,
        resolve_local_image_path,
        resolve_record_product_images,
        should_recompute_break_even,
        sort_purchase_records_for_display,
        summarize_repricing_row,
    )
    from utils._desktop_ui_compat import PurchaseRowEditDialog
except ImportError:
    from desktop.utils._desktop_import_compat import (  # type: ignore
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        SCROLL_LOAD_THRESHOLD_PX,
        apply_monthly_auto_ladder_to_record,
        augment_purchase_cost_records,
        backfill_condition_label_in_record,
        backfill_purchase_date_from_sku,
        calc_elapsed_days_for_purchase_record as _calc_elapsed_days_for_purchase_record,
        compute_break_even_for_record,
        fee_storage_value,
        fill_purchase_record_tp_from_369,
        get_augment_batch_size,
        get_page_size,
        is_amazon_sales_channel,
        is_eligible_for_monthly_auto,
        is_fee_amount_column,
        is_incremental_render_enabled,
        load_369_repricer_config,
        merge_purchase_history_db_into_display_records,
        normalize_status_code,
        purchase_record_purchase_timestamp,
        resolve_local_image_path,
        resolve_record_product_images,
        should_recompute_break_even,
        sort_purchase_records_for_display,
        summarize_repricing_row,
    )
    from desktop.utils._desktop_ui_compat import PurchaseRowEditDialog  # type: ignore

from .support import (
    PRODUCT_NAME_DISPLAY_LIMIT,
    SortableDateItem,
    PurchaseFullTextItemDelegate,
    DraggableTableWidget,
    ProductEditDialog,
    _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV,
    _PURCHASE_RIGHT_ALIGN_NUMERIC_HEADERS,
    _PURCHASE_STATUS_FILTER_OPTIONS,
    _PURCHASE_CHANNEL_FILTER_OPTIONS,
    _PURCHASE_FILE_PATH_COLUMNS,
    _PURCHASE_URL_COLUMNS,
    _PURCHASE_FULLTEXT_MIN_COLUMN_WIDTH,
    _purchase_numeric_cell_text,
    _make_purchase_numeric_table_item,
    _purchase_record_sales_channel,
    _purchase_record_shipping_method,
    purchase_record_matches_amazon_mfn_filter,
    purchase_record_matches_non_amazon_channel_filter,
    _purchase_table_cell_full_text,
)


class PurchaseTableMixin:
    def load_purchase_data(self, records: List[Dict[str, Any]]):
        """仕入DBデータを読み込み"""
        if not records:
            self.purchase_all_records_master = []
            self.purchase_all_records = []
            self.purchase_records = []
            self._invalidate_purchase_table_full_master()
            self.populate_purchase_table([])
            self.update_purchase_count_label()
            return

        # 起動時はスナップショットから復元されるため、DB側の最新情報（ステータス/理由など）をマージしてから表示する
        merged = list(records or [])
        try:
            merged = merge_purchase_history_db_into_display_records(
                records or [],
                self.purchase_history_db,
                include_db_only_rows=True,
            )
        except Exception as e:
            print(f"仕入DBデータのmergeエラー: {e}")

        if self._purchase_incremental_render_enabled() and len(merged) > self._purchase_incremental_page_size():
            self._load_purchase_data_incremental(merged)
            return

        try:
            records = self._augment_purchase_records(merged)
        except Exception as e:
            print(f"仕入DBデータのaugmentエラー: {e}")
            records = merged
        # マスターを保持しておき、フィルタ時はそこから再計算する
        self.purchase_all_records_master = copy.deepcopy(records)
        self.purchase_all_records = copy.deepcopy(records)
        self.purchase_records = copy.deepcopy(records)
        self._invalidate_purchase_table_full_master()
        self.populate_purchase_table(self.purchase_records)
        self._purchase_table_full_master_built = bool(self.purchase_records)
        if self._purchase_search_filters_active():
            self.filter_purchase_records()
        else:
            self.update_purchase_count_label()

    def refresh_purchase_table_if_built(self) -> None:
        """仕入DBテーブルが構築済みなら再描画する。"""
        if not getattr(self, "_purchase_table_full_master_built", False):
            if not getattr(self, "_purchase_incremental_active", False):
                return
        records = getattr(self, "purchase_all_records", None) or []
        if (
            self._purchase_incremental_render_enabled()
            and len(records) > self._purchase_incremental_page_size()
        ):
            self.populate_purchase_table(records)
        else:
            self.populate_purchase_table(records, force_full=True)
            self._purchase_table_full_master_built = bool(records)

    def on_import_inventory(self):
        """仕入管理タブからデータを取り込み"""
        records = self._collect_inventory_records()
        if records:
            if hasattr(self, 'purchase_all_records') and self.purchase_all_records:
                reply = QMessageBox.question(
                    self, "確認", 
                    "既存のデータがあります。追加しますか？\n（Noを選ぶと既存データはクリアされます）",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                )
                if reply == QMessageBox.Cancel:
                    return
                if reply == QMessageBox.No:
                    self.purchase_all_records = []
            else:
                self.purchase_all_records = []
            
            existing_skus = {r.get("SKU") or r.get("sku") for r in self.purchase_all_records}
            new_count = 0
            for r in records:
                self._fill_tp_from_comment(r)  # コメントの1ta/1tp/2ta/2tpからTP1/TP2を補完
                sku = r.get("SKU") or r.get("sku")
                if sku and sku not in existing_skus:
                    self.purchase_all_records.append(r)
                    existing_skus.add(sku)
                    new_count += 1
                elif not sku:
                    self.purchase_all_records.append(r)
                    new_count += 1
            
            self.purchase_records = list(self.purchase_all_records)
            self._invalidate_purchase_table_full_master()
            self.populate_purchase_table(self.purchase_records)
            self._purchase_table_full_master_built = bool(self.purchase_records)
            self.filter_purchase_records()
            self.update_purchase_count_label()
            self.save_purchase_snapshot()
            
            QMessageBox.information(self, "完了", f"{new_count}件のデータを取り込みました。")

    def _build_purchase_status_collapsible_filter(self) -> QWidget:
        """仕入DB検索：ステータスを複数選択でき、パネルは折りたたみ可能。"""
        self._purchase_status_checkboxes: List[Tuple[str, QCheckBox]] = []
        self._purchase_channel_filter_checkboxes: List[Tuple[str, QCheckBox]] = []
        self._purchase_status_filter_apply_timer = QTimer(self)
        self._purchase_status_filter_apply_timer.setSingleShot(True)
        self._purchase_status_filter_apply_timer.timeout.connect(self.filter_purchase_records)
        outer = QWidget()
        outer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        v = QVBoxLayout(outer)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self._purchase_status_filter_toggle = QToolButton()
        self._purchase_status_filter_toggle.setCheckable(True)
        self._purchase_status_filter_toggle.setChecked(True)
        self._purchase_status_filter_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._purchase_status_filter_toggle.setText("ステータスで絞り込み")
        self._purchase_status_filter_toggle.setArrowType(Qt.DownArrow)
        self._purchase_status_filter_toggle.toggled.connect(self._on_purchase_status_filter_section_toggled)
        head.addWidget(self._purchase_status_filter_toggle, 0)
        hint = QLabel(
            "チェックした条件だけ表示（ステータス未選択＝全ステータス、"
            "チャネル未選択＝チャネル条件なし）"
        )
        hint.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        hint.setWordWrap(False)
        head.addWidget(hint, 0)
        v.addLayout(head)

        self._purchase_status_filter_scroll = QScrollArea()
        # 中身の高さに合わせ、ビューポート内で無駄に縦に伸ばさない
        self._purchase_status_filter_scroll.setWidgetResizable(False)
        self._purchase_status_filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._purchase_status_filter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._purchase_status_filter_scroll.setFrameShape(QFrame.StyledPanel)
        self._purchase_status_filter_scroll.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        # ダークテーマ：ビューポートが白のままだと文字が読めないため背景を黒系に固定
        _sf_bg = "#0a0a0a"
        self._purchase_status_filter_scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {_sf_bg}; border: 1px solid #444444; }}"
            "QScrollBar:vertical { background: #1a1a1a; width: 10px; margin: 0; }"
            "QScrollBar::handle:vertical { background: #555555; min-height: 24px; border-radius: 4px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self._purchase_status_filter_scroll.viewport().setStyleSheet(
            f"background-color: {_sf_bg};"
        )

        inner = QWidget()
        inner.setStyleSheet(
            f"QWidget {{ background-color: {_sf_bg}; }}"
            "QCheckBox { color: #f0f0f0; spacing: 6px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #888888; "
            "background-color: #252525; border-radius: 2px; }"
            "QCheckBox::indicator:checked { background-color: #3d7ec4; border-color: #5a9ee0; }"
        )
        row = QHBoxLayout(inner)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(12)
        for label, code in _PURCHASE_STATUS_FILTER_OPTIONS:
            cb = QCheckBox(label)
            cb.stateChanged.connect(self._on_purchase_status_filter_checkbox_changed)
            self._purchase_status_checkboxes.append((code, cb))
            row.addWidget(cb, 0)
        sep = QLabel("｜")
        sep.setStyleSheet("color: #666666; padding: 0 4px;")
        row.addWidget(sep, 0)
        for label, code in _PURCHASE_CHANNEL_FILTER_OPTIONS:
            cb = QCheckBox(label)
            cb.setToolTip(
                "Amazon自己発送: 販売チャネルが Amazon かつ発送方法が自己発送。\n"
                "フリマ等: 販売チャネルが Amazon 以外（メルカリ・ヤフオク等）。"
            )
            cb.stateChanged.connect(self._on_purchase_status_filter_checkbox_changed)
            self._purchase_channel_filter_checkboxes.append((code, cb))
            row.addWidget(cb, 0)
        clear_btn = QPushButton("クリア")
        clear_btn.setToolTip(
            "ステータス・チャネル（Amazon自己発送／フリマ等）のチェックだけ外します"
            "（日付・SKU等の検索欄はそのまま）"
        )
        clear_btn.setFixedSize(72, 22)
        clear_btn.setStyleSheet("font-size: 11px; padding: 0 4px;")
        clear_btn.clicked.connect(self._on_purchase_status_filter_clear_clicked)
        row.addWidget(clear_btn, 0)
        row.addStretch(1)

        self._purchase_status_filter_scroll.setWidget(inner)
        inner.adjustSize()
        _sh = inner.sizeHint()
        _frame = max(4, self._purchase_status_filter_scroll.frameWidth() * 2)
        self._purchase_status_filter_scroll.setFixedHeight(max(34, _sh.height() + _frame + 2))
        self._purchase_status_filter_scroll.setFixedWidth(_sh.width() + _frame + 6)
        v.addWidget(self._purchase_status_filter_scroll, 0, Qt.AlignmentFlag.AlignLeft)
        return outer

    def _on_purchase_status_filter_section_toggled(self, expanded: bool) -> None:
        if hasattr(self, "_purchase_status_filter_scroll"):
            self._purchase_status_filter_scroll.setVisible(expanded)
        if hasattr(self, "_purchase_status_filter_toggle"):
            self._purchase_status_filter_toggle.setArrowType(
                Qt.DownArrow if expanded else Qt.RightArrow
            )

    def _purchase_status_filter_selected_codes(self) -> set:
        codes: set = set()
        for code, cb in getattr(self, "_purchase_status_checkboxes", []):
            if cb.isChecked():
                codes.add(str(code).lower())
        return codes

    def _purchase_channel_filter_selected_codes(self) -> set:
        codes: set = set()
        for code, cb in getattr(self, "_purchase_channel_filter_checkboxes", []):
            if cb.isChecked():
                codes.add(str(code).lower())
        return codes

    def _purchase_record_matches_channel_filters(
        self, record: Dict[str, Any], selected: set
    ) -> bool:
        if not selected:
            return True
        if "amazon_mfn" in selected and purchase_record_matches_amazon_mfn_filter(record):
            return True
        if "non_amazon" in selected and purchase_record_matches_non_amazon_channel_filter(
            record
        ):
            return True
        return False

    def _reset_purchase_status_filter_checkboxes(self) -> None:
        for _, cb in getattr(self, "_purchase_status_checkboxes", []):
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        for _, cb in getattr(self, "_purchase_channel_filter_checkboxes", []):
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)

    def _on_purchase_status_filter_clear_clicked(self) -> None:
        self._reset_purchase_status_filter_checkboxes()
        self.filter_purchase_records()

    def _on_purchase_status_filter_checkbox_changed(self, _state: int) -> None:
        """
        チェック連打時に毎回全件再描画しないよう、短いデバウンスで反映する。
        体感の引っ掛かりを減らす目的。
        """
        t = getattr(self, "_purchase_status_filter_apply_timer", None)
        if t is None:
            self.filter_purchase_records()
            return
        t.start(120)

    def _on_purchase_repricing_filter_changed(self, _state: int) -> None:
        t = getattr(self, "_purchase_status_filter_apply_timer", None)
        if t is None:
            self.filter_purchase_records()
            return
        t.start(120)

    def _purchase_repricing_filters_active(self) -> bool:
        if getattr(self, "purchase_filter_ladder_only", None) and self.purchase_filter_ladder_only.isChecked():
            return True
        if (
            getattr(self, "purchase_filter_repricing_incomplete", None)
            and self.purchase_filter_repricing_incomplete.isChecked()
        ):
            return True
        return False

    def _reset_purchase_repricing_filter_checkboxes(self) -> None:
        for attr in ("purchase_filter_ladder_only", "purchase_filter_repricing_incomplete"):
            cb = getattr(self, attr, None)
            if cb is None:
                continue
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)

    def _summarize_repricing_for_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return summarize_repricing_row(record)

    def _purchase_record_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        sku = str(sku or "").strip()
        if not sku:
            return None
        for lst_name in (
            "purchase_all_records_master",
            "purchase_all_records",
            "purchase_records",
        ):
            lst = getattr(self, lst_name, None)
            if not isinstance(lst, list):
                continue
            for rec in lst:
                s = str(rec.get("SKU") or rec.get("sku") or "").strip()
                if s == sku:
                    return rec
        return None

    def _make_purchase_repricing_column_item(
        self, record: Dict[str, Any], header: str
    ) -> QTableWidgetItem:
        """月別・改定価格・価格改定列のセルを生成（一覧の再描画・部分更新で共用）。"""
        if header == "月別":
            summary = self._summarize_repricing_for_record(record)
            text = str(summary.get("monthly_label") or "—")
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            if summary.get("ladder_on"):
                item.setForeground(QColor("#7ec8ff"))
            else:
                item.setForeground(QColor("#888888"))
            item.setToolTip(
                "月別運用ON: 30日刻みの個別改定ルールを使用。\n"
                "OFF: TP0〜TP3（4段）を使用。"
            )
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            return item

        if header == "改定価格":
            summary = self._summarize_repricing_for_record(record)
            text = str(summary.get("price_label") or "—")
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            item.setToolTip(str(summary.get("price_tooltip") or ""))
            if not summary.get("repricing_on"):
                item.setForeground(QColor("#888888"))
            elif summary.get("price_complete"):
                item.setForeground(QColor("#7dcea0"))
            elif summary.get("filter_incomplete"):
                item.setForeground(QColor("#f5b041"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            else:
                item.setForeground(QColor("#f0f0f0"))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            return item

        if header == "価格改定":
            raw = record.get("価格改定")
            if raw is None:
                raw = record.get("repricing_enabled", 1)
            flag = str(raw).strip().lower() if raw is not None else ""
            text = "OFF" if flag in ("0", "off", "false", "無効", "no") else "ON"
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            return item

        item = QTableWidgetItem("")
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _make_purchase_receipt_image_table_item(
        self, record: Dict[str, Any]
    ) -> QTableWidgetItem:
        """レシート編集後など、レシート画像列セルを1件分だけ再構築する。"""
        value = self._get_record_value(record, ["レシート画像"])
        receipt_image_str = "" if value is None else str(value).strip()
        display_text = ""
        resolved_path = None
        item = QTableWidgetItem("")
        item.setFlags(item.flags() | Qt.ItemIsEnabled)
        saved_path = str(record.get("レシート画像パス") or "").strip()
        if saved_path and Path(saved_path).is_file():
            resolved_path = str(Path(saved_path).resolve())
            display_text = resolved_path
        elif receipt_image_str:
            file_path = self._resolve_receipt_file_path(record, receipt_image_str)
            if file_path:
                file_path_obj = Path(file_path)
                if file_path_obj.exists():
                    resolved_path = str(file_path_obj.resolve())
                    display_text = resolved_path
                    record["レシート画像パス"] = resolved_path
                else:
                    resolved_path = str(file_path)
                    display_text = resolved_path
                    record["レシート画像パス"] = file_path
        item.setText(display_text)
        if display_text.strip():
            item.setToolTip(display_text)
        if resolved_path:
            item.setData(Qt.UserRole, resolved_path)
        elif receipt_image_str:
            item.setData(Qt.UserRole, receipt_image_str)
        if display_text.strip() or receipt_image_str:
            item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
        return item

    def _refresh_purchase_repricing_table_cells_for_record(
        self, record: Dict[str, Any]
    ) -> None:
        """仕入行編集反映後、該当SKUの改定・手数料・利益系セルを即時更新する。"""
        if not hasattr(self, "purchase_columns") or not hasattr(self, "purchase_table"):
            return
        sku = str(record.get("SKU") or record.get("sku") or "").strip()
        if not sku:
            return
        master_rec = self._purchase_record_by_sku(sku) or record

        repricing_headers = ("月別", "改定価格", "価格改定")
        field_headers = (
            "発送方法",
            "販売チャネル",
            "プラットフォーム手数料",
            "Amazon手数料",
            "出荷費用",
            "費用合計",
            "仕入れ価格",
            "見込み利益",
            "損益分岐点",
            "想定利益率",
            "想定ROI",
        )

        self.purchase_table.setUpdatesEnabled(False)
        try:
            for row in range(self.purchase_table.rowCount()):
                if self._purchase_table_row_sku(row) != sku:
                    continue
                for h in repricing_headers:
                    if h not in self.purchase_columns:
                        continue
                    col = self.purchase_columns.index(h)
                    self.purchase_table.setItem(
                        row, col, self._make_purchase_repricing_column_item(master_rec, h)
                    )
                for h in field_headers:
                    if h not in self.purchase_columns:
                        continue
                    col = self.purchase_columns.index(h)
                    value = self._get_record_value(master_rec, [h])
                    if h in _PURCHASE_RIGHT_ALIGN_NUMERIC_HEADERS:
                        self.purchase_table.setItem(
                            row, col, _make_purchase_numeric_table_item(h, value)
                        )
                    else:
                        text = "" if value is None else str(value).strip()
                        self.purchase_table.setItem(row, col, QTableWidgetItem(text))
                if "レシート画像" in self.purchase_columns:
                    col = self.purchase_columns.index("レシート画像")
                    self.purchase_table.setItem(
                        row,
                        col,
                        self._make_purchase_receipt_image_table_item(master_rec),
                    )
        finally:
            self.purchase_table.setUpdatesEnabled(True)
            self.purchase_table.viewport().update()

    def _invalidate_purchase_table_full_master(self) -> None:
        self._purchase_table_full_master_built = False
        self._purchase_incremental_reset()

    def _sync_purchase_status_norm(self, record: Dict[str, Any]) -> str:
        """ステータスフィルタ用コードをレコードに反映（常に最新のステータスから計算）。"""
        code = normalize_status_code(record.get("ステータス") or record.get("status"))
        record["_status_norm"] = code
        return code

    def _purchase_search_filters_active(self) -> bool:
        if self.purchase_search_query.text().strip():
            return True
        if self._purchase_status_filter_selected_codes():
            return True
        if self._purchase_channel_filter_selected_codes():
            return True
        if self._purchase_repricing_filters_active():
            return True
        return False

    def _purchase_master_records(self) -> List[Dict[str, Any]]:
        master = getattr(self, "purchase_all_records_master", None)
        if master:
            return list(master)
        fallback = getattr(self, "purchase_all_records", None)
        return list(fallback) if fallback else []

    def _purchase_table_has_full_master_rows(self) -> bool:
        master = self._purchase_master_records()
        return bool(master) and self.purchase_table.rowCount() == len(master)

    def _purchase_record_matches_unified_search(
        self, record: Dict[str, Any], query: str
    ) -> bool:
        """1つのキーワードで日付・SKU・ASIN・JAN・商品名を部分一致検索（OR）。"""
        q = (query or "").strip()
        if not q:
            return True
        q_lower = q.lower()

        for date_key in ("仕入れ日", "purchase_date", "出品日", "listed_date"):
            date_val = str(record.get(date_key) or "").strip()
            if date_val and self._date_matches(date_val, q):
                return True
            if date_val and q.isdigit() and len(q) >= 4:
                normalized = self._normalize_date_for_search(date_val) or ""
                if normalized and q in normalized.replace("-", ""):
                    return True

        for key_a, key_b in (("SKU", "sku"), ("ASIN", "asin"), ("JAN", "jan")):
            val = str(record.get(key_a) or record.get(key_b) or "").strip()
            if val and q_lower in val.lower():
                return True

        title = str(
            record.get("商品名")
            or record.get("product_name")
            or record.get("title")
            or record.get("product_title")
            or ""
        ).strip()
        if title and q_lower in title.lower():
            return True

        return False

    def _compute_filtered_purchase_records(self) -> List[Dict[str, Any]]:
        """マスターから検索条件で絞り込み（ディープコピーしない）。"""
        keyword_query = self.purchase_search_query.text().strip()
        status_selected = self._purchase_status_filter_selected_codes()
        channel_selected = self._purchase_channel_filter_selected_codes()

        filtered_records = self._purchase_master_records()

        if keyword_query:
            filtered_records = [
                r
                for r in filtered_records
                if self._purchase_record_matches_unified_search(r, keyword_query)
            ]

        if status_selected:
            filtered_records = [
                r for r in filtered_records
                if self._sync_purchase_status_norm(r) in status_selected
            ]

        if channel_selected:
            filtered_records = [
                r
                for r in filtered_records
                if self._purchase_record_matches_channel_filters(r, channel_selected)
            ]

        if getattr(self, "purchase_filter_ladder_only", None) and self.purchase_filter_ladder_only.isChecked():
            filtered_records = [
                r
                for r in filtered_records
                if self._summarize_repricing_for_record(r).get("filter_ladder_match")
            ]

        if (
            getattr(self, "purchase_filter_repricing_incomplete", None)
            and self.purchase_filter_repricing_incomplete.isChecked()
        ):
            filtered_records = [
                r
                for r in filtered_records
                if self._summarize_repricing_for_record(r).get("filter_incomplete")
            ]

        return filtered_records

    def _purchase_table_row_sku(self, row: int) -> str:
        """テーブル行から SKU を取得（ソート後も UserRole を優先）。"""
        if not hasattr(self, "purchase_columns"):
            return ""
        sku_col = None
        for i, col in enumerate(self.purchase_columns):
            if col == "SKU":
                sku_col = i
                break
        if sku_col is None:
            return ""
        it = self.purchase_table.item(row, sku_col)
        if it is None:
            return ""
        stored = it.data(Qt.UserRole)
        if stored is not None and str(stored).strip():
            return str(stored).strip()
        return str(it.text() or "").strip()

    def _purchase_table_row_id(self, row: int) -> Optional[int]:
        preferred_cols: List[int] = []
        if hasattr(self, "purchase_columns"):
            for name in ("SKU", "仕入れ日", "ASIN", "JAN"):
                try:
                    preferred_cols.append(self.purchase_columns.index(name))
                except ValueError:
                    pass
        scan_cols = preferred_cols + [
            c for c in range(self.purchase_table.columnCount()) if c not in preferred_cols
        ]
        for c in scan_cols:
            it = self.purchase_table.item(row, c)
            if it is None:
                continue
            v = it.data(Qt.UserRole + 1)
            if v is None:
                continue
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
        return None

    def _sync_purchase_table_row_order_index(self) -> None:
        """sortItems 後の論理行 → _row_id 対応を更新（ソート後もフィルタが効くようにする）。"""
        self._purchase_table_row_ids_by_index = [
            self._purchase_table_row_id(row)
            for row in range(self.purchase_table.rowCount())
        ]

    def _sync_purchase_row_ids_to_master(
        self, source_records: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """populate で付与した _row_id / _status_norm をマスター側へ同期。"""
        sources = source_records
        if sources is None:
            sources = getattr(self, "purchase_records", None) or []
        id_by_sku: Dict[str, int] = {}
        norm_by_sku: Dict[str, str] = {}
        for rec in sources:
            sku = str(rec.get("SKU") or rec.get("sku") or "").strip()
            if not sku:
                continue
            try:
                rid = rec.get("_row_id")
                if rid is not None:
                    id_by_sku[sku] = int(rid)
            except (TypeError, ValueError):
                pass
            norm = rec.get("_status_norm")
            if norm is not None and str(norm).strip():
                norm_by_sku[sku] = str(norm).strip().lower()
        if not id_by_sku and not norm_by_sku:
            return
        for lst_name in ("purchase_all_records_master", "purchase_all_records"):
            lst = getattr(self, lst_name, None)
            if not isinstance(lst, list):
                continue
            for rec in lst:
                sku = str(rec.get("SKU") or rec.get("sku") or "").strip()
                if not sku:
                    continue
                if sku in id_by_sku:
                    rec["_row_id"] = id_by_sku[sku]
                if sku in norm_by_sku:
                    rec["_status_norm"] = norm_by_sku[sku]

    def _fast_set_row_visibility(self, visible_skus: set, show_all: bool) -> None:
        """テーブル行を SKU セットに基づいて即時表示/非表示切り替え（repopulate なし）。"""
        row_count = self.purchase_table.rowCount()
        self.purchase_table.setUpdatesEnabled(False)
        try:
            for row in range(row_count):
                if show_all:
                    self.purchase_table.setRowHidden(row, False)
                else:
                    sku = self._purchase_table_row_sku(row)
                    self.purchase_table.setRowHidden(row, sku not in visible_skus)
        finally:
            self.purchase_table.setUpdatesEnabled(True)
            self.purchase_table.viewport().repaint()
            QApplication.processEvents()

    def filter_purchase_records(self):
        """検索条件でフィルタリング"""
        if not hasattr(self, "purchase_all_records_master") or self.purchase_all_records_master is None:
            self.purchase_all_records_master = []
        if not hasattr(self, "purchase_all_records") or self.purchase_all_records is None:
            self.purchase_all_records = []

        master = self._purchase_master_records()
        filters_active = self._purchase_search_filters_active()
        filtered_records = self._compute_filtered_purchase_records()
        self.purchase_records = filtered_records

        can_fast_hide = (
            bool(master)
            and self._purchase_table_full_master_built
            and self.purchase_table.rowCount() == len(master)
            and not getattr(self, "_purchase_incremental_active", False)
        )

        if (
            not filters_active
            and getattr(self, "_purchase_incremental_active", False)
            and self._purchase_incremental_rendered > 0
            and len(self._purchase_incremental_display_records or []) == len(master)
            and self.purchase_table.rowCount() > 0
        ):
            self.purchase_records = list(master) if master else []
            self.update_purchase_count_label()
            return

        if can_fast_hide:
            if filters_active:
                visible_skus = {
                    str(r.get("SKU") or r.get("sku") or "").strip()
                    for r in filtered_records
                    if str(r.get("SKU") or r.get("sku") or "").strip()
                }
                self._fast_set_row_visibility(visible_skus, show_all=False)
            else:
                self._fast_set_row_visibility(set(), show_all=True)
            self.update_purchase_count_label()
            return

        display = filtered_records if filters_active else (master or filtered_records)
        if (
            self._purchase_incremental_render_enabled()
            and len(display) > self._purchase_incremental_page_size()
        ):
            self.populate_purchase_table(display)
        else:
            self.populate_purchase_table(display, force_full=True)
            self._purchase_table_full_master_built = bool(display)
        self.update_purchase_count_label()

    def clear_purchase_search(self):
        """検索条件をクリアして全件表示"""
        self.purchase_search_query.clear()
        self._reset_purchase_status_filter_checkboxes()
        self._reset_purchase_repricing_filter_checkboxes()
        master = self._purchase_master_records()
        self.purchase_records = list(master) if master else []

        if master and self.purchase_table.rowCount() == len(master):
            # テーブルが全件構築済み → 全行表示のみ（高速）
            self._fast_set_row_visibility(set(), show_all=True)
        else:
            self.populate_purchase_table(self.purchase_records)

        self.update_purchase_count_label()

    def toggle_view_mode(self, mode: str):
        """表示モードを切り替え"""
        # 既に選択されているボタンを再度クリックした場合は何もしない
        if hasattr(self, 'purchase_view_mode') and self.purchase_view_mode == mode:
            # 同じボタンを再度クリックした場合は、ALLに戻す
            if mode != "all":
                mode = "all"
            else:
                return  # 既にALLが選択されている場合は何もしない
        
        # ボタンの状態を更新
        self.view_all_button.setChecked(mode == "all")
        self.view_status_button.setChecked(mode == "status")
        self.view_tp_button.setChecked(mode == "tp")
        self.view_image_button.setChecked(mode == "image")
        self.view_ledger_button.setChecked(mode == "ledger")
        
        self.purchase_view_mode = mode
        
        # 列の表示/非表示を更新
        self._update_column_visibility()

    def _update_column_visibility(self):
        """列の表示/非表示を更新"""
        if not hasattr(self, 'purchase_columns'):
            return
        
        # 「仕入れ個数」列のインデックスを取得
        quantity_col_idx = None
        for i, col_name in enumerate(self.purchase_columns):
            if col_name == "仕入れ個数":
                quantity_col_idx = i
                break
        
        if quantity_col_idx is None:
            return
        
        # 表示する列の範囲を定義
        tp_columns = {"TP0", "TP1", "TP2", "TP3"}
        tp_indices = {i for i, col_name in enumerate(self.purchase_columns) if col_name in tp_columns}
        repricing_summary_columns = {"月別", "改定価格"}
        repricing_summary_indices = {
            i for i, col_name in enumerate(self.purchase_columns) if col_name in repricing_summary_columns
        }

        if self.purchase_view_mode == "all":
            # 通常表示（TP0〜TP3は非表示）
            visible_ranges = [(quantity_col_idx + 1, len(self.purchase_columns))]
        elif self.purchase_view_mode == "status":
            # ステータス・ステータス理由のみ
            status_start = None
            status_end = None
            for i, col_name in enumerate(self.purchase_columns):
                if col_name == "ステータス":
                    status_start = i
                if col_name == "ステータス理由":
                    status_end = i + 1
                    break
            if status_start is not None and status_end is not None:
                visible_ranges = [(status_start, status_end)]
            else:
                visible_ranges = []
        elif self.purchase_view_mode == "image":
            # レシート画像から画像URL6まで
            image_start = None
            image_end = None
            for i, col_name in enumerate(self.purchase_columns):
                if col_name == "レシート画像":
                    image_start = i
                if col_name == "画像URL6":
                    image_end = i + 1
                    break
            if image_start is not None and image_end is not None:
                visible_ranges = [(image_start, image_end)]
            else:
                visible_ranges = []
        elif self.purchase_view_mode == "ledger":
            # 品目から台帳登録済まで
            ledger_start = None
            ledger_end = None
            for i, col_name in enumerate(self.purchase_columns):
                if col_name == "品目":
                    ledger_start = i
                if col_name == "台帳登録済":
                    ledger_end = i + 1
                    break
            if ledger_start is not None and ledger_end is not None:
                visible_ranges = [(ledger_start, ledger_end)]
            else:
                visible_ranges = []
        elif self.purchase_view_mode == "tp":
            # TP0/TP1/TP2 だけにフォーカス
            tp_start = None
            tp_end = None
            for i, col_name in enumerate(self.purchase_columns):
                if col_name == "TP0" and tp_start is None:
                    tp_start = i
                if col_name == "TP3":
                    tp_end = i + 1
            if tp_start is not None and tp_end is not None:
                visible_ranges = [(tp_start, tp_end)]
            else:
                visible_ranges = []
        else:
            visible_ranges = []
        
        # 列の表示/非表示を設定
        for col_idx in range(len(self.purchase_columns)):
            # 「仕入れ個数」より左の列は常に表示
            if col_idx <= quantity_col_idx:
                self.purchase_table.setColumnHidden(col_idx, False)
            else:
                # 「仕入れ個数」より右の列は、表示範囲内かどうかで判定
                is_visible = False
                if self.purchase_view_mode == "all":
                    is_visible = True
                else:
                    for start, end in visible_ranges:
                        if start <= col_idx < end:
                            is_visible = True
                            break
                # TP列は「TP」モード時のみ表示
                if col_idx in tp_indices:
                    is_visible = self.purchase_view_mode == "tp"
                # 月別・改定価格は通常表示とTP表示で見える
                if col_idx in repricing_summary_indices:
                    is_visible = self.purchase_view_mode in ("all", "tp")
                self.purchase_table.setColumnHidden(col_idx, not is_visible)
        # 在庫保管手数料はSP-API運用時まで非表示
        if "在庫保管手数料" in self.purchase_columns:
            self.purchase_table.setColumnHidden(
                self.purchase_columns.index("在庫保管手数料"),
                True
            )

    def update_purchase_count_label(self):
        """保存件数ラベルを更新"""
        if not hasattr(self, 'purchase_all_records'):
            self.purchase_all_records = []
            
        master = getattr(self, "purchase_all_records_master", None) or getattr(
            self, "purchase_all_records", []
        )
        total_count = len(master) if master else 0
        filtered_count = len(self.purchase_records) if hasattr(self, "purchase_records") else 0

        if total_count == filtered_count:
            self.purchase_count_label.setText(f"保存件数: {total_count}件（スナップショット: 最大10件まで）")
        else:
            self.purchase_count_label.setText(
                f"表示: {filtered_count}件 / 全体: {total_count}件（スナップショット: 最大10件まで）"
            )

    def _normalize_date_for_search(self, date_str: str) -> Optional[str]:
        """検索用に日付を正規化（yyyy-mm-dd形式）"""
        if not date_str:
            return None
        # 区切り文字と日本語表記を統一
        date_str = (
            str(date_str)
            .replace("/", "-")
            .replace(".", "-")
            .replace("年", "-")
            .replace("月", "-")
            .replace("日", "")
        )
        parts = date_str.split("-")
        if len(parts) >= 3:
            try:
                year = int(parts[0])
                month = int(parts[1])
                # 3つ目の要素に「日付＋時刻」が入っているケースに対応（例: '29 15:56'）
                day_part = parts[2]
                import re as _re
                m = _re.match(r"\s*(\d{1,2})", str(day_part))
                if not m:
                    return date_str
                day = int(m.group(1))
                return f"{year:04d}-{month:02d}-{day:02d}"
            except ValueError:
                pass
        return date_str

    def _date_matches(self, record_date: str, search_date: str) -> bool:
        """日付が一致するかチェック（部分一致対応）"""
        if not record_date or not search_date:
            return False
        normalized_record = self._normalize_date_for_search(str(record_date))
        if not normalized_record:
            return False
        return search_date in normalized_record or normalized_record.startswith(search_date)

    def _collect_inventory_records(self) -> Optional[List[Dict[str, Any]]]:
        if not self.inventory_widget:
            QMessageBox.warning(self, "取り込み不可", "仕入管理タブへの参照がありません。")
            return None
        try:
            df = None
            if hasattr(self.inventory_widget, "get_table_data"):
                df = self.inventory_widget.get_table_data()
            if df is None:
                df = getattr(self.inventory_widget, "inventory_data", None)
            if df is None or len(df) == 0:
                QMessageBox.warning(self, "データなし", "仕入管理のデータが空です。")
                return None
        except Exception as e:
            QMessageBox.critical(self, "取り込みエラー", f"仕入データ取得に失敗しました:\n{e}")
            return None

        try:
            df = df.fillna("")
        except Exception:
            pass
        try:
            records = df.to_dict(orient="records")
        except Exception as e:
            QMessageBox.critical(self, "変換エラー", f"データ変換に失敗しました:\n{e}")
            return None
        return self._augment_purchase_records(records)

    def _augment_purchase_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """保証・レシート情報・仕入DBのステータス等を付与"""
        augmented: List[Dict[str, Any]] = []
        for record in records:
            row = dict(record)
            sku = row.get("SKU") or row.get("sku")
            backfill_purchase_date_from_sku(row)
            backfill_condition_label_in_record(row)
            for i in range(1, 7):
                image_url_key = f"image_url_{i}"
                image_url_col = f"画像URL{i}"
                if image_url_col not in row or not row.get(image_url_col):
                    image_url = record.get(image_url_key) or record.get(f"画像URL{i}")
                    if image_url:
                        row[image_url_col] = image_url
            comment_warranty = self._infer_warranty_from_comment(row)
            if comment_warranty:
                # コメントから取得した保証期間は保証最終日として扱う
                row["保証最終日"] = comment_warranty
            # コメントの「1ta/1tp数字」「2ta/2tp数字」からTP1/TP2を補完
            self._fill_tp_from_comment(row)
            resolve_record_product_images(row)

            if sku:
                try:
                    product = self.db.get_by_sku(sku)
                except Exception:
                    product = None
                if product:
                    # 保証期間（日数）を取得
                    warranty_period_days = product.get("warranty_period_days")
                    if warranty_period_days is not None and "保証期間" not in row:
                        row["保証期間"] = warranty_period_days
                    
                    # 保証最終日を取得
                    warranty_until = product.get("warranty_until")
                    if warranty_until and "保証最終日" not in row:
                        row["保証最終日"] = warranty_until
                    
                    if "レシート画像" not in row and product.get("receipt_id") is not None:
                        row["レシート画像"] = product.get("receipt_id")
                    for i in range(1, 7):
                        image_key = f"image_{i}"
                        image_col = f"画像{i}"
                        if image_col not in row or not row.get(image_col):
                            image_path = product.get(image_key)
                            if image_path:
                                row[image_col] = image_path
                        # 画像URLを取得
                        image_url_key = f"image_url_{i}"
                        image_url_col = f"画像URL{i}"
                        if image_url_col not in row or not row.get(image_url_col):
                            image_url = product.get(image_url_key)
                            if image_url:
                                row[image_url_col] = image_url
                # 保証書情報の取得
                try:
                    warranties = self.warranty_db.list_by_sku(sku)
                except Exception:
                    warranties = []
                
                if warranties:
                    # 最新の保証書を取得
                    warranty = warranties[0]
                    # 保証書画像（ファイル名、拡張子なし）
                    warranty_file_path = warranty.get('file_path', '')
                    if warranty_file_path:
                        from pathlib import Path
                        warranty_image_name = Path(warranty_file_path).stem
                        if "保証書画像" not in row:
                            row["保証書画像"] = warranty_image_name
                    
                    # 保証書ID（後方互換性のため保持、ただし保証書画像が設定されていない場合のみ）
                    warranty_id = warranty.get('id')
                    if warranty_id is not None:
                        # 旧カラム名「保証書ID」も設定（後方互換性）
                        if "保証書ID" not in row:
                            row["保証書ID"] = warranty_id
                else:
                    # 保証書DBにない場合、既存の「保証書ID」から保証書画像を取得を試みる
                    if "保証書画像" not in row and "保証書ID" in row:
                        warranty_id = row.get("保証書ID")
                        if warranty_id:
                            try:
                                warranty = self.warranty_db.get_warranty(int(warranty_id))
                                if warranty:
                                    warranty_file_path = warranty.get('file_path', '')
                                    if warranty_file_path:
                                        from pathlib import Path
                                        warranty_image_name = Path(warranty_file_path).stem
                                        row["保証書画像"] = warranty_image_name
                            except Exception:
                                pass
                
                # 保証期間と保証最終日をProductDatabaseから取得
                if product:
                    # 保証期間（日数）を取得
                    warranty_period_days = product.get("warranty_period_days")
                    if warranty_period_days is not None and "保証期間" not in row:
                        row["保証期間"] = warranty_period_days
                    
                    # 保証最終日を取得
                    warranty_until = product.get("warranty_until")
                    if warranty_until and "保証最終日" not in row:
                        row["保証最終日"] = warranty_until

                # --- 仕入DBからステータス等を取得 ---
                try:
                    purchase_info = self.purchase_history_db.get_by_sku(sku)
                    if purchase_info:
                        sales_channel = str(purchase_info.get("sales_channel") or "").strip() or "Amazon"
                        row["販売チャネル"] = str(row.get("販売チャネル") or "").strip() or sales_channel
                        # 画像URLは PurchaseDatabase 側を正として補完する。
                        # products テーブル未作成SKUでも、仕入DBタブで URL が消えないようにする。
                        for i in range(1, 7):
                            image_url_col = f"画像URL{i}"
                            if image_url_col not in row or not row.get(image_url_col):
                                url_val = purchase_info.get(f"image_url_{i}")
                                if url_val:
                                    row[image_url_col] = url_val
                        status = purchase_info.get("status", "ready")
                        status_reason = purchase_info.get("status_reason", "")
                        status_set_at = purchase_info.get("status_set_at", "")
                        listed_date = purchase_info.get("listed_date") or ""

                        row["ステータス"] = status
                        row["status"] = status
                        if status_reason:
                            row["ステータス理由"] = status_reason
                            row["status_reason"] = status_reason
                        if str(status or "").strip().lower() == "selling":
                            sr_now = str(
                                row.get("ステータス理由") or row.get("status_reason") or ""
                            ).strip()
                            if not sr_now:
                                row["ステータス理由"] = _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV
                                row["status_reason"] = _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV
                        tp0 = purchase_info.get("tp0") or ""
                        tp1 = purchase_info.get("tp1") or purchase_info.get("ta1") or ""
                        tp2 = purchase_info.get("tp2") or purchase_info.get("ta2") or ""
                        tp3 = purchase_info.get("tp3") or ""
                        if tp0:
                            row["TP0"] = tp0
                            row["tp0"] = tp0
                        if tp1:
                            row["TP1"] = tp1
                            row["tp1"] = tp1
                        if tp2:
                            row["TP2"] = tp2
                            row["tp2"] = tp2
                        if tp3:
                            row["TP3"] = tp3
                            row["tp3"] = tp3
                        if status_set_at:
                            row["status_set_at"] = status_set_at
                        # 出品日は視認用。値がなければ空文字のまま
                        if listed_date:
                            row["出品日"] = listed_date
                            row["listed_date"] = listed_date
                        repricing_enabled = purchase_info.get("repricing_enabled", 1)
                        row["価格改定"] = "OFF" if str(repricing_enabled).strip().lower() in ("0", "off", "false", "no") else "ON"
                        le = purchase_info.get("ladder_enabled")
                        if le is not None:
                            row["ladder_enabled"] = le
                        lr = purchase_info.get("ladder_rules")
                        if lr:
                            row["ladder_rules"] = lr
                        st = str(purchase_info.get("status") or "").strip().lower()
                        if st == "inventory_only":
                            row["ステータス"] = "inventory_only"
                            row["status"] = "inventory_only"
                except Exception as e:
                    print(f"仕入DB情報取得エラー(SKU={sku}): {e}")
            # 既存データ互換: 未設定時は Amazon を既定値にする
            if not str(row.get("販売チャネル") or "").strip():
                row["販売チャネル"] = "Amazon"

            # レシート画像は証憑管理の linked_skus 紐付けがある SKU のみ反映
            self._sync_receipt_fields_from_voucher_link(row)

            self._sync_purchase_status_norm(row)
            row["_hirio_augmented"] = True
            augmented.append(row)
        return augment_purchase_cost_records(augmented)

    def _augment_one_purchase_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """1件だけ augment（段階読み込み用）。"""
        rows = self._augment_purchase_records([record])
        return rows[0] if rows else dict(record)

    def _ensure_purchase_records_augmented(self, start: int, end: int) -> None:
        """指定範囲の仕入レコードを in-place で augment（済みはスキップ）。"""
        master = getattr(self, "purchase_all_records", None) or []
        if not master:
            return
        start = max(0, start)
        end = min(end, len(master))
        if start >= end:
            return
        changed = False
        for i in range(start, end):
            if master[i].get("_hirio_augmented"):
                continue
            aug = self._augment_one_purchase_record(master[i])
            master[i].clear()
            master[i].update(aug)
            changed = True
        if changed:
            augment_purchase_cost_records(master[start:end])
        if end > getattr(self, "_purchase_augmented_through", 0):
            self._purchase_augmented_through = end

    def _ensure_display_records_augmented(
        self, records: List[Dict[str, Any]], start: int, end: int
    ) -> None:
        """表示用リストの指定範囲を in-place で augment（段階描画と同じ順序）。"""
        if not records:
            return
        start = max(0, start)
        end = min(end, len(records))
        if start >= end:
            return
        changed = False
        for i in range(start, end):
            if records[i].get("_hirio_augmented"):
                continue
            aug = self._augment_one_purchase_record(records[i])
            records[i].clear()
            records[i].update(aug)
            changed = True
        if changed:
            augment_purchase_cost_records(records[start:end])

    def _purchase_record_purchase_timestamp(self, record: Dict[str, Any]) -> float:
        return purchase_record_purchase_timestamp(record)

    def _purchase_records_for_incremental_display(
        self, records: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return sort_purchase_records_for_display(records)

    def ensure_purchase_records_fully_augmented(self) -> None:
        """一括処理前に全件 augment を完了させる（段階読み込み中でも安全）。"""
        total = len(getattr(self, "purchase_all_records", None) or [])
        if total <= 0:
            return
        self._ensure_purchase_records_augmented(0, total)

    def _purchase_incremental_render_enabled(self) -> bool:
        return is_incremental_render_enabled(getattr(self, "settings", None))

    def _purchase_incremental_page_size(self) -> int:
        return get_page_size(getattr(self, "settings", None))

    def _purchase_incremental_augment_batch_size(self) -> int:
        return get_augment_batch_size(getattr(self, "settings", None))

    def _purchase_incremental_reset(self) -> None:
        self._purchase_incremental_active = False
        self._purchase_incremental_display_records = []
        self._purchase_incremental_rendered = 0
        self._purchase_incremental_loading_more = False

    def _update_purchase_incremental_built_flag(self) -> None:
        """段階描画の進捗に応じて _purchase_table_full_master_built を更新。"""
        if not self._purchase_incremental_active:
            return
        display = self._purchase_incremental_display_records or []
        master = self._purchase_master_records()
        fully_rendered = self._purchase_incremental_rendered >= len(display)
        is_full_master_view = (
            len(display) == len(master)
            and not self._purchase_search_filters_active()
        )
        self._purchase_table_full_master_built = bool(
            fully_rendered and is_full_master_view and display
        )

    def _ensure_purchase_scroll_listener(self) -> None:
        if self._purchase_scroll_load_connected:
            return
        if not hasattr(self, "purchase_table"):
            return
        bar = self.purchase_table.verticalScrollBar()
        bar.valueChanged.connect(self._on_purchase_table_scroll)
        self._purchase_scroll_load_connected = True

    def _on_purchase_table_scroll(self, value: int) -> None:
        if not self._purchase_incremental_active or self._purchase_incremental_loading_more:
            return
        bar = self.purchase_table.verticalScrollBar()
        if bar.maximum() - value > SCROLL_LOAD_THRESHOLD_PX:
            return
        self._purchase_incremental_load_more_rows()

    def _maybe_purchase_incremental_prefetch(self) -> None:
        """
        行数が少なくスクロールバーが出ない場合も次ページを先読みする。
        （全件が画面に収まり末尾スクロールが発生しないケース対策）
        """
        if not self._purchase_incremental_active or self._purchase_incremental_loading_more:
            return
        display = self._purchase_incremental_display_records or []
        if self._purchase_incremental_rendered >= len(display):
            return
        bar = self.purchase_table.verticalScrollBar()
        if bar.maximum() > SCROLL_LOAD_THRESHOLD_PX:
            return
        self._purchase_incremental_load_more_rows()

    def _schedule_background_augment(self) -> None:
        """表示中のテーブルとは別に、メモリ上の残りレコードをバックグラウンド augment。"""
        if not self._purchase_incremental_render_enabled():
            return
        total = len(getattr(self, "purchase_all_records", None) or [])
        if self._purchase_augmented_through >= total:
            return
        QTimer.singleShot(20, self._run_background_augment_batch)

    def _run_background_augment_batch(self) -> None:
        if not self._purchase_incremental_render_enabled():
            return
        total = len(getattr(self, "purchase_all_records", None) or [])
        start = self._purchase_augmented_through
        if start >= total:
            return
        batch = self._purchase_incremental_augment_batch_size()
        end = min(start + batch, total)
        try:
            self._ensure_purchase_records_augmented(start, end)
        except Exception as exc:
            logging.getLogger(__name__).warning("仕入DBバックグラウンドaugment失敗: %s", exc)
            return
        if end < total:
            QTimer.singleShot(20, self._run_background_augment_batch)

    def _purchase_incremental_begin_display(self, records: List[Dict[str, Any]]) -> None:
        """段階読み込み: 先頭ページのみテーブル描画。"""
        records = self._purchase_records_for_incremental_display(records or [])
        self._purchase_incremental_active = True
        self._purchase_incremental_display_records = records
        total = len(records)
        page = self._purchase_incremental_page_size()
        first_end = min(page, total)
        master = self._purchase_master_records()
        col_source = master if master and len(master) >= total else records
        self._ensure_display_records_augmented(records, 0, first_end)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.purchase_table.setUpdatesEnabled(False)
        try:
            self._populate_purchase_table_impl(
                records,
                render_start=0,
                render_end=first_end,
                append=False,
                column_scan_records=col_source,
                finalize=(first_end >= total),
            )
        finally:
            self.purchase_table.setUpdatesEnabled(True)
            QApplication.restoreOverrideCursor()
            self.purchase_table.viewport().repaint()
            QApplication.processEvents()
        self._purchase_incremental_rendered = first_end
        self._update_purchase_incremental_built_flag()
        self._ensure_purchase_scroll_listener()
        if first_end < total:
            self._schedule_background_augment()
        QTimer.singleShot(0, self._maybe_purchase_incremental_prefetch)

    def _purchase_incremental_load_more_rows(self) -> None:
        """スクロール末尾で次のページをテーブルに追加。"""
        if not self._purchase_incremental_active or self._purchase_incremental_loading_more:
            return
        display = self._purchase_incremental_display_records or []
        total = len(display)
        rendered = self._purchase_incremental_rendered
        if rendered >= total:
            return
        self._purchase_incremental_loading_more = True
        try:
            page = self._purchase_incremental_page_size()
            next_end = min(rendered + page, total)
            self._ensure_display_records_augmented(display, rendered, next_end)
            master = self._purchase_master_records()
            col_source = master if master and len(master) >= total else display
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.purchase_table.setUpdatesEnabled(False)
            try:
                self._populate_purchase_table_impl(
                    display,
                    render_start=rendered,
                    render_end=next_end,
                    append=True,
                    column_scan_records=col_source,
                    finalize=(next_end >= total),
                )
            finally:
                self.purchase_table.setUpdatesEnabled(True)
                QApplication.restoreOverrideCursor()
                self.purchase_table.viewport().repaint()
                QApplication.processEvents()
            self._purchase_incremental_rendered = next_end
            self._update_purchase_incremental_built_flag()
            QTimer.singleShot(0, self._maybe_purchase_incremental_prefetch)
        except Exception as exc:
            logging.getLogger(__name__).warning("仕入DB段階読み込み追加失敗: %s", exc)
        finally:
            self._purchase_incremental_loading_more = False

    def _purchase_incremental_load_all_rows_sync(self) -> None:
        """段階読み込み中でも保存・一括処理前にテーブルへ全行を描画する。"""
        if not getattr(self, "_purchase_incremental_active", False):
            return
        display = self._purchase_incremental_display_records or []
        guard = 0
        while self._purchase_incremental_rendered < len(display) and guard < 10000:
            self._purchase_incremental_load_more_rows()
            guard += 1
        self._update_purchase_incremental_built_flag()

    def _load_purchase_data_incremental(self, merged: List[Dict[str, Any]]) -> None:
        """merge 済みデータを段階 augment + 段階描画で読み込む。"""
        base = [dict(r) for r in (merged or [])]
        self.purchase_all_records_master = base
        self.purchase_all_records = base
        self.purchase_records = list(base)
        self._purchase_augmented_through = 0
        self._invalidate_purchase_table_full_master()
        if not base:
            self.populate_purchase_table([], force_full=True)
            self.update_purchase_count_label()
            return
        self._purchase_incremental_begin_display(self.purchase_records)
        if self._purchase_search_filters_active():
            self.filter_purchase_records()
        else:
            self.update_purchase_count_label()

    def populate_purchase_table(
        self, records: List[Dict[str, Any]], *, force_full: bool = False
    ):
        """仕入DBテーブルにレコードを反映"""
        from pathlib import Path
        records = records or []
        for record in records:
            self._sync_receipt_fields_from_voucher_link(record)
        augment_purchase_cost_records(records)

        use_incremental = (
            not force_full
            and self._purchase_incremental_render_enabled()
            and len(records) > self._purchase_incremental_page_size()
        )

        if use_incremental:
            self._purchase_incremental_begin_display(records)
            return

        self._purchase_incremental_reset()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.purchase_table.setUpdatesEnabled(False)
        try:
            self._populate_purchase_table_impl(records)
        except Exception as e:
            raise
        finally:
            self.purchase_table.setUpdatesEnabled(True)
            QApplication.restoreOverrideCursor()
            # repaint() は同期描画なのでクリック不要で即時反映される
            self.purchase_table.viewport().repaint()
            QApplication.processEvents()

    def _populate_purchase_table_impl(
        self,
        records: List[Dict[str, Any]],
        *,
        render_start: int = 0,
        render_end: int | None = None,
        append: bool = False,
        column_scan_records: List[Dict[str, Any]] | None = None,
        finalize: bool = True,
    ):
        from pathlib import Path
        records = records or []
        if render_end is None:
            render_end = len(records)
        render_start = max(0, min(render_start, len(records)))
        render_end = max(render_start, min(render_end, len(records)))
        slice_records = records[render_start:render_end]
        scan_records = column_scan_records if column_scan_records is not None else records

        base_columns = list(self.inventory_columns)
        if not base_columns:
            base_columns = self._resolve_inventory_columns()

        # 仕入DBテーブルでは「仕入れ日」の右に「出品日」「経過日数」カラムを追加しておく
        columns = list(base_columns)
        try:
            if "出品日" not in columns:
                purchase_date_idx = columns.index("仕入れ日")
                columns.insert(purchase_date_idx + 1, "出品日")
            if "経過日数" not in columns:
                listed_date_idx = columns.index("出品日")
                columns.insert(listed_date_idx + 1, "経過日数")
        except ValueError:
            # 「仕入れ日」列が存在しない場合はそのまま（開発用などの特殊レイアウト想定）
            pass
        seen = set(col.upper() for col in columns)
        
        # 古物台帳用カラムは ledger_db に保存するため仕入DBには表示しない（残骸列の除外）
        _purchase_table_exclude_columns = frozenset({
            "品目", "品名", "氏名(個人)", "本人確認書類", "確認番号", "確認日", "確認者", "台帳登録済",
            "person_name", "person_address", "id_type", "id_number", "id_checked_on", "id_checked_by", "id_proof_ref",
            "kobutsu_kind", "hinmoku", "hinmei",
            # 表示専用の計算列
            "経過日数",
            # TA0/TA1/TA2/TA3 系の古い列は今後は表示しない
            "TA0", "TA1", "TA2", "TA3", "ta0", "ta1", "ta2", "ta3",
        })
        
        # レコードから追加の列を取得（既にcolumnsに含まれているもの・古物台帳用除外リストは除外）
        for record in scan_records:
            for key in record.keys():
                if key in _purchase_table_exclude_columns:
                    continue
                upper_key = key.upper()
                if upper_key in ("TA0", "TA1", "TA2", "TA3"):
                    # 念のため大文字マッチでも除外
                    continue
                if upper_key not in seen:
                    seen.add(upper_key)
                    columns.append(key)
        for tail_col in ("月別", "改定価格", "価格改定"):
            while tail_col in columns:
                columns.remove(tail_col)
        for tail_col in ("月別", "改定価格", "価格改定"):
            columns.append(tail_col)
        self.purchase_columns = columns
        # _row_id は下のループ内で欠けている行に採番する。採番前にマップを作るとキーが欠落し、
        # 編集時に row_map ミス→SKU先頭一致で別商品が開く不具合になるため、ここでは空にしてループ内で登録する。
        if not append:
            self._purchase_row_map = {}
            self._purchase_table_row_ids_by_index: List[Optional[int]] = []

        # テーブル内容をクリアし、更新中はソート/シグナルを止める（穴あき防止）
        if not append:
            self.purchase_table.blockSignals(True)
            self.purchase_table.setSortingEnabled(False)
            self.purchase_table.clearContents()
            self.purchase_table.setRowCount(len(slice_records))
            self.purchase_table.setColumnCount(len(columns))
        else:
            self.purchase_table.blockSignals(True)
            self.purchase_table.setSortingEnabled(False)
            base_append_row = self.purchase_table.rowCount()
            self.purchase_table.setRowCount(base_append_row + len(slice_records))

        if not append:
            base_row = 0
        else:
            base_row = self.purchase_table.rowCount() - len(slice_records)

        if not append:
            # 表示ラベルだけ「仕入先」→「店舗コード」に置き換え
            display_columns = list(columns)
            try:
                idx = display_columns.index("仕入先")
                display_columns[idx] = "店舗コード"
            except ValueError:
                pass
            self.purchase_table.setHorizontalHeaderLabels(display_columns)

            # 列幅を変更可能にする設定（データ設定前に設定）
            header = self.purchase_table.horizontalHeader()
            for col_idx in range(len(columns)):
                header.setSectionResizeMode(col_idx, QHeaderView.Interactive)

        for offset, record in enumerate(slice_records):
            row = base_row + offset
            # レコードに行IDを付与（なければ採番し、型は int に揃える）
            if "_row_id" not in record or record.get("_row_id") is None:
                record["_row_id"] = self._purchase_row_id_counter
                self._purchase_row_id_counter += 1
            try:
                row_id = int(record.get("_row_id"))
            except (TypeError, ValueError):
                record["_row_id"] = self._purchase_row_id_counter
                self._purchase_row_id_counter += 1
                row_id = int(record["_row_id"])
            record["_row_id"] = row_id
            self._purchase_row_map[row_id] = record
            self._purchase_table_row_ids_by_index.append(row_id)

            for col, header in enumerate(columns):
                value = self._get_record_value(record, [header])
                if value is None:
                    value = ""
                
                # JANコードの.0を削除（表示用の正規化）
                if header == "JAN" or header == "jan":
                    if value:
                        jan_str = str(value).strip()
                        # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
                        if jan_str.endswith(".0"):
                            jan_str = jan_str[:-2]
                        value = jan_str
                
                if header == "商品名":
                    full_text = "" if value is None else str(value)
                    display_text = self._truncate_text(full_text, PRODUCT_NAME_DISPLAY_LIMIT)
                    item = QTableWidgetItem(display_text)
                    if full_text:
                        item.setToolTip(full_text)
                    item.setData(Qt.UserRole, full_text)
                elif header == "レシート画像":
                    receipt_image_str = "" if value is None else str(value).strip()
                    display_text = ""
                    resolved_path = None
                    item = QTableWidgetItem("")
                    item.setFlags(item.flags() | Qt.ItemIsEnabled)
                    saved_path = str(record.get("レシート画像パス") or "").strip()
                    if saved_path and Path(saved_path).is_file():
                        resolved_path = str(Path(saved_path).resolve())
                        display_text = resolved_path
                    elif receipt_image_str:
                        file_path = self._resolve_receipt_file_path(record, receipt_image_str)
                        if file_path:
                            file_path_obj = Path(file_path)
                            if file_path_obj.exists():
                                resolved_path = str(file_path_obj.resolve())
                                display_text = resolved_path
                                record["レシート画像パス"] = resolved_path
                            else:
                                resolved_path = str(file_path)
                                display_text = resolved_path
                                record["レシート画像パス"] = file_path
                    item.setText(display_text)
                    if display_text.strip():
                        item.setToolTip(display_text)
                    if resolved_path:
                        item.setData(Qt.UserRole, resolved_path)
                    elif receipt_image_str:
                        item.setData(Qt.UserRole, receipt_image_str)
                    if display_text.strip() or receipt_image_str:
                        item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
                elif header == "レシート画像URL":
                    receipt_image_url_str = str(
                        record.get("レシート画像URL")
                        or record.get("receipt_image_url")
                        or ("" if value is None else str(value))
                    ).strip()
                    if receipt_image_url_str and self._is_placeholder_url(receipt_image_url_str):
                        receipt_image_url_str = ""
                    if receipt_image_url_str:
                        record["レシート画像URL"] = receipt_image_url_str
                    item = QTableWidgetItem(receipt_image_url_str)
                    if receipt_image_url_str:
                        item.setFlags(item.flags() | Qt.ItemIsEnabled)
                        item.setToolTip(receipt_image_url_str)
                        item.setData(Qt.UserRole, receipt_image_url_str)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                elif header == "保証書画像":
                    warranty_image_str = "" if value is None else str(value)
                    display_text = warranty_image_str
                    warranty_file_path = None
                    if warranty_image_str:
                        item = QTableWidgetItem("")
                        item.setFlags(item.flags() | Qt.ItemIsEnabled)
                        sku_for_warranty = str(record.get('SKU') or record.get('sku') or '')
                        # キャッシュ優先（ファイル名キー→レシートDB、SKUキー→保証書DB）
                        warranty_file_path = self._receipt_file_path_cache.get(warranty_image_str)
                        if warranty_file_path is None and warranty_image_str not in self._receipt_file_path_cache:
                            try:
                                receipt_info = self.receipt_db.find_by_file_name(warranty_image_str)
                                if receipt_info:
                                    warranty_file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path', '')
                            except Exception:
                                pass
                            self._receipt_file_path_cache[warranty_image_str] = warranty_file_path
                        if not warranty_file_path:
                            warranty_file_path = self._warranty_sku_path_cache.get(sku_for_warranty)
                            if warranty_file_path is None and sku_for_warranty not in self._warranty_sku_path_cache:
                                try:
                                    warranties = self.warranty_db.list_by_sku(sku_for_warranty)
                                    if warranties:
                                        warranty_file_path = warranties[0].get('file_path', '')
                                except Exception:
                                    pass
                                self._warranty_sku_path_cache[sku_for_warranty] = warranty_file_path
                        if warranty_file_path:
                            file_path_obj = Path(warranty_file_path)
                            if file_path_obj.exists():
                                display_text = str(file_path_obj.resolve())
                                item.setData(Qt.UserRole, display_text)
                            else:
                                display_text = str(warranty_file_path)
                                item.setData(Qt.UserRole, warranty_file_path)
                        else:
                            item.setData(Qt.UserRole, warranty_image_str)
                        item.setText(display_text)
                        if display_text.strip():
                            item.setToolTip(display_text)
                        item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
                    else:
                        item = QTableWidgetItem("")
                elif header and header.startswith("画像") and header[2:].isdigit():
                    image_path = value or ""
                    if image_path:
                        resolved = resolve_local_image_path(str(image_path), record)
                        if resolved:
                            image_path = resolved
                            record[header] = resolved
                        display_path = str(image_path)
                        item = QTableWidgetItem(display_path)
                        item.setData(Qt.UserRole, display_path)
                        exists = Path(display_path).is_file()
                        tip = display_path
                        if not exists:
                            tip += "\n（ファイル未検出・画像管理フォルダ内を再探索します）"
                        item.setToolTip(tip)
                        item.setForeground(Qt.white)  # 青色から白色に変更
                        font = item.font()
                        font.setUnderline(True)
                        item.setFont(font)
                    else:
                        item = QTableWidgetItem("")
                elif header and header.startswith("画像URL") and header[6:].isdigit():
                    # 画像URL列の処理
                    image_url = value or ""
                    if image_url:
                        url_text = str(image_url)
                        item = QTableWidgetItem(url_text)
                        item.setToolTip(url_text)
                        item.setData(Qt.UserRole, url_text)
                        # 編集モードに入らないようにする（ダブルクリックで文字列編集させない）
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    else:
                        item = QTableWidgetItem("")
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                elif header in ("月別", "改定価格", "価格改定"):
                    item = self._make_purchase_repricing_column_item(record, header)
                elif header == "想定利益率" or header == "想定ROI":
                    # 想定利益率・想定ROI列の処理：空欄の場合は再計算
                    value_str = str(value) if value else ""
                    value_float = None
                    try:
                        if value_str:
                            value_float = float(value_str)
                    except (ValueError, TypeError):
                        value_float = None
                    
                    # 空欄または0の場合は再計算
                    if value_float is None or value_float == 0:
                        # 再計算に必要な値を取得
                        purchase_price = None
                        planned_price = None
                        expected_profit = None
                        
                        # 仕入れ価格を取得
                        purchase_price_key = None
                        for key in ["仕入れ価格", "仕入価格", "purchase_price", "cost"]:
                            if key in record:
                                purchase_price_key = key
                                break
                        if purchase_price_key:
                            try:
                                purchase_price = float(record[purchase_price_key]) if record[purchase_price_key] else 0
                            except (ValueError, TypeError):
                                purchase_price = 0
                        
                        # 販売予定価格を取得
                        planned_price_key = None
                        for key in ["販売予定価格", "planned_price", "price"]:
                            if key in record:
                                planned_price_key = key
                                break
                        if planned_price_key:
                            try:
                                planned_price = float(record[planned_price_key]) if record[planned_price_key] else 0
                            except (ValueError, TypeError):
                                planned_price = 0
                        
                        # 見込み利益を取得
                        expected_profit_key = None
                        for key in ["見込み利益", "expected_profit", "profit"]:
                            if key in record:
                                expected_profit_key = key
                                break
                        if expected_profit_key:
                            try:
                                expected_profit = float(record[expected_profit_key]) if record[expected_profit_key] else 0
                            except (ValueError, TypeError):
                                expected_profit = 0
                        
                        # 見込み利益が計算されていない場合は計算
                        if expected_profit is None or expected_profit == 0:
                            if planned_price and purchase_price:
                                other_cost = record.get('その他費用') or record.get('other_cost') or 0
                                try:
                                    other_cost = float(other_cost) if other_cost else 0
                                except (ValueError, TypeError):
                                    other_cost = 0
                                expected_profit = planned_price - purchase_price - other_cost
                        
                        # 想定利益率または想定ROIを計算
                        if header == "想定利益率":
                            if planned_price and planned_price > 0 and expected_profit:
                                calculated_value = (expected_profit / planned_price) * 100
                                value_float = round(calculated_value, 2)
                                # レコードにも保存
                                record['想定利益率'] = value_float
                            else:
                                value_float = 0.0
                        elif header == "想定ROI":
                            if purchase_price and purchase_price > 0 and expected_profit:
                                calculated_value = (expected_profit / purchase_price) * 100
                                value_float = round(calculated_value, 2)
                                # レコードにも保存
                                record['想定ROI'] = value_float
                            else:
                                value_float = 0.0
                    
                    # 値を表示
                    if value_float is not None and value_float != 0:
                        item = QTableWidgetItem(f"{value_float:.2f}")
                    else:
                        item = QTableWidgetItem("")
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif header in (
                    "仕入れ価格", "見込み利益", COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST,
                    "在庫保管手数料",
                ):
                    try:
                        fv = float(str(value).replace(",", "").strip()) if value not in (None, "") else None
                    except (ValueError, TypeError):
                        fv = None
                    if fv is None:
                        item = QTableWidgetItem("")
                        if is_fee_amount_column(header):
                            record[header] = ""
                    else:
                        rounded_yen = int(round(fv))
                        if is_fee_amount_column(header):
                            stored = fee_storage_value(rounded_yen)
                            record[header] = stored
                            item = QTableWidgetItem(
                                str(rounded_yen) if rounded_yen else ""
                            )
                        else:
                            record[header] = rounded_yen
                            item = QTableWidgetItem(str(rounded_yen))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif header == "損益分岐点":
                    purchase_v = None
                    for key in ("仕入れ価格", "仕入価格", "purchase_price", "cost"):
                        if key in record and record[key] not in (None, ""):
                            try:
                                purchase_v = float(
                                    str(record[key]).replace(",", "").strip()
                                )
                            except (ValueError, TypeError):
                                purchase_v = None
                            break
                    planned_v = None
                    for key in ("販売予定価格", "planned_price", "price"):
                        if key in record and record[key] not in (None, ""):
                            try:
                                planned_v = float(
                                    str(record[key]).replace(",", "").strip()
                                )
                            except (ValueError, TypeError):
                                planned_v = None
                            break
                    profit_v = 0.0
                    for key in ("見込み利益", "expected_profit", "profit"):
                        if key in record and record[key] not in (None, ""):
                            try:
                                profit_v = float(
                                    str(record[key]).replace(",", "").strip()
                                )
                            except (ValueError, TypeError):
                                profit_v = 0.0
                            break
                    try:
                        other_v = float(
                            str(
                                record.get("その他費用")
                                or record.get("other_cost")
                                or 0
                            ).replace(",", "").strip()
                        )
                    except (ValueError, TypeError):
                        other_v = 0.0
                    stored_be = value
                    recomputed = compute_break_even_for_record(record)
                    if (
                        recomputed is not None
                        and purchase_v is not None
                        and planned_v is not None
                        and should_recompute_break_even(
                            stored_be,
                            purchase_v,
                            planned_v,
                            profit_v,
                            other_v,
                        )
                    ):
                        display_val = int(round(recomputed))
                        record["損益分岐点"] = display_val
                        item = QTableWidgetItem(str(display_val))
                    else:
                        try:
                            if stored_be not in (None, ""):
                                fv = float(str(stored_be).replace(",", "").strip())
                                display_val = int(round(fv))
                                record["損益分岐点"] = display_val
                                item = QTableWidgetItem(str(display_val))
                            else:
                                item = QTableWidgetItem("")
                        except (ValueError, TypeError):
                            item = QTableWidgetItem(str(stored_be) if stored_be else "")
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif header == "仕入れ日" or header.upper() == "PURCHASE_DATE":
                    # 仕入れ日列の処理：ソート用の値を設定
                    date_str = str(value) if value else ""
                    # ソート用の値を設定（datetimeオブジェクトまたはタイムスタンプ）
                    sort_value = 0.0
                    if date_str:
                        try:
                            # 日付文字列をパース（複数の形式に対応）
                            date_str_clean = date_str.strip()
                            # "2025/12/6 10:16" 形式を想定
                            if " " in date_str_clean:
                                date_part, time_part = date_str_clean.split(" ", 1)
                                date_part = date_part.replace("/", "-")
                                datetime_str = f"{date_part} {time_part}"
                                # "YYYY-MM-DD HH:MM" 形式でパース
                                dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                sort_value = dt.timestamp()
                            else:
                                # 日付のみの場合
                                date_part = date_str_clean.replace("/", "-")
                                dt = datetime.strptime(date_part, "%Y-%m-%d")
                                sort_value = dt.timestamp()
                        except Exception:
                            try:
                                # 別の形式を試す
                                date_part = date_str_clean.replace("/", "-").split(" ")[0]
                                dt = datetime.strptime(date_part, "%Y-%m-%d")
                                sort_value = dt.timestamp()
                            except Exception:
                                # パースに失敗した場合は、0を設定（最古として扱う）
                                sort_value = 0.0
                    # SortableDateItemを使用してソート可能にする
                    item = SortableDateItem(date_str, sort_value)
                elif header == "経過日数":
                    elapsed_days = _calc_elapsed_days_for_purchase_record(record)
                    if elapsed_days is not None:
                        item = SortableDateItem(str(elapsed_days), float(elapsed_days))
                    else:
                        item = SortableDateItem("", 0.0)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setToolTip("出品日（未設定時は仕入れ日）から今日までの経過日数")
                elif header == "ステータス":
                    # ステータス列の処理：プルダウンで選択可能
                    status_value = str(value) if value else "ready"
                    status_combo = QComboBox()
                    status_combo.addItem("出品可能", "ready")
                    status_combo.addItem("破損", "damaged")
                    status_combo.addItem("登録不可", "unlistable")
                    status_combo.addItem("保管中", "storage")
                    status_combo.addItem("次回出品予定", "pending")
                    status_combo.addItem("販売中", "selling")
                    status_combo.addItem("一部販売済み", "partially_sold")
                    status_combo.addItem("販売済み", "sold")
                    status_combo.addItem("在庫専用", "inventory_only")
                    
                    # 現在の値を設定
                    current_index = 0
                    for i in range(status_combo.count()):
                        if status_combo.itemData(i) == status_value:
                            current_index = i
                            break
                    status_combo.setCurrentIndex(current_index)
                    
                    # ステータス変更時の処理
                    def on_status_changed(idx, r=row, rec=record):
                        new_status = status_combo.itemData(idx)
                        rec["ステータス"] = new_status
                        rec["status"] = new_status
                        rec["_status_norm"] = str(new_status or "").strip().lower()
                        # ステータス設定日時を更新
                        rec["status_set_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if new_status == "selling":
                            cur_r = str(
                                rec.get("ステータス理由") or rec.get("status_reason") or ""
                            ).strip()
                            if not cur_r:
                                rec["ステータス理由"] = _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV
                                rec["status_reason"] = _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV
                        
                        # purchase_all_records / master / purchase_records を更新
                        sku = rec.get("SKU") or rec.get("sku")
                        if sku:
                            for target_list in ["purchase_all_records", "purchase_all_records_master", "purchase_records"]:
                                lst = getattr(self, target_list, None)
                                if lst:
                                    for t_rec in lst:
                                        t_sku = t_rec.get("SKU") or t_rec.get("sku")
                                        if t_sku == sku:
                                            t_rec["ステータス"] = new_status
                                            t_rec["status"] = new_status
                                            t_rec["status_set_at"] = rec["status_set_at"]
                                            t_rec["ステータス理由"] = rec.get("ステータス理由") or rec.get("status_reason") or ""
                                            t_rec["status_reason"] = rec.get("status_reason") or rec.get("ステータス理由") or ""
                                            break
                        
                        # データベースに保存（ステータス理由も含める）
                        if sku:
                            try:
                                # ステータス理由も取得して保存
                                status_reason = rec.get("ステータス理由") or rec.get("status_reason") or ""
                                tp0 = rec.get("TP0") or rec.get("tp0") or ""
                                tp1 = rec.get("TP1") or rec.get("tp1") or rec.get("TA1") or rec.get("ta1") or ""
                                tp2 = rec.get("TP2") or rec.get("tp2") or rec.get("TA2") or rec.get("ta2") or ""
                                tp3 = rec.get("TP3") or rec.get("tp3") or ""
                                purchase_data = {
                                    "sku": sku,
                                    "status": new_status,
                                    "status_reason": status_reason,
                                    "tp0": tp0,
                                    "tp1": tp1,
                                    "tp2": tp2,
                                    "tp3": tp3,
                                    "status_set_at": rec["status_set_at"]
                                }
                                self.purchase_history_db.upsert(purchase_data)
                                print(f"ステータス保存成功: SKU={sku}, status={new_status}, status_reason={status_reason}")
                            except Exception as e:
                                import traceback
                                error_msg = f"ステータス保存エラー (SKU={sku}): {e}\n{traceback.format_exc()}"
                                print(error_msg)
                                QMessageBox.warning(
                                    self,
                                    "保存エラー",
                                    f"ステータスの保存に失敗しました。\nSKU: {sku}\nエラー: {str(e)}"
                                )
                        
                        # 行の背景色を更新
                        self._update_row_color_by_status(r, new_status)

                        # ステータスフィルタをリセットして再描画（変更後に行が消えないよう常に全件表示に戻す）
                        self._reset_purchase_status_filter_checkboxes()

                        # フィルタを再適用（全件表示）してテーブルを再描画
                        self.filter_purchase_records()
                        # 表示モードに応じた列の表示/非表示を確実に更新
                        self._update_column_visibility()

                        # スナップショットも保存（次回起動時にステータスがリセットされないようにする）
                        try:
                            self.save_purchase_snapshot()
                        except Exception as e:
                            print(f"スナップショット保存エラー(ステータス変更): {e}")
                    
                    status_combo.currentIndexChanged.connect(on_status_changed)
                    self.purchase_table.setCellWidget(row, col, status_combo)
                    continue  # セルウィジェットを設定したので、itemは設定しない
                elif header == "ステータス理由":
                    # ステータス理由列の処理：編集可能なテキスト
                    reason_value = str(value) if value else ""
                    st_row = str(
                        record.get("ステータス") or record.get("status") or ""
                    ).strip().lower()
                    if st_row == "selling" and not reason_value.strip():
                        reason_value = _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV
                        record["ステータス理由"] = reason_value
                        record["status_reason"] = reason_value
                    item = QTableWidgetItem(reason_value)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    # 編集時の処理は、itemChangedシグナルで処理（後で接続）
                else:
                    if header in _PURCHASE_RIGHT_ALIGN_NUMERIC_HEADERS:
                        item = _make_purchase_numeric_table_item(header, value)
                    else:
                        item = QTableWidgetItem(str(value))
                    # SKUはUserRoleにフル値を保持（表示幅で...になっても保存時はフルで使う）
                    if header == "SKU" and value is not None and str(value).strip():
                        item.setData(Qt.UserRole, str(value).strip())
                
                if header != "ステータス":  # ステータス列はセルウィジェットを設定済み
                    self.purchase_table.setItem(row, col, item)

            # 行IDを各セルの UserRole+1 に保存（ソート後も編集対象を一意に特定する）
            # ステータス列はセルウィジェットのため item が無い → 他列すべてに付与しておく
            try:
                for c in range(self.purchase_table.columnCount()):
                    it = self.purchase_table.item(row, c)
                    if it is not None:
                        it.setData(Qt.UserRole + 1, row_id)
            except Exception:
                pass

            # 出品日が入っていて、ステータスが未設定（ready 相当）の場合は自動で「販売中」にする
            try:
                listed_date_raw = record.get("出品日") or record.get("listed_date") or ""
                status_raw = record.get("ステータス") or record.get("status") or ""
                listed_date_str = str(listed_date_raw).strip()
                status_str = str(status_raw).strip().lower()
                if listed_date_str and (not status_str or status_str == "ready"):
                    # レコード側の値も更新
                    record["ステータス"] = "selling"
                    record["status"] = "selling"
                    lr = str(
                        record.get("ステータス理由") or record.get("status_reason") or ""
                    ).strip()
                    if not lr:
                        record["ステータス理由"] = _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV
                        record["status_reason"] = _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV
                    # テーブル上のコンボボックスも更新（シグナルは発火させない）
                    if "ステータス" in columns:
                        status_col_idx = columns.index("ステータス")
                        widget = self.purchase_table.cellWidget(row, status_col_idx)
                        from PySide6.QtWidgets import QComboBox as _QComboForStatus
                        if isinstance(widget, _QComboForStatus):
                            old_block = widget.blockSignals(True)
                            try:
                                for i in range(widget.count()):
                                    if widget.itemData(i) == "selling":
                                        widget.setCurrentIndex(i)
                                        break
                            finally:
                                widget.blockSignals(old_block)
                    # 行の色も更新
                    self._update_row_color_by_status(row, "selling")
            except Exception:
                # 自動設定に失敗してもアプリ全体には影響させない
                pass
        
        # 追加・初回描画した行の背景色を設定（ステータスに応じて）
        for offset, record in enumerate(slice_records):
            row = base_row + offset
            status_value = str(record.get("ステータス") or record.get("status") or "ready")
            self._update_row_color_by_status(row, status_value)

        if not finalize:
            if not append:
                if not hasattr(self, "purchase_view_mode"):
                    self.purchase_view_mode = "all"
                self._update_column_visibility()
                restore_table_column_widths(
                    self.purchase_table, "ProductWidget/PurchaseTableColumnWidths"
                )
            self.purchase_table.blockSignals(False)
            self.purchase_table.setSortingEnabled(True)
            self.purchase_table.viewport().update()
            return

        # 各列をリサイズ可能に設定
        header = self.purchase_table.horizontalHeader()
        for col_idx in range(len(columns)):
            header.setSectionResizeMode(col_idx, QHeaderView.Interactive)
        
        # 列幅のみを復元（リサイズモードは変更しない）
        restore_table_column_widths(self.purchase_table, "ProductWidget/PurchaseTableColumnWidths")
        self._apply_purchase_fulltext_columns(columns)
        
        # ステータス理由列の編集時の処理を接続（既存の接続を解除してから接続）
        status_reason_col_idx = None
        sku_col_idx = None
        status_col_idx = None
        for col_idx, col_name in enumerate(columns):
            if col_name == "ステータス理由":
                status_reason_col_idx = col_idx
            if col_name == "SKU":
                sku_col_idx = col_idx
            if col_name == "ステータス":
                status_col_idx = col_idx
        # SKU列が無い場合は安全に終了
        if sku_col_idx is None:
            sku_col_idx = None
        
        # 表示問題対策: SKU列をフル表示するため最小幅を確保（DBには全文入っているが表示で...になるのを防ぐ）
        if sku_col_idx is not None:
            MIN_SKU_COLUMN_WIDTH = 300
            if header.sectionSize(sku_col_idx) < MIN_SKU_COLUMN_WIDTH:
                header.resizeSection(sku_col_idx, MIN_SKU_COLUMN_WIDTH)
        
        if status_reason_col_idx is not None:
            # 既存のitemChangedシグナル接続を解除（重複接続を防ぐ）
            # 注意: disconnect()を引数なしで呼ぶと、接続がない場合にRuntimeWarningが出るが、
            # 動作には影響しないため、例外をキャッチして無視する
            try:
                self.purchase_table.itemChanged.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                # 接続がない場合や切断に失敗した場合はエラーを無視
                pass
            
            # itemChangedシグナルを接続（編集時に自動保存）
            def on_item_changed(item_changed):
                if item_changed.column() == status_reason_col_idx:
                    row = item_changed.row()
                    if row < 0:
                        return

                    new_reason = item_changed.text()

                    # ソート有効時は records[row] が別レコードになるため、テーブル上のSKUで特定する
                    sku_val = None
                    if sku_col_idx is not None:
                        sku_item = self.purchase_table.item(row, sku_col_idx)
                        if sku_item:
                            sku_val = (sku_item.text() or "").strip()
                    if not sku_val:
                        # フォールバック：recordsから取る（ソートしていない前提）
                        if 0 <= row < len(records):
                            sku_val = (records[row].get("SKU") or records[row].get("sku") or "").strip()
                    if not sku_val:
                        return

                    # まず表示用records（この描画に渡ってきたリスト）にも反映（見た目が戻らないように）
                    if 0 <= row < len(records):
                        records[row]["ステータス理由"] = new_reason
                        records[row]["status_reason"] = new_reason

                    # purchase_all_records / master / purchase_records へ反映（再描画・再起動で消えないようにする）
                    for target_list in ["purchase_all_records", "purchase_all_records_master", "purchase_records"]:
                        lst = getattr(self, target_list, None)
                        if not lst:
                            continue
                        for t_rec in lst:
                            t_sku = (t_rec.get("SKU") or t_rec.get("sku") or "")
                            if str(t_sku).strip() == sku_val:
                                t_rec["ステータス理由"] = new_reason
                                t_rec["status_reason"] = new_reason
                                break

                    # 現在のステータスもテーブルから取得（可能なら）
                    current_status = None
                    if status_col_idx is not None:
                        w = self.purchase_table.cellWidget(row, status_col_idx)
                        if isinstance(w, QComboBox):
                            current_status = w.currentData()
                    if not current_status:
                        # フォールバック：マスターから取得
                        current_status = "ready"
                        for lst_name in ["purchase_all_records_master", "purchase_all_records"]:
                            lst = getattr(self, lst_name, None)
                            if not lst:
                                continue
                            for t_rec in lst:
                                t_sku = (t_rec.get("SKU") or t_rec.get("sku") or "")
                                if str(t_sku).strip() == sku_val:
                                    current_status = t_rec.get("ステータス") or t_rec.get("status") or "ready"
                                    break

                    # データベースに保存（ステータス・TP0/TP1/TP2も一緒に保存）
                    tp0 = ""
                    tp1 = ""
                    tp2 = ""
                    tp3 = ""
                    if 0 <= row < len(records):
                        tp0 = records[row].get("TP0") or records[row].get("tp0") or ""
                        tp1 = records[row].get("TP1") or records[row].get("tp1") or records[row].get("TA1") or records[row].get("ta1") or ""
                        tp2 = records[row].get("TP2") or records[row].get("tp2") or records[row].get("TA2") or records[row].get("ta2") or ""
                        tp3 = records[row].get("TP3") or records[row].get("tp3") or ""
                    # テーブル上のTP0/TP1/TP2の現在値を取得
                    if "TP0" in columns:
                        idx = columns.index("TP0")
                        item_tp0 = self.purchase_table.item(row, idx)
                        if item_tp0 and item_tp0.text():
                            tp0 = item_tp0.text()
                    if "TP1" in columns:
                        idx = columns.index("TP1")
                        item_tp1 = self.purchase_table.item(row, idx)
                        if item_tp1 and item_tp1.text():
                            tp1 = item_tp1.text()
                    if "TP2" in columns:
                        idx = columns.index("TP2")
                        item_tp2 = self.purchase_table.item(row, idx)
                        if item_tp2 and item_tp2.text():
                            tp2 = item_tp2.text()
                    if "TP3" in columns:
                        idx = columns.index("TP3")
                        item_tp3 = self.purchase_table.item(row, idx)
                        if item_tp3 and item_tp3.text():
                            tp3 = item_tp3.text()
                    try:
                        purchase_data = {
                            "sku": sku_val,
                            "status": current_status,
                            "status_reason": new_reason,
                            "tp0": tp0,
                            "tp1": tp1,
                            "tp2": tp2,
                            "tp3": tp3,
                        }
                        self.purchase_history_db.upsert(purchase_data)
                        print(f"ステータス理由保存成功: SKU={sku_val}, status={current_status}, status_reason={new_reason}")
                    except Exception as e:
                        import traceback
                        error_msg = f"ステータス理由保存エラー (SKU={sku_val}): {e}\n{traceback.format_exc()}"
                        print(error_msg)
                        QMessageBox.warning(
                            self,
                            "保存エラー",
                            f"ステータス理由の保存に失敗しました。\nSKU: {sku_val}\nエラー: {str(e)}"
                        )

                    # スナップショットも保存（次回起動時に理由が消えないようにする）
                    try:
                        self.save_purchase_snapshot()
                    except Exception as e:
                        print(f"スナップショット保存エラー(ステータス理由変更): {e}")
            
            self.purchase_table.itemChanged.connect(on_item_changed)
        
        # デフォルトで仕入れ日列を降順でソート
        # 仕入れ日列のインデックスを取得
        purchase_date_col_idx = None
        for col_idx, col_name in enumerate(columns):
            if col_name == "仕入れ日" or col_name.upper() == "PURCHASE_DATE":
                purchase_date_col_idx = col_idx
                break
        
        # 仕入れ日列が見つかった場合は降順でソート
        if purchase_date_col_idx is not None:
            # 仕入れ日列で降順ソート
            self.purchase_table.sortItems(purchase_date_col_idx, Qt.DescendingOrder)

        self._sync_purchase_table_row_order_index()
        
        # 表示モードに応じた列の表示/非表示を設定（必ず実行）
        if not hasattr(self, 'purchase_view_mode'):
            # デフォルトで全表示
            self.purchase_view_mode = "all"
        self._update_column_visibility()

        self._sync_purchase_row_ids_to_master(records)

        # 再描画のためソートを有効化し、シグナルを戻す
        self.purchase_table.setSortingEnabled(True)
        self.purchase_table.blockSignals(False)
        self.purchase_table.viewport().update()

    def _get_record_value(self, record: Dict[str, Any], keys: List[str]) -> Any:
        """大文字小文字を無視して値を取得"""
        for key in keys:
            for r_key, value in record.items():
                if r_key.upper() == key.upper():
                    return value
        return None

    def _truncate_text(self, text: str, limit: int) -> str:
        """テキストを指定文字数で丸める"""
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def _extract_yyyymmdd_from_text(self, text: str) -> Optional[str]:
        """文字列先頭付近の YYYYMMDD を抽出"""
        text = str(text or "").strip()
        m = re.match(r"^(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"
        m = re.match(r"^(\d{8})", text)
        if m:
            return m.group(1)
        return None

    def _receipt_key_matches_purchase_record(
        self, row: Dict[str, Any], receipt_key: str
    ) -> bool:
        """確定済みレシート識別子が仕入SKU/仕入日と整合するか（誤自動紐付け除外用）"""
        receipt_key = self._receipt_image_lookup_key(receipt_key)
        if not receipt_key:
            return False
        receipt_date = self._extract_yyyymmdd_from_text(receipt_key)
        if not receipt_date:
            return True

        sku = str(row.get("SKU") or row.get("sku") or "").strip()
        sku_date = self._extract_yyyymmdd_from_text(sku)
        if sku_date and abs(int(sku_date) - int(receipt_date)) <= 1:
            return True

        purchase_date = str(row.get("仕入れ日") or row.get("purchase_date") or "").strip()
        purchase_yyyymmdd = self._extract_yyyymmdd_from_text(purchase_date)
        if purchase_yyyymmdd and abs(int(purchase_yyyymmdd) - int(receipt_date)) <= 1:
            return True
        return False

    def _get_voucher_linked_receipt_info(self, sku: str) -> Optional[Dict[str, Any]]:
        """証憑管理で linked_skus に含まれる SKU のレシート情報を返す。"""
        sku = str(sku or "").strip()
        if not sku:
            return None
        try:
            info = self.receipt_db.find_by_linked_sku(sku)
        except Exception:
            return None
        if not info:
            return None
        linked = {
            s.strip()
            for s in str(info.get("linked_skus") or "").split(",")
            if s.strip()
        }
        if sku not in linked:
            return None
        return info

    def _sync_receipt_fields_from_voucher_link(self, row: Dict[str, Any]) -> None:
        """仕入レコードのレシート関連列を同期（証憑紐付け優先、確定済みデータは保持）。"""
        sku = str(row.get("SKU") or row.get("sku") or "").strip()
        clear_keys = ("レシート画像", "レシート画像パス", "レシート画像URL")

        voucher_info = self._get_voucher_linked_receipt_info(sku) if sku else None
        if voucher_info:
            fp = str(
                voucher_info.get("original_file_path") or voucher_info.get("file_path") or ""
            ).strip()
            stem = Path(fp).stem if fp else ""
            row["レシート画像"] = stem
            if fp and Path(fp).is_file():
                row["レシート画像パス"] = str(Path(fp).resolve())
            else:
                row["レシート画像パス"] = ""
            row["レシート画像URL"] = str(
                voucher_info.get("gcs_url") or voucher_info.get("image_url") or ""
            ).strip()
            return

        receipt_key = str(
            row.get("レシート画像") or row.get("receipt_id") or ""
        ).strip()
        saved_path = str(row.get("レシート画像パス") or row.get("receipt_image_path") or "").strip()
        saved_url = str(
            row.get("レシート画像URL") or row.get("receipt_image_url") or ""
        ).strip()

        if receipt_key and self._receipt_key_matches_purchase_record(row, receipt_key):
            if saved_path and Path(saved_path).is_file():
                row["レシート画像パス"] = str(Path(saved_path).resolve())
            else:
                resolved = self._resolve_receipt_file_path(row, receipt_key)
                row["レシート画像パス"] = resolved or saved_path
            if saved_url and not self._is_placeholder_url(saved_url):
                row["レシート画像URL"] = saved_url
            else:
                row["レシート画像URL"] = self._resolve_receipt_image_url(row, saved_url)
            return

        for key in clear_keys:
            row[key] = ""

    @staticmethod
    def _is_placeholder_url(url: Any) -> bool:
        """省略表示や未入力の URL プレースホルダーか判定"""
        text = str(url or "").strip()
        if not text:
            return True
        lowered = text.lower()
        if lowered in ("https://...", "http://...", "https://…", "http://…"):
            return True
        if text.endswith("...") or text.endswith("…"):
            return True
        if text.startswith("http") and len(text) <= 15 and "..." in text:
            return True
        return False

    @staticmethod
    def _receipt_image_lookup_key(text: str) -> str:
        """レシートDB検索用キー（フルパスならファイル名 stem）"""
        t = str(text or "").strip()
        if not t:
            return ""
        if "\\" in t or "/" in t:
            return Path(t).stem
        return t

    def _find_receipt_info_for_key(self, receipt_key: str) -> Optional[Dict[str, Any]]:
        lookup = self._receipt_image_lookup_key(receipt_key)
        if not lookup:
            return None
        if lookup in self._receipt_info_by_key_cache:
            return self._receipt_info_by_key_cache[lookup]
        info = None
        try:
            info = self.receipt_db.find_by_file_name(lookup)
        except Exception:
            info = None
        self._receipt_info_by_key_cache[lookup] = info
        return info

    _RECEIPT_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")

    def _receipt_local_search_roots(self) -> List[Path]:
        """証憑管理のデフォルトフォルダ等、ローカルレシート探索の起点"""
        roots: List[Path] = []
        seen: set[str] = set()

        def add(path: Path) -> None:
            if not path:
                return
            key = str(path)
            if key in seen:
                return
            seen.add(key)
            if path.exists():
                roots.append(path)

        try:
            s = QSettings("HIRIO", "SedoriDesktopApp")
            default = str(s.value("receipt/default_folder", "") or "").strip()
            if default:
                dp = Path(default)
                add(dp)
                if dp.parent.exists():
                    add(dp.parent)
                if dp.parent.parent.exists():
                    add(dp.parent.parent)
        except Exception:
            pass
        return roots

    def _receipt_stems_for_local_search(self, record: Dict[str, Any], receipt_key: str) -> List[str]:
        """ローカル探索用のファイル名（拡張子なし）候補"""
        stems: List[str] = []
        seen: set[str] = set()

        def add(name: str) -> None:
            stem = Path(str(name or "").strip()).stem
            if stem and stem not in seen:
                seen.add(stem)
                stems.append(stem)

        add(self._receipt_image_lookup_key(receipt_key))
        for url_key in ("レシート画像URL", "receipt_image_url"):
            url = str(record.get(url_key) or "").strip()
            if not url:
                continue
            if "receipts/" in url:
                add(url.split("receipts/", 1)[-1].split("?")[0])
            elif url.lower().startswith("http"):
                add(Path(url).name)
        return stems

    @classmethod
    def _try_receipt_file_in_dir(cls, directory: Path, stem: str) -> Optional[str]:
        if not directory.is_dir() or not stem:
            return None
        for ext in cls._RECEIPT_IMAGE_EXTS:
            for candidate in (directory / f"{stem}{ext}", directory / f"{stem}{ext.upper()}"):
                if candidate.is_file():
                    return str(candidate.resolve())
        return None

    def _search_local_receipt_file(self, record: Dict[str, Any], receipt_key: str) -> Optional[str]:
        """デフォルトフォルダ等からレシートファイルを完全一致（stem）で探す。"""
        receipt_key = str(receipt_key or "").strip()
        if not receipt_key:
            return None
        stems = self._receipt_stems_for_local_search(record, receipt_key)
        if not stems:
            return None

        for root in self._receipt_local_search_roots():
            for stem in stems:
                for search_dir in (root, root / "レシート画像"):
                    hit = self._try_receipt_file_in_dir(search_dir, stem)
                    if hit:
                        return hit

            if not root.is_dir():
                continue
            try:
                for route_dir in root.iterdir():
                    if not route_dir.is_dir():
                        continue
                    receipt_dir = route_dir / "レシート画像"
                    for stem in stems:
                        hit = self._try_receipt_file_in_dir(receipt_dir, stem)
                        if hit:
                            return hit
            except OSError:
                pass
        return None

    def _resolve_receipt_file_path(self, record: Dict[str, Any], receipt_key: str) -> Optional[str]:
        """レシート画像のローカルファイルパスを解決（証憑紐付け済みの識別子のみ）。"""
        receipt_key = str(receipt_key or "").strip()
        lookup = self._receipt_image_lookup_key(receipt_key)
        candidates = [
            record.get("レシート画像パス"),
            record.get("receipt_image_path"),
        ]
        if lookup:
            candidates.extend([
                self._receipt_file_path_cache.get(receipt_key),
                self._receipt_file_path_cache.get(lookup),
            ])
        for src in candidates:
            if src:
                path_text = str(src).strip()
                if path_text and Path(path_text).is_file():
                    resolved = str(Path(path_text).resolve())
                    cache_key = lookup or receipt_key
                    if cache_key:
                        self._receipt_file_path_cache[cache_key] = resolved
                    return resolved
        if not receipt_key:
            return None
        info = self._find_receipt_info_for_key(receipt_key)
        if info:
            file_path = info.get("original_file_path") or info.get("file_path")
            if file_path:
                path_text = str(file_path).strip()
                if Path(path_text).is_file():
                    resolved = str(Path(path_text).resolve())
                    self._receipt_file_path_cache[lookup or receipt_key] = resolved
                    return resolved
        found = self._search_local_receipt_file(record, receipt_key)
        if found:
            self._receipt_file_path_cache[lookup or receipt_key] = found
            return found
        return None

    def _resolve_receipt_image_url(self, record: Dict[str, Any], current: Any = "") -> str:
        """レシート画像URLを返す（証憑紐付け済みレコードのみ補完）。"""
        url = str(
            current
            or record.get("レシート画像URL")
            or record.get("receipt_image_url")
            or ""
        ).strip()
        if url and not self._is_placeholder_url(url):
            return url

        receipt_key = str(
            record.get("レシート画像")
            or record.get("receipt_id")
            or record.get("receipt_image")
            or ""
        ).strip()
        if receipt_key:
            info = self._find_receipt_info_for_key(receipt_key)
            if info:
                for key in ("gcs_url", "image_url"):
                    candidate = str(info.get(key) or "").strip()
                    if candidate and not self._is_placeholder_url(candidate):
                        return candidate
            inferred = self._infer_gcs_receipt_url(receipt_key)
            if inferred and not self._is_placeholder_url(inferred):
                return inferred

        sku = str(record.get("SKU") or record.get("sku") or "").strip()
        if sku:
            info = self._get_voucher_linked_receipt_info(sku)
            if info:
                for key in ("gcs_url", "image_url"):
                    candidate = str(info.get(key) or "").strip()
                    if candidate and not self._is_placeholder_url(candidate):
                        return candidate
        return ""

    @staticmethod
    def _infer_gcs_receipt_url(receipt_key: str) -> str:
        """レシート識別子から GCS URL を推定（DB 未登録時のフォールバック）。"""
        key = PurchaseTableMixin._receipt_image_lookup_key(receipt_key)
        if not key:
            return ""
        if key.lower().startswith("http"):
            return key
        if re.match(r"^\d{4}-\d{2}-\d{2}-", key) or key.startswith("PXL_"):
            return f"https://storage.googleapis.com/hirio-images-main/receipts/{key}.jpg"
        return ""

    def _purchase_fulltext_column_indices(self, columns: List[str]) -> List[int]:
        return [
            i for i, name in enumerate(columns)
            if name in _PURCHASE_FILE_PATH_COLUMNS or name in _PURCHASE_URL_COLUMNS
        ]

    def _apply_purchase_fulltext_columns(self, columns: List[str]) -> None:
        """パス/URL列の省略表示を無効化し、列幅の最小値を確保する。"""
        indices = self._purchase_fulltext_column_indices(columns)
        if not indices:
            return
        delegate = PurchaseFullTextItemDelegate(self.purchase_table)
        header = self.purchase_table.horizontalHeader()
        self.purchase_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        for col_idx in indices:
            self.purchase_table.setItemDelegateForColumn(col_idx, delegate)
            if header.sectionSize(col_idx) < _PURCHASE_FULLTEXT_MIN_COLUMN_WIDTH:
                header.resizeSection(col_idx, _PURCHASE_FULLTEXT_MIN_COLUMN_WIDTH)

    def _update_row_color_by_status(self, row: int, status: str):
        """ステータスに応じて行の背景色・文字色を設定"""
        from PySide6.QtGui import QColor
        
        status = str(status).lower() if status else "ready"
        
        # ステータスに応じた色を設定
        color_map = {
            "ready": QColor(50, 50, 50),  # 通常（デフォルトの背景色）
            "damaged": QColor(80, 30, 30),  # 破損：赤系
            "unlistable": QColor(80, 50, 20),  # 登録不可：オレンジ系
            "storage": QColor(20, 30, 80),  # 保管中：青系
            "pending": QColor(80, 70, 20),  # 次回出品予定：黄色系
            "selling": QColor(20, 80, 40),  # 販売中：緑系
            "partially_sold": QColor(20, 70, 70),  # 一部販売済み：青緑系
            "sold": QColor(60, 60, 60),  # 販売済み：やや暗め
            "inventory_only": QColor(42, 58, 72),  # 在庫専用：青灰（在庫CSV登録）
        }
        
        bg_color = color_map.get(status, QColor(50, 50, 50))
        fg_color = QColor(255, 220, 80) if status == "inventory_only" else None
        
        # 行全体の背景色を設定
        for col in range(self.purchase_table.columnCount()):
            item = self.purchase_table.item(row, col)
            if item:
                item.setBackground(bg_color)
                if fg_color is not None:
                    item.setForeground(fg_color)
            else:
                # セルウィジェットがある場合（ステータス列など）
                widget = self.purchase_table.cellWidget(row, col)
                if widget:
                    fg_style = ""
                    if fg_color is not None:
                        fg_style = (
                            f"color: rgb({fg_color.red()}, {fg_color.green()}, {fg_color.blue()});"
                        )
                    widget.setStyleSheet(
                        f"background-color: rgb({bg_color.red()}, {bg_color.green()}, {bg_color.blue()});"
                        f"{fg_style}"
                    )

    def _show_purchase_context_menu(self, position):
        """コンテキストメニューを表示"""
        menu = QMenu()
        
        # クリックされた行を取得（ステータス列は QComboBox のため itemAt が None になりやすい → indexAt を優先）
        row_for_edit: Optional[int] = None
        idx = self.purchase_table.indexAt(position)
        if idx.isValid():
            row_for_edit = idx.row()
        else:
            item = self.purchase_table.itemAt(position)
            if item is not None:
                row_for_edit = item.row()
        if row_for_edit is None:
            sel = self.purchase_table.selectionModel().selectedRows()
            if len(sel) == 1:
                row_for_edit = sel[0].row()

        item = self.purchase_table.itemAt(position)
        if item:
            row = item.row()
            col = item.column()
            header = self.purchase_table.horizontalHeaderItem(col)
            header_text = header.text() if header else ""
            
            # レシート画像カラムの場合、レシート画像を紐付けするメニューを追加
            if header_text == "レシート画像":
                link_receipt_action = menu.addAction("レシート画像を紐付け")
                link_receipt_action.triggered.connect(lambda: self._link_receipt_image_to_sku(row))
                menu.addSeparator()
        
        copy_action = menu.addAction("選択範囲をコピー")
        copy_action.triggered.connect(self._copy_selection_to_clipboard)
        menu.addSeparator()

        # 選択行削除（行削除ボタンと同じ処理）
        delete_row_action = menu.addAction("選択行を削除")
        delete_row_action.triggered.connect(self.on_delete_purchase_row)
        menu.addSeparator()
        edit_action = menu.addAction("編集（Keepa・TA価格）")
        if row_for_edit is not None:
            edit_action.triggered.connect(lambda checked, r=row_for_edit: self._open_purchase_row_edit(r))
        else:
            edit_action.triggered.connect(self._open_purchase_row_edit)
        menu.addSeparator()
        amazon_action = menu.addAction("Amazon商品ページを開く")
        amazon_action.triggered.connect(self._open_amazon_link)
        keepa_action = menu.addAction("Keepaを開く")
        keepa_action.triggered.connect(self._open_keepa_link)
        menu.addSeparator()
        copy_sku_action = menu.addAction("SKUをコピー")
        copy_sku_action.triggered.connect(self._copy_sku)
        copy_asin_action = menu.addAction("ASINをコピー")
        copy_asin_action.triggered.connect(self._copy_asin)
        menu.exec_(self.purchase_table.viewport().mapToGlobal(position))

    def _copy_selection_to_clipboard(self):
        selection = self.purchase_table.selectedRanges()
        if not selection:
            return
        text = ""
        for r in range(selection[0].topRow(), selection[0].bottomRow() + 1):
            row_text = []
            for c in range(selection[0].leftColumn(), selection[0].rightColumn() + 1):
                item = self.purchase_table.item(r, c)
                row_text.append(item.text() if item else "")
            text += "\t".join(row_text) + "\n"
        QApplication.clipboard().setText(text)

    def _open_amazon_link(self):
        row = self.purchase_table.currentRow()
        if row < 0:
            return
        asin = self._get_value_from_row(row, ["ASIN", "asin"])
        if asin:
            url = f"https://www.amazon.co.jp/dp/{asin}"
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.warning(self, "エラー", "ASINが見つかりません。")

    def _open_keepa_link(self):
        row = self.purchase_table.currentRow()
        if row < 0:
            return
        asin = self._get_value_from_row(row, ["ASIN", "asin"])
        if asin:
            url = f"https://keepa.com/#!product/5-{asin}"
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.warning(self, "エラー", "ASINが見つかりません。")

    def _copy_sku(self):
        row = self.purchase_table.currentRow()
        if row < 0:
            return
        sku = self._get_value_from_row(row, ["SKU", "sku"])
        if sku:
            QApplication.clipboard().setText(sku)

    def _copy_asin(self):
        row = self.purchase_table.currentRow()
        if row < 0:
            return
        asin = self._get_value_from_row(row, ["ASIN", "asin"])
        if asin:
            QApplication.clipboard().setText(asin)

