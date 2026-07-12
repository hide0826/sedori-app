#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa live offer / offerCSV ヘルパー（Mixin）。"""

from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple

from .models import KeepaOfferRow


class KeepaOfferHelpersMixin:
    """offerCSV・live offers・FBA/Amazon 判定。"""

    # live offers を取るときのオファー本数（Keepa トークンとトレードオフ）
    _LIVE_OFFERS_LIMIT: int = 60

    @staticmethod
    def _offer_csv_numbers(csv: Any) -> Optional[List[float]]:
        """offerCSV を数値リストに正規化する（list / numpy / カンマ区切り文字列に対応）。"""
        if csv is None:
            return None
        if isinstance(csv, str):
            s = csv.strip()
            if not s:
                return None
            parts = [p.strip() for p in s.split(",") if p.strip() != ""]
            if not parts:
                return None
            out: List[float] = []
            for p in parts:
                try:
                    out.append(float(p))
                except (TypeError, ValueError):
                    return None
            return out
        try:
            seq = list(csv)
        except TypeError:
            return None
        out: List[float] = []
        for x in seq:
            try:
                out.append(float(x))
            except (TypeError, ValueError):
                return None
        return out if out else None

    @staticmethod
    def _offer_last_landed_list_price(offer: Dict[str, Any]) -> Optional[float]:
        """offerCSV の末尾から (本体+送料) を取得。値はリスト価格系と同様に 100 で割った単位。"""
        csv = offer.get("offerCSV")
        # 分割後は定義モジュール内で Mixin 名を参照（KeepaService 経由でも同一実装）
        seq = KeepaOfferHelpersMixin._offer_csv_numbers(csv)
        if not seq:
            return None
        if len(seq) < 3:
            return None
        # Keepa: [時刻, 価格, 送料, 時刻, 価格, 送料, ...] — 価格は index 1,4,7,...（len-2 から 3 刻み）
        for i in range(len(seq) - 2, -1, -3):
            if i + 1 >= len(seq):
                continue
            try:
                price = float(seq[i])
                ship_raw = seq[i + 1]
                ship = float(ship_raw) if ship_raw is not None else 0.0
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            if ship < 0:
                ship = 0.0
            return (price + ship) / 100.0
        return None

    @staticmethod
    def _offer_last_price_ship_list_units(offer: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """offerCSV 末尾トリプレットから (本体, 送料) をリスト単位で返す（各々 /100 済み）。"""
        csv = offer.get("offerCSV")
        seq = KeepaOfferHelpersMixin._offer_csv_numbers(csv)
        if not seq or len(seq) < 3:
            return None, None
        for i in range(len(seq) - 2, -1, -3):
            if i + 1 >= len(seq):
                continue
            try:
                price = float(seq[i])
                ship_raw = seq[i + 1]
                ship = float(ship_raw) if ship_raw is not None else 0.0
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            if ship < 0:
                ship = 0.0
            return price / 100.0, ship / 100.0
        return None, None

    # Keepa Offer.condition（公式 Offer.java と同一）
    # 0 不明, 1 新品, 2 中古・ほぼ新品, 3 中古・非常に良い, 4 中古・良い, 5 中古・可, 6 再生品, 7–10 コレクティブル各種
    _CONDITION_LABEL_JP: Dict[int, str] = {
        0: "不明",
        1: "新品",
        2: "ほぼ新品",
        3: "非常に良い",
        4: "良い",
        5: "可",
        6: "再生品",
        7: "コレクティブル・ほぼ新品",
        8: "コレクティブル・非常に良い",
        9: "コレクティブル・良い",
        10: "コレクティブル・可",
    }

    @classmethod
    def _condition_label_jp(cls, code: int) -> str:
        if code < 0:
            return "不明"
        return cls._CONDITION_LABEL_JP.get(code, f"条件{code}")

    @staticmethod
    def _offer_is_fba(offer: Dict[str, Any]) -> bool:
        return bool(
            offer.get("isFBA")
            or offer.get("isAmazonFulfilled")
            or offer.get("is_amazon_fulfilled")
        )

    @staticmethod
    def _offer_is_amazon_retail(offer: Dict[str, Any]) -> bool:
        return bool(offer.get("isAmazon") or offer.get("is_amazon"))

    @staticmethod
    def _offer_seller_id(offer: Dict[str, Any]) -> Optional[str]:
        sid = offer.get("sellerId") or offer.get("seller_id")
        if sid is None:
            return None
        s = str(sid).strip()
        return s.upper() if s else None

    @classmethod
    def _offer_seller_note(cls, offer: Dict[str, Any]) -> str:
        sid_raw = offer.get("sellerId") or offer.get("seller_id")
        name = offer.get("sellerName") or offer.get("seller_name")
        if sid_raw and name:
            return f"{name} ({sid_raw})"
        if sid_raw:
            return str(sid_raw)
        if name:
            return str(name)
        return "-"

    def build_live_offer_display_rows(
        self,
        raw_product: Dict[str, Any],
    ) -> Tuple[List[KeepaOfferRow], List[KeepaOfferRow]]:
        """
        live offers を新品 / 中古に分け、出品者向けの行リストにする。
        価格スケールは extract_min_landed_prices と同じ _maybe_scale_to_jpy を一括適用。
        """
        offers = raw_product.get("offers") or []
        if not isinstance(offers, list) or not offers:
            return [], []

        landed_by_key: Dict[str, float] = {}
        meta_by_key: Dict[str, Tuple[Dict[str, Any], float, float]] = {}

        for i, offer in enumerate(offers):
            if not isinstance(offer, dict):
                continue
            pr, sh = self._offer_last_price_ship_list_units(offer)
            if pr is None:
                continue
            landed = pr + sh
            if landed <= 0:
                continue
            key = str(i)
            landed_by_key[key] = landed
            meta_by_key[key] = (offer, pr, sh)

        if not landed_by_key:
            return [], []

        ref_jpy = self._reference_price_jpy_from_product(raw_product)
        scaled_landed = self._maybe_scale_to_jpy(
            {k: float(v) for k, v in landed_by_key.items()},
            reference_jpy=ref_jpy,
        )

        new_rows: List[KeepaOfferRow] = []
        used_rows: List[KeepaOfferRow] = []

        for key, landed_raw in landed_by_key.items():
            offer, pr, sh = meta_by_key[key]
            scaled_total = scaled_landed.get(key)
            if scaled_total is None:
                continue
            try:
                cond_i = int(offer.get("condition"))
            except (TypeError, ValueError):
                cond_i = -1

            fac = float(scaled_total) / landed_raw if landed_raw > 0 else 1.0
            price_jpy = int(round(pr * fac))
            ship_jpy = int(round(sh * fac))
            total_jpy = int(round(float(scaled_total)))

            row = KeepaOfferRow(
                condition_label=self._condition_label_jp(cond_i),
                is_fba=self._offer_is_fba(offer),
                is_amazon=self._offer_is_amazon_retail(offer),
                seller_note=self._offer_seller_note(offer),
                price_jpy=price_jpy,
                ship_jpy=ship_jpy,
                total_jpy=total_jpy,
                seller_id=self._offer_seller_id(offer),
            )
            # Keepa: 1=新品のみが新品列。0=不明・2以降は中古側に出す
            if cond_i == 1:
                new_rows.append(row)
            else:
                used_rows.append(row)

        new_rows.sort(key=lambda r: (r.total_jpy, r.price_jpy))
        used_rows.sort(key=lambda r: (r.total_jpy, r.price_jpy))
        return new_rows, used_rows

    def extract_min_landed_prices_from_live_offers(
        self,
        raw_product: Dict[str, Any],
    ) -> Tuple[Dict[str, Optional[float]], bool]:
        """
        live offers からコンディション別の「本体+送料」最安を集計する（FBA/自己発送どちらも含む）。

        戻り値:
        - 辞書キー: new, used_like_new, used_very_good, used_good, used_acceptable
        - bool: offers リストが 1 件以上あったか（空なら別扱いで UI が分かるように）
        """
        offers = raw_product.get("offers") or []
        if not isinstance(offers, list):
            return (
                {
                    "new": None,
                    "used_like_new": None,
                    "used_very_good": None,
                    "used_good": None,
                    "used_acceptable": None,
                },
                False,
            )

        # Keepa Offer.condition（Offer.java）
        cond_to_key: Dict[int, str] = {
            1: "new",
            2: "used_like_new",
            3: "used_very_good",
            4: "used_good",
            5: "used_acceptable",
        }
        mins: Dict[str, Optional[float]] = {
            "new": None,
            "used_like_new": None,
            "used_very_good": None,
            "used_good": None,
            "used_acceptable": None,
        }

        for offer in offers:
            if not isinstance(offer, dict):
                continue
            try:
                cond_i = int(offer.get("condition"))
            except (TypeError, ValueError):
                continue
            key = cond_to_key.get(cond_i)
            if not key:
                continue
            landed = self._offer_last_landed_list_price(offer)
            if landed is None or landed <= 0:
                continue
            cur = mins.get(key)
            if cur is None or landed < cur:
                mins[key] = landed

        return mins, len(offers) > 0

    def extract_fba_min_prices_from_live_offers(
        self,
        raw_product: Dict[str, Any],
        *,
        reference_jpy: Optional[float] = None,
    ) -> Dict[str, Optional[float]]:
        """
        Keepaの live offers から、FBAのみ・コンディション別の「現在最安」を抽出する（第2段階）。

        前提:
        - query(..., offers=xx, only_live_offers=True) で取得した product を渡す。
        - raw_product['offers'] が live offers のみになる。

        返すキー:
        - used_like_new_fba / used_very_good_fba / used_good_fba / used_acceptable_fba
        """
        try:
            import keepa  # type: ignore
        except Exception:
            keepa = None  # type: ignore

        offers = raw_product.get("offers") or []
        if not isinstance(offers, list) or not offers:
            return {
                "used_like_new_fba": None,
                "used_very_good_fba": None,
                "used_good_fba": None,
                "used_acceptable_fba": None,
            }

        # Keepa Offer.condition（Offer.java）。新品(1)はこの集計から除外（中古帯のみ）
        cond_to_key = {
            2: "used_like_new_fba",
            3: "used_very_good_fba",
            4: "used_good_fba",
            5: "used_acceptable_fba",
        }

        mins: Dict[str, Optional[float]] = {v: None for v in cond_to_key.values()}

        def _offer_current_price(offer: Dict[str, Any]) -> Optional[float]:
            csv = offer.get("offerCSV")
            if not csv:
                return None
            # offerCSV を解析して最新価格を取る（keepa.convert_offer_history が利用可能）
            try:
                if keepa is not None and hasattr(keepa, "convert_offer_history"):
                    _times, _prices = keepa.convert_offer_history(csv)  # type: ignore[attr-defined]
                    if _prices is None or len(_prices) == 0:
                        return None
                    return float(_prices[-1])
            except Exception:
                pass
            # フォールバック: offerCSV は [t, price, shipping, t, price, shipping, ...] 形式
            try:
                seq = list(csv)
                if len(seq) < 2:
                    return None
                # 末尾から price を探す
                for i in range(len(seq) - 2, -1, -3):
                    v = seq[i]
                    if v is None:
                        continue
                    fv = float(v)
                    if fv > 0:
                        return fv / 100.0  # ここは多くのケースで cents/100。下で補正もする
            except Exception:
                return None
            return None

        for offer in offers:
            try:
                if not offer.get("isFBA"):
                    continue
                cond = offer.get("condition")
                try:
                    cond_i = int(cond)
                except Exception:
                    continue
                key = cond_to_key.get(cond_i)
                if not key:
                    continue
                price = _offer_current_price(offer)
                if price is None or price <= 0:
                    continue
                cur_min = mins.get(key)
                if cur_min is None or price < cur_min:
                    mins[key] = price
            except Exception:
                continue

        return self._maybe_scale_to_jpy(mins, reference_jpy=reference_jpy)
