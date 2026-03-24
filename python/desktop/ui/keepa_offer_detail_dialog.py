#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa live offers の出品者別一覧ダイアログ"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from services.keepa_service import KeepaOfferRow
except Exception:
    from desktop.services.keepa_service import KeepaOfferRow


class KeepaOfferDetailDialog(QDialog):
    """出品価格情報（新品 / 中古を横並びに近い構成で表示）。"""

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        asin: str,
        title: str,
        new_rows: List[KeepaOfferRow],
        used_rows: List[KeepaOfferRow],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"出品価格情報 — {asin}")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        head = QLabel(f"<b>ASIN</b> {asin}<br><b>タイトル</b> {title or '（なし）'}")
        head.setWordWrap(True)
        head.setTextFormat(Qt.RichText)
        root.addWidget(head)

        section_title = QLabel("出品価格情報（live offers）")
        f = QFont(section_title.font())
        f.setBold(True)
        section_title.setFont(f)
        root.addWidget(section_title)

        columns = QHBoxLayout()
        columns.setSpacing(12)

        columns.addWidget(self._build_column_group("新品", new_rows), 1)
        columns.addWidget(self._build_column_group("中古", used_rows), 1)

        wrap = QWidget()
        wrap.setLayout(columns)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(wrap)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        root.addWidget(buttons)

    def _build_column_group(self, heading: str, rows: List[KeepaOfferRow]) -> QGroupBox:
        box = QGroupBox(f"{heading}（{len(rows)} 件）")
        lay = QVBoxLayout(box)
        lay.setSpacing(6)
        if not rows:
            lay.addWidget(QLabel("（オファーなし）"))
            lay.addStretch(1)
            return box
        for r in rows:
            lay.addWidget(self._row_label(r))
        lay.addStretch(1)
        return box

    @staticmethod
    def _row_label(r: KeepaOfferRow) -> QLabel:
        fulfill = "FBA" if r.is_fba else "自己発送"
        amz = "【Amazon】" if r.is_amazon else ""
        text = (
            f"{amz}<b>{r.condition_label}</b>（{fulfill}） "
            f"{r.price_jpy:,} 円<span style='color:#aaa'>（送 {r.ship_jpy:,} 円）</span> "
            f"→ <b>計 {r.total_jpy:,} 円</b><br>"
            f"<span style='color:#888;font-size:11px;'>{r.seller_note}</span>"
        )
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.RichText)
        return lab
