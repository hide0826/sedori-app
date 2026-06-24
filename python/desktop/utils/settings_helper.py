# -*- coding: utf-8 -*-
"""
設定ヘルパー

アプリ全体で参照する設定（PRO版フラグなど）を一元管理します。
"""

from PySide6.QtCore import QSettings


def _settings():
    """QSettings の共通インスタンスを返す（HIRIO DesktopApp）"""
    return QSettings("HIRIO", "DesktopApp")


def get_amazon_seller_id() -> str:
    """
    設定タブ（詳細設定）で保存した自店の Amazon セラーID（マーチャントID）を返します。
    未設定時は空文字です。Keepa の offer sellerId などと照合する用途向け。
    """
    v = _settings().value("amazon/seller_id", "") or ""
    return str(v).strip()


DEFAULT_PRICETAR_LISTING_URL = "https://jp3.pricetar.com/seller/product/csvwarehousing"
DEFAULT_PRICETAR_REPRICING_URL = "https://jp3.pricetar.com/seller/product/csvproductedit"


def get_pricetar_listing_url() -> str:
    """
    設定タブ（詳細設定 → プライスター）の CSV出品（入庫）URL を返します。
    """
    url = str(
        _settings().value("pricetar/listing_url", DEFAULT_PRICETAR_LISTING_URL)
        or DEFAULT_PRICETAR_LISTING_URL
    ).strip()
    return url or DEFAULT_PRICETAR_LISTING_URL


def get_pricetar_repricing_url() -> str:
    """
    設定タブ（詳細設定 → プライスター）の CSV価格改定（在庫編集）URL を返します。
    """
    url = str(
        _settings().value("pricetar/repricing_url", DEFAULT_PRICETAR_REPRICING_URL)
        or DEFAULT_PRICETAR_REPRICING_URL
    ).strip()
    return url or DEFAULT_PRICETAR_REPRICING_URL


DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL = (
    "https://sellercentral-japan.amazon.com/imaging/upload"
)
DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL = (
    "https://sellercentral-japan.amazon.com/product-search/bulk"
)


def get_amazon_fba_simulator_url() -> str:
    """
    設定タブ（詳細設定 → Amazon）の FBA料金シミュレーターURL を返します。
    未設定時は Seller Central の既定URLです。
    """
    default_url = "https://sellercentral.amazon.co.jp/revcalpublic?lang=ja_JP"
    url = str(_settings().value("amazon/fba_simulator_url", default_url) or default_url).strip()
    return url or default_url


def get_amazon_bulk_image_upload_url() -> str:
    """設定タブ（詳細設定 → Amazon）の一括商品画像アップロードURL。"""
    url = str(
        _settings().value("amazon/bulk_image_upload_url", DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL)
        or DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL
    ).strip()
    return url or DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL


def get_amazon_inventory_loader_upload_url() -> str:
    """設定タブ（詳細設定 → Amazon）の出品ファイル(L)アップロードURL。"""
    url = str(
        _settings().value(
            "amazon/inventory_loader_upload_url",
            DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
        )
        or DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL
    ).strip()
    return url or DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL


def is_pro_enabled() -> bool:
    """
    PRO版が有効かどうかを返します。
    設定タブの「PRO版を有効にする」スイッチで変更されます。
    今後のPRO機能はこのフラグを前提に実装してください。
    開発段階ではデフォルトでTrue（ON）です。
    """
    return _settings().value("pro/enabled", True, type=bool)


def is_recording_mode() -> bool:
    """デモモードが有効か。ON時は仮想DBのみに読み書きする。"""
    return _settings().value("recording/enabled", False, type=bool)


def set_recording_mode_enabled_flag(enabled: bool) -> None:
    _settings().setValue("recording/enabled", bool(enabled))
