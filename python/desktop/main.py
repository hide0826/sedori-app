#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HIRIO PySide6 デスクトップアプリ - メインエントリーポイント

せどり業務統合システム
- 価格改定機能（既存FastAPI活用）
- 仕入管理システム
- 古物台帳自動生成
- 一括実行ワークフロー

技術スタック: PySide6 + FastAPI + SQLite
"""

import sys
import os
from pathlib import Path

# PySide6のインポート
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont

# プロジェクト内のモジュール
from ui.main_window import MainWindow
from api.client import APIClient


class HIRIOApplication:
    """HIRIOアプリケーションのメインクラス"""
    
    def __init__(self):
        self.app = None
        self.main_window = None
        self.api_client = None
        
    def setup_application(self):
        """アプリケーションの初期設定"""
        # QApplicationの作成
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("HIRIO - せどり業務統合システム")
        self.app.setApplicationVersion("1.0.0")
        self.app.setOrganizationName("HIRIO")
        
        # アプリケーション設定（非推奨の属性は削除）
        # self.app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        # self.app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        
        # フォント設定
        font = QFont("Segoe UI", 9)
        self.app.setFont(font)
        
        # APIクライアントの初期化
        self.api_client = APIClient()
        
        # メインウィンドウの作成
        self.main_window = MainWindow(self.api_client)
        self.main_window.show()
        
        # スタイルシートの適用
        self.load_styles()
        
    def load_styles(self):
        """スタイルシートの読み込み"""
        try:
            style_path = Path(__file__).parent / "ui" / "styles.qss"
            if style_path.exists():
                with open(style_path, 'r', encoding='utf-8') as f:
                    style = f.read()
                    self.app.setStyleSheet(style)
            else:
                print(f"警告: スタイルシートが見つかりません: {style_path}")
        except Exception as e:
            print(f"スタイルシート読み込みエラー: {e}")
    
    def run(self):
        """アプリケーションの実行"""
        try:
            # アプリケーション設定
            self.setup_application()
            
            # メインループの開始
            return self.app.exec()
            
        except Exception as e:
            print(f"アプリケーション実行エラー: {e}")
            QMessageBox.critical(
                None, 
                "エラー", 
                f"アプリケーションの起動に失敗しました:\n{str(e)}"
            )
            return 1


def main():
    """メイン関数"""
    print("HIRIO デスクトップアプリを起動中...")
    
    # アプリケーションの作成と実行
    hirio_app = HIRIOApplication()
    exit_code = hirio_app.run()
    
    print("HIRIO アプリケーションを終了します")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
