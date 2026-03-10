#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルートサマリー一覧ウィジェット

ルート登録機能で保存されたデータを一覧表示
- 日付/ルート名/総仕入点数/総想定粗利/平均仕入価格/総稼働時間/想定時給
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QLabel, QGroupBox
)
from PySide6.QtCore import Qt, Signal
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from database.route_db import RouteDatabase
from database.store_db import StoreDatabase


class RouteListWidget(QWidget):
    """ルートサマリー一覧ウィジェット"""
    
    # データ更新シグナル
    route_selected = Signal(int)  # route_idを送信
    
    def __init__(self):
        super().__init__()
        self.route_db = RouteDatabase()
        self.store_db = StoreDatabase()
        self._sync_done = False  # 同期フラグ
        
        self.setup_ui()
        self.load_routes()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # ヘッダー
        header_label = QLabel("ルートサマリー一覧")
        header_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(header_label)
        
        # 操作ボタン
        self.setup_action_buttons(layout)
        
        # テーブル
        self.setup_table(layout)
        
        # 統計情報
        self.update_statistics()
    
    def _safe_float(self, v):
        """数値以外やbytesが混ざっていても0.0にフォールバックする安全なfloat変換"""
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            try:
                # bytesの場合は一度decodeして再トライ
                if isinstance(v, bytes):
                    return float(v.decode("utf-8", errors="ignore") or 0)
            except Exception:
                pass
            return 0.0
    
    def setup_action_buttons(self, parent_layout):
        """操作ボタンの設定"""
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        
        # 更新ボタン
        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(self.load_routes)
        button_layout.addWidget(refresh_btn)

        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_selected_route)
        button_layout.addWidget(delete_btn)
        
        button_layout.addStretch()
        
        parent_layout.addWidget(button_group)
    
    def setup_table(self, parent_layout):
        """テーブルの設定"""
        table_group = QGroupBox("ルート一覧")
        table_layout = QVBoxLayout(table_group)
        
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # ソート機能を有効化
        self.table.setSortingEnabled(True)
        # チェックボックスを白ベースで見やすくする（ダークテーマ向け）
        self.table.setStyleSheet("""
            QTableView::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #cccccc;
                background-color: #ffffff;
            }
            QTableView::indicator:checked {
                image: none;
                background-color: #007bff;
                border: 1px solid #007bff;
            }
        """)
        
        # ヘッダー設定
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        # 文字数に応じて自動で幅をフィット
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionsClickable(True)
        
        # ダブルクリックで詳細表示
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        # チェックボックス変更時にフラグを更新
        self.table.itemChanged.connect(self.on_item_changed)
        
        table_layout.addWidget(self.table)
        
        # 統計情報ラベル
        self.stats_label = QLabel("統計: 読み込み中...")
        self.stats_label.setWordWrap(True)
        table_layout.addWidget(self.stats_label)
        
        parent_layout.addWidget(table_group)
    
    def load_routes(self):
        """ルート一覧を読み込む"""
        # 既存データの同期（毎回実行して最新化）
        # これにより既存データにも利益率とROIが計算・適用される
        try:
            self.route_db.sync_total_item_count_from_visits()
        except Exception:
            pass
        
        routes = self.route_db.list_route_summaries()
        self.update_table(routes)
        self.update_statistics()
    
    def update_table(self, routes: list):
        """テーブルを更新"""
        # ソート機能とシグナルを一時的に無効化（大量更新時の不要なイベント発火を防止）
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        
        columns = [
            "日付",
            "ルート名",
            "出品",   # 出品CSV作成完了
            "証憑",   # レシート確定完了
            "画像",   # 画像テンプレ書き込み完了
            "出発時間",
            "帰宅時間",
            "総仕入点数",
            "総仕入額",
            "総想定販売額",
            "総想定粗利",
            "想定利益率",
            "想定ROI",
            "平均仕入価格",
            "総稼働時間 (h)",
            "想定時給",
            "仕入健全度（件数）",
            "仕入健全度（金額）",
            "実効見込み利益",
            "実現率(%)",
        ]
        
        self.table.setRowCount(len(routes))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        
        # データの設定
        for i, route in enumerate(routes):
            # 日付
            self.table.setItem(i, 0, QTableWidgetItem(route.get('route_date', '')))
            
            # ルート名（スポットは route_display_name、通常はルートコードから変換）
            route_code = route.get('route_code', '')
            route_name = route.get('route_display_name') or self.store_db.get_route_name_by_code(route_code) or route_code
            self.table.setItem(i, 1, QTableWidgetItem(route_name or ''))

            # 出品 / 証憑 / 画像 チェックボックス
            for col_index, key in ((2, 'listing_completed'), (3, 'evidence_completed'), (4, 'images_completed')):
                flag_item = QTableWidgetItem()
                flag_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                checked = bool(route.get(key) or 0)
                flag_item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self.table.setItem(i, col_index, flag_item)
            
            # 出発時間・帰宅時間
            dep_time = self._format_time(route.get('departure_time'))
            ret_time = self._format_time(route.get('return_time'))
            self.table.setItem(i, 5, QTableWidgetItem(dep_time))
            self.table.setItem(i, 6, QTableWidgetItem(ret_time))
            
            # 総仕入点数
            total_item_count = route.get('total_item_count', 0) or 0
            item_count_item = QTableWidgetItem()
            item_count_item.setData(Qt.EditRole, total_item_count)
            item_count_item.setText(str(total_item_count))
            self.table.setItem(i, 7, item_count_item)

            # 総仕入額
            total_purchase_amount = self._safe_float(route.get('total_purchase_amount', 0))
            purchase_item = QTableWidgetItem()
            purchase_item.setData(Qt.EditRole, total_purchase_amount)
            purchase_item.setText(self._format_currency(total_purchase_amount))
            self.table.setItem(i, 8, purchase_item)

            # 総想定販売額
            total_sales_amount = self._safe_float(route.get('total_sales_amount', 0))
            sales_item = QTableWidgetItem()
            sales_item.setData(Qt.EditRole, total_sales_amount)
            sales_item.setText(self._format_currency(total_sales_amount))
            self.table.setItem(i, 9, sales_item)
            
            # 総想定粗利
            total_gross_profit = self._safe_float(route.get('total_gross_profit', 0))
            profit_item = QTableWidgetItem()
            profit_item.setData(Qt.EditRole, total_gross_profit)
            profit_item.setText(self._format_currency(total_gross_profit))
            self.table.setItem(i, 10, profit_item)
            
            # 想定利益率（常に再計算して更新）
            # 計算: (総想定粗利 / 総想定販売額) * 100
            total_sales_amount = self._safe_float(route.get('total_sales_amount', 0))
            if total_sales_amount > 0:
                expected_margin = (total_gross_profit / total_sales_amount) * 100
            else:
                expected_margin = 0.0
            expected_margin = round(expected_margin, 2)
            margin_item = QTableWidgetItem()
            margin_item.setData(Qt.EditRole, expected_margin)
            margin_item.setText(f"{expected_margin:.2f}")
            self.table.setItem(i, 11, margin_item)
            
            # 想定ROI（常に再計算して更新）
            # 計算: (総想定粗利 / 総仕入額) * 100
            total_purchase_amount = self._safe_float(route.get('total_purchase_amount', 0))
            if total_purchase_amount > 0:
                expected_roi = (total_gross_profit / total_purchase_amount) * 100
            else:
                expected_roi = 0.0
            expected_roi = round(expected_roi, 2)
            roi_item = QTableWidgetItem()
            roi_item.setData(Qt.EditRole, expected_roi)
            roi_item.setText(f"{expected_roi:.2f}")
            self.table.setItem(i, 12, roi_item)
            
            # 計算した値をデータベースに保存（既存データにも適用）
            route_id = route.get('id')
            if route_id:
                try:
                    # 既存のroute_dataを取得して更新
                    update_data = {
                        'total_purchase_amount': total_purchase_amount,
                        'total_sales_amount': total_sales_amount,
                        'total_gross_profit': total_gross_profit,
                        'expected_margin': expected_margin,
                        'expected_roi': expected_roi,
                    }
                    # 他のフィールドも保持
                    for key in ['route_date', 'route_code', 'departure_time', 'return_time',
                               'toll_fee_outbound', 'toll_fee_return', 'parking_fee',
                               'meal_cost', 'other_expenses', 'remarks',
                               'total_working_hours', 'estimated_hourly_rate',
                               'total_item_count', 'purchase_success_rate', 'avg_purchase_price']:
                        if key in route:
                            update_data[key] = route[key]
                    
                    self.route_db.update_route_summary(route_id, update_data)
                except Exception as e:
                    # エラーは無視（表示は継続）
                    print(f"利益率・ROIの保存エラー (route_id={route_id}): {e}")
            
            # 平均仕入価格
            avg_price = self._safe_float(route.get('avg_purchase_price', 0))
            avg_item = QTableWidgetItem()
            avg_item.setData(Qt.EditRole, avg_price)
            avg_item.setText(self._format_currency(avg_price))
            self.table.setItem(i, 13, avg_item)
            
            # 総稼働時間
            working_hours = route.get('total_working_hours', 0) or 0
            hours_item = QTableWidgetItem()
            hours_item.setData(Qt.EditRole, working_hours)
            hours_item.setText(self._format_hours(working_hours))
            self.table.setItem(i, 14, hours_item)
            
            # 想定時給
            hourly_rate = route.get('estimated_hourly_rate', 0) or 0
            rate_item = QTableWidgetItem()
            rate_item.setData(Qt.EditRole, hourly_rate)
            rate_item.setText(self._format_currency(hourly_rate))
            self.table.setItem(i, 15, rate_item)

            # 仕入健全度（件数）/（金額）/ 実効見込み利益 / 実現率
            from utils.settings_helper import is_pro_enabled
            if is_pro_enabled():
                # 件数
                count_text = route.get('health_score_count') or ""
                self.table.setItem(i, 16, QTableWidgetItem(str(count_text)))
                # 金額
                amount_text = route.get('health_score_amount') or ""
                self.table.setItem(i, 17, QTableWidgetItem(str(amount_text)))
                # 実効見込み利益
                eff_profit_val = self._safe_float(route.get('effective_profit'))
                eff_item = QTableWidgetItem()
                eff_item.setData(Qt.EditRole, eff_profit_val)
                eff_item.setText(self._format_currency(eff_profit_val))
                self.table.setItem(i, 18, eff_item)
                # 実現率(%)
                eff_rate_val = self._safe_float(route.get('effective_rate'))
                ratep_item = QTableWidgetItem()
                ratep_item.setData(Qt.EditRole, eff_rate_val)
                ratep_item.setText(f"{eff_rate_val:.1f}" if eff_rate_val is not None else "")
                self.table.setItem(i, 19, ratep_item)
            else:
                # PRO版でない場合は空欄
                self.table.setItem(i, 16, QTableWidgetItem(""))
                self.table.setItem(i, 17, QTableWidgetItem(""))
                self.table.setItem(i, 18, QTableWidgetItem(""))
                self.table.setItem(i, 19, QTableWidgetItem(""))
            
            # 各行にIDを保持（ダブルクリック時やチェック変更時の参照用）
            self.table.item(i, 0).setData(Qt.UserRole, route.get('id'))
        
        # ソート機能とシグナルを再有効化
        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        
        # 列幅の自動調整
        self.table.resizeColumnsToContents()
    
    def delete_selected_route(self):
        """選択中のルートサマリーを削除"""
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "選択してください", "削除するルートを選択してください。")
            return
        route_id = selected[0].data(Qt.UserRole)
        if not route_id:
            QMessageBox.warning(self, "削除できません", "対象のルートIDが取得できませんでした。")
            return
        reply = QMessageBox.question(
            self,
            "確認",
            "選択したルートサマリーを削除しますか？\n店舗訪問詳細も削除されます。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        if self.route_db.delete_route_summary(route_id):
            QMessageBox.information(self, "削除完了", "ルートサマリーを削除しました。")
            self.load_routes()
        else:
            QMessageBox.warning(self, "削除できません", "削除対象が見つかりませんでした。")
    
    def update_statistics(self):
        """統計情報を更新"""
        routes = self.route_db.list_route_summaries()
        total_routes = len(routes)
        total_items = sum(int(route.get('total_item_count') or 0) for route in routes)
        total_purchase = sum(self._safe_float(route.get('total_purchase_amount')) for route in routes)
        total_sales = sum(self._safe_float(route.get('total_sales_amount')) for route in routes)
        total_profit = sum(self._safe_float(route.get('total_gross_profit')) for route in routes)
        avg_hourly = 0.0
        hourly_values = [self._safe_float(route.get('estimated_hourly_rate')) for route in routes if route.get('estimated_hourly_rate') is not None]
        if hourly_values:
            avg_hourly = sum(hourly_values) / len(hourly_values)
        # 実効見込み利益・実現率（PRO版のみ集計）
        from utils.settings_helper import is_pro_enabled
        eff_profit_total = 0.0
        eff_rate_avg = 0.0
        if is_pro_enabled():
            eff_profit_total = sum(self._safe_float(route.get('effective_profit')) for route in routes)
            eff_rates = [self._safe_float(route.get('effective_rate')) for route in routes if route.get('effective_rate') is not None]
            if eff_rates:
                eff_rate_avg = sum(eff_rates) / len(eff_rates)
        self.stats_label.setText(
            f"統計: ルート数 {total_routes}件 / 総仕入点数 {total_items:,}点 / "
            f"総仕入額 {self._format_currency(total_purchase)} / "
            f"総想定販売額 {self._format_currency(total_sales)} / "
            f"総想定粗利 {self._format_currency(total_profit)} / "
            f"平均想定時給 {self._format_currency(avg_hourly)}"
            + (
                f" / 総実効見込み利益 {self._format_currency(eff_profit_total)} / "
                f"平均実現率 {eff_rate_avg:.1f}%"
                if is_pro_enabled() else ""
            )
        )
    
    def on_item_double_clicked(self, item: QTableWidgetItem):
        """ダブルクリック時の処理"""
        route_id = item.data(Qt.UserRole)
        if route_id:
            self.route_selected.emit(route_id)

    def on_item_changed(self, item: QTableWidgetItem):
        """チェックボックス変更時にDBのフラグを更新"""
        if not item or item.column() not in (2, 3, 4):
            return

        # 行のIDを取得
        id_item = self.table.item(item.row(), 0)
        if not id_item:
            return
        route_id = id_item.data(Qt.UserRole)
        if not route_id:
            return

        flag_map = {2: "listing_completed", 3: "evidence_completed", 4: "images_completed"}
        flag_name = flag_map.get(item.column())
        if not flag_name:
            return

        try:
            from database.route_db import RouteDatabase
            db = RouteDatabase()
            db.set_route_flag(route_id, flag_name, item.checkState() == Qt.Checked)
        except Exception as e:
            # エラーが出てもUIはそのままにしておき、コンソールにだけ出力
            print(f"ルートフラグ更新エラー (route_id={route_id}, flag={flag_name}): {e}")

    # ==================== ヘルパーメソッド ====================

    def _format_time(self, datetime_str: str) -> str:
        if not datetime_str:
            return ""
        try:
            parts = str(datetime_str).strip()
            if " " in parts:
                parts = parts.split(" ")[1]
            if "T" in parts:
                parts = parts.split("T")[1]
            return parts[:5]
        except Exception:
            return ""

    def _format_currency(self, value) -> str:
        try:
            if value is None:
                return "0"
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return "0"

    def _format_hours(self, value) -> str:
        try:
            if value is None:
                return "0.0"
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "0.0"

