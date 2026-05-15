# -*- coding: utf-8 -*-
"""
証憑管理（レシート）から仕入DBの金額系カラムを更新するかどうかのポリシー。

現状、見込み利益・損益分岐点の再計算は Amazon 手数料・送料を十分に反映しにくい。
SP-API 等で正しい手数料・送料が取れるようになったら True にし、
receipt_widget 内の配賦・保存ロジックとあわせて見直すこと。
"""
from __future__ import annotations

from typing import Any, Optional

# True にしたときのみ、レシート保存・一括マッチング等で「仕入れ価格」および
# それに連動する見込み利益・損益分岐点・想定利益率・想定ROI・ProductDB.purchase_price を更新する。
RECEIPT_MUTATES_PURCHASE_DB_PRICE: bool = False

# レシート合計と紐付けSKU合計の差額がこの金額以内なら「OK」（仕入DBの金額は変更しない）
RECEIPT_PRICE_DIFFERENCE_TOLERANCE: int = 30


def is_acceptable_price_difference(difference: Any) -> bool:
    """差額が許容範囲内か（絶対値が RECEIPT_PRICE_DIFFERENCE_TOLERANCE 以下）"""
    if difference is None:
        return False
    try:
        return abs(int(round(float(difference)))) <= RECEIPT_PRICE_DIFFERENCE_TOLERANCE
    except (ValueError, TypeError):
        return False
