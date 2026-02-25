#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
起動中プログレスダイアログ

「起動しています ○○%」とスピナー（くるくる）を表示するモーダルダイアログ。
メインウィンドウのタブ構築フェーズに合わせてパーセントを更新する。
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QWidget,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont


# スピナー用の文字（順に切り替えて「くるくる」表現）
SPINNER_CHARS = ("／", "－", "＼", "｜")


class StartupProgressDialog(QDialog):
    """起動中に表示するプログレスダイアログ（％表示＋スピナー）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HIRIO")
        self.setWindowFlags(
            Qt.Dialog
            | Qt.CustomizeWindowHint
            | Qt.WindowTitleHint
            | Qt.WindowStaysOnTopHint
        )
        self.setModal(False)  # ブロックせずタブ構築を進める
        self.setFixedSize(320, 160)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # スピナー（文字が順に変わる）
        self._spinner_index = 0
        self._spinner_label = QLabel(SPINNER_CHARS[0])
        font = QFont()
        font.setPointSize(24)
        font.setBold(True)
        self._spinner_label.setFont(font)
        self._spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._spinner_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 「起動しています XX%」
        self._percent_label = QLabel("起動しています 0%")
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._percent_label)

        # プログレスバー（見た目用）
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("%p%")
        layout.addWidget(self._progress_bar)

        # スピナー用タイマー（約150msごとに文字を切り替え）
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._update_spinner)
        self._spinner_timer.start(150)

    def _update_spinner(self):
        self._spinner_index = (self._spinner_index + 1) % len(SPINNER_CHARS)
        self._spinner_label.setText(SPINNER_CHARS[self._spinner_index])

    def set_progress(self, percent: int):
        """0〜100のパーセントで表示を更新"""
        percent = max(0, min(100, percent))
        self._percent_label.setText(f"起動しています {percent}%")
        self._progress_bar.setValue(percent)

    def closeEvent(self, event):
        self._spinner_timer.stop()
        super().closeEvent(event)
