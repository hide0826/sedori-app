#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ネット仕入のスタンバイ画面。

Discord 審査通過 →（Webで購入入力）→ ここに表示 → ネット仕入一覧へ送る。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from services.hit_standby import (
        load_standby_items,
        mark_imported,
        purchase_to_inventory_row,
        resolve_hirio_shared_dir,
    )
except ImportError:
    from desktop.services.hit_standby import (  # type: ignore
        load_standby_items,
        mark_imported,
        purchase_to_inventory_row,
        resolve_hirio_shared_dir,
    )


class HitStandbyDialog(QDialog):
    """Discord仕入れ候補のスタンバイ一覧。"""

    def __init__(
        self,
        *,
        on_send_row: Callable[[Dict[str, Any]], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("スタンバイ（Discord仕入れ候補）")
        self.resize(980, 640)
        self._on_send_row = on_send_row
        self._items: List[Dict[str, Any]] = []
        self._current: Optional[Dict[str, Any]] = None

        root = QVBoxLayout(self)
        shared = resolve_hirio_shared_dir()
        self.hint = QLabel(
            "Discordで審査を通った候補です。"
            "購入入力済みの行を選んで「仕入一覧に送る」と、ネット仕入一覧へ足します"
            "（出品CSV生成できる形式）。\n"
            f"データ場所: {shared}"
        )
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["状態", "日時", "商品名", "仕入", "販売予定", "粗利"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_select)
        left_layout.addWidget(self.table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.detail_title = QLabel("（行を選んでください）")
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        right_layout.addWidget(self.detail_title)

        self.detail_meta = QLabel("")
        self.detail_meta.setWordWrap(True)
        self.detail_meta.setStyleSheet("color: #9aa8c0;")
        right_layout.addWidget(self.detail_meta)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.thumbs_host = QWidget()
        self.thumbs_layout = QHBoxLayout(self.thumbs_host)
        self.thumbs_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.thumbs_host)
        scroll.setMinimumHeight(140)
        right_layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        self.open_url_btn = QPushButton("商品ページを開く")
        self.open_url_btn.clicked.connect(self._open_url)
        self.open_url_btn.setEnabled(False)
        btn_row.addWidget(self.open_url_btn)

        self.send_btn = QPushButton("仕入一覧に送る")
        self.send_btn.setToolTip(
            "選んだ購入済み候補を、ネット仕入一覧のうしろへ1件足します。"
            "出品CSV生成と同じ列形式です。"
        )
        self.send_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; "
            "padding: 8px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1b5e20; }"
            "QPushButton:disabled { background-color: #555; color: #aaa; }"
        )
        self.send_btn.clicked.connect(self._send_current)
        self.send_btn.setEnabled(False)
        btn_row.addWidget(self.send_btn)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)
        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([560, 420])

        bottom = QHBoxLayout()
        self.refresh_btn = QPushButton("再読込")
        self.refresh_btn.clicked.connect(self.reload)
        bottom.addWidget(self.refresh_btn)
        bottom.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self.reload()

    def reload(self) -> None:
        try:
            self._items = load_standby_items()
        except Exception as exc:  # noqa: BLE001
            self._items = []
            QMessageBox.warning(self, "スタンバイ", f"読込に失敗しました:\n{exc}")
        self._fill_table()
        self._clear_detail()

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            kind = str(item.get("kind") or "")
            imported = bool(item.get("imported"))
            if kind == "pending":
                status = "未購入"
            elif imported:
                status = "送済"
            else:
                status = "購入済"

            def _cell(text: str) -> QTableWidgetItem:
                cell = QTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, row)
                return cell

            self.table.setItem(row, 0, _cell(status))
            self.table.setItem(row, 1, _cell(str(item.get("at") or "")[:19]))
            self.table.setItem(row, 2, _cell((str(item.get("title") or ""))[:60]))
            buy = item.get("buy_yen")
            sell = item.get("sell_yen")
            profit = item.get("profit_yen")
            self.table.setItem(
                row, 3, _cell(f"{int(buy):,}円" if isinstance(buy, int) else "-")
            )
            self.table.setItem(
                row, 4, _cell(f"{int(sell):,}円" if isinstance(sell, int) else "-")
            )
            self.table.setItem(
                row, 5, _cell(f"{int(profit):,}円" if isinstance(profit, int) else "-")
            )
        self.table.resizeColumnsToContents()
        if self._items:
            self.table.selectRow(0)

    def _clear_detail(self) -> None:
        self._current = None
        self.detail_title.setText("（行を選んでください）")
        self.detail_meta.setText("")
        self.open_url_btn.setEnabled(False)
        self.send_btn.setEnabled(False)
        self._set_thumbs([])

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            self._clear_detail()
            return
        idx = rows[0].row()
        if idx < 0 or idx >= len(self._items):
            self._clear_detail()
            return
        item = self._items[idx]
        self._current = item
        self.detail_title.setText(str(item.get("title") or "(無題)"))
        buy = item.get("buy_yen")
        sell = item.get("sell_yen")
        profit = item.get("profit_yen")
        margin = item.get("margin_rate")
        margin_txt = f"{float(margin) * 100:.1f}%" if isinstance(margin, (int, float)) else "-"
        kind = item.get("kind")
        if kind == "pending":
            status = "未購入（Webの購入ボタンで金額を入れてください）"
        elif item.get("imported"):
            status = "ネット仕入へ送済"
        else:
            status = "購入済・未送信"
        buy_txt = f"{buy:,}円" if isinstance(buy, int) else "-"
        sell_txt = f"{sell:,}円" if isinstance(sell, int) else "-"
        profit_txt = f"{profit:,}円（{margin_txt}）" if isinstance(profit, int) else "-"
        self.detail_meta.setText(
            f"状態: {status}\n"
            f"ASIN: {item.get('asin') or '-'}　KW: {item.get('keyword') or '-'}\n"
            f"仕入: {buy_txt}　販売予定: {sell_txt}　粗利: {profit_txt}\n"
            f"{item.get('fee_note') or ''}"
        )
        self.open_url_btn.setEnabled(bool(str(item.get("url") or "").strip()))
        can_send = kind == "purchased" and not bool(item.get("imported"))
        self.send_btn.setEnabled(can_send)
        self._set_thumbs(list(item.get("image_files") or []))

    def _set_thumbs(self, paths: List[Path]) -> None:
        while self.thumbs_layout.count():
            child = self.thumbs_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
        for path in paths[:5]:
            label = QLabel()
            label.setFixedSize(110, 110)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "background:#1a2438; border:1px solid #2a3650; border-radius:8px;"
            )
            pix = QPixmap(str(path))
            if not pix.isNull():
                label.setPixmap(
                    pix.scaled(
                        110,
                        110,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                label.setText("画像")
            self.thumbs_layout.addWidget(label)
        self.thumbs_layout.addStretch()

    def _open_url(self) -> None:
        if not self._current:
            return
        url = str(self._current.get("url") or "").strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _send_current(self) -> None:
        item = self._current
        if not item:
            return
        if item.get("kind") != "purchased":
            QMessageBox.information(
                self,
                "スタンバイ",
                "未購入の候補は送れません。先に Discord の「購入した」から金額を保存してください。",
            )
            return
        if item.get("imported"):
            QMessageBox.information(self, "スタンバイ", "この候補はすでに送済みです。")
            return
        asin = str(item.get("asin") or "").strip()
        if not asin:
            QMessageBox.warning(self, "スタンバイ", "ASIN が無いため送れません。")
            return
        try:
            row = purchase_to_inventory_row(item)
            self._on_send_row(row)
            mark_imported(str(item.get("token") or ""))
            item["imported"] = True
            self._fill_table()
            # 同じ行を再選択
            for i, it in enumerate(self._items):
                if it.get("token") == item.get("token"):
                    self.table.selectRow(i)
                    break
            QMessageBox.information(
                self,
                "スタンバイ",
                "ネット仕入一覧に1件送りました。出品CSV生成が使えます。",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "スタンバイ", f"送信に失敗しました:\n{exc}")
