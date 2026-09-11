#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Takeout「お気に入りの場所.csv」から未登録店舗を取り込む。

- ルートは未所属（affiliated_route_name / route_code は空）
- Places API で住所・電話・緯度経度を取得
- 店舗コードはチェーンマッピングから自動採番
- 重複判定: 店舗名（空白無視）／電話／住所／近接座標
"""

from __future__ import annotations

import csv
import re
import time
import unicodedata
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

SAME_LOCATION_RADIUS_M = 80.0

try:
    from services.google_maps_service import get_store_info_from_google
except ImportError:
    try:
        from google_maps_service import get_store_info_from_google
    except ImportError:
        get_store_info_from_google = None  # type: ignore


@dataclass
class TakeoutPlaceRow:
    title: str
    url: str = ""
    note: str = ""
    tags: str = ""
    comment: str = ""


@dataclass
class ImportSkip:
    title: str
    reason: str
    matched_store: str = ""


@dataclass
class ImportAdded:
    title: str
    store_code: str
    address: str
    phone: str
    store_id: int


@dataclass
class TakeoutImportResult:
    parsed: int = 0
    added: List[ImportAdded] = field(default_factory=list)
    skipped: List[ImportSkip] = field(default_factory=list)
    failed: List[ImportSkip] = field(default_factory=list)
    cancelled: bool = False


def normalize_store_name(name: str) -> str:
    """スペース有無・全半角ゆれを吸収した比較用店舗名。"""
    s = unicodedata.normalize("NFKC", (name or "").strip())
    s = s.lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = s.replace("・", "").replace("･", "")
    # よくある括弧注釈のゆれは残す（別館判定に使う場合がある）
    return s


def normalize_phone(phone: str) -> str:
    """数字のみの電話番号（先頭の国番号81は0に揃える）。"""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("81") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def normalize_address(address: str) -> str:
    """住所比較用（空白除去・全半角統一）。"""
    s = unicodedata.normalize("NFKC", (address or "").strip())
    s = re.sub(r"[\s\u3000]+", "", s)
    s = s.replace("日本", "")
    # 郵便番号表記ゆれ
    s = re.sub(r"〒?\d{3}-?\d{4}", "", s)
    return s


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2.0 * r * asin(sqrt(a))


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_takeout_favorites_csv(path: str | Path) -> List[TakeoutPlaceRow]:
    """Takeout お気に入り CSV を読み込む（UTF-8 / UTF-8-SIG）。"""
    file_path = Path(path)
    rows: List[TakeoutPlaceRow] = []
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            with file_path.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                # 列名ゆれ吸収
                def _col(*candidates: str) -> Optional[str]:
                    for c in candidates:
                        if c in fieldnames:
                            return c
                    return None

                title_col = _col("タイトル", "title", "Title", "名前", "name")
                url_col = _col("URL", "url", "Url")
                note_col = _col("メモ", "note", "Note")
                tags_col = _col("タグ", "tags", "Tags")
                comment_col = _col("コメント", "comment", "Comment")
                if not title_col:
                    raise ValueError(
                        "CSVに「タイトル」列が見つかりません。"
                        f"列: {', '.join(fieldnames)}"
                    )

                for raw in reader:
                    title = (raw.get(title_col) or "").strip()
                    if not title:
                        continue
                    rows.append(
                        TakeoutPlaceRow(
                            title=title,
                            url=(raw.get(url_col) or "").strip() if url_col else "",
                            note=(raw.get(note_col) or "").strip() if note_col else "",
                            tags=(raw.get(tags_col) or "").strip() if tags_col else "",
                            comment=(raw.get(comment_col) or "").strip()
                            if comment_col
                            else "",
                        )
                    )
            return rows
        except UnicodeDecodeError as e:
            last_error = e
            rows = []
            continue
    if last_error:
        raise last_error
    return rows


class _DuplicateIndex:
    """既存店舗の重複判定インデックス。"""

    def __init__(self, stores: Sequence[Dict[str, Any]]):
        self.by_name: Dict[str, Dict[str, Any]] = {}
        self.by_phone: Dict[str, Dict[str, Any]] = {}
        self.by_address: Dict[str, Dict[str, Any]] = {}
        self.coords: List[Tuple[Dict[str, Any], float, float]] = []
        for store in stores:
            name_key = normalize_store_name(str(store.get("store_name") or ""))
            if name_key and name_key not in self.by_name:
                self.by_name[name_key] = store
            phone_key = normalize_phone(str(store.get("phone") or ""))
            if phone_key and len(phone_key) >= 9 and phone_key not in self.by_phone:
                self.by_phone[phone_key] = store
            addr_key = normalize_address(str(store.get("address") or ""))
            if addr_key and len(addr_key) >= 8 and addr_key not in self.by_address:
                self.by_address[addr_key] = store
            lat = _coerce_float(store.get("latitude"))
            lng = _coerce_float(store.get("longitude"))
            if lat is not None and lng is not None:
                self.coords.append((store, lat, lng))

    def find_duplicate(
        self,
        *,
        title: str,
        address: str = "",
        phone: str = "",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        name_key = normalize_store_name(title)
        if name_key and name_key in self.by_name:
            return self.by_name[name_key], "店舗名が一致（空白・表記ゆれを無視）"

        phone_key = normalize_phone(phone)
        if phone_key and len(phone_key) >= 9 and phone_key in self.by_phone:
            return self.by_phone[phone_key], "電話番号が一致"

        addr_key = normalize_address(address)
        if addr_key and len(addr_key) >= 8 and addr_key in self.by_address:
            return self.by_address[addr_key], "住所が一致"

        if latitude is not None and longitude is not None:
            for store, lat, lng in self.coords:
                if _haversine_m(latitude, longitude, lat, lng) <= SAME_LOCATION_RADIUS_M:
                    # 同座標でもチェーンが明らかに違う併設店は別店舗として通す
                    existing_name = normalize_store_name(str(store.get("store_name") or ""))
                    if name_key and existing_name:
                        # 先頭のチェーンっぽい部分が大きく違う場合は併設の可能性
                        if not _likely_same_brand(name_key, existing_name):
                            continue
                    return store, f"座標が近い（{SAME_LOCATION_RADIUS_M:.0f}m以内・同系統）"
        return None

    def register(self, store: Dict[str, Any]) -> None:
        """インポート中に追加した店舗も以降の重複判定に使う。"""
        name_key = normalize_store_name(str(store.get("store_name") or ""))
        if name_key:
            self.by_name[name_key] = store
        phone_key = normalize_phone(str(store.get("phone") or ""))
        if phone_key and len(phone_key) >= 9:
            self.by_phone[phone_key] = store
        addr_key = normalize_address(str(store.get("address") or ""))
        if addr_key and len(addr_key) >= 8:
            self.by_address[addr_key] = store
        lat = _coerce_float(store.get("latitude"))
        lng = _coerce_float(store.get("longitude"))
        if lat is not None and lng is not None:
            self.coords.append((store, lat, lng))


def _likely_same_brand(a: str, b: str) -> bool:
    """正規化名の先頭部分が似ていれば同系統とみなす。"""
    if not a or not b:
        return True
    if a == b:
        return True
    # 短い方の先頭6〜10文字
    n = min(10, max(6, min(len(a), len(b))))
    return a[:n] == b[:n] or a in b or b in a


def _resolve_store_code(db: Any, store_name: str) -> str:
    code = db.get_next_store_code_from_store_name(store_name)
    if code:
        return code
    default_prefix = db.find_default_chain_code_for_others()
    if default_prefix:
        code = db.get_next_store_code_for_prefix(default_prefix)
        if code:
            return code
    return ""


def import_takeout_favorites(
    db: Any,
    csv_path: str | Path,
    *,
    fetch_info: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    progress_callback: Optional[Callable[[int, int, str], bool]] = None,
    api_delay_sec: float = 0.25,
    dry_run: bool = False,
) -> TakeoutImportResult:
    """
    Takeout CSV から未登録店舗を未所属で取り込む。

    progress_callback(current, total, label) -> continue?
    """
    result = TakeoutImportResult()
    places = parse_takeout_favorites_csv(csv_path)
    result.parsed = len(places)
    if not places:
        return result

    fetcher = fetch_info or get_store_info_from_google
    index = _DuplicateIndex(db.list_stores())
    # 同一CSV内の重複タイトルも抑止
    seen_titles: Set[str] = set()

    total = len(places)
    for i, place in enumerate(places):
        if progress_callback is not None:
            cont = progress_callback(i, total, place.title)
            if cont is False:
                result.cancelled = True
                break

        name_key = normalize_store_name(place.title)
        if not name_key:
            continue
        if name_key in seen_titles:
            result.skipped.append(
                ImportSkip(title=place.title, reason="CSV内で重複タイトル")
            )
            continue
        seen_titles.add(name_key)

        # 名前だけで既存判定（API節約）
        dup = index.find_duplicate(title=place.title)
        if dup:
            store, reason = dup
            result.skipped.append(
                ImportSkip(
                    title=place.title,
                    reason=reason,
                    matched_store=str(store.get("store_name") or ""),
                )
            )
            continue

        info: Optional[Dict[str, Any]] = None
        if fetcher is not None:
            try:
                info = fetcher(place.title)
            except Exception as e:
                result.failed.append(
                    ImportSkip(title=place.title, reason=f"API取得失敗: {e}")
                )
                continue
            if api_delay_sec > 0:
                time.sleep(api_delay_sec)

        address = str((info or {}).get("address") or "")
        phone = str((info or {}).get("phone") or "")
        lat = _coerce_float((info or {}).get("latitude"))
        lng = _coerce_float((info or {}).get("longitude"))

        if info:
            dup = index.find_duplicate(
                title=place.title,
                address=address,
                phone=phone,
                latitude=lat,
                longitude=lng,
            )
            if dup:
                store, reason = dup
                result.skipped.append(
                    ImportSkip(
                        title=place.title,
                        reason=reason,
                        matched_store=str(store.get("store_name") or ""),
                    )
                )
                continue
        elif fetcher is not None:
            # APIキーはあるがヒットなし → 名前のみで未所属登録も可能だが、
            # 住所なしだと重複判定が弱いので失敗扱いにする
            result.failed.append(
                ImportSkip(title=place.title, reason="Google Maps で店舗情報が見つからない")
            )
            continue

        store_code = _resolve_store_code(db, place.title)
        store_data: Dict[str, Any] = {
            "store_name": place.title,
            "store_code": store_code or None,
            "affiliated_route_name": None,
            "route_code": None,
            "supplier_code": None,
            "address": address,
            "phone": phone,
            "custom_fields": {},
        }
        if lat is not None and lng is not None:
            store_data["latitude"] = lat
            store_data["longitude"] = lng
        if place.note or place.comment:
            store_data["notes"] = "\n".join(
                x for x in [place.note, place.comment] if x
            )

        if dry_run:
            fake_id = -(len(result.added) + 1)
            store_data["id"] = fake_id
            index.register(store_data)
            result.added.append(
                ImportAdded(
                    title=place.title,
                    store_code=store_code,
                    address=address,
                    phone=phone,
                    store_id=fake_id,
                )
            )
            continue

        try:
            new_id = db.add_store(store_data)
            store_data["id"] = new_id
            index.register(store_data)
            result.added.append(
                ImportAdded(
                    title=place.title,
                    store_code=store_code,
                    address=address,
                    phone=phone,
                    store_id=int(new_id),
                )
            )
        except Exception as e:
            result.failed.append(
                ImportSkip(title=place.title, reason=f"DB保存失敗: {e}")
            )

    if progress_callback is not None and not result.cancelled:
        progress_callback(total, total, "完了")

    return result
