#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析ウィジェット

基本分析機能の表示
- 店舗別粗利ランキング（棒グラフ）
- ルート別時給比較（折れ線グラフ）
- 月別仕入れ数推移（折れ線グラフ）
- 店舗評価の平均値・推移
- 基本統計情報
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QComboBox, QDateEdit, QTabWidget, QFileDialog,
    QMessageBox
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.route_db import RouteDatabase
from utils.data_exporter import DataExporter

# matplotlibのインポート（グラフ表示用）
try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import matplotlib.dates as mdates
    import matplotlib
    # 日本語フォント設定
    try:
        matplotlib.rcParams['font.family'] = 'MS Gothic'  # Windows環境
    except:
        try:
            matplotlib.rcParams['font.family'] = 'Yu Gothic'  # Windows環境（代替）
        except:
            pass
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("警告: matplotlibがインストールされていません。グラフ機能は使用できません。")


class AnalysisWidget(QWidget):
    """分析ウィジェット"""
    
    def __init__(self):
        super().__init__()
        self.route_db = RouteDatabase()
        
        self.setup_ui()
        self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # フィルタエリア
        self.setup_filters(layout)
        
        # タブ（統計・グラフ）
        self.setup_tabs(layout)
    
    def setup_filters(self, parent_layout):
        """フィルタエリアの設定"""
        filter_group = QGroupBox("期間指定")
        filter_layout = QHBoxLayout(filter_group)
        
        filter_layout.addWidget(QLabel("開始日:"))
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-3))
        filter_layout.addWidget(self.start_date_edit)
        
        filter_layout.addWidget(QLabel("終了日:"))
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate.currentDate())
        filter_layout.addWidget(self.end_date_edit)
        
        update_btn = QPushButton("更新")
        update_btn.clicked.connect(self.load_data)
        filter_layout.addWidget(update_btn)
        
        export_btn = QPushButton("エクスポート")
        export_btn.clicked.connect(self.export_data)
        export_btn.setStyleSheet("background-color: #28a745; color: white;")
        filter_layout.addWidget(export_btn)
        
        filter_layout.addStretch()
        
        parent_layout.addWidget(filter_group)
    
    def setup_tabs(self, parent_layout):
        """タブの設定"""
        self.tab_widget = QTabWidget()
        
        # 基本統計タブ
        self.stats_widget = self.create_stats_widget()
        self.tab_widget.addTab(self.stats_widget, "基本統計")
        
        if MATPLOTLIB_AVAILABLE:
            # グラフタブ
            self.graphs_widget = self.create_graphs_widget()
            self.tab_widget.addTab(self.graphs_widget, "グラフ分析")
        else:
            no_graph_label = QLabel("matplotlibがインストールされていません。\nグラフ機能を使用するには、以下のコマンドでインストールしてください:\npip install matplotlib")
            no_graph_label.setAlignment(Qt.AlignCenter)
            self.tab_widget.addTab(no_graph_label, "グラフ分析")
        
        parent_layout.addWidget(self.tab_widget)
    
    def create_stats_widget(self) -> QWidget:
        """基本統計ウィジェットの作成"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.stats_label = QLabel("統計情報を読み込み中...")
        self.stats_label.setAlignment(Qt.AlignTop)
        self.stats_label.setFont(QFont("Courier", 10))
        layout.addWidget(self.stats_label)
        
        return widget
    
    def create_graphs_widget(self) -> QWidget:
        """グラフウィジェットの作成"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # グラフタブ
        graph_tabs = QTabWidget()
        
        # 店舗別粗利ランキング
        store_profit_canvas = self.create_store_profit_chart()
        graph_tabs.addTab(store_profit_canvas, "店舗別粗利ランキング")
        
        # ルート別時給比較
        hourly_rate_canvas = self.create_hourly_rate_chart()
        graph_tabs.addTab(hourly_rate_canvas, "ルート別時給比較")
        
        # 月別仕入れ数推移
        monthly_chart_canvas = self.create_monthly_chart()
        graph_tabs.addTab(monthly_chart_canvas, "月別仕入れ数推移")
        
        # 店舗評価推移
        rating_canvas = self.create_rating_chart()
        graph_tabs.addTab(rating_canvas, "店舗評価推移")
        
        layout.addWidget(graph_tabs)
        
        return widget
    
    def create_store_profit_chart(self):
        """店舗別粗利ランキンググラフ"""
        fig = Figure(figsize=(10, 6))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        
        # データ取得（ダミーデータ）
        ax.text(0.5, 0.5, 'データを読み込んで表示', ha='center', va='center', transform=ax.transAxes)
        ax.set_title('店舗別粗利ランキング（トップ10）')
        
        return canvas
    
    def create_hourly_rate_chart(self):
        """ルート別時給比較グラフ"""
        fig = Figure(figsize=(10, 6))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        
        ax.text(0.5, 0.5, 'データを読み込んで表示', ha='center', va='center', transform=ax.transAxes)
        ax.set_title('ルート別時給比較')
        
        return canvas
    
    def create_monthly_chart(self):
        """月別仕入れ数推移グラフ"""
        fig = Figure(figsize=(10, 6))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        
        ax.text(0.5, 0.5, 'データを読み込んで表示', ha='center', va='center', transform=ax.transAxes)
        ax.set_title('月別仕入れ数推移')
        
        return canvas
    
    def create_rating_chart(self):
        """店舗評価推移グラフ"""
        fig = Figure(figsize=(10, 6))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        
        ax.text(0.5, 0.5, 'データを読み込んで表示', ha='center', va='center', transform=ax.transAxes)
        ax.set_title('店舗評価推移')
        
        return canvas
    
    def load_data(self):
        """データを読み込んで表示を更新"""
        try:
            start_date = self.start_date_edit.date().toString('yyyy-MM-dd')
            end_date = self.end_date_edit.date().toString('yyyy-MM-dd')
            
            # ルートサマリー取得
            routes = self.route_db.list_route_summaries(start_date=start_date, end_date=end_date)
            
            # 統計情報を計算
            stats = self._calculate_statistics(routes)
            
            # 統計情報を表示
            stats_text = f"""
基本統計情報
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
期間: {start_date} 〜 {end_date}

【ルート情報】
- ルート数: {stats['total_routes']} 回
- 平均時給: {stats['avg_hourly_rate']:,.0f} 円/時間
- 総粗利: {stats['total_gross_profit']:,.0f} 円
- 平均実働時間: {stats['avg_working_hours']:.2f} 時間/ルート

【店舗訪問】
- 総訪問数: {stats['total_visits']} 回
- 仕入れ成功数: {stats['successful_purchases']} 回
- 仕入れ成功率: {stats['purchase_success_rate']:.1f}%
- 平均店舗評価: {stats['avg_store_rating']:.2f} / 5.0

【仕入れ】
- 総仕入れ点数: {stats['total_items']} 点
- 平均仕入れ単価: {stats['avg_purchase_price']:,.0f} 円/点
            """.strip()
            
            self.stats_label.setText(stats_text)
            
            # グラフも更新
            if MATPLOTLIB_AVAILABLE:
                self.update_charts(routes)
            
        except Exception as e:
            self.stats_label.setText(f"データ読み込みエラー: {str(e)}")
    
    def _calculate_statistics(self, routes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """統計情報を計算"""
        total_routes = len(routes)
        total_gross_profit = sum(r.get('total_gross_profit', 0) or 0 for r in routes)
        total_working_hours = sum(r.get('total_working_hours', 0) or 0 for r in routes)
        
        avg_hourly_rate = 0
        if total_working_hours > 0:
            total_hourly_value = sum(r.get('estimated_hourly_rate', 0) or 0 for r in routes if r.get('estimated_hourly_rate'))
            if total_hourly_value > 0:
                avg_hourly_rate = total_hourly_value / total_routes if total_routes > 0 else 0
        
        # 店舗訪問詳細を取得
        total_visits = 0
        successful_purchases = 0
        total_items = 0
        total_rating = 0
        rating_count = 0
        
        for route in routes:
            route_id = route.get('id')
            if route_id:
                visits = self.route_db.get_store_visits_by_route(route_id)
                total_visits += len(visits)
                successful_purchases += sum(1 for v in visits if v.get('purchase_success', False))
                total_items += sum(v.get('store_item_count', 0) or 0 for v in visits)
                
                for visit in visits:
                    rating = visit.get('store_rating')
                    if rating:
                        total_rating += rating
                        rating_count += 1
        
        purchase_success_rate = (successful_purchases / total_visits * 100) if total_visits > 0 else 0
        avg_store_rating = (total_rating / rating_count) if rating_count > 0 else 0
        avg_purchase_price = (total_gross_profit / total_items) if total_items > 0 else 0
        avg_working_hours = (total_working_hours / total_routes) if total_routes > 0 else 0
        
        return {
            'total_routes': total_routes,
            'total_visits': total_visits,
            'successful_purchases': successful_purchases,
            'purchase_success_rate': purchase_success_rate,
            'total_gross_profit': total_gross_profit,
            'avg_hourly_rate': avg_hourly_rate,
            'avg_working_hours': avg_working_hours,
            'total_items': total_items,
            'avg_purchase_price': avg_purchase_price,
            'avg_store_rating': avg_store_rating
        }
    
    def update_charts(self, routes: List[Dict[str, Any]]):
        """グラフを更新"""
        if not MATPLOTLIB_AVAILABLE:
            return
        
        # 店舗別粗利ランキング
        self._update_store_profit_chart(routes)
        
        # ルート別時給比較
        self._update_hourly_rate_chart(routes)
        
        # 月別仕入れ数推移
        self._update_monthly_chart(routes)
        
        # 店舗評価推移
        self._update_rating_chart(routes)
    
    def _update_store_profit_chart(self, routes: List[Dict[str, Any]]):
        """店舗別粗利ランキンググラフを更新"""
        # 実装: 店舗コードごとに粗利を集計してランキング表示
        pass
    
    def _update_hourly_rate_chart(self, routes: List[Dict[str, Any]]):
        """ルート別時給比較グラフを更新"""
        # 実装: ルートコードごとに時給を集計して表示
        pass
    
    def _update_monthly_chart(self, routes: List[Dict[str, Any]]):
        """月別仕入れ数推移グラフを更新"""
        # 実装: 月別に仕入れ数を集計して表示
        pass
    
    def _update_rating_chart(self, routes: List[Dict[str, Any]]):
        """店舗評価推移グラフを更新"""
        # 実装: 時系列で店舗評価の推移を表示
        pass
    
    def export_data(self):
        """データをエクスポート"""
        try:
            start_date = self.start_date_edit.date().toString('yyyy-MM-dd')
            end_date = self.end_date_edit.date().toString('yyyy-MM-dd')
            
            # データ取得
            routes = self.route_db.list_route_summaries(start_date=start_date, end_date=end_date)
            
            visits = []
            for route in routes:
                route_id = route.get('id')
                if route_id:
                    route_visits = self.route_db.get_store_visits_by_route(route_id)
                    visits.extend(route_visits)
            
            if not routes:
                QMessageBox.warning(self, "警告", "エクスポートするデータがありません")
                return
            
            # エクスポート形式選択ダイアログ
            format_options = {
                'CSV形式': 'csv',
                'Excel形式': 'excel',
                'Looker Studio用（推奨）': 'looker_studio'
            }
            
            file_path, selected_filter = QFileDialog.getSaveFileName(
                self,
                "データをエクスポート",
                f"hirio_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSVファイル (*.csv);;Excelファイル (*.xlsx);;すべてのファイル (*)"
            )
            
            if not file_path:
                return
            
            # エクスポート実行
            if selected_filter == "Excelファイル (*.xlsx)" or file_path.endswith('.xlsx'):
                # Excel形式
                if DataExporter.export_all_data(routes, visits, str(Path(file_path).parent), 'excel'):
                    QMessageBox.information(self, "完了", "データをエクスポートしました")
                else:
                    QMessageBox.warning(self, "エラー", "エクスポートに失敗しました")
            elif 'looker_studio' in file_path.lower() or 'looker' in file_path.lower():
                # Looker Studio用
                if DataExporter.export_for_looker_studio(routes, visits, file_path):
                    QMessageBox.information(self, "完了", "Looker Studio用データをエクスポートしました")
                else:
                    QMessageBox.warning(self, "エラー", "エクスポートに失敗しました")
            else:
                # CSV形式（ルートサマリーと店舗訪問詳細を別々に）
                base_path = Path(file_path).parent / Path(file_path).stem
                route_file = f"{base_path}_routes.csv"
                visit_file = f"{base_path}_visits.csv"
                looker_file = f"{base_path}_looker_studio.csv"
                
                success = True
                success &= DataExporter.export_route_summaries(routes, route_file, 'csv')
                success &= DataExporter.export_store_visits(visits, visit_file, 'csv')
                success &= DataExporter.export_for_looker_studio(routes, visits, looker_file)
                
                if success:
                    QMessageBox.information(
                        self,
                        "完了",
                        f"データをエクスポートしました:\n- {route_file}\n- {visit_file}\n- {looker_file}"
                    )
                else:
                    QMessageBox.warning(self, "エラー", "エクスポートに失敗しました")
                    
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"エクスポート中にエラーが発生しました:\n{str(e)}")

