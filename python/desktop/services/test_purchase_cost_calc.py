#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""purchase_cost_calc の単体テスト（pytest 不要・直接実行可）"""

from purchase_cost_calc import (
    COL_PLATFORM_FEE,
    COL_SHIPPING,
    COL_TOTAL_COST,
    augment_purchase_cost_record,
    blank_zero_fee_columns_in_record,
    effective_sale_deduction,
    fee_storage_value,
    format_money_display,
    infer_total_cost,
    migrate_record_keys,
    recalculate_profit_fields,
    sync_total_cost_field,
)


def test_infer_ignores_break_even():
    """改定後の akaji(損益分岐点) からは費用合計を出さない"""
    total = infer_total_cost(2200, 7800, 3000, 0, 0)
    assert total == 2600  # 7800-2200-3000


def test_infer_from_profit():
    total = infer_total_cost(550, 2500, 800, 0, 0)
    assert total == 1150


def test_effective_uses_total_when_no_components():
    assert effective_sale_deduction(0, 0, 1046) == 1046


def test_recalculate_with_total_cost_edit():
    fields = recalculate_profit_fields(2200, 7800, 0, 0, 1046)
    assert fields["損益分岐点"] == 3246
    assert fields["見込み利益"] == 4554
    assert fields[COL_TOTAL_COST] == 1046


def test_migrate_legacy_key():
    rec = {"Amazon手数料": 500, "仕入れ価格": 1000, "販売予定価格": 2000}
    migrate_record_keys(rec)
    assert rec[COL_PLATFORM_FEE] == 500


def test_augment_overwrites_akaji_derived_total():
    """損益分岐点は akaji のまま、費用合計は見込み利益から再計算"""
    rec = {
        "仕入れ価格": 550,
        "販売予定価格": 2500,
        "見込み利益": 800,
        "損益分岐点": 1154,
        COL_TOTAL_COST: 604,
    }
    augment_purchase_cost_record(rec)
    assert rec[COL_TOTAL_COST] == 1150
    assert rec["損益分岐点"] == 1154


def test_augment_amasearch_without_akaji():
    rec = {
        "仕入れ価格": 550,
        "販売予定価格": 2500,
        "見込み利益": 800,
    }
    augment_purchase_cost_record(rec)
    assert rec[COL_TOTAL_COST] == 1150


def test_infer_zero_total_from_profit():
    """見込み利益が粗利と同額なら費用合計は 0 → 保存は空欄"""
    total = infer_total_cost(1078, 3980, 2902, 0, 0)
    assert total == 0
    assert fee_storage_value(total) == ""


def test_format_zero_as_empty():
    assert format_money_display(0, zero_as_empty=True) == ""
    assert format_money_display(1224, zero_as_empty=True) == "1,224"


def test_recalculate_infers_total_when_fees_zero():
    fields = recalculate_profit_fields(
        1078, 3980, 0, 0, 0,
        stored_profit=2902,
        prefer_stored_profit=True,
    )
    assert fields[COL_TOTAL_COST] == 0
    rec = {COL_PLATFORM_FEE: 0, COL_SHIPPING: 0, COL_TOTAL_COST: 0}
    blank_zero_fee_columns_in_record(rec)
    assert rec[COL_PLATFORM_FEE] == ""
    assert rec[COL_SHIPPING] == ""
    assert rec[COL_TOTAL_COST] == ""


def test_sync_clears_wrong_total_without_profit():
    rec = {
        "仕入れ価格": 1000,
        "販売予定価格": 2000,
        "損益分岐点": 1500,
        COL_TOTAL_COST: 500,
    }
    sync_total_cost_field(rec)
    assert rec[COL_TOTAL_COST] == ""


if __name__ == "__main__":
    test_infer_ignores_break_even()
    test_infer_from_profit()
    test_effective_uses_total_when_no_components()
    test_recalculate_with_total_cost_edit()
    test_migrate_legacy_key()
    test_augment_overwrites_akaji_derived_total()
    test_augment_amasearch_without_akaji()
    test_infer_zero_total_from_profit()
    test_format_zero_as_empty()
    test_recalculate_infers_total_when_fees_zero()
    test_sync_clears_wrong_total_without_profit()
    print("ok")
