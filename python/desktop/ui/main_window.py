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
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence
import subprocess
import threading
import time

# プロジェクト内のモジュール
from ui.repricer_widget import RepricerWidget
from ui.repricer_settings_widget import RepricerSettingsWidget
from ui.inventory_widget import InventoryWidget
from ui.workflow_panel import WorkflowPanel


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
            self.process = subprocess.Popen([
                "python", "-m", "uvicorn", 
                "python.app:app", 
                "--host", "localhost", 
                "--port", "8000",
                "--reload"
            ], cwd="..")  # プロジェクトルートに移動
            
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
        
        # 各タブの追加
        self.setup_tabs()
        
        # レイアウトに追加
        main_layout.addWidget(self.tab_widget)
        
    def setup_tabs(self):
        """タブの設定"""
        # 価格改定タブ
        self.repricer_widget = RepricerWidget(self.api_client)
        self.tab_widget.addTab(self.repricer_widget, "価格改定")
        
        # 価格改定ルール設定タブ
        self.repricer_settings_widget = RepricerSettingsWidget(self.api_client)
        self.tab_widget.addTab(self.repricer_settings_widget, "価格改定ルール")
        
        # 仕入管理タブ
        self.inventory_widget = InventoryWidget(self.api_client)
        self.tab_widget.addTab(self.inventory_widget, "仕入管理")
        
        # 古物台帳タブ（プレースホルダー）
        self.antique_widget = QWidget()
        antique_layout = QVBoxLayout(self.antique_widget)
        antique_layout.addWidget(QLabel("古物台帳機能（開発予定）"))
        self.tab_widget.addTab(self.antique_widget, "古物台帳")
        
        # 設定タブ（プレースホルダー）
        self.settings_widget = QWidget()
        settings_layout = QVBoxLayout(self.settings_widget)
        settings_layout.addWidget(QLabel("設定画面（開発予定）"))
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
            QMessageBox.information(self, "サーバー停止", "FastAPIサーバーは起動していません")
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
