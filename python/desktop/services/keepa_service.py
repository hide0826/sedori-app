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
from typing import Optional, Dict, Any

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








