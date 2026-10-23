#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ネット仕入のスタンバイ画面。

Discord 審査通過 →（Webで購入入力）→ ここに表示 → ネット仕入一覧へ送る。
購入済みだけを表示し、チェックした複数件をまとめて送れる。
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

# 列: 0=チェック, 1=状態, 2=日時, 3=商品名, 4=仕入, 5=販売予定, 6=粗利
_COL_CHECK = 0


class HitStandbyDialog(QDialog):
    """Discord仕入れ候補のスタンバイ一覧（購入済みのみ）。"""

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
            "購入入力済みの候補だけを表示します。"
            "チェックした商品を「チェックした商品を仕入一覧に送る」でまとめて送れます"
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

        check_row = QHBoxLayout()
        self.select_all_btn = QPushButton("未送信を全選択")
        self.select_all_btn.setToolTip("まだ送っていない購入済みにチェックを付けます")
        self.select_all_btn.clicked.connect(self._select_all_unsent)
        check_row.addWidget(self.select_all_btn)
        self.clear_check_btn = QPushButton("チェック解除")
        self.clear_check_btn.clicked.connect(self._clear_checks)
        check_row.addWidget(self.clear_check_btn)
        check_row.addStretch()
        left_layout.addLayout(check_row)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["", "状態", "日時", "商品名", "仕入", "販売予定", "粗利"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
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

        self.send_btn = QPushButton("チェックした商品を仕入一覧に送る")
        self.send_btn.setToolTip(
            "チェックした購入済み候補を、ネット仕入一覧のうしろへまとめて足します。"
        )
        self.send_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; "
            "padding: 8px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1b5e20; }"
            "QPushButton:disabled { background-color: #555; color: #aaa; }"
        )
        self.send_btn.clicked.connect(self._send_checked)
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
            # 購入入力済みだけ（未購入スナップショットは出さない）
            self._items = load_standby_items(include_pending=False)
        except Exception as exc:  # noqa: BLE001
            self._items = []
            QMessageBox.warning(self, "スタンバイ", f"読込に失敗しました:\n{exc}")
        self._fill_table()

    def _fill_table(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._items))
            for row, item in enumerate(self._items):
                imported = bool(item.get("imported"))
                status = "送済" if imported else "購入済"

                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                # 送済はチェック不可（再送防止）
                if imported:
                    check.setFlags(Qt.ItemFlag.ItemIsSelectable)
                    check.setCheckState(Qt.CheckState.Unchecked)
                else:
                    check.setCheckState(Qt.CheckState.Unchecked)
                check.setData(Qt.ItemDataRole.UserRole, row)
                self.table.setItem(row, _COL_CHECK, check)

                values = [
                    status,
                    str(item.get("at") or "")[:19],
                    (str(item.get("title") or ""))[:60],
                    f"{int(item['buy_yen']):,}円"
                    if isinstance(item.get("buy_yen"), int)
                    else "-",
                    f"{int(item['sell_yen']):,}円"
                    if isinstance(item.get("sell_yen"), int)
                    else "-",
                    f"{int(item['profit_yen']):,}円"
                    if isinstance(item.get("profit_yen"), int)
                    else "-",
                ]
                for col, text in enumerate(values, start=1):
                    cell = QTableWidgetItem(text)
                    cell.setData(Qt.ItemDataRole.UserRole, row)
                    self.table.setItem(row, col, cell)
            self.table.resizeColumnsToContents()
            self.table.setColumnWidth(_COL_CHECK, 36)
            if self._items:
                self.table.selectRow(0)
        finally:
            self.table.blockSignals(False)

        if self._items:
            self._show_item(0)
        else:
            self._clear_detail()
        self._update_send_btn()

    def _clear_detail(self) -> None:
        self._current = None
        self.detail_title.setText("（行を選んでください）")
        self.detail_meta.setText("")
        self.open_url_btn.setEnabled(False)
        self._set_thumbs([])

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item is not None and item.column() == _COL_CHECK:
            self._update_send_btn()

    def _on_cell_clicked(self, row: int, column: int) -> None:
        # チェック列クリック時はトグル（送済以外）
        if column == _COL_CHECK:
            cell = self.table.item(row, _COL_CHECK)
            if cell is not None and (cell.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                self.table.blockSignals(True)
                try:
                    if cell.checkState() == Qt.CheckState.Checked:
                        cell.setCheckState(Qt.CheckState.Unchecked)
                    else:
                        cell.setCheckState(Qt.CheckState.Checked)
                finally:
                    self.table.blockSignals(False)
                self._update_send_btn()
        self._show_item(row)

    def _on_select(self) -> None:
        idx = self.table.currentRow()
        if idx < 0:
            model = self.table.selectionModel()
            rows = model.selectedRows() if model is not None else []
            if not rows:
                self._clear_detail()
                return
            idx = rows[0].row()
        self._show_item(idx)

    def _show_item(self, idx: int) -> None:
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
        margin_txt = (
            f"{float(margin) * 100:.1f}%" if isinstance(margin, (int, float)) else "-"
        )
        if item.get("imported"):
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
        self._set_thumbs(list(item.get("image_files") or []))

    def _checked_rows(self) -> List[int]:
        rows: List[int] = []
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, _COL_CHECK)
            if cell is None:
                continue
            if cell.checkState() == Qt.CheckState.Checked:
                rows.append(row)
        return rows

    def _update_send_btn(self) -> None:
        n = len(self._checked_rows())
        self.send_btn.setEnabled(n > 0)
        if n > 0:
            self.send_btn.setText(f"チェックした商品を仕入一覧に送る（{n}件）")
        else:
            self.send_btn.setText("チェックした商品を仕入一覧に送る")

    def _select_all_unsent(self) -> None:
        self.table.blockSignals(True)
        try:
            for row, item in enumerate(self._items):
                cell = self.table.item(row, _COL_CHECK)
                if cell is None:
                    continue
                if item.get("imported"):
                    cell.setCheckState(Qt.CheckState.Unchecked)
                    continue
                if cell.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    cell.setCheckState(Qt.CheckState.Checked)
        finally:
            self.table.blockSignals(False)
        self._update_send_btn()

    def _clear_checks(self) -> None:
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                cell = self.table.item(row, _COL_CHECK)
                if cell is not None:
                    cell.setCheckState(Qt.CheckState.Unchecked)
        finally:
            self.table.blockSignals(False)
        self._update_send_btn()

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

    def _send_checked(self) -> None:
        rows = self._checked_rows()
        if not rows:
            QMessageBox.information(
                self, "スタンバイ", "送る商品にチェックを付けてください。"
            )
            return

        ok_count = 0
        skip: List[str] = []
        errors: List[str] = []
        for row in rows:
            if row < 0 or row >= len(self._items):
                continue
            item = self._items[row]
            title = (str(item.get("title") or "")[:40]) or "(無題)"
            if item.get("imported"):
                skip.append(f"{title}（送済）")
                continue
            asin = str(item.get("asin") or "").strip()
            if not asin:
                skip.append(f"{title}（ASINなし）")
                continue
            try:
                inv_row = purchase_to_inventory_row(item)
                self._on_send_row(inv_row)
                mark_imported(str(item.get("token") or ""))
                item["imported"] = True
                ok_count += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{title}: {exc}")

        self._fill_table()

        parts = [f"{ok_count} 件をネット仕入一覧に送りました。"]
        if skip:
            parts.append("スキップ: " + " / ".join(skip[:8]))
            if len(skip) > 8:
                parts.append(f"ほか {len(skip) - 8} 件")
        if errors:
            parts.append("失敗: " + " / ".join(errors[:5]))
        if ok_count > 0 and not errors:
            QMessageBox.information(self, "スタンバイ", "\n".join(parts))
        elif ok_count > 0:
            QMessageBox.warning(self, "スタンバイ", "\n".join(parts))
        else:
            QMessageBox.warning(
                self,
                "スタンバイ",
                "送れる商品がありませんでした。\n" + "\n".join(parts[1:]),
            )
