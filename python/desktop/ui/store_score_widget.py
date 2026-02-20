#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗スコア一覧ウィジェット

ルート情報（想定粗利・仕入点数・評価）を蓄積した結果を店舗ごとに集計し、
店舗スコアとして表示する。データベース管理 > 店舗マスタ > 店舗スコアタブで使用。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QGroupBox, QComboBox,
)
from PySide6.QtCore import Qt

from database.route_db import RouteDatabase
from database.route_visit_db import RouteVisitDatabase
from database.store_db import StoreDatabase
from services.store_score_service import get_merged_store_aggregates


class StoreScoreWidget(QWidget):
    """店舗スコア一覧ウィジェット"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.route_db = RouteDatabase()
        self.route_visit_db = RouteVisitDatabase()
        self.store_db = StoreDatabase()
        self.setup_ui()
        self.load_scores()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header = QLabel("店舗スコア一覧")
        header.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(header)

        btn_group = QGroupBox("操作")
        btn_layout = QHBoxLayout(btn_group)
        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(self.load_scores)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addWidget(QLabel("ルートで絞り込み:"))
        self.route_filter_combo = QComboBox()
        self.route_filter_combo.setMinimumWidth(180)
        self.route_filter_combo.currentTextChanged.connect(self._apply_route_filter)
        btn_layout.addWidget(self.route_filter_combo)
        btn_layout.addStretch()
        layout.addWidget(btn_group)

        table_group = QGroupBox("店舗別実績・スコア")
        table_layout = QVBoxLayout(table_group)
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        self._all_rows: list = []  # 全件（ルート絞り込み用）
        table_layout.addWidget(self.table)
        self.stats_label = QLabel("")
        self.stats_label.setWordWrap(True)
        table_layout.addWidget(self.stats_label)
        layout.addWidget(table_group)

    def load_scores(self):
        try:
            rows = get_merged_store_aggregates(
                self.route_db,
                self.route_visit_db,
                self.store_db,
            )
        except Exception as e:
            self.stats_label.setText(f"集計エラー: {e}")
            self.table.setRowCount(0)
            self._all_rows = []
            return

        self._all_rows = rows
        self._refresh_route_filter_combo()
        self._fill_table(rows)

    def _refresh_route_filter_combo(self):
        """ルート絞り込みコンボに「すべて」＋登録ルート名をセット"""
        current = self.route_filter_combo.currentText()
        self.route_filter_combo.blockSignals(True)
        self.route_filter_combo.clear()
        self.route_filter_combo.addItem("すべて", None)
        try:
            for name in (self.store_db.get_route_names() or []):
                self.route_filter_combo.addItem(name, name)
        except Exception:
            pass
        idx = self.route_filter_combo.findText(current) if current else 0
        self.route_filter_combo.setCurrentIndex(max(0, idx))
        self.route_filter_combo.blockSignals(False)

    def _apply_route_filter(self):
        """ルート絞り込みに応じて表示行を更新"""
        key = self.route_filter_combo.currentData()
        if key is None:
            rows = self._all_rows
        else:
            rows = [r for r in self._all_rows if (r.get("route_name") or "").strip() == key]
        self._fill_table(rows)

    def _fill_table(self, rows: list):
        """指定した行リストでテーブルを再描画"""
        columns = [
            "店舗コード", "店舗名", "ルート名", "訪問回数",
            "累計想定粗利", "累計仕入点数", "平均評価", "スコア",
        ]
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setSortingEnabled(False)

        for i, row in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(row.get("store_code", "")))
            self.table.setItem(i, 1, QTableWidgetItem(row.get("store_name", "")))
            self.table.setItem(i, 2, QTableWidgetItem(row.get("route_name", "")))
            vc = row.get("visit_count", 0)
            self.table.setItem(i, 3, QTableWidgetItem(str(vc)))
            gp = row.get("total_gross_profit", 0)
            gp_item = QTableWidgetItem()
            gp_item.setData(Qt.EditRole, gp)
            gp_item.setText(f"{int(gp):,}")
            self.table.setItem(i, 4, gp_item)
            ic = row.get("total_item_count", 0)
            ic_item = QTableWidgetItem()
            ic_item.setData(Qt.EditRole, ic)
            ic_item.setText(str(ic))
            self.table.setItem(i, 5, ic_item)
            ar = row.get("avg_rating", 0)
            ar_item = QTableWidgetItem()
            ar_item.setData(Qt.EditRole, round(ar, 2))
            ar_item.setText(f"{ar:.2f}")
            self.table.setItem(i, 6, ar_item)
            sc = row.get("score", 0)
            sc_item = QTableWidgetItem()
            sc_item.setData(Qt.EditRole, sc)
            sc_item.setText(f"{sc:.1f}")
            self.table.setItem(i, 7, sc_item)

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        total = len(self._all_rows)
        self.stats_label.setText(
            f"店舗数: {len(rows)}件 / 全{total}件\n"
            "集計: ルート登録・仕入管理のDBに保存された想定粗利・仕入点数・評価を店舗ごとに集計。"
            "訪問回数は「訪問ログ」の記録件数（同一ルート保存で二重計上しないよう訪問ログのみ集計）。"
            "到着・出発時刻のいずれかが入っている訪問のみ集計（未入力は未訪問としてスコアから除外）。"
            "店舗名・ルート名は店舗マスタおよび訪問ログから補完（マスタ未登録でログにも無い場合は空欄）。"
        )
