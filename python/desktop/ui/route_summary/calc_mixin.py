#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RouteSummary RouteSummaryCalcMixin."""
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



class RouteSummaryCalcMixin:
    def update_calculation_results(self):
        """計算結果ラベルを最新状態に更新"""
        metrics = self._calculate_summary_metrics()
        self.latest_summary_metrics = metrics or {}

        if not metrics:
            self.calculation_label.setText("計算結果: データ未入力")
            return

        def fmt_number(value, digits=0):
            try:
                if value is None:
                    return "0"
                if digits == 0:
                    return f"{float(value):,.0f}"
                return f"{float(value):,.2f}"
            except (ValueError, TypeError):
                return "0"

        text = (
            f"日付: {metrics.get('route_date', '')} / ルート: {metrics.get('route_name', '')}\n"
            f"総仕入点数: {fmt_number(metrics.get('total_item_count'))}点 / "
            f"総仕入額: {fmt_number(metrics.get('total_purchase_amount'))}円 / "
            f"総想定販売額: {fmt_number(metrics.get('total_sales_amount'))}円\n"
            f"総想定粗利: {fmt_number(metrics.get('total_gross_profit'))}円 / "
            f"平均仕入価格: {fmt_number(metrics.get('avg_purchase_price'))}円\n"
            f"総稼働時間: {fmt_number(metrics.get('total_working_hours'), 2)}h / "
            f"想定時給: {fmt_number(metrics.get('estimated_hourly_rate'))}円"
        )
        self.calculation_label.setText(text)

    def auto_calculate_store_ratings(self):
        """店舗訪問テーブルの星評価を自動計算"""
        if not hasattr(self, "store_visits_table"):
            return
        row_count = self.store_visits_table.rowCount()
        for row in range(row_count):
            rating = self._calculate_store_rating_for_row(row)
            if rating <= 0:
                rating = 0.0
            else:
                rating = max(0.0, min(5.0, round(rating * 2) / 2))
            star_widget = self.store_visits_table.cellWidget(row, COL_STAR)
            if not isinstance(star_widget, StarRatingWidget):
                star_widget = StarRatingWidget(self.store_visits_table, rating=0, star_size=14)
                star_widget.rating_changed.connect(partial(self.on_star_rating_changed, row))
                self.store_visits_table.setCellWidget(row, COL_STAR, star_widget)
            # setRatingでシグナルが発火してUndo履歴が増えないよう一時的にブロック
            block_prev = star_widget.blockSignals(True)
            try:
                star_widget.setRating(rating)
            finally:
                star_widget.blockSignals(block_prev)

    def _calculate_store_rating_for_row(self, row: int) -> float:
        """指定行の星評価を算出"""
        qty = self._parse_float_value(self._get_table_item(row, COL_QTY))
        profit = self._parse_float_value(self._get_table_item(row, COL_PROFIT))
        stay = self._parse_float_value(self._get_table_item(row, COL_STAY))

        if qty <= 0 or profit <= 0:
            return 0
        stay = max(1.0, stay)

        base_score = self._determine_base_score(int(round(qty)))
        profit_per_minute = profit / stay

        profit_threshold = 190.0
        profit_scale = 30.0
        profit_factor = max(0.0, min(5.0, (profit_per_minute - profit_threshold) / profit_scale))

        base_weight = 0.7
        profit_weight = 0.3

        final_score = (base_weight * base_score) + (profit_weight * profit_factor)
        return max(0.0, min(5.0, final_score))

    def _determine_base_score(self, item_count: int) -> int:
        if item_count >= 10:
            return 5
        if item_count >= 7:
            return 4
        if item_count >= 5:
            return 3
        if item_count >= 3:
            return 2
        return 1

    def _parse_float_value(self, value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        text = text.replace(',', '')
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _calculate_total_working_hours(self, departure_time: Optional[str], return_time: Optional[str]) -> float:
        """総稼働時間（時間）を計算"""
        dep_dt = None
        ret_dt = None
        if self.calc_service:
            dep_dt = CalculationService.parse_datetime_string(departure_time)
            ret_dt = CalculationService.parse_datetime_string(return_time)
        if not dep_dt and departure_time:
            try:
                dep_dt = datetime.fromisoformat(departure_time.replace('Z', '+00:00'))
            except Exception:
                dep_dt = None
        if not ret_dt and return_time:
            try:
                ret_dt = datetime.fromisoformat(return_time.replace('Z', '+00:00'))
            except Exception:
                ret_dt = None
        if dep_dt and ret_dt:
            if self.calc_service:
                hours = CalculationService.calculate_total_working_hours(dep_dt, ret_dt)
                if hours is not None:
                    return max(round(hours, 2), 0.0)
            diff = (ret_dt - dep_dt).total_seconds() / 3600.0
            if diff < 0:
                diff = 0.0
            return round(diff, 2)
        return 0.0

    def _calculate_hourly_rate(self, gross_profit: Optional[float], working_hours: Optional[float]) -> float:
        """想定時給を計算"""
        gross = gross_profit or 0.0
        hours = working_hours or 0.0
        if self.calc_service:
            value = CalculationService.calculate_hourly_rate(gross, hours)
            if value is not None:
                return max(round(value, 2), 0.0)
        if hours > 0:
            return round(gross / hours, 2)
        return 0.0

    def _calculate_summary_metrics(self) -> Optional[Dict[str, Any]]:
        """現在の入力値からサマリー指標を算出"""
        try:
            route_date = self.route_date_edit.dateTime().toString('yyyy-MM-dd')
        except Exception:
            route_date = ''

        route_code = self.get_selected_route_code()
        route_name_display = self.route_code_combo.currentText().strip() or route_code
        try:
            if route_code:
                resolved = self.store_db.get_route_name_by_code(route_code)
                if resolved:
                    route_name_display = resolved
        except Exception:
            pass

        def to_float(value) -> Optional[float]:
            if value is None:
                return None
            try:
                if isinstance(value, str):
                    value = value.replace(',', '').strip()
                    if value == '':
                        return None
                return float(value)
            except (ValueError, TypeError):
                return None

        def to_int(value) -> Optional[int]:
            val = to_float(value)
            if val is None:
                return None
            return int(round(val))

        inventory_df = None
        # 3-6-9仕入管理タブにデータがあれば優先的に使用し、無ければ本番タブのデータを使う
        candidate_widgets = []
        if getattr(self, "inventory_widget_dev", None) is not None:
            candidate_widgets.append(self.inventory_widget_dev)
        if getattr(self, "inventory_widget_main", None) is not None:
            candidate_widgets.append(self.inventory_widget_main)

        for inv_widget in candidate_widgets:
            try:
                data = getattr(inv_widget, "inventory_data", None)
                if data is not None:
                    if hasattr(data, "iterrows"):
                        inventory_df = data.copy()
                    elif isinstance(data, list):
                        inventory_df = pd.DataFrame(data)
                if inventory_df is not None and len(inventory_df) > 0:
                    break
            except Exception:
                inventory_df = None

        total_purchase = 0.0
        total_sales = 0.0
        total_profit = 0.0
        total_items = 0
        # 仕入健全度・実効見込み利益（開発タブ + PRO版のみ）
        health_score_count = None
        health_score_amount = None
        effective_profit = None
        theoretical_profit = None
        effective_rate = None

        if inventory_df is not None and len(inventory_df) > 0:
            for _, row in inventory_df.iterrows():
                qty = to_float(
                    row.get('仕入れ個数')
                    or row.get('purchase_count')
                    or row.get('quantity')
                    or row.get('quantityPurchased')
                    or row.get('数量')
                ) or 0.0
                purchase_price = to_float(row.get('仕入れ価格') or row.get('purchasePrice') or row.get('cost_price'))
                sale_price = to_float(row.get('販売予定価格') or row.get('plannedPrice') or row.get('expected_sale_price'))
                profit_unit = to_float(row.get('見込み利益') or row.get('expected_profit') or row.get('profit') or row.get('expectedProfit'))

                total_items += int(round(qty))
                if purchase_price is not None:
                    total_purchase += purchase_price * qty
                if sale_price is not None:
                    total_sales += sale_price * qty
                if profit_unit is not None:
                    total_profit += profit_unit * qty

            if total_sales == 0 and total_purchase and total_profit:
                total_sales = total_purchase + total_profit
            if total_profit == 0 and total_sales and total_purchase:
                total_profit = total_sales - total_purchase

            # PRO版かつ開発タブのデータがあれば、仕入健全度・実効見込み利益も計算
            from utils.settings_helper import is_pro_enabled
            dev_widget = getattr(self, "inventory_widget_dev", None)
            if dev_widget is not None and getattr(dev_widget, "dev_mode", False) and is_pro_enabled():
                try:
                    # inventory_widget.py のロジックを流用
                    count_health = dev_widget._compute_health_score_3_6_9(inventory_df)
                    profit_health = dev_widget._compute_health_score_3_6_9_profit(inventory_df)
                    if count_health:
                        r3, r6, r9 = count_health.get("ratio_3"), count_health.get("ratio_6"), count_health.get("ratio_9")
                        level = count_health.get("level")
                        health_score_count = f"{r3}:{r6}:{r9}（{level}）"
                    if profit_health:
                        pr3, pr6, pr9 = profit_health.get("ratio_3"), profit_health.get("ratio_6"), profit_health.get("ratio_9")
                        plevel = profit_health.get("level")
                        eff_rate = profit_health.get("effective_rate")
                        total_profit_th = profit_health.get("total_profit")
                        effective_profit_val = profit_health.get("effective_profit")
                        health_score_amount = f"{pr3}:{pr6}:{pr9}（{plevel}）"
                        effective_profit = effective_profit_val
                        theoretical_profit = total_profit_th
                        effective_rate = eff_rate
                except Exception:
                    # 健全度計算でエラーが出ても、他のルート集計は継続
                    pass

        table_items = 0
        table_profit = 0.0
        for row in range(self.store_visits_table.rowCount()):
            qty = to_float(self._get_table_item(row, COL_QTY)) or 0.0
            table_items += int(round(qty))
            profit_val = to_float(self._get_table_item(row, COL_PROFIT)) or 0.0
            table_profit += profit_val

        if total_items == 0:
            total_items = table_items
        if total_profit == 0:
            total_profit = table_profit
        if total_sales == 0 and total_purchase and total_profit:
            total_sales = total_purchase + total_profit

        avg_purchase_price = 0.0
        if total_items > 0 and total_purchase:
            avg_purchase_price = total_purchase / total_items

        route_data_preview = self.get_route_data()
        working_hours = self._calculate_total_working_hours(
            route_data_preview.get('departure_time'),
            route_data_preview.get('return_time')
        )
        hourly_rate = self._calculate_hourly_rate(total_profit, working_hours)

        return {
            'route_date': route_date,
            'route_code': route_code,
            'route_name': route_name_display,
            'total_item_count': total_items,
            'total_purchase_amount': total_purchase,
            'total_sales_amount': total_sales,
            'total_gross_profit': total_profit,
            'avg_purchase_price': avg_purchase_price,
            'total_working_hours': working_hours,
            'estimated_hourly_rate': hourly_rate,
            'health_score_count': health_score_count,
            'health_score_amount': health_score_amount,
            'effective_profit': effective_profit,
            'theoretical_profit': theoretical_profit,
            'effective_rate': effective_rate,
        }

