#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ランキングカンバンウィジェット

分析タブ内で店舗・ルートのランキングをカンバン形式（横5列）で表示する。
"""
from __future__ import annotations

import sys
import os
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QSizePolicy, QSpinBox, QGroupBox,
)
from PySide6.QtCore import Qt

from database.route_db import RouteDatabase
from database.route_visit_db import RouteVisitDatabase
from database.store_db import StoreDatabase
from services.ranking_service import build_ranking_boards


class _RankingColumn(QFrame):
    """カンバン1列（タイトル＋ランキングカード）"""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setStyleSheet(
            "QFrame { background-color: #2b2b2b; border: 1px solid #444; border-radius: 6px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-weight: bold; font-size: 11pt; color: #e8e8e8;")
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet("font-size: 8pt; color: #999;")
        sub_lbl.setWordWrap(True)
        layout.addWidget(sub_lbl)

        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(4)
        layout.addLayout(self._cards_layout)
        layout.addStretch()

    def set_entries(self, entries: List[Dict[str, Any]], formatter) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not entries:
            empty = QLabel("（データなし）")
            empty.setStyleSheet("color: #888; font-size: 9pt;")
            self._cards_layout.addWidget(empty)
            return
        for rank, entry in enumerate(entries, start=1):
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background-color: #363636; border-radius: 4px; padding: 2px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(6, 4, 6, 4)
            card_layout.setSpacing(2)
            rank_lbl = QLabel(f"#{rank}")
            rank_lbl.setStyleSheet("font-weight: bold; color: #6eb5ff; font-size: 9pt;")
            card_layout.addWidget(rank_lbl)
            name_lbl = QLabel(formatter.name(entry))
            name_lbl.setWordWrap(True)
            name_lbl.setStyleSheet("color: #f0f0f0; font-size: 9pt;")
            card_layout.addWidget(name_lbl)
            val_lbl = QLabel(formatter.value(entry))
            val_lbl.setStyleSheet("color: #b8e986; font-size: 9pt;")
            card_layout.addWidget(val_lbl)
            sub = formatter.sub(entry)
            if sub:
                sub_lbl = QLabel(sub)
                sub_lbl.setStyleSheet("color: #aaa; font-size: 8pt;")
                card_layout.addWidget(sub_lbl)
            self._cards_layout.addWidget(card)


class _ColumnFormatter:
    def __init__(self, name_fn, value_fn, sub_fn=None):
        self._name_fn = name_fn
        self._value_fn = value_fn
        self._sub_fn = sub_fn or (lambda e: "")

    def name(self, entry: Dict[str, Any]) -> str:
        return self._name_fn(entry)

    def value(self, entry: Dict[str, Any]) -> str:
        return self._value_fn(entry)

    def sub(self, entry: Dict[str, Any]) -> str:
        return self._sub_fn(entry)


def _store_label(entry: Dict[str, Any]) -> str:
    name = (entry.get("store_name") or "").strip()
    code = (entry.get("store_code") or "").strip()
    if name and code:
        return f"{name}\n({code})"
    return name or code or "—"


def _route_label(entry: Dict[str, Any]) -> str:
    name = (entry.get("route_name") or "").strip()
    code = (entry.get("route_code") or "").strip()
    if name and name != code:
        return name
    return name or code or "—"


class RankingKanbanWidget(QWidget):
    """分析用ランキングカンバン"""

    _COLUMNS = (
        ("store_profit", "高想定利益額\n店舗", "店舗スコアと同じ累計想定粗利"),
        ("store_visits", "訪問回数", "店舗スコアと同じ訪問ログ集計"),
        ("store_score", "店舗スコア", "店舗スコアタブと同じ算出（0〜100）"),
        ("route_margin", "高想定利益率\nルート", "期間内ルートサマリー（粗利÷販売額）"),
        ("route_profit", "高想定利益額\nルート", "期間内ルートサマリーの累計想定粗利"),
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.route_db = RouteDatabase()
        self.route_visit_db = RouteVisitDatabase()
        self.store_db = StoreDatabase()
        self._columns: Dict[str, _RankingColumn] = {}
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        title = QLabel("ランキング（カンバン）")
        title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        header_row.addWidget(title)
        header_row.addStretch()
        header_row.addWidget(QLabel("表示件数:"))
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(3, 30)
        self.top_n_spin.setValue(10)
        self.top_n_spin.valueChanged.connect(self._reload_last_period)
        header_row.addWidget(self.top_n_spin)
        layout.addLayout(header_row)

        self.period_label = QLabel("")
        self.period_label.setStyleSheet("color: #999; font-size: 9pt;")
        layout.addWidget(self.period_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        board = QWidget()
        board_layout = QHBoxLayout(board)
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(10)
        board_layout.setAlignment(Qt.AlignTop)

        formatters = {
            "store_profit": _ColumnFormatter(
                _store_label,
                lambda e: f"{int(float(e.get('total_gross_profit') or 0)):,} 円",
                lambda e: f"訪問 {int(e.get('visit_count') or 0)}回",
            ),
            "store_visits": _ColumnFormatter(
                _store_label,
                lambda e: f"{int(e.get('visit_count') or 0)} 回",
                lambda e: f"スコア {float(e.get('score') or 0):.1f}",
            ),
            "store_score": _ColumnFormatter(
                _store_label,
                lambda e: f"{float(e.get('score') or 0):.1f} 点",
                lambda e: (
                    f"訪問 {int(e.get('visit_count') or 0)}回 · "
                    f"粗利 {int(float(e.get('total_gross_profit') or 0)):,}円"
                ),
            ),
            "route_margin": _ColumnFormatter(
                _route_label,
                lambda e: f"{float(e.get('expected_margin') or 0):.2f}%",
                lambda e: f"実施 {int(e.get('route_count') or 0)}回",
            ),
            "route_profit": _ColumnFormatter(
                _route_label,
                lambda e: f"{int(float(e.get('total_gross_profit') or 0)):,} 円",
                lambda e: f"利益率 {float(e.get('expected_margin') or 0):.2f}%",
            ),
        }

        self._formatters = formatters
        for key, title, subtitle in self._COLUMNS:
            col = _RankingColumn(title.replace("\n", " "), subtitle)
            self._columns[key] = col
            board_layout.addWidget(col)

        board_layout.addStretch()
        scroll.setWidget(board)
        layout.addWidget(scroll, stretch=1)

        note = QLabel(
            "店舗の訪問回数・累計粗利・スコアは「店舗スコア」タブと同じ集計（全期間）。"
            " ルートは期間内のルートサマリー。上部の「更新」で再読み込みします。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 8pt;")
        layout.addWidget(note)

        self._last_start: Optional[str] = None
        self._last_end: Optional[str] = None

    def _reload_last_period(self) -> None:
        if self._last_start is not None:
            self.load_rankings(self._last_start, self._last_end)

    def load_rankings(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        self._last_start = start_date
        self._last_end = end_date
        route_period = "全期間"
        if start_date and end_date:
            route_period = f"{start_date} 〜 {end_date}"
        elif start_date:
            route_period = f"{start_date} 以降"
        elif end_date:
            route_period = f"{end_date} まで"
        self.period_label.setText(
            f"店舗（訪問・粗利・スコア）: 店舗スコアと同じ全期間 / "
            f"ルート: {route_period}"
        )

        top_n = self.top_n_spin.value()
        try:
            boards = build_ranking_boards(
                self.route_db,
                self.route_visit_db,
                self.store_db,
                start_date=start_date,
                end_date=end_date,
                top_n=top_n,
            )
        except Exception as e:
            for key, col in self._columns.items():
                col.set_entries([], self._formatters[key])
            self.period_label.setText(f"集計エラー: {e}")
            return

        for key, col in self._columns.items():
            col.set_entries(boards.get(key, []), self._formatters[key])
