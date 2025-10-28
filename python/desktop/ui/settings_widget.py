#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
設定ウィジェット

アプリケーション設定
- API接続設定
- デフォルトディレクトリ設定
- 表示設定
- ログ設定
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QCheckBox,
    QGroupBox, QTabWidget, QTextEdit, QFileDialog,
    QMessageBox, QComboBox, QSlider
)
from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtGui import QFont
import json
from pathlib import Path


class SettingsWidget(QWidget):
    """設定ウィジェット"""
    
    settings_changed = Signal(dict)  # 設定変更シグナル
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.settings = QSettings("HIRIO", "DesktopApp")
        
        # UIの初期化
        self.setup_ui()
        self.load_settings()
        
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # タブウィジェットの作成
        tab_widget = QTabWidget()
        
        # 各設定タブの追加
        self.setup_api_tab(tab_widget)
        self.setup_display_tab(tab_widget)
        self.setup_advanced_tab(tab_widget)
        self.setup_about_tab(tab_widget)
        
        layout.addWidget(tab_widget)
        
        # 下部：保存・リセットボタン
        self.setup_action_buttons(layout)
        
    def setup_api_tab(self, parent):
        """API設定タブ"""
        api_widget = QWidget()
        layout = QVBoxLayout(api_widget)
        
        # API接続設定
        api_group = QGroupBox("API接続設定")
        api_layout = QGridLayout(api_group)
        
        # ベースURL
        api_layout.addWidget(QLabel("APIベースURL:"), 0, 0)
        self.api_url_edit = QLineEdit("http://localhost:8000")
        self.api_url_edit.setPlaceholderText("http://localhost:8000")
        api_layout.addWidget(self.api_url_edit, 0, 1)
        
        # タイムアウト設定
        api_layout.addWidget(QLabel("タイムアウト(秒):"), 1, 0)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(30)
        api_layout.addWidget(self.timeout_spin, 1, 1)
        
        # 接続テストボタン
        self.test_connection_btn = QPushButton("接続テスト")
        self.test_connection_btn.clicked.connect(self.test_api_connection)
        api_layout.addWidget(self.test_connection_btn, 2, 0, 1, 2)
        
        layout.addWidget(api_group)
        
        # デフォルトディレクトリ設定
        dir_group = QGroupBox("デフォルトディレクトリ設定")
        dir_layout = QGridLayout(dir_group)
        
        # CSVファイル用ディレクトリ
        dir_layout.addWidget(QLabel("CSVファイル用:"), 0, 0)
        self.csv_dir_edit = QLineEdit()
        self.csv_dir_edit.setPlaceholderText("CSVファイルのデフォルトディレクトリ")
        dir_layout.addWidget(self.csv_dir_edit, 0, 1)
        
        csv_browse_btn = QPushButton("参照")
        csv_browse_btn.clicked.connect(lambda: self.browse_directory(self.csv_dir_edit))
        dir_layout.addWidget(csv_browse_btn, 0, 2)
        
        # 結果保存用ディレクトリ
        dir_layout.addWidget(QLabel("結果保存用:"), 1, 0)
        self.result_dir_edit = QLineEdit()
        self.result_dir_edit.setPlaceholderText("結果保存のデフォルトディレクトリ")
        dir_layout.addWidget(self.result_dir_edit, 1, 1)
        
        result_browse_btn = QPushButton("参照")
        result_browse_btn.clicked.connect(lambda: self.browse_directory(self.result_dir_edit))
        dir_layout.addWidget(result_browse_btn, 1, 2)
        
        layout.addWidget(dir_group)
        
        layout.addStretch()
        parent.addTab(api_widget, "API設定")
        
    def setup_display_tab(self, parent):
        """表示設定タブ"""
        display_widget = QWidget()
        layout = QVBoxLayout(display_widget)
        
        # テーブル表示設定
        table_group = QGroupBox("テーブル表示設定")
        table_layout = QGridLayout(table_group)
        
        # 行の高さ
        table_layout.addWidget(QLabel("行の高さ:"), 0, 0)
        self.row_height_spin = QSpinBox()
        self.row_height_spin.setRange(20, 100)
        self.row_height_spin.setValue(25)
        table_layout.addWidget(self.row_height_spin, 0, 1)
        
        # フォントサイズ
        table_layout.addWidget(QLabel("フォントサイズ:"), 1, 0)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 16)
        self.font_size_spin.setValue(9)
        table_layout.addWidget(self.font_size_spin, 1, 1)
        
        # 交互行色
        self.alternating_colors_cb = QCheckBox("交互行色を有効にする")
        self.alternating_colors_cb.setChecked(True)
        table_layout.addWidget(self.alternating_colors_cb, 2, 0, 1, 2)
        
        # ソート機能
        self.sorting_enabled_cb = QCheckBox("ソート機能を有効にする")
        self.sorting_enabled_cb.setChecked(True)
        table_layout.addWidget(self.sorting_enabled_cb, 3, 0, 1, 2)
        
        layout.addWidget(table_group)
        
        # 価格改定結果表示設定
        result_group = QGroupBox("価格改定結果表示設定")
        result_layout = QGridLayout(result_group)
        
        # Title列の文字数制限
        result_layout.addWidget(QLabel("Title列の文字数制限:"), 0, 0)
        self.title_limit_spin = QSpinBox()
        self.title_limit_spin.setRange(20, 100)
        self.title_limit_spin.setValue(50)
        result_layout.addWidget(self.title_limit_spin, 0, 1)
        
        # 価格変更の色分け
        self.price_color_cb = QCheckBox("価格変更の色分けを有効にする")
        self.price_color_cb.setChecked(True)
        result_layout.addWidget(self.price_color_cb, 1, 0, 1, 2)
        
        # ツールチップ表示
        self.tooltip_enabled_cb = QCheckBox("ツールチップを有効にする")
        self.tooltip_enabled_cb.setChecked(True)
        result_layout.addWidget(self.tooltip_enabled_cb, 2, 0, 1, 2)
        
        layout.addWidget(result_group)
        
        layout.addStretch()
        parent.addTab(display_widget, "表示設定")
        
    def setup_advanced_tab(self, parent):
        """詳細設定タブ"""
        advanced_widget = QWidget()
        layout = QVBoxLayout(advanced_widget)
        
        # パフォーマンス設定
        perf_group = QGroupBox("パフォーマンス設定")
        perf_layout = QGridLayout(perf_group)
        
        # 最大表示行数
        perf_layout.addWidget(QLabel("最大表示行数:"), 0, 0)
        self.max_rows_spin = QSpinBox()
        self.max_rows_spin.setRange(100, 10000)
        self.max_rows_spin.setValue(1000)
        perf_layout.addWidget(self.max_rows_spin, 0, 1)
        
        # バッチサイズ
        perf_layout.addWidget(QLabel("バッチサイズ:"), 1, 0)
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(10, 1000)
        self.batch_size_spin.setValue(50)
        perf_layout.addWidget(self.batch_size_spin, 1, 1)
        
        # 自動保存
        self.auto_save_cb = QCheckBox("処理結果の自動保存を有効にする")
        self.auto_save_cb.setChecked(False)
        perf_layout.addWidget(self.auto_save_cb, 2, 0, 1, 2)
        
        layout.addWidget(perf_group)
        
        # ログ設定
        log_group = QGroupBox("ログ設定")
        log_layout = QGridLayout(log_group)
        
        # ログレベル
        log_layout.addWidget(QLabel("ログレベル:"), 0, 0)
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        log_layout.addWidget(self.log_level_combo, 0, 1)
        
        # ログファイル保存
        self.log_file_cb = QCheckBox("ログファイルを保存する")
        self.log_file_cb.setChecked(True)
        log_layout.addWidget(self.log_file_cb, 1, 0, 1, 2)
        
        # ログファイルパス
        log_layout.addWidget(QLabel("ログファイルパス:"), 2, 0)
        self.log_file_edit = QLineEdit("logs/hirio.log")
        log_layout.addWidget(self.log_file_edit, 2, 1)
        
        log_browse_btn = QPushButton("参照")
        log_browse_btn.clicked.connect(lambda: self.browse_file(self.log_file_edit, "ログファイル"))
        log_layout.addWidget(log_browse_btn, 2, 2)
        
        layout.addWidget(log_group)
        
        layout.addStretch()
        parent.addTab(advanced_widget, "詳細設定")
        
    def setup_about_tab(self, parent):
        """アプリケーション情報タブ"""
        about_widget = QWidget()
        layout = QVBoxLayout(about_widget)
        
        # アプリケーション情報
        info_group = QGroupBox("アプリケーション情報")
        info_layout = QVBoxLayout(info_group)
        
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMaximumHeight(200)
        info_text.setHtml("""
        <h3>HIRIO - せどり業務統合システム</h3>
        <p><b>バージョン:</b> 1.0.0</p>
        <p><b>技術スタック:</b> PySide6 + FastAPI + SQLite</p>
        <p><b>開発目標:</b> 年内MVP（仕入管理システム完成）</p>
        <p><b>主要機能:</b></p>
        <ul>
        <li>価格改定機能（既存FastAPI活用）</li>
        <li>仕入管理システム</li>
        <li>古物台帳自動生成</li>
        <li>一括実行ワークフロー</li>
        </ul>
        <p><b>© 2025 HIRIO Project</b></p>
        """)
        info_layout.addWidget(info_text)
        
        layout.addWidget(info_group)
        
        # システム情報
        system_group = QGroupBox("システム情報")
        system_layout = QVBoxLayout(system_group)
        
        system_text = QTextEdit()
        system_text.setReadOnly(True)
        system_text.setMaximumHeight(150)
        system_text.setPlainText(f"""
Python バージョン: {__import__('sys').version}
PySide6 バージョン: {__import__('PySide6').__version__}
作業ディレクトリ: {Path.cwd()}
設定ファイル: {self.settings.fileName()}
        """)
        system_layout.addWidget(system_text)
        
        layout.addWidget(system_group)
        
        layout.addStretch()
        parent.addTab(about_widget, "アプリケーション情報")
        
    def setup_action_buttons(self, parent_layout):
        """アクションボタンの設定"""
        button_layout = QHBoxLayout()
        
        # 保存ボタン
        self.save_btn = QPushButton("設定を保存")
        self.save_btn.clicked.connect(self.save_settings)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
        """)
        button_layout.addWidget(self.save_btn)
        
        # リセットボタン
        self.reset_btn = QPushButton("設定をリセット")
        self.reset_btn.clicked.connect(self.reset_settings)
        button_layout.addWidget(self.reset_btn)
        
        # デフォルトボタン
        self.default_btn = QPushButton("デフォルトに戻す")
        self.default_btn.clicked.connect(self.load_default_settings)
        button_layout.addWidget(self.default_btn)
        
        button_layout.addStretch()
        parent_layout.addLayout(button_layout)
        
    def browse_directory(self, line_edit):
        """ディレクトリ選択ダイアログ"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "ディレクトリを選択",
            line_edit.text() or str(Path.home())
        )
        if directory:
            line_edit.setText(directory)
            
    def browse_file(self, line_edit, title):
        """ファイル選択ダイアログ"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            line_edit.text() or str(Path.home()),
            "すべてのファイル (*)"
        )
        if file_path:
            line_edit.setText(file_path)
            
    def test_api_connection(self):
        """API接続テスト"""
        try:
            # 一時的にAPIクライアントのURLを更新
            original_url = self.api_client.base_url
            self.api_client.base_url = self.api_url_edit.text()
            
            if self.api_client.test_connection():
                QMessageBox.information(self, "接続テスト", "API接続に成功しました")
            else:
                QMessageBox.warning(self, "接続テスト", "API接続に失敗しました")
                
            # URLを元に戻す
            self.api_client.base_url = original_url
            
        except Exception as e:
            QMessageBox.critical(self, "接続テストエラー", f"接続テスト中にエラーが発生しました:\n{str(e)}")
            
    def load_settings(self):
        """設定の読み込み"""
        # API設定
        self.api_url_edit.setText(self.settings.value("api/url", "http://localhost:8000"))
        self.timeout_spin.setValue(int(self.settings.value("api/timeout", 30)))
        
        # ディレクトリ設定
        self.csv_dir_edit.setText(self.settings.value("directories/csv", ""))
        self.result_dir_edit.setText(self.settings.value("directories/result", ""))
        
        # 表示設定
        self.row_height_spin.setValue(int(self.settings.value("display/row_height", 25)))
        self.font_size_spin.setValue(int(self.settings.value("display/font_size", 9)))
        self.alternating_colors_cb.setChecked(self.settings.value("display/alternating_colors", True, type=bool))
        self.sorting_enabled_cb.setChecked(self.settings.value("display/sorting_enabled", True, type=bool))
        self.title_limit_spin.setValue(int(self.settings.value("display/title_limit", 50)))
        self.price_color_cb.setChecked(self.settings.value("display/price_color", True, type=bool))
        self.tooltip_enabled_cb.setChecked(self.settings.value("display/tooltip_enabled", True, type=bool))
        
        # パフォーマンス設定
        self.max_rows_spin.setValue(int(self.settings.value("performance/max_rows", 1000)))
        self.batch_size_spin.setValue(int(self.settings.value("performance/batch_size", 50)))
        self.auto_save_cb.setChecked(self.settings.value("performance/auto_save", False, type=bool))
        
        # ログ設定
        self.log_level_combo.setCurrentText(self.settings.value("log/level", "INFO"))
        self.log_file_cb.setChecked(self.settings.value("log/file_enabled", True, type=bool))
        self.log_file_edit.setText(self.settings.value("log/file_path", "logs/hirio.log"))
        
    def save_settings(self):
        """設定の保存"""
        try:
            # API設定
            self.settings.setValue("api/url", self.api_url_edit.text())
            self.settings.setValue("api/timeout", self.timeout_spin.value())
            
            # ディレクトリ設定
            self.settings.setValue("directories/csv", self.csv_dir_edit.text())
            self.settings.setValue("directories/result", self.result_dir_edit.text())
            
            # 表示設定
            self.settings.setValue("display/row_height", self.row_height_spin.value())
            self.settings.setValue("display/font_size", self.font_size_spin.value())
            self.settings.setValue("display/alternating_colors", self.alternating_colors_cb.isChecked())
            self.settings.setValue("display/sorting_enabled", self.sorting_enabled_cb.isChecked())
            self.settings.setValue("display/title_limit", self.title_limit_spin.value())
            self.settings.setValue("display/price_color", self.price_color_cb.isChecked())
            self.settings.setValue("display/tooltip_enabled", self.tooltip_enabled_cb.isChecked())
            
            # パフォーマンス設定
            self.settings.setValue("performance/max_rows", self.max_rows_spin.value())
            self.settings.setValue("performance/batch_size", self.batch_size_spin.value())
            self.settings.setValue("performance/auto_save", self.auto_save_cb.isChecked())
            
            # ログ設定
            self.settings.setValue("log/level", self.log_level_combo.currentText())
            self.settings.setValue("log/file_enabled", self.log_file_cb.isChecked())
            self.settings.setValue("log/file_path", self.log_file_edit.text())
            
            # 設定変更シグナルを発火
            settings_dict = self.get_current_settings()
            self.settings_changed.emit(settings_dict)
            
            QMessageBox.information(self, "設定保存", "設定を保存しました")
            
        except Exception as e:
            QMessageBox.critical(self, "設定保存エラー", f"設定の保存に失敗しました:\n{str(e)}")
            
    def reset_settings(self):
        """設定のリセット"""
        reply = QMessageBox.question(
            self,
            "設定リセット確認",
            "現在の設定をリセットしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.settings.clear()
            self.load_settings()
            QMessageBox.information(self, "設定リセット", "設定をリセットしました")
            
    def load_default_settings(self):
        """デフォルト設定の読み込み"""
        # デフォルト値を設定
        self.api_url_edit.setText("http://localhost:8000")
        self.timeout_spin.setValue(30)
        self.csv_dir_edit.setText("")
        self.result_dir_edit.setText("")
        self.row_height_spin.setValue(25)
        self.font_size_spin.setValue(9)
        self.alternating_colors_cb.setChecked(True)
        self.sorting_enabled_cb.setChecked(True)
        self.title_limit_spin.setValue(50)
        self.price_color_cb.setChecked(True)
        self.tooltip_enabled_cb.setChecked(True)
        self.max_rows_spin.setValue(1000)
        self.batch_size_spin.setValue(50)
        self.auto_save_cb.setChecked(False)
        self.log_level_combo.setCurrentText("INFO")
        self.log_file_cb.setChecked(True)
        self.log_file_edit.setText("logs/hirio.log")
        
    def get_current_settings(self):
        """現在の設定を辞書で取得"""
        return {
            "api": {
                "url": self.api_url_edit.text(),
                "timeout": self.timeout_spin.value()
            },
            "directories": {
                "csv": self.csv_dir_edit.text(),
                "result": self.result_dir_edit.text()
            },
            "display": {
                "row_height": self.row_height_spin.value(),
                "font_size": self.font_size_spin.value(),
                "alternating_colors": self.alternating_colors_cb.isChecked(),
                "sorting_enabled": self.sorting_enabled_cb.isChecked(),
                "title_limit": self.title_limit_spin.value(),
                "price_color": self.price_color_cb.isChecked(),
                "tooltip_enabled": self.tooltip_enabled_cb.isChecked()
            },
            "performance": {
                "max_rows": self.max_rows_spin.value(),
                "batch_size": self.batch_size_spin.value(),
                "auto_save": self.auto_save_cb.isChecked()
            },
            "log": {
                "level": self.log_level_combo.currentText(),
                "file_enabled": self.log_file_cb.isChecked(),
                "file_path": self.log_file_edit.text()
            }
        }
