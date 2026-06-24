"""仕入DBテーブル段階読み込み設定のテスト。"""
from __future__ import annotations

from services.purchase_table_incremental import (
    DEFAULT_AUGMENT_BATCH_SIZE,
    DEFAULT_ENABLED,
    DEFAULT_PAGE_SIZE,
    get_augment_batch_size,
    get_page_size,
    is_incremental_render_enabled,
    purchase_record_purchase_timestamp,
    sort_purchase_records_for_display,
)


class _FakeSettings:
    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})

    def value(self, key, default=None, type=None):
        if key not in self._data:
            if type is bool:
                return bool(default)
            return default
        raw = self._data[key]
        if type is bool:
            return bool(raw)
        return raw


def test_defaults_when_no_settings():
    assert is_incremental_render_enabled(None) is DEFAULT_ENABLED
    assert get_page_size(None) == DEFAULT_PAGE_SIZE
    assert get_augment_batch_size(None) == DEFAULT_AUGMENT_BATCH_SIZE


def test_settings_roundtrip():
    s = _FakeSettings(
        {
            "performance/purchase_incremental_render": False,
            "performance/purchase_page_size": 150,
            "performance/purchase_augment_batch_size": 80,
        }
    )
    assert is_incremental_render_enabled(s) is False
    assert get_page_size(s) == 150
    assert get_augment_batch_size(s) == 80


def test_page_size_clamped():
    s = _FakeSettings({"performance/purchase_page_size": 5})
    assert get_page_size(s) == 20
    s2 = _FakeSettings({"performance/purchase_page_size": 9999})
    assert get_page_size(s2) == 500


def test_sort_purchase_records_newest_first():
    records = [
        {"SKU": "old", "仕入れ日": "2025/5/22 10:00"},
        {"SKU": "new", "仕入れ日": "2025/6/17 9:00"},
        {"SKU": "mid", "仕入れ日": "2025/5/23 8:00"},
    ]
    ordered = sort_purchase_records_for_display(records)
    assert [r["SKU"] for r in ordered] == ["new", "mid", "old"]
    assert purchase_record_purchase_timestamp(ordered[0]) >= purchase_record_purchase_timestamp(
        ordered[1]
    )
