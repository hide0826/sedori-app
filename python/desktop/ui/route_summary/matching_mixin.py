#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RouteSummary RouteSummaryMatchingMixin."""
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



class RouteSummaryMatchingMixin:
    def run_matching(self):
        """照合処理実行（改良版：仕入管理データを参照）"""
        try:
            # 現在のルートIDが必要。未保存なら保存を促し、自動保存を試みる
            if not self.current_route_id:
                reply = QMessageBox.question(
                    self,
                    "未保存のルート",
                    "照合処理を実行するにはルートの保存が必要です。今すぐ保存しますか？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.save_data()
                if not self.current_route_id:
                    QMessageBox.warning(self, "警告", "ルートIDが未確定のため処理を中止しました")
                    return
            
            # 仕入管理データの確認
            if not self.inventory_widget:
                QMessageBox.warning(self, "警告", "仕入管理ウィジェットへの参照がありません")
                return
            
            inventory_data = self.inventory_widget.inventory_data
            if inventory_data is None or len(inventory_data) == 0:
                # データがない場合、CSVファイル選択にフォールバック
                reply = QMessageBox.question(
                    self,
                    "データなし",
                    "仕入管理にデータがありません。\nCSVファイルを選択して処理しますか？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    # 既存のCSVファイル選択処理を呼び出し
                    self.execute_matching_from_csv()
                return
            
            # 時間許容誤差の設定
            tolerance, ok = QInputDialog.getInt(
                self,
                "時間許容誤差",
                "時間許容誤差（分）:",
                30, 0, 120, 1
            )
            if not ok:
                return
            
            # データをJSON形式に変換（NaN値を事前に処理）
            # NaN値を空文字列に置換してからJSON化
            clean_data = inventory_data.fillna('')
            purchase_data = clean_data.to_dict(orient="records")
            
            # 照合処理（デスクトップと同一 DB を直接参照）
            QMessageBox.information(self, "処理中", "照合処理を実行しています...")
            from services.inventory_store_matching_runner import (
                InventoryStoreMatchingError,
                match_stores_from_purchase_data_local,
            )
            try:
                result = match_stores_from_purchase_data_local(
                    purchase_data=purchase_data,
                    route_summary_id=self.current_route_id,
                    time_tolerance_minutes=tolerance,
                )
            except InventoryStoreMatchingError as e:
                QMessageBox.warning(self, "エラー", str(e))
                return
            
            # 結果を仕入管理ウィジェットに反映
            if result.get('status') == 'success':
                # 照合後のデータで仕入管理データを更新
                result_data = result.get('data', [])
                if result_data:
                    import pandas as pd
                    updated_df = pd.DataFrame(result_data)
                    
                    # 仕入管理ウィジェットのデータを更新
                    self.inventory_widget.inventory_data = updated_df
                    self.inventory_widget.filtered_data = updated_df.copy()
                    self.inventory_widget.update_table()
                    self.inventory_widget.update_data_count()
                
                # 店舗コード別の粗利を集計してルートサマリーを更新
                self._update_route_gross_profit_from_inventory(result_data)
                
                # 結果表示
                stats = result.get('stats', {})
                matched_rows = stats.get('matched_rows', 0)
                total_rows = stats.get('total_rows', 0)
                
                msg = f"照合処理完了\n\n総行数: {total_rows}\nマッチした行数: {matched_rows}"
                msg += "\n\n仕入管理タブのデータが更新され、\nルートサマリーの想定粗利も自動計算されました。"
                QMessageBox.information(self, "照合処理完了", msg)
                self.update_calculation_results()
            else:
                QMessageBox.warning(self, "エラー", "照合処理に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"照合処理中にエラーが発生しました:\n{str(e)}")

    def execute_matching_from_csv(self):
        """照合処理実行（CSVファイル版）"""
        try:
            # 現在のルートIDが必要。未保存なら保存を促し、自動保存を試みる
            if not self.current_route_id:
                reply = QMessageBox.question(
                    self,
                    "未保存のルート",
                    "照合処理を実行するにはルートの保存が必要です。今すぐ保存しますか？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.save_data()
                if not self.current_route_id:
                    QMessageBox.warning(self, "警告", "ルートIDが未確定のため処理を中止しました")
                    return
            
            # APIクライアント確認
            if not self.api_client:
                from api.client import APIClient
                self.api_client = APIClient()
            
            # CSVファイル選択
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "仕入CSVファイルを選択",
                "",
                "CSVファイル (*.csv);;すべてのファイル (*)"
            )
            if not file_path:
                return
            
            # 時間許容誤差の設定（デフォルト30分）
            tolerance, ok = QInputDialog.getInt(
                self,
                "時間許容誤差",
                "時間許容誤差（分）:",
                30, 0, 120, 1
            )
            if not ok:
                return
            
            # API呼び出し
            QMessageBox.information(self, "処理中", "照合処理を実行しています...")
            result = self.api_client.inventory_match_stores(
                file_path=file_path,
                route_summary_id=self.current_route_id,
                time_tolerance_minutes=tolerance
            )
            
            # 結果表示
            stats = result.get('stats', {})
            matched_rows = stats.get('matched_rows', 0)
            total_rows = stats.get('total_rows', 0)
            
            msg = f"照合処理完了\n\n総行数: {total_rows}\nマッチした行数: {matched_rows}"
            if matched_rows > 0:
                msg += f"\n\nプレビュー（先頭10件）には店舗コードが自動付与されています。"
            
            QMessageBox.information(self, "照合処理完了", msg)
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"照合処理中にエラーが発生しました:\n{str(e)}")

    def recalculate_matching(self):
        """照合再計算処理: 仕入管理タブのデータから想定粗利・仕入れ点数を再計算"""
        try:
            if not self.current_route_id:
                QMessageBox.warning(self, "警告", "先にルートを保存してください")
                return
            
            # 仕入管理データの確認
            if not self.inventory_widget:
                QMessageBox.warning(self, "警告", "仕入管理ウィジェットへの参照がありません")
                return
            
            # 🔥 重要: テーブルから最新のデータを再取得（手入力データを含む）
            # テーブルの内容をinventory_dataに同期
            if hasattr(self.inventory_widget, 'sync_inventory_data_from_table'):
                sync_success = self.inventory_widget.sync_inventory_data_from_table()
                if not sync_success:
                    QMessageBox.warning(self, "警告", "テーブルデータの取得に失敗しました")
                    return
            
            # テーブルから直接データを取得（より確実な方法）
            if hasattr(self.inventory_widget, 'get_table_data'):
                table_data = self.inventory_widget.get_table_data()
                if table_data is not None and len(table_data) > 0:
                    inventory_data = table_data
                    print(f"\n=== 照合再計算: テーブルからデータ取得 ===")
                    print(f"取得件数: {len(inventory_data)}")
                    # デバッグ: K1-010の件数を確認
                    k1_010_count = 0
                    if '仕入先' in inventory_data.columns:
                        k1_010_count = len(inventory_data[inventory_data['仕入先'].astype(str).str.strip().str.replace('(', '').str.replace(')', '') == 'K1-010'])
                    print(f"K1-010の件数（テーブルから取得）: {k1_010_count}")
                    # inventory_dataも更新しておく（今後の処理で使用される可能性があるため）
                    self.inventory_widget.inventory_data = table_data.copy()
                    self.inventory_widget.filtered_data = table_data.copy()
                else:
                    inventory_data = self.inventory_widget.inventory_data
                    print(f"\n=== 照合再計算: テーブルデータが空のため、既存のinventory_dataを使用 ===")
            else:
                inventory_data = self.inventory_widget.inventory_data
                print(f"\n=== 照合再計算: get_table_dataメソッドがないため、既存のinventory_dataを使用 ===")
            
            if inventory_data is None or len(inventory_data) == 0:
                QMessageBox.warning(self, "警告", "仕入管理にデータがありません")
                return
            
            # 確認ダイアログ
            reply = QMessageBox.question(
                self,
                "照合再計算",
                "想定粗利・仕入れ点数を再計算しますか？\n\n他の項目は変更されません。",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            
            # データをJSON形式に変換（NaN値を事前に処理）
            clean_data = inventory_data.fillna('')
            purchase_data = clean_data.to_dict(orient="records")
            
            # 粗利再計算
            self._update_route_gross_profit_from_inventory(purchase_data)
            self.update_calculation_results()
            
            QMessageBox.information(self, "完了", "照合再計算が完了しました")
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"照合再計算中にエラーが発生しました:\n{str(e)}")

    def _update_route_gross_profit_from_inventory(self, inventory_data: List[Dict[str, Any]]):
        """
        仕入管理データから店舗コード別の粗利を集計してルートサマリーを更新
        
        計算方法:
        - 想定粗利: 各商品の「仕入れ個数 × 見込み利益」を店舗別に合計
        - 仕入れ点数: 店舗毎の「仕入れ個数」の総数（SUM）
        """
        try:
            if not self.current_route_id:
                return
            
            # 店舗コード別の粗利と仕入れ個数を集計
            store_profits = {}  # 想定粗利の合計（仕入れ個数 × 見込み利益）
            store_item_counts = {}  # 仕入れ個数の総数
            print(f"\n照合再計算開始: inventory_data件数={len(inventory_data)}")
            # デバッグ: K1-010のデータを全て確認
            k1_010_items = []
            for idx, item in enumerate(inventory_data):
                store_code_raw = item.get('仕入先') or item.get('supplier')
                if store_code_raw:
                    store_code_cleaned = store_code_raw.strip().strip('()') if isinstance(store_code_raw, str) else str(store_code_raw).strip().strip('()')
                    if store_code_cleaned == 'K1-010':
                        k1_010_items.append((
                            idx, 
                            item.get('商品名', 'N/A')[:30], 
                            item.get('仕入れ個数'), 
                            item.get('見込み利益')
                        ))
            
            if k1_010_items:
                print(f"  K1-010のデータ一覧 ({len(k1_010_items)}件):")
                for idx, name, count, profit in k1_010_items:
                    print(f"    行{idx}: {name}, 仕入れ個数={count}, 見込み利益={profit}")
            
            for idx, item in enumerate(inventory_data):
                store_code = item.get('仕入先') or item.get('supplier')
                if not store_code:
                    continue
                
                # 括弧を取り除いて正規化（例: "(K1-010)" → "K1-010"）
                if isinstance(store_code, str):
                    store_code = store_code.strip().strip('()')
                
                # 仕入れ個数と見込み利益を取得
                item_count = self._safe_float(item.get('仕入れ個数') or item.get('purchase_count') or item.get('quantity'))
                expected_profit = self._safe_float(item.get('見込み利益') or item.get('expected_profit') or item.get('profit'))
                
                # デバッグ: 値がNoneのデータを確認
                if store_code == 'K1-010':
                    if item_count is None or expected_profit is None:
                        print(f"  K1-010で値None検出: 仕入れ個数={item.get('仕入れ個数')}, 見込み利益={item.get('見込み利益')}")
                
                # 初期化
                if store_code not in store_profits:
                    store_profits[store_code] = 0
                if store_code not in store_item_counts:
                    store_item_counts[store_code] = 0
                
                # 仕入れ個数の総数を計算（店舗毎の合計）
                if item_count is not None and item_count >= 0:
                    store_item_counts[store_code] += int(item_count)
                
                # 想定粗利の計算（仕入れ個数 × 見込み利益）
                if item_count is not None and expected_profit is not None:
                    # 仕入れ個数が0以上の場合は計算に含める
                    if item_count >= 0:
                        profit_per_store = item_count * expected_profit
                        store_profits[store_code] += profit_per_store
                        # デバッグ: K1-010を含むデータを出力
                        if store_code == 'K1-010':
                            print(f"  K1-010処理: 仕入れ個数={item_count}, 見込み利益={expected_profit}, 粗利={profit_per_store}")
            
            # デバッグ: 集計結果を出力
            print(f"\n=== 照合再計算: 店舗別粗利集計結果 ===")
            for code in store_profits.keys():
                profit = store_profits.get(code, 0)
                item_count = store_item_counts.get(code, 0)
                print(f"  {code}: 粗利={profit}円, 仕入れ個数={item_count}")
            
            # ルートサマリーの店舗訪問詳細を取得
            visits = self.route_db.get_store_visits_by_route(self.current_route_id)
            
            # 各店舗訪問に粗利を設定
            for visit in visits:
                store_code = visit.get('store_code')
                if store_code in store_profits:
                    # 整数に変換（小数点なし）
                    visit['store_gross_profit'] = int(store_profits[store_code])
                    # 仕入れ点数は店舗毎の仕入れ個数の総数
                    visit['store_item_count'] = store_item_counts.get(store_code, 0)
                    # 粗利が0より大きい場合は仕入れ成功とみなす
                    visit['purchase_success'] = (store_profits[store_code] > 0)
                    print(f"  → {store_code} を更新: 粗利={visit['store_gross_profit']}, 仕入れ個数={visit['store_item_count']}")
                    logging.info(f"照合再計算: {store_code} を更新 - 粗利: {visit['store_gross_profit']}, 仕入れ個数: {visit['store_item_count']}")
                else:
                    # マッチしない店舗は0に設定
                    visit['store_gross_profit'] = 0
                    visit['store_item_count'] = 0
                    visit['purchase_success'] = False
                    print(f"  → {store_code} はマッチなし")
                    logging.info(f"照合再計算: {store_code} はマッチなし")
                
                # 店舗訪問詳細を更新
                result = self.route_db.update_store_visit(visit['id'], visit)
                if not result:
                    print(f"  ⚠️ {store_code} のDB更新に失敗")
                    logging.warning(f"照合再計算: {store_code} のDB更新に失敗")
            
            # テーブルを更新
            if self.current_route_id:
                # デバッグ: 更新前のDB状態を確認
                print(f"\n照合再計算完了: 更新した店舗数={len([v for v in visits if v.get('store_code') in store_profits])}")
                self.load_saved_data(self.current_route_id)

                # 画面のテーブルにも即時反映（DB読込に失敗した場合のフォールバック）
                try:
                    code_col = 1  # 店舗コード列
                    gross_col = 7  # 想定粗利列
                    count_col = 8  # 仕入れ点数列
                    for r in range(self.store_visits_table.rowCount()):
                        code_item = self.store_visits_table.item(r, code_col)
                        if not code_item:
                            continue
                        code = (code_item.text() or '').strip()
                        if not code:
                            continue
                        if code in store_profits or code in store_item_counts:
                            gp = int(store_profits.get(code, 0))
                            cnt = int(store_item_counts.get(code, 0))
                            self.store_visits_table.setItem(r, gross_col, QTableWidgetItem(str(gp)))
                            self.store_visits_table.setItem(r, count_col, QTableWidgetItem(str(cnt)))
                except Exception as _e:
                    print(f"UI反映フォールバックでエラー: {_e}")
            
            self.auto_calculate_store_ratings()

        except Exception as e:
            # エラーはログに記録するが、ユーザーには通知しない（主要処理は成功しているため）
            logging.error(f"ルート粗利更新エラー: {str(e)}")

