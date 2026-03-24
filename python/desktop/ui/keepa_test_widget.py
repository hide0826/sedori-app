#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa テスト用ウィジェット

ASIN を入力して、Keepa API から以下の情報を取得して表示するタブ:
- タイトル
- 画像URL
- 新品・中古（非常に良い/良い/可）: **live offers** の **本体+送料** 合計でコンディション別最安（円。1/100 返却時は 100 倍）
- 該当コンディションの出品が無いときは「無し」（offers が空のときは「-」）
- ランキング
- カテゴリ名
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional
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
    from ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog
except Exception:
    # 明示的パス指定のフォールバック
    from desktop.services.keepa_service import KeepaService, KeepaProductInfo
    from desktop.ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog


class KeepaTestWidget(QWidget):
    """ASIN から Keepa 情報を取得するテストタブ"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.keepa_service = KeepaService()
        self._last_raw_product: Optional[Dict[str, Any]] = None
        self._last_title: str = ""
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
        self.result_table = QTableWidget(1, 9)
        self.result_table.setHorizontalHeaderLabels([
            "タイトル",
            "画像URL",
            "新品価格",
            "中古・非常に良い",
            "中古・良い",
            "中古・可",
            "ランキング",
            "カテゴリ名",
            "詳細",
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
        self.result_table.removeCellWidget(0, 8)
        self._last_raw_product = None
        self._last_title = ""
        info_item = QTableWidgetItem(message)
        info_item.setFlags(Qt.ItemIsEnabled)
        self.result_table.setItem(0, 0, info_item)
        # 他の列は空のまま

    def _set_product_row(self, info: KeepaProductInfo) -> None:
        """取得した商品情報をテーブルに反映する。"""
        self.result_table.clearContents()
        self.result_table.removeCellWidget(0, 8)

        def _set(col: int, text: str) -> None:
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.result_table.setItem(0, col, item)

        def _format_price_jpy(
            state: Literal["ok", "no_seller", "no_data"],
            value: Optional[float],
        ) -> str:
            if state == "no_seller":
                return "無し"
            if state != "ok" or value is None:
                return "-"
            return str(int(round(value)))

        _set(0, info.title or "(タイトルなし)")
        _set(1, info.image_url or "-")
        _set(2, _format_price_jpy(info.new_price_state, info.new_price))
        _set(3, _format_price_jpy(info.used_very_good_state, info.used_very_good))
        _set(4, _format_price_jpy(info.used_good_state, info.used_good))
        _set(5, _format_price_jpy(info.used_acceptable_state, info.used_acceptable))
        _set(6, str(info.sales_rank) if info.sales_rank is not None else "-")
        _set(7, info.category_name or "-")

        detail_btn = QPushButton("詳細")
        detail_btn.setToolTip("live offers の出品者別・価格・送料を表示します")
        detail_btn.clicked.connect(self._on_detail_clicked)
        self.result_table.setCellWidget(0, 8, detail_btn)

    # ------------------------------------------------------------------
    # スロット
    # ------------------------------------------------------------------
    def _on_detail_clicked(self) -> None:
        if not self._last_raw_product:
            QMessageBox.information(
                self,
                "出品詳細",
                "先に「Keepa から取得」でデータを読み込んでください。",
            )
            return
        new_rows, used_rows = self.keepa_service.build_live_offer_display_rows(self._last_raw_product)
        dlg = KeepaOfferDetailDialog(
            self,
            asin=self.asin_edit.text().strip(),
            title=self._last_title,
            new_rows=new_rows,
            used_rows=used_rows,
        )
        dlg.exec()

    def on_fetch_clicked(self) -> None:
        asin = self.asin_edit.text().strip()
        if not asin:
            QMessageBox.warning(self, "入力エラー", "ASIN を入力してください。")
            return

        try:
            info, raw = self.keepa_service.fetch_product_with_raw(asin)
        except RuntimeError as e:
            QMessageBox.critical(self, "Keepa エラー", str(e))
            return

        self._last_raw_product = raw
        self._last_title = info.title or ""
        self._set_product_row(info)








