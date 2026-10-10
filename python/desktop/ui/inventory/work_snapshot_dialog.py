#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作業スナップショットの呼び出しダイアログ。"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class WorkSnapshotPickDialog(QDialog):
    """保存済みスナップショットを選んで呼び出す。"""

    def __init__(
        self,
        snapshots: List[Dict[str, Any]],
        on_delete: Callable[[str], List[Dict[str, Any]]],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("スナップ呼出")
        self.resize(720, 420)
        self._on_delete = on_delete
        self._snapshots = list(snapshots)
        self._selected_id: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("呼び出したいスナップショットを選んでください。"))

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["保存名", "件数", "保存日時"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_load)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.delete_btn = QPushButton("削除")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        buttons.addWidget(self.delete_btn)
        buttons.addStretch()
        box = QDialogButtonBox()
        self.load_btn = QPushButton("呼び出す")
        self.cancel_btn = QPushButton("キャンセル")
        box.addButton(self.load_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(self.cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        self.load_btn.clicked.connect(self._on_load)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)
        self._reload_table()

    def _reload_table(self) -> None:
        self.table.setRowCount(len(self._snapshots))
        for row, snap in enumerate(self._snapshots):
            name_item = QTableWidgetItem(str(snap.get("name") or ""))
            name_item.setData(Qt.ItemDataRole.UserRole, str(snap.get("id") or ""))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(snap.get("item_count") or 0)))
            self.table.setItem(row, 2, QTableWidgetItem(str(snap.get("created_at") or "")))
        self.table.resizeColumnsToContents()
        if self._snapshots:
            self.table.selectRow(0)

    def _current_id(self) -> Optional[str]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        snap_id = item.data(Qt.ItemDataRole.UserRole)
        return str(snap_id) if snap_id else None

    def _on_load(self) -> None:
        snap_id = self._current_id()
        if not snap_id:
            QMessageBox.information(self, "スナップ呼出", "呼び出す行を選んでください。")
            return
        self._selected_id = snap_id
        self.accept()

    def _on_delete_clicked(self) -> None:
        snap_id = self._current_id()
        if not snap_id:
            QMessageBox.information(self, "削除", "削除する行を選んでください。")
            return
        reply = QMessageBox.question(
            self,
            "削除",
            "選んだスナップショットを削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._snapshots = list(self._on_delete(snap_id) or [])
        self._reload_table()

    def selected_id(self) -> Optional[str]:
        return self._selected_id
