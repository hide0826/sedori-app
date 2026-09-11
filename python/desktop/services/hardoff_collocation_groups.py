#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ハードオフ／ホビーオフ／オフハウスの併設店グループ化。

- 緯度経度が指定距離以内の HA / HO / OF を1グループにまとめる
- 代表店舗の優先順: ハードオフ(HA) → ホビーオフ(HO) → オフハウス(OF)
- 座標なし・他チェーンは単独のまま
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Sequence, Tuple

COLOCATION_RADIUS_M = 30.0

# 小さいほど代表になりやすい
BRAND_PRIORITY = {
    "HA": 0,  # ハードオフ
    "HO": 1,  # ホビーオフ
    "OF": 2,  # オフハウス
}


@dataclass
class CollocationGroup:
    """併設グループ（members は代表優先順）。"""

    representative: Dict[str, Any]
    members: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def extra_count(self) -> int:
        return max(0, len(self.members) - 1)

    @property
    def member_count(self) -> int:
        return len(self.members)


def collocation_toggle_label(member_count: int, *, expanded: bool = False) -> str:
    """UI用: 「＋2店舗併設」「－3店舗」など。"""
    n = int(member_count or 0)
    if n <= 1:
        return ""
    if expanded:
        return f"－{n}店舗"
    return f"＋{n}店舗併設"


def collocation_group_key(members: Sequence[Dict[str, Any]]) -> str:
    ids = []
    for s in members:
        try:
            ids.append(int(s.get("id")))
        except (TypeError, ValueError):
            continue
    return ",".join(str(i) for i in sorted(ids))


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    )
    return 2.0 * r * asin(sqrt(a))


def store_code_prefix(store: Dict[str, Any]) -> str:
    raw = str(store.get("store_code") or store.get("supplier_code") or "").strip().upper()
    if not raw:
        return ""
    if "-" in raw:
        return raw.split("-", 1)[0].strip()
    if "_" in raw:
        return raw.split("_", 1)[0].strip()
    # HA01 のような形式
    import re

    m = re.match(r"^([A-Z]+)", raw)
    return m.group(1) if m else raw


def detect_hardoff_family_brand(store: Dict[str, Any]) -> Optional[str]:
    """HA / HO / OF のいずれか。該当しなければ None。"""
    prefix = store_code_prefix(store)
    if prefix in BRAND_PRIORITY:
        return prefix

    name = str(store.get("store_name") or "")
    name_u = name.upper()
    # 名称判定（併記はより優先の方）
    has_ha = ("ハードオフ" in name) or ("HARD OFF" in name_u) or ("HARDOFF" in name_u)
    has_ho = ("ホビーオフ" in name) or ("HOBBY OFF" in name_u) or ("HOBBYOFF" in name_u)
    has_of = ("オフハウス" in name) or ("OFF HOUSE" in name_u) or ("OFFHOUSE" in name_u)
    # コード無しの併記店名は HA 優先
    if has_ha:
        return "HA"
    if has_ho:
        return "HO"
    if has_of:
        return "OF"
    return None


def _brand_sort_key(store: Dict[str, Any]) -> Tuple[int, int, str]:
    brand = detect_hardoff_family_brand(store) or "ZZ"
    prio = BRAND_PRIORITY.get(brand, 99)
    try:
        order = int(store.get("display_order") if store.get("display_order") is not None else 999999)
    except (TypeError, ValueError):
        order = 999999
    code = str(store.get("store_code") or store.get("supplier_code") or "")
    return (prio, order, code)


def group_hardoff_family_stores(
    stores: Sequence[Dict[str, Any]],
    radius_m: float = COLOCATION_RADIUS_M,
) -> List[CollocationGroup]:
    """
    表示順を保ちつつ、HA/HO/OF の近接店をグループ化して返す。

    戻り値の各グループ.members は代表優先順（HA→HO→OF）。
    非対象店舗・座標なしは1件グループ。
    """
    indexed: List[Tuple[int, Dict[str, Any]]] = list(enumerate(stores))
    n = len(indexed)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    coords: List[Optional[Tuple[float, float]]] = []
    brands: List[Optional[str]] = []
    for _, store in indexed:
        brands.append(detect_hardoff_family_brand(store))
        lat = _coerce_float(store.get("latitude"))
        lng = _coerce_float(store.get("longitude"))
        if lat is None or lng is None:
            coords.append(None)
        else:
            coords.append((lat, lng))

    for i in range(n):
        if brands[i] is None or coords[i] is None:
            continue
        lat1, lng1 = coords[i]  # type: ignore[misc]
        for j in range(i + 1, n):
            if brands[j] is None or coords[j] is None:
                continue
            lat2, lng2 = coords[j]  # type: ignore[misc]
            if _haversine_m(lat1, lng1, lat2, lng2) <= radius_m:
                union(i, j)

    buckets: Dict[int, List[int]] = {}
    for i in range(n):
        root = find(i)
        buckets.setdefault(root, []).append(i)

    # 元の並びに近い順でグループを出す（各グループの先頭出現順）
    groups: List[CollocationGroup] = []
    emitted: set = set()
    for i in range(n):
        root = find(i)
        if root in emitted:
            continue
        emitted.add(root)
        member_idxs = buckets[root]
        member_stores = [indexed[k][1] for k in member_idxs]
        member_stores.sort(key=_brand_sort_key)
        groups.append(
            CollocationGroup(
                representative=member_stores[0],
                members=member_stores,
            )
        )
    return groups
