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
    QMessageBox, QSplitter, QPushButton, QApplication,
)
from typing import Literal
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSettings
from PySide6.QtGui import QAction, QKeySequence
import subprocess
import sys
import threading
import time

from ui.startup_progress_dialog import StartupProgressDialog

# 重いウィジェットは setup_tabs() 内で遅延インポート（起動時間短縮のため）


class APIServerThread(QThread):
    """FastAPIサーバー起動スレッド"""
    server_started = Signal()
    server_error = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.process = None
        
    def run(self):
        """FastAPIサーバーの起動（python/app.py を正しい cwd で実行）"""
        try:
            import os
            import requests

            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            python_dir = os.path.join(project_root, "python")
            app_py = os.path.join(python_dir, "app.py")
            if not os.path.isfile(app_py):
                self.server_error.emit(f"app.py が見つかりません:\n{app_py}")
                return

            self.process = subprocess.Popen(
                [sys.executable, app_py],
                cwd=python_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            health_url = "http://127.0.0.1:8000/health"
            for _ in range(60):
                if self.process.poll() is not None:
                    tail = ""
                    if self.process.stdout:
                        try:
                            tail = self.process.stdout.read() or ""
                        except Exception:
                            pass
                    tail = tail[-2000:] if tail else "(ログなし)"
                    self.server_error.emit(
                        "FastAPIプロセスがすぐ終了しました。\n"
                        "・別の黒い画面で API を起動していないか確認\n"
                        "・8000番ポートが他アプリで使われていないか確認\n\n"
                        f"ログ末尾:\n{tail}"
                    )
                    return
                try:
                    if requests.get(health_url, timeout=1).status_code == 200:
                        self.server_started.emit()
                        return
                except Exception:
                    pass
                time.sleep(0.5)

            self.server_error.emit(
                "起動後30秒以内に API に接続できませんでした。\n"
                f"確認: ブラウザで {health_url} を開いてください。"
            )
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
        
        # タブの順序は _deferred_setup_tabs 完了後に復元する
        
    def closeEvent(self, event):
        """ウィンドウが閉じるときのイベント"""
        # タブの順序を保存
        self.save_tab_order()
        
        # 各ウィジェットの設定を保存
        if hasattr(self, 'repricer_widget') and hasattr(self.repricer_widget, 'save_settings'):
            self.repricer_widget.save_settings()
        if hasattr(self, 'repricer_widget_369') and hasattr(self.repricer_widget_369, 'save_settings'):
            self.repricer_widget_369.save_settings()
        if hasattr(self, 'inventory_widget') and hasattr(self.inventory_widget, 'save_settings'):
            self.inventory_widget.save_settings()
        if hasattr(self, 'inventory_widget_dev') and hasattr(self.inventory_widget_dev, 'save_settings'):
            self.inventory_widget_dev.save_settings()
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
        if hasattr(self, 'customer_support_widget') and hasattr(self.customer_support_widget, 'save_sessions'):
            self.customer_support_widget.save_sessions()

        try:
            from utils.ui_utils import save_all_table_column_widths
            save_all_table_column_widths()
        except Exception:
            pass
        
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
        
        # 起動直後は「読み込み中」タブのみ表示し、ウィンドウ表示後にタブを構築（起動時間短縮）
        loading_widget = QWidget()
        loading_layout = QVBoxLayout(loading_widget)
        loading_layout.addWidget(QLabel("タブを読み込み中..."))
        self.tab_widget.addTab(loading_widget, "読み込み中...")
        self._tabs_loaded = False
        
        # レイアウトに追加
        main_layout.addWidget(self.tab_widget)
        
        # ウィンドウ表示後にタブを構築（イベントループに1回入ってから実行）
        QTimer.singleShot(0, self._deferred_setup_tabs)
        
    # 段階的タブ構築の間隔（ミリ秒）。起動直後に最初のタブが使えるようにしつつ、残りはバックグラウンドで追加
    _TAB_SETUP_INTERVAL_MS = 35

    def _deferred_setup_tabs(self):
        """ウィンドウ表示後にタブを段階的に構築（起動体感を短縮）"""
        if getattr(self, "_tabs_loaded", False):
            return
        self.tab_widget.removeTab(0)
        # 起動プログレスダイアログを表示（起動しています ○○% ＋ スピナー）
        self._startup_progress = StartupProgressDialog(self)
        self._startup_progress.set_progress(0)
        self._startup_progress.show()
        QApplication.processEvents()
        self._setup_tab_phase = 0
        self._run_next_tab_phase()

    def _run_next_tab_phase(self):
        """次のタブ構築フェーズを実行し、続きがあればタイマーでスケジュール"""
        phase = getattr(self, "_setup_tab_phase", 0)
        try:
            done = self._setup_tabs_phase(phase)
            # フェーズ完了ごとにプログレスを更新（8フェーズで 12, 25, 37, 50, 62, 75, 87, 100%）
            progress_pct = round((phase + 1) * 100 / 8)
            if hasattr(self, "_startup_progress") and self._startup_progress:
                self._startup_progress.set_progress(progress_pct)
                QApplication.processEvents()
            if done:
                self._tabs_loaded = True
                if hasattr(self, "_startup_progress") and self._startup_progress:
                    self._startup_progress.set_progress(100)
                    QApplication.processEvents()
                    self._startup_progress.close()
                    self._startup_progress = None
                self.restore_tab_order()
                QApplication.processEvents()
                return
            self._setup_tab_phase = phase + 1
            QTimer.singleShot(self._TAB_SETUP_INTERVAL_MS, self._run_next_tab_phase)
        except Exception:
            self._tabs_loaded = True
            if hasattr(self, "_startup_progress") and self._startup_progress:
                try:
                    self._startup_progress.close()
                except Exception:
                    pass
                self._startup_progress = None
            self.restore_tab_order()
            raise

    def _on_main_tab_current_changed(self, index: int) -> None:
        """データベース管理タブを初めて開いたときに商品DBの遅延読み込みを開始する。"""
        try:
            if index < 0:
                return
            db_tabs = getattr(self, "_db_management_tabs", None)
            if db_tabs is None or self.tab_widget.widget(index) is not db_tabs:
                return
            product_widget = getattr(self, "product_widget", None)
            if product_widget is not None:
                product_widget.ensure_initial_data_loaded()
            try:
                self._on_db_management_subtab_changed(db_tabs.currentIndex())
            except Exception:
                pass
        except Exception:
            pass

    @staticmethod
    def _build_db_placeholder(text: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label)
        return w

    def _on_db_management_subtab_changed(self, index: int) -> None:
        """データベース管理サブタブの重い画面を表示時に遅延生成する。"""
        try:
            db_tabs = getattr(self, "_db_management_tabs", None)
            if db_tabs is None or index < 0:
                return
            label = db_tabs.tabText(index)
            if label == "店舗マスタ" and getattr(self, "store_master_widget", None) is None:
                from ui.store_master_widget import StoreMasterWidget
                self.store_master_widget = StoreMasterWidget()
                db_tabs.removeTab(index)
                db_tabs.insertTab(index, self.store_master_widget, "店舗マスタ")
                db_tabs.setCurrentIndex(index)
            elif label == "ルート訪問DB" and getattr(self, "route_visit_widget", None) is None:
                from ui.route_visit_widget import RouteVisitLogWidget
                self.route_visit_widget = RouteVisitLogWidget()
                db_tabs.removeTab(index)
                db_tabs.insertTab(index, self.route_visit_widget, "ルート訪問DB")
                db_tabs.setCurrentIndex(index)
        except Exception:
            pass

    def _attach_repricer_settings_lazy(
        self,
        tab_widget: QTabWidget,
        mode: Literal["standard", "369"],
    ) -> None:
        """改定ルールタブは初回表示時だけ生成（起動時の不要な API 読込を防ぐ）。"""
        attr = "repricer_settings_widget" if mode == "standard" else "repricer_settings_widget_369"
        setattr(self, attr, None)

        placeholder = QWidget()
        ph_layout = QVBoxLayout(placeholder)
        ph_label = QLabel("このタブを開くと改定ルール設定を読み込みます。")
        ph_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_layout.addWidget(ph_label)
        tab_widget.addTab(placeholder, "改定ルール")

        def _on_tab_changed(index: int) -> None:
            if index != 1 or getattr(self, attr) is not None:
                return
            from ui.repricer_settings_widget import RepricerSettingsWidget

            widget = RepricerSettingsWidget(self.api_client, mode=mode)
            setattr(self, attr, widget)
            tab_widget.blockSignals(True)
            tab_widget.removeTab(1)
            tab_widget.insertTab(1, widget, "改定ルール")
            tab_widget.setCurrentIndex(1)
            tab_widget.blockSignals(False)

        tab_widget.currentChanged.connect(_on_tab_changed)

    def _setup_tabs_phase(self, phase: int) -> bool:
        """タブを1フェーズずつ構築。True を返すと全タブ完了。"""
        if phase == 0:
            # 価格改定・仕入管理（まずここが使えるようにする）
            from ui.repricer_widget import RepricerWidget
            self.repricer_widget = RepricerWidget(self.api_client, mode="standard")
            repricer_tabs = QTabWidget()
            repricer_tabs.addTab(self.repricer_widget, "改定実行")
            self._attach_repricer_settings_lazy(repricer_tabs, "standard")
            old_reprice_tab_index = self.tab_widget.addTab(repricer_tabs, "旧価格改定")
            self.tab_widget.setTabVisible(old_reprice_tab_index, False)

            # 既存の価格改定タブを複製した「3-6-9価格改定」タブ
            self.repricer_widget_369 = RepricerWidget(self.api_client, mode="369")
            repricer_tabs_369 = QTabWidget()
            repricer_tabs_369.addTab(self.repricer_widget_369, "改定実行")
            self._attach_repricer_settings_lazy(repricer_tabs_369, "369")
            self.tab_widget.addTab(repricer_tabs_369, "価格改定")

            from ui.inventory_widget import InventoryWidget
            from ui.condition_template_widget import ConditionTemplateWidget
            self.inventory_widget = InventoryWidget(self.api_client)
            self.condition_template_widget = ConditionTemplateWidget()
            inventory_tabs = QTabWidget()
            inventory_tabs.addTab(self.inventory_widget, "仕入データ")
            inventory_tabs.addTab(self.condition_template_widget, "コンディション説明")
            old_inventory_tab_index = self.tab_widget.addTab(inventory_tabs, "旧仕入管理")
            self.tab_widget.setTabVisible(old_inventory_tab_index, False)
            # 3-6-9仕入管理: 同一機能だが data_dev / 別QSettings で独立インスタンス（本番DBを壊さない）
            self.inventory_widget_dev = InventoryWidget(self.api_client, dev_mode=True)
            self.condition_template_widget_dev = ConditionTemplateWidget()
            inventory_tabs_dev = QTabWidget()
            inventory_tabs_dev.addTab(self.inventory_widget_dev, "仕入データ")
            inventory_tabs_dev.addTab(self.condition_template_widget_dev, "コンディション説明")
            self.tab_widget.addTab(inventory_tabs_dev, "仕入管理")
            return False

        if phase == 1:
            # 古物台帳・ルート
            from ui.antique_widget import AntiqueWidget
            self.antique_widget = AntiqueWidget(self.api_client, inventory_widget=self.inventory_widget)
            self.tab_widget.addTab(self.antique_widget, "古物台帳")
            from ui.route_summary_widget import RouteSummaryWidget
            from ui.route_list_widget import RouteListWidget
            route_tabs = QTabWidget()
            self.route_summary_widget = RouteSummaryWidget(self.api_client, inventory_widget=self.inventory_widget)
            route_tabs.addTab(self.route_summary_widget, "ルート選択")
            self.route_list_widget = RouteListWidget()
            route_tabs.addTab(self.route_list_widget, "ルートサマリー")
            self.route_summary_widget.data_saved.connect(self.route_list_widget.load_routes)
            from utils.route_utils import set_route_list_refresh_callback, set_route_list_widget
            set_route_list_refresh_callback(self.route_list_widget.load_routes)
            set_route_list_widget(self.route_list_widget)
            self.tab_widget.addTab(route_tabs, "ルート")
            # 本番用仕入管理タブと開発用仕入管理タブの両方にルートウィジェットを接続
            self.inventory_widget.set_route_summary_widget(self.route_summary_widget)
            self.inventory_widget.set_antique_widget(self.antique_widget)
            self.inventory_widget.spot_saved.connect(self.route_list_widget.load_routes)
            # 開発タブ側でもルートテンプレ読込・照合処理を使えるようにする
            if hasattr(self, "inventory_widget_dev") and self.inventory_widget_dev is not None:
                self.inventory_widget_dev.set_route_summary_widget(self.route_summary_widget)
                self.inventory_widget_dev.set_antique_widget(self.antique_widget)
                self.inventory_widget_dev.spot_saved.connect(self.route_list_widget.load_routes)
            return False

        if phase == 2:
            # データベース管理（コンディション説明は仕入管理タブに移動済み）
            from ui.product_widget import ProductWidget
            from ui.data_acquisition_widget import DataAcquisitionWidget
            self.store_master_widget = None
            self.product_widget = ProductWidget(
                inventory_widget=self.inventory_widget,
                api_client=self.api_client,
            )
            if hasattr(self, "repricer_widget") and self.repricer_widget is not None:
                self.repricer_widget.set_product_widget(self.product_widget)
            if hasattr(self, "repricer_widget_369") and self.repricer_widget_369 is not None:
                self.repricer_widget_369.set_product_widget(self.product_widget)
            self.inventory_widget.set_product_widget(self.product_widget)
            if hasattr(self, "customer_support_widget") and self.customer_support_widget is not None:
                self.customer_support_widget.set_product_widget(self.product_widget)
            # 3-6-9仕入管理からDB保存したときも仕入DBタブに即反映するため参照を渡す
            if hasattr(self, "inventory_widget_dev") and self.inventory_widget_dev is not None:
                self.inventory_widget_dev.set_product_widget(self.product_widget)
            self.route_visit_widget = None
            db_management_tabs = QTabWidget()
            db_management_tabs.addTab(self.product_widget, "商品DB")
            db_management_tabs.addTab(self._build_db_placeholder("店舗マスタを開くと読み込みます"), "店舗マスタ")
            db_management_tabs.addTab(self._build_db_placeholder("ルート訪問DBを開くと読み込みます"), "ルート訪問DB")
            self._db_management_tabs = db_management_tabs
            if not getattr(self, "_db_mgmt_subtab_hook_connected", False):
                self._db_management_tabs.currentChanged.connect(self._on_db_management_subtab_changed)
                self._db_mgmt_subtab_hook_connected = True
            self.tab_widget.addTab(db_management_tabs, "データベース管理")
            if not getattr(self, "_db_mgmt_tab_hook_connected", False):
                self.tab_widget.currentChanged.connect(self._on_main_tab_current_changed)
                self._db_mgmt_tab_hook_connected = True
            # 基礎データ取得タブ（Amazonレポート/SP-API 連携の入口）
            self.data_acquisition_widget = DataAcquisitionWidget()
            self.tab_widget.addTab(self.data_acquisition_widget, "データ取得")
            return False

        if phase == 3:
            # バッチ処理・分析
            from ui.store_code_batch_widget import StoreCodeBatchWidget
            self.store_code_batch_widget = StoreCodeBatchWidget()
            self.tab_widget.addTab(self.store_code_batch_widget, "バッチ処理")
            from ui.analysis_widget import AnalysisWidget
            self.analysis_widget = AnalysisWidget()
            self.tab_widget.addTab(self.analysis_widget, "分析")
            return False

        if phase == 4:
            # 証憑管理
            from ui.evidence_manager_widget import EvidenceManagerWidget
            self.evidence_widget = EvidenceManagerWidget(
                self.api_client,
                inventory_widget=self.inventory_widget,
                product_widget=self.product_widget
            )
            if hasattr(self.evidence_widget, 'receipt_widget'):
                self.evidence_widget.receipt_widget.set_evidence_widget(self.evidence_widget)
            self.tab_widget.addTab(self.evidence_widget, "証憑管理")
            return False

        if phase == 5:
            # 台帳
            from ui.purchase_ledger_widget import PurchaseLedgerWidget
            from ui.expense_ledger_widget import ExpenseLedgerWidget
            ledger_tabs = QTabWidget()
            self.purchase_ledger_widget = PurchaseLedgerWidget(self.api_client)
            ledger_tabs.addTab(self.purchase_ledger_widget, "仕入台帳")
            self.expense_ledger_widget = ExpenseLedgerWidget(self.api_client)
            ledger_tabs.addTab(self.expense_ledger_widget, "経費台帳")
            self.tab_widget.addTab(ledger_tabs, "台帳")
            return False

        if phase == 6:
            # バーコードチェッカー・画像管理
            from ui.barcode_checker_widget import BarcodeCheckerWidget
            self.barcode_checker_widget = BarcodeCheckerWidget()
            self.tab_widget.addTab(self.barcode_checker_widget, "バーコードチェッカー")
            from ui.image_manager_widget import ImageManagerWidget
            self.image_manager_widget = ImageManagerWidget(self.api_client)
            self.image_manager_widget.set_product_widget(self.product_widget)
            self.tab_widget.addTab(self.image_manager_widget, "画像管理")
            return False

        if phase == 7:
            # Keepaテスト・SP-APIテスト・画像テスト・カスタマー対応AI・設定（最後に設定タブ）
            from ui.keepa_test_widget import KeepaTestWidget
            from ui.sp_api_test_widget import SPAPITestWidget
            from ui.image_test_widget import ImageTestWidget
            from ui.customer_support_widget import CustomerSupportWidget
            from ui.settings_widget import SettingsWidget
            self.keepa_test_widget = KeepaTestWidget(product_widget=getattr(self, "product_widget", None))
            self.tab_widget.addTab(self.keepa_test_widget, "Keepaテスト")
            self.sp_api_test_widget = SPAPITestWidget()
            self.tab_widget.addTab(self.sp_api_test_widget, "SP-APIテスト")
            self.image_test_widget = ImageTestWidget()
            self.tab_widget.addTab(self.image_test_widget, "画像テスト")
            self.customer_support_widget = CustomerSupportWidget(
                product_widget=getattr(self, "product_widget", None)
            )
            self.tab_widget.addTab(self.customer_support_widget, "カスタマー対応AI")
            self.settings_widget = SettingsWidget(self.api_client)
            self.settings_widget.settings_changed.connect(self.on_settings_changed)
            self.tab_widget.addTab(self.settings_widget, "設定")
            return True

        return True
        
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
        """API接続状況のチェック（/health へ実際に問い合わせ）"""
        if not getattr(self, "api_status_label", None):
            return
        self.api_status_label.setText("API: 確認中…")
        self.api_status_label.setStyleSheet("color: gray;")
        QTimer.singleShot(0, self._refresh_api_status_label)

    def _refresh_api_status_label(self):
        """FastAPI /health の応答でステータスバーを更新"""
        try:
            if not self.api_client:
                self.api_status_label.setText("API: 未接続")
                self.api_status_label.setStyleSheet("color: red;")
                return
            if self.api_client.test_connection():
                self.api_status_label.setText("API: 接続済み")
                self.api_status_label.setStyleSheet("color: green;")
            else:
                self.api_status_label.setText("API: 未接続")
                self.api_status_label.setStyleSheet("color: red;")
        except Exception:
            self.api_status_label.setText("API: エラー")
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
                base = getattr(self.api_client, "base_url", "http://127.0.0.1:8000")
                QMessageBox.warning(
                    self,
                    "API接続テスト",
                    "FastAPIサーバーに接続できませんでした。\n\n"
                    f"接続先: {base}/health\n\n"
                    "確認:\n"
                    "1) ツール → FastAPIサーバー起動（または python フォルダで python app.py）\n"
                    "2) 黒い画面を2つ開いていないか（8000番の取り合い）\n"
                    "3) 設定の API URL が http://127.0.0.1:8000 か\n"
                    "4) 価格改定プレビュー処理中は数十秒かかることがあります（完了まで待つ）",
                )
        except Exception as e:
            base = getattr(self.api_client, "base_url", "http://127.0.0.1:8000")
            QMessageBox.warning(
                self,
                "API接続エラー",
                f"API接続に失敗しました:\n{str(e)}\n\n接続先: {base}/health",
            )
            
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
                    try:
                        self.api_client.request_timeout = max(5, int(api_settings['timeout']))
                    except (TypeError, ValueError):
                        pass
                self.check_api_connection()
            
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
        if not getattr(self, "_tabs_loaded", False):
            return
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
