"""
仕入DBテーブルの段階読み込み（インクリメンタル描画）設定。

QSettings で ON/OFF でき、OFF にすると従来の全件一括描画に戻せる。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

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


def purchase_record_purchase_timestamp(record: Dict[str, Any]) -> float:
    """仕入れ日のソート用タイムスタンプ（新しいほど大きい）。"""
    date_str = str(
        record.get("仕入れ日") or record.get("purchase_date") or ""
    ).strip()
    if not date_str:
        return 0.0
    try:
        date_str_clean = date_str.strip()
        if " " in date_str_clean:
            date_part, time_part = date_str_clean.split(" ", 1)
            date_part = date_part.replace("/", "-")
            dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M")
            return dt.timestamp()
        date_part = date_str_clean.replace("/", "-").split(" ")[0]
        dt = datetime.strptime(date_part, "%Y-%m-%d")
        return dt.timestamp()
    except Exception:
        try:
            date_part = date_str.replace("/", "-").split(" ")[0]
            dt = datetime.strptime(date_part, "%Y-%m-%d")
            return dt.timestamp()
        except Exception:
            return 0.0


def sort_purchase_records_for_display(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """段階描画前に仕入れ日降順へ並べ替え（最新が先頭ページに来る）。"""

    def _sort_key(rec: Dict[str, Any]) -> tuple:
        sku = str(rec.get("SKU") or rec.get("sku") or "").strip()
        return (purchase_record_purchase_timestamp(rec), sku)

    return sorted(records or [], key=_sort_key, reverse=True)


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
