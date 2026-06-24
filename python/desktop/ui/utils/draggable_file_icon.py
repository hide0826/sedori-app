#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保存済みファイルをドラッグ＆ドロップで外部アプリへ送るアイコンウィジェット。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QMimeData, QUrl, QFileInfo
from PySide6.QtGui import QCursor, QDrag
from PySide6.QtWidgets import QApplication, QFileIconProvider, QLabel

try:
    from utils.win_browser_helper import (
        bring_browser_to_front,
        lower_qt_widget_to_back,
        raise_qt_widget,
        set_browser_topmost,
    )
except ImportError:
    from desktop.utils.win_browser_helper import (  # type: ignore
        bring_browser_to_front,
        lower_qt_widget_to_back,
        raise_qt_widget,
        set_browser_topmost,
    )


class DraggableFileIconWidget(QLabel):
    """ファイルアイコンを表示し、OS標準のドラッグでパスを渡す。"""

    def __init__(self, file_path: str = "", parent: Optional[QLabel] = None):
        super().__init__(parent)
        self._file_path = ""
        self._drag_start_pos = None
        self._tooltip_prefix = ""
        self._browser_title_keywords: List[str] = ["pricetar", "プライスター"]
        # 最小化するとドラッグ元が失われドロップできなくなるため既定はオフ
        self._minimize_host_on_drag = False
        self._host_lowered_for_drag = False
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
        if not self._file_path:
            self.setToolTip(self._tooltip_prefix or "")

    def set_browser_title_keywords(self, keywords: List[str]) -> None:
        """ドラッグ時に前面へ出すブラウザのタイトルキーワード。"""
        self._browser_title_keywords = [str(k).strip() for k in keywords if str(k).strip()]

    def set_minimize_host_on_drag(self, enabled: bool) -> None:
        """ドラッグ中に親ウィンドウを最小化する（Windows 向け）。"""
        self._minimize_host_on_drag = bool(enabled)

    def _prepare_browser_for_drag(self) -> None:
        if sys.platform != "win32" or not self._browser_title_keywords:
            return
        bring_browser_to_front(self._browser_title_keywords)
        set_browser_topmost(self._browser_title_keywords, True)

    def _lower_host_for_drag(self, host) -> None:
        if sys.platform != "win32" or host is None:
            return
        if self._minimize_host_on_drag:
            if not host.isMinimized():
                host.showMinimized()
            return
        self._host_lowered_for_drag = lower_qt_widget_to_back(host)

    def _restore_host_after_drag(self, host, host_was_minimized: bool, host_was_maximized: bool) -> None:
        if sys.platform != "win32" or host is None:
            return
        if self._minimize_host_on_drag and not host_was_minimized:
            if host_was_maximized:
                host.showMaximized()
            else:
                host.showNormal()
            host.raise_()
            return
        if self._host_lowered_for_drag:
            raise_qt_widget(host)
            self._host_lowered_for_drag = False

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
        drag_note = ""
        if sys.platform == "win32" and self._browser_title_keywords:
            if self._minimize_host_on_drag:
                drag_note = "\n（ドラッグ中はアプリが一時的に最小化されます）"
            else:
                drag_note = "\n（ドラッグ中はブラウザが最前面に出ます）"
        self.setToolTip(
            f"{prefix}"
            "このアイコンをドラッグしてドロップ先へ送れます"
            f"{drag_note}\n\n"
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
            if self._file_path and sys.platform == "win32" and self._browser_title_keywords:
                self._prepare_browser_for_drag()
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

        host = self.window()
        host_was_minimized = host.isMinimized() if host is not None else False
        host_was_maximized = host.isMaximized() if host is not None else False

        if sys.platform == "win32" and self._browser_title_keywords:
            self._prepare_browser_for_drag()
            self._lower_host_for_drag(host)

        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            if sys.platform == "win32" and self._browser_title_keywords:
                set_browser_topmost(self._browser_title_keywords, False)
                bring_browser_to_front(self._browser_title_keywords)
            self._restore_host_after_drag(host, host_was_minimized, host_was_maximized)

        self._drag_start_pos = None
