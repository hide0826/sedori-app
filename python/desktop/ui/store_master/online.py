#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""電脳店舗・プラットフォーム・フリマ・問屋マスタ。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QLabel, QGroupBox, QFileDialog, QTextEdit,
    QComboBox, QCheckBox, QDialogButtonBox, QTabWidget,
    QProgressDialog, QApplication, QListWidget, QListWidgetItem,
    QSplitter, QDoubleSpinBox, QAbstractItemView, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QSettings
from PySide6.QtGui import QColor, QDrag
from typing import Tuple, List, Dict, Any, Optional
import sys
import os
import re
import webbrowser

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from utils.excel_importer import ExcelImporter
from utils.ui_utils import reapply_table_column_widths


class OnlinePlatformEditDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.data = data
        self._manual_code = False
        self._manual_prefix = False
        self.setWindowTitle("電脳プラットフォーム編集" if data else "電脳プラットフォーム追加")
        self.setModal(True)
        self._build_ui()
        if data:
            self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("例: AMZ")
        self.code_edit.textEdited.connect(self._on_code_edited)
        form.addRow("プラットフォームコード:", self.code_edit)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: Amazon")
        self.name_edit.textChanged.connect(self._on_platform_name_changed)
        form.addRow("プラットフォーム名:", self.name_edit)
        self.category_combo = QComboBox()
        self.category_combo.addItems(["モール", "フリマ", "その他"])
        form.addRow("区分:", self.category_combo)
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("例: AMZ")
        self.prefix_edit.textEdited.connect(self._on_prefix_edited)
        form.addRow("コード接頭辞:", self.prefix_edit)
        self.active_check = QCheckBox("有効")
        self.active_check.setChecked(True)
        form.addRow("状態:", self.active_check)
        self.notes_edit = QLineEdit()
        form.addRow("備考:", self.notes_edit)
        layout.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _load_data(self):
        self.code_edit.setText(self.data.get("platform_code", ""))
        self.name_edit.setText(self.data.get("platform_name", ""))
        self.category_combo.setCurrentText(self.data.get("category", "モール"))
        self.prefix_edit.setText(self.data.get("code_prefix", ""))
        self.active_check.setChecked(bool(self.data.get("is_active", 1)))
        self.notes_edit.setText(self.data.get("notes", ""))
        # 既存データ編集時は既存値を尊重（自動補完で上書きしない）
        self._manual_code = True
        self._manual_prefix = True

    def _on_code_edited(self, text: str):
        self._manual_code = bool((text or "").strip())

    def _on_prefix_edited(self, text: str):
        self._manual_prefix = bool((text or "").strip())

    def _suggest_platform_tokens(self, name: str) -> tuple[str, str]:
        n = (name or "").strip().lower()
        known = {
            "amazon": ("AMZ", "AMZ"),
            "楽天": ("RKT", "RKT"),
            "rakuten": ("RKT", "RKT"),
            "rakuten ichiba": ("RKT", "RKT"),
            "ヤフショ": ("YHS", "YHS"),
            "yahoo shopping": ("YHS", "YHS"),
            "yahooショッピング": ("YHS", "YHS"),
            "ヤフオク": ("YAO", "YAO"),
            "yahoo auction": ("YAO", "YAO"),
            "メルカリ": ("MRC", "MRC"),
            "mercari": ("MRC", "MRC"),
            "ラクマ": ("RKM", "RKM"),
            "rakuma": ("RKM", "RKM"),
        }
        if n in known:
            return known[n]
        import re
        alnum = re.sub(r"[^A-Za-z0-9]", "", (name or "").upper())
        if not alnum:
            return ("PLT", "PLT")
        token = (alnum[:3] if len(alnum) >= 3 else alnum.ljust(3, "X"))
        return (token, token)

    def _on_platform_name_changed(self, text: str):
        # 追加時のみ自動提案（既存編集は手入力優先）
        if self.data:
            return
        if not (text or "").strip():
            return
        code, prefix = self._suggest_platform_tokens(text)
        if (not self._manual_code) or not self.code_edit.text().strip():
            self.code_edit.setText(code)
        if (not self._manual_prefix) or not self.prefix_edit.text().strip():
            self.prefix_edit.setText(prefix)

    def get_data(self) -> Dict[str, Any]:
        return {
            "platform_code": self.code_edit.text().strip().upper(),
            "platform_name": self.name_edit.text().strip(),
            "category": self.category_combo.currentText().strip(),
            "code_prefix": self.prefix_edit.text().strip().upper(),
            "is_active": 1 if self.active_check.isChecked() else 0,
            "notes": self.notes_edit.text().strip(),
        }


class FleaMarketEditDialog(QDialog):
    """フリマプラットフォーム追加・編集（区分は固定でフリマ。手数料率はフリマ設定タブで編集）"""

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.data = data
        self._manual_code = False
        self._manual_prefix = False
        self.setWindowTitle("フリマ編集" if data else "フリマ追加")
        self.setModal(True)
        self._build_ui()
        if data:
            self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("例: MRC")
        self.code_edit.textEdited.connect(self._on_code_edited)
        form.addRow("コード:", self.code_edit)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: メルカリ")
        self.name_edit.textChanged.connect(self._on_platform_name_changed)
        form.addRow("名称:", self.name_edit)
        self.category_label = QLabel("フリマ")
        form.addRow("区分:", self.category_label)
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("例: MRC")
        self.prefix_edit.textEdited.connect(self._on_prefix_edited)
        form.addRow("接頭辞:", self.prefix_edit)
        self.active_check = QCheckBox("有効")
        self.active_check.setChecked(True)
        form.addRow("状態:", self.active_check)
        self.notes_edit = QLineEdit()
        form.addRow("備考:", self.notes_edit)
        layout.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _load_data(self):
        self.code_edit.setText(self.data.get("platform_code", ""))
        self.name_edit.setText(self.data.get("platform_name", ""))
        self.prefix_edit.setText(self.data.get("code_prefix", ""))
        self.active_check.setChecked(bool(self.data.get("is_active", 1)))
        self.notes_edit.setText(self.data.get("notes", ""))
        self._manual_code = True
        self._manual_prefix = True

    def _on_code_edited(self, text: str):
        self._manual_code = bool((text or "").strip())

    def _on_prefix_edited(self, text: str):
        self._manual_prefix = bool((text or "").strip())

    def _suggest_tokens(self, name: str) -> tuple[str, str]:
        n = (name or "").strip().lower()
        known = {
            "メルカリ": ("MRC", "MRC"),
            "mercari": ("MRC", "MRC"),
            "ヤフオク": ("YAO", "YAO"),
            "yahoo auction": ("YAO", "YAO"),
            "ラクマ": ("RKM", "RKM"),
            "rakuma": ("RKM", "RKM"),
            "paypayフリマ": ("PPF", "PPF"),
        }
        if n in known:
            return known[n]
        import re
        alnum = re.sub(r"[^A-Za-z0-9]", "", (name or "").upper())
        if not alnum:
            return ("FRM", "FRM")
        token = (alnum[:3] if len(alnum) >= 3 else alnum.ljust(3, "X"))
        return (token, token)

    def _on_platform_name_changed(self, text: str):
        if self.data:
            return
        if not (text or "").strip():
            return
        code, prefix = self._suggest_tokens(text)
        if (not self._manual_code) or not self.code_edit.text().strip():
            self.code_edit.setText(code)
        if (not self._manual_prefix) or not self.prefix_edit.text().strip():
            self.prefix_edit.setText(prefix)

    def get_data(self) -> Dict[str, Any]:
        return {
            "platform_code": self.code_edit.text().strip().upper(),
            "platform_name": self.name_edit.text().strip(),
            "category": "フリマ",
            "code_prefix": self.prefix_edit.text().strip().upper(),
            "is_active": 1 if self.active_check.isChecked() else 0,
            "notes": self.notes_edit.text().strip(),
        }


class OnlineStoreEditDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.db = StoreDatabase()
        self.data = data
        self.setWindowTitle("電脳店舗編集" if data else "電脳店舗追加")
        self.setModal(True)
        self._build_ui()
        self._load_platforms()
        if data:
            self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.platform_combo = QComboBox()
        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        form.addRow("プラットフォーム:", self.platform_combo)
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("自動生成")
        form.addRow("店舗コード:", self.code_edit)
        self.shop_name_edit = QLineEdit()
        self.shop_name_edit.setPlaceholderText("ショップ名 / 出品者名")
        self.shop_name_edit.textChanged.connect(self._on_shop_name_changed)
        form.addRow("店舗名:", self.shop_name_edit)
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("住所（任意）")
        form.addRow("住所:", self.address_edit)
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("電話番号（任意）")
        form.addRow("電話番号:", self.phone_edit)
        self.registration_edit = QLineEdit()
        form.addRow("登録番号:", self.registration_edit)
        self.secondhand_license_edit = QLineEdit()
        self.secondhand_license_edit.setPlaceholderText("任意")
        form.addRow("古物商許可番号:", self.secondhand_license_edit)
        self.active_check = QCheckBox("有効")
        self.active_check.setChecked(True)
        form.addRow("状態:", self.active_check)
        self.notes_edit = QLineEdit()
        form.addRow("備考:", self.notes_edit)
        layout.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _load_platforms(self):
        self.platform_combo.clear()
        # 新規は有効なプラットフォームのみ。編集時は無効化済みのものも含めて一覧し、現在値と整合させる。
        active_only = self.data is None
        for p in self.db.list_online_platforms(active_only=active_only):
            self.platform_combo.addItem(f"{p.get('platform_name')} ({p.get('category')})", p)

    def _on_platform_changed(self):
        self._autofill_code_if_empty()

    def _on_shop_name_changed(self, _text: str):
        self._autofill_code_if_empty()

    def _autofill_code_if_empty(self):
        if self.data:
            return
        if self.code_edit.text().strip():
            return
        pdata = self.platform_combo.currentData()
        if not pdata:
            return
        prefix = pdata.get("code_prefix") or pdata.get("platform_code") or "ONL"
        self.code_edit.setText(self.db.get_next_online_store_code(prefix))

    def accept(self):
        fw = QApplication.focusWidget()
        if fw is not None:
            fw.clearFocus()
        super().accept()

    def _load_data(self):
        current_platform_id = self.data.get("platform_id")
        for i in range(self.platform_combo.count()):
            pdata = self.platform_combo.itemData(i)
            if pdata and pdata.get("id") == current_platform_id:
                self.platform_combo.setCurrentIndex(i)
                break
        self.code_edit.setText(self.data.get("supplier_code", ""))
        self.shop_name_edit.setText(self.data.get("shop_name", ""))
        self.address_edit.setText(self.data.get("address", "") or "")
        self.phone_edit.setText(self.data.get("phone", "") or "")
        self.registration_edit.setText(self.data.get("registration_number", ""))
        self.secondhand_license_edit.setText(self.data.get("secondhand_license_number", "") or "")
        self.notes_edit.setText(self.data.get("notes", ""))
        self.active_check.setChecked(bool(self.data.get("is_active", 1)))

    def get_data(self) -> Dict[str, Any]:
        pdata = self.platform_combo.currentData() or {}
        return {
            "platform_id": pdata.get("id"),
            "supplier_code": self.code_edit.text().strip().upper(),
            "shop_name": self.shop_name_edit.text().strip(),
            "address": self.address_edit.text().strip(),
            "phone": self.phone_edit.text().strip(),
            "registration_number": self.registration_edit.text().strip(),
            "secondhand_license_number": self.secondhand_license_edit.text().strip(),
            "is_active": 1 if self.active_check.isChecked() else 0,
            "notes": self.notes_edit.text().strip(),
        }


class WholesalerEditDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.db = StoreDatabase()
        self.data = data
        self.setWindowTitle("問屋編集" if data else "問屋追加")
        self.setModal(True)
        self._build_ui()
        if data:
            self._load_data()
        else:
            self.code_edit.setText(self.db.get_next_wholesaler_code("WS"))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.code_edit = QLineEdit()
        form.addRow("問屋コード:", self.code_edit)
        self.name_edit = QLineEdit()
        form.addRow("問屋名:", self.name_edit)
        self.registration_edit = QLineEdit()
        form.addRow("登録番号:", self.registration_edit)
        self.active_check = QCheckBox("有効")
        self.active_check.setChecked(True)
        form.addRow("状態:", self.active_check)
        self.notes_edit = QLineEdit()
        form.addRow("備考:", self.notes_edit)
        layout.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _load_data(self):
        self.code_edit.setText(self.data.get("wholesaler_code", ""))
        self.name_edit.setText(self.data.get("name", ""))
        self.registration_edit.setText(self.data.get("registration_number", ""))
        self.notes_edit.setText(self.data.get("notes", ""))
        self.active_check.setChecked(bool(self.data.get("is_active", 1)))

    def get_data(self) -> Dict[str, Any]:
        return {
            "wholesaler_code": self.code_edit.text().strip().upper(),
            "name": self.name_edit.text().strip(),
            "registration_number": self.registration_edit.text().strip(),
            "is_active": 1 if self.active_check.isChecked() else 0,
            "notes": self.notes_edit.text().strip(),
        }


class OnlinePlatformListWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("プラットフォーム名で検索...")
        self.search_edit.textChanged.connect(self.load_data)
        top.addWidget(self.search_edit)
        add_btn = QPushButton("追加"); add_btn.clicked.connect(self.add_item); top.addWidget(add_btn)
        edit_btn = QPushButton("編集"); edit_btn.clicked.connect(self.edit_item); top.addWidget(edit_btn)
        del_btn = QPushButton("削除"); del_btn.clicked.connect(self.delete_item); top.addWidget(del_btn)
        layout.addLayout(top)
        caution_label = QLabel(
            "古物台帳記帳のため、プラットフォーム名は正式名称"
            "（例: Amazon.co.jp、楽天市場、Yahoo!ショッピング）での登録を推奨します。"
        )
        caution_label.setWordWrap(True)
        caution_label.setStyleSheet("color: #ffc107; padding: 2px 0px;")
        layout.addWidget(caution_label)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        self.table.setSizePolicy(self.table.sizePolicy().horizontalPolicy(), self.table.sizePolicy().verticalPolicy())
        layout.addWidget(self.table)

    def load_data(self):
        rows = self.db.list_online_platforms(active_only=False)
        s = (self.search_edit.text() or "").strip().lower()
        if s:
            rows = [r for r in rows if s in str(r.get("platform_name", "")).lower()]
        cols = ["ID", "コード", "名称", "区分", "接頭辞", "有効", "備考"]
        self.table.setRowCount(len(rows)); self.table.setColumnCount(len(cols)); self.table.setHorizontalHeaderLabels(cols)
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("platform_code", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("platform_name", "")))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("category", "")))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("code_prefix", "")))
            self.table.setItem(i, 5, QTableWidgetItem("ON" if r.get("is_active", 1) else "OFF"))
            self.table.setItem(i, 6, QTableWidgetItem(r.get("notes", "")))
        reapply_table_column_widths(self.table)
        self.table.verticalHeader().setDefaultSectionSize(26)

    def _get_selected_id(self) -> Optional[int]:
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not sel:
            return None
        item = self.table.item(sel[0].row(), 0)
        try:
            return int(item.text()) if item else None
        except Exception:
            return None

    def _on_table_double_clicked(self, row: int, _column: int):
        if row < 0:
            return
        self.table.selectRow(row)
        self.edit_item()

    def add_item(self):
        d = OnlinePlatformEditDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        data = d.get_data()
        if not data.get("platform_code") or not data.get("platform_name") or not data.get("code_prefix"):
            QMessageBox.warning(self, "入力エラー", "コード・名称・接頭辞は必須です。")
            return
        if self.db.check_online_platform_code_exists(data["platform_code"]):
            QMessageBox.warning(self, "重複", "プラットフォームコードが重複しています。")
            return
        self.db.add_online_platform(data)
        self.load_data()

    def edit_item(self):
        pid = self._get_selected_id()
        if not pid:
            return
        data = self.db.get_online_platform(pid)
        if not data:
            return
        d = OnlinePlatformEditDialog(self, data=data)
        if d.exec() != QDialog.Accepted:
            return
        new_data = d.get_data()
        if self.db.check_online_platform_code_exists(new_data["platform_code"], exclude_id=pid):
            QMessageBox.warning(self, "重複", "プラットフォームコードが重複しています。")
            return
        self.db.update_online_platform(pid, new_data)
        self.load_data()

    def delete_item(self):
        pid = self._get_selected_id()
        if not pid:
            return
        if QMessageBox.question(self, "確認", "選択したプラットフォームを削除しますか？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.db.delete_online_platform(pid)
        self.load_data()


class FleaMarketListWidget(QWidget):
    """フリマプラットフォーム一覧（設定 > 店舗コード設定 > フリマコード）"""

    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("名称で検索...")
        self.search_edit.textChanged.connect(self.load_data)
        top.addWidget(self.search_edit)
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_item)
        top.addWidget(add_btn)
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self.edit_item)
        top.addWidget(edit_btn)
        del_btn = QPushButton("削除")
        del_btn.clicked.connect(self.delete_item)
        top.addWidget(del_btn)
        layout.addLayout(top)
        caution_label = QLabel(
            "古物台帳記帳のため、名称は正式名称（例: メルカリ、ラクマ）での登録を推奨します。\n"
            "手数料率は「設定 > フリマ設定」で入力してください。"
        )
        caution_label.setWordWrap(True)
        caution_label.setStyleSheet("color: #ffc107; padding: 2px 0px;")
        layout.addWidget(caution_label)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        self.table.setSizePolicy(self.table.sizePolicy().horizontalPolicy(), self.table.sizePolicy().verticalPolicy())
        layout.addWidget(self.table)

    def load_data(self):
        rows = self.db.list_flea_markets(active_only=False)
        s = (self.search_edit.text() or "").strip().lower()
        if s:
            rows = [r for r in rows if s in str(r.get("platform_name", "")).lower()]
        cols = ["ID", "コード", "名称", "区分", "接頭辞", "有効", "備考"]
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("platform_code", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("platform_name", "")))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("category", "フリマ")))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("code_prefix", "")))
            self.table.setItem(i, 5, QTableWidgetItem("ON" if r.get("is_active", 1) else "OFF"))
            self.table.setItem(i, 6, QTableWidgetItem(r.get("notes", "")))
        reapply_table_column_widths(self.table)
        self.table.verticalHeader().setDefaultSectionSize(26)

    def _get_selected_id(self) -> Optional[int]:
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not sel:
            return None
        item = self.table.item(sel[0].row(), 0)
        try:
            return int(item.text()) if item else None
        except Exception:
            return None

    def _on_table_double_clicked(self, row: int, _column: int):
        if row < 0:
            return
        self.table.selectRow(row)
        self.edit_item()

    def add_item(self):
        d = FleaMarketEditDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        data = d.get_data()
        if not data.get("platform_code") or not data.get("platform_name") or not data.get("code_prefix"):
            QMessageBox.warning(self, "入力エラー", "コード・名称・接頭辞は必須です。")
            return
        if self.db.check_flea_market_code_exists(data["platform_code"]):
            QMessageBox.warning(self, "重複", "コードが重複しています。")
            return
        self.db.add_flea_market(data)
        self.load_data()

    def edit_item(self):
        mid = self._get_selected_id()
        if not mid:
            return
        row_data = self.db.get_flea_market(mid)
        if not row_data:
            return
        d = FleaMarketEditDialog(self, data=row_data)
        if d.exec() != QDialog.Accepted:
            return
        new_data = d.get_data()
        if self.db.check_flea_market_code_exists(new_data["platform_code"], exclude_id=mid):
            QMessageBox.warning(self, "重複", "コードが重複しています。")
            return
        self.db.update_flea_market(mid, new_data)
        self.load_data()

    def delete_item(self):
        mid = self._get_selected_id()
        if not mid:
            return
        if (
            QMessageBox.question(
                self,
                "確認",
                "選択したフリマを削除しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self.db.delete_flea_market(mid)
        self.load_data()


class OnlineStoreListWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("店舗名/コード/プラットフォームで検索...")
        self.search_edit.textChanged.connect(self.load_data)
        top.addWidget(self.search_edit)
        add_btn = QPushButton("追加"); add_btn.clicked.connect(self.add_item); top.addWidget(add_btn)
        edit_btn = QPushButton("編集"); edit_btn.clicked.connect(self.edit_item); top.addWidget(edit_btn)
        del_btn = QPushButton("削除"); del_btn.clicked.connect(self.delete_item); top.addWidget(del_btn)
        layout.addLayout(top)
        self.table = QTableWidget()
        self.table._hirio_table_column_settings_key = "table_column_widths/store_master/online_stores"
        self.table._hirio_table_column_legacy_keys = ["store_master/online_stores_column_widths"]
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        # セル直接編集は DB に保存されない（一覧は参照専用）。変更は「編集」または行ダブルクリック。
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_online_store_cell_double_clicked)
        self.table.setToolTip("内容の保存は「編集」ボタン、または行のダブルクリックで開くダイアログから行ってください。")
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.table, 1)

    def _on_online_store_cell_double_clicked(self, row: int, _col: int):
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.selectRow(row)
        self.edit_item()

    def load_data(self):
        rows = self.db.list_online_stores(search_term=(self.search_edit.text() or "").strip(), active_only=False)
        # 店舗一覧と同様に 店舗名の直後に 住所・電話番号
        cols = [
            "ID", "店舗コード", "店舗名", "住所", "電話番号",
            "プラットフォーム", "区分", "登録番号", "古物商許可番号", "有効", "備考",
        ]
        self.table.setRowCount(len(rows)); self.table.setColumnCount(len(cols)); self.table.setHorizontalHeaderLabels(cols)
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("supplier_code", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("shop_name", "")))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("address", "") or ""))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("phone", "") or ""))
            self.table.setItem(i, 5, QTableWidgetItem(r.get("platform_name", "")))
            self.table.setItem(i, 6, QTableWidgetItem(r.get("category", "")))
            self.table.setItem(i, 7, QTableWidgetItem(r.get("registration_number", "")))
            self.table.setItem(i, 8, QTableWidgetItem(r.get("secondhand_license_number", "") or ""))
            self.table.setItem(i, 9, QTableWidgetItem("ON" if r.get("is_active", 1) else "OFF"))
            self.table.setItem(i, 10, QTableWidgetItem(r.get("notes", "")))
        reapply_table_column_widths(self.table)
        self.table.verticalHeader().setDefaultSectionSize(26)

    def _get_selected_id(self) -> Optional[int]:
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not sel:
            return None
        item = self.table.item(sel[0].row(), 0)
        try:
            return int(item.text()) if item else None
        except Exception:
            return None

    def add_item(self):
        d = OnlineStoreEditDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        data = d.get_data()
        if not data.get("platform_id") or not data.get("supplier_code") or not data.get("shop_name"):
            QMessageBox.warning(self, "入力エラー", "プラットフォーム・店舗コード・店舗名は必須です。")
            return
        if self.db.check_online_store_code_exists(data["supplier_code"]):
            QMessageBox.warning(self, "重複", "店舗コードが重複しています。")
            return
        self.db.add_online_store(data)
        self.load_data()

    def edit_item(self):
        sid = self._get_selected_id()
        if not sid:
            return
        data = self.db.get_online_store(sid)
        if not data:
            return
        d = OnlineStoreEditDialog(self, data=data)
        if d.exec() != QDialog.Accepted:
            return
        new_data = d.get_data()
        if self.db.check_online_store_code_exists(new_data["supplier_code"], exclude_id=sid):
            QMessageBox.warning(self, "重複", "店舗コードが重複しています。")
            return
        self.db.update_online_store(sid, new_data)
        self.load_data()

    def delete_item(self):
        sid = self._get_selected_id()
        if not sid:
            return
        if QMessageBox.question(self, "確認", "選択した電脳店舗を削除しますか？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.db.delete_online_store(sid)
        self.load_data()


class WholesalerListWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("問屋名/コードで検索...")
        self.search_edit.textChanged.connect(self.load_data)
        top.addWidget(self.search_edit)
        add_btn = QPushButton("追加"); add_btn.clicked.connect(self.add_item); top.addWidget(add_btn)
        edit_btn = QPushButton("編集"); edit_btn.clicked.connect(self.edit_item); top.addWidget(edit_btn)
        del_btn = QPushButton("削除"); del_btn.clicked.connect(self.delete_item); top.addWidget(del_btn)
        layout.addLayout(top)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def load_data(self):
        rows = self.db.list_wholesalers(search_term=(self.search_edit.text() or "").strip(), active_only=False)
        cols = ["ID", "問屋コード", "問屋名", "登録番号", "有効", "備考"]
        self.table.setRowCount(len(rows)); self.table.setColumnCount(len(cols)); self.table.setHorizontalHeaderLabels(cols)
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("wholesaler_code", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("name", "")))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("registration_number", "")))
            self.table.setItem(i, 4, QTableWidgetItem("ON" if r.get("is_active", 1) else "OFF"))
            self.table.setItem(i, 5, QTableWidgetItem(r.get("notes", "")))
        reapply_table_column_widths(self.table)

    def _get_selected_id(self) -> Optional[int]:
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not sel:
            return None
        item = self.table.item(sel[0].row(), 0)
        try:
            return int(item.text()) if item else None
        except Exception:
            return None

    def add_item(self):
        d = WholesalerEditDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        data = d.get_data()
        if not data.get("wholesaler_code") or not data.get("name"):
            QMessageBox.warning(self, "入力エラー", "問屋コード・問屋名は必須です。")
            return
        if self.db.check_wholesaler_code_exists(data["wholesaler_code"]):
            QMessageBox.warning(self, "重複", "問屋コードが重複しています。")
            return
        self.db.add_wholesaler(data)
        self.load_data()

    def edit_item(self):
        wid = self._get_selected_id()
        if not wid:
            return
        data = self.db.get_wholesaler(wid)
        if not data:
            return
        d = WholesalerEditDialog(self, data=data)
        if d.exec() != QDialog.Accepted:
            return
        new_data = d.get_data()
        if self.db.check_wholesaler_code_exists(new_data["wholesaler_code"], exclude_id=wid):
            QMessageBox.warning(self, "重複", "問屋コードが重複しています。")
            return
        self.db.update_wholesaler(wid, new_data)
        self.load_data()

    def delete_item(self):
        wid = self._get_selected_id()
        if not wid:
            return
        if QMessageBox.question(self, "確認", "選択した問屋を削除しますか？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.db.delete_wholesaler(wid)
        self.load_data()
