#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入DB未登録SKU一覧（在庫CSVから抽出）"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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

try:
    from desktop.services.purchase_inventory_only import (
        PURCHASE_STATUS_INVENTORY_ONLY_LABEL,
        register_inventory_only_row,
        save_pending_missing_list,
    )
except ImportError:
    from services.purchase_inventory_only import (  # type: ignore
        PURCHASE_STATUS_INVENTORY_ONLY_LABEL,
        register_inventory_only_row,
        save_pending_missing_list,
    )


class InventoryOnlySkusDialog(QDialog):
    def __init__(
        self,
        missing_rows: List[Dict[str, Any]],
        *,
        purchase_db: Any,
        product_widget: Optional[Any] = None,
        repricer_widget: Optional[Any] = None,
        csv_path: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._rows = list(missing_rows)
        self._purchase_db = purchase_db
        self._product_widget = product_widget
        self._repricer_widget = repricer_widget
        self._csv_path = csv_path
        self.setWindowTitle(f"仕入DB未登録SKU（{len(self._rows)}件）")
        self.setMinimumSize(640, 360)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        hint = QLabel(
            "在庫CSVにあって仕入DBに無い SKU、または ASIN が未入力の SKU です。\n"
            f"「{PURCHASE_STATUS_INVENTORY_ONLY_LABEL}」として登録すると、在庫CSVの内容で上書きされます。\n"
            "月別運用・個別改定ルールもあとから設定できます。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["SKU", "ASIN", "商品名", "仕入れ価格", "販売予定価格", "見込み利益"]
        )
        self._table.setRowCount(len(self._rows))
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        for i, row in enumerate(self._rows):
            self._table.setItem(i, 0, QTableWidgetItem(str(row.get("SKU") or row.get("sku") or "")))
            self._table.setItem(i, 1, QTableWidgetItem(str(row.get("ASIN") or row.get("asin") or "")))
            title = str(row.get("商品名") or row.get("title") or "")
            if len(title) > 60:
                title = title[:60] + "..."
            self._table.setItem(i, 2, QTableWidgetItem(title))
            self._table.setItem(i, 3, QTableWidgetItem(str(row.get("cost") or row.get("仕入れ価格") or "")))
            self._table.setItem(i, 4, QTableWidgetItem(str(row.get("price") or row.get("販売予定価格") or "")))
            self._table.setItem(i, 5, QTableWidgetItem(str(row.get("profit") or row.get("見込み利益") or "")))
        self._table.resizeColumnsToContents()
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        register_all_btn = QPushButton("すべて在庫専用として登録・上書き")
        register_all_btn.clicked.connect(self._register_all)
        btn_row.addWidget(register_all_btn)
        edit_btn = QPushButton("選択行を編集（月別運用）")
        edit_btn.clicked.connect(self._edit_selected)
        btn_row.addWidget(edit_btn)
        save_list_btn = QPushButton("一覧をJSON保存")
        save_list_btn.clicked.connect(self._save_list)
        btn_row.addWidget(save_list_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _selected_row(self) -> Optional[Dict[str, Any]]:
        r = self._table.currentRow()
        if r < 0 or r >= len(self._rows):
            return None
        return self._rows[r]

    def _register_all(self) -> None:
        if not self._rows:
            return
        reply = QMessageBox.question(
            self,
            "一括登録",
            f"{len(self._rows)} 件を「{PURCHASE_STATUS_INVENTORY_ONLY_LABEL}」として仕入DBに登録・上書きしますか？\n"
            "（ASIN 未入力の既存行は在庫CSVの内容で置き換わります）\n"
            "（月別運用はオフ。あとから仕入行の編集で設定できます）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ok = 0
        for row in self._rows:
            try:
                register_inventory_only_row(
                    row,
                    self._purchase_db,
                    product_widget=self._product_widget,
                )
                ok += 1
            except Exception as e:
                print(f"[inventory_only] register failed: {e}")
        QMessageBox.information(self, "登録完了", f"{ok} 件を仕入DBに登録しました。")
        self._refresh_product_widget()
        self.accept()

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if not row:
            QMessageBox.information(self, "編集", "行を選択してください。")
            return
        sku = str(row.get("SKU") or row.get("sku") or "").strip()
        if not sku:
            return
        try:
            register_inventory_only_row(
                row,
                self._purchase_db,
                product_widget=self._product_widget,
            )
        except Exception as e:
            QMessageBox.warning(self, "登録", f"登録に失敗しました:\n{e}")
            return
        self._refresh_product_widget()
        if self._repricer_widget and hasattr(self._repricer_widget, "open_purchase_row_edit_for_sku"):
            self._repricer_widget.open_purchase_row_edit_for_sku(
                sku,
                asin=str(row.get("ASIN") or row.get("asin") or ""),
                title=str(row.get("商品名") or row.get("title") or ""),
                csv_price=row.get("price"),
            )
        else:
            QMessageBox.information(
                self,
                "登録",
                f"SKU {sku} を在庫専用として登録しました。\n仕入DBタブから編集できます。",
            )

    def _save_list(self) -> None:
        path = save_pending_missing_list(self._rows, csv_path=self._csv_path)
        QMessageBox.information(self, "保存", f"一覧を保存しました:\n{path}")

    def _refresh_product_widget(self) -> None:
        pw = self._product_widget
        if pw is None:
            return
        try:
            if hasattr(pw, "load_purchase_data") and hasattr(pw, "purchase_history_db"):
                # スナップショット全件を維持しつつ hirio.db をマージ（在庫専用の追加分を含む）
                base = getattr(pw, "purchase_all_records_master", None) or getattr(
                    pw, "purchase_all_records", []
                )
                pw.load_purchase_data(list(base) if base else pw.purchase_history_db.list_all())
                pw.save_purchase_snapshot()
        except Exception as e:
            print(f"[inventory_only] refresh product_widget: {e}")
