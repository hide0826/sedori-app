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
from PySide6.QtCore import Qt, QDate, QTime, QDateTime, Signal, QSettings, QThread, QTimer, QEvent
from PySide6.QtGui import QFont, QColor, QPalette, QStandardItemModel, QStandardItem, QDesktopServices, QKeySequence
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
        get_purchase_evidence_local_root,
        set_purchase_evidence_local_root,
    )
except ImportError:
    from desktop.utils.route_utils import mark_route_flags_from_folder  # type: ignore
    from desktop.utils.settings_helper import (  # type: ignore
        get_pricetar_listing_url,
        is_pro_enabled,
        is_recording_mode,
        get_purchase_evidence_local_root,
        set_purchase_evidence_local_root,
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
    checked_detail_description,
    _normalize_condition_note_newlines,
    _to_stored_newlines,
    _is_repricing_enabled_value,
)
from .flea_evidence_panel import FleaEvidencePanel
from services.flea_market_evidence_ocr import is_delivery_label_name
from services.flea_market_evidence_service import (
    EVIDENCE_HIDDEN_COLUMNS,
    record_fields_from_save,
    save_evidence_bundle,
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
        self.evidence_panel: Optional[FleaEvidencePanel] = None
        self._evidence_extra_fields: Dict[str, Any] = {}
        self.setWindowTitle("行の編集")
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)
        self._build_ui()
        self._apply_custom_missing_checkbox_labels()
        self._load_row_data()
        self._sync_missing_custom_checkboxes_enabled()
        self._attach_evidence_panel()
    
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
        self._scroll_area = scroll
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        self._evidence_host = QWidget()
        self._evidence_host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        evidence_host_layout = QVBoxLayout(self._evidence_host)
        evidence_host_layout.setContentsMargins(0, 0, 0, 0)
        evidence_host_layout.setSpacing(0)
        content_layout.addWidget(self._evidence_host)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        self._form_layout = form
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
            if col in EVIDENCE_HIDDEN_COLUMNS:
                continue
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
            "欠品・詳細にチェックがあるときは、詳細説明の文だけを入れます。\n"
            "チェックが無いときは、良い・非常に良いなどのテンプレートを入れます。\n"
            "「その他詳細」に入力がある場合は、AI が説明文を生成します。"
        )
        self.call_condition_note_btn.clicked.connect(self._on_call_condition_note)
        clear_condition_note_btn = QPushButton("クリア")
        clear_condition_note_btn.setToolTip("コンディション説明欄のテキストを空にします。")
        clear_condition_note_btn.clicked.connect(self._on_clear_condition_note)
        btn_layout.addWidget(self.call_condition_note_btn)
        btn_layout.addWidget(clear_condition_note_btn)
        btn_layout.addStretch()
        form.addRow("", btn_row)
        content_layout.addWidget(form_widget)
        
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

    def _checked_detail_description(self) -> Optional[str]:
        """欠品・詳細がONなら詳細説明の文だけ。未チェックなら None。"""
        try:
            missing_data = self.condition_template_db.load_missing_keywords()
            keywords = missing_data.get("keywords", {}) or {}
        except Exception:
            keywords = {}
        return checked_detail_description(
            keywords,
            manual=bool(self.missing_manual_checkbox.isChecked()),
            inner_box=bool(self.missing_inner_box_checkbox.isChecked()),
            custom1=bool(self.missing_custom1_checkbox.isChecked()),
            custom2=bool(self.missing_custom2_checkbox.isChecked()),
            custom3=bool(self.missing_custom3_checkbox.isChecked()),
        )

    def _on_call_condition_note(self):
        note_w = self._widgets.get("コンディション説明")
        detail = self._checked_detail_description()
        if detail is not None:
            if not detail:
                QMessageBox.information(
                    self,
                    "呼び出し",
                    "チェックした項目の文が、詳細説明に登録されていません。",
                )
                return
            if note_w and isinstance(note_w, QPlainTextEdit):
                note_w.setPlainText(_normalize_condition_note_newlines(detail))
            return

        other_details = ""
        if self.other_details_edit is not None:
            other_details = self.other_details_edit.text().strip()
        if other_details:
            self._start_ai_condition_note_generation(other_details)
            return

        cond_w = self._widgets.get("コンディション")
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
        text = _normalize_condition_note_newlines(text)
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
        from services.flea_market_evidence_service import EVIDENCE_HIDDEN_COLUMNS
        for col in EVIDENCE_HIDDEN_COLUMNS:
            if col not in result:
                result[col] = str(self.row_data.get(col) or "")
        result.update(self._evidence_extra_fields)
        return result

    def _widget_text(self, col: str) -> str:
        w = self._widgets.get(col)
        if isinstance(w, QLineEdit):
            return w.text().strip()
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText().strip()
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        return str(self.row_data.get(col) or "").strip()

    def _set_widget_text(self, col: str, value: str, only_if_empty: bool = False) -> None:
        if not value:
            return
        if only_if_empty and self._widget_text(col):
            return
        w = self._widgets.get(col)
        if isinstance(w, QLineEdit):
            w.setText(value)
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText(value)

    def _attach_evidence_panel(self) -> None:
        """スクショ貼付パネルをスクロール先頭に出す（判定漏れで消えないように常時表示）。"""
        current_dt = self._widget_text("仕入れ日") or str(self.row_data.get("仕入れ日") or "")
        panel = FleaEvidencePanel(current_dt, self)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        panel.setMinimumHeight(280)
        panel.load_existing_row(self.row_data)
        panel.ocr_finished.connect(self._apply_ocr_fields_to_widgets)
        host = getattr(self, "_evidence_host", None)
        host_layout = host.layout() if host is not None else None
        if host_layout is not None:
            host_layout.addWidget(panel)
        elif getattr(self, "_form_layout", None) is not None:
            self._form_layout.insertRow(0, panel)
        else:
            layout = self.layout()
            if layout is not None:
                layout.insertWidget(0, panel)
        self.evidence_panel = panel
        self.setMinimumWidth(980)
        self.setMinimumHeight(760)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        scroll = getattr(self, "_scroll_area", None)
        if scroll is not None:
            QTimer.singleShot(0, lambda: scroll.verticalScrollBar().setValue(0))

    def eventFilter(self, watched, event):
        if self.evidence_panel is not None and event is not None:
            try:
                if event.type() == QEvent.KeyPress and event.matches(QKeySequence.Paste):
                    w = watched if isinstance(watched, QWidget) else None
                    if w is not None and (w is self or self.isAncestorOf(w)):
                        clip = QApplication.clipboard()
                        img = clip.image() if clip else None
                        if img is not None and not img.isNull():
                            self.evidence_panel.paste_clipboard_to_next()
                            return True
            except Exception:
                pass
        return super().eventFilter(watched, event)

    def _remove_evidence_event_filter(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def _apply_ocr_fields_to_widgets(self, parsed, only_if_empty: bool = False) -> None:
        if parsed is None:
            return
        self._set_widget_text(
            "取引ID", getattr(parsed, "item_id", "") or "", only_if_empty=only_if_empty
        )
        self._set_widget_text(
            "出品URL", getattr(parsed, "listing_url", "") or "", only_if_empty=only_if_empty
        )
        seller = getattr(parsed, "seller_name", "") or ""
        if is_delivery_label_name(seller):
            seller = ""
        current_seller = self._widget_text("ユーザー名")
        # 配送表示だけ入っているときは、読み取った出品者名で入れ直してよい
        seller_only_if_empty = only_if_empty and not is_delivery_label_name(current_seller)
        self._set_widget_text("ユーザー名", seller, only_if_empty=seller_only_if_empty)

    def accept(self):
        if self.evidence_panel is not None:
            if not self._commit_evidence_panel():
                return
        self._remove_evidence_event_filter()
        super().accept()

    def reject(self):
        if self.evidence_panel is not None:
            self.evidence_panel.cleanup_temps()
        self._remove_evidence_event_filter()
        super().reject()

    def _commit_evidence_panel(self) -> bool:
        panel = self.evidence_panel
        if panel is None:
            return True
        parsed = panel.ocr_result()
        if panel.has_any_image() and not parsed.has_core_fields():
            # ここでOCR完了通知を出すと、手入力したユーザー名が上書きされる
            blocked = False
            try:
                panel.ocr_finished.disconnect(self._apply_ocr_fields_to_widgets)
                blocked = True
            except (TypeError, RuntimeError):
                blocked = False
            try:
                parsed = panel.run_ocr()
            finally:
                if blocked:
                    panel.ocr_finished.connect(self._apply_ocr_fields_to_widgets)
        self._apply_ocr_fields_to_widgets(parsed, only_if_empty=True)
        if panel.should_apply_datetime() and parsed.purchase_datetime:
            self._set_widget_text("仕入れ日", parsed.purchase_datetime)
        if not panel.has_any_image():
            return True
        try:
            from utils.settings_helper import (
                get_purchase_evidence_local_root,
                set_purchase_evidence_local_root,
            )
        except ImportError:
            from desktop.utils.settings_helper import (  # type: ignore
                get_purchase_evidence_local_root,
                set_purchase_evidence_local_root,
            )
        root = get_purchase_evidence_local_root()
        if not root:
            root = QFileDialog.getExistingDirectory(self, "仕入証憑の保存先フォルダを選択")
            if not root:
                QMessageBox.warning(
                    self,
                    "証憑",
                    "スクショを保存するには、保存先フォルダを選んでください。",
                )
                return False
            set_purchase_evidence_local_root(root)
        asin = self._widget_text("ASIN")
        store = self._widget_text("仕入先") or str(self.row_data.get("仕入先") or "")
        dt = self._widget_text("仕入れ日")
        temps = panel.export_slot_temp_paths()
        try:
            markets = StoreDatabase().list_flea_markets(active_only=False)
        except Exception:
            markets = []
        try:
            result = save_evidence_bundle(
                root=root,
                purchase_datetime=dt,
                store_value=store,
                asin=asin,
                slot_sources=temps,
                flea_markets=markets,
                upload_to_gcs=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "証憑", f"ローカル保存に失敗しました:\n{exc}")
            return False
        finally:
            panel.cleanup_temps()
        self._evidence_extra_fields = record_fields_from_save(result)
        if result.gcs_error:
            QMessageBox.warning(
                self,
                "GCS",
                "画像はパソコンに保存しましたが、クラウド（GCS）へのアップロードに失敗しました。\n"
                f"{result.gcs_error}",
            )
        return True

