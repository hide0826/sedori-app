#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa live offers の出品者別一覧ダイアログ"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont, QGuiApplication, QShowEvent
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

try:
    from utils.settings_helper import get_amazon_seller_id
except Exception:
    from desktop.utils.settings_helper import get_amazon_seller_id


# 自店オファー強調（ダークUI向け：水色の枠＋青緑がかった背景）
_OWN_OFFER_STYLE = """
    QLabel {
        background-color: #1a3d42;
        border: 2px solid #26c6da;
        border-radius: 8px;
        padding: 10px;
    }
"""


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
        # モーダルにすると親（仕入行の編集など）が操作不能になるため参照用ウィンドウは非モーダル
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._my_seller_id = get_amazon_seller_id().strip().upper()

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

        legend = QLabel(
            "<b>表示の見方</b><br>"
            "・<span style='color:#80deea;'>水色の枠</span>と"
            "<span style='color:#4db6ac;'>青緑がかった背景</span> … "
            "設定タブ → 詳細設定 → Amazon の「自店のセラーID」に保存した ID と一致するオファー（あなたの出品の目印）です。<br>"
            "・それ以外のグレー地のカード … 他出品者のオファーです。"
        )
        legend.setWordWrap(True)
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet("color: #bbb; font-size: 12px; padding: 6px 4px;")
        root.addWidget(legend)

        if not self._my_seller_id:
            hint = QLabel(
                "※ いまは自店セラーIDが未設定です。強調表示を使うには、設定タブで ID を入力して保存してください。"
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #ffab40; font-size: 12px;")
            root.addWidget(hint)

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

        self._placed_near_anchor = False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._placed_near_anchor:
            return
        anchor = self.parentWidget()
        if anchor is None:
            return
        self._placed_near_anchor = True
        self._move_beside_anchor(anchor)

    @staticmethod
    def _widget_global_rect(w: QWidget) -> QRect:
        """ウィンドウ・子ウィジェット共通で、画面上の矩形を返す。"""
        if w.isWindow():
            return w.frameGeometry()
        top_left = w.mapToGlobal(QPoint(0, 0))
        return QRect(top_left.x(), top_left.y(), w.width(), w.height())

    def _move_beside_anchor(self, anchor: QWidget) -> None:
        """仕入行の編集など親の横（右→左→下の順）に出し、画面外にはみ出さないようにする。"""
        margin = 12
        ar = self._widget_global_rect(anchor)
        sw = self.width()
        sh = self.height()
        scr = QGuiApplication.screenAt(ar.center()) or QGuiApplication.primaryScreen()
        if scr is None:
            return
        avail = scr.availableGeometry()

        def _clamp_pos(x: int, y: int) -> tuple[int, int]:
            x = max(avail.left(), min(x, avail.right() - sw))
            y = max(avail.top(), min(y, avail.bottom() - sh))
            return x, y

        # 1) 親の右側
        x = ar.right() + margin
        y = ar.top()
        if x + sw <= avail.right() + 1:
            self.move(*_clamp_pos(x, y))
            return

        # 2) 親の左側
        x = ar.left() - sw - margin
        if x >= avail.left() - 1:
            self.move(*_clamp_pos(x, y))
            return

        # 3) 親の下（幅は画面内に収める）
        x = ar.left()
        y = ar.bottom() + margin
        if x + sw > avail.right():
            x = max(avail.left(), avail.right() - sw)
        self.move(*_clamp_pos(x, y))

    def _is_own_offer(self, r: KeepaOfferRow) -> bool:
        if not self._my_seller_id:
            return False
        sid = (r.seller_id or "").strip().upper()
        return bool(sid and sid == self._my_seller_id)

    def _build_column_group(self, heading: str, rows: List[KeepaOfferRow]) -> QGroupBox:
        box = QGroupBox(f"{heading}（{len(rows)} 件）")
        lay = QVBoxLayout(box)
        lay.setSpacing(6)
        if not rows:
            lay.addWidget(QLabel("（オファーなし）"))
            lay.addStretch(1)
            return box
        for r in rows:
            lay.addWidget(self._make_row_label(r))
        lay.addStretch(1)
        return box

    def _make_row_label(self, r: KeepaOfferRow) -> QLabel:
        fulfill = "FBA" if r.is_fba else "自己発送"
        amz = "【Amazon】" if r.is_amazon else ""
        own = self._is_own_offer(r)
        seller_color = "#b2ebf2" if own else "#888"
        if r.ship_jpy == 0:
            price_html = f"<b>{r.total_jpy:,} 円</b>（送料込）"
        else:
            price_html = (
                f"{r.price_jpy:,} 円<span style='color:#aaa'>（送 {r.ship_jpy:,} 円）</span> "
                f"→ <b>計 {r.total_jpy:,} 円</b>"
            )
        text = (
            f"{amz}<b>{r.condition_label}</b>（{fulfill}） {price_html}<br>"
            f"<span style='color:{seller_color};font-size:11px;'>{r.seller_note}</span>"
        )
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.RichText)
        if own:
            lab.setStyleSheet(_OWN_OFFER_STYLE)
        return lab
