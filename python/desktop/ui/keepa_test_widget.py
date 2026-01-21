#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa テスト用ウィジェット

ASIN を入力して、Keepa API から以下の情報を取得して表示するタブ:
- タイトル
- 画像URL
- 新品価格
- 中古価格
- ランキング
- カテゴリ名
"""

from __future__ import annotations

from typing import Optional
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
)

# プロジェクトルートをパスに追加（python/desktop を sys.path に含める）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# デスクトップ側servicesを優先して読み込む
try:
    from services.keepa_service import KeepaService, KeepaProductInfo  # python/desktop/services
except Exception:
    # 明示的パス指定のフォールバック
    from desktop.services.keepa_service import KeepaService, KeepaProductInfo


class KeepaTestWidget(QWidget):
    """ASIN から Keepa 情報を取得するテストタブ"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.keepa_service = KeepaService()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # --- 上部: ASIN 入力 + 取得ボタン ---
        top_layout = QHBoxLayout()

        top_layout.addWidget(QLabel("ASIN:"))

        self.asin_edit = QLineEdit()
        self.asin_edit.setPlaceholderText("例: B00007B4DM")
        top_layout.addWidget(self.asin_edit, 1)

        self.fetch_button = QPushButton("Keepa から取得")
        self.fetch_button.clicked.connect(self.on_fetch_clicked)
        top_layout.addWidget(self.fetch_button)

        layout.addLayout(top_layout)

        # --- 下部: 結果テーブル（1行固定） ---
        self.result_table = QTableWidget(1, 6)
        self.result_table.setHorizontalHeaderLabels([
            "タイトル",
            "画像URL",
            "新品価格",
            "中古価格",
            "ランキング",
            "カテゴリ名",
        ])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setSelectionMode(QTableWidget.SingleSelection)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.result_table)

        # 初期メッセージ
        self._set_info_row("ASIN を入力して『Keepa から取得』を押してください。")

    # ------------------------------------------------------------------
    # UI ヘルパー
    # ------------------------------------------------------------------
    def _set_info_row(self, message: str) -> None:
        """テーブルに情報メッセージだけを表示する。"""
        self.result_table.clearContents()
        info_item = QTableWidgetItem(message)
        info_item.setFlags(Qt.ItemIsEnabled)
        self.result_table.setItem(0, 0, info_item)
        # 他の列は空のまま

    def _set_product_row(self, info: KeepaProductInfo) -> None:
        """取得した商品情報をテーブルに反映する。"""
        self.result_table.clearContents()

        def _set(col: int, text: str) -> None:
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.result_table.setItem(0, col, item)

        _set(0, info.title or "(タイトルなし)")
        _set(1, info.image_url or "-")
        _set(2, f"{info.new_price:.2f}" if info.new_price is not None else "-")
        _set(3, f"{info.used_price:.2f}" if info.used_price is not None else "-")
        _set(4, str(info.sales_rank) if info.sales_rank is not None else "-")
        _set(5, info.category_name or "-")

    # ------------------------------------------------------------------
    # スロット
    # ------------------------------------------------------------------
    def on_fetch_clicked(self) -> None:
        asin = self.asin_edit.text().strip()
        if not asin:
            QMessageBox.warning(self, "入力エラー", "ASIN を入力してください。")
            return

        try:
            info = self.keepa_service.fetch_product_by_asin(asin)
        except RuntimeError as e:
            QMessageBox.critical(self, "Keepa エラー", str(e))
            return

        self._set_product_row(info)








