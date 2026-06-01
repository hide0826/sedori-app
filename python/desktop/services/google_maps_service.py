#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Maps APIを使用した店舗情報取得サービス

店舗名から住所・電話番号を取得する機能を提供

注意:
- `requests`ライブラリが必要です（通常は標準でインストール済み）
- APIキーは QSettings("HIRIO", "DesktopApp") の "ocr/gemini_api_key" から読み込みます。
  （Gemini APIキーにMaps APIの権限を付与したものを使用）
- 新しいPlaces API (New) を使用します
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QSettings

try:
    import requests
except ImportError:
    requests = None

_PREFECTURE_RE = re.compile(r"(北海道|[^\s,，、]+?[都道府県])")
_CITY_RE = re.compile(r"([^\s,，、]+?市)")
_WARD_RE = re.compile(r"([^\s,，、]+?区)")
_POSTAL_RE = re.compile(r"(\d{3}-\d{4})")
_TRAILING_COUNTRY_RE = re.compile(r"[\s,，、]*(?:日本|Japan)\s*$", re.IGNORECASE)


def _component_text(components: List[Dict[str, Any]], *types: str) -> str:
    """addressComponents から最初に一致した種別のテキストを返す。"""
    for comp in components or []:
        comp_types = comp.get("types") or []
        if any(t in comp_types for t in types):
            text = (comp.get("longText") or comp.get("shortText") or "").strip()
            if text:
                return text
    return ""


def _strip_country_prefix(address: str) -> str:
    s = (address or "").strip()
    for prefix in ("日本、", "日本,", "日本，"):
        if s.startswith(prefix):
            s = s[len(prefix) :].strip()
            break
    return _TRAILING_COUNTRY_RE.sub("", s).strip()


def format_address_from_postal_address(postal_address: Optional[Dict[str, Any]]) -> str:
    """postalAddress から 〒郵便番号 都道府県市区町村… 形式を組み立てる。"""
    if not postal_address:
        return ""

    postal = (postal_address.get("postalCode") or "").strip()
    admin = (postal_address.get("administrativeArea") or "").strip()
    locality = (postal_address.get("locality") or "").strip()
    sublocality = (postal_address.get("sublocality") or "").strip()
    lines = [
        str(ln).strip()
        for ln in (postal_address.get("addressLines") or [])
        if ln and str(ln).strip()
    ]

    body = admin + locality
    if sublocality and sublocality not in body:
        body += sublocality
    for line in lines:
        if line not in body:
            body += line

    body = body.strip()
    if not body and not postal:
        return ""

    if postal:
        return f"〒{postal} {body}".strip()
    return body


def format_address_from_components(components: List[Dict[str, Any]]) -> str:
    """addressComponents から日本式住所を組み立てる（店舗名は含めない）。"""
    if not components:
        return ""

    postal = _component_text(components, "postal_code")
    prefecture = _component_text(
        components, "administrative_area_level_1", "administrative_area"
    )
    city = _component_text(
        components, "locality", "administrative_area_level_2"
    )
    ward = _component_text(
        components,
        "sublocality_level_1",
        "sublocality",
        "administrative_area_level_3",
    )
    sub2 = _component_text(components, "sublocality_level_2")
    sub3 = _component_text(components, "sublocality_level_3")
    sub4 = _component_text(components, "sublocality_level_4")
    route = _component_text(components, "route")
    street_number = _component_text(components, "street_number")
    premise = _component_text(components, "premise")
    floor = _component_text(components, "floor")

    detail_parts: List[str] = []
    for part in (sub2, sub3, sub4, route, street_number, premise, floor):
        if part and part not in "".join(detail_parts):
            detail_parts.append(part)

    body = prefecture + city + ward + "".join(detail_parts)
    body = body.strip()
    if not body and not postal:
        return ""

    if postal:
        return f"〒{postal} {body}".strip()
    return body


def _remove_last_match(pattern: re.Pattern, text: str) -> tuple[str, str]:
    """文字列中で最後に現れるパターンを取り除き、(一致文字列, 残り) を返す。"""
    matches = list(pattern.finditer(text))
    if not matches:
        return "", text
    m = matches[-1]
    return m.group(1), (text[: m.start()] + text[m.end() :]).strip()


def _parse_trailing_city_ward(text: str) -> tuple[str, str, str]:
    """末尾の 市・区 を解析し、(区, 市, 残り) を返す。"""
    s = (text or "").strip()
    if not s.endswith("市"):
        return "", "", s

    city = ""
    before = s
    for length in range(3, 14):
        if length > len(s):
            break
        candidate = s[-length:]
        if not candidate.endswith("市"):
            continue
        if re.fullmatch(r"[一-龥ぁ-んァ-ヶー々]{1,5}市", candidate):
            city = candidate
            before = s[:-length].strip()
            break

    if not city:
        return "", "", s

    ward = ""
    if city.endswith("市") and len(city) > 1:
        ward_candidate = f"{city[:-1]}区"
        if before.endswith(ward_candidate):
            ward = ward_candidate
            before = before[: -len(ward_candidate)].strip()

    return ward, city, before


def _normalize_address_detail(detail: str) -> str:
    """町名・丁目・番地を日本式の並びに整える。"""
    s = (detail or "").strip()
    if not s:
        return ""

    s = re.sub(r"(?i)^(\d+)\s*[fFlL]\s*", "", s).strip()
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", " ", s).strip()

    chome_m = re.search(
        r"(\d+)\s*丁目\s*[-\s]*(\d+)\s*[-\s]*(\d+)", s
    )
    town_m = re.search(r"([一-龥ぁ-んァ-ヶー々]+)\s*$", s)
    town = town_m.group(1) if town_m else ""
    if chome_m:
        block = f"{chome_m.group(1)}丁目{chome_m.group(2)}-{chome_m.group(3)}"
        if town:
            return f"{town}{block}"
        return block

    return s.replace(" ", "")


def _extract_parts_forward_order(s: str) -> Dict[str, str]:
    """都道府県→市→区→番地 の順で書かれた住所を解析する。"""
    rest = (s or "").strip()
    prefecture = ""
    pm = _PREFECTURE_RE.match(rest)
    if pm:
        prefecture = pm.group(1)
        rest = rest[pm.end() :].strip()

    city = ""
    cm = re.match(r"([一-龥ぁ-んァ-ヶー々]{1,5}市)", rest)
    if cm:
        city = cm.group(1)
        rest = rest[cm.end() :].strip()

    ward = ""
    wm = re.match(r"([一-龥ぁ-んァ-ヶー々]{1,8}区)", rest)
    if wm:
        ward = wm.group(1)
        rest = rest[wm.end() :].strip()

    return {
        "postal": "",
        "prefecture": prefecture,
        "city": city,
        "ward": ward,
        "detail": rest.replace(" ", ""),
    }


def _extract_parts_from_free_text(text: str) -> Dict[str, str]:
    """逆順などの formattedAddress から都道府県・市区・残りを抽出する。"""
    s = _strip_country_prefix(text)
    postal = ""
    m = _POSTAL_RE.search(s)
    if m:
        postal = m.group(1)
        s = (s[: m.start()] + s[m.end() :]).strip()

    s = _TRAILING_COUNTRY_RE.sub("", s).strip()

    if "," in s or "，" in s:
        chunks = re.split(r"[,，]", s)
        if len(chunks) >= 2:
            head = chunks[0].strip()
            tail = ",".join(chunks[1:]).strip()
            if head and not re.search(r"[都道府県市区町村丁目]", head):
                s = tail

    if _PREFECTURE_RE.match(s):
        parts = _extract_parts_forward_order(s)
        parts["postal"] = postal
        return parts

    prefecture, s = _remove_last_match(_PREFECTURE_RE, s)
    ward, city, s = _parse_trailing_city_ward(s)
    detail = _normalize_address_detail(s)

    return {
        "postal": postal,
        "prefecture": prefecture,
        "city": city,
        "ward": ward,
        "detail": detail,
    }


def _format_from_parts(parts: Dict[str, str]) -> str:
    body = (
        (parts.get("prefecture") or "")
        + (parts.get("city") or "")
        + (parts.get("ward") or "")
        + (parts.get("detail") or "")
    ).strip()
    postal = (parts.get("postal") or "").strip()
    if not body and not postal:
        return ""
    if postal:
        return f"〒{postal} {body}".strip()
    return body


def is_nonstandard_japanese_address(address: Optional[str]) -> bool:
    """他行の 〒先頭 形式と異なる住所かどうか。"""
    s = (address or "").strip()
    if not s:
        return False
    if s.startswith("〒"):
        return False
    if re.search(r"(日本|Japan)\s*$", s, re.IGNORECASE):
        return True
    if s.startswith("日本、") or s.startswith("日本,"):
        return True
    if _POSTAL_RE.search(s) and not s.startswith("〒"):
        if _PREFECTURE_RE.search(s):
            return True
    return False


def normalize_japanese_address(
    formatted: str = "",
    postal_address: Optional[Dict[str, Any]] = None,
    components: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Google Maps の住所を 〒郵便番号 都道府県市区町村… 形式に統一する。

    postalAddress / addressComponents を優先し、失敗時は formattedAddress をヒューリスティック整形。
    """
    for formatter, arg in (
        (format_address_from_postal_address, postal_address),
        (format_address_from_components, components or []),
    ):
        if arg:
            try:
                if formatter is format_address_from_components:
                    normalized = formatter(arg)  # type: ignore[arg-type]
                else:
                    normalized = formatter(arg)  # type: ignore[arg-type]
            except Exception:
                normalized = ""
            if normalized:
                return normalized

    raw = (formatted or "").strip()
    if not raw:
        return ""

    cleaned = _strip_country_prefix(raw)
    if cleaned.startswith("〒"):
        return cleaned

    parts = _extract_parts_from_free_text(raw)
    rebuilt = _format_from_parts(parts)
    if rebuilt:
        return rebuilt

    return cleaned


def normalize_stored_japanese_address(address: Optional[str]) -> str:
    """DB保存済みの住所を日本式に整形（APIなし）。"""
    raw = (address or "").strip()
    if not raw:
        return ""
    if not is_nonstandard_japanese_address(raw):
        return _strip_country_prefix(raw) if raw.startswith("日本") else raw
    return normalize_japanese_address(formatted=raw) or _strip_country_prefix(raw)


def _resolve_api_key(api_key: Optional[str]) -> Optional[str]:
    if api_key:
        return api_key
    settings = QSettings("HIRIO", "DesktopApp")
    api_key = settings.value("ocr/gemini_api_key", "") or None
    if not api_key:
        api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("Maps_API_KEY") or None
    return api_key


def get_store_info_from_google(
    store_name: str,
    api_key: Optional[str] = None,
    language_code: str = "ja",
) -> Optional[Dict[str, str]]:
    """
    店舗名からGoogle Maps APIを使用して住所・電話番号を取得

    Args:
        store_name: 店舗名（例: "BOOKOFF SUPER BAZAAR 14号千葉幕張店"）
        api_key: APIキー（省略時は設定から取得）
        language_code: 言語コード（デフォルト: 'ja' 日本語）

    Returns:
        辞書型 {'address': '...', 'phone': '...'} または None
    """
    if requests is None:
        error_msg = (
            "警告: requestsライブラリがインストールされていません。\n"
            "インストール方法: pip install requests"
        )
        print(error_msg)
        return None

    api_key = _resolve_api_key(api_key)
    if not api_key:
        print("警告: Google Maps APIキーが設定されていません。")
        print("設定タブの「OCR設定」でGemini APIキーを設定してください。")
        print("（Gemini APIキーにMaps APIの権限を付与してください）")
        return None

    try:
        search_url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
        }

        search_payload = {
            "textQuery": store_name,
            "maxResultCount": 1,
            "languageCode": language_code,
            "regionCode": "JP",
        }

        search_response = requests.post(
            search_url, headers=headers, json=search_payload, timeout=30
        )
        search_response.raise_for_status()
        search_data = search_response.json()

        if not search_data.get("places") or len(search_data["places"]) == 0:
            print(f"店舗が見つかりませんでした: {store_name}")
            return None

        place = search_data["places"][0]
        place_id = place.get("id")

        if not place_id:
            print(f"店舗IDが取得できませんでした: {store_name}")
            return None

        details_url = f"https://places.googleapis.com/v1/places/{place_id}"
        details_headers = {
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "formattedAddress,addressComponents,postalAddress,"
                "nationalPhoneNumber,internationalPhoneNumber"
            ),
        }

        details_params = {
            "languageCode": language_code,
            "regionCode": "JP",
        }

        details_response = requests.get(
            details_url,
            headers=details_headers,
            params=details_params,
            timeout=30,
        )
        details_response.raise_for_status()
        details_data = details_response.json()

        formatted = details_data.get("formattedAddress", "") or ""
        components = details_data.get("addressComponents") or []
        postal_address = details_data.get("postalAddress")
        address = normalize_japanese_address(
            formatted=formatted,
            postal_address=postal_address,
            components=components,
        )
        phone = (
            details_data.get("nationalPhoneNumber")
            or details_data.get("internationalPhoneNumber")
            or ""
        )

        if not address and not phone:
            return None

        return {
            "address": address,
            "phone": phone,
        }

    except requests.exceptions.RequestException as e:
        print(f"店舗情報の取得エラー ({store_name}): APIリクエストエラー - {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                error_data = e.response.json()
                print(f"エラー詳細: {error_data}")
            except Exception:
                print(f"エラーレスポンス: {e.response.text}")
        return None
    except Exception as e:
        print(f"店舗情報の取得エラー ({store_name}): {e}")
        return None


def _stores_needing_address_recovery(store_db) -> List[Dict[str, Any]]:
    """住所の形式修正が必要な店舗を抽出する。"""
    conn = store_db._get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, store_name, address, phone
        FROM stores
        WHERE address IS NOT NULL AND TRIM(address) != ''
        """
    )
    results: List[Dict[str, Any]] = []
    for row in cursor.fetchall():
        address = row["address"] or ""
        if is_nonstandard_japanese_address(address):
            results.append(
                {
                    "id": row["id"],
                    "store_name": row["store_name"],
                    "address": address,
                    "phone": row["phone"],
                }
            )
    return results


def recover_store_info_with_japanese(
    store_db, api_key: Optional[str] = None
) -> Dict[str, int]:
    """
    非標準の住所形式を持つ店舗を日本語で再取得、またはローカル整形で更新する。

    対象:
    - 末尾が Japan / 日本
    - 〒 なしで郵便番号・都道府県を含む逆順っぽい住所
    - 先頭が「日本、」の住所
    """
    api_key = _resolve_api_key(api_key)
    if not api_key:
        print("警告: Google Maps APIキーが設定されていません。")
        return {"total": 0, "updated": 0, "failed": 0}

    stores_to_recover = _stores_needing_address_recovery(store_db)
    total = len(stores_to_recover)
    updated = 0
    failed = 0

    print(f"リカバリー対象: {total}件の店舗が見つかりました")

    for store in stores_to_recover:
        store_id = store["id"]
        store_name = store["store_name"]
        old_address = store.get("address") or ""

        print(f"処理中: {store_name} (ID: {store_id})")

        new_address = ""
        new_phone = store.get("phone") or ""

        if store_name:
            info = get_store_info_from_google(
                store_name, api_key=api_key, language_code="ja"
            )
            if info:
                new_address = info.get("address") or ""
                if info.get("phone"):
                    new_phone = info["phone"]

        if not new_address:
            new_address = normalize_stored_japanese_address(old_address)

        if not new_address or new_address == old_address:
            if not new_address:
                print("  整形結果なし")
                failed += 1
            else:
                print("  変更なし（スキップ）")
            continue

        try:
            existing_store = store_db.get_store(store_id)
            if not existing_store:
                print(f"  エラー: 店舗ID {store_id} が見つかりません")
                failed += 1
                continue
            existing_store["address"] = new_address
            if new_phone:
                existing_store["phone"] = new_phone
            store_db.update_store(store_id, existing_store)
            updated += 1
            print(f"  更新成功: 住所={new_address[:60]}...")
        except Exception as e:
            print(f"  更新エラー: {e}")
            failed += 1

    return {
        "total": total,
        "updated": updated,
        "failed": failed,
    }
