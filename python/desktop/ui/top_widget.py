#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOP（ホーム）ダッシュボードウィジェット

アプリ起動時に表示するサマリー画面。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.top_dashboard_service import TopDashboardService


class _DashboardCard(QFrame):
    """セクション用カード"""

    def __init__(self, title: str, accent: str, icon: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("dashboardCard")
        self.setStyleSheet(
            f"""
            QFrame#dashboardCard {{
                background-color: #353535;
                border: 1px solid #4a4a4a;
                border-left: 4px solid {accent};
                border-radius: 10px;
            }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"font-size: 22pt; color: {accent};")
        header.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 14pt; font-weight: bold; color: {accent}; letter-spacing: 1px;"
        )
        header.addWidget(title_label)
        header.addStretch()
        layout.addLayout(header)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(8)
        layout.addLayout(self.body_layout)

    def set_body_widget(self, widget: QWidget) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.body_layout.addWidget(widget)


class TopWidget(QWidget):
    """アプリ起動時のTOPダッシュボード"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._service = TopDashboardService()
        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(24)

        # ── ヒーローヘッダー ──
        hero = QFrame()
        hero.setObjectName("topHero")
        hero.setStyleSheet(
            """
            QFrame#topHero {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a3a5c,
                    stop:0.5 #1e4d7a,
                    stop:1 #0d2137
                );
                border-radius: 14px;
                border: 1px solid #2a6090;
            }
            """
        )
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(36, 32, 36, 32)
        hero_layout.setSpacing(10)

        title = QLabel("HIRIO")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 42pt; font-weight: 800; color: #ffffff; letter-spacing: 6px;"
        )
        hero_layout.addWidget(title)

        subtitle = QLabel("店舗中古せどり事務業務統合システム")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            "font-size: 16pt; font-weight: 500; color: #b8d4f0; letter-spacing: 2px;"
        )
        hero_layout.addWidget(subtitle)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        refresh_btn = QPushButton("⟳  更新")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.12);
                color: #e8f4ff;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 8px;
                padding: 8px 20px;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.22);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.08);
            }
            """
        )
        refresh_btn.clicked.connect(self.refresh)
        refresh_row.addWidget(refresh_btn)
        hero_layout.addLayout(refresh_row)

        layout.addWidget(hero)

        # ── カード群 ──
        self.pending_card = _DashboardCard("未実装タスク", "#e85d4c", "⚠")
        self.last_route_card = _DashboardCard("前回ルート", "#3d9ae8", "◎")
        self.next_route_card = _DashboardCard("次回ルート候補", "#5cb85c", "→")

        layout.addWidget(self.pending_card)
        layout.addWidget(self.last_route_card)
        layout.addWidget(self.next_route_card)
        layout.addStretch()

    def refresh(self) -> None:
        """DBから最新データを読み込んで表示を更新"""
        try:
            data = self._service.build_dashboard_data()
        except Exception as exc:
            self.pending_card.set_body_widget(self._empty_label(f"データ読み込みエラー: {exc}", "#e85d4c"))
            self.last_route_card.set_body_widget(self._empty_label("—", "#888888"))
            self.next_route_card.set_body_widget(self._empty_label("—", "#888888"))
            return

        self.pending_card.set_body_widget(self._build_pending_body(data.get("pending_tasks") or []))
        self.last_route_card.set_body_widget(self._build_last_route_body(data.get("last_route")))
        self.next_route_card.set_body_widget(
            self._build_next_candidates_body(data.get("next_route_candidates") or [])
        )

    @staticmethod
    def _empty_label(text: str, color: str = "#aaaaaa") -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size: 12pt; color: {color}; padding: 4px 0;")
        return label

    def _build_pending_body(self, tasks: List[Dict[str, Any]]) -> QWidget:
        if not tasks:
            return self._empty_label("未完了のタスクはありません ✓", "#5cb85c")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        for task in tasks:
            date = task.get("route_date", "")
            name = task.get("route_name", "")
            labels = task.get("pending_labels") or []
            labels_text = "　".join(labels)
            text = f"{date}　{name}　{labels_text}　未実装です。"

            row = QFrame()
            row.setStyleSheet(
                """
                QFrame {
                    background-color: #2a2a2a;
                    border-radius: 8px;
                    border: 1px solid #4a3535;
                }
                """
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 10, 14, 10)

            dot = QLabel("●")
            dot.setStyleSheet("color: #e85d4c; font-size: 10pt;")
            row_layout.addWidget(dot, alignment=Qt.AlignTop)

            label = QLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet("font-size: 12pt; color: #f0e0dc; line-height: 1.4;")
            row_layout.addWidget(label, stretch=1)

            layout.addWidget(row)

        return container

    def _build_last_route_body(self, last_route: Optional[Dict[str, Any]]) -> QWidget:
        if not last_route:
            return self._empty_label("ルートサマリーがまだ登録されていません", "#888888")

        date = last_route.get("route_date", "")
        name = last_route.get("route_name", "")

        frame = QFrame()
        frame.setStyleSheet(
            """
            QFrame {
                background-color: #2a3540;
                border-radius: 10px;
                border: 1px solid #3d5a73;
            }
            """
        )
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(20, 16, 20, 16)

        main_text = QLabel(f"{date}　{name}")
        main_text.setStyleSheet("font-size: 18pt; font-weight: bold; color: #d0e8ff;")
        frame_layout.addWidget(main_text)

        hint = QLabel("ルートサマリー直近の記録")
        hint.setStyleSheet("font-size: 10pt; color: #7a9ab8;")
        frame_layout.addWidget(hint)

        return frame

    def _build_next_candidates_body(self, candidates: List[Dict[str, Any]]) -> QWidget:
        if not candidates:
            return self._empty_label("登録ルートがありません（店舗マスタでルートを登録してください）", "#888888")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        rank_colors = ["#ffd700", "#c0c0c0", "#cd7f32"]

        for idx, candidate in enumerate(candidates):
            name = candidate.get("route_name", "")
            last = candidate.get("last_visit_date")
            rank_color = rank_colors[idx] if idx < len(rank_colors) else "#888888"

            row = QFrame()
            row.setStyleSheet(
                """
                QFrame {
                    background-color: #2a332a;
                    border-radius: 8px;
                    border: 1px solid #3d5a3d;
                }
                """
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 12, 14, 12)

            rank = QLabel(str(idx + 1))
            rank.setFixedSize(28, 28)
            rank.setAlignment(Qt.AlignCenter)
            rank.setStyleSheet(
                f"""
                background-color: {rank_color};
                color: #1a1a1a;
                font-weight: bold;
                font-size: 12pt;
                border-radius: 14px;
                """
            )
            row_layout.addWidget(rank)

            info = QVBoxLayout()
            info.setSpacing(2)
            name_label = QLabel(name)
            name_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #d8f0d8;")
            info.addWidget(name_label)

            if last:
                sub = QLabel(f"最終巡回: {last}")
                sub.setStyleSheet("font-size: 10pt; color: #8ab88a;")
            else:
                sub = QLabel("未巡回 — 優先候補")
                sub.setStyleSheet("font-size: 10pt; color: #e8a838; font-weight: bold;")
            info.addWidget(sub)
            row_layout.addLayout(info)
            row_layout.addStretch()

            layout.addWidget(row)

        hint = QLabel("※ 登録ルートのうち、最終巡回から最も時間が経過した順に表示")
        hint.setStyleSheet("font-size: 9pt; color: #6a8a6a; margin-top: 4px;")
        layout.addWidget(hint)

        return container
