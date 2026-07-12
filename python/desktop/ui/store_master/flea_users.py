#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマユーザーマスタ。"""
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


class FleaMarketUserEditDialog(QDialog):
    """フリマ常連ユーザー 追加・編集ダイアログ。

    - プラットフォーム名は flea_markets テーブルの名称をプルダウン表示
      （内部的には platform_code を保持。表示はユーザーが分かりやすい platform_name）
    - 固有ID/URL は任意。ユーザー名は必須。
    """

    def __init__(self, parent=None, data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.db = StoreDatabase()
        self.data = data
        # id があるときのみ「編集」。入力画面からの下書きプリフィルは data ありでも「追加」。
        self.setWindowTitle(
            "フリマユーザー編集" if (data and data.get("id")) else "フリマユーザー追加"
        )
        self.setModal(True)
        self._build_ui()
        self._load_platforms()
        if data:
            self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # プラットフォーム（プルダウン: flea_markets の名称）
        self.platform_combo = QComboBox()
        self.platform_combo.setMinimumWidth(220)
        self.platform_combo.setToolTip(
            "「設定 > 店舗コード設定 > フリマコード」で登録した名称が表示されます。"
        )
        form.addRow("プラットフォーム名:", self.platform_combo)

        # ユーザー名
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("例: hirio_user")
        form.addRow("ユーザー名:", self.username_edit)

        # 固有ID / URL
        self.unique_id_edit = QLineEdit()
        self.unique_id_edit.setPlaceholderText(
            "例: ユーザーページのURL や プラットフォーム内の固有ID"
        )
        form.addRow("固有ID / URL:", self.unique_id_edit)

        # 評価数（ランク選択）
        self.rating_combo = QComboBox()
        for t in FLEA_MARKET_USER_RATING_TIERS:
            self.rating_combo.addItem(t)
        form.addRow("評価数:", self.rating_combo)

        # 本人確認済み
        self.identity_check = QCheckBox("本人確認済み")
        form.addRow("本人確認:", self.identity_check)

        # 備考
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("メモ（任意）")
        form.addRow("備考:", self.notes_edit)

        layout.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _load_platforms(self):
        """フリマプラットフォーム一覧を読み込んでコンボへ反映。"""
        self.platform_combo.blockSignals(True)
        self.platform_combo.clear()
        rows = self.db.list_flea_markets(active_only=False)
        if not rows:
            self.platform_combo.addItem("(未登録)", "")
        else:
            for r in rows:
                name = r.get("platform_name", "")
                code = r.get("platform_code", "")
                self.platform_combo.addItem(name, code)
        self.platform_combo.blockSignals(False)

    def _load_data(self):
        if not self.data:
            return
        # プラットフォーム選択を復元（code で照合）
        code = (self.data.get("platform_code") or "").strip().upper()
        idx = -1
        for i in range(self.platform_combo.count()):
            if (self.platform_combo.itemData(i) or "").upper() == code:
                idx = i
                break
        if idx < 0 and self.data.get("platform_name"):
            # 名称で再検索（コードが変わっている場合の救済）
            name = self.data.get("platform_name") or ""
            for i in range(self.platform_combo.count()):
                if self.platform_combo.itemText(i) == name:
                    idx = i
                    break
        if idx >= 0:
            self.platform_combo.setCurrentIndex(idx)
        self.username_edit.setText(self.data.get("username", ""))
        self.unique_id_edit.setText(self.data.get("unique_id", ""))
        tier = self.data.get("rating_tier") or ""
        if tier:
            tier_idx = self.rating_combo.findText(tier)
            if tier_idx >= 0:
                self.rating_combo.setCurrentIndex(tier_idx)
        self.identity_check.setChecked(bool(self.data.get("identity_verified", 0)))
        self.notes_edit.setText(self.data.get("notes", ""))

    def _on_accept(self):
        # 簡易バリデーション
        if not self.platform_combo.currentData():
            QMessageBox.warning(
                self,
                "入力エラー",
                "プラットフォームが選択されていません。\n"
                "「設定 > 店舗コード設定 > フリマコード」でフリマを登録してください。",
            )
            return
        if not self.username_edit.text().strip():
            QMessageBox.warning(self, "入力エラー", "ユーザー名は必須です。")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return {
            "platform_code": (self.platform_combo.currentData() or "").strip().upper(),
            "platform_name": self.platform_combo.currentText().strip(),
            "username": self.username_edit.text().strip(),
            "unique_id": self.unique_id_edit.text().strip(),
            "rating_tier": self.rating_combo.currentText().strip(),
            "identity_verified": 1 if self.identity_check.isChecked() else 0,
            "notes": self.notes_edit.text().strip(),
        }


class FleaMarketUserListWidget(QWidget):
    """フリマ常連ユーザー一覧（データベース管理 > 店舗マスタ > フリマユーザー一覧）。"""

    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 説明ラベル
        info_label = QLabel(
            "フリマで複数回取引したユーザーをここに登録しておくと、"
            "仕入データ入力時に自動補完できるようになります。"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #aaaaaa; padding: 2px 0px;")
        layout.addWidget(info_label)

        # 上段：検索 + プラットフォーム絞り込み + 操作ボタン
        top = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("ユーザー名 / 固有ID / 備考 で検索...")
        self.search_edit.textChanged.connect(self.load_data)
        top.addWidget(self.search_edit, 2)

        self.platform_filter_combo = QComboBox()
        self.platform_filter_combo.setMinimumWidth(180)
        self.platform_filter_combo.currentIndexChanged.connect(self.load_data)
        top.addWidget(self.platform_filter_combo, 1)

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

        # テーブル
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.table, 1)

        self._reload_platform_filter()

    def _reload_platform_filter(self):
        """プラットフォーム絞り込みコンボを再構築。"""
        self.platform_filter_combo.blockSignals(True)
        self.platform_filter_combo.clear()
        self.platform_filter_combo.addItem("全プラットフォーム", "")
        rows = self.db.list_flea_markets(active_only=False)
        for r in rows:
            self.platform_filter_combo.addItem(
                r.get("platform_name", ""), r.get("platform_code", "")
            )
        self.platform_filter_combo.blockSignals(False)

    def load_data(self):
        platform_code = self.platform_filter_combo.currentData() or ""
        keyword = (self.search_edit.text() or "").strip()
        try:
            rows = self.db.list_flea_market_users(
                platform_code=platform_code or None,
                search=keyword or None,
            )
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"一覧の読み込みに失敗しました:\n{e}")
            rows = []

        cols = [
            "ID", "プラットフォーム", "ユーザー名", "固有ID / URL",
            "評価数", "本人確認", "備考",
        ]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("platform_name", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("username", "")))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("unique_id", "") or ""))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("rating_tier", "") or ""))
            verified = bool(r.get("identity_verified", 0))
            self.table.setItem(i, 5, QTableWidgetItem("✓" if verified else ""))
            self.table.setItem(i, 6, QTableWidgetItem(r.get("notes", "") or ""))

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
        # プラットフォームが1件もない場合は事前に注意
        if not self.db.list_flea_markets(active_only=False):
            QMessageBox.information(
                self,
                "プラットフォーム未登録",
                "フリマプラットフォームが未登録です。\n"
                "「設定 > 店舗コード設定 > フリマコード」から先に登録してください。",
            )
            return
        d = FleaMarketUserEditDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        try:
            self.db.add_flea_market_user(d.get_data())
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"追加に失敗しました:\n{e}")
            return
        self._reload_platform_filter()
        self.load_data()

    def edit_item(self):
        uid = self._get_selected_id()
        if not uid:
            QMessageBox.information(self, "選択", "編集する行を選択してください。")
            return
        row_data = self.db.get_flea_market_user(uid)
        if not row_data:
            return
        d = FleaMarketUserEditDialog(self, data=row_data)
        if d.exec() != QDialog.Accepted:
            return
        try:
            self.db.update_flea_market_user(uid, d.get_data())
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"更新に失敗しました:\n{e}")
            return
        self.load_data()

    def delete_item(self):
        uid = self._get_selected_id()
        if not uid:
            QMessageBox.information(self, "選択", "削除する行を選択してください。")
            return
        if (
            QMessageBox.question(
                self,
                "確認",
                "選択したフリマユーザーを削除しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            self.db.delete_flea_market_user(uid)
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"削除に失敗しました:\n{e}")
            return
        self.load_data()

    def showEvent(self, event):
        """タブが表示されるたびにプラットフォーム一覧を最新化（設定タブで追加した内容を即反映）。"""
        super().showEvent(event)
        try:
            current_code = self.platform_filter_combo.currentData() or ""
            self._reload_platform_filter()
            # 元の選択を維持
            idx = -1
            for i in range(self.platform_filter_combo.count()):
                if (self.platform_filter_combo.itemData(i) or "") == current_code:
                    idx = i
                    break
            if idx >= 0:
                self.platform_filter_combo.setCurrentIndex(idx)
            self.load_data()
        except Exception:
            pass
