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
    account_title: Optional[str] = None  # 経費先マッチ時は経費先の科目（仕訳）


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

    @staticmethod
    def _normalize_phone(raw: Optional[str]) -> Optional[str]:
        """電話番号を正規化して比較しやすくする

        - 全角→半角
        - 電話番号に関係ない文字を除去
        - 10桁/11桁のみの場合は 03-1234-5678 / 090-1234-5678 形式に整形
        - ハイフン区切り3ブロックまでに統一
        """
        if not raw:
            return None
        import unicodedata
        import re

        s = unicodedata.normalize("NFKC", str(raw))
        s = s.replace("ー", "-").replace("−", "-").replace("―", "-").replace("‐", "-")
        s = re.sub(r"[^0-9-]", "", s)
        # 連続した数字のみの場合は標準的なハイフン位置に整形
        if "-" not in s and len(s) in (10, 11):
            if len(s) == 10:
                s = f"{s[0:2]}-{s[2:6]}-{s[6:]}"
            else:
                s = f"{s[0:3]}-{s[3:7]}-{s[7:]}"
        parts = [p for p in s.split("-") if p]
        if len(parts) >= 3:
            return "-".join(parts[:3])
        return s or None

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

    def _guess_store_code_by_phone(self, phone_number: Optional[str]) -> Optional[str]:
        """電話番号から店舗コードを推定

        店舗名はOCRの表記揺れが大きいため、比較的精度の高い電話番号を優先的に使用する。
        - 電話番号が取得できていない場合は None を返す
        - stores.phone を同じ正規化ルールで整形し、完全一致した店舗の store_code を返す
        """
        normalized_target = self._normalize_phone(phone_number)
        if not normalized_target:
            return None

        try:
            stores = self.store_db.list_stores()
        except Exception:
            stores = []

        for st in stores:
            store_phone = st.get("phone") or ""
            if not store_phone:
                continue
            normalized_store_phone = self._normalize_phone(store_phone)
            if normalized_store_phone and normalized_store_phone == normalized_target:
                # 店舗コード優先、なければ互換性のため仕入れ先コード
                return st.get("store_code") or st.get("supplier_code")

        return None

    def _guess_expense_destination_by_phone(self, phone_number: Optional[str]) -> Optional[Tuple[str, str]]:
        """電話番号から経費先を推定。(経費先コード, 科目journal) を返す。見つからなければ None"""
        normalized_target = self._normalize_phone(phone_number)
        if not normalized_target:
            return None
        try:
            dests = self.store_db.list_expense_destinations()
        except Exception:
            dests = []
        for d in dests:
            dest_phone = d.get("phone") or ""
            if not dest_phone:
                continue
            normalized_dest_phone = self._normalize_phone(dest_phone)
            if normalized_dest_phone and normalized_dest_phone == normalized_target:
                code = (d.get("code") or "").strip()
                journal = (d.get("journal") or "").strip()
                if code:
                    return (code, journal)
        return None

    def _guess_expense_destination_by_name(self, raw_name: Optional[str]) -> Optional[Tuple[str, str]]:
        """店舗名（名称）から経費先を推定。(経費先コード, 科目journal) を返す。見つからなければ None"""
        if not raw_name:
            return None
        raw_name = self._normalize_text(raw_name)
        try:
            dests = self.store_db.list_expense_destinations(search_term=raw_name)
        except Exception:
            dests = []
        if not dests:
            try:
                dests = self.store_db.list_expense_destinations()
            except Exception:
                dests = []
        raw_lower = raw_name.lower()
        for d in dests:
            name = (d.get("name") or "").lower()
            if name and (raw_lower in name or name in raw_lower):
                code = (d.get("code") or "").strip()
                journal = (d.get("journal") or "").strip()
                if code:
                    return (code, journal)
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
        phone_number = receipt.get('phone_number')
        total = receipt.get('total_amount')
        discount = receipt.get('discount_amount') or 0
        effective_total = None
        if isinstance(total, int):
            effective_total = total - (discount or 0)

        # 日付一致のアイテムに限定
        same_day_items = [it for it in purchase_items if (it.get('purchase_date') == purchase_date)]

        # 推定店舗コード
        # 1. 明示的に指定された店舗コード（preferred_store_code / receipt.store_code）
        # 2. 電話番号からの推定（店舗マスタ優先）
        # 3. 店舗名（store_name_raw）からの推定（店舗マスタ）
        # 4. 店舗に無い場合は経費先を電話番号・名称で検索
        store_code = (
            preferred_store_code
            or receipt.get('store_code')
            or self._guess_store_code_by_phone(phone_number)
            or self._guess_store_code(raw_name)
        )
        account_title_from_expense: Optional[str] = None
        if not store_code:
            expense_match = self._guess_expense_destination_by_phone(phone_number) or self._guess_expense_destination_by_name(raw_name)
            if expense_match:
                store_code = expense_match[0]
                account_title_from_expense = expense_match[1] or None

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
            account_title=account_title_from_expense,
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
