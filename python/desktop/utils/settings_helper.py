# -*- coding: utf-8 -*-
"""
設定ヘルパー

アプリ全体で参照する設定（PRO版フラグなど）を一元管理します。
"""

from PySide6.QtCore import QSettings


def _settings():
    """QSettings の共通インスタンスを返す（HIRIO DesktopApp）"""
    return QSettings("HIRIO", "DesktopApp")


def get_amazon_seller_id() -> str:
    """
    設定タブ（詳細設定）で保存した自店の Amazon セラーID（マーチャントID）を返します。
    未設定時は空文字です。Keepa の offer sellerId などと照合する用途向け。
    """
    v = _settings().value("amazon/seller_id", "") or ""
    return str(v).strip()


def is_pro_enabled() -> bool:
    """
    PRO版が有効かどうかを返します。
    設定タブの「PRO版を有効にする」スイッチで変更されます。
    今後のPRO機能はこのフラグを前提に実装してください。
    開発段階ではデフォルトでTrue（ON）です。
    """
    return _settings().value("pro/enabled", True, type=bool)
