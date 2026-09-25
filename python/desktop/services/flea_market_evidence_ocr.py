#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ取引画面スクショの OCR テキストから取引情報を切り出す。"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

MERCARI_ITEM_URL_PREFIX = "https://jp.mercari.com/item/"

_TRANSACTION_HINTS = (
    "購入日時",
    "商品ID",
    "取引が完了",
    "取引完了",
    "取引画面",
)

_SELLER_SKIP_FRAGMENTS = (
    "出品者情報",
    "本人確認",
    "24時間",
    "評価を変更",
    "取引が完了",
    "取引完了",
    "コピーする",
    "ゆうゆうメルカリ便",
    "ゆうパケット",
    "でお届け",
    "らくらくメルカリ便",
    "専用資材",
    "匿名配送",
    "出品者負担",
    "出品者レベル",
    "送料",
    "サイズ",
    "厚さ",
    "重さ",
    "kg以内",
    "cm以内",
)

_DATE_LABEL_RE = re.compile(
    r"購入日時\s*[:：]?\s*"
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
    r"(?:\s+(\d{1,2})\s*[:：時]\s*(\d{1,2}))?",
)

_ITEM_ID_LABELED_RE = re.compile(
    r"商品ID\s*[:：]?\s*(m\d{8,16})",
    re.IGNORECASE,
)
_ITEM_ID_BARE_RE = re.compile(r"\b(m\d{8,16})\b", re.IGNORECASE)

_PRICE_RE = re.compile(
    r"商品代金\s*[:：]?\s*[¥￥]?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
)


@dataclass
class FleaTransactionOcrResult:
    """取引画面 OCR の切り出し結果。取れない項目は空。"""

    purchase_datetime: str = ""
    item_id: str = ""
    listing_url: str = ""
    seller_name: str = ""
    item_price: Optional[int] = None
    is_transaction_page: bool = False
    raw_text: str = ""
    notes: List[str] = field(default_factory=list)

    def has_core_fields(self) -> bool:
        return bool(self.purchase_datetime or self.item_id)


def normalize_ocr_text(text: str) -> str:
    """全角英数・空白を半角にそろえる。"""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    return normalized.replace("\r\n", "\n").replace("\r", "\n")


def looks_like_transaction_page(text: str) -> bool:
    """取引画面らしいキーワードが十分あるか。"""
    n = normalize_ocr_text(text)
    if not n:
        return False
    hits = sum(1 for hint in _TRANSACTION_HINTS if hint in n)
    return hits >= 2


def listing_url_from_item_id(item_id: str) -> str:
    """メルカリ商品IDから出品URLを組み立てる。"""
    item = (item_id or "").strip()
    if not item:
        return ""
    if item.lower().startswith("m") and item[1:].isdigit():
        return f"{MERCARI_ITEM_URL_PREFIX}{item}"
    return ""


def parse_transaction_ocr_text(text: str) -> FleaTransactionOcrResult:
    """OCR全文から購入日時・商品ID・出品者・代金を取り出す。"""
    raw = text or ""
    n = normalize_ocr_text(raw)
    result = FleaTransactionOcrResult(
        raw_text=n,
        is_transaction_page=looks_like_transaction_page(n),
    )
    if not n.strip():
        return result

    result.purchase_datetime = _extract_purchase_datetime(n)
    result.item_id = _extract_item_id(n)
    result.listing_url = listing_url_from_item_id(result.item_id)
    result.seller_name = _extract_seller_name(n)
    result.item_price = _extract_item_price(n)
    return result


def pick_transaction_text(texts: Sequence[str]) -> Optional[str]:
    """複数枚のOCR結果から取引画面らしいものを選ぶ。"""
    scored: List[tuple] = []
    for text in texts:
        n = normalize_ocr_text(text)
        if not n.strip():
            continue
        hits = sum(1 for hint in _TRANSACTION_HINTS if hint in n)
        scored.append((hits, n))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best_hits, best_text = scored[0]
    if best_hits >= 1:
        return best_text
    return None


def _extract_purchase_datetime(text: str) -> str:
    m = _DATE_LABEL_RE.search(text)
    if not m:
        return ""
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = m.group(4)
    minute = m.group(5)
    date_part = f"{year:04d}-{month:02d}-{day:02d}"
    if hour is None or minute is None:
        return date_part
    return f"{date_part} {int(hour):02d}:{int(minute):02d}"


def _extract_item_id(text: str) -> str:
    m = _ITEM_ID_LABELED_RE.search(text)
    if m:
        return m.group(1)
    m = _ITEM_ID_BARE_RE.search(text)
    return m.group(1) if m else ""


def _extract_item_price(text: str) -> Optional[int]:
    m = _PRICE_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _extract_seller_name(text: str) -> str:
    lines = [ln.strip() for ln in text.split("\n")]
    for i, line in enumerate(lines):
        if "出品者情報" not in line:
            continue
        # 同じ行に名前が続く場合
        rest = line.split("出品者情報", 1)[-1].strip(" :：")
        if rest and not _is_seller_skip_line(rest):
            return rest
        for follow in lines[i + 1 : i + 6]:
            if not follow:
                continue
            if _is_seller_skip_line(follow):
                continue
            if follow.startswith("¥") or follow.startswith("￥"):
                continue
            return follow
    return ""


def _is_seller_skip_line(line: str) -> bool:
    return any(frag in line for frag in _SELLER_SKIP_FRAGMENTS)


def is_delivery_label_name(name: str) -> bool:
    """配送方法の文言を、出品者名とみなさない。"""
    text = str(name or "").strip()
    if not text:
        return False
    return _is_seller_skip_line(text)
