#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Directions API で道路沿いルート・所要時間を取得する。

- 1リクエストあたり経由地は最大 23（origin/destination 除く）
- 長いルートは分割して合計
- API 失敗時は呼び出し側で直線フォールバックすること
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import requests
except ImportError:
    requests = None

try:
    from services.google_maps_service import resolve_maps_api_key
except ImportError:
    try:
        from google_maps_service import resolve_maps_api_key
    except ImportError:
        resolve_maps_api_key = None  # type: ignore

MAX_WAYPOINTS = 23
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"

# プロセス内キャッシュ（同一ルート再描画用）
_CACHE: Dict[str, "RouteDirectionsResult"] = {}


@dataclass
class RouteDirectionsResult:
    ok: bool
    polyline: List[List[float]] = field(default_factory=list)  # [[lat, lng], ...]
    distance_m: int = 0
    duration_s: int = 0
    error: str = ""

    @property
    def distance_km(self) -> float:
        return round(self.distance_m / 1000.0, 1)

    @property
    def duration_text(self) -> str:
        total = int(self.duration_s or 0)
        hours, rem = divmod(total, 3600)
        minutes = rem // 60
        if hours > 0:
            return f"{hours}時間{minutes}分"
        return f"{minutes}分"


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def store_latlng(store: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    lat = _coerce_float(store.get("latitude"))
    lng = _coerce_float(store.get("longitude"))
    if lat is None or lng is None:
        return None
    return (lat, lng)


def _cache_key(points: Sequence[Tuple[float, float]]) -> str:
    raw = json.dumps([[round(a, 5), round(b, 5)] for a, b in points], separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _decode_polyline(encoded: str) -> List[List[float]]:
    """Google encoded polyline → [[lat, lng], ...]"""
    coordinates: List[List[float]] = []
    index = 0
    lat = 0
    lng = 0
    length = len(encoded)
    while index < length:
        result = 0
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else (result >> 1)
        lat += dlat

        result = 0
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if result & 1 else (result >> 1)
        lng += dlng
        coordinates.append([lat / 1e5, lng / 1e5])
    return coordinates


def _chunk_points(
    points: Sequence[Tuple[float, float]],
    max_waypoints: int = MAX_WAYPOINTS,
) -> List[List[Tuple[float, float]]]:
    """origin + waypoints + destination として扱えるチャンクに分割。"""
    if len(points) < 2:
        return []
    # 1チャンクあたり地点数 = max_waypoints + 2 (origin/dest)
    max_points = max_waypoints + 2
    chunks: List[List[Tuple[float, float]]] = []
    start = 0
    while start < len(points) - 1:
        end = min(start + max_points - 1, len(points) - 1)
        chunk = list(points[start : end + 1])
        if len(chunk) >= 2:
            chunks.append(chunk)
        if end >= len(points) - 1:
            break
        start = end  # 接続点を共有
    return chunks


def _fetch_chunk(
    chunk: Sequence[Tuple[float, float]],
    api_key: str,
) -> RouteDirectionsResult:
    if requests is None:
        return RouteDirectionsResult(ok=False, error="requests 未インストール")
    if len(chunk) < 2:
        return RouteDirectionsResult(ok=False, error="地点不足")

    origin = f"{chunk[0][0]},{chunk[0][1]}"
    destination = f"{chunk[-1][0]},{chunk[-1][1]}"
    params: Dict[str, str] = {
        "origin": origin,
        "destination": destination,
        "key": api_key,
        "language": "ja",
        "mode": "driving",
        "units": "metric",
    }
    if len(chunk) > 2:
        params["waypoints"] = "|".join(f"{lat},{lng}" for lat, lng in chunk[1:-1])

    try:
        resp = requests.get(DIRECTIONS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return RouteDirectionsResult(ok=False, error=str(e))

    status = data.get("status") or ""
    if status != "OK":
        msg = data.get("error_message") or status or "Directions API エラー"
        return RouteDirectionsResult(ok=False, error=msg)

    routes = data.get("routes") or []
    if not routes:
        return RouteDirectionsResult(ok=False, error="ルートなし")

    route0 = routes[0]
    overview = (route0.get("overview_polyline") or {}).get("points") or ""
    poly = _decode_polyline(overview) if overview else []
    distance_m = 0
    duration_s = 0
    for leg in route0.get("legs") or []:
        distance_m += int((leg.get("distance") or {}).get("value") or 0)
        duration_s += int((leg.get("duration") or {}).get("value") or 0)

    return RouteDirectionsResult(
        ok=True,
        polyline=poly,
        distance_m=distance_m,
        duration_s=duration_s,
    )


def fetch_driving_route(
    stores: Sequence[Dict[str, Any]],
    api_key: Optional[str] = None,
    use_cache: bool = True,
) -> RouteDirectionsResult:
    """店舗リスト（訪問順）から道路沿いルートを取得。"""
    points: List[Tuple[float, float]] = []
    for store in stores:
        ll = store_latlng(store)
        if ll is not None:
            points.append(ll)

    if len(points) < 2:
        return RouteDirectionsResult(
            ok=False,
            error="座標付き店舗が2件未満のため道路ルートを計算できません",
        )

    key = None
    if resolve_maps_api_key:
        key = resolve_maps_api_key(api_key)
    elif api_key:
        key = api_key.strip() or None
    if not key:
        return RouteDirectionsResult(ok=False, error="Maps API キーが未設定です")

    cache_id = _cache_key(points)
    if use_cache and cache_id in _CACHE:
        return _CACHE[cache_id]

    merged = RouteDirectionsResult(ok=True)
    for chunk in _chunk_points(points):
        part = _fetch_chunk(chunk, key)
        if not part.ok:
            return part
        if merged.polyline and part.polyline:
            # 接続点の重複を避ける
            merged.polyline.extend(part.polyline[1:])
        else:
            merged.polyline.extend(part.polyline)
        merged.distance_m += part.distance_m
        merged.duration_s += part.duration_s

    if use_cache:
        _CACHE[cache_id] = merged
    return merged


def clear_directions_cache() -> None:
    _CACHE.clear()
