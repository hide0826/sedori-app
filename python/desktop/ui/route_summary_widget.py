#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルートサマリー入力ウィジェット

ルートサマリーの入力・編集機能
- テンプレートファイルの読み込み
- ルート情報の入力・編集
- 店舗別情報の入力・編集
- 照合処理・店舗コード自動挿入
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QMessageBox, QFileDialog, QDateTimeEdit, QLineEdit,
    QTextEdit, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QDialog, QFormLayout, QDialogButtonBox, QTabWidget
)
from PySide6.QtCore import Qt, QDateTime, Signal
from PySide6.QtGui import QColor
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.route_db import RouteDatabase
from database.store_db import StoreDatabase

# サービス・ユーティリティのインポート（相対パス）
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from services.route_matching_service import RouteMatchingService
except ImportError:
    RouteMatchingService = None  # オプション機能として扱う

try:
    from services.calculation_service import CalculationService
except ImportError:
    CalculationService = None

try:
    from utils.template_generator import TemplateGenerator
except ImportError:
    TemplateGenerator = None


class RouteSummaryWidget(QWidget):
    """ルートサマリー入力ウィジェット"""
    
    data_saved = Signal(int)  # データ保存完了
    
    def __init__(self):
        super().__init__()
        self.route_db = RouteDatabase()
        self.store_db = StoreDatabase()
        self.matching_service = RouteMatchingService() if RouteMatchingService else None
        self.calc_service = CalculationService() if CalculationService else None
        
        self.current_route_id = None
        self.route_data = {}
        self.store_visits = []
        
        self.setup_ui()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：操作ボタン
        self.setup_action_buttons(layout)
        
        # 中央：タブ（ルート情報・店舗訪問詳細）
        self.setup_tabs(layout)
        
        # 下部：計算結果表示
        self.setup_calculation_results(layout)
    
    def setup_action_buttons(self, parent_layout):
        """操作ボタンの設定"""
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        
        # テンプレート生成ボタン
        template_btn = QPushButton("テンプレート生成")
        template_btn.clicked.connect(self.generate_template)
        template_btn.setStyleSheet("background-color: #28a745; color: white;")
        button_layout.addWidget(template_btn)
        
        # テンプレート読み込みボタン
        load_template_btn = QPushButton("テンプレート読み込み")
        load_template_btn.clicked.connect(self.load_template)
        button_layout.addWidget(load_template_btn)
        
        # 照合処理ボタン
        matching_btn = QPushButton("照合処理実行")
        matching_btn.clicked.connect(self.run_matching)
        matching_btn.setStyleSheet("background-color: #007bff; color: white;")
        button_layout.addWidget(matching_btn)
        
        # 保存ボタン
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_data)
        save_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        button_layout.addWidget(save_btn)
        
        # 新規作成ボタン
        new_btn = QPushButton("新規作成")
        new_btn.clicked.connect(self.new_route)
        button_layout.addWidget(new_btn)
        
        button_layout.addStretch()
        
        parent_layout.addWidget(button_group)
    
    def setup_tabs(self, parent_layout):
        """タブの設定"""
        self.tab_widget = QTabWidget()
        
        # ルート情報タブ
        self.route_info_widget = self.create_route_info_widget()
        self.tab_widget.addTab(self.route_info_widget, "ルート情報")
        
        # 店舗訪問詳細タブ
        self.store_visits_widget = self.create_store_visits_widget()
        self.tab_widget.addTab(self.store_visits_widget, "店舗訪問詳細")
        
        parent_layout.addWidget(self.tab_widget)
    
    def create_route_info_widget(self) -> QWidget:
        """ルート情報入力ウィジェットの作成"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # ルート日付
        self.route_date_edit = QDateTimeEdit()
        self.route_date_edit.setCalendarPopup(True)
        self.route_date_edit.setDateTime(QDateTime.currentDateTime())
        self.route_date_edit.setDisplayFormat("yyyy-MM-dd")
        layout.addRow("ルート日付:", self.route_date_edit)
        
        # ルートコード
        self.route_code_edit = QLineEdit()
        layout.addRow("ルートコード:", self.route_code_edit)
        
        # 出発時間
        self.departure_time_edit = QDateTimeEdit()
        self.departure_time_edit.setCalendarPopup(True)
        self.departure_time_edit.setDateTime(QDateTime.currentDateTime())
        self.departure_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addRow("出発時間:", self.departure_time_edit)
        
        # 帰宅時間
        self.return_time_edit = QDateTimeEdit()
        self.return_time_edit.setCalendarPopup(True)
        self.return_time_edit.setDateTime(QDateTime.currentDateTime())
        self.return_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addRow("帰宅時間:", self.return_time_edit)
        
        # 経費
        cost_layout = QHBoxLayout()
        self.toll_fee_outbound_spin = QDoubleSpinBox()
        self.toll_fee_outbound_spin.setMaximum(999999)
        self.toll_fee_outbound_spin.setSuffix(" 円")
        cost_layout.addWidget(QLabel("往路高速代:"))
        cost_layout.addWidget(self.toll_fee_outbound_spin)
        
        self.toll_fee_return_spin = QDoubleSpinBox()
        self.toll_fee_return_spin.setMaximum(999999)
        self.toll_fee_return_spin.setSuffix(" 円")
        cost_layout.addWidget(QLabel("復路高速代:"))
        cost_layout.addWidget(self.toll_fee_return_spin)
        
        self.parking_fee_spin = QDoubleSpinBox()
        self.parking_fee_spin.setMaximum(999999)
        self.parking_fee_spin.setSuffix(" 円")
        cost_layout.addWidget(QLabel("駐車場代:"))
        cost_layout.addWidget(self.parking_fee_spin)
        layout.addRow("経費:", cost_layout)
        
        expense_layout = QHBoxLayout()
        self.meal_cost_spin = QDoubleSpinBox()
        self.meal_cost_spin.setMaximum(999999)
        self.meal_cost_spin.setSuffix(" 円")
        expense_layout.addWidget(QLabel("食費:"))
        expense_layout.addWidget(self.meal_cost_spin)
        
        self.other_expenses_spin = QDoubleSpinBox()
        self.other_expenses_spin.setMaximum(999999)
        self.other_expenses_spin.setSuffix(" 円")
        expense_layout.addWidget(QLabel("その他:"))
        expense_layout.addWidget(self.other_expenses_spin)
        layout.addRow("", expense_layout)
        
        # 備考
        self.remarks_edit = QTextEdit()
        self.remarks_edit.setMaximumHeight(100)
        layout.addRow("備考（天候等）:", self.remarks_edit)
        
        return widget
    
    def create_store_visits_widget(self) -> QWidget:
        """店舗訪問詳細テーブルウィジェットの作成"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # テーブル
        self.store_visits_table = QTableWidget()
        self.store_visits_table.setAlternatingRowColors(True)
        self.store_visits_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.store_visits_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        
        headers = [
            "訪問順序", "店舗コード", "店舗IN時間", "店舗OUT時間",
            "移動時間（分）", "距離（km）", "想定粗利", "仕入れ点数",
            "仕入れ成功", "空振り理由", "店舗評価", "店舗メモ"
        ]
        self.store_visits_table.setColumnCount(len(headers))
        self.store_visits_table.setHorizontalHeaderLabels(headers)
        
        header = self.store_visits_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        layout.addWidget(self.store_visits_table)
        
        # 行追加・削除ボタン
        button_layout = QHBoxLayout()
        add_row_btn = QPushButton("行追加")
        add_row_btn.clicked.connect(self.add_store_visit_row)
        button_layout.addWidget(add_row_btn)
        
        delete_row_btn = QPushButton("行削除")
        delete_row_btn.clicked.connect(self.delete_store_visit_row)
        button_layout.addWidget(delete_row_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        return widget
    
    def setup_calculation_results(self, parent_layout):
        """計算結果表示の設定"""
        result_group = QGroupBox("計算結果")
        result_layout = QVBoxLayout(result_group)
        
        self.calculation_label = QLabel("計算結果: データ未入力")
        result_layout.addWidget(self.calculation_label)
        
        parent_layout.addWidget(result_group)
    
    def generate_template(self):
        """テンプレート生成"""
        try:
            route_code = self.route_code_edit.text().strip()
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "テンプレートファイルを保存",
                f"route_template_{datetime.now().strftime('%Y%m%d')}.xlsx",
                "Excelファイル (*.xlsx);;CSVファイル (*.csv)"
            )
            
            if not file_path:
                return
            
            # 店舗コード一覧を取得（ルートコードから）
            store_codes = []
            if route_code:
                stores = self.store_db.list_stores()
                store_codes = [
                    store.get('supplier_code')
                    for store in stores
                    if store.get('route_code') == route_code and store.get('supplier_code')
                ]
            
            if not TemplateGenerator:
                QMessageBox.warning(self, "エラー", "テンプレート生成機能が利用できません")
                return
            
            if file_path.endswith('.xlsx'):
                success = TemplateGenerator.generate_excel_template(file_path, route_code, store_codes)
            else:
                success = TemplateGenerator.generate_csv_template(file_path, route_code, store_codes)
            
            if success:
                QMessageBox.information(self, "成功", f"テンプレートを生成しました:\n{file_path}")
            else:
                QMessageBox.warning(self, "エラー", "テンプレートの生成に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"テンプレート生成中にエラーが発生しました:\n{str(e)}")
    
    def load_template(self):
        """テンプレート読み込み"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "テンプレートファイルを選択",
                "",
                "Excelファイル (*.xlsx *.xlsm);;CSVファイル (*.csv);;すべてのファイル (*)"
            )
            
            if not file_path:
                return
            
            # Excel読み込み
            if file_path.endswith(('.xlsx', '.xlsm')):
                df_route = pd.read_excel(file_path, sheet_name='ルート情報')
                try:
                    df_visits = pd.read_excel(file_path, sheet_name='店舗訪問詳細')
                except Exception as e:
                    QMessageBox.warning(self, "エラー", f"Excelファイルの読み込みに失敗しました:\n{str(e)}")
                    return
            else:
                # CSV読み込み（簡易実装）
                QMessageBox.warning(self, "注意", "CSV形式の読み込みは開発中です")
                return
            
            # ルート情報を読み込み
            route_values = {}
            if '値' in df_route.columns and '項目' in df_route.columns:
                for _, row in df_route.iterrows():
                    item = row.get('項目', '')
                    value = row.get('値', '')
                    if item == 'ルート日付':
                        try:
                            dt = pd.to_datetime(value)
                            self.route_date_edit.setDateTime(QDateTime.fromString(dt.strftime('%Y-%m-%d'), 'yyyy-MM-dd'))
                        except:
                            pass
                    elif item == 'ルートコード':
                        self.route_code_edit.setText(str(value))
                    elif item == '出発時間':
                        try:
                            dt = pd.to_datetime(value)
                            self.departure_time_edit.setDateTime(QDateTime.fromString(dt.strftime('%Y-%m-%d %H:%M'), 'yyyy-MM-dd HH:mm'))
                        except:
                            pass
                    elif item == '帰宅時間':
                        try:
                            dt = pd.to_datetime(value)
                            self.return_time_edit.setDateTime(QDateTime.fromString(dt.strftime('%Y-%m-%d %H:%M'), 'yyyy-MM-dd HH:mm'))
                        except:
                            pass
                    elif item == '往路高速代':
                        self.toll_fee_outbound_spin.setValue(float(value) if value else 0)
                    elif item == '復路高速代':
                        self.toll_fee_return_spin.setValue(float(value) if value else 0)
                    elif item == '駐車場代':
                        self.parking_fee_spin.setValue(float(value) if value else 0)
                    elif item == '食費':
                        self.meal_cost_spin.setValue(float(value) if value else 0)
                    elif item == 'その他経費':
                        self.other_expenses_spin.setValue(float(value) if value else 0)
                    elif item == '備考（天候等）':
                        self.remarks_edit.setPlainText(str(value) if value else '')
            
            # 店舗訪問詳細を読み込み
            self.store_visits_table.setRowCount(len(df_visits))
            for i, row in df_visits.iterrows():
                for j, header in enumerate([
                    "訪問順序", "店舗コード", "店舗IN時間", "店舗OUT時間",
                    "前店舗からの移動時間（分）", "前店舗からの距離（km）",
                    "店舗毎想定粗利", "店舗毎仕入れ点数", "仕入れ成功",
                    "空振り理由", "店舗評価（1-5）", "店舗メモ"
                ]):
                    value = row.get(header, '')
                    item = QTableWidgetItem(str(value) if pd.notna(value) else '')
                    self.store_visits_table.setItem(i, j, item)
            
            QMessageBox.information(self, "完了", "テンプレートを読み込みました")
            self.update_calculation_results()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"テンプレート読み込み中にエラーが発生しました:\n{str(e)}")
    
    def run_matching(self):
        """照合処理実行"""
        QMessageBox.information(self, "照合処理", "照合処理機能は仕入リストと連携する必要があります")
    
    def add_store_visit_row(self):
        """店舗訪問行を追加"""
        row = self.store_visits_table.rowCount()
        self.store_visits_table.insertRow(row)
        
        # 訪問順序を自動設定
        order_item = QTableWidgetItem(str(row + 1))
        order_item.setFlags(order_item.flags() & ~Qt.ItemIsEditable)
        self.store_visits_table.setItem(row, 0, order_item)
    
    def delete_store_visit_row(self):
        """選択された店舗訪問行を削除"""
        selected_rows = self.store_visits_table.selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除する行を選択してください")
            return
        
        for row in sorted(selected_rows, reverse=True):
            self.store_visits_table.removeRow(row.row())
        
        # 訪問順序を再設定
        for i in range(self.store_visits_table.rowCount()):
            order_item = self.store_visits_table.item(i, 0)
            if order_item:
                order_item.setText(str(i + 1))
        
        self.update_calculation_results()
    
    def get_route_data(self) -> Dict[str, Any]:
        """入力データを取得"""
        route_date = self.route_date_edit.dateTime().toString('yyyy-MM-dd')
        departure_time = self.departure_time_edit.dateTime().toString('yyyy-MM-dd HH:mm:ss')
        return_time = self.return_time_edit.dateTime().toString('yyyy-MM-dd HH:mm:ss')
        
        return {
            'route_date': route_date,
            'route_code': self.route_code_edit.text().strip(),
            'departure_time': departure_time,
            'return_time': return_time,
            'toll_fee_outbound': self.toll_fee_outbound_spin.value(),
            'toll_fee_return': self.toll_fee_return_spin.value(),
            'parking_fee': self.parking_fee_spin.value(),
            'meal_cost': self.meal_cost_spin.value(),
            'other_expenses': self.other_expenses_spin.value(),
            'remarks': self.remarks_edit.toPlainText()
        }
    
    def get_store_visits_data(self) -> List[Dict[str, Any]]:
        """店舗訪問詳細データを取得"""
        visits = []
        
        for i in range(self.store_visits_table.rowCount()):
            visit = {
                'visit_order': i + 1,
                'store_code': self._get_table_item(i, 1),
                'store_in_time': self._get_table_item(i, 2),
                'store_out_time': self._get_table_item(i, 3),
                'travel_time_from_prev': self._safe_float(self._get_table_item(i, 4)),
                'distance_from_prev': self._safe_float(self._get_table_item(i, 5)),
                'store_gross_profit': self._safe_float(self._get_table_item(i, 6)),
                'store_item_count': self._safe_int(self._get_table_item(i, 7)),
                'purchase_success': self._get_table_item(i, 8) == 'YES',
                'no_purchase_reason': self._get_table_item(i, 9),
                'store_rating': self._safe_int(self._get_table_item(i, 10)),
                'store_notes': self._get_table_item(i, 11)
            }
            visits.append(visit)
        
        return visits
    
    def _get_table_item(self, row: int, col: int) -> str:
        """テーブルのアイテムを取得"""
        item = self.store_visits_table.item(row, col)
        return item.text() if item else ''
    
    def _safe_float(self, value: str) -> Optional[float]:
        """安全にfloatに変換"""
        try:
            return float(value) if value else None
        except (ValueError, TypeError):
            return None
    
    def _safe_int(self, value: str) -> Optional[int]:
        """安全にintに変換"""
        try:
            return int(float(value)) if value else None
        except (ValueError, TypeError):
            return None
    
    def update_calculation_results(self):
        """計算結果を更新"""
        try:
            route_data = self.get_route_data()
            store_visits = self.get_store_visits_data()
            
            # 計算実行
            stats = self.calc_service.calculate_route_statistics(route_data, store_visits)
            
            # 結果表示
            result_text = f"""
計算結果:
- 実働時間: {stats.get('total_working_hours', 0):.2f} 時間
- 総粗利: {stats.get('total_gross_profit', 0):,.0f} 円
- 総仕入れ点数: {stats.get('total_item_count', 0)} 点
- 想定時給: {stats.get('estimated_hourly_rate', 0):,.0f} 円/時間
- 仕入れ成功率: {stats.get('purchase_success_rate', 0) * 100:.1f}%
- 平均仕入れ単価: {stats.get('avg_purchase_price', 0):,.0f} 円/点
            """.strip()
            
            self.calculation_label.setText(result_text)
            
        except Exception as e:
            self.calculation_label.setText(f"計算エラー: {str(e)}")
    
    def save_data(self):
        """データを保存"""
        try:
            route_data = self.get_route_data()
            store_visits = self.get_store_visits_data()
            
            # バリデーション
            if not route_data.get('route_code'):
                QMessageBox.warning(self, "警告", "ルートコードを入力してください")
                return
            
            # 計算実行
            if not self.calc_service:
                QMessageBox.warning(self, "エラー", "計算サービスが利用できません")
                return
            
            stats = self.calc_service.calculate_route_statistics(route_data, store_visits)
            
            # 計算結果をroute_dataに追加
            route_data.update(stats)
            
            # データベースに保存
            if self.current_route_id:
                # 更新
                self.route_db.update_route_summary(self.current_route_id, route_data)
                # 既存の店舗訪問詳細を削除
                existing_visits = self.route_db.get_store_visits_by_route(self.current_route_id)
                for visit in existing_visits:
                    self.route_db.delete_store_visit(visit['id'])
            else:
                # 新規作成
                self.current_route_id = self.route_db.add_route_summary(route_data)
            
            # 店舗訪問詳細を保存
            for visit in store_visits:
                visit['route_summary_id'] = self.current_route_id
                self.route_db.add_store_visit(visit)
            
            QMessageBox.information(self, "完了", "データを保存しました")
            self.data_saved.emit(self.current_route_id)
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"データ保存中にエラーが発生しました:\n{str(e)}")
    
    def new_route(self):
        """新規ルート作成"""
        self.current_route_id = None
        self.route_code_edit.clear()
        self.route_date_edit.setDateTime(QDateTime.currentDateTime())
        self.departure_time_edit.setDateTime(QDateTime.currentDateTime())
        self.return_time_edit.setDateTime(QDateTime.currentDateTime())
        self.toll_fee_outbound_spin.setValue(0)
        self.toll_fee_return_spin.setValue(0)
        self.parking_fee_spin.setValue(0)
        self.meal_cost_spin.setValue(0)
        self.other_expenses_spin.setValue(0)
        self.remarks_edit.clear()
        self.store_visits_table.setRowCount(0)
        self.calculation_label.setText("計算結果: データ未入力")

