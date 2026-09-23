# -*- coding: utf-8 -*-
"""メルカリ商品URLから証憑3枚を、インストール済みChromeで撮る。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Sequence

_ITEM_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:jp\.)?mercari\.com/item/(m\d{6,})",
    re.IGNORECASE,
)


class MercariLoginRequired(Exception):
    """ログイン画面なので、人がログインするまで止める。"""


def mercari_chrome_profile_dir() -> Path:
    """撮影用Chromeのプロフィール。いつものChromeとは別の窓になる。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / "HIRIO" / "mercari_chrome"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_mercari_item_url(value: object) -> str:
    """出品URLからメルカリ商品ページのURLを取り出す。それ以外は空。"""
    text = str(value or "").strip()
    if not text or text.lower() in ("nan", "none"):
        return ""
    match = _ITEM_URL_RE.search(text)
    if not match:
        return ""
    return f"https://jp.mercari.com/item/{match.group(1)}"


def looks_like_mercari_login(url: str, body_text: str = "") -> bool:
    """ログイン画面かどうか。商品ページに『ログイン』の文字があるだけでは判定しない。"""
    current = (url or "").lower()
    if "accounts.mercari.com" in current or "/login" in current or "signin" in current:
        return True
    text = body_text or ""
    if "パスワード" in text and "ログイン" in text and "取引画面を表示する" not in text:
        return True
    return False


def _page_needs_login(page) -> bool:
    try:
        if looks_like_mercari_login(page.url or "", ""):
            return True
    except Exception:
        return False
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def capture_mercari_item_shots(page, url: str, out_dir: Path) -> List[str]:
    """商品ページ上・説明・取引画面の3枚を保存する。ログイン画面なら例外。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1200)
    if _page_needs_login(page):
        raise MercariLoginRequired()

    listing = out_dir / "01_listing.png"
    desc = out_dir / "02_listing_desc.png"
    transaction = out_dir / "03_transaction.png"
    page.screenshot(path=str(listing), full_page=False)

    try:
        page.get_by_text("商品の説明").first.scroll_into_view_if_needed(timeout=8000)
        page.wait_for_timeout(600)
    except Exception:
        try:
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(600)
        except Exception:
            pass
    if _page_needs_login(page):
        raise MercariLoginRequired()
    page.screenshot(path=str(desc), full_page=False)

    button = page.get_by_text("取引画面を表示する").first
    button.scroll_into_view_if_needed(timeout=8000)
    button.click(timeout=8000)
    page.wait_for_timeout(1500)
    if _page_needs_login(page):
        raise MercariLoginRequired()
    try:
        page.get_by_text("購入日時").first.wait_for(timeout=15000)
    except Exception as exc:
        if _page_needs_login(page):
            raise MercariLoginRequired() from exc
        raise RuntimeError("取引画面を開けませんでした。購入者としてログインしているか確認してください。") from exc
    page.screenshot(path=str(transaction), full_page=False)
    return [str(listing), str(desc), str(transaction)]


def open_mercari_chrome(playwright, profile_dir: Optional[Path] = None):
    """インストール済みのChromeを、撮影用プロフィールで開く。"""
    folder = profile_dir or mercari_chrome_profile_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(folder),
        channel="chrome",
        headless=False,
        viewport={"width": 1280, "height": 860},
        locale="ja-JP",
        args=["--disable-blink-features=AutomationControlled"],
    )


def first_page(context):
    pages: Sequence = getattr(context, "pages", None) or []
    if pages:
        return pages[0]
    return context.new_page()
