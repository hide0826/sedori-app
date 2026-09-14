#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗タグマスタ管理ダイアログ（複数タグ対応）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
    QGroupBox,
)

from database.store_db import StoreDatabase


class StoreTagEditDialog(QDialog):
    """タグ1件の追加・編集。"""

    def __init__(self, parent=None, tag_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.tag_data = tag_data or {}
        self.setWindowTitle("タグ編集" if tag_data else "タグ追加")
        self.setModal(True)
        self._color = (self.tag_data.get("color") or "#1976d2").strip() or "#1976d2"
        self._setup_ui()
        if tag_data:
            self._load()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: 大型店舗")
        form.addRow("タグ名:", self.name_edit)

        color_row = QHBoxLayout()
        self.color_btn = QPushButton("色を選ぶ")
        self.color_btn.clicked.connect(self._pick_color)
        self.color_preview = QLabel("  ")
        self.color_preview.setFixedWidth(36)
        self._apply_color_preview()
        color_row.addWidget(self.color_preview)
        color_row.addWidget(self.color_btn)
        color_row.addStretch()
        form.addRow("色:", color_row)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 9999)
        self.priority_spin.setValue(100)
        self.priority_spin.setToolTip(
            "小さいほど優先（複数タグ時のピン色に使います）"
        )
        form.addRow("優先度:", self.priority_spin)

        self.order_spin = QSpinBox()
        self.order_spin.setRange(0, 9999)
        self.order_spin.setValue(0)
        form.addRow("表示順:", self.order_spin)

        self.active_check = QCheckBox("有効")
        self.active_check.setChecked(True)
        form.addRow("状態:", self.active_check)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_color_preview(self) -> None:
        self.color_preview.setStyleSheet(
            f"background-color: {self._color}; border: 1px solid #555; border-radius: 3px;"
        )
        self.color_preview.setToolTip(self._color)

    def _pick_color(self) -> None:
        initial = QColor(self._color)
        chosen = QColorDialog.getColor(initial, self, "タグ色を選択")
        if chosen.isValid():
            self._color = chosen.name()
            self._apply_color_preview()

    def _load(self) -> None:
        self.name_edit.setText(str(self.tag_data.get("name") or ""))
        self._color = (self.tag_data.get("color") or "#1976d2").strip() or "#1976d2"
        self._apply_color_preview()
        try:
            self.priority_spin.setValue(int(self.tag_data.get("priority") or 100))
        except (TypeError, ValueError):
            self.priority_spin.setValue(100)
        try:
            self.order_spin.setValue(int(self.tag_data.get("display_order") or 0))
        except (TypeError, ValueError):
            self.order_spin.setValue(0)
        self.active_check.setChecked(bool(self.tag_data.get("is_active", 1)))

    def get_data(self) -> Dict[str, Any]:
        return {
            "name": self.name_edit.text().strip(),
            "color": self._color,
            "priority": self.priority_spin.value(),
            "display_order": self.order_spin.value(),
            "is_active": 1 if self.active_check.isChecked() else 0,
        }

    def accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "警告", "タグ名を入力してください。")
            return
        super().accept()


class StoreTagsDialog(QDialog):
    """店舗タグマスタ一覧。"""

    def __init__(self, parent=None, db: Optional[StoreDatabase] = None):
        super().__init__(parent)
        self.db = db or StoreDatabase()
        self.setWindowTitle("店舗タグ管理")
        self.setModal(True)
        self.resize(720, 420)
        self._setup_ui()
        self.reload()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        info = QLabel(
            "店舗には複数のタグを付けられます。\n"
            "地図のピン色は、付いたタグのうち優先度が最も高い（数値が小さい）色を使います。\n"
            "ブランド系（BOOKOFF／セカンドストリート／ハードオフ／トレジャーファクトリー／その他）は"
            "店名から自動判別できます。評価系タグ（大型店舗など）とは分けて使えます。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        group = QGroupBox("タグ一覧")
        group_layout = QVBoxLayout(group)
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        cols = ["ID", "タグ名", "色", "優先度", "表示順", "状態"]
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        group_layout.addWidget(self.table)
        layout.addWidget(group)

        buttons = QHBoxLayout()
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_tag)
        buttons.addWidget(add_btn)
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self.edit_tag)
        buttons.addWidget(edit_btn)
        delete_btn = QPushButton("削除")
        delete_btn.setStyleSheet(
            "QPushButton { background-color: #dc3545; color: white; padding: 8px 16px; border-radius: 4px; }"
        )
        delete_btn.clicked.connect(self.delete_tag)
        buttons.addWidget(delete_btn)

        auto_btn = QPushButton("既存店舗へブランド自動付与")
        auto_btn.setToolTip(
            "全店舗の店名から BOOKOFF／セカンドストリート／ハードオフ／"
            "トレジャーファクトリー／その他 を判別して付与します。\n"
            "すでに店舗種別タグがある店舗は付け直します（評価系は残します）。"
        )
        auto_btn.clicked.connect(self.auto_apply_brand_tags)
        buttons.addWidget(auto_btn)

        buttons.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def reload(self) -> None:
        tags = self.db.list_store_tags(active_only=False)
        self.table.setRowCount(len(tags))
        for i, tag in enumerate(tags):
            self.table.setItem(i, 0, QTableWidgetItem(str(tag.get("id") or "")))
            self.table.setItem(i, 1, QTableWidgetItem(str(tag.get("name") or "")))
            color = str(tag.get("color") or "#1976d2").strip() or "#1976d2"
            # 色列はスウォッチ表示（コードはツールチップ）
            placeholder = QTableWidgetItem("")
            placeholder.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            placeholder.setData(Qt.UserRole, color)
            self.table.setItem(i, 2, placeholder)
            swatch = QLabel()
            swatch.setFixedHeight(22)
            swatch.setMinimumWidth(56)
            swatch.setAlignment(Qt.AlignCenter)
            swatch.setToolTip(f"色: {color}")
            swatch.setStyleSheet(
                f"background-color: {color}; border: 1px solid #888; "
                f"border-radius: 4px; margin: 2px;"
            )
            self.table.setCellWidget(i, 2, swatch)
            self.table.setItem(i, 3, QTableWidgetItem(str(tag.get("priority") or "")))
            self.table.setItem(i, 4, QTableWidgetItem(str(tag.get("display_order") or "")))
            active = "有効" if tag.get("is_active", 1) else "無効"
            self.table.setItem(i, 5, QTableWidgetItem(active))
            self.table.item(i, 0).setData(Qt.UserRole, tag)
        self.table.setColumnWidth(2, 72)

    def auto_apply_brand_tags(self) -> None:
        try:
            from services.store_brand_tag_service import (
                apply_brand_tags_to_all_stores,
                ensure_brand_store_tags,
            )
        except Exception:
            try:
                from store_brand_tag_service import (  # type: ignore
                    apply_brand_tags_to_all_stores,
                    ensure_brand_store_tags,
                )
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"自動付与モジュールを読めません:\n{e}")
                return

        reply = QMessageBox.question(
            self,
            "ブランドタグ自動付与",
            "全店舗の店名から店舗種別タグを自動付与します。\n"
            "（BOOKOFF／セカンドストリート／ハードオフ／トレジャーファクトリー／その他）\n\n"
            "既存の店舗種別は店名に合わせて付け直します。\n"
            "大型店舗などの評価系タグはそのまま残ります。\n"
            "続行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            ensure_brand_store_tags(self.db)
            result = apply_brand_tags_to_all_stores(
                self.db, replace_existing_brand=True
            )
            self.reload()
            QMessageBox.information(
                self,
                "完了",
                f"調査: {result['scanned']} 件\n"
                f"付与・更新: {result['updated']} 件\n"
                f"スキップ: {result['skipped']} 件",
            )
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"自動付与に失敗しました:\n{e}")

    def _selected_tag(self) -> Optional[Dict[str, Any]]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if not item:
            return None
        data = item.data(Qt.UserRole)
        return data if isinstance(data, dict) else None

    def add_tag(self) -> None:
        dialog = StoreTagEditDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.db.add_store_tag(dialog.get_data())
            self.reload()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{e}")

    def edit_tag(self) -> None:
        tag = self._selected_tag()
        if not tag:
            QMessageBox.warning(self, "警告", "編集するタグを選択してください。")
            return
        dialog = StoreTagEditDialog(self, tag_data=tag)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.db.update_store_tag(int(tag["id"]), dialog.get_data())
            self.reload()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{e}")

    def delete_tag(self) -> None:
        tag = self._selected_tag()
        if not tag:
            QMessageBox.warning(self, "警告", "削除するタグを選択してください。")
            return
        reply = QMessageBox.question(
            self,
            "確認",
            f"タグ「{tag.get('name')}」を削除しますか？\n店舗への紐付けも外れます。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.db.delete_store_tag(int(tag["id"]))
            self.reload()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{e}")
