#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa API ラッパーサービス

ASIN から以下の情報を取得するための薄いラッパー:
- タイトル
- 画像URL（1枚目）
- 新品・中古コンディション別の最安（**live offers** から **price+送料** の合計で集計）
- JP で 1/100 スケールのときは円に補正
- ランキング
- カテゴリ名（簡易。productGroup などから取得）

注意:
- 別途 `pip install keepa` が必要です。
- APIキーは QSettings("HIRIO", "DesktopApp") の "keepa/api_key" から読み込みます。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple, Literal
import time
from datetime import datetime, timedelta, timezone
import statistics
import json
import re

from PySide6.QtCore import QSettings

# Keepa の画像キー用ベースURL（公式ドキュメント準拠）
IMAGE_BASE_URL = "https://images-na.ssl-images-amazon.com/images/I/"


@dataclass
class KeepaProductInfo:
    asin: str
    title: Optional[str]
    image_url: Optional[str]
    new_price: Optional[float]
    new_price_state: Literal["ok", "no_seller", "no_data"]
    used_like_new: Optional[float]
    used_like_new_state: Literal["ok", "no_seller", "no_data"]
    used_very_good: Optional[float]
    used_very_good_state: Literal["ok", "no_seller", "no_data"]
    used_good: Optional[float]
    used_good_state: Literal["ok", "no_seller", "no_data"]
    used_acceptable: Optional[float]
    used_acceptable_state: Literal["ok", "no_seller", "no_data"]
    sales_rank: Optional[int]
    category_name: Optional[str]


@dataclass
class KeepaOfferRow:
    """live offer 1件分（UI 表示用・円は fetch 時と同じスケール補正済み）。"""

    condition_label: str
    is_fba: bool
    is_amazon: bool
    seller_note: str
    price_jpy: int
    ship_jpy: int
    total_jpy: int
    seller_id: Optional[str] = None


@dataclass
class Keepa369AnalysisResult:
    """3-6-9ロジック用の解析結果"""

    window_days: int
    sales_drop_count: int
    inferred_sales_count: int
    total_effective_drop_count: int
    used_price_avg: Optional[float]
    used_price_range: Optional[float]
    used_offer_count_delta: Optional[int]
    condition_price_summary: Dict[str, Dict[str, Optional[float]]]
    ai_mode: str
    ai_adjustment_percent: float
    ai_reasoning: str


class KeepaService:
    """Keepa API 呼び出し用サービス"""

    _QUERY_RETRY_COUNT: int = 3
    _QUERY_RETRY_WAIT_SECONDS: float = 1.5

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

    def _query_with_retry(self, asin: str, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        Keepa API呼び出しをリトライ付きで実行する。
        タイムアウトや一時的な通信不良時に数回再試行する。
        """
        last_error: Optional[Exception] = None
        for attempt in range(1, self._QUERY_RETRY_COUNT + 1):
            try:
                return self._client.query(asin, **kwargs)
            except Exception as e:  # noqa: BLE001
                last_error = e
                # 最終試行ならそのまま抜ける
                if attempt >= self._QUERY_RETRY_COUNT:
                    break
                time.sleep(self._QUERY_RETRY_WAIT_SECONDS * attempt)
        if last_error is not None:
            raise last_error
        return []

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
        seq = KeepaService._offer_csv_numbers(csv)
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
        seq = KeepaService._offer_csv_numbers(csv)
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

    def _build_keepa_product_info(self, asin: str, p: Dict[str, Any]) -> KeepaProductInfo:
        title = p.get("title")

        image_url: Optional[str] = None
        images_csv = p.get("imagesCSV")
        if isinstance(images_csv, str) and images_csv:
            key = images_csv.split(",")[0]
            image_url = key if key.startswith("http") else IMAGE_BASE_URL + key
        else:
            images_list = p.get("images")
            if isinstance(images_list, list) and images_list:
                key = images_list[0]
                image_url = key if isinstance(key, str) and key.startswith("http") else IMAGE_BASE_URL + str(key)

        data: Dict[str, Any] = p.get("data", {}) or {}
        sales_rank = self._extract_latest_rank(data.get("SALES"))

        mins_raw, had_any_offers = self.extract_min_landed_prices_from_live_offers(p)

        to_scale: Dict[str, float] = {}
        for k, v in mins_raw.items():
            if v is not None and v > 0:
                to_scale[k] = float(v)

        scaled = self._maybe_scale_to_jpy(
            {k: float(v) for k, v in to_scale.items()},
            reference_jpy=self._reference_price_jpy_from_product(p),
        )

        def _state_for_key(key: str) -> Tuple[Literal["ok", "no_seller", "no_data"], Optional[float]]:
            v = mins_raw.get(key)
            if v is not None and v > 0:
                return ("ok", scaled.get(key))
            if had_any_offers:
                return ("no_seller", None)
            return ("no_data", None)

        new_st, new_price = _state_for_key("new")
        ln_st, used_like_new = _state_for_key("used_like_new")
        vg_st, used_very_good = _state_for_key("used_very_good")
        g_st, used_good = _state_for_key("used_good")
        acc_st, used_acceptable = _state_for_key("used_acceptable")

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
            new_price_state=new_st,
            used_like_new=used_like_new,
            used_like_new_state=ln_st,
            used_very_good=used_very_good,
            used_very_good_state=vg_st,
            used_good=used_good,
            used_good_state=g_st,
            used_acceptable=used_acceptable,
            used_acceptable_state=acc_st,
            sales_rank=sales_rank,
            category_name=category_name,
        )

    def fetch_product_with_raw(self, asin: str) -> Tuple[KeepaProductInfo, Dict[str, Any]]:
        """ASIN から商品情報と Keepa 生 product 辞書を返す（offers 詳細表示用）。"""
        self._ensure_client()

        try:
            products = self._query_with_retry(
                asin,
                domain="JP",
                offers=self._LIVE_OFFERS_LIMIT,
                only_live_offers=True,
                stats=90,
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "Keepa API 呼び出しに失敗しました。"
                "ネットワークやKeepa側混雑の可能性があります。"
                f"（{self._QUERY_RETRY_COUNT}回再試行済み）\n詳細: {e}"
            ) from e

        if not products:
            raise RuntimeError(f"ASIN {asin} に対応する商品が見つかりませんでした。")

        p: Dict[str, Any] = products[0]
        return self._build_keepa_product_info(asin, p), p

    def fetch_product_by_asin(self, asin: str) -> KeepaProductInfo:
        """ASIN から商品情報を取得する。

        エラー時は RuntimeError を投げるので、呼び出し側で QMessageBox などで通知してください。
        """
        info, _ = self.fetch_product_with_raw(asin)
        return info

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
            products = self._query_with_retry(asin, **kwargs)
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

    # ---------------------------
    # 3-6-9 ロジック向け解析
    # ---------------------------
    _KEEPA_EPOCH = datetime(2011, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def _keepa_minutes_to_datetime(cls, keepa_minutes: float) -> datetime:
        return cls._KEEPA_EPOCH + timedelta(minutes=float(keepa_minutes))

    @staticmethod
    def _to_float_or_none(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            v = float(value)
            return v
        except (TypeError, ValueError):
            return None

    def _extract_time_series(
        self,
        raw_product: Dict[str, Any],
        key_candidates: List[str],
    ) -> List[Tuple[datetime, float]]:
        """
        Keepa raw product の data/csv から時系列を取り出す。
        - keepa ライブラリ経由の data[key]（値のみ配列）にも対応
        - 生 csv の [minute, value, minute, value, ...] にも対応
        """
        # 1) data キーから取得
        data = raw_product.get("data") or {}
        for key in key_candidates:
            series = data.get(key)
            if series is None:
                continue
            try:
                seq = list(series)
            except TypeError:
                continue
            if not seq:
                continue
            # keepa.convert_history が使える場合はそれを最優先
            try:
                import keepa  # type: ignore
                if hasattr(keepa, "convert_history"):
                    times, values = keepa.convert_history(seq)  # type: ignore[attr-defined]
                    out: List[Tuple[datetime, float]] = []
                    if times is not None and values is not None:
                        for t, v in zip(times, values):
                            fv = self._to_float_or_none(v)
                            if fv is None or fv <= 0:
                                continue
                            if isinstance(t, datetime):
                                out.append((t if t.tzinfo else t.replace(tzinfo=timezone.utc), fv))
                            else:
                                tv = self._to_float_or_none(t)
                                if tv is not None:
                                    out.append((self._keepa_minutes_to_datetime(tv), fv))
                    if out:
                        return out
            except Exception:
                pass

            # フォールバック: [m, v, m, v, ...]
            if len(seq) >= 2:
                out = []
                for i in range(0, len(seq) - 1, 2):
                    m = self._to_float_or_none(seq[i])
                    v = self._to_float_or_none(seq[i + 1])
                    if m is None or v is None or v <= 0:
                        continue
                    out.append((self._keepa_minutes_to_datetime(m), v))
                if out:
                    return out

        # 2) 生 csv フィールドから取得（エクスポートJSON互換）
        csv_field = raw_product.get("csv") or {}
        for key in key_candidates:
            series = csv_field.get(key)
            if series is None:
                continue
            try:
                seq = list(series)
            except TypeError:
                continue
            out = []
            for i in range(0, len(seq) - 1, 2):
                m = self._to_float_or_none(seq[i])
                v = self._to_float_or_none(seq[i + 1])
                if m is None or v is None or v <= 0:
                    continue
                out.append((self._keepa_minutes_to_datetime(m), v))
            if out:
                return out
        return []

    @staticmethod
    def _slice_series(
        series: List[Tuple[datetime, float]],
        *,
        window_days: int,
    ) -> List[Tuple[datetime, float]]:
        if not series:
            return []
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=window_days)
        return [(t, v) for t, v in series if t >= since]

    @staticmethod
    def _count_sales_drops(rank_series: List[Tuple[datetime, float]]) -> int:
        """
        SALESランクのドロップ数（順位が良化=数値が減少）を近似カウント。
        小さなノイズを避けるため、直前比3%以上改善をドロップとみなす。
        """
        if len(rank_series) < 2:
            return 0
        count = 0
        prev = rank_series[0][1]
        for _, cur in rank_series[1:]:
            if prev > 0 and cur > 0:
                improved_ratio = (prev - cur) / prev
                if improved_ratio >= 0.03:
                    count += 1
            prev = cur
        return count

    @staticmethod
    def _infer_sales_from_offer_count(offer_count_series: List[Tuple[datetime, float]]) -> int:
        """
        ランキング欠落時の代替判定:
        出品者数が減少した変化を「実売推測」としてカウント。
        """
        if len(offer_count_series) < 2:
            return 0
        inferred = 0
        prev = int(round(offer_count_series[0][1]))
        for _, cur_raw in offer_count_series[1:]:
            cur = int(round(cur_raw))
            if cur < prev:
                inferred += (prev - cur)
            prev = cur
        return max(inferred, 0)

    @staticmethod
    def _series_avg_and_range(series: List[Tuple[datetime, float]]) -> Tuple[Optional[float], Optional[float]]:
        if not series:
            return None, None
        vals = [v for _, v in series if v > 0]
        if not vals:
            return None, None
        return float(statistics.mean(vals)), float(max(vals) - min(vals))

    def analyze_keepa_for_369(
        self,
        raw_product: Dict[str, Any],
        *,
        window_days: int = 90,
    ) -> Dict[str, Any]:
        """
        Keepaデータから3-6-9ロジック用の判断材料を抽出する（非AI）。
        """
        w = max(1, min(int(window_days), 365))

        sales_series = self._slice_series(
            self._extract_time_series(raw_product, ["SALES", "sales", "sales_rank"]),
            window_days=w,
        )
        used_price_series = self._slice_series(
            self._extract_time_series(raw_product, ["USED", "USED_NEWBIE", "used_price"]),
            window_days=w,
        )
        used_offer_count_series = self._slice_series(
            self._extract_time_series(raw_product, ["COUNT_USED", "USED_OFFER_COUNT", "count_used"]),
            window_days=w,
        )

        c_vg = self._slice_series(
            self._extract_time_series(raw_product, ["USED_VERY_GOOD_SHIPPING", "COUNT_USED_VERY_GOOD"]),
            window_days=w,
        )
        c_g = self._slice_series(
            self._extract_time_series(raw_product, ["USED_GOOD_SHIPPING", "COUNT_USED_GOOD"]),
            window_days=w,
        )
        c_a = self._slice_series(
            self._extract_time_series(raw_product, ["USED_ACCEPTABLE_SHIPPING", "COUNT_USED_ACCEPTABLE"]),
            window_days=w,
        )

        sales_drop_count = self._count_sales_drops(sales_series)
        inferred_sales_count = self._infer_sales_from_offer_count(used_offer_count_series)
        total_effective_drop_count = sales_drop_count + inferred_sales_count

        used_avg, used_range = self._series_avg_and_range(used_price_series)
        offer_delta = None
        if len(used_offer_count_series) >= 2:
            offer_delta = int(round(used_offer_count_series[-1][1] - used_offer_count_series[0][1]))

        def _summary(series: List[Tuple[datetime, float]]) -> Dict[str, Optional[float]]:
            avg, rg = self._series_avg_and_range(series)
            return {
                "avg": avg,
                "range": rg,
                "latest": series[-1][1] if series else None,
            }

        result = {
            "window_days": w,
            "sales_drop_count": sales_drop_count,
            "inferred_sales_count": inferred_sales_count,
            "total_effective_drop_count": total_effective_drop_count,
            "used_price_avg": used_avg,
            "used_price_range": used_range,
            "used_offer_count_delta": offer_delta,
            "condition_price_summary": {
                "very_good": _summary(c_vg),
                "good": _summary(c_g),
                "acceptable": _summary(c_a),
            },
        }
        return result

    def interpret_369_with_gemini(
        self,
        analysis: Dict[str, Any],
        *,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.0-flash",
    ) -> Dict[str, Any]:
        """
        抽出済み分析データをGeminiに渡して、運用モードと補正値を返す。
        補正値は -5.0〜+5.0% にクリップする。
        """
        if api_key is None:
            settings = QSettings("HIRIO", "DesktopApp")
            api_key = (settings.value("ocr/gemini_api_key", "") or "").strip() or None
        if not api_key:
            return {
                "mode": "バランス",
                "ai_adjustment_percent": 0.0,
                "reasoning": "Gemini APIキー未設定のため、補正値は0%。",
            }
        try:
            import google.generativeai as genai  # type: ignore
        except Exception:
            return {
                "mode": "バランス",
                "ai_adjustment_percent": 0.0,
                "reasoning": "google-generativeai未導入のため、補正値は0%。",
            }

        prompt = (
            "あなたは中古せどり価格戦略アシスタントです。"
            "以下の3-6-9分析データを見て、運用モードと補正値を返してください。"
            "出力はJSONのみ。\n\n"
            "判定基準:\n"
            "- 月間ドロップ10回以上: 高回転（利益追求寄り、+2~+3%も可）\n"
            "- 月間ドロップ2回以下: 滞留リスク（回転重視、早め値下げ）\n"
            "- ランキング欠落時は inferred_sales_count を実売推測として含める\n"
            "- 出品者数急増なら回避行動（補正をマイナス）\n\n"
            "出力スキーマ:\n"
            "{\n"
            '  "mode": "利益追求|バランス|回転重視",\n'
            '  "ai_adjustment_percent": number,  // -5.0 〜 +5.0\n'
            '  "reasoning": "日本語で根拠"\n'
            "}\n\n"
            f"分析データ:\n{json.dumps(analysis, ensure_ascii=False)}"
        )
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name,
                generation_config={
                    "temperature": 0.2,
                    "max_output_tokens": 512,
                    "response_mime_type": "application/json",
                },
            )
            response = model.generate_content(prompt)
            text = getattr(response, "text", "") or ""
            if not text and getattr(response, "candidates", None):
                parts = response.candidates[0].content.parts  # type: ignore[attr-defined]
                if parts:
                    text = parts[0].text
            parsed: Dict[str, Any] = json.loads(text)
        except Exception as e:
            return {
                "mode": "バランス",
                "ai_adjustment_percent": 0.0,
                "reasoning": f"Gemini判定失敗のため補正値は0%。詳細: {e}",
            }

        mode = str(parsed.get("mode", "バランス"))
        if mode not in ("利益追求", "バランス", "回転重視"):
            mode = "バランス"
        adj = self._to_float_or_none(parsed.get("ai_adjustment_percent"))
        if adj is None:
            adj = 0.0
        adj = max(-5.0, min(5.0, float(adj)))
        reasoning = str(parsed.get("reasoning", "") or "").strip() or "根拠なし"
        return {
            "mode": mode,
            "ai_adjustment_percent": adj,
            "reasoning": reasoning,
        }

    def run_369_analysis_with_ai(
        self,
        raw_product: Dict[str, Any],
        *,
        window_days: int = 90,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.0-flash",
    ) -> Dict[str, Any]:
        """
        3-6-9ロジックの最終出力を返す。
        出力:
        - 実売推測込みドロップ数
        - 推奨運用モード
        - AI補正値（±5%）
        - 根拠
        """
        analysis = self.analyze_keepa_for_369(raw_product, window_days=window_days)
        ai_result = self.interpret_369_with_gemini(
            analysis,
            api_key=api_key,
            model_name=model_name,
        )
        return {
            "drop_count": int(analysis.get("total_effective_drop_count", 0) or 0),
            "sales_drop_count": int(analysis.get("sales_drop_count", 0) or 0),
            "inferred_sales_count": int(analysis.get("inferred_sales_count", 0) or 0),
            "mode": ai_result.get("mode", "バランス"),
            "ai_adjustment_percent": float(ai_result.get("ai_adjustment_percent", 0.0) or 0.0),
            "reasoning": str(ai_result.get("reasoning", "") or ""),
            "analysis": analysis,
        }

    def build_price_sell_probability_estimates(
        self,
        analysis: Dict[str, Any],
        *,
        lower_price: Optional[float],
        planned_price: Optional[float],
        step_count: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        解析結果から「価格ごとの売れる確率（推定）」を簡易算出する。
        厳密予測ではなく、比較のためのヒューリスティック指標。
        """
        lp = self._to_float_or_none(lower_price)
        pp = self._to_float_or_none(planned_price)
        if lp is None and pp is None:
            return []
        if lp is None:
            lp = pp
        if pp is None:
            pp = lp
        if lp is None or pp is None:
            return []
        low = min(lp, pp)
        high = max(lp, pp)
        if high <= 0:
            return []
        if abs(high - low) < 1:
            prices = [int(round(low))]
        else:
            n = max(3, min(int(step_count), 15))
            step = (high - low) / (n - 1)
            prices = [int(round(low + step * i)) for i in range(n)]

        drop_count = float(analysis.get("total_effective_drop_count", 0) or 0)
        offer_delta = analysis.get("used_offer_count_delta")
        offer_delta_f = float(offer_delta) if offer_delta is not None else 0.0
        used_avg = self._to_float_or_none(analysis.get("used_price_avg"))
        used_range = self._to_float_or_none(analysis.get("used_price_range")) or 0.0

        # ベース需要: ドロップ数が多いほど上がる（0.05〜0.95）
        base_demand = max(0.05, min(0.95, 0.15 + (drop_count / 20.0)))
        # 競合圧: 出品者増で悪化、減で改善
        competition_pressure = max(-0.25, min(0.25, offer_delta_f / 40.0))

        out: List[Dict[str, Any]] = []
        band_width = max(200.0, used_range * 0.6)
        for p in prices:
            # 価格が安いほど売れやすい（low→+0.18, high→-0.18）
            rel = 0.0
            if high > low:
                rel = (p - low) / (high - low)  # 0..1
            price_factor = (0.18 - rel * 0.36)

            market_fit = 0.0
            if used_avg is not None and used_avg > 0:
                distance = abs(p - used_avg)
                market_fit = max(-0.2, 0.14 - (distance / band_width) * 0.14)

            prob = base_demand + price_factor - competition_pressure + market_fit
            prob = max(0.01, min(0.99, prob))
            out.append(
                {
                    "price": int(p),
                    "sell_probability": round(prob, 4),
                    "sell_probability_percent": round(prob * 100.0, 1),
                }
            )
        return out




