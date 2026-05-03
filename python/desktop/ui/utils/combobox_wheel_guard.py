#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アプリ全体で QComboBox のマウスホイール誤操作を防止するユーティリティ。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QComboBox


class ComboBoxWheelGuardFilter(QObject):
    """コンボ・スピン系のホイール誤操作を防ぐイベントフィルタ。"""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        try:
            if event.type() == QEvent.Wheel:
                if isinstance(obj, QComboBox):
                    # 誤スクロールで選択値が変わらないよう、ホイールイベントを握りつぶす
                    event.ignore()
                    return True
                if isinstance(obj, QAbstractSpinBox):
                    # 数値入力（QSpinBox/QDoubleSpinBox 等）の誤変更を防ぐ
                    event.ignore()
                    return True
            return super().eventFilter(obj, event)
        except Exception:
            return super().eventFilter(obj, event)


_FILTER_INSTANCE: Optional[ComboBoxWheelGuardFilter] = None


def install_combobox_wheel_guard(app: QApplication) -> None:
    """アプリ全体にコンボボックスのホイール無効化フィルタを取り付ける。"""
    global _FILTER_INSTANCE
    if _FILTER_INSTANCE is None:
        _FILTER_INSTANCE = ComboBoxWheelGuardFilter(app)
        app.installEventFilter(_FILTER_INSTANCE)
