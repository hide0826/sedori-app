# -*- coding: utf-8 -*-
"""折りたたみ可能なセクション（ルート地図左パネル用・ダーク）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QToolButton,
    QSizePolicy,
    QFrame,
)


class CollapsibleSection(QWidget):
    """ヘッダークリックで中身を畳む／開くパネル。

    畳んだときはヘッダー高さだけになり、親スプリッタが他パネルへ余白を渡せる。
    """

    toggled = Signal(bool)

    def __init__(self, title: str, *, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._title = title
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QToolButton()
        self.header.setObjectName("collapsibleHeader")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(bool(expanded))
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setStyleSheet(
            """
            QToolButton#collapsibleHeader {
                background: #2a2a2a;
                color: #f0f0f0;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 6px 8px;
                font-weight: bold;
                text-align: left;
            }
            QToolButton#collapsibleHeader:hover {
                background: #333333;
            }
            QToolButton#collapsibleHeader:checked {
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                background: #323232;
            }
            """
        )
        self.header.toggled.connect(self._on_toggled)
        root.addWidget(self.header)

        self.body = QFrame()
        self.body.setObjectName("collapsibleBody")
        self.body.setStyleSheet(
            """
            QFrame#collapsibleBody {
                background: #1e1e1e;
                border: 1px solid #444444;
                border-top: none;
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
                color: #f0f0f0;
            }
            """
        )
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 6, 6, 6)
        self.body_layout.setSpacing(4)
        self.body.setVisible(bool(expanded))
        root.addWidget(self.body, 1)

        self._apply_expanded(bool(expanded))

    def set_title(self, title: str) -> None:
        self._title = title
        self.header.setText(title)

    def title(self) -> str:
        return self._title

    def is_expanded(self) -> bool:
        return bool(self.header.isChecked())

    def header_height(self) -> int:
        hint = self.header.sizeHint().height()
        return max(30, int(hint) + 4)

    def set_expanded(self, expanded: bool) -> None:
        if self.header.isChecked() != bool(expanded):
            self.header.setChecked(bool(expanded))
        else:
            self._apply_expanded(bool(expanded))

    def _on_toggled(self, checked: bool) -> None:
        self._apply_expanded(bool(checked))
        self.toggled.emit(bool(checked))

    def _apply_expanded(self, expanded: bool) -> None:
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)
        if expanded:
            self.setMinimumHeight(self.header_height() + 40)
            self.setMaximumHeight(16777215)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            h = self.header_height()
            self.setMinimumHeight(h)
            self.setMaximumHeight(h)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.updateGeometry()
