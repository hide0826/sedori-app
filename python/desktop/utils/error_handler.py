#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
エラーハンドリングユーティリティ

ユーザーフレンドリーなエラーメッセージの提供
"""

import traceback
import logging
from typing import Dict, Any, Optional
from PySide6.QtWidgets import QMessageBox, QWidget
from PySide6.QtCore import QObject, Signal


class ErrorHandler(QObject):
    """エラーハンドリングクラス"""
    
    error_occurred = Signal(str, str)  # エラーメッセージ, 詳細情報
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
    def handle_exception(self, exception: Exception, context: str = "") -> str:
        """例外を処理してユーザーフレンドリーなメッセージを返す"""
        try:
            error_type = type(exception).__name__
            error_message = str(exception)
            
            # エラータイプに応じたメッセージの生成
            user_message = self._generate_user_message(error_type, error_message, context)
            
            # ログに記録
            self.logger.error(f"Error in {context}: {error_message}", exc_info=True)
            
            # シグナルを発火
            self.error_occurred.emit(user_message, error_message)
            
            return user_message
            
        except Exception as e:
            # エラーハンドリング自体でエラーが発生した場合
            fallback_message = f"予期しないエラーが発生しました: {str(e)}"
            self.logger.critical(f"Error in error handler: {e}", exc_info=True)
            return fallback_message
    
    def _generate_user_message(self, error_type: str, error_message: str, context: str) -> str:
        """エラータイプに応じたユーザーメッセージを生成"""
        
        # ファイル関連エラー
        if "FileNotFoundError" in error_type:
            return f"ファイルが見つかりません。\nファイルパスを確認してください。\n\n詳細: {error_message}"
        
        elif "PermissionError" in error_type:
            return f"ファイルへのアクセスが拒否されました。\nファイルが他のアプリケーションで使用されていないか確認してください。\n\n詳細: {error_message}"
        
        elif "UnicodeDecodeError" in error_type:
            return f"ファイルの文字エンコーディングに問題があります。\nUTF-8エンコーディングのCSVファイルを使用してください。\n\n詳細: {error_message}"
        
        # ネットワーク関連エラー
        elif "ConnectionError" in error_type or "requests.exceptions.ConnectionError" in error_type:
            return f"APIサーバーに接続できません。\nサーバーが起動しているか確認してください。\n\n詳細: {error_message}"
        
        elif "TimeoutError" in error_type or "requests.exceptions.Timeout" in error_type:
            return f"APIサーバーへの接続がタイムアウトしました。\nネットワーク接続を確認してください。\n\n詳細: {error_message}"
        
        # データ関連エラー
        elif "KeyError" in error_type:
            return f"必要なデータが見つかりません。\nCSVファイルの列名を確認してください。\n\n詳細: {error_message}"
        
        elif "ValueError" in error_type:
            return f"データの形式に問題があります。\n数値データが正しい形式か確認してください。\n\n詳細: {error_message}"
        
        elif "pandas.errors" in error_type:
            return f"CSVファイルの読み込みに失敗しました。\nファイル形式を確認してください。\n\n詳細: {error_message}"
        
        # メモリ関連エラー
        elif "MemoryError" in error_type:
            return f"メモリが不足しています。\nデータサイズを小さくするか、システムのメモリを確認してください。\n\n詳細: {error_message}"
        
        # 権限関連エラー
        elif "PermissionError" in error_type:
            return f"ファイルへの書き込み権限がありません。\n管理者権限で実行するか、ファイルの権限を確認してください。\n\n詳細: {error_message}"
        
        # その他のエラー
        else:
            return f"エラーが発生しました。\n\nエラータイプ: {error_type}\n詳細: {error_message}\n\n問題が解決しない場合は、ログファイルを確認してください。"
    
    def show_error_dialog(self, parent: QWidget, title: str, message: str, details: str = ""):
        """エラーダイアログを表示"""
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        
        if details:
            msg_box.setDetailedText(details)
        
        msg_box.exec()
    
    def show_warning_dialog(self, parent: QWidget, title: str, message: str):
        """警告ダイアログを表示"""
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.exec()
    
    def show_info_dialog(self, parent: QWidget, title: str, message: str):
        """情報ダイアログを表示"""
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.exec()


class ValidationError(Exception):
    """バリデーションエラー"""
    pass


class APIError(Exception):
    """APIエラー"""
    def __init__(self, message: str, status_code: int = None, response_data: Dict[str, Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class FileProcessingError(Exception):
    """ファイル処理エラー"""
    pass


class DataProcessingError(Exception):
    """データ処理エラー"""
    pass


def safe_execute(func, *args, **kwargs):
    """安全な関数実行（エラーハンドリング付き）"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_handler = ErrorHandler()
        return error_handler.handle_exception(e, f"Function: {func.__name__}")


def validate_csv_file(file_path: str) -> bool:
    """CSVファイルのバリデーション"""
    try:
        import pandas as pd
        from pathlib import Path
        
        # ファイルの存在確認
        if not Path(file_path).exists():
            raise FileNotFoundError(f"ファイルが見つかりません: {file_path}")
        
        # ファイルサイズの確認
        file_size = Path(file_path).stat().st_size
        if file_size == 0:
            raise ValidationError("ファイルが空です")
        
        if file_size > 100 * 1024 * 1024:  # 100MB
            raise ValidationError("ファイルサイズが大きすぎます（100MB以下にしてください）")
        
        # CSVファイルの読み込みテスト（CSVIOクラスを使用）
        try:
            from utils.csv_io import csv_io
            df = csv_io.read_csv(file_path)
            if df is None:
                raise ValidationError("CSVファイルの読み込みに失敗しました。ファイル形式を確認してください。")
        except Exception as e:
            raise ValidationError(f"CSVファイルの読み込みに失敗しました: {str(e)}")
        
        # 必要な列の確認
        required_columns = ['SKU', 'ASIN', 'title']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValidationError(f"必要な列が見つかりません: {', '.join(missing_columns)}")
        
        return True
        
    except Exception as e:
        if isinstance(e, (ValidationError, FileNotFoundError)):
            raise
        else:
            raise ValidationError(f"ファイルの検証中にエラーが発生しました: {str(e)}")


def validate_api_connection(api_client) -> bool:
    """API接続のバリデーション"""
    try:
        return api_client.test_connection()
    except Exception as e:
        raise APIError(f"API接続の確認中にエラーが発生しました: {str(e)}")


# グローバルエラーハンドラー
global_error_handler = ErrorHandler()
