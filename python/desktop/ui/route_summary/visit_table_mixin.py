#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RouteSummary RouteSummaryVisitTableMixin."""
from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple
import html
import os
import sys
import re
import logging
import webbrowser
from functools import partial
from datetime import datetime, time as dt_time
from pathlib import Path

import pandas as pd
import openpyxl

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QMessageBox, QFileDialog, QDateTimeEdit, QLineEdit,
    QTextEdit, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QDialog, QFormLayout, QDialogButtonBox, QTabWidget, QStyledItemDelegate, QStyle, QInputDialog,
    QSplitter, QApplication,
)
from PySide6.QtCore import Qt, QDateTime, QTime, Signal, QSettings, QUrl
from PySide6.QtGui import QColor, QShortcut, QKeySequence, QDrag, QGuiApplication, QBrush

from ui.star_rating_widget import StarRatingWidget

from .support import (
    WEBENGINE_AVAILABLE,
    QWebEngineView,
    ROUTE_SEGMENT_ROW_COLORS,
    COL_VISIT_INCLUDE,
    COL_VISIT_ORDER,
    COL_STORE_CODE,
    COL_STORE_NAME,
    COL_IN_TIME,
    COL_OUT_TIME,
    COL_STAY,
    COL_TRAVEL,
    COL_PROFIT,
    COL_QTY,
    COL_STAR,
    COL_NOTES,
    VISIT_TABLE_VISIBLE_COLUMNS,
    _VISIT_TABLE_DEFAULT_WIDTHS,
    _ROUTE_WORKFLOW_PIPELINE_SEGMENTS,
    _ROUTE_WORKFLOW_PIPELINE_SEP,
    _format_route_workflow_prefix_html,
    _format_route_workflow_pipeline_html,
    _template_include_from_db_value,
    _visit_include_checked,
    SafeInternalMoveTable,
    StoreSelectDialog,
    SavedRoutesDialog,
    RouteDatabase,
    StoreDatabase,
    RouteVisitDatabase,
    attach_table_column_width_persistence,
    reapply_table_column_widths,
    RouteMatchingService,
    CalculationService,
    TemplateGenerator,
    generate_route_map_urls,
    resolve_maps_api_key,
)



class RouteSummaryVisitTableMixin:
    def _setup_visit_table_column_persistence(self) -> None:
        """店舗訪問詳細テーブルの列幅を保存・復元する（初回のみ取り付け）。"""
        if not hasattr(self, "store_visits_table"):
            return
        table = self.store_visits_table
        if getattr(table, "_hirio_visit_table_persistence_ready", False):
            return
        table._hirio_table_column_settings_key = (
            "table_column_widths/route_summary/store_visits"
        )
        persistence = attach_table_column_width_persistence(
            table,
            default_widths=_VISIT_TABLE_DEFAULT_WIDTHS,
        )
        table._hirio_visit_table_persistence_ready = True
        persistence.apply(allow_defaults=True)

    def _apply_visit_table_column_visibility(self) -> None:
        """テンプレート向け列のみ表示（データ列は非表示で保持）"""
        if not hasattr(self, "store_visits_table"):
            return
        for col in range(self.store_visits_table.columnCount()):
            self.store_visits_table.setColumnHidden(col, col not in VISIT_TABLE_VISIBLE_COLUMNS)

    def add_store_from_master(self):
        """店舗マスタ一覧から選択して店舗を追加"""
        try:
            dialog = StoreSelectDialog(self.store_db, self)
            if dialog.exec() == QDialog.Accepted:
                selected = dialog.get_selected_stores()
                if not selected:
                    return
                # 変更前の状態保存
                self.save_table_state()
                base_rows = self.store_visits_table.rowCount()
                for i, store in enumerate(selected):
                    row = base_rows + i
                    self.store_visits_table.insertRow(row)
                    store_code = (store.get('store_code') or '').strip()
                    visit_code = store_code or (store.get('supplier_code') or '').strip()
                    include_checked = _template_include_from_db_value(store.get('template_include'))
                    self._fill_visit_table_row(
                        row,
                        store_code=visit_code,
                        store_name=store.get('store_name', ''),
                        notes=self._resolve_store_master_notes(store),
                        include_checked=include_checked,
                        order_editable=False,
                    )
                self.update_visit_order()
                self.save_store_order()
                self.recalc_travel_times()
                self.save_table_state()
                # 計算結果更新（存在しない環境でも落ちないように）
                getattr(self, 'update_calculation_results', lambda: None)()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"店舗追加中にエラーが発生しました:\n{str(e)}")

    def update_route_codes(self):
        """ルートコード一覧を更新"""
        try:
            # 既存のルート名を取得
            route_names = self.store_db.get_route_names()
            
            # コンボボックスをクリア
            self.route_code_combo.clear()
            
            # ルート名を追加
            for route_name in route_names:
                self.route_code_combo.addItem(route_name)
            
            # 空の選択肢も追加（手動入力用）
            if not self.route_code_combo.findText("") >= 0:
                self.route_code_combo.addItem("")
            
            # デフォルトは空白に設定
            self.route_code_combo.setCurrentText("")
                
        except Exception as e:
            print(f"ルートコード一覧更新エラー: {e}")

    def on_route_code_changed(self, route_name: str):
        """ルートコード変更時の処理"""
        try:
            self._sync_google_map_url_from_selected_route(route_name)
        except Exception as e:
            print(f"ルートコード変更処理エラー: {e}")

    def get_selected_route_code(self) -> str:
        """選択されたルートコードを取得"""
        route_name = self.route_code_combo.currentText().strip()
        if route_name:
            return self.store_db.ensure_route_code(route_name)
        return ""

    def _set_visit_row_checkbox(self, row: int, checked: bool = True) -> None:
        """店舗訪問行のテンプレート出力チェックボックスを配置"""
        container = QWidget(self.store_visits_table)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        checkbox = QCheckBox(container)
        checkbox.setChecked(checked)
        checkbox.stateChanged.connect(lambda _state: self.on_table_item_changed(None))
        layout.addWidget(checkbox)
        self.store_visits_table.setCellWidget(row, COL_VISIT_INCLUDE, container)

    def _collect_visit_order_and_includes(self) -> tuple:
        """現在テーブルの訪問順序とテンプレート出力フラグを店舗コード別に収集"""
        store_orders: Dict[str, int] = {}
        store_includes: Dict[str, bool] = {}
        for row in range(self.store_visits_table.rowCount()):
            code_item = self.store_visits_table.item(row, COL_STORE_CODE)
            if not code_item:
                continue
            store_code = code_item.text().strip()
            if store_code:
                store_orders[store_code] = row + 1
                store_includes[store_code] = _visit_include_checked(self.store_visits_table, row)
        return store_orders, store_includes

    def _fill_visit_table_row(
        self,
        row: int,
        *,
        store_code: str = "",
        store_name: str = "",
        in_time: str = "",
        out_time: str = "",
        stay: str = "",
        travel: str = "",
        profit: str = "0",
        qty: str = "0",
        rating: float = 0,
        notes: str = "",
        include_checked: bool = True,
        visit_order: Optional[str] = None,
        order_editable: bool = True,
    ) -> None:
        """店舗訪問詳細テーブルの1行を標準構成で埋める"""
        order_text = visit_order if visit_order is not None else str(row + 1)
        order_item = QTableWidgetItem(order_text)
        if not order_editable:
            order_item.setFlags(order_item.flags() & ~Qt.ItemIsEditable)
        self.store_visits_table.setItem(row, COL_VISIT_ORDER, order_item)
        self._set_visit_row_checkbox(row, include_checked)
        self.store_visits_table.setItem(row, COL_STORE_CODE, QTableWidgetItem(store_code))
        self.store_visits_table.setItem(row, COL_STORE_NAME, QTableWidgetItem(store_name))
        self.store_visits_table.setItem(row, COL_IN_TIME, QTableWidgetItem(in_time))
        self.store_visits_table.setItem(row, COL_OUT_TIME, QTableWidgetItem(out_time))
        self.store_visits_table.setItem(row, COL_STAY, QTableWidgetItem(stay))
        self.store_visits_table.setItem(row, COL_TRAVEL, QTableWidgetItem(travel))
        self.store_visits_table.setItem(row, COL_PROFIT, QTableWidgetItem(profit))
        self.store_visits_table.setItem(row, COL_QTY, QTableWidgetItem(qty))
        star_widget = StarRatingWidget(self.store_visits_table, rating=rating, star_size=14)
        star_widget.rating_changed.connect(lambda rating, r=row: self.on_star_rating_changed(r, rating))
        self.store_visits_table.setCellWidget(row, COL_STAR, star_widget)
        notes_item = QTableWidgetItem(notes)
        if notes:
            notes_item.setToolTip(notes)
        self.store_visits_table.setItem(row, COL_NOTES, notes_item)

    @staticmethod
    def _merge_notes_for_template_export(*parts: str) -> str:
        """カンマ区切りの備考を結合し、トークン単位で重複を除いて Excel 出力用の1文字列にする。"""
        seen: List[str] = []
        for part in parts:
            for seg in str(part or "").split(","):
                s = seg.strip()
                if s and s not in seen:
                    seen.append(s)
        return ", ".join(seen)

    @staticmethod
    def _resolve_store_master_notes(store_info: Optional[Dict[str, Any]]) -> str:
        """stores.notes と custom_fields.notes を読み取り用に1つにまとめる（旧データ互換）。"""
        if not store_info:
            return ""
        sql_notes = str(store_info.get("notes", "") or "").strip()
        cf_notes = str((store_info.get("custom_fields") or {}).get("notes", "") or "").strip()
        return RouteSummaryVisitTableMixin._merge_notes_for_template_export(sql_notes, cf_notes)

    @staticmethod
    def _visit_store_code_from_dict(store: Dict[str, Any]) -> str:
        code = (store.get("store_code") or "").strip()
        if code:
            return code
        return (store.get("supplier_code") or "").strip()

    def _table_notes_at_row(self, row: int) -> str:
        notes_item = self.store_visits_table.item(row, COL_NOTES)
        if not notes_item:
            return ""
        return notes_item.text().strip()

    def _persist_visit_table_notes_to_store_master(self) -> tuple[int, int]:
        """店舗訪問テーブルの備考列を店舗マスタ（stores.notes）へ上書き保存する。"""
        updated = 0
        skipped = 0
        for row in range(self.store_visits_table.rowCount()):
            code_item = self.store_visits_table.item(row, COL_STORE_CODE)
            store_code = code_item.text().strip() if code_item else ""
            if not store_code:
                skipped += 1
                continue
            table_notes = self._table_notes_at_row(row)
            if self.store_db.set_store_notes_by_code(store_code, table_notes):
                updated += 1
            else:
                skipped += 1
                print(f"店舗マスタ備考の上書きをスキップ（店舗未登録）: {store_code}")
        return updated, skipped

    def get_stores_from_table(self, for_template_output: bool = False) -> List[Dict[str, Any]]:
        """テーブルから訪問順序に基づいて店舗一覧を取得

        for_template_output=True のときはチェックが入っている店舗のみ返す。
        """
        try:
            stores = []
            table = self.store_visits_table
            
            # テーブルの行数
            row_count = table.rowCount()
            if row_count == 0:
                return []
            
            # 各行から訪問順序と店舗コードを取得
            table_data = []
            for row in range(row_count):
                if for_template_output and not _visit_include_checked(table, row):
                    continue

                # 訪問順序
                visit_order_item = table.item(row, COL_VISIT_ORDER)
                visit_order = None
                if visit_order_item:
                    try:
                        visit_order = int(visit_order_item.text())
                    except (ValueError, AttributeError):
                        visit_order = row + 1  # デフォルト値
                else:
                    visit_order = row + 1
                
                # 店舗コード
                store_code_item = table.item(row, COL_STORE_CODE)
                store_code = store_code_item.text().strip() if store_code_item else ''
                
                # 店舗名
                store_name_item = table.item(row, COL_STORE_NAME)
                store_name = store_name_item.text().strip() if store_name_item else ''
                
                if store_code:  # 店舗コードがある行のみ処理
                    table_data.append({
                        'visit_order': visit_order,
                        'store_code': store_code,
                        'store_name': store_name,
                        'row': row
                    })
            
            # 訪問順序でソート
            table_data.sort(key=lambda x: x['visit_order'])
            
            # 店舗マスタから詳細情報を取得
            for data in table_data:
                store_code = data['store_code']
                row = data['row']
                table_notes = self._table_notes_at_row(row)
                store_info = self.store_db.get_store_by_code(store_code)
                if store_info:
                    # 店舗マスタの情報をコピー
                    store = dict(store_info)
                    # テーブルの店舗名を優先（ユーザーが変更している可能性があるため）
                    if data['store_name']:
                        store['store_name'] = data['store_name']
                    # テーブル備考を正とする（空のときはマスタ備考をExcelへ）
                    if table_notes:
                        store["notes"] = table_notes
                    else:
                        store["notes"] = self._resolve_store_master_notes(store_info)
                    stores.append(store)
                else:
                    # 店舗マスタにない場合はテーブルの情報のみで作成
                    store = {
                        'store_code': store_code,
                        'supplier_code': store_code,  # 互換性のため
                        'store_name': data['store_name'],
                        'notes': table_notes,
                    }
                    stores.append(store)
            
            return stores
        except Exception as e:
            print(f"テーブルから店舗一覧取得エラー: {e}")
            import traceback
            print(traceback.format_exc())
            return []

    def get_stores_for_route(self, route_name: str) -> List[Dict[str, Any]]:
        """指定されたルートの店舗一覧を取得（表示順序でソート）"""
        try:
            # 表示順序でソートされた店舗一覧を取得
            if hasattr(self.store_db, 'get_stores_for_route_ordered'):
                return self.store_db.get_stores_for_route_ordered(route_name)
            else:
                # 後方互換性のため、表示順序がない場合は従来の方法
                stores = self.store_db.list_stores()
                route_stores = [
                    store for store in stores
                    if store.get('affiliated_route_name') == route_name
                ]
                # display_orderでソート（存在しない場合は0）
                route_stores.sort(key=lambda x: (x.get('display_order', 0), x.get('store_name', '')))
                return route_stores
        except Exception as e:
            print(f"店舗一覧取得エラー: {e}")
            return []

    def setup_shortcuts(self):
        """ショートカットキーの設定"""
        # Ctrl+Z: Undo
        undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(self.undo_action)
        
        # Ctrl+Y: Redo
        redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        redo_shortcut.activated.connect(self.redo_action)

    def _snapshot_table_state(self):
        """現在のテーブル状態をスナップショットとして返す（星評価・チェック含む）"""
        state = []
        for row in range(self.store_visits_table.rowCount()):
            row_data = {}
            for col in range(self.store_visits_table.columnCount()):
                if col == COL_STAR:
                    star_widget = self.store_visits_table.cellWidget(row, col)
                    row_data[col] = int(star_widget.rating()) if star_widget else 0
                elif col == COL_VISIT_INCLUDE:
                    row_data[col] = _visit_include_checked(self.store_visits_table, row)
                else:
                    item = self.store_visits_table.item(row, col)
                    row_data[col] = item.text() if item else ''
            state.append(row_data)
        return state

    def save_table_state(self):
        """テーブルの現在の状態を保存（Undo用）"""
        state = self._snapshot_table_state()
        # 直前と同じ状態は保存しない（無駄な履歴を防止）
        if self.undo_stack and self.undo_stack[-1] == state:
            return
        self.undo_stack.append(state)
        if len(self.undo_stack) > self.max_undo_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def restore_table_state(self, state):
        """テーブルの状態を復元"""
        # 変更イベントを一時的に無効化
        self.store_visits_table.blockSignals(True)
        
        try:
            self.store_visits_table.setRowCount(len(state))
            for row_idx, row_data in enumerate(state):
                for col_idx, value in row_data.items():
                    col_idx_int = int(col_idx)
                    if col_idx_int == COL_STAR:
                        try:
                            rating = int(float(str(value))) if str(value) not in (None, '', 'None') else 0
                        except Exception:
                            rating = 0
                        star_widget = StarRatingWidget(self.store_visits_table, rating=rating)
                        star_widget.rating_changed.connect(lambda rating, r=row_idx: self.on_star_rating_changed(r, rating))
                        self.store_visits_table.setCellWidget(row_idx, col_idx_int, star_widget)
                    elif col_idx_int == COL_VISIT_INCLUDE:
                        self._set_visit_row_checkbox(row_idx, bool(value))
                    else:
                        item = QTableWidgetItem(str(value))
                        self.store_visits_table.setItem(row_idx, col_idx_int, item)
            
            # 訪問順序を再設定
            self.update_visit_order()
            # 行の高さを内容に合わせて自動調整（折り返しテキスト対応）
            self.store_visits_table.resizeRowsToContents()
            getattr(self, 'update_calculation_results', lambda: None)()
        finally:
            # 変更イベントを再有効化
            self.store_visits_table.blockSignals(False)

    def undo_action(self):
        """Undo操作"""
        if not self.undo_stack:
            QMessageBox.information(self, "情報", "元に戻す操作がありません")
            return
        
        # 現在の状態をRedoスタックに保存
        current_state = self._snapshot_table_state()
        self.redo_stack.append(current_state)
        
        # Undoスタックから前の状態を取得
        previous_state = self.undo_stack.pop()
        # 直前に保存された状態が現状態と同一の場合、さらに一つ前を使う
        if previous_state == current_state and self.undo_stack:
            previous_state = self.undo_stack.pop()
        if previous_state != current_state:
            self.restore_table_state(previous_state)
            QMessageBox.information(self, "完了", "操作を元に戻しました")
        else:
            QMessageBox.information(self, "情報", "元に戻す操作がありません")
        # 訪問順序を保存
        self.save_store_order()

    def redo_action(self):
        """Redo操作"""
        if not self.redo_stack:
            QMessageBox.information(self, "情報", "やり直す操作がありません")
            return
        
        # 現在の状態をUndoスタックに保存
        current_state = []
        for row in range(self.store_visits_table.rowCount()):
            row_data = {}
            for col in range(self.store_visits_table.columnCount()):
                item = self.store_visits_table.item(row, col)
                row_data[col] = item.text() if item else ''
            current_state.append(row_data)
        self.undo_stack.append(current_state)
        
        # Redoスタックから次の状態を復元
        next_state = self.redo_stack.pop()
        self.restore_table_state(next_state)
        
        # 訪問順序を保存
        self.save_store_order()
        
        QMessageBox.information(self, "完了", "操作をやり直しました")

    def on_table_item_changed(self, item):
        """テーブルのアイテムが変更されたときの処理"""
        # 頻繁に呼ばれるので、少し遅延させてから保存（連続変更を1回として扱う）
        if not hasattr(self, '_change_timer'):
            from PySide6.QtCore import QTimer
            self._change_timer = QTimer()
            self._change_timer.setSingleShot(True)
            def _batched_update():
                self.save_table_state()
                self.recalc_travel_times()
            self._change_timer.timeout.connect(_batched_update)
        
        # タイマーをリセット（500ms後に保存）
        self._change_timer.stop()
        self._change_timer.start(500)

    def _rebind_star_rating_signals(self) -> None:
        """星評価ウィジェットのシグナルを現在の行構成に合わせて再接続する。"""
        for row in range(self.store_visits_table.rowCount()):
            star_widget = self.store_visits_table.cellWidget(row, COL_STAR)
            if not isinstance(star_widget, StarRatingWidget):
                continue
            try:
                star_widget.rating_changed.disconnect()
            except Exception:
                pass
            star_widget.rating_changed.connect(lambda rating, r=row: self.on_star_rating_changed(r, rating))

    def on_rows_reordered_safe(self):
        """SafeInternalMoveTable での行並び替え後処理。"""
        self.on_rows_moved(None, 0, 0, None, 0)

    def on_rows_moved(self, parent, start, end, destination, row):
        """行移動時の処理（訪問順序を再設定）"""
        if getattr(self, "_is_reordering_rows", False):
            return
        self._is_reordering_rows = True

        # 変更イベントを一時的に無効化
        self.store_visits_table.blockSignals(True)
        
        try:
            # 訪問順序を再設定
            for i in range(self.store_visits_table.rowCount()):
                order_item = self.store_visits_table.item(i, COL_VISIT_ORDER)
                if order_item:
                    order_item.setText(str(i + 1))
            self._rebind_star_rating_signals()
            
            # 状態を保存
            self.save_table_state()
            
            # 訪問順序を保存
            self.save_store_order()
            getattr(self, 'update_calculation_results', lambda: None)()
        finally:
            # 変更イベントを再有効化
            self.store_visits_table.blockSignals(False)
            self._is_reordering_rows = False

    def save_store_order(self):
        """現在の訪問順序をデータベースに保存（自動保存用）"""
        try:
            route_name = self.route_code_combo.currentText().strip()
            if not route_name:
                return
            
            store_orders, store_includes = self._collect_visit_order_and_includes()
            if store_orders:
                if hasattr(self.store_db, 'update_store_display_order'):
                    self.store_db.update_store_display_order(
                        route_name, store_orders, store_includes
                    )
        except Exception as e:
            print(f"訪問順序保存エラー: {e}")

    def save_visit_order_to_db(self):
        """訪問順序をデータベースに保存（ボタンから明示的に呼び出し）"""
        try:
            route_name = self.route_code_combo.currentText().strip()
            if not route_name:
                QMessageBox.warning(self, "警告", "ルートが選択されていません。")
                return
            
            # テーブルにデータがあるか確認
            if self.store_visits_table.rowCount() == 0:
                QMessageBox.warning(self, "警告", "保存する店舗データがありません。")
                return
            
            store_orders, store_includes = self._collect_visit_order_and_includes()
            if not store_orders:
                QMessageBox.warning(self, "警告", "保存する店舗コードがありません。")
                return
            
            included_count = sum(1 for v in store_includes.values() if v)
            excluded_count = len(store_includes) - included_count
            
            # データベースに保存
            if hasattr(self.store_db, 'update_store_display_order'):
                success = self.store_db.update_store_display_order(
                    route_name, store_orders, store_includes
                )
                if success:
                    QMessageBox.information(
                        self, 
                        "保存完了", 
                        f"訪問順序とテンプレート出力設定を保存しました。\n\n"
                        f"ルート: {route_name}\n"
                        f"保存件数: {len(store_orders)}件\n"
                        f"テンプレート出力: {included_count}件"
                        + (f"（除外 {excluded_count}件）" if excluded_count else "")
                        + "\n\n"
                        f"次回同じルートを呼び出した時に、保存された順序とチェック状態で表示されます。"
                    )
                else:
                    QMessageBox.warning(self, "エラー", "訪問順序の保存に失敗しました。")
            else:
                QMessageBox.warning(self, "エラー", "データベースに保存機能がありません。")
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"訪問順序保存エラー: {e}")
            print(f"エラー詳細:\n{error_detail}")
            QMessageBox.critical(
                self, 
                "エラー", 
                f"訪問順序の保存中にエラーが発生しました:\n{str(e)}\n\n詳細はコンソールを確認してください。"
            )

    def auto_add_stores(self):
        """選択されたルートの店舗を自動追加（重複チェック付き）"""
        # 変更前の状態を保存
        self.save_table_state()
        
        # 店舗マスタから「店舗コード」として使う値を取得するヘルパー
        # 優先: 店舗コード（store_code） → フォールバック: 仕入れ先コード
        def _get_visit_store_code(store: dict) -> str:
            # 1. 店舗コードを優先
            code = (store.get('store_code') or '').strip()
            if code:
                return code
            # 2. 店舗コードが空の場合だけ仕入れ先コードを使用
            return (store.get('supplier_code') or '').strip()
        
        try:
            route_name = self.route_code_combo.currentText().strip()
            if not route_name:
                QMessageBox.warning(self, "警告", "ルートを選択してください")
                return
            
            # 選択されたルートの店舗一覧を取得
            stores = self.get_stores_for_route(route_name)
            if not stores:
                QMessageBox.information(self, "情報", f"ルート「{route_name}」に登録されている店舗がありません")
                return
            
            # 既存の店舗コード一覧を取得（重複チェック用）
            existing_codes = set()
            for row in range(self.store_visits_table.rowCount()):
                code_item = self.store_visits_table.item(row, COL_STORE_CODE)
                if code_item:
                    code = code_item.text().strip()
                    if code:
                        existing_codes.add(code)
            
            # 追加する店舗をフィルタリング（重複を除外）
            stores_to_add = [
                store for store in stores
                if _get_visit_store_code(store) and _get_visit_store_code(store) not in existing_codes
            ]
            
            if not stores_to_add:
                QMessageBox.information(self, "情報", "追加可能な店舗がありません（すべて既に追加済みです）")
                return
            
            # 既存の行数を取得
            current_rows = self.store_visits_table.rowCount()
            
            # 店舗をテーブルに追加
            for i, store in enumerate(stores_to_add):
                row = current_rows + i
                self.store_visits_table.insertRow(row)
                visit_code = _get_visit_store_code(store)
                include_checked = _template_include_from_db_value(store.get('template_include'))
                any_code = visit_code
                store_info = self.store_db.get_store_by_code(any_code) if any_code else None
                notes = self._resolve_store_master_notes(store_info) if store_info else (
                    store.get('notes', '') or ''
                )
                self._fill_visit_table_row(
                    row,
                    store_code=visit_code,
                    store_name=store.get('store_name', ''),
                    notes=notes,
                    include_checked=include_checked,
                )
            
            # 訪問順序を再設定
            self.update_visit_order()
            
            # 訪問順序を保存
            self.save_store_order()
            
            # 行の高さを内容に合わせて自動調整（折り返しテキスト対応）
            self.store_visits_table.resizeRowsToContents()
            
            # 変更後の状態を保存
            self.save_table_state()
            
            QMessageBox.information(self, "完了", f"{len(stores_to_add)}件の店舗を追加しました")
            getattr(self, 'update_calculation_results', lambda: None)()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"店舗自動追加中にエラーが発生しました:\n{str(e)}")

    def update_visit_order(self):
        """訪問順序を再設定"""
        for i in range(self.store_visits_table.rowCount()):
            order_item = self.store_visits_table.item(i, COL_VISIT_ORDER)
            if order_item:
                order_item.setText(str(i + 1))
        # 順序が変わったら移動時間も更新
        self.recalc_travel_times()

    def recalc_travel_times(self):
        """滞在時間と移動時間（分）を自動計算して反映"""
        try:
            row_count = self.store_visits_table.rowCount()
            if row_count == 0:
                return

            def parse_hhmm(text: str) -> Optional[QTime]:
                text = (text or '').strip()
                if not text:
                    return None
                # HH:mm または H:mm を許容
                parts = text.split(':')
                if len(parts) != 2:
                    return None
                try:
                    h = int(parts[0])
                    m = int(parts[1])
                    if 0 <= h < 24 and 0 <= m < 60:
                        return QTime(h, m)
                except ValueError:
                    return None
                return None

            def get_text(row: int, col: int) -> str:
                item = self.store_visits_table.item(row, col)
                return item.text() if item else ''

            # 各行の滞在時間（店舗OUT - 店舗IN）を算出
            for r in range(row_count):
                in_t = parse_hhmm(get_text(r, COL_IN_TIME))
                out_t = parse_hhmm(get_text(r, COL_OUT_TIME))
                if in_t and out_t:
                    mins = in_t.secsTo(out_t) // 60
                    mins = max(0, int(mins))
                    self.store_visits_table.setItem(r, COL_STAY, QTableWidgetItem(str(mins)))
                else:
                    self.store_visits_table.setItem(r, COL_STAY, QTableWidgetItem(''))

            # 1店舗目の移動時間は空（出発時間が削除されたため）
            if row_count > 0:
                self.store_visits_table.setItem(0, COL_TRAVEL, QTableWidgetItem(''))

            # 2店舗目以降: 前店舗OUT → 現在IN
            for r in range(1, row_count):
                prev_out = parse_hhmm(get_text(r - 1, COL_OUT_TIME))
                cur_in = parse_hhmm(get_text(r, COL_IN_TIME))
                if prev_out and cur_in:
                    mins = prev_out.secsTo(cur_in) // 60
                    mins = max(0, int(mins))
                    self.store_visits_table.setItem(r, COL_TRAVEL, QTableWidgetItem(str(mins)))
                else:
                    self.store_visits_table.setItem(r, COL_TRAVEL, QTableWidgetItem(''))
        except Exception as e:
            print(f"移動時間計算エラー: {e}")

    def reorder_by_visit_order(self):
        """訪問順序列に入力された数字に基づいて行を並び替える"""
        try:
            row_count = self.store_visits_table.rowCount()
            if row_count == 0:
                QMessageBox.information(self, "情報", "並び替える行がありません")
                return
            
            # 変更前の状態を保存（Undo用）
            self.save_table_state()
            
            # 各行のデータと訪問順序を取得
            rows_data = []
            for row in range(row_count):
                order_item = self.store_visits_table.item(row, COL_VISIT_ORDER)
                order_text = order_item.text().strip() if order_item else ""
                
                try:
                    order_num = int(order_text) if order_text else row + 1000
                except ValueError:
                    order_num = row + 1000
                
                row_data = {
                    'order': order_num,
                    'original_row': row,
                    'cells': [],
                    'include_checked': _visit_include_checked(self.store_visits_table, row),
                }
                
                for col in range(self.store_visits_table.columnCount()):
                    if col in (COL_VISIT_INCLUDE, COL_STAR):
                        row_data['cells'].append("")
                        continue
                    item = self.store_visits_table.item(row, col)
                    row_data['cells'].append(item.text() if item else "")
                
                star_widget = self.store_visits_table.cellWidget(row, COL_STAR)
                if star_widget and hasattr(star_widget, 'rating'):
                    row_data['star_rating'] = star_widget.rating()
                else:
                    row_data['star_rating'] = 0
                
                rows_data.append(row_data)
            
            # 訪問順序でソート
            rows_data.sort(key=lambda x: x['order'])
            
            # テーブルを一旦ブロック
            self.store_visits_table.blockSignals(True)
            
            try:
                # テーブルをクリアして再構築
                self.store_visits_table.setRowCount(0)
                self.store_visits_table.setRowCount(len(rows_data))
                
                for new_row, data in enumerate(rows_data):
                    for col, cell_text in enumerate(data['cells']):
                        if col in (COL_VISIT_INCLUDE, COL_STAR):
                            continue
                        if col == COL_VISIT_ORDER:
                            item = QTableWidgetItem(str(new_row + 1))
                        else:
                            item = QTableWidgetItem(cell_text)
                        self.store_visits_table.setItem(new_row, col, item)
                    
                    self._set_visit_row_checkbox(new_row, data.get('include_checked', True))
                    star_widget = StarRatingWidget(
                        self.store_visits_table, 
                        rating=data['star_rating'], 
                        star_size=14
                    )
                    star_widget.rating_changed.connect(
                        lambda rating, r=new_row: self.on_star_rating_changed(r, rating)
                    )
                    self.store_visits_table.setCellWidget(new_row, COL_STAR, star_widget)
                
            finally:
                self.store_visits_table.blockSignals(False)
            
            # 移動時間を再計算
            self.recalc_travel_times()
            
            # 訪問順序を保存
            self.save_store_order()
            
            # 変更後の状態を保存
            self.save_table_state()
            
            # 計算結果を更新
            getattr(self, 'update_calculation_results', lambda: None)()
            
            QMessageBox.information(self, "完了", "訪問順序に基づいて行を並び替えました")
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"並び替え中にエラーが発生しました:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def add_store_visit_row(self):
        """店舗訪問行を追加"""
        # 変更前の状態を保存
        self.save_table_state()
        
        row = self.store_visits_table.rowCount()
        self.store_visits_table.insertRow(row)
        self._fill_visit_table_row(row, include_checked=True)
        
        # 変更後の状態を保存
        self.save_table_state()

    def on_star_rating_changed(self, row: int, rating: int):
        """星評価が変更されたときの処理"""
        # データ変更をUndoスタックに保存
        self.on_table_item_changed(None)

    def clear_all_rows(self):
        """すべての行をクリア"""
        reply = QMessageBox.question(
            self,
            "確認",
            "すべての行を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 変更前の状態を保存
            self.save_table_state()
            
            self.store_visits_table.setRowCount(0)
            # 訪問順序を保存（クリア状態）
            self.save_store_order()
            getattr(self, 'update_calculation_results', lambda: None)()
            
            # 変更後の状態を保存
            self.save_table_state()
            
            QMessageBox.information(self, "完了", "すべての行を削除しました")

    def delete_store_visit_row(self):
        """選択された店舗訪問行を削除"""
        # 選択行の取得（行選択/セル選択の両対応）
        selected_indexes = self.store_visits_table.selectionModel().selectedRows()
        selected_rows = {idx.row() for idx in selected_indexes}
        if not selected_rows:
            current = self.store_visits_table.currentRow()
            if current >= 0:
                selected_rows = {current}
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除する行を選択してください")
            return
        
        # 変更前の状態を保存
        self.save_table_state()
        
        # 行番号を降順でソート（後ろから削除することでインデックスがずれない）
        for row in sorted(selected_rows, reverse=True):
            self.store_visits_table.removeRow(row)
        
        # 訪問順序を再設定
        self.update_visit_order()
        
        # 訪問順序を保存
        self.save_store_order()
        
        # 変更後の状態を保存
        self.save_table_state()
        
        getattr(self, 'update_calculation_results', lambda: None)()

    def _get_table_item(self, row: int, col: int) -> str:
        item = self.store_visits_table.item(row, col)
        return item.text() if item else ''

