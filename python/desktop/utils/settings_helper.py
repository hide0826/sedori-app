# -*- coding: utf-8 -*-
"""
設定ヘルパー

アプリ全体で参照する設定（PRO版フラグなど）を一元管理します。
"""

from PySide6.QtCore import QSettings


def _settings():
    """QSettings の共通インスタンスを返す（HIRIO DesktopApp）"""
    return QSettings("HIRIO", "DesktopApp")


def is_pro_enabled() -> bool:
    """
    PRO版が有効かどうかを返します。
    設定タブの「PRO版を有効にする」スイッチで変更されます。
    今後のPRO機能はこのフラグを前提に実装してください。
    開発段階ではデフォルトでTrue（ON）です。
    """
    return _settings().value("pro/enabled", True, type=bool)
