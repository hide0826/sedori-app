#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa API ラッパーサービス

ASIN から以下の情報を取得するための薄いラッパー:
- タイトル
- 画像URL（1枚目）
- 新品価格
- 中古価格
- ランキング
- カテゴリ名（簡易。productGroup などから取得）

注意:
- 別途 `pip install keepa` が必要です。
- APIキーは QSettings("HIRIO", "DesktopApp") の "keepa/api_key" から読み込みます。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

from PySide6.QtCore import QSettings

# Keepa の画像キー用ベースURL（公式ドキュメント準拠）
IMAGE_BASE_URL = "https://images-na.ssl-images-amazon.com/images/I/"


@dataclass
class KeepaProductInfo:
    asin: str
    title: Optional[str]
    image_url: Optional[str]
    new_price: Optional[float]
    used_price: Optional[float]
    sales_rank: Optional[int]
    category_name: Optional[str]


class KeepaService:
    """Keepa API 呼び出し用サービス"""

    def __init__(self, api_key: Optional[str] = None) -> None:
        # API キーが渡されなければ設定から読む
        if api_key is None:
            settings = QSettings("HIRIO", "DesktopApp")
            api_key = settings.value("keepa/api_key", "") or None
        self.api_key = api_key
        self._client = None  # 遅延初期化

    def _ensure_client(self):
        if self._client is not None:
            return
        if not self.api_key:
            raise RuntimeError("Keepa APIキーが設定されていません。設定タブで入力してください。")

        try:
            import keepa  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "keepa ライブラリが見つかりません。\n"
                "ターミナルで 'pip install keepa' を実行してください。"
            ) from e

        # 日本の Amazon を対象にする（古い keepa ライブラリ互換のため domain 引数は渡さない）
        self._client = keepa.Keepa(self.api_key)

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

    def fetch_product_by_asin(self, asin: str) -> KeepaProductInfo:
        """ASIN から商品情報を取得する。

        エラー時は RuntimeError を投げるので、呼び出し側で QMessageBox などで通知してください。
        """
        self._ensure_client()

        try:
            # 日本の Amazon.co.jp を明示的に指定して ASIN を問い合わせる
            products = self._client.query(asin, domain="JP")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Keepa API 呼び出しに失敗しました: {e}") from e

        if not products:
            raise RuntimeError(f"ASIN {asin} に対応する商品が見つかりませんでした。")

        p: Dict[str, Any] = products[0]

        title = p.get("title")

        # 画像 URL（imagesCSV があれば優先）
        image_url: Optional[str] = None
        images_csv = p.get("imagesCSV")
        if isinstance(images_csv, str) and images_csv:
            key = images_csv.split(",")[0]
            # フルURLでなければベースURLを付与する
            image_url = key if key.startswith("http") else IMAGE_BASE_URL + key
        else:
            images_list = p.get("images")
            if isinstance(images_list, list) and images_list:
                key = images_list[0]
                image_url = key if isinstance(key, str) and key.startswith("http") else IMAGE_BASE_URL + str(key)

        data: Dict[str, Any] = p.get("data", {}) or {}
        new_price = self._extract_latest_price(data.get("NEW"))
        used_price = self._extract_latest_price(data.get("USED"))
        sales_rank = self._extract_latest_rank(data.get("SALES"))

        # カテゴリ名は厳密には category ツリーを引く必要があるが、
        # ここではコストを抑えるため productGroup や productCategory を優先して使う。
        category_name: Optional[str] = (
            p.get("productGroup")
            or p.get("productCategory")
            or None
        )

        return KeepaProductInfo(
            asin=asin,
            title=title,
            image_url=image_url,
            new_price=new_price,
            used_price=used_price,
            sales_rank=sales_rank,
            category_name=category_name,
        )

    def fetch_raw_product_by_asin(
        self,
        asin: str,
        *,
        stats: Optional[int] = None,
        offers: Optional[int] = None,
        only_live_offers: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        ASIN から Keepa の生 product 辞書を取得する（グラフ描画・時系列用）。
        失敗時は None を返す。呼び出し側で RuntimeError をキャッチする必要はない。
        """
        self._ensure_client()
        try:
            kwargs: Dict[str, Any] = {"domain": "JP"}
            if stats is not None:
                kwargs["stats"] = stats
            if offers is not None:
                kwargs["offers"] = offers
            if only_live_offers is not None:
                kwargs["only_live_offers"] = bool(only_live_offers)
            products = self._client.query(asin, **kwargs)
        except Exception:  # noqa: BLE001
            return None
        if not products:
            return None
        return products[0]

    @staticmethod
    def _maybe_scale_to_jpy(prices: Dict[str, Optional[float]], *, reference_jpy: Optional[float] = None) -> Dict[str, Optional[float]]:
        """
        Keepa/keepaライブラリの価格が 1/100 スケールで返るケース（JPで起きがち）を吸収する。

        例: 7,900円が 79.0 として返る -> 100倍して 7,900 に補正。
        - reference_jpy が与えられる場合は、それと桁が合わないときに補正する。
        - reference_jpy が無い場合は、最大値が小さすぎる場合に補正する（安全寄りのヒューリスティック）。
        """
        vals = [v for v in prices.values() if isinstance(v, (int, float)) and v is not None and v > 0]
        if not vals:
            return prices
        max_v = max(float(v) for v in vals)

        # 参照価格（販売予定価格など）が 1000円以上なのに Keepa側が 300未満なら 1/100 スケールとみなす
        if reference_jpy is not None and reference_jpy >= 1000 and max_v < 300:
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

        # Keepaのoffer conditionコード（経験則 & 一般的な対応）
        # 0: NEW, 1: USED - Like New, 2: USED - Very Good, 3: USED - Good, 4: USED - Acceptable
        cond_to_key = {
            1: "used_like_new_fba",
            2: "used_very_good_fba",
            3: "used_good_fba",
            4: "used_acceptable_fba",
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




