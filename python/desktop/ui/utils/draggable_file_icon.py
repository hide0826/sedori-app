#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保存済みファイルをドラッグ＆ドロップで外部アプリへ送るアイコンウィジェット。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QMimeData, QUrl, QFileInfo
from PySide6.QtGui import QCursor, QDrag
from PySide6.QtWidgets import QApplication, QFileIconProvider, QLabel


class DraggableFileIconWidget(QLabel):
    """ファイルアイコンを表示し、OS標準のドラッグでパスを渡す。"""

    def __init__(self, file_path: str = "", parent: Optional[QLabel] = None):
        super().__init__(parent)
        self._file_path = ""
        self._drag_start_pos = None
        self._tooltip_prefix = ""
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(80, 80)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.setStyleSheet(
            "border: 2px dashed #5aa2ff; border-radius: 8px; background-color: #1e2a36;"
        )
        if file_path:
            self.set_file_path(file_path)
        else:
            self.clear_file()

    def set_tooltip_prefix(self, text: str) -> None:
        self._tooltip_prefix = str(text or "").strip()

    def set_file_path(self, file_path: str) -> None:
        self._file_path = str(file_path or "").strip()
        if not self._file_path or not os.path.isfile(self._file_path):
            self.clear_file()
            return
        provider = QFileIconProvider()
        icon = provider.icon(QFileInfo(self._file_path))
        pixmap = icon.pixmap(56, 56)
        self.setPixmap(pixmap)
        file_name = Path(self._file_path).name
        prefix = f"{self._tooltip_prefix}\n\n" if self._tooltip_prefix else ""
        self.setToolTip(
            f"{prefix}"
            "このアイコンをドラッグしてドロップ先へ送れます\n\n"
            f"{file_name}\n{self._file_path}"
        )
        self.setEnabled(True)

    def clear_file(self) -> None:
        self._file_path = ""
        self.clear()
        self.setToolTip(self._tooltip_prefix or "")
        self.setEnabled(False)

    def file_path(self) -> str:
        return self._file_path

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._drag_start_pos is None:
            return
        if (
            event.position().toPoint() - self._drag_start_pos
        ).manhattanLength() < QApplication.startDragDistance():
            return
        if not self._file_path or not os.path.isfile(self._file_path):
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(self._file_path)])
        mime_data.setText(self._file_path)
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        pixmap = self.pixmap()
        if pixmap and not pixmap.isNull():
            drag.setPixmap(
                pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        drag.exec(Qt.DropAction.CopyAction)
        self._drag_start_pos = None
