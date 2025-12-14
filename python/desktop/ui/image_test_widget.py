#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像テストウィジェット

画像の白抜き（背景透明化）処理をテストするためのタブ
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QComboBox,
    QGroupBox,
)
from PySide6.QtGui import QPixmap, QImage

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# デスクトップ側servicesを優先して読み込む
try:
    from services.image_background_removal_service import ImageBackgroundRemovalService
except Exception:
    from desktop.services.image_background_removal_service import ImageBackgroundRemovalService


class BackgroundRemovalThread(QThread):
    """背景削除処理をバックグラウンドで実行するスレッド"""
    finished = Signal(str)  # 出力ファイルパス
    error = Signal(str)  # エラーメッセージ

    def __init__(self, input_path: str, output_path: Optional[str] = None, model_name: str = "u2net"):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.model_name = model_name

    def run(self):
        try:
            service = ImageBackgroundRemovalService()
            output_path = service.remove_background(self.input_path, self.output_path, self.model_name)
            if output_path:
                self.finished.emit(output_path)
            else:
                self.error.emit("背景削除処理が失敗しました（出力パスがNone）")
        except Exception as e:
            self.error.emit(str(e))


class ImageTestWidget(QWidget):
    """画像テストウィジェット（白抜き処理）"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.input_image_path: Optional[str] = None
        self.output_image_path: Optional[str] = None
        self.removal_thread: Optional[BackgroundRemovalThread] = None
        self.progress_dialog: Optional[QProgressDialog] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 上部: モデル選択と操作ボタン
        top_layout = QHBoxLayout()

        # モデル選択グループ
        model_group = QGroupBox("モデル選択")
        model_layout = QHBoxLayout(model_group)
        
        model_layout.addWidget(QLabel("モデル:"))
        self.model_combo = QComboBox()
        # rembgで利用可能なモデル一覧
        self.model_combo.addItems([
            "u2net",              # 汎用（デフォルト、高精度）
            "u2netp",             # 軽量版（高速）
            "u2net_human_seg",    # 人物専用
            "u2net_cloth_seg",    # 衣類専用
            "silueta",            # シルエット抽出
            "isnet-general-use",  # ISNet汎用
            "isnet-anime",        # アニメ風
            "sam",                # SAM（Segment Anything Model）
        ])
        self.model_combo.setCurrentText("u2net")  # デフォルト
        self.model_combo.setToolTip(
            "u2net: 汎用・高精度（推奨）\n"
            "u2netp: 軽量版・高速\n"
            "u2net_human_seg: 人物専用\n"
            "u2net_cloth_seg: 衣類専用\n"
            "silueta: シルエット抽出\n"
            "isnet-general-use: ISNet汎用\n"
            "isnet-anime: アニメ風\n"
            "sam: SAM（Segment Anything Model）"
        )
        model_layout.addWidget(self.model_combo)
        model_layout.addStretch()
        
        top_layout.addWidget(model_group)

        # 操作ボタン
        button_layout = QHBoxLayout()

        self.select_image_btn = QPushButton("画像を選択")
        self.select_image_btn.clicked.connect(self.on_select_image)
        button_layout.addWidget(self.select_image_btn)

        self.process_btn = QPushButton("白抜き処理を実行")
        self.process_btn.clicked.connect(self.on_process_clicked)
        self.process_btn.setEnabled(False)
        button_layout.addWidget(self.process_btn)

        self.save_result_btn = QPushButton("結果を保存")
        self.save_result_btn.clicked.connect(self.on_save_result)
        self.save_result_btn.setEnabled(False)
        button_layout.addWidget(self.save_result_btn)

        top_layout.addLayout(button_layout)
        layout.addLayout(top_layout)

        # 中央: 画像表示エリア（左右分割）
        splitter = QSplitter(Qt.Horizontal)

        # 左側: 元画像
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 5, 5, 5)

        left_label = QLabel("元画像")
        left_label.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(left_label)

        self.original_image_label = QLabel()
        self.original_image_label.setAlignment(Qt.AlignCenter)
        self.original_image_label.setMinimumSize(400, 400)
        self.original_image_label.setStyleSheet("border: 1px solid gray; background-color: #f0f0f0;")
        self.original_image_label.setText("画像を選択してください")
        left_layout.addWidget(self.original_image_label)

        splitter.addWidget(left_widget)

        # 右側: 白抜き後画像
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 5, 5, 5)

        right_label = QLabel("白抜き後")
        right_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(right_label)

        self.result_image_label = QLabel()
        self.result_image_label.setAlignment(Qt.AlignCenter)
        self.result_image_label.setMinimumSize(400, 400)
        self.result_image_label.setStyleSheet("border: 1px solid gray; background-color: #f0f0f0;")
        self.result_image_label.setText("処理結果がここに表示されます")
        right_layout.addWidget(self.result_image_label)

        splitter.addWidget(right_widget)

        splitter.setSizes([400, 400])
        layout.addWidget(splitter)

        # 下部: ステータス表示
        self.status_label = QLabel("準備完了")
        layout.addWidget(self.status_label)

    def on_select_image(self) -> None:
        """画像選択ダイアログを表示"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "画像を選択",
            "",
            "画像ファイル (*.jpg *.jpeg *.png *.bmp *.gif);;すべてのファイル (*)"
        )

        if not file_path:
            return

        self.input_image_path = file_path
        self._load_original_image(file_path)
        self.process_btn.setEnabled(True)
        self.status_label.setText(f"画像を選択しました: {Path(file_path).name}")

    def _load_original_image(self, file_path: str) -> None:
        """元画像を読み込んで表示"""
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "エラー", "画像の読み込みに失敗しました。")
            return

        # ラベルサイズに合わせてスケール
        scaled_pixmap = pixmap.scaled(
            self.original_image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.original_image_label.setPixmap(scaled_pixmap)

    def on_process_clicked(self) -> None:
        """白抜き処理を実行"""
        if not self.input_image_path:
            QMessageBox.warning(self, "エラー", "画像を選択してください。")
            return

        # rembgが利用可能かチェック
        available, info = ImageBackgroundRemovalService.is_available()
        if not available:
            import sys
            python_path = sys.executable
            
            # エラーメッセージから必要なコマンドを抽出
            install_cmd = f"{python_path} -m pip install rembg"
            if "onnxruntime" in info.lower():
                install_cmd = f"{python_path} -m pip install onnxruntime"
            
            reply = QMessageBox.question(
                self,
                "ライブラリ未インストール",
                f"{info}\n\n"
                f"解決方法:\n"
                f"1. 以下のコマンドをターミナルで実行してください:\n"
                f"   {install_cmd}\n"
                f"2. アプリを再起動してください\n\n"
                f"インストールコマンドをコピーしますか？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # クリップボードにコピー
                from PySide6.QtWidgets import QApplication
                clipboard = QApplication.clipboard()
                clipboard.setText(install_cmd)
                QMessageBox.information(
                    self,
                    "コピー完了",
                    "インストールコマンドをクリップボードにコピーしました。\n"
                    "ターミナルに貼り付けて実行してください。"
                )
            return

        # 選択されたモデルを取得
        selected_model = self.model_combo.currentText()

        # 進捗ダイアログを表示
        self.progress_dialog = QProgressDialog("白抜き処理中...", "キャンセル", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setCancelButton(None)  # キャンセル不可（処理中は待つ）
        self.progress_dialog.show()

        # バックグラウンドスレッドで処理
        self.removal_thread = BackgroundRemovalThread(
            self.input_image_path,
            model_name=selected_model
        )
        self.removal_thread.finished.connect(self.on_process_finished)
        self.removal_thread.error.connect(self.on_process_error)
        self.removal_thread.start()

        self.process_btn.setEnabled(False)
        self.status_label.setText(f"白抜き処理中... (モデル: {selected_model})")

    def on_process_finished(self, output_path: str) -> None:
        """白抜き処理完了"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.output_image_path = output_path
        self._load_result_image(output_path)
        self.save_result_btn.setEnabled(True)
        self.process_btn.setEnabled(True)
        self.status_label.setText(f"処理完了: {Path(output_path).name}")

    def on_process_error(self, error_message: str) -> None:
        """白抜き処理エラー"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        QMessageBox.critical(self, "処理エラー", f"白抜き処理に失敗しました:\n{error_message}")
        self.process_btn.setEnabled(True)
        self.status_label.setText("処理エラー")

    def _load_result_image(self, file_path: str) -> None:
        """白抜き後の画像を読み込んで表示"""
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "エラー", "結果画像の読み込みに失敗しました。")
            return

        # ラベルサイズに合わせてスケール
        scaled_pixmap = pixmap.scaled(
            self.result_image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.result_image_label.setPixmap(scaled_pixmap)

    def on_save_result(self) -> None:
        """結果画像を別名で保存"""
        if not self.output_image_path:
            QMessageBox.warning(self, "エラー", "保存する画像がありません。")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "結果画像を保存",
            str(Path(self.output_image_path).parent / "白抜き結果.png"),
            "PNG画像 (*.png);;すべてのファイル (*)"
        )

        if not file_path:
            return

        try:
            from shutil import copyfile
            copyfile(self.output_image_path, file_path)
            QMessageBox.information(self, "保存完了", f"画像を保存しました:\n{file_path}")
            self.status_label.setText(f"保存完了: {Path(file_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", f"画像の保存に失敗しました:\n{e}")




