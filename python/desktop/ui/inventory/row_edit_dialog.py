#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入1行編集ダイアログ。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QSplitter, QMessageBox, QFrame,
    QCheckBox, QSpinBox, QDateEdit, QFileDialog,
    QDialog, QDialogButtonBox, QSizePolicy, QInputDialog, QProgressDialog,
    QPlainTextEdit, QScrollArea, QFormLayout,
    QToolButton, QApplication, QAbstractItemView,
)
from PySide6.QtCore import Qt, QDate, QTime, QDateTime, Signal, QSettings, QThread, QTimer
from PySide6.QtGui import QFont, QColor, QPalette, QStandardItemModel, QStandardItem, QDesktopServices
from PySide6.QtCore import QUrl
import pandas as pd
from pathlib import Path
import re
import sys
import os
import tempfile
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime
from html import escape

# ui/inventory/ から desktop/ を import パス先頭へ
_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)


from database.store_db import StoreDatabase
from database.inventory_db import InventoryDatabase
from database.inventory_route_snapshot_db import InventoryRouteSnapshotDatabase
from database.product_db import ProductDatabase
from database.product_purchase_db import ProductPurchaseDatabase
from database.route_visit_db import RouteVisitDatabase
from database.warranty_db import WarrantyDatabase
from ui.star_rating_widget import StarRatingWidget
try:
    from utils.route_utils import mark_route_flags_from_folder
    from utils.settings_helper import (
        get_pricetar_listing_url,
        is_pro_enabled,
        is_recording_mode,
    )
except ImportError:
    from desktop.utils.route_utils import mark_route_flags_from_folder  # type: ignore
    from desktop.utils.settings_helper import (  # type: ignore
        get_pricetar_listing_url,
        is_pro_enabled,
        is_recording_mode,
    )

try:
    from ui.utils.draggable_file_icon import DraggableFileIconWidget
except ImportError:
    from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget  # type: ignore

try:
    from ui.utils.browser_front_scheduler import schedule_bring_browser_to_front
except ImportError:
    from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front  # type: ignore

from services.keepa_service import KeepaService
from services.ocr_service import OCRService
from services.purchase_cost_calc import (
    COL_PLATFORM_FEE,
    COL_SHIPPING,
    COL_TOTAL_COST,
    COL_LEGACY_AMAZON_FEE,
    augment_purchase_cost_record,
    backfill_total_cost_dataframe,
    cell_has_numeric_value,
    fee_storage_value,
    format_money_display,
    is_fee_amount_column,
    migrate_dataframe_fee_columns,
    read_fee_fields,
    recalculate_profit_fields,
    sync_total_cost_field,
    to_float as purchase_cost_to_float,
)

from .support import (
    SALES_CHANNEL_OPTIONS,
    SHIPPING_METHOD_OPTIONS,
    _ConditionNoteAiGenerateThread,
    _normalize_condition_note_newlines,
    _to_stored_newlines,
    _is_repricing_enabled_value,
)

class InventoryRowEditDialog(QDialog):
    """仕入データ1行を編集するダイアログ（コンディション説明は複数行・呼び出しボタン付き）"""
    
    def __init__(self, column_headers: List[str], row_data: Dict[str, Any],
                 condition_template_db, get_condition_key_func, parent=None):
        super().__init__(parent)
        self.column_headers = column_headers
        self.row_data = dict(row_data) if row_data else {}
        self.condition_template_db = condition_template_db
        self.get_condition_key = get_condition_key_func
        self._widgets = {}
        self._ai_generate_thread: Optional[_ConditionNoteAiGenerateThread] = None
        self.other_details_edit: Optional[QLineEdit] = None
        self.call_condition_note_btn: Optional[QPushButton] = None
        self.setWindowTitle("行の編集")
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)
        self._build_ui()
        self._apply_custom_missing_checkbox_labels()
        self._load_row_data()
        self._sync_missing_custom_checkboxes_enabled()
    
    def _sync_missing_custom_checkboxes_enabled(self) -> None:
        """取説欠品・内箱欠品のどちらかがONのときはカスタムを選べない（テンプレ重複の不具合防止）。"""
        fixed_on = self.missing_manual_checkbox.isChecked() or self.missing_inner_box_checkbox.isChecked()
        custom_cbs = (
            self.missing_custom1_checkbox,
            self.missing_custom2_checkbox,
            self.missing_custom3_checkbox,
        )
        for cb in custom_cbs:
            if fixed_on:
                cb.setChecked(False)
            cb.setEnabled(not fixed_on)
            cb.setToolTip(
                "取説欠品・内箱欠品のチェックを外すと、こちらを選べます。"
                if fixed_on
                else ""
            )
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)
        self.missing_manual_checkbox = QCheckBox("取説欠品")
        self.missing_inner_box_checkbox = QCheckBox("内箱欠品")
        self.missing_custom1_checkbox = QCheckBox("カスタム1")
        self.missing_custom2_checkbox = QCheckBox("カスタム2")
        self.missing_custom3_checkbox = QCheckBox("カスタム3")
        self.repricing_enabled_checkbox = QCheckBox("価格改定を有効（ON）")
        _missing_cb_style = """
                QCheckBox {
                    background-color: #3c3c3c;
                    color: #ffffff;
                    font-weight: bold;
                    border: 1px solid #555555;
                    border-radius: 3px;
                    padding: 2px 8px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                }
            """
        for cb in (
            self.missing_manual_checkbox,
            self.missing_inner_box_checkbox,
            self.missing_custom1_checkbox,
            self.missing_custom2_checkbox,
            self.missing_custom3_checkbox,
        ):
            cb.setStyleSheet(_missing_cb_style)
        self.missing_manual_checkbox.toggled.connect(self._sync_missing_custom_checkboxes_enabled)
        self.missing_inner_box_checkbox.toggled.connect(self._sync_missing_custom_checkboxes_enabled)
        
        for col in self.column_headers:
            if col == "その他詳細":
                continue
            if col == "コンディション説明":
                # コンディション説明の上に欠品・詳細（カスタム）チェックを配置
                missing_opts = QWidget()
                missing_opts_layout = QVBoxLayout(missing_opts)
                missing_opts_layout.setContentsMargins(0, 0, 0, 0)
                row1 = QHBoxLayout()
                row1.addWidget(self.missing_manual_checkbox)
                row1.addWidget(self.missing_inner_box_checkbox)
                row1.addStretch()
                missing_opts_layout.addLayout(row1)
                row2 = QHBoxLayout()
                row2.addWidget(self.missing_custom1_checkbox)
                row2.addWidget(self.missing_custom2_checkbox)
                row2.addWidget(self.missing_custom3_checkbox)
                row2.addStretch()
                missing_opts_layout.addLayout(row2)
                form.addRow("欠品・詳細（選択）:", missing_opts)

                self.other_details_edit = QLineEdit()
                self.other_details_edit.setPlaceholderText("例）シール使用済み、ブルーリュウソウル欠品 等")
                self._widgets["その他詳細"] = self.other_details_edit
                form.addRow("その他詳細:", self.other_details_edit)

                w = QPlainTextEdit()
                w.setPlaceholderText("複数行入力可。改行は\\nで保存されます。")
                w.setMinimumHeight(120)
                self._widgets[col] = w
                form.addRow(QLabel(col + ":"), w)
            elif col == "コメント":
                w = QPlainTextEdit()
                w.setMinimumHeight(60)
                self._widgets[col] = w
                form.addRow(QLabel(col + ":"), w)
            elif col == "発送方法":
                w = QComboBox()
                w.addItems(SHIPPING_METHOD_OPTIONS)
                self._widgets[col] = w
                form.addRow(QLabel(col + ":"), w)
            elif col == "販売チャネル":
                w = QComboBox()
                w.addItems(SALES_CHANNEL_OPTIONS)
                self._widgets[col] = w
                form.addRow(QLabel(col + ":"), w)
            elif col == "価格改定":
                self._widgets[col] = self.repricing_enabled_checkbox
                form.addRow(QLabel(col + ":"), self.repricing_enabled_checkbox)
            else:
                w = QLineEdit()
                self._widgets[col] = w
                form.addRow(QLabel(col + ":"), w)
        
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        self.call_condition_note_btn = QPushButton("コンディション説明呼び出し")
        self.call_condition_note_btn.setToolTip(
            "コンディション説明タブのテンプレートを挿入します。\n"
            "「その他詳細」に入力がある場合は、欠品・詳細の選択と合わせて AI が説明文を生成します。"
        )
        self.call_condition_note_btn.clicked.connect(self._on_call_condition_note)
        clear_condition_note_btn = QPushButton("クリア")
        clear_condition_note_btn.setToolTip("コンディション説明欄のテキストを空にします。")
        clear_condition_note_btn.clicked.connect(self._on_clear_condition_note)
        btn_layout.addWidget(self.call_condition_note_btn)
        btn_layout.addWidget(clear_condition_note_btn)
        btn_layout.addStretch()
        form.addRow("", btn_row)
        
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
    
    def _apply_custom_missing_checkbox_labels(self) -> None:
        """詳細説明タブで保存したカスタム名称をチェックボックス表示に反映"""
        try:
            md = self.condition_template_db.load_missing_keywords()
            lab = md.get("custom_labels") or {}
            defaults = {"custom1": "カスタム1", "custom2": "カスタム2", "custom3": "カスタム3"}
            self.missing_custom1_checkbox.setText(lab.get("custom1") or defaults["custom1"])
            self.missing_custom2_checkbox.setText(lab.get("custom2") or defaults["custom2"])
            self.missing_custom3_checkbox.setText(lab.get("custom3") or defaults["custom3"])
        except Exception:
            pass

    def _load_row_data(self):
        for col in self.column_headers:
            w = self._widgets.get(col)
            if not w:
                continue
            val = self.row_data.get(col, "")
            if val is None or (isinstance(val, float) and pd.isna(val)):
                val = ""
            val = str(val).strip() if val != "" else ""
            if col == "コンディション説明":
                # 保存時は改行を\nで扱うので、表示時はリテラル \n を実際の改行に
                val = _normalize_condition_note_newlines(val)
            if isinstance(w, QPlainTextEdit):
                w.setPlainText(val)
            elif isinstance(w, QComboBox):
                if col == "発送方法" and not val:
                    val = "FBA"
                if not val:
                    val = "Amazon"
                idx = w.findText(val)
                if idx < 0:
                    w.addItem(val)
                    idx = w.findText(val)
                w.setCurrentIndex(max(0, idx))
            elif isinstance(w, QCheckBox):
                w.setChecked(_is_repricing_enabled_value(val))
            else:
                w.setText(val)
    
    def _on_clear_condition_note(self) -> None:
        note_w = self._widgets.get("コンディション説明")
        if note_w and isinstance(note_w, QPlainTextEdit):
            note_w.clear()

    def _on_call_condition_note(self):
        other_details = ""
        if self.other_details_edit is not None:
            other_details = self.other_details_edit.text().strip()
        if other_details:
            self._start_ai_condition_note_generation(other_details)
            return

        cond_w = self._widgets.get("コンディション")
        note_w = self._widgets.get("コンディション説明")
        if not cond_w or not note_w:
            return
        condition_text = cond_w.text().strip() if isinstance(cond_w, QLineEdit) else cond_w.toPlainText().strip()
        if not condition_text:
            QMessageBox.information(self, "呼び出し", "先に「コンディション」を入力してください。")
            return
        condition_key = self.get_condition_key(condition_text)
        text = self.condition_template_db.get_condition_description_text(condition_key)
        if not text:
            QMessageBox.information(self, "呼び出し", f"コンディション「{condition_text}」に対応する説明が登録されていません。\nコンディション説明タブで登録してください。")
            return
        # テンプレートは改行を "\\n" で保存しているので、表示用に実際の改行に変換（1行表示で行区切りに\nが入った状態で編集欄に表示）
        text = _normalize_condition_note_newlines(text)

        # 欠品・詳細（カスタム）チェックに応じて「詳細説明」タブの文面を挿入
        try:
            manual_checked = bool(self.missing_manual_checkbox.isChecked())
            inner_box_checked = bool(self.missing_inner_box_checkbox.isChecked())
            missing_key = ""
            if manual_checked and inner_box_checked:
                missing_key = "取説・内箱欠品"
            elif manual_checked:
                missing_key = "取説欠品"
            elif inner_box_checked:
                missing_key = "内箱欠品"

            missing_data = self.condition_template_db.load_missing_keywords()
            kw = missing_data.get("keywords", {}) or {}

            if missing_key:
                missing_text = str(kw.get(missing_key, "") or "").strip()
                if missing_text:
                    if "{欠品}" in text:
                        text = text.replace("{欠品}", missing_text)
                    elif "【付属品】" in text:
                        text = text.replace("【付属品】", f"【付属品】{missing_text}")
                    else:
                        text = f"{text}\n【付属品】{missing_text}".strip()

            extra_parts: List[str] = []
            for ck, cb in (
                ("custom1", self.missing_custom1_checkbox),
                ("custom2", self.missing_custom2_checkbox),
                ("custom3", self.missing_custom3_checkbox),
            ):
                if cb.isChecked():
                    part = str(kw.get(ck, "") or "").strip()
                    if part:
                        extra_parts.append(part)
            if extra_parts:
                extra_block = "\n".join(extra_parts)
                text = f"{text.rstrip()}\n{extra_block}".strip() if text.strip() else extra_block
        except Exception:
            # 詳細説明が取得できない場合は通常テンプレートのみを使用
            pass

        note_w.setPlainText(text)

    def _collect_missing_selection_items(self) -> List[Dict[str, str]]:
        """欠品・詳細チェックと詳細説明タブの文面を収集する。"""
        items: List[Dict[str, str]] = []
        try:
            missing_data = self.condition_template_db.load_missing_keywords()
            kw = missing_data.get("keywords", {}) or {}
        except Exception:
            kw = {}

        manual_checked = bool(self.missing_manual_checkbox.isChecked())
        inner_box_checked = bool(self.missing_inner_box_checkbox.isChecked())
        if manual_checked and inner_box_checked:
            missing_key = "取説・内箱欠品"
            label = "取説・内箱欠品"
        elif manual_checked:
            missing_key = "取説欠品"
            label = "取説欠品"
        elif inner_box_checked:
            missing_key = "内箱欠品"
            label = "内箱欠品"
        else:
            missing_key = ""
            label = ""

        if missing_key:
            items.append({
                "label": label,
                "text": str(kw.get(missing_key, "") or "").strip(),
            })

        for ck, cb in (
            ("custom1", self.missing_custom1_checkbox),
            ("custom2", self.missing_custom2_checkbox),
            ("custom3", self.missing_custom3_checkbox),
        ):
            if cb.isChecked():
                items.append({
                    "label": cb.text().strip(),
                    "text": str(kw.get(ck, "") or "").strip(),
                })
        return items

    def _start_ai_condition_note_generation(self, other_details: str) -> None:
        cond_w = self._widgets.get("コンディション")
        if not cond_w:
            return
        condition_text = cond_w.text().strip() if isinstance(cond_w, QLineEdit) else cond_w.toPlainText().strip()
        if not condition_text:
            QMessageBox.information(self, "呼び出し", "先に「コンディション」を入力してください。")
            return

        if self._ai_generate_thread is not None and self._ai_generate_thread.isRunning():
            QMessageBox.information(self, "呼び出し", "生成処理が実行中です。しばらくお待ちください。")
            return

        condition_key = self.get_condition_key(condition_text)
        template_text = self.condition_template_db.get_condition_description_text(condition_key)
        if not template_text:
            QMessageBox.information(
                self,
                "呼び出し",
                f"コンディション「{condition_text}」に対応する説明が登録されていません。\n"
                "コンディション説明タブで登録してください。",
            )
            return

        product_w = self._widgets.get("商品名")
        product_name = ""
        if isinstance(product_w, QLineEdit):
            product_name = product_w.text().strip()

        missing_items = self._collect_missing_selection_items()
        if self.call_condition_note_btn is not None:
            self.call_condition_note_btn.setEnabled(False)
            self.call_condition_note_btn.setText("AI生成中...")

        self._ai_generate_thread = _ConditionNoteAiGenerateThread(
            condition_label=condition_text,
            condition_template=template_text,
            missing_items=missing_items,
            other_details=other_details,
            product_name=product_name,
            parent=self,
        )
        self._ai_generate_thread.finished_ok.connect(self._on_ai_generate_finished)
        self._ai_generate_thread.finished_error.connect(self._on_ai_generate_error)
        self._ai_generate_thread.finished.connect(self._on_ai_generate_thread_finished)
        self._ai_generate_thread.start()

    def _on_ai_generate_finished(self, text: str) -> None:
        note_w = self._widgets.get("コンディション説明")
        if note_w and isinstance(note_w, QPlainTextEdit):
            note_w.setPlainText(_normalize_condition_note_newlines(text))

    def _on_ai_generate_error(self, message: str) -> None:
        QMessageBox.warning(self, "呼び出し", message)

    def _on_ai_generate_thread_finished(self) -> None:
        if self.call_condition_note_btn is not None:
            self.call_condition_note_btn.setEnabled(True)
            self.call_condition_note_btn.setText("コンディション説明呼び出し")
        self._ai_generate_thread = None
    
    def get_result(self) -> Dict[str, Any]:
        result = {}
        for col in self.column_headers:
            w = self._widgets.get(col)
            if not w:
                continue
            if isinstance(w, QPlainTextEdit):
                val = w.toPlainText().strip()
            elif isinstance(w, QComboBox):
                val = w.currentText().strip()
            elif isinstance(w, QCheckBox):
                val = "ON" if w.isChecked() else "OFF"
            else:
                val = w.text().strip()
            if col == "コンディション説明":
                # 保存時は改行を \n で扱う（1行表示で行区切りに\nが入る形）
                val = _to_stored_newlines(val) if val else ""
            elif col == "発送方法":
                val = val or "FBA"
            elif col == "販売チャネル":
                val = val or "Amazon"
            result[col] = val
        return result

