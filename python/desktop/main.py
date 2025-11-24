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

# 例外ロギング（できるだけ早くセット）
import traceback
from datetime import datetime
LOG_PATH = Path(__file__).parent / "desktop_error.log"

def _log_error(message: str):
    try:
        LOG_PATH.write_text("", encoding="utf-8") if not LOG_PATH.exists() else None
    except Exception:
        pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
            f.write(message)
            f.write("\n\n")
    except Exception:
        pass

def _global_excepthook(exc_type, exc_value, exc_tb):
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _log_error(tb_text)
    try:
        # 既にQApplicationがあればそのままダイアログ表示、無ければ一時作成
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "エラー", f"未処理の例外が発生しました。\n\nログ: {LOG_PATH}\n\n詳細:\n{tb_text}")
    except Exception:
        # それでも無理なら標準出力
        print(tb_text)
    finally:
        # 終了コードを返す
        os._exit(1)

# PySide6のインポート（excepthook設定後）
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont

# グローバル例外ハンドラを登録
sys.excepthook = _global_excepthook


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
        
        # APIクライアントとメインウィンドウの作成（インポート含めて保護）
        try:
            from api.client import APIClient
        except Exception as e:
            _log_error("APIClient import error:\n" + "".join(traceback.format_exception(type(e), e, e.__traceback__)))
            raise
        try:
            from ui.main_window import MainWindow
        except Exception as e:
            _log_error("MainWindow import error:\n" + "".join(traceback.format_exception(type(e), e, e.__traceback__)))
            raise
        try:
            from ui.utils.copy_context_menu import install_copy_context_menu
        except Exception as e:
            _log_error("copy_context_menu import error:\n" + "".join(traceback.format_exception(type(e), e, e.__traceback__)))
            raise
        
        self.api_client = APIClient()
        self.main_window = MainWindow(self.api_client)
        self.main_window.show()
        install_copy_context_menu(self.app)
        
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
            import traceback
            tb_text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            _log_error(tb_text)
            print(f"アプリケーション実行エラー: {e}")
            QMessageBox.critical(
                None, 
                "エラー", 
                f"アプリケーションの起動に失敗しました:\n{str(e)}\n\nログ: {LOG_PATH}"
            )
            return 1


def main():
    """メイン関数"""
    print("HIRIO デスクトップアプリを起動中...")
    # グローバル例外ハンドラ（コンソールが一瞬で閉じる環境でもログに残す）
    sys.excepthook = _global_excepthook
    
    # アプリケーションの作成と実行
    hirio_app = HIRIOApplication()
    exit_code = hirio_app.run()
    
    print("HIRIO アプリケーションを終了します")
    return exit_code


if __name__ == "__main__":
    main()
