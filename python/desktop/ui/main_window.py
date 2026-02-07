#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HIRIO メインウィンドウ

メニューバー + タブナビゲーション構成
- 価格改定タブ
- 仕入管理タブ  
- 古物台帳タブ
- 設定タブ
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTabWidget, QMenuBar, QMenu, QStatusBar, QLabel,
    QMessageBox, QSplitter, QPushButton
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSettings
from PySide6.QtGui import QAction, QKeySequence
import subprocess
import threading
import time

# プロジェクト内のモジュール
from ui.repricer_widget import RepricerWidget
from ui.repricer_settings_widget import RepricerSettingsWidget
from ui.inventory_widget import InventoryWidget
from ui.antique_widget import AntiqueWidget
from ui.settings_widget import SettingsWidget
from ui.workflow_panel import WorkflowPanel
from ui.store_master_widget import StoreMasterWidget
from ui.route_summary_widget import RouteSummaryWidget
from ui.route_list_widget import RouteListWidget
from ui.route_visit_widget import RouteVisitLogWidget
from ui.analysis_widget import AnalysisWidget
from ui.product_widget import ProductWidget
from ui.condition_template_widget import ConditionTemplateWidget
from ui.barcode_checker_widget import BarcodeCheckerWidget
from ui.image_manager_widget import ImageManagerWidget
from ui.evidence_manager_widget import EvidenceManagerWidget
from ui.purchase_ledger_widget import PurchaseLedgerWidget
from ui.expense_ledger_widget import ExpenseLedgerWidget
from ui.keepa_test_widget import KeepaTestWidget
from ui.image_test_widget import ImageTestWidget
from ui.store_code_batch_widget import StoreCodeBatchWidget


class APIServerThread(QThread):
    """FastAPIサーバー起動スレッド"""
    server_started = Signal()
    server_error = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.process = None
        
    def run(self):
        """FastAPIサーバーの起動"""
        try:
            # FastAPIサーバーを起動
            # pythonディレクトリに移動してから起動
            import os
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            python_dir = os.path.join(project_root, "python")
            
            self.process = subprocess.Popen([
                "python", "-m", "uvicorn", 
                "app:app", 
                "--host", "localhost", 
                "--port", "8000",
                "--reload"
            ], cwd=python_dir)  # pythonディレクトリに移動
            
            # サーバー起動待機
            time.sleep(3)
            self.server_started.emit()
            
        except Exception as e:
            self.server_error.emit(str(e))
    
    def stop_server(self):
        """サーバーの停止"""
        if self.process:
            self.process.terminate()
            self.process = None


class MainWindow(QMainWindow):
    """HIRIOメインウィンドウ"""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.api_server_thread = None
        self.server_running = False
        
        # 設定管理
        self.settings = QSettings("HIRIO", "SedoriDesktopApp")
        
        # UIの初期化
        self.setup_ui()
        self.setup_menu()
        self.setup_status_bar()
        
        # ウィンドウ設定
        self.setWindowTitle("HIRIO - せどり業務統合システム")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # 中央配置
        self.center_window()
        
        # タブの順序を復元
        self.restore_tab_order()
        
    def closeEvent(self, event):
        """ウィンドウが閉じるときのイベント"""
        # タブの順序を保存
        self.save_tab_order()
        
        # 各ウィジェットの設定を保存
        if hasattr(self, 'repricer_widget') and hasattr(self.repricer_widget, 'save_settings'):
            self.repricer_widget.save_settings()
        if hasattr(self, 'inventory_widget') and hasattr(self.inventory_widget, 'save_settings'):
            self.inventory_widget.save_settings()
        if hasattr(self, 'antique_widget') and hasattr(self.antique_widget, 'save_settings'):
            self.antique_widget.save_settings()
        if hasattr(self, 'route_summary_widget') and hasattr(self.route_summary_widget, 'save_settings'):
            self.route_summary_widget.save_settings()
        if hasattr(self, 'product_widget') and hasattr(self.product_widget, 'save_settings'):
            self.product_widget.save_settings()
        if hasattr(self, 'store_master_widget') and hasattr(self.store_master_widget, 'save_settings'):
            self.store_master_widget.save_settings()
        if hasattr(self, 'evidence_widget') and hasattr(self.evidence_widget, 'save_settings'):
            self.evidence_widget.save_settings()
        if hasattr(self, 'purchase_ledger_widget') and hasattr(self.purchase_ledger_widget, 'save_settings'):
            self.purchase_ledger_widget.save_settings()
        if hasattr(self, 'expense_ledger_widget') and hasattr(self.expense_ledger_widget, 'save_settings'):
            self.expense_ledger_widget.save_settings()
        if hasattr(self, 'image_manager_widget') and hasattr(self.image_manager_widget, 'save_settings'):
            self.image_manager_widget.save_settings()
        
        # FastAPIサーバーを停止
        self.stop_fastapi_server()
        super().closeEvent(event)
        
    def setup_ui(self):
        """UIの基本設定"""
        # 中央ウィジェット
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # メインレイアウト
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # タブウィジェットの作成
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        # タブのドラッグ&ドロップによる順序変更を有効化
        self.tab_widget.setMovable(True)
        # タブが移動されたときに順序を保存
        self.tab_widget.tabBar().tabMoved.connect(self.save_tab_order)
        
        # 各タブの追加
        self.setup_tabs()
        
        # レイアウトに追加
        main_layout.addWidget(self.tab_widget)
        
    def setup_tabs(self):
        """タブの設定"""
        # 価格改定タブ（サブタブを持つ）
        # 各価格改定ウィジェットの作成
        self.repricer_widget = RepricerWidget(self.api_client)
        self.repricer_settings_widget = RepricerSettingsWidget(self.api_client)
        
        # 価格改定用のサブタブウィジェットを作成
        repricer_tabs = QTabWidget()
        repricer_tabs.addTab(self.repricer_widget, "改定実行")
        repricer_tabs.addTab(self.repricer_settings_widget, "改定ルール")
        
        # メインタブに追加
        self.tab_widget.addTab(repricer_tabs, "価格改定")
        
        # 仕入管理タブ（仮に作成）
        self.inventory_widget = InventoryWidget(self.api_client)
        self.tab_widget.addTab(self.inventory_widget, "仕入管理")
        
        # 古物台帳タブ（仕入管理ウィジェット参照を渡す）
        self.antique_widget = AntiqueWidget(self.api_client, inventory_widget=self.inventory_widget)
        self.tab_widget.addTab(self.antique_widget, "古物台帳")
        
        # ===== ルートタブ（メインタブ） =====
        # ルート登録とルートサマリーをまとめる
        route_tabs = QTabWidget()
        self.route_summary_widget = RouteSummaryWidget(self.api_client, inventory_widget=self.inventory_widget)
        route_tabs.addTab(self.route_summary_widget, "ルート登録")
        self.route_list_widget = RouteListWidget()
        route_tabs.addTab(self.route_list_widget, "ルートサマリー")
        
        # 保存完了時にサマリー一覧を更新
        self.route_summary_widget.data_saved.connect(self.route_list_widget.load_routes)
        
        # メインタブに追加
        self.tab_widget.addTab(route_tabs, "ルート")
        
        # 仕入管理ウィジェットから参照できるように設定
        self.inventory_widget.set_route_summary_widget(self.route_summary_widget)
        self.inventory_widget.set_antique_widget(self.antique_widget)
        
        # ===== データベース管理タブ（メインタブ） =====
        # 商品DB、店舗マスタ、ルート訪問DB、コンディション説明をまとめる
        self.store_master_widget = StoreMasterWidget()
        self.product_widget = ProductWidget(inventory_widget=self.inventory_widget)
        # InventoryWidgetにProductWidgetへの参照を設定
        self.inventory_widget.set_product_widget(self.product_widget)
        self.route_visit_widget = RouteVisitLogWidget()
        self.condition_template_widget = ConditionTemplateWidget()
        
        db_management_tabs = QTabWidget()
        db_management_tabs.addTab(self.product_widget, "商品DB")
        db_management_tabs.addTab(self.store_master_widget, "店舗マスタ")
        db_management_tabs.addTab(self.route_visit_widget, "ルート訪問DB")
        db_management_tabs.addTab(self.condition_template_widget, "コンディション説明")
        
        # メインタブに追加
        self.tab_widget.addTab(db_management_tabs, "データベース管理")
        
        # 店舗コード移行用バッチタブ
        self.store_code_batch_widget = StoreCodeBatchWidget()
        self.tab_widget.addTab(self.store_code_batch_widget, "バッチ処理")
        
        # 分析タブ
        self.analysis_widget = AnalysisWidget()
        self.tab_widget.addTab(self.analysis_widget, "分析")
        
        # 証憑管理タブ（レシート + 保証書統合）
        self.evidence_widget = EvidenceManagerWidget(
            self.api_client,
            inventory_widget=self.inventory_widget,
            product_widget=self.product_widget
        )
        # ReceiptWidgetにEvidenceManagerWidgetへの参照を設定
        if hasattr(self.evidence_widget, 'receipt_widget'):
            self.evidence_widget.receipt_widget.set_evidence_widget(self.evidence_widget)
        self.tab_widget.addTab(self.evidence_widget, "証憑管理")
        
        # 台帳タブ（確定申告用）
        ledger_tabs = QTabWidget()
        self.purchase_ledger_widget = PurchaseLedgerWidget(self.api_client)
        ledger_tabs.addTab(self.purchase_ledger_widget, "仕入台帳")
        self.expense_ledger_widget = ExpenseLedgerWidget(self.api_client)
        ledger_tabs.addTab(self.expense_ledger_widget, "経費台帳")
        self.tab_widget.addTab(ledger_tabs, "台帳")
        
        # バーコードチェッカータブ
        self.barcode_checker_widget = BarcodeCheckerWidget()
        self.tab_widget.addTab(self.barcode_checker_widget, "バーコードチェッカー")
        
        # 画像管理タブ
        self.image_manager_widget = ImageManagerWidget(self.api_client)
        # ImageManagerWidgetにProductWidgetへの参照を設定
        self.image_manager_widget.set_product_widget(self.product_widget)
        self.tab_widget.addTab(self.image_manager_widget, "画像管理")

        # Keepaテストタブ
        self.keepa_test_widget = KeepaTestWidget()
        self.tab_widget.addTab(self.keepa_test_widget, "Keepaテスト")
        
        # 画像テストタブ
        self.image_test_widget = ImageTestWidget()
        self.tab_widget.addTab(self.image_test_widget, "画像テスト")
        
        # 設定タブ
        self.settings_widget = SettingsWidget(self.api_client)
        self.settings_widget.settings_changed.connect(self.on_settings_changed)
        self.tab_widget.addTab(self.settings_widget, "設定")
        
    def setup_menu(self):
        """メニューバーの設定"""
        menubar = self.menuBar()
        
        # ファイルメニュー
        file_menu = menubar.addMenu("ファイル(&F)")
        
        # 新規プロジェクト
        new_action = QAction("新規プロジェクト(&N)", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.new_project)
        file_menu.addAction(new_action)
        
        # プロジェクトを開く
        open_action = QAction("プロジェクトを開く(&O)", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_project)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        # 終了
        exit_action = QAction("終了(&X)", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 編集メニュー
        edit_menu = menubar.addMenu("編集(&E)")
        
        # 設定
        settings_action = QAction("設定(&S)", self)
        settings_action.triggered.connect(self.show_settings)
        edit_menu.addAction(settings_action)
        
        # 表示メニュー
        view_menu = menubar.addMenu("表示(&V)")
        
        
        # ツールメニュー
        tools_menu = menubar.addMenu("ツール(&T)")
        
        # FastAPIサーバー起動
        self.start_server_action = QAction("FastAPIサーバー起動(&S)", self)
        self.start_server_action.triggered.connect(self.start_fastapi_server)
        tools_menu.addAction(self.start_server_action)
        
        # FastAPIサーバー停止
        self.stop_server_action = QAction("FastAPIサーバー停止(&T)", self)
        self.stop_server_action.triggered.connect(self.stop_fastapi_server)
        self.stop_server_action.setEnabled(False)
        tools_menu.addAction(self.stop_server_action)
        
        tools_menu.addSeparator()
        
        # API接続テスト
        api_test_action = QAction("API接続テスト(&A)", self)
        api_test_action.triggered.connect(self.test_api_connection)
        tools_menu.addAction(api_test_action)
        
        # ヘルプメニュー
        help_menu = menubar.addMenu("ヘルプ(&H)")
        
        # バージョン情報
        about_action = QAction("バージョン情報(&A)", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
    def setup_status_bar(self):
        """ステータスバーの設定"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # ステータスラベル
        self.status_label = QLabel("準備完了")
        self.status_bar.addWidget(self.status_label)
        
        # API接続ステータス
        self.api_status_label = QLabel("API: 未接続")
        self.status_bar.addPermanentWidget(self.api_status_label)
        
        # API接続チェック
        self.check_api_connection()
        
        
    def center_window(self):
        """ウィンドウを中央に配置"""
        screen = self.screen().availableGeometry()
        size = self.size()
        x = (screen.width() - size.width()) // 2
        y = (screen.height() - size.height()) // 2
        self.move(x, y)
        
    def check_api_connection(self):
        """API接続状況のチェック"""
        try:
            # API接続テスト（ダミー実装）
            if self.api_client:
                self.api_status_label.setText("API: 接続済み")
                self.api_status_label.setStyleSheet("color: green;")
            else:
                self.api_status_label.setText("API: 未接続")
                self.api_status_label.setStyleSheet("color: red;")
        except Exception as e:
            self.api_status_label.setText(f"API: エラー ({str(e)})")
            self.api_status_label.setStyleSheet("color: red;")
    
    # メニューアクションの実装
    def new_project(self):
        """新規プロジェクト"""
        QMessageBox.information(self, "新規プロジェクト", "新規プロジェクト機能（開発予定）")
        
    def open_project(self):
        """プロジェクトを開く"""
        QMessageBox.information(self, "プロジェクトを開く", "プロジェクトを開く機能（開発予定）")
        
    def show_settings(self):
        """設定画面を表示"""
        QMessageBox.information(self, "設定", "設定画面（開発予定）")
        
            
    def start_fastapi_server(self):
        """FastAPIサーバーの起動"""
        if self.server_running:
            QMessageBox.information(self, "サーバー起動", "FastAPIサーバーは既に起動しています")
            return
            
        try:
            self.status_label.setText("FastAPIサーバー起動中...")
            
            # サーバースレッドの作成と起動
            self.api_server_thread = APIServerThread()
            self.api_server_thread.server_started.connect(self.on_server_started)
            self.api_server_thread.server_error.connect(self.on_server_error)
            self.api_server_thread.start()
            
        except Exception as e:
            QMessageBox.critical(self, "サーバー起動エラー", f"FastAPIサーバーの起動に失敗しました:\n{str(e)}")
    
    def stop_fastapi_server(self):
        """FastAPIサーバーの停止"""
        if not self.server_running:
            # サーバーが起動していない場合は何もしない（メッセージも表示しない）
            return
            
        try:
            if self.api_server_thread:
                self.api_server_thread.stop_server()
                self.api_server_thread.quit()
                self.api_server_thread.wait()
                self.api_server_thread = None
            
            self.server_running = False
            self.start_server_action.setEnabled(True)
            self.stop_server_action.setEnabled(False)
            self.status_label.setText("FastAPIサーバー停止")
            self.api_status_label.setText("API: 停止")
            self.api_status_label.setStyleSheet("color: red;")
            
            QMessageBox.information(self, "サーバー停止", "FastAPIサーバーを停止しました")
            
        except Exception as e:
            QMessageBox.critical(self, "サーバー停止エラー", f"FastAPIサーバーの停止に失敗しました:\n{str(e)}")
    
    def on_server_started(self):
        """サーバー起動完了"""
        self.server_running = True
        self.start_server_action.setEnabled(False)
        self.stop_server_action.setEnabled(True)
        self.status_label.setText("FastAPIサーバー起動完了")
        self.api_status_label.setText("API: 起動中")
        self.api_status_label.setStyleSheet("color: orange;")
        
        # 接続テストを実行
        QTimer.singleShot(2000, self.test_api_connection)
    
    def on_server_error(self, error_message):
        """サーバー起動エラー"""
        self.server_running = False
        self.start_server_action.setEnabled(True)
        self.stop_server_action.setEnabled(False)
        self.status_label.setText("FastAPIサーバー起動失敗")
        self.api_status_label.setText("API: エラー")
        self.api_status_label.setStyleSheet("color: red;")
        
        QMessageBox.critical(self, "サーバー起動エラー", f"FastAPIサーバーの起動に失敗しました:\n{error_message}")
    
    def test_api_connection(self):
        """API接続テスト"""
        try:
            if self.api_client.test_connection():
                self.status_label.setText("API接続テスト完了")
                self.api_status_label.setText("API: 接続済み")
                self.api_status_label.setStyleSheet("color: green;")
                QMessageBox.information(self, "API接続テスト", "FastAPIサーバーに正常に接続できました")
            else:
                self.status_label.setText("API接続テスト失敗")
                self.api_status_label.setText("API: 接続失敗")
                self.api_status_label.setStyleSheet("color: red;")
                QMessageBox.warning(self, "API接続テスト", "FastAPIサーバーに接続できませんでした")
        except Exception as e:
            QMessageBox.warning(self, "API接続エラー", f"API接続に失敗しました:\n{str(e)}")
            
    def api_test_completed(self):
        """API接続テスト完了"""
        self.status_label.setText("API接続テスト完了")
        self.check_api_connection()
        
    def on_settings_changed(self, settings_dict):
        """設定変更時の処理"""
        try:
            # API設定の更新
            if 'api' in settings_dict:
                api_settings = settings_dict['api']
                if 'url' in api_settings:
                    self.api_client.base_url = api_settings['url']
                if 'timeout' in api_settings:
                    # タイムアウト設定の適用（必要に応じて実装）
                    pass
            
            # その他の設定変更処理
            self.status_label.setText("設定が更新されました")
            
        except Exception as e:
            QMessageBox.warning(self, "設定更新エラー", f"設定の適用中にエラーが発生しました:\n{str(e)}")
    
    def show_about(self):
        """バージョン情報を表示"""
        QMessageBox.about(
            self,
            "HIRIO について",
            """
            <h3>HIRIO - せどり業務統合システム</h3>
            <p>バージョン: 1.0.0</p>
            <p>技術スタック: PySide6 + FastAPI + SQLite</p>
            <p>開発目標: 年内MVP（仕入管理システム完成）</p>
            <p>© 2025 HIRIO Project</p>
            """
        )
    
    def save_tab_order(self):
        """タブの順序を保存"""
        tab_count = self.tab_widget.count()
        tab_order = []
        for i in range(tab_count):
            tab_text = self.tab_widget.tabText(i)
            tab_order.append(tab_text)
        self.settings.setValue("main_tab_order", tab_order)
    
    def restore_tab_order(self):
        """タブの順序を復元"""
        tab_order = self.settings.value("main_tab_order", [])
        if not tab_order or len(tab_order) == 0:
            return
        
        # 一時的にタブの移動を無効化
        self.tab_widget.setMovable(False)
        
        # 現在のタブの位置を取得（テキスト→インデックス）
        tab_text_to_index = {}
        tab_count = self.tab_widget.count()
        for i in range(tab_count):
            tab_text = self.tab_widget.tabText(i)
            tab_text_to_index[tab_text] = i
        
        # 保存された順序に従ってタブを移動
        # 後ろから前に移動することで、インデックスのずれを防ぐ
        moved_tabs = set()
        for target_index, tab_text in enumerate(tab_order):
            if tab_text in tab_text_to_index:
                # 現在の位置を再取得（移動により変更されている可能性がある）
                current_index = None
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.tabText(i) == tab_text:
                        current_index = i
                        break
                
                if current_index is not None and current_index != target_index:
                    self.tab_widget.tabBar().moveTab(current_index, target_index)
                moved_tabs.add(tab_text)
        
        # 保存された順序に存在しないタブを最後に配置
        remaining_tabs = []
        for i in range(self.tab_widget.count()):
            tab_text = self.tab_widget.tabText(i)
            if tab_text not in moved_tabs:
                remaining_tabs.append((i, tab_text))
        
        # 残りのタブを順番に最後に移動
        target_index = len(tab_order)
        for original_index, tab_text in remaining_tabs:
            # 現在の位置を再取得
            current_index = None
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == tab_text:
                    current_index = i
                    break
            
            if current_index is not None and current_index != target_index:
                self.tab_widget.tabBar().moveTab(current_index, target_index)
            target_index += 1
        
        # タブの移動を再有効化
        self.tab_widget.setMovable(True)
