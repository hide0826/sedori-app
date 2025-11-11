#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルート訪問履歴ビュー

route_visit_logs テーブルの内容を一覧表示し、ルート登録タブで保存された履歴を確認できる。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QGroupBox, QLabel, QHeaderView, QDateEdit, QComboBox, QCheckBox, QMessageBox
)
from PySide6.QtCore import Qt, QDate
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.route_visit_db import RouteVisitDatabase


class RouteVisitLogWidget(QWidget):
    """ルート訪問履歴ウィジェット"""

    def __init__(self):
        super().__init__()
        self.visit_db = RouteVisitDatabase()

        self.setup_ui()
        self.load_route_codes()
        self.load_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header = QLabel("ルート訪問履歴")
        header.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(header)

        self.setup_filters(layout)
        self.setup_table(layout)

    def setup_filters(self, parent_layout):
        group = QGroupBox("フィルター")
        filter_layout = QHBoxLayout(group)

        # 日付フィルタ
        self.date_check = QCheckBox("日付で絞り込み")
        self.date_check.stateChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(self.date_check)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.dateChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(self.date_edit)

        # ルートコードフィルタ
        self.route_combo = QComboBox()
        self.route_combo.currentIndexChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(QLabel("ルート:"))
        filter_layout.addWidget(self.route_combo)

        # 操作ボタン
        refresh_btn = QPushButton("再読込")
        refresh_btn.clicked.connect(self.load_data)
        filter_layout.addWidget(refresh_btn)

        clear_btn = QPushButton("フィルタ解除")
        clear_btn.clicked.connect(self.reset_filters)
        filter_layout.addWidget(clear_btn)

        filter_layout.addStretch()

        parent_layout.addWidget(group)

    def setup_table(self, parent_layout):
        group = QGroupBox("訪問詳細")
        table_layout = QVBoxLayout(group)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)

        table_layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        delete_btn = QPushButton("選択削除")
        delete_btn.clicked.connect(self.delete_selected_visit)
        button_layout.addWidget(delete_btn)

        clear_btn = QPushButton("全削除（デバッグ用）")
        clear_btn.clicked.connect(self.delete_all_visits)
        clear_btn.setStyleSheet("color: #ff7676;")
        button_layout.addWidget(clear_btn)

        table_layout.addLayout(button_layout)

        parent_layout.addWidget(group)

    def load_route_codes(self):
        """ルートコードコンボボックスの更新"""
        self.route_combo.blockSignals(True)
        self.route_combo.clear()
        self.route_combo.addItem("すべて", "")

        try:
            for row in self.visit_db.list_route_codes():
                display = row.get('route_name') or row.get('route_code')
                code = row.get('route_code') or ''
                if display and code:
                    self.route_combo.addItem(f"{display} ({code})", code)
        except Exception as e:
            print(f"ルートコードの取得に失敗しました: {e}")

        self.route_combo.blockSignals(False)

    def load_data(self):
        """テーブルの再描画"""
        route_code = self.route_combo.currentData() or ""
        route_date = None
        if self.date_check.isChecked():
            route_date = self.date_edit.date().toString('yyyy-MM-dd')

        try:
            visits = self.visit_db.list_route_visits(route_date=route_date, route_code=route_code or None)
        except Exception as e:
            print(f"訪問履歴の取得に失敗しました: {e}")
            visits = []

        columns = [
            "日付", "ルート名", "ルートコード", "訪問順",
            "店舗コード", "店舗名", "IN時刻", "OUT時刻",
            "滞在時間(分)", "移動時間(分)", "仕入点数", "想定粗利",
            "評価", "メモ", "登録日時", "更新日時"
        ]

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visits))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        for row_idx, visit in enumerate(visits):
            self._set_item(row_idx, 0, visit.get('route_date', ''))
            self._set_item(row_idx, 1, visit.get('route_name', ''))
            self._set_item(row_idx, 2, visit.get('route_code', ''))
            self._set_number_item(row_idx, 3, visit.get('visit_order'))
            self._set_item(row_idx, 4, visit.get('store_code', ''))
            self._set_item(row_idx, 5, visit.get('store_name', ''))
            self._set_item(row_idx, 6, self._format_time(visit.get('store_in_time')))
            self._set_item(row_idx, 7, self._format_time(visit.get('store_out_time')))
            self._set_number_item(row_idx, 8, visit.get('stay_duration'), digits=1)
            self._set_number_item(row_idx, 9, visit.get('travel_time_from_prev'), digits=1)
            self._set_number_item(row_idx, 10, visit.get('store_item_count'))
            self._set_number_item(row_idx, 11, visit.get('store_gross_profit'))
            self._set_number_item(row_idx, 12, visit.get('store_rating'))
            self._set_item(row_idx, 13, visit.get('store_notes', ''))
            self._set_item(row_idx, 14, visit.get('created_at', ''))
            self._set_item(row_idx, 15, visit.get('updated_at', ''))
            first_item = self.table.item(row_idx, 0)
            if first_item:
                first_item.setData(Qt.UserRole, visit.get('id'))

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

    def reset_filters(self):
        self.route_combo.setCurrentIndex(0)
        self.date_check.setChecked(False)
        self.date_edit.setDate(QDate.currentDate())
        self.load_data()

    def on_filter_changed(self, *args):
        if isinstance(args[0], bool):
            pass  # placeholder
        self.load_data()

    def _set_item(self, row: int, col: int, value: str):
        item = QTableWidgetItem(str(value) if value is not None else '')
        self.table.setItem(row, col, item)

    def _set_number_item(self, row: int, col: int, value, digits: int = 0):
        if value is None or value == '':
            display = ''
            sort_value = 0
        else:
            try:
                sort_value = float(value)
                if digits == 0:
                    display = f"{int(round(sort_value)):,}"
                else:
                    display = f"{sort_value:.{digits}f}"
            except (TypeError, ValueError):
                display = str(value)
                sort_value = 0
        item = QTableWidgetItem(display)
        item.setData(Qt.EditRole, sort_value)
        self.table.setItem(row, col, item)

    def _format_time(self, datetime_str: str) -> str:
        if not datetime_str:
            return ""
        text = str(datetime_str)
        if " " in text:
            text = text.split(" ")[1]
        if "T" in text:
            text = text.split("T")[1]
        return text[:5]

    def delete_selected_visit(self):
        """選択行を削除"""
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.warning(self, "削除", "削除する行を選択してください。")
            return

        visit_ids = []
        for idx in selected:
            item = self.table.item(idx.row(), 0)
            visit_id = item.data(Qt.UserRole) if item else None
            if visit_id is not None:
                visit_ids.append(int(visit_id))

        if not visit_ids:
            QMessageBox.warning(self, "削除", "選択した行からIDを取得できませんでした。")
            return

        reply = QMessageBox.question(
            self,
            "確認",
            f"{len(visit_ids)}件の訪問データを削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        for vid in visit_ids:
            self.visit_db.delete_visit_by_id(vid)

        self.load_route_codes()
        self.load_data()

    def delete_all_visits(self):
        """全件削除（デバッグ用途）"""
        reply = QMessageBox.question(
            self,
            "全削除の確認",
            "ルート訪問DBの全データを削除します。よろしいですか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.visit_db.delete_all_visits()
        self.load_route_codes()
        self.load_data()


