#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa 価格抽出・円スケール補正ヘルパー（Mixin）。"""

from __future__ import annotations

from typing import Optional, Dict, Any, List


class KeepaPriceHelpersMixin:
    """価格系列・コンディション価格・円スケール補正。"""

    @staticmethod
    def _extract_latest_price(price_series: Optional[list]) -> Optional[float]:
        """Keepa の価格配列から直近の有効価格を取得する（円換算）。"""
        if price_series is None:
            return None

        # keepa の古いバージョンでは numpy 配列になることがあるので、
        # 真偽値評価ではなく len() と list() で扱う
        try:
            seq = list(price_series)
        except TypeError:
            return None

        if len(seq) == 0:
            return None

        # 後ろから走査して 0 より大きい値を見つける
        for v in reversed(seq):
            if v is None:
                continue
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            if val > 0:
                # keepa ライブラリ側でスケーリング済みのため、そのまま返す
                return round(val, 2)
        return None

    @staticmethod
    def _extract_latest_rank(rank_series: Optional[list]) -> Optional[int]:
        if rank_series is None:
            return None

        try:
            seq = list(rank_series)
        except TypeError:
            return None

        if len(seq) == 0:
            return None

        for v in reversed(seq):
            if v and v > 0:
                return int(v)
        return None

    def _reference_price_jpy_from_product(self, raw_product: Dict[str, Any]) -> Optional[float]:
        """live offers のスケール合わせ用。stats.current（円ベース）を優先し、無ければ履歴 data を使う。"""
        if not isinstance(raw_product, dict):
            return None
        from_stats: List[float] = []
        try:
            stats = raw_product.get("stats") or {}
            cur = stats.get("current")
            if isinstance(cur, list) and cur:
                for idx in (18, 21, 20, 22, 19, 2, 1, 10):
                    if idx < 0 or idx >= len(cur):
                        continue
                    v = cur[idx]
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        continue
                    if fv > 0:
                        from_stats.append(fv)
        except Exception:
            pass
        if from_stats:
            return max(from_stats)

        candidates: List[float] = []
        data: Dict[str, Any] = raw_product.get("data", {}) or {}
        for key in (
            "BUY_BOX_SHIPPING",
            "NEW_FBA_SHIPPING",
            "NEW_SHIPPING",
            "USED_GOOD_SHIPPING",
            "USED_VERY_GOOD_SHIPPING",
            "USED_ACCEPTABLE_SHIPPING",
            "USED_NEW_SHIPPING",
            "USED_SHIPPING",
            "USED",
            "NEW_FBA",
            "NEW",
        ):
            p = self._extract_latest_price(data.get(key))
            if p is not None and p > 0:
                candidates.append(float(p))
        return max(candidates) if candidates else None

    @staticmethod
    def _maybe_scale_to_jpy(prices: Dict[str, Optional[float]], *, reference_jpy: Optional[float] = None) -> Dict[str, Optional[float]]:
        """
        Keepa/keepaライブラリの価格が 1/100 スケールで返るケース（JPで起きがち）を吸収する。

        例: 7,900円が 79.0 として返る -> 100倍して 7,900 に補正。
        - reference_jpy（stats.current や履歴から取った代表価格）が 1000円以上かつ
          集計値の最大が 300 未満のときは ×100（live offers と stats の桁ずれ吸収）。
        - reference_jpy が無い場合は、最大値が 200 未満なら ×100（ヒューリスティック）。
        """
        vals = [v for v in prices.values() if isinstance(v, (int, float)) and v is not None and v > 0]
        if not vals:
            return prices
        max_v = max(float(v) for v in vals)

        # 参照価格（履歴・stats 等）が十分高いのに offer 集計が桁違いに低い → さらに ×100 が必要なケース（JP）
        if reference_jpy is not None and reference_jpy >= 1000 and max_v > 0 and max_v < 300:
            return {k: (None if v is None else round(float(v) * 100.0, 2)) for k, v in prices.items()}

        # 参照が無い場合: 価格の最大が 200未満なら 1/100 の可能性が高い（JPの実価格としては不自然）
        if reference_jpy is None and max_v < 200:
            return {k: (None if v is None else round(float(v) * 100.0, 2)) for k, v in prices.items()}

        return prices

    def extract_condition_prices_jp(
        self,
        raw_product: Dict[str, Any],
        *,
        reference_jpy: Optional[float] = None,
    ) -> Dict[str, Optional[float]]:
        """
        Keepa の生 product 辞書から、コンディション別の「直近価格」を抽出する（第1段階）。

        戻り値のキーは UI 表示向けに固定:
        - new: 新品（Marketplace new）
        - new_fba: 新品FBA（Keepa の NEW_FBA があれば）
        - used: 中古（Marketplace used）
        - used_like_new: 中古-ほぼ新品（送料込み）
        - used_very_good: 中古-非常に良い（送料込み）
        - used_good: 中古-良い（送料込み）
        - used_acceptable: 中古-可（送料込み）
        - buy_box: BuyBox（送料込み）

        注意: ここでは「FBA限定」にはしていない（第2段階で offers 集計が必要）。
        """
        data: Dict[str, Any] = (raw_product.get("data", {}) or {}) if isinstance(raw_product, dict) else {}
        getp = self._extract_latest_price
        prices: Dict[str, Optional[float]] = {
            "new": getp(data.get("NEW")),
            "new_fba": getp(data.get("NEW_FBA")),
            "used": getp(data.get("USED")),
            # Keepaのキー名は USED_NEW_SHIPPING が「Used - Like New」相当
            "used_like_new": getp(data.get("USED_NEW_SHIPPING")),
            "used_very_good": getp(data.get("USED_VERY_GOOD_SHIPPING")),
            "used_good": getp(data.get("USED_GOOD_SHIPPING")),
            "used_acceptable": getp(data.get("USED_ACCEPTABLE_SHIPPING")),
            "buy_box": getp(data.get("BUY_BOX_SHIPPING")),
        }

        # JPで履歴キーが入らない場合があるため、stats.current をフォールバックに使う
        try:
            stats = raw_product.get("stats") or {}
            current = stats.get("current")
            if isinstance(current, list) and current:
                def _cur(i: int) -> Optional[float]:
                    if i < 0 or i >= len(current):
                        return None
                    v = current[i]
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        return None
                    return None if v <= 0 else v

                # まだ値が取れていない項目だけ current から埋める
                if not prices.get("new"):
                    prices["new"] = _cur(1)
                if not prices.get("new_fba"):
                    prices["new_fba"] = _cur(10)
                if not prices.get("used"):
                    prices["used"] = _cur(2)
                if not prices.get("buy_box"):
                    prices["buy_box"] = _cur(18)
                if not prices.get("used_like_new"):
                    prices["used_like_new"] = _cur(19)
                if not prices.get("used_very_good"):
                    prices["used_very_good"] = _cur(20)
                if not prices.get("used_good"):
                    prices["used_good"] = _cur(21)
                if not prices.get("used_acceptable"):
                    prices["used_acceptable"] = _cur(22)
        except Exception:
            pass

        return self._maybe_scale_to_jpy(prices, reference_jpy=reference_jpy)

    @staticmethod
    def extract_used_offer_count(raw_product: Dict[str, Any]) -> Optional[int]:
        """Keepa stats.current から中古出品数（COUNT_USED）を取得する。なければ None。"""
        try:
            stats = raw_product.get("stats") or {}
            current = stats.get("current")
            if not isinstance(current, list) or len(current) <= 12:
                return None
            v = current[12]  # COUNT_USED
            if v is None:
                return None
            iv = int(v)
            return iv if iv >= 0 else None
        except Exception:
            return None
