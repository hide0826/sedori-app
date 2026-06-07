#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗訪問リストから Google Maps ルート URL を生成するサービス。

- ルート1の始点: 現在地 (Current+Location)
- ルート2以降の始点: 前ルートの最終店舗
- 1 URL あたり最大 9 店舗（始点含め Google Maps の 10 地点上限）
- 同一緯度経度の併設店舗は 1 地点にまとめる
- Maps Embed API 用 URL も併せて生成（API キー指定時）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode

COORD_PRECISION = 5
MAX_STOPS_PER_SEGMENT = 9
ORIGIN_LABEL = "Current+Location"
EMBED_ORIGIN_CURRENT = "Current Location"


@dataclass
class SkippedDuplicateStore:
    """同座標のためスキップされた店舗"""

    store_code: str
    store_name: str
    kept_store_code: str
    kept_store_name: str


@dataclass
class RouteMapSegment:
    """分割された 1 本のルート URL"""

    index: int
    url: str
    store_codes: List[str] = field(default_factory=list)
    store_names: List[str] = field(default_factory=list)
    embed_url: str = ""


@dataclass
class RouteMapGenerationResult:
    """URL 生成結果"""

    segments: List[RouteMapSegment] = field(default_factory=list)
    skipped_duplicates: List[SkippedDuplicateStore] = field(default_factory=list)
    missing_coordinates: List[Dict[str, str]] = field(default_factory=list)
    store_code_to_segment: Dict[str, int] = field(default_factory=dict)


try:
    from services.google_maps_service import resolve_maps_api_key
except ImportError:
    try:
        from google_maps_service import resolve_maps_api_key
    except ImportError:
        resolve_maps_api_key = None  # type: ignore


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def location_key(store: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    lat = _coerce_float(store.get("latitude"))
    lng = _coerce_float(store.get("longitude"))
    if lat is None or lng is None:
        return None
    return (round(lat, COORD_PRECISION), round(lng, COORD_PRECISION))


def dedupe_stores_by_coordinates(
    stores: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[SkippedDuplicateStore]]:
    """訪問順を保ちつつ、同一座標の店舗を先頭 1 件にまとめる。"""
    unique: List[Dict[str, Any]] = []
    skipped: List[SkippedDuplicateStore] = []
    seen: Dict[Tuple[float, float], Dict[str, Any]] = {}

    for store in stores:
        key = location_key(store)
        if key is None:
            unique.append(dict(store))
            continue
        if key in seen:
            kept = seen[key]
            skipped.append(
                SkippedDuplicateStore(
                    store_code=str(store.get("store_code") or store.get("supplier_code") or ""),
                    store_name=str(store.get("store_name") or ""),
                    kept_store_code=str(kept.get("store_code") or kept.get("supplier_code") or ""),
                    kept_store_name=str(kept.get("store_name") or ""),
                )
            )
            continue
        kept_store = dict(store)
        seen[key] = kept_store
        unique.append(kept_store)

    return unique, skipped


def stop_to_path_segment(store: Dict[str, Any]) -> str:
    lat = _coerce_float(store.get("latitude"))
    lng = _coerce_float(store.get("longitude"))
    if lat is not None and lng is not None:
        return f"{lat},{lng}"
    label = (store.get("address") or store.get("store_name") or "").strip()
    if not label:
        code = store.get("store_code") or store.get("supplier_code") or "?"
        return quote(str(code))
    return quote(label)


def stop_to_embed_location(store: Dict[str, Any]) -> str:
    """Embed API 用の origin / destination / waypoint 文字列（未エンコード）"""
    lat = _coerce_float(store.get("latitude"))
    lng = _coerce_float(store.get("longitude"))
    if lat is not None and lng is not None:
        return f"{lat},{lng}"
    label = (store.get("address") or store.get("store_name") or "").strip()
    if label:
        return label
    return str(store.get("store_code") or store.get("supplier_code") or "?")


def _embed_origin_from_path_origin(origin: str) -> str:
    if origin == ORIGIN_LABEL:
        return EMBED_ORIGIN_CURRENT
    return origin


def build_directions_url(
    stops: Sequence[Dict[str, Any]],
    origin: Optional[str] = None,
) -> str:
    """Google Maps ルート URL を組み立てる。origin 省略時は現在地。"""
    origin_part = origin if origin is not None else ORIGIN_LABEL
    parts = [origin_part] + [stop_to_path_segment(s) for s in stops]
    return "https://www.google.com/maps/dir/" + "/".join(parts)


def build_embed_directions_url(
    stops: Sequence[Dict[str, Any]],
    api_key: str,
    origin: Optional[str] = None,
) -> str:
    """Maps Embed API（directions）の iframe src URL を組み立てる。"""
    key = (api_key or "").strip()
    if not key or not stops:
        return ""

    origin_part = origin if origin is not None else ORIGIN_LABEL
    origin_loc = _embed_origin_from_path_origin(origin_part)

    destination = stop_to_embed_location(stops[-1])
    params: Dict[str, str] = {
        "key": key,
        "origin": origin_loc,
        "destination": destination,
        "language": "ja",
    }
    if len(stops) > 1:
        params["waypoints"] = "|".join(stop_to_embed_location(s) for s in stops[:-1])

    return "https://www.google.com/maps/embed/v1/directions?" + urlencode(params)


def split_into_segments(
    stores: Sequence[Dict[str, Any]],
    max_stops: int = MAX_STOPS_PER_SEGMENT,
) -> List[List[Dict[str, Any]]]:
    if max_stops <= 0:
        return []
    return [list(stores[i : i + max_stops]) for i in range(0, len(stores), max_stops)]


def _build_store_code_to_segment(
    segments: Sequence[RouteMapSegment],
    skipped: Sequence[SkippedDuplicateStore],
) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for seg in segments:
        for code in seg.store_codes:
            if code:
                mapping[code] = seg.index
    for dup in skipped:
        kept_seg = mapping.get(dup.kept_store_code)
        if kept_seg and dup.store_code:
            mapping[dup.store_code] = kept_seg
    return mapping


def generate_route_map_urls(
    stores: Sequence[Dict[str, Any]],
    max_stops: int = MAX_STOPS_PER_SEGMENT,
    api_key: Optional[str] = None,
) -> RouteMapGenerationResult:
    """店舗リストから分割済み Google Maps URL を生成する。"""
    result = RouteMapGenerationResult()
    if not stores:
        return result

    unique_stores, skipped = dedupe_stores_by_coordinates(stores)
    result.skipped_duplicates = skipped

    for store in unique_stores:
        if location_key(store) is None:
            result.missing_coordinates.append(
                {
                    "store_code": str(store.get("store_code") or store.get("supplier_code") or ""),
                    "store_name": str(store.get("store_name") or ""),
                }
            )

    resolved_key = resolve_maps_api_key(api_key) if resolve_maps_api_key else None
    chunks = split_into_segments(unique_stores, max_stops=max_stops)
    for idx, chunk in enumerate(chunks, start=1):
        if idx == 1:
            origin = ORIGIN_LABEL
        else:
            origin = stop_to_path_segment(chunks[idx - 2][-1])
        embed_url = ""
        if resolved_key:
            embed_url = build_embed_directions_url(chunk, resolved_key, origin=origin)
        result.segments.append(
            RouteMapSegment(
                index=idx,
                url=build_directions_url(chunk, origin=origin),
                store_codes=[
                    str(s.get("store_code") or s.get("supplier_code") or "")
                    for s in chunk
                ],
                store_names=[str(s.get("store_name") or "") for s in chunk],
                embed_url=embed_url,
            )
        )

    result.store_code_to_segment = _build_store_code_to_segment(result.segments, skipped)
    return result
