# -*- coding: utf-8 -*-
"""
証憑管理（レシート）から仕入DBの金額系カラムを更新するかどうかのポリシー。

現状、見込み利益・損益分岐点の再計算は Amazon 手数料・送料を十分に反映しにくい。
SP-API 等で正しい手数料・送料が取れるようになったら True にし、
receipt_widget 内の配賦・保存ロジックとあわせて見直すこと。
"""

# True にしたときのみ、レシート保存・一括マッチング等で「仕入れ価格」および
# それに連動する見込み利益・損益分岐点・想定利益率・想定ROI・ProductDB.purchase_price を更新する。
RECEIPT_MUTATES_PURCHASE_DB_PRICE: bool = False
