"""
仕入DBテーブルの段階読み込み（インクリメンタル描画）設定。

QSettings で ON/OFF でき、OFF にすると従来の全件一括描画に戻せる。
"""
from __future__ import annotations

from typing import Any

# QSettings キー（HIRIO / DesktopApp）
SETTINGS_KEY_ENABLED = "performance/purchase_incremental_render"
SETTINGS_KEY_PAGE_SIZE = "performance/purchase_page_size"
SETTINGS_KEY_AUGMENT_BATCH = "performance/purchase_augment_batch_size"

DEFAULT_ENABLED = True
DEFAULT_PAGE_SIZE = 100
DEFAULT_AUGMENT_BATCH_SIZE = 100
MIN_PAGE_SIZE = 20
MAX_PAGE_SIZE = 500
MIN_AUGMENT_BATCH = 20
MAX_AUGMENT_BATCH = 500

# スクロール末尾判定: 残りピクセルがこの値以下なら次ページを読み込む
SCROLL_LOAD_THRESHOLD_PX = 80


def is_incremental_render_enabled(settings: Any) -> bool:
    """段階読み込みが有効か（未設定時は既定 ON）。"""
    if settings is None:
        return DEFAULT_ENABLED
    return bool(settings.value(SETTINGS_KEY_ENABLED, DEFAULT_ENABLED, type=bool))


def get_page_size(settings: Any) -> int:
    """テーブルに一度に描画する行数。"""
    if settings is None:
        return DEFAULT_PAGE_SIZE
    try:
        value = int(settings.value(SETTINGS_KEY_PAGE_SIZE, DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        value = DEFAULT_PAGE_SIZE
    return max(MIN_PAGE_SIZE, min(MAX_PAGE_SIZE, value))


def get_augment_batch_size(settings: Any) -> int:
    """バックグラウンドで augment する行数（DB照会のバッチ）。"""
    if settings is None:
        return DEFAULT_AUGMENT_BATCH_SIZE
    try:
        value = int(settings.value(SETTINGS_KEY_AUGMENT_BATCH, DEFAULT_AUGMENT_BATCH_SIZE))
    except (TypeError, ValueError):
        value = DEFAULT_AUGMENT_BATCH_SIZE
    return max(MIN_AUGMENT_BATCH, min(MAX_AUGMENT_BATCH, value))
