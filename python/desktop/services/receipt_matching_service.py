#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシートマッチングサービス

- 条件:
  - 日付=同日
  - 店舗=部分一致（店舗マスタ/学習辞書）
  - 金額一致= |(合計 - 値引) - (アイテム合計)| <= 許容誤差（既定±10円）

- 学習:
  - ユーザーが選択/修正した店舗コードを `receipt_match_learnings` に蓄積
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import unicodedata

from ..database.store_db import StoreDatabase
from ..database.receipt_db import ReceiptDatabase


@dataclass
class MatchCandidate:
    receipt_id: int
    purchase_date: Optional[str]
    store_code: Optional[str]
    store_name_raw: Optional[str]
    expected_total: Optional[int]
    diff: Optional[int]
    items_count: int


class ReceiptMatchingService:
    def __init__(self, amount_tolerance: int = 10):
        self.amount_tolerance = amount_tolerance
        self.store_db = StoreDatabase()
        self.receipt_db = ReceiptDatabase()

    @staticmethod
    def _normalize_text(s: str) -> str:
        if not s:
            return ""
        s = unicodedata.normalize('NFKC', s)
        return s.strip()

    def _guess_store_code(self, raw_name: Optional[str]) -> Optional[str]:
        if not raw_name:
            return None
        raw_name = self._normalize_text(raw_name)
        # 1) 学習辞書
        guessed = self.receipt_db.guess_store_code(raw_name)
        if guessed:
            return guessed[0]
        # 2) 店舗マスタ: 部分一致
        try:
            # list_storesメソッドを使用（検索語を指定）
            stores = self.store_db.list_stores(search_term=raw_name)
        except AttributeError:
            # list_storesが存在しない場合は、全店舗を取得して部分一致
            try:
                stores = self.store_db.list_stores()  # 引数なしで全店舗を取得
            except Exception:
                stores = []
        except Exception:
            stores = []
        
        # 検索結果が空の場合は、全店舗を取得して部分一致
        if not stores:
            try:
                stores = self.store_db.list_stores()  # 引数なしで全店舗を取得
            except Exception:
                stores = []
        
        raw_lower = raw_name.lower()
        for st in stores:
            name = (st.get('store_name') or '').lower()
            if name and raw_lower in name:
                # 店舗コード優先、なければ互換性のため仕入れ先コード
                return st.get('store_code') or st.get('supplier_code')
        return None

    @staticmethod
    def _calc_items_total(items: List[Dict[str, Any]]) -> int:
        total = 0
        for it in items:
            qty = it.get('quantity') or it.get('仕入れ個数') or 0
            price = it.get('purchase_price') or it.get('仕入れ価格') or 0
            try:
                qty = int(round(float(qty)))
                price = int(round(float(price)))
            except Exception:
                qty = 0
                price = 0
            total += qty * price
        return int(total)

    def find_match_candidates(
        self,
        receipt: Dict[str, Any],
        purchase_items: List[Dict[str, Any]],
        preferred_store_code: Optional[str] = None,
    ) -> List[MatchCandidate]:
        """
        レシートに対するマッチ候補を返す
        - 同日フィルタ
        - 店舗コードは learning/部分一致で推定（preferred_store_code 優先）
        - 金額比較: |(total - discount) - items_total| <= tolerance
        """
        purchase_date = receipt.get('purchase_date')
        raw_name = receipt.get('store_name_raw')
        total = receipt.get('total_amount')
        discount = receipt.get('discount_amount') or 0
        effective_total = None
        if isinstance(total, int):
            effective_total = total - (discount or 0)

        # 日付一致のアイテムに限定
        same_day_items = [it for it in purchase_items if (it.get('purchase_date') == purchase_date)]

        # 推定店舗コード
        store_code = preferred_store_code or receipt.get('store_code') or self._guess_store_code(raw_name)

        # 店舗コードでさらに絞り込み（あれば）
        if store_code:
            filtered_items = [it for it in same_day_items if (it.get('store_code') == store_code or it.get('仕入れ先') == store_code)]
        else:
            filtered_items = same_day_items

        items_total = self._calc_items_total(filtered_items)
        diff = None if effective_total is None else abs(effective_total - items_total)

        candidate = MatchCandidate(
            receipt_id=receipt.get('id'),
            purchase_date=purchase_date,
            store_code=store_code,
            store_name_raw=raw_name,
            expected_total=items_total,
            diff=diff,
            items_count=len(filtered_items),
        )

        # 許容誤差内なら候補として返す、誤差不明でも一応返す
        if diff is None or diff <= self.amount_tolerance:
            return [candidate]
        return [candidate]

    def learn_store_correction(self, receipt_id: int, correct_store_code: str) -> bool:
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            return False
        raw = receipt.get('store_name_raw')
        if not raw:
            return False
        self.receipt_db.learn_store_match(raw, correct_store_code, weight=1)
        # レシート自体も更新
        self.receipt_db.update_receipt(receipt_id, {"store_code": correct_store_code})
        return True
