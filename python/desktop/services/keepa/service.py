#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KeepaService 本体（API クライアント・fetch）。"""

from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple, Literal
import time

from PySide6.QtCore import QSettings

from .models import IMAGE_BASE_URL, KeepaProductInfo
from .price_helpers import KeepaPriceHelpersMixin
from .offer_helpers import KeepaOfferHelpersMixin
from .analysis_369 import Keepa369AnalysisMixin


class KeepaService(
    KeepaPriceHelpersMixin,
    KeepaOfferHelpersMixin,
    Keepa369AnalysisMixin,
):
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
