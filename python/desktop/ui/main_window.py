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
    QMessageBox, QSplitter
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence

# プロジェクト内のモジュール
from ui.repricer_widget import RepricerWidget
from ui.inventory_widget import InventoryWidget
from ui.workflow_panel import WorkflowPanel


class MainWindow(QMainWindow):
    """HIRIOメインウィンドウ"""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.workflow_panel = None
        
        # UIの初期化
        self.setup_ui()
        self.setup_menu()
        self.setup_status_bar()
        self.setup_workflow_panel()
        
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
        
        # ワークフローパネルの追加
        try:
            self.workflow_panel = WorkflowPanel(self.api_client)
            print(f"WorkflowPanel created: {type(self.workflow_panel)}")
            main_layout.addWidget(self.workflow_panel)
            print("WorkflowPanel added to layout")
        except Exception as e:
            print(f"Error creating WorkflowPanel: {e}")
            import traceback
            traceback.print_exc()
        
    def setup_tabs(self):
        """タブの設定"""
        # 価格改定タブ
        self.repricer_widget = RepricerWidget(self.api_client)
        self.tab_widget.addTab(self.repricer_widget, "価格改定")
        
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
        
        # ワークフローパネルの表示/非表示
        workflow_action = QAction("ワークフローパネル(&W)", self)
        workflow_action.setCheckable(True)
        workflow_action.setChecked(True)
        workflow_action.triggered.connect(self.toggle_workflow_panel)
        view_menu.addAction(workflow_action)
        
        # ツールメニュー
        tools_menu = menubar.addMenu("ツール(&T)")
        
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
        
    def setup_workflow_panel(self):
        """ワークフローパネルの設定"""
        # ワークフローパネルは既にsetup_uiで追加済み
        pass
        
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
        
    def toggle_workflow_panel(self, checked):
        """ワークフローパネルの表示/非表示"""
        if checked:
            self.workflow_panel.show()
        else:
            self.workflow_panel.hide()
            
    def test_api_connection(self):
        """API接続テスト"""
        try:
            # ダミーのAPI接続テスト
            self.status_label.setText("API接続テスト中...")
            QTimer.singleShot(1000, self.api_test_completed)
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
