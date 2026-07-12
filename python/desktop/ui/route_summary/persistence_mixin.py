#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RouteSummary RouteSummaryPersistenceMixin."""
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



class RouteSummaryPersistenceMixin:
    def load_saved_data(self, route_id: int):
        """指定IDの保存データを読み込む"""
        try:
            row = self.route_db.get_route_summary(route_id)
            if not row:
                QMessageBox.information(self, "情報", "保存済みデータが見つかりませんでした")
                return
            self.current_route_id = route_id
            # 上部フィールド
            self.route_date_edit.setDateTime(QDateTime.fromString(row.get('route_date',''), 'yyyy-MM-dd'))
            
            # ルートコードを読み込んだルートに更新（日本語名で表示）
            route_code = row.get('route_code', '')
            
            if route_code:
                # シグナルを一時的にブロック（currentTextChangedが発火しないように）
                self.route_code_combo.blockSignals(True)
                try:
                    # コンボボックスのアイテムを先に更新（最新のルート一覧を反映）
                    self.update_route_codes()
                    
                    # ルートコードから日本語名を取得
                    route_name = self.store_db.get_route_name_by_code(route_code)
                    print(f"\n=== 保存データ読み込みデバッグ ===")
                    print(f"DBから取得したroute_code: '{route_code}'")
                    print(f"get_route_name_by_code('{route_code}') の結果: '{route_name}'")
                    
                    # もし取得できなかった場合、ルートコードが既に日本語名の可能性がある
                    if not route_name:
                        # ルートコードがそのまま日本語名の場合（後方互換性のため）
                        # コンボボックスにその値があるかチェック
                        if self.route_code_combo.findText(route_code) >= 0:
                            route_name = route_code
                            print(f"route_codeが直接日本語名として存在: '{route_code}'")
                    
                    display_value = route_name if route_name else route_code
                    print(f"表示値（display_value）: '{display_value}'")
                    
                    # コンボボックスに該当するアイテムがあるかチェック
                    idx = self.route_code_combo.findText(display_value)
                    print(f"findText('{display_value}') の結果: idx={idx}")
                    
                    if idx >= 0:
                        # アイテムが見つかった場合は選択
                        self.route_code_combo.setCurrentIndex(idx)
                        print(f"setCurrentIndex({idx}) を実行")
                    else:
                        # アイテムが見つからない場合は追加してから選択
                        print(f"アイテムが見つからないため追加します")
                        self.route_code_combo.addItem(display_value)
                        idx = self.route_code_combo.findText(display_value)
                        if idx >= 0:
                            self.route_code_combo.setCurrentIndex(idx)
                            print(f"追加後に setCurrentIndex({idx}) を実行")
                        else:
                            # 最後の手段：直接テキストを設定（編集可能なので）
                            self.route_code_combo.setCurrentText(display_value)
                            print(f"直接 setCurrentText('{display_value}') を実行")
                    
                    # 最終的な表示値を確認
                    final_display = self.route_code_combo.currentText()
                    print(f"最終的な表示値: '{final_display}'")
                    print(f"==============================\n")
                finally:
                    # シグナルのブロックを解除
                    self.route_code_combo.blockSignals(False)
                    self._sync_google_map_url_from_selected_route()
            else:
                # ルートコードが空の場合は、コンボボックスを更新してクリア
                self.update_route_codes()
                self.route_code_combo.setCurrentText('')
                self._sync_google_map_url_from_selected_route("")
            # 出発時間・帰宅時間・経費・備考は削除されたため、読み込み処理をスキップ
            
            # 店舗訪問詳細
            visits = self.route_db.get_store_visits_by_route(route_id)
            # ルート名からコード→店名の簡易マップを作成（補完用）
            code_to_name = {}
            try:
                route_name = self.route_code_combo.currentText().strip()
                if route_name:
                    for s in self.get_stores_for_route(route_name):
                        c = s.get('store_code') or s.get('supplier_code')
                        n = s.get('store_name')
                        if c and n:
                            code_to_name[c] = n
            except Exception:
                pass
            self.store_visits_table.blockSignals(True)
            try:
                self.store_visits_table.setRowCount(len(visits))
                for i, v in enumerate(visits):
                    code = v.get('store_code', '')
                    store_name = code_to_name.get(code, '')
                    if not store_name and code:
                        try:
                            s = self.store_db.get_store_by_code(code)
                            store_name = (s or {}).get('store_name', '')
                        except Exception:
                            store_name = ''
                    store_in_time = v.get('store_in_time') or ''
                    store_out_time = v.get('store_out_time') or ''
                    try:
                        store_in_display = store_in_time.split(' ')[1][:5] if ' ' in store_in_time else store_in_time[:5]
                    except Exception:
                        store_in_display = ''
                    try:
                        store_out_display = store_out_time.split(' ')[1][:5] if ' ' in store_out_time else store_out_time[:5]
                    except Exception:
                        store_out_display = ''
                    gross_profit = v.get('store_gross_profit')
                    profit_text = '0' if gross_profit in (None, '') else str(int(float(gross_profit)))
                    item_count = v.get('store_item_count')
                    qty_text = '0' if item_count in (None, '') else str(int(item_count))
                    existing_rating = v.get('store_rating')
                    try:
                        rating_value = float(existing_rating) if existing_rating not in (None, '') else 0.0
                    except (TypeError, ValueError):
                        rating_value = 0.0
                    store_notes = v.get('store_notes', '') or ''
                    if code:
                        try:
                            master_row = self.store_db.get_store_by_code(code)
                            if master_row:
                                store_notes = self._resolve_store_master_notes(master_row) or store_notes
                                include_checked = _template_include_from_db_value(master_row.get('template_include'))
                            else:
                                include_checked = True
                        except Exception:
                            include_checked = True
                    else:
                        include_checked = True
                    self._fill_visit_table_row(
                        i,
                        store_code=code,
                        store_name=store_name,
                        in_time=store_in_display,
                        out_time=store_out_display,
                        stay=str(v.get('stay_duration') or ''),
                        travel=str(v.get('travel_time_from_prev') or ''),
                        profit=profit_text,
                        qty=qty_text,
                        rating=rating_value,
                        notes=store_notes,
                        include_checked=include_checked,
                        order_editable=False,
                    )
            finally:
                self.store_visits_table.blockSignals(False)
            
            self.auto_calculate_store_ratings()
            self.update_visit_order()
            getattr(self, 'update_calculation_results', lambda: None)()
            # Undo基点
            self.undo_stack.clear(); self.redo_stack.clear(); self.save_table_state()
            QMessageBox.information(self, "完了", "保存済みデータを読み込みました")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存済みデータの読み込みに失敗しました:\n{str(e)}")

    def delete_saved_data(self, route_id: int):
        """指定IDの保存済みデータを削除"""
        try:
            target_id = route_id
            reply = QMessageBox.question(
                self,
                "削除確認",
                "この保存データを削除しますか？（店舗訪問詳細も削除されます）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            ok = self.route_db.delete_route_summary(int(target_id))
            if ok:
                # 画面側はクリア
                if self.current_route_id == target_id:
                    self.current_route_id = None
                self.store_visits_table.setRowCount(0)
                self.undo_stack.clear(); self.redo_stack.clear(); self.save_table_state()
                QMessageBox.information(self, "完了", "保存データを削除しました")
            else:
                QMessageBox.warning(self, "警告", "削除できませんでした")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存データの削除に失敗しました:\n{str(e)}")

    def open_saved_history(self):
        """保存履歴ダイアログを開き、読み込み/削除を実行"""
        dlg = SavedRoutesDialog(self.route_db, self.store_db, self)
        res = dlg.exec()
        if res == QDialog.Accepted:
            action, route_id = dlg.get_result()
            if action == 'load' and route_id:
                self.load_saved_data(route_id)
            elif action == 'delete' and route_id:
                self.delete_saved_data(route_id)

    def invalidate_stale_route_binding(self, route_data: Dict[str, Any]) -> None:
        """画面の日付・ルートコードと current_route_id の指す行が一致しなければ ID を解除する。

        誤ったテンプレで一時保存したあと、正しいテンプレを読み込んだのに古い ID が残っていると、
        save_data が同日同コードの解決をスキップして別ルート行を上書きしてしまうのを防ぐ。
        """
        if not self.current_route_id:
            return
        row = self.route_db.get_route_summary(self.current_route_id)
        if not row:
            self.current_route_id = None
            return
        want_date = str(route_data.get('route_date') or '').strip()
        want_code = str(route_data.get('route_code') or '').strip()
        got_date = str(row.get('route_date') or '').strip()
        got_code = str(row.get('route_code') or '').strip()
        if got_date != want_date or got_code != want_code:
            self.current_route_id = None

    def save_data(self):
        """データを保存"""
        try:
            route_data = self.get_route_data()
            store_visits = self.get_store_visits_data()
            self.invalidate_stale_route_binding(route_data)
            route_name_display = self.route_code_combo.currentText().strip() or route_data.get('route_code', '')
            
            if not route_data.get('route_code'):
                QMessageBox.warning(self, "警告", "ルートコードを入力してください")
                return
            
            self.save_store_order()
            
            stats = {}
            try:
                if self.calc_service:
                    stats = self.calc_service.calculate_route_statistics(route_data, store_visits) or {}
            except Exception:
                stats = {}
            stats_defaults = {
                'total_working_hours': 0,
                'estimated_hourly_rate': 0,
                'total_gross_profit': 0,
                'purchase_success_rate': 0,
                'avg_purchase_price': 0,
            }
            stats = {**stats_defaults, **stats}
            route_data.update(stats)
            route_data['route_name_display'] = route_name_display
            
            metrics = self.latest_summary_metrics or self._calculate_summary_metrics()
            if metrics:
                route_data['total_item_count'] = metrics.get('total_item_count', 0)
                route_data['total_gross_profit'] = metrics.get('total_gross_profit', 0.0)
                route_data['avg_purchase_price'] = metrics.get('avg_purchase_price', 0.0)
                route_data['total_purchase_amount'] = metrics.get('total_purchase_amount', 0.0)
                route_data['total_sales_amount'] = metrics.get('total_sales_amount', 0.0)
                route_data['total_working_hours'] = metrics.get('total_working_hours', 0.0)
                route_data['estimated_hourly_rate'] = metrics.get('estimated_hourly_rate', 0.0)
                # 仕入健全度・実効見込み利益（PRO版＋開発タブの統計結果）を引き継ぐ
                route_data['health_score_count'] = metrics.get('health_score_count')
                route_data['health_score_amount'] = metrics.get('health_score_amount')
                route_data['effective_profit'] = metrics.get('effective_profit')
                route_data['theoretical_profit'] = metrics.get('theoretical_profit')
                route_data['effective_rate'] = metrics.get('effective_rate')
            else:
                def _int_safe(x):
                    try:
                        if x is None or x == '':
                            return 0
                        return int(float(x))
                    except Exception:
                        return 0
                def _float_safe(x):
                    try:
                        if x is None or x == '':
                            return 0.0
                        return float(x)
                    except Exception:
                        return 0.0
                route_data['total_item_count'] = sum(_int_safe(v.get('store_item_count')) for v in store_visits)
                route_data['total_gross_profit'] = sum(_float_safe(v.get('store_gross_profit')) for v in store_visits)
                route_data['total_purchase_amount'] = 0.0
                route_data['total_sales_amount'] = 0.0
                total_working_hours = self._calculate_total_working_hours(route_data.get('departure_time'), route_data.get('return_time'))
                route_data['total_working_hours'] = total_working_hours
                route_data['estimated_hourly_rate'] = self._calculate_hourly_rate(route_data.get('total_gross_profit'), total_working_hours)
            
            # 同日・同ルートが存在する場合は上書き
            if not self.current_route_id:
                existing = self.route_db.get_route_summary_by_date_code(route_data.get('route_date'), route_data.get('route_code'))
                if existing:
                    self.current_route_id = existing.get('id')
            
            if self.current_route_id:
                self.route_db.update_route_summary(self.current_route_id, route_data)
                existing_visits = self.route_db.get_store_visits_by_route(self.current_route_id)
                for visit in existing_visits:
                    self.route_db.delete_store_visit(visit['id'])
            else:
                self.current_route_id = self.route_db.add_route_summary(route_data)
            
            for visit in store_visits:
                visit['route_summary_id'] = self.current_route_id
                self.route_db.add_store_visit(visit)

            try:
                if self.route_visit_db:
                    self.route_visit_db.replace_route_visits(
                        route_data.get('route_date'),
                        route_data.get('route_code'),
                        route_name_display,
                        store_visits
                    )
            except Exception as db_err:
                logging.exception(f"ルート訪問履歴の保存に失敗しました: {db_err}")
            
            QMessageBox.information(self, "完了", "データを保存しました")
            self.data_saved.emit(self.current_route_id)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"データ保存中にエラーが発生しました:\n{str(e)}")

    def get_route_data(self) -> Dict[str, Any]:
        """入力データを取得"""
        route_date = self.route_date_edit.dateTime().toString('yyyy-MM-dd')
        
        # route_dataから読み込んだ値を取得（テンプレート読み込み時に設定される）
        departure_time = self.route_data.get('departure_time') if hasattr(self, 'route_data') and self.route_data else None
        return_time = self.route_data.get('return_time') if hasattr(self, 'route_data') and self.route_data else None
        toll_fee_outbound = self.route_data.get('toll_fee_outbound') if hasattr(self, 'route_data') and self.route_data else 0
        toll_fee_return = self.route_data.get('toll_fee_return') if hasattr(self, 'route_data') and self.route_data else 0
        
        # デフォルト値の設定
        if not departure_time:
            departure_time = f"{route_date} 00:00:00"
        elif ' ' not in str(departure_time) and route_date:
            # HH:MM形式の場合はルート日付と結合
            departure_time = f"{route_date} {departure_time}:00"
        
        if not return_time:
            return_time = f"{route_date} 00:00:00"
        elif ' ' not in str(return_time) and route_date:
            # HH:MM形式の場合はルート日付と結合
            return_time = f"{route_date} {return_time}:00"

        route_name = ""
        if hasattr(self, 'route_data') and self.route_data:
            route_name = (
                str(self.route_data.get('route_name') or '')
                or str(self.route_data.get('route_name_display') or '')
            ).strip()
        if not route_name:
            route_name = self.route_code_combo.currentText().strip()
        
        return {
            'route_date': route_date,
            'route_code': self.get_selected_route_code(),
            'route_name': route_name,
            'route_name_display': route_name,
            'departure_time': departure_time,
            'return_time': return_time,
            'toll_fee_outbound': toll_fee_outbound if toll_fee_outbound else 0,
            'toll_fee_return': toll_fee_return if toll_fee_return else 0,
            'parking_fee': 0,
            'meal_cost': 0,
            'other_expenses': 0,
            'remarks': ''
        }

    def get_store_visits_data(self) -> List[Dict[str, Any]]:
        visits = []
        route_date = self.route_date_edit.dateTime().toString('yyyy-MM-dd')
        
        # 出発時刻・帰宅時間・往路高速代・復路高速代を除外する店舗コードリスト
        exclude_store_codes = ['出発時刻', '帰宅時刻', '往路高速代', '復路高速代']
        
        for i in range(self.store_visits_table.rowCount()):
            store_code = self._get_table_item(i, COL_STORE_CODE)
            
            # 出発時刻・帰宅時間・往路高速代・復路高速代は店舗訪問情報として扱わない
            if store_code in exclude_store_codes:
                continue
            
            star_widget = self.store_visits_table.cellWidget(i, COL_STAR)
            rating = star_widget.rating() if star_widget else 0
            
            # HH:MM形式の時間を取得してルート日付と結合
            in_time_str = self._get_table_item(i, COL_IN_TIME)
            out_time_str = self._get_table_item(i, COL_OUT_TIME)
            
            # HH:MMを yyyy-MM-dd HH:MM:SS に変換
            store_in_time = self._combine_datetime(route_date, in_time_str)
            store_out_time = self._combine_datetime(route_date, out_time_str)
            
            visit = {
                'visit_order': len(visits) + 1,  # 除外した行を考慮して訪問順序を再計算
                'store_code': store_code,
                'store_name': self._get_table_item(i, COL_STORE_NAME),
                'store_in_time': store_in_time,
                'store_out_time': store_out_time,
                'stay_duration': self._safe_float(self._get_table_item(i, COL_STAY)),
                'travel_time_from_prev': self._safe_float(self._get_table_item(i, COL_TRAVEL)),
                'store_gross_profit': self._safe_float(self._get_table_item(i, COL_PROFIT)),
                'store_item_count': self._safe_int(self._get_table_item(i, COL_QTY)),
                'store_rating': rating,
                'store_notes': self._get_table_item(i, COL_NOTES)
            }
            visits.append(visit)
        return visits

    @staticmethod
    def _format_hm(value: Optional[str]) -> str:
        if not value:
            return ''
        text = str(value)
        if ' ' in text:
            text = text.split(' ')[1]
        return text[:5]

    def apply_route_snapshot(self, route_data: Dict[str, Any], visits: List[Dict[str, Any]]):
        """外部から受け取ったルート情報・店舗情報をUIに反映"""
        if route_data is None:
            route_data = {}
        date_str = route_data.get('route_date')
        if date_str:
            try:
                self.route_date_edit.setDateTime(QDateTime.fromString(date_str, 'yyyy-MM-dd'))
            except Exception:
                pass
        display_value = route_data.get('route_name_display') or route_data.get('route_code', '')
        if display_value:
            self.route_code_combo.blockSignals(True)
            try:
                self.update_route_codes()
                idx = self.route_code_combo.findText(display_value)
                if idx >= 0:
                    self.route_code_combo.setCurrentIndex(idx)
                else:
                    self.route_code_combo.addItem(display_value)
                    idx = self.route_code_combo.findText(display_value)
                    if idx >= 0:
                        self.route_code_combo.setCurrentIndex(idx)
                    else:
                        self.route_code_combo.setCurrentText(display_value)
            finally:
                self.route_code_combo.blockSignals(False)
                self._sync_google_map_url_from_selected_route()
        # 出発時間・帰宅時間・経費・備考は削除されたため、読み込み処理をスキップ
        
        self.store_visits_table.blockSignals(True)
        try:
            self.store_visits_table.setRowCount(len(visits))
            for i, visit in enumerate(visits):
                self._fill_visit_table_row(
                    i,
                    visit_order=str(visit.get('visit_order', i + 1)),
                    store_code=visit.get('store_code', ''),
                    store_name=visit.get('store_name', ''),
                    in_time=self._format_hm(visit.get('store_in_time')),
                    out_time=self._format_hm(visit.get('store_out_time')),
                    stay=str(visit.get('stay_duration', '')),
                    travel=str(visit.get('travel_time_from_prev', '')),
                    profit=str(visit.get('store_gross_profit', '')),
                    qty=str(visit.get('store_item_count', '')),
                    rating=float(visit.get('store_rating', 0) or 0),
                    notes=visit.get('store_notes', '') or '',
                    include_checked=True,
                    order_editable=False,
                )
        finally:
            self.store_visits_table.blockSignals(False)
        self.update_visit_order()
        getattr(self, 'recalc_travel_times', lambda: None)()
        self.current_route_id = None

    def _combine_datetime(self, date_str: str, time_str: str) -> str:
        """ルート日付と時間（HH:MM）を結合してDATETIME形式にする"""
        if not time_str or not time_str.strip():
            return ''
        
        try:
            # HH:MM形式をチェック
            parts = time_str.strip().split(':')
            if len(parts) != 2:
                return ''
            
            h = int(parts[0])
            m = int(parts[1])
            
            if not (0 <= h <= 23 and 0 <= m <= 59):
                return ''
            
            # yyyy-MM-dd HH:MM:SS形式で返す
            return f"{date_str} {h:02d}:{m:02d}:00"
        except (ValueError, TypeError):
            return ''

    def _safe_float(self, value: str) -> Optional[float]:
        try:
            return float(value) if value else None
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value: str) -> Optional[int]:
        try:
            return int(float(value)) if value else None
        except (ValueError, TypeError):
            return None

