#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アプリ全体に右クリックコピー機能を付与するユーティリティ
"""
from __future__ import annotations

from typing import Optional, Dict

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QLabel,
    QPushButton,
    QAbstractItemView,
    QWidget,
)


class CopyContextMenuFilter(QObject):
    """任意のウィジェットにコピー項目を追加するイベントフィルタ"""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        try:
            if (
                event.type() == QEvent.ContextMenu
                and isinstance(obj, QWidget)
                and obj.contextMenuPolicy() == Qt.DefaultContextMenu
            ):
                if isinstance(obj, (QLineEdit, QTextEdit, QPlainTextEdit)):
                    self._show_text_widget_menu(obj, event)
                    return True
                if isinstance(obj, QAbstractItemView):
                    self._show_item_view_menu(obj, event)
                    return True
                if isinstance(obj, (QLabel, QPushButton)):
                    if obj.text().strip():
                        self._show_simple_copy_menu(obj, event)
                        return True
            return super().eventFilter(obj, event)
        except KeyboardInterrupt:
            # KeyboardInterruptは再発生させる（アプリケーション終了のため）
            raise
        except Exception as e:
            # その他の例外はログに記録して処理を継続
            import traceback
            print(f"[ERROR] copy_context_menu eventFilter エラー: {e}")
            print(f"[ERROR] トレースバック:\n{traceback.format_exc()}")
            # エラーが発生してもアプリケーションを継続させる
            return super().eventFilter(obj, event)

    def _show_text_widget_menu(self, widget, event: QEvent):
        try:
            menu = widget.createStandardContextMenu()
            if menu is None:
                return
            menu.addSeparator()
            copy_action = QAction("コピー", widget)
            copy_action.triggered.connect(widget.copy)
            menu.addAction(copy_action)
            menu.exec(event.globalPos())
        except Exception as e:
            import traceback
            print(f"[ERROR] _show_text_widget_menu エラー: {e}")
            print(f"[ERROR] トレースバック:\n{traceback.format_exc()}")

    def _show_item_view_menu(self, view: QAbstractItemView, event: QEvent):
        try:
            menu = QMenu(view)
            copy_action = menu.addAction("コピー")
            copy_action.triggered.connect(lambda: self._copy_from_item_view(view))
            menu.exec(event.globalPos())
        except Exception as e:
            import traceback
            print(f"[ERROR] _show_item_view_menu エラー: {e}")
            print(f"[ERROR] トレースバック:\n{traceback.format_exc()}")

    def _show_simple_copy_menu(self, widget: QWidget, event: QEvent):
        try:
            menu = QMenu(widget)
            copy_action = menu.addAction("コピー")
            copy_action.triggered.connect(
                lambda: QApplication.clipboard().setText(widget.text())
            )
            menu.exec(event.globalPos())
        except Exception as e:
            import traceback
            print(f"[ERROR] _show_simple_copy_menu エラー: {e}")
            print(f"[ERROR] トレースバック:\n{traceback.format_exc()}")

    def _copy_from_item_view(self, view: QAbstractItemView):
        selection_model = view.selectionModel()
        if selection_model is None:
            return
        indexes = selection_model.selectedIndexes()
        if not indexes:
            return

        rows: Dict[int, Dict[int, str]] = {}
        min_col = min(index.column() for index in indexes)
        max_col = max(index.column() for index in indexes)

        for index in indexes:
            rows.setdefault(index.row(), {})[index.column()] = index.data() or ""

        lines = []
        for row in sorted(rows.keys()):
            row_data = []
            for col in range(min_col, max_col + 1):
                row_data.append(rows[row].get(col, ""))
            lines.append("\t".join(row_data))

        QApplication.clipboard().setText("\n".join(lines))


_FILTER_INSTANCE: Optional[CopyContextMenuFilter] = None


def install_copy_context_menu(app: QApplication):
    """アプリケーション全体にコピー用イベントフィルタを取り付ける"""
    global _FILTER_INSTANCE
    if _FILTER_INSTANCE is None:
        _FILTER_INSTANCE = CopyContextMenuFilter(app)
        app.installEventFilter(_FILTER_INSTANCE)

