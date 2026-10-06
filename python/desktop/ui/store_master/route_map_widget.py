#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗マスタ「ルート地図」タブ: 文字ラベル／ピン＋ルート線＋全選択＋タグ色分け。"""
from __future__ import annotations

import json
import math
import re
import sys
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QUrl, Signal, QSettings, QTimer, QEvent, QPoint
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QCheckBox,
    QSplitter,
    QGroupBox,
    QMessageBox,
    QScrollArea,
    QFrame,
    QStyle,
    QStyleOptionButton,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QSizePolicy,
    QDialog,
    QInputDialog,
    QMenu,
)

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from database.store_db import StoreDatabase

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEBENGINE_AVAILABLE = True
except Exception:
    QWebEngineView = None  # type: ignore
    WEBENGINE_AVAILABLE = False

from .store_tags_dialog import StoreTagsDialog
from .collapsible_section import CollapsibleSection
from .store_dialogs import StoreEditDialog

try:
    from services.store_brand_tag_service import (
        MAP_ICON_DEFS,
        MAP_ICON_ORDER,
        hardoff_collocation_icon_key,
        is_brand_tag_name,
        is_quality_tag_name,
        resolve_map_icon_key,
    )
except Exception:
    try:
        from store_brand_tag_service import (  # type: ignore
            MAP_ICON_DEFS,
            MAP_ICON_ORDER,
            hardoff_collocation_icon_key,
            is_brand_tag_name,
            is_quality_tag_name,
            resolve_map_icon_key,
        )
    except Exception:
        MAP_ICON_DEFS = {}  # type: ignore
        MAP_ICON_ORDER = ()  # type: ignore

        def resolve_map_icon_key(store_name: str, tag_names=None) -> str:
            return "other"

        def hardoff_collocation_icon_key(member_count: int) -> str:
            return "hardoff1"

        def is_brand_tag_name(name: str) -> bool:
            return False

        def is_quality_tag_name(name: str) -> bool:
            return name in (
                "大型店舗",
                "値付け甘い",
                "あまり行かなくて良い",
            )

try:
    from services.hardoff_collocation_groups import (
        COLOCATION_RADIUS_M,
        detect_hardoff_family_brand,
        group_hardoff_family_stores,
    )
except Exception:
    try:
        from hardoff_collocation_groups import (  # type: ignore
            COLOCATION_RADIUS_M,
            detect_hardoff_family_brand,
            group_hardoff_family_stores,
        )
    except Exception:
        COLOCATION_RADIUS_M = 80.0  # type: ignore
        detect_hardoff_family_brand = None  # type: ignore
        group_hardoff_family_stores = None  # type: ignore

ROUTE_LINE_COLORS = [
    "#1e88e5",  # 青
    "#fb8c00",  # オレンジ
    "#8e24aa",  # 紫
    "#e53935",  # 赤（旧ティール：緑地図で埋もれにくい）
    "#d81b60",  # ピンク
    "#3949ab",  # 藍
    "#f4511e",  # 深オレンジ
    "#00acc1",  # シアン
    "#6d4c41",  # 茶（旧黄緑）
    "#5e35b1",  # 深紫
    "#c62828",  # 濃赤（旧ライム）
    "#546e7a",  # グレー青
]

DEFAULT_PIN_COLOR = "#1976d2"

# ハードオフ系併設で選べるブランド（優先順）
_HARDOFF_BRAND_ORDER: Tuple[str, ...] = ("HA", "HO", "OF")
_HARDOFF_BRAND_LABELS = {
    "HA": "ハードオフ",
    "HO": "ホビーオフ",
    "OF": "オフハウス",
}
SKIPPED_PIN_COLOR = "#9e9e9e"
UNASSIGNED_KEY = "__unassigned__"


def _template_include_from_value(value: Any) -> bool:
    """stores.template_include / will_visit 相当。未設定は訪問する扱い。"""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return bool(value)


def _will_visit_from_store(store: Dict[str, Any]) -> bool:
    if "will_visit" in store:
        return bool(store.get("will_visit"))
    return _template_include_from_value(store.get("template_include"))


def _rows_for_pick_order(
    baseline: List[Dict[str, Any]], pick_order: List[str]
) -> List[Dict[str, Any]]:
    """地図クリック選択順の店舗行を組み立てる。

    選んだ店は先頭＋チェックON、ルート登録済みでも未選択の店は末尾＋チェックOFF。
    """
    by_code: Dict[str, Dict[str, Any]] = {}
    for row in baseline:
        code = str(row.get("store_code") or "").strip()
        if not code or code in by_code:
            continue
        by_code[code] = dict(row)
        by_code[code]["store_code"] = code
    picked = [str(c).strip() for c in pick_order if str(c).strip()]
    picked_set = set(picked)
    for code, row in by_code.items():
        row["checked"] = code in picked_set
    remaining = [
        by_code[str(r.get("store_code") or "").strip()]
        for r in baseline
        if str(r.get("store_code") or "").strip() in by_code
        and str(r.get("store_code") or "").strip() not in picked_set
    ]
    return [by_code[c] for c in picked if c in by_code] + remaining


SETTINGS_ORG = "HIRIO"
SETTINGS_APP = "desktop"
SETTINGS_MAIN_SPLITTER = "store_master/route_map/main_splitter"
SETTINGS_LEFT_SPLITTER = "store_master/route_map/left_splitter"
SETTINGS_MAP_VIEW = "store_master/route_map/map_view"
SETTINGS_COLLAPSE_ROUTES = "store_master/route_map/collapse_routes"
SETTINGS_COLLAPSE_VISITS = "store_master/route_map/collapse_visits"
SETTINGS_COLLAPSE_TAGS = "store_master/route_map/collapse_tags"

# ダークテーマでもチェック枠が見えるようにする共通スタイル
CHECKBOX_BASE_STYLE = """
QCheckBox {
    spacing: 8px;
    padding: 2px 0;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #cfd8dc;
    border-radius: 3px;
    background: #2b2b2b;
}
QCheckBox::indicator:checked {
    background: #4caf50;
    border: 2px solid #81c784;
}
QCheckBox::indicator:unchecked {
    background: #2b2b2b;
    border: 2px solid #cfd8dc;
}
"""

def _checkbox_style(text_color: str) -> str:
    """ダークパネル上の色付き文字用チェックボックス。"""
    return CHECKBOX_BASE_STYLE + f"\nQCheckBox {{ color: {text_color}; font-weight: bold; }}"


class RouteNameCheckBox(QCheckBox):
    """ルート一覧用。トグルはチェック枠クリックのみ。店名側はダブルクリック拡大。"""

    def _indicator_rect(self):
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        return self.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, self)

    def _pos(self, event):
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _on_indicator(self, event) -> bool:
        return self._indicator_rect().contains(self._pos(event))

    def mousePressEvent(self, event) -> None:
        if self._on_indicator(event):
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._on_indicator(event):
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        # 枠上のダブルクリックは通常のチェック動作、店名側は eventFilter で拡大
        if self._on_indicator(event):
            super().mouseDoubleClickEvent(event)


def _pin_color_for_store(store: Dict[str, Any]) -> str:
    """丸ピン色は評価・メモタグのみ。店舗種別は店舗ラベル側で見る。"""
    tags = store.get("tags") or []
    # attach_tags_to_stores は priority 昇順
    for tag in tags:
        name = str(tag.get("name") or "")
        if is_brand_tag_name(name) or name == "その他":
            continue
        color = (tag.get("color") or "").strip()
        if color:
            return color
    return DEFAULT_PIN_COLOR


def _icon_key_for_store(store: Dict[str, Any]) -> str:
    tag_names = [t.get("name") for t in (store.get("tags") or []) if t.get("name")]
    return resolve_map_icon_key(str(store.get("store_name") or ""), tag_names)


def _brand_of_store(store: Dict[str, Any]) -> Optional[str]:
    if detect_hardoff_family_brand is None:
        return None
    try:
        return detect_hardoff_family_brand(store)
    except Exception:
        return None


def _ordered_member_brands(members: List[Dict[str, Any]]) -> List[str]:
    found: List[str] = []
    for m in members:
        brand = _brand_of_store(m)
        if brand and brand not in found:
            found.append(brand)
    return [b for b in _HARDOFF_BRAND_ORDER if b in found]


def _missing_hardoff_brands(member_brands: List[str]) -> List[str]:
    present = {str(b or "").strip().upper() for b in (member_brands or [])}
    return [b for b in _HARDOFF_BRAND_ORDER if b not in present]


def _suggest_collocated_store_name(source_name: str, brand: str) -> str:
    """併設登録用の店舗名候補（例: オフハウス 東所沢店 → ハードオフ 東所沢店）。"""
    label = _HARDOFF_BRAND_LABELS.get(brand, brand)
    location = ""
    try:
        from services.combined_store_split_service import extract_location_suffix

        location = extract_location_suffix(source_name)
    except Exception:
        try:
            from combined_store_split_service import (  # type: ignore
                extract_location_suffix,
            )

            location = extract_location_suffix(source_name)
        except Exception:
            location = ""
    if not location:
        return label
    use_space = bool(re.search(r"(ハウス|オフ)\s+\S", source_name or ""))
    if use_space:
        return f"{label} {location}".strip()
    return f"{label}{location}".strip()


def _store_map_dict(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        lat = float(store.get("latitude"))
        lng = float(store.get("longitude"))
    except (TypeError, ValueError):
        return None
    tags = store.get("tags") or []
    tag_names = [t.get("name") for t in tags if t.get("name")]
    brand = _brand_of_store(store)
    try:
        checked = bool(int(store.get("collocation_checked") or 0))
    except (TypeError, ValueError):
        checked = bool(store.get("collocation_checked"))
    entry = _member_entry_from_store(store)
    return {
        "id": store.get("id"),
        "store_code": store.get("store_code") or store.get("supplier_code") or "",
        "store_name": store.get("store_name") or "",
        "lat": lat,
        "lng": lng,
        "pin_color": _pin_color_for_store(store),
        "icon_key": _icon_key_for_store(store),
        "tag_names": tag_names,
        "tag_ids": [int(t["id"]) for t in tags if t.get("id") is not None],
        "member_names": [entry["store_name"]] if entry.get("store_name") else [],
        "member_brands": [brand] if brand else [],
        "members": [entry] if entry.get("store_code") or entry.get("id") is not None else [],
        "is_hardoff_family": brand is not None,
        "collocation_checked": checked,
        "will_visit": _will_visit_from_store(store),
    }


def _member_entry_from_store(store: Dict[str, Any]) -> Dict[str, Any]:
    """ポップアップの併設一覧・個別削除用の1行データ。"""
    code = str(store.get("store_code") or store.get("supplier_code") or "").strip()
    name = str(store.get("store_name") or "").strip()
    sid = None
    try:
        if store.get("id") is not None:
            sid = int(store.get("id"))
    except (TypeError, ValueError):
        sid = None
    brand = _brand_of_store(store) or ""
    return {
        "id": sid,
        "store_code": code,
        "store_name": name,
        "brand": brand,
    }


def _mean_lat_lng(stores: List[Dict[str, Any]]) -> Optional[tuple]:
    lats: List[float] = []
    lngs: List[float] = []
    for store in stores:
        try:
            lats.append(float(store.get("latitude")))
            lngs.append(float(store.get("longitude")))
        except (TypeError, ValueError):
            continue
    if not lats:
        return None
    return (sum(lats) / len(lats), sum(lngs) / len(lngs))


def _markers_from_stores(stores_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """地図ピン用。HA/HO/OF の併設は 1 ピン（H1/H2/H3）にまとめる。"""
    if not stores_raw:
        return []
    if group_hardoff_family_stores is None:
        markers = []
        for store in stores_raw:
            mapped = _store_map_dict(store)
            if mapped:
                markers.append(mapped)
        return markers

    markers: List[Dict[str, Any]] = []
    for group in group_hardoff_family_stores(stores_raw):
        members = list(group.members or [])
        mapped = None
        for candidate in [group.representative] + members:
            mapped = _store_map_dict(candidate)
            if mapped:
                break
        if not mapped:
            continue
        # 併設ピンの訪問フラグは代表店を優先
        mapped["will_visit"] = _will_visit_from_store(group.representative)
        member_codes = []
        member_ids: List[int] = []
        for m in members:
            mc = str(m.get("store_code") or m.get("supplier_code") or "").strip()
            if mc and mc not in member_codes:
                member_codes.append(mc)
            mid = m.get("id")
            if mid is not None:
                try:
                    mid_i = int(mid)
                except (TypeError, ValueError):
                    mid_i = None
                if mid_i is not None and mid_i not in member_ids:
                    member_ids.append(mid_i)
        mapped["member_codes"] = member_codes
        mapped["member_ids"] = member_ids
        member_brands = _ordered_member_brands(members)
        mapped["member_brands"] = member_brands
        member_entries = []
        for m in members:
            entry = _member_entry_from_store(m)
            if entry.get("store_code") or entry.get("id") is not None:
                member_entries.append(entry)
        mapped["members"] = member_entries
        # 併設ピンはメンバーのいずれかが確認済みならピン全体を確認済み
        any_checked = False
        for m in members:
            try:
                if bool(int(m.get("collocation_checked") or 0)):
                    any_checked = True
                    break
            except (TypeError, ValueError):
                if m.get("collocation_checked"):
                    any_checked = True
                    break
        mapped["collocation_checked"] = any_checked
        if member_brands:
            mapped["is_hardoff_family"] = True
            mapped["icon_key"] = hardoff_collocation_icon_key(len(members))
            names = []
            for m in members:
                name = str(m.get("store_name") or "").strip()
                if name and name not in names:
                    names.append(name)
            mapped["member_names"] = names
            mean = _mean_lat_lng(members)
            if mean:
                mapped["lat"], mapped["lng"] = mean
        markers.append(mapped)
    return markers


def _mark_route_endpoints(stores: List[Dict[str, Any]]) -> None:
    """訪問する店の先頭をスタート、末尾をゴールにする（1店なら both）。"""
    visit_idxs = [
        i for i, s in enumerate(stores) if s.get("will_visit", True) is not False
    ]
    if not visit_idxs:
        return
    first_i = visit_idxs[0]
    last_i = visit_idxs[-1]
    if first_i == last_i:
        stores[first_i]["endpoint"] = "both"
    else:
        stores[first_i]["endpoint"] = "start"
        stores[last_i]["endpoint"] = "goal"


def _marker_lat_lng(marker: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    try:
        return (float(marker.get("lat")), float(marker.get("lng")))
    except (TypeError, ValueError):
        return None


def _approx_distance_m(
    a: Tuple[float, float], b: Tuple[float, float]
) -> float:
    lat1, lng1 = a
    lat2, lng2 = b
    dy = (lat1 - lat2) * 111_000.0
    dx = (lng1 - lng2) * 111_000.0 * max(
        0.2, abs(math.cos(math.radians(lat1)))
    )
    return (dx * dx + dy * dy) ** 0.5


def _merge_marker_members(base: Dict[str, Any], other: Dict[str, Any]) -> None:
    """other の併設メンバー情報を base に合流させる。"""
    codes = list(base.get("member_codes") or [])
    ids = list(base.get("member_ids") or [])
    names = list(base.get("member_names") or [])
    brands = list(base.get("member_brands") or [])
    members = list(base.get("members") or [])

    def _append_member(entry: Dict[str, Any]) -> None:
        code = str(entry.get("store_code") or "").strip()
        try:
            sid = int(entry["id"]) if entry.get("id") is not None else None
        except (TypeError, ValueError):
            sid = None
        for existing in members:
            if code and str(existing.get("store_code") or "").strip() == code:
                return
            if sid is not None and existing.get("id") == sid:
                return
        row = {
            "id": sid,
            "store_code": code,
            "store_name": str(entry.get("store_name") or "").strip(),
            "brand": str(entry.get("brand") or "").strip().upper(),
        }
        members.append(row)
        if code and code not in codes:
            codes.append(code)
        if sid is not None and sid not in ids:
            ids.append(sid)
        name = row["store_name"]
        if name and name not in names:
            names.append(name)
        brand = row["brand"]
        if brand and brand not in brands:
            brands.append(brand)

    def _seed_from_parallel(src: Dict[str, Any]) -> None:
        src_members = src.get("members") or []
        if src_members:
            for entry in src_members:
                if isinstance(entry, dict):
                    _append_member(entry)
            return
        mcodes = list(src.get("member_codes") or [])
        mids = list(src.get("member_ids") or [])
        mnames = list(src.get("member_names") or [])
        if not mcodes and src.get("store_code"):
            _append_member(
                {
                    "id": src.get("id"),
                    "store_code": src.get("store_code"),
                    "store_name": src.get("store_name"),
                    "brand": "",
                }
            )
            return
        for i, code in enumerate(mcodes):
            mid = mids[i] if i < len(mids) else None
            mname = mnames[i] if i < len(mnames) else ""
            _append_member(
                {
                    "id": mid,
                    "store_code": code,
                    "store_name": mname,
                    "brand": "",
                }
            )

    if not members:
        _seed_from_parallel(base)
    _seed_from_parallel(other)

    for brand in other.get("member_brands") or []:
        bs = str(brand or "").strip().upper()
        if bs and bs not in brands:
            brands.append(bs)

    base["member_codes"] = codes
    base["member_ids"] = ids
    base["member_names"] = names
    base["members"] = members
    base["member_brands"] = [b for b in _HARDOFF_BRAND_ORDER if b in brands]
    base["is_hardoff_family"] = True
    base["collocation_checked"] = bool(base.get("collocation_checked")) or bool(
        other.get("collocation_checked")
    )
    # ピン表示用アイコンはメンバー店舗数（H1/H2/H3）
    member_count = max(len(ids), len(codes), len(members), 1)
    base["icon_key"] = hardoff_collocation_icon_key(member_count)


def _line_only_marker(marker: Dict[str, Any]) -> Dict[str, Any]:
    """ルート線用に座標だけ残し、ピン描画は抑止する。"""
    return {
        "id": marker.get("id"),
        "store_code": marker.get("store_code") or "",
        "store_name": marker.get("store_name") or "",
        "lat": marker.get("lat"),
        "lng": marker.get("lng"),
        "will_visit": marker.get("will_visit", True),
        "endpoint": marker.get("endpoint"),
        "pick_index": marker.get("pick_index"),
        "template_include": marker.get("template_include"),
        "suppress_pin": True,
        "is_hardoff_family": False,
        "member_codes": [],
        "member_ids": [],
        "member_names": [],
        "member_brands": [],
        "members": [],
    }


def _merge_cross_route_hardoff_markers(
    map_routes: List[Dict[str, Any]],
    unassigned: List[Dict[str, Any]],
    *,
    radius_m: Optional[float] = None,
) -> None:
    """
    ルート／未所属をまたいで近接する HA/HO/OF ピンを1つにまとめる。

    線引き用の座標は各ルートに残し、余分なピンだけ suppress_pin にする。
    """
    limit = float(radius_m if radius_m is not None else COLOCATION_RADIUS_M)
    slots: List[Tuple[str, int, Dict[str, Any]]] = []
    for ri, route in enumerate(map_routes or []):
        for marker in route.get("stores") or []:
            if marker.get("is_hardoff_family") and not marker.get("suppress_pin"):
                slots.append(("route", ri, marker))
    for marker in unassigned or []:
        if marker.get("is_hardoff_family") and not marker.get("suppress_pin"):
            slots.append(("unassigned", -1, marker))

    n = len(slots)
    if n < 2:
        return

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
    for _, _, marker in slots:
        coords.append(_marker_lat_lng(marker))

    for i in range(n):
        if coords[i] is None:
            continue
        for j in range(i + 1, n):
            if coords[j] is None:
                continue
            if _approx_distance_m(coords[i], coords[j]) <= limit:  # type: ignore[arg-type]
                union(i, j)

    buckets: Dict[int, List[int]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)

    for idxs in buckets.values():
        if len(idxs) < 2:
            continue
        # メンバーが多いピンを代表に残す
        def _score(i: int) -> Tuple[int, int]:
            m = slots[i][2]
            return (
                len(m.get("member_ids") or m.get("member_codes") or []),
                1 if m.get("endpoint") else 0,
            )

        keep_i = max(idxs, key=_score)
        keep_marker = slots[keep_i][2]
        for i in idxs:
            if i == keep_i:
                continue
            other = slots[i][2]
            _merge_marker_members(keep_marker, other)
            # 線用スタブへ差し替え
            stub = _line_only_marker(other)
            kind, ri, _ = slots[i]
            if kind == "route":
                stores = map_routes[ri].get("stores") or []
                for si, s in enumerate(stores):
                    if s is other:
                        stores[si] = stub
                        break
            else:
                for ui, s in enumerate(unassigned):
                    if s is other:
                        unassigned[ui] = stub
                        break


def _store_matches_code(store: Dict[str, Any], store_code: str) -> bool:
    code = (store_code or "").strip()
    if not code:
        return False
    sc = str(store.get("store_code") or "").strip()
    if sc == code:
        return True
    members = store.get("member_codes") or []
    return code in {str(m).strip() for m in members}


def _json_for_js(obj: Any) -> str:
    """HTML / runJavaScript 用に JSON を安全化。"""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def build_leaflet_html(payload: Dict[str, Any]) -> str:
    """Leaflet 地図 HTML（CDN）。payload は JSON 埋め込み。"""
    data_json = _json_for_js(payload)
    grayscale = bool(payload.get("grayscale"))
    # 注意: この文字列は後で f-string に {tile_url} として埋め込む。
    # ここを {{s}} にすると Leaflet に二重ブレースが渡りタイルが真っ黒になる。
    tile_url = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attr = "&copy; OpenStreetMap"
    map_bg = "#e8e8e8" if grayscale else "#cfd8dc"
    tile_filter_css = (
        ".leaflet-tile-pane { filter: grayscale(100%) contrast(1.05) brightness(1.05); }"
        if grayscale
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body, #map {{ margin:0; padding:0; height:100%; width:100%; background:{map_bg}; }}
  .legend {{
    background: rgba(30,30,30,0.9); color:#eee; padding:8px 10px;
    border-radius:6px; font: 12px/1.4 sans-serif; max-width:280px;
  }}
  .legend .swatch {{
    display:inline-block; width:12px; height:12px; border-radius:50%;
    margin-right:6px; border:1px solid #fff; vertical-align:middle;
  }}
  .popup-title {{ font-weight:bold; margin-bottom:4px; }}
  .popup-tags {{ color:#1565c0; font-size:12px; }}
  .popup-actions {{
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}
  .popup-actions button {{
    border: 1px solid #90a4ae;
    background: #eceff1;
    color: #263238;
    border-radius: 4px;
    padding: 4px 8px;
    font: 12px/1.2 "Segoe UI","Meiryo UI",sans-serif;
    cursor: pointer;
  }}
  .popup-actions button.danger {{
    background: #ffebee;
    border-color: #ef9a9a;
    color: #b71c1c;
  }}
  .popup-actions button.primary {{
    background: #e3f2fd;
    border-color: #64b5f6;
    color: #0d47a1;
  }}
  .popup-actions button.colloc {{
    background: #e8f5e9;
    border-color: #81c784;
    color: #1b5e20;
  }}
  .popup-actions button:hover {{ filter: brightness(0.97); }}
  .popup-members {{
    margin: 6px 0 2px;
    padding: 4px 0;
    border-top: 1px solid #eceff1;
  }}
  .popup-members .mem-title {{
    font: 700 11px/1.3 sans-serif;
    color: #455a64;
    margin-bottom: 4px;
  }}
  .popup-member-row {{
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 3px 0;
  }}
  .popup-member-row .mem-name {{
    flex: 1;
    min-width: 0;
    font: 12px/1.3 "Segoe UI","Meiryo UI",sans-serif;
    color: #263238;
  }}
  .popup-member-row .mem-code {{
    color: #607d8b;
    font-size: 11px;
  }}
  .popup-member-row button.mem-del {{
    flex: 0 0 auto;
    background: #ffebee;
    border: 1px solid #ef9a9a;
    color: #b71c1c;
    border-radius: 4px;
    padding: 2px 6px;
    font: 11px/1.2 "Segoe UI","Meiryo UI",sans-serif;
    cursor: pointer;
  }}
  .popup-member-row button.mem-del:hover {{ filter: brightness(0.97); }}
  .popup-candidates {{
    margin-top: 8px;
    max-height: 160px;
    overflow-y: auto;
    border-top: 1px solid #cfd8dc;
    padding-top: 6px;
  }}
  .popup-candidates .cand-title {{
    font: 700 11px/1.3 sans-serif;
    color: #455a64;
    margin-bottom: 4px;
  }}
  .popup-candidates a {{
    display: block;
    padding: 4px 6px;
    margin: 2px 0;
    border-radius: 4px;
    text-decoration: none;
    color: #0d47a1;
    background: #f5f9fc;
    font: 12px/1.3 "Segoe UI","Meiryo UI",sans-serif;
  }}
  .popup-candidates a:hover {{ background: #e3f2fd; }}
  .popup-candidates .cand-dist {{
    color: #607d8b;
    font-size: 11px;
    margin-left: 4px;
  }}
  .mode-badge {{
    background: rgba(30,30,30,0.85); color:#eee; padding:4px 8px;
    border-radius:4px; font: 11px/1.3 sans-serif;
  }}
  .hirio-pin-wrap, .hirio-pin-wrap.leaflet-div-icon {{
    background: transparent !important;
    border: none !important;
  }}
  .hirio-pin {{
    width: 34px;
    height: 44px;
    text-align: center;
    position: relative;
  }}
  .hirio-pin.selected {{
    width: 44px;
    height: 56px;
  }}
  .hirio-pin-badge {{
    width: 30px;
    height: 30px;
    margin: 0 auto;
    border-radius: 50%;
    border: 2px solid #fff;
    box-shadow: 0 1px 5px rgba(0,0,0,0.45);
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .hirio-pin.selected .hirio-pin-badge {{
    width: 38px;
    height: 38px;
    border: 3px solid #ffeb3b;
    box-shadow: 0 2px 8px rgba(0,0,0,0.55);
  }}
  .hirio-pin-text {{
    color: #fff;
    font: 700 11px/1 "Segoe UI","Meiryo UI","Yu Gothic UI",sans-serif;
    letter-spacing: 0;
  }}
  .hirio-pin.selected .hirio-pin-text {{
    font-size: 13px;
  }}
  .hirio-pin-pointer {{
    width: 0;
    height: 0;
    margin: -1px auto 0;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top-width: 10px;
    border-top-style: solid;
  }}
  .hirio-pin.selected .hirio-pin-pointer {{
    border-left-width: 8px;
    border-right-width: 8px;
    border-top-width: 12px;
  }}
  .hirio-endpoint {{
    position: absolute;
    left: 50%;
    top: -14px;
    transform: translateX(-50%);
    padding: 1px 5px;
    border-radius: 8px;
    font: 700 10px/1.2 "Segoe UI","Meiryo UI",sans-serif;
    color: #fff;
    white-space: nowrap;
    border: 1px solid #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.45);
    z-index: 2;
  }}
  .hirio-endpoint.start {{ background: #2e7d32; }}
  .hirio-endpoint.goal {{ background: #c62828; }}
  .hirio-endpoint.both {{ background: #6a1b9a; }}
  .hirio-pin.selected .hirio-endpoint {{
    top: -16px;
    font-size: 11px;
  }}
  .hirio-pick-num {{
    position: absolute;
    right: -6px;
    top: -6px;
    min-width: 18px;
    height: 18px;
    padding: 0 4px;
    border-radius: 9px;
    background: #e65100;
    color: #fff;
    border: 1px solid #fff;
    font: 700 11px/18px "Segoe UI","Meiryo UI",sans-serif;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.45);
    z-index: 3;
  }}
  .hirio-checked {{
    position: absolute;
    left: -4px;
    top: -4px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #2e7d32;
    color: #fff;
    border: 1px solid #fff;
    font: 700 11px/16px "Segoe UI","Meiryo UI",sans-serif;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.45);
    z-index: 3;
  }}
  .hirio-pin.selected .hirio-checked {{
    width: 18px;
    height: 18px;
    font-size: 12px;
    line-height: 18px;
  }}
  .popup-check-row {{
    margin-top: 6px;
    font-size: 12px;
    color: #1b5e20;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .popup-check-row input {{ margin: 0; }}
  .popup-colloc-status {{
    margin-top: 6px;
    font-size: 12px;
    color: #546e7a;
  }}
  .popup-colloc-cand {{
    margin-top: 6px;
    border-top: 1px solid #cfd8dc;
    padding-top: 6px;
    max-height: 180px;
    overflow-y: auto;
  }}
  .popup-colloc-cand .cand-title {{
    font-weight: bold;
    font-size: 12px;
    margin-bottom: 4px;
  }}
  .popup-colloc-cand .cand-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    padding: 4px 0;
    border-bottom: 1px solid #eceff1;
    font-size: 12px;
  }}
  .popup-colloc-cand .cand-meta {{ color: #607d8b; font-size: 11px; }}
  .popup-colloc-cand button {{
    border: 1px solid #81c784;
    background: #e8f5e9;
    color: #1b5e20;
    border-radius: 4px;
    padding: 3px 8px;
    font: 12px/1.2 "Segoe UI","Meiryo UI",sans-serif;
    cursor: pointer;
    white-space: nowrap;
  }}
  .legend-checked {{
    display: inline-flex;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #2e7d32;
    color: #fff;
    border: 1px solid #fff;
    margin-right: 6px;
    vertical-align: middle;
    align-items: center;
    justify-content: center;
    font: 700 11px/1 "Segoe UI",sans-serif;
  }}
  body.hirio-pick-mode {{
    cursor: crosshair;
  }}
  body.hirio-pick-mode .hirio-pin {{
    cursor: pointer;
  }}
  .legend-icon {{
    display: inline-flex;
    width: 24px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid #fff;
    margin-right: 6px;
    vertical-align: middle;
    align-items: center;
    justify-content: center;
    font: 700 10px/1 "Segoe UI","Meiryo UI",sans-serif;
    color: #fff;
  }}
  .legend-endpoint {{
    display: inline-block;
    padding: 1px 6px;
    border-radius: 8px;
    margin-right: 6px;
    font: 700 10px/1.2 sans-serif;
    color: #fff;
    border: 1px solid #fff;
    vertical-align: middle;
  }}
  {tile_filter_css}
</style>
</head>
<body>
<div id="map"></div>
<script>
window.__HIRIO_DATA = {data_json};
const map = L.map('map', {{ zoomControl: true }});
window.__HIRIO_MAP = map;
window.__HIRIO_MAP_VIEW = null;
window.__HIRIO_READY = false;

const layerGroup = L.layerGroup().addTo(map);
let legendControl = null;
let modeBadgeControl = null;
const DEFAULT_PIN = '{DEFAULT_PIN_COLOR}';

function hirioRememberView() {{
  try {{
    const c = map.getCenter();
    const view = {{ lat: c.lat, lng: c.lng, zoom: map.getZoom() }};
    window.__HIRIO_MAP_VIEW = view;
    // Python 側へ確実に伝える（titleChanged）
    document.title = 'HIRIO_MAP:' + JSON.stringify(view);
  }} catch (e) {{}}
}}
map.on('moveend', hirioRememberView);
map.on('zoomend', hirioRememberView);

L.tileLayer('{tile_url}', {{
  maxZoom: 19,
  attribution: '{tile_attr}'
}}).addTo(map);

function hirioSetGrayscale(on) {{
  const pane = document.querySelector('.leaflet-tile-pane');
  if (pane) {{
    pane.style.filter = on
      ? 'grayscale(100%) contrast(1.05) brightness(1.05)'
      : '';
  }}
  document.body.style.background = on ? '#e8e8e8' : '#cfd8dc';
  const mapEl = document.getElementById('map');
  if (mapEl) mapEl.style.background = on ? '#e8e8e8' : '#cfd8dc';
}}

function notifyStorePick(store) {{
  if (!window.__HIRIO_PICK_MODE) return;
  try {{
    document.title = 'HIRIO_PICK:' + JSON.stringify({{
      store_code: store.store_code || '',
      member_codes: store.member_codes || []
    }});
  }} catch (e) {{}}
}}

function notifyRouteAction(payload) {{
  try {{
    const body = payload || {{}};
    body._ts = Date.now();
    document.title = 'HIRIO_ROUTE:' + JSON.stringify(body);
  }} catch (e) {{}}
}}

function approxKm(lat1, lng1, lat2, lng2) {{
  const dy = (lat1 - lat2) * 111.0;
  const dx = (lng1 - lng2) * 111.0 * Math.cos((lat1 * Math.PI) / 180);
  return Math.sqrt(dx * dx + dy * dy);
}}

function storeActionPayload(store, extra) {{
  const base = {{
    store_id: store.id || null,
    store_code: store.store_code || '',
    store_name: store.store_name || '',
    member_codes: store.member_codes || [],
    member_ids: store.member_ids || [],
    member_names: store.member_names || [],
    member_brands: store.member_brands || [],
    from_route_code: store.route_code || '',
    from_route_name: store.route_name || '',
    lat: store.lat,
    lng: store.lng
  }};
  if (extra) {{
    Object.keys(extra).forEach(function(k) {{ base[k] = extra[k]; }});
  }}
  return base;
}}

function nearestRouteCandidates(store, limit) {{
  const centers = (window.__HIRIO_DATA && window.__HIRIO_DATA.route_centers) || [];
  const current = (store.route_code || '').trim();
  const lat = store.lat;
  const lng = store.lng;
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return [];
  const rows = [];
  centers.forEach(function(c) {{
    if (!c || !Number.isFinite(c.lat) || !Number.isFinite(c.lng)) return;
    const code = (c.route_code || '').trim();
    if (!code) return;
    if (current && code === current) return;
    rows.push({{
      route_code: code,
      route_name: c.route_name || code,
      km: approxKm(lat, lng, c.lat, c.lng)
    }});
  }});
  rows.sort(function(a, b) {{ return a.km - b.km; }});
  return rows.slice(0, limit || 12);
}}

function bindStorePopup(marker, store, routeName) {{
  const tags = (store.tag_names || []).join(' / ') || '（タグなし）';
  const code = store.store_code ? '[' + store.store_code + '] ' : '';
  const memberRows = (store.members && store.members.length)
    ? store.members
    : (store.member_names || []).map(function(n, i) {{
        return {{
          id: (store.member_ids || [])[i] || null,
          store_code: (store.member_codes || [])[i] || '',
          store_name: n || ''
        }};
      }});
  let extra = '';
  if (memberRows.length > 1 && !window.__HIRIO_PICK_MODE) {{
    extra = '<div class="popup-members"><div class="mem-title">併設（個別に削除可）</div>';
    memberRows.forEach(function(m) {{
      const mid = (m && m.id != null) ? String(m.id) : '';
      const mcode = (m && m.store_code) ? String(m.store_code) : '';
      const mname = (m && m.store_name) ? String(m.store_name) : (mcode || '（無名）');
      extra +=
        '<div class="popup-member-row">' +
          '<div class="mem-name">' + mname +
            (mcode ? ' <span class="mem-code">[' + mcode + ']</span>' : '') +
          '</div>' +
          '<button type="button" class="mem-del hirio-btn-delete-one"' +
            ' data-id="' + mid + '"' +
            ' data-code="' + encodeURIComponent(mcode) + '"' +
            ' data-name="' + encodeURIComponent(mname) + '"' +
          '>削除</button>' +
        '</div>';
    }});
    extra += '</div>';
  }} else if (memberRows.length > 1) {{
    const names = memberRows.map(function(m) {{
      return (m && m.store_name) ? m.store_name : '';
    }}).filter(Boolean);
    extra = '<div>併設: ' + names.join(' / ') + '</div>';
  }}
  const assigned = !!(store.route_code || '').trim();
  const routeLabel = routeName || store.route_name || (assigned ? store.route_code : '未所属');
  const memberBrands = store.member_brands || [];
  const missingBrands = ['HA', 'HO', 'OF'].filter(function(b) {{
    return memberBrands.indexOf(b) < 0;
  }});
  const isHardoff = !!store.is_hardoff_family;
  const showColloc = isHardoff && missingBrands.length > 0;
  const checked = !!store.collocation_checked;
  let hardoffExtra = '';
  if (isHardoff && !window.__HIRIO_PICK_MODE) {{
    hardoffExtra =
      '<label class="popup-check-row">' +
        '<input type="checkbox" class="hirio-chk-colloc"' +
        (checked ? ' checked' : '') + '>' +
        '併設確認済み' +
      '</label>' +
      '<div class="popup-colloc-status"></div>' +
      '<div class="popup-colloc-cand" style="display:none;"></div>';
  }}
  let actions = '';
  if (!window.__HIRIO_PICK_MODE) {{
    const deleteAllLabel = memberRows.length > 1 ? '全店をDBから削除' : 'DBから削除';
    actions =
      '<div class="popup-actions">' +
        (assigned
          ? '<button type="button" class="danger hirio-btn-unassign">ルート解除</button>'
          : '') +
        '<button type="button" class="primary hirio-btn-register">ルート登録</button>' +
        (isHardoff
          ? '<button type="button" class="colloc hirio-btn-auto-colloc">併設を自動確認</button>'
          : '') +
        (showColloc
          ? '<button type="button" class="colloc hirio-btn-colloc">併設店舗登録</button>'
          : '') +
        '<button type="button" class="danger hirio-btn-delete">' + deleteAllLabel + '</button>' +
      '</div>' +
      '<div class="popup-candidates" style="display:none;"></div>';
  }}
  marker.bindPopup(
    '<div class="popup-title">' + code + (store.store_name || '') + '</div>' +
    extra +
    '<div>ルート: ' + routeLabel + '</div>' +
    '<div class="popup-tags">タグ: ' + tags + '</div>' +
    hardoffExtra +
    actions,
    {{ maxWidth: 340 }}
  );
  marker.on('popupopen', function() {{
    if (window.__HIRIO_PICK_MODE) return;
    const root = marker.getPopup() && marker.getPopup().getElement();
    if (!root) return;
    const unBtn = root.querySelector('.hirio-btn-unassign');
    const regBtn = root.querySelector('.hirio-btn-register');
    const collocBtn = root.querySelector('.hirio-btn-colloc');
    const autoBtn = root.querySelector('.hirio-btn-auto-colloc');
    const delBtn = root.querySelector('.hirio-btn-delete');
    const chk = root.querySelector('.hirio-chk-colloc');
    const status = root.querySelector('.popup-colloc-status');
    const candBox = root.querySelector('.popup-candidates');
    const cacheKey = storeCacheKey(store);
    if (chk) {{
      chk.onchange = function() {{
        notifyRouteAction(
          storeActionPayload(store, {{
            action: 'set_collocation_checked',
            checked: !!chk.checked,
            member_brands: memberBrands
          }})
        );
      }};
    }}
    function requestAutoCheck(force) {{
      if (status) status.textContent = force ? 'Googleで再検索中…' : 'Googleで確認中…';
      notifyRouteAction(
        storeActionPayload(store, {{
          action: 'auto_check_collocation',
          member_brands: memberBrands,
          force: !!force,
          cache_key: cacheKey,
          lat: store.lat,
          lng: store.lng
        }})
      );
    }}
    if (autoBtn) {{
      autoBtn.onclick = function(ev) {{
        try {{ L.DomEvent.stop(ev); }} catch (errA) {{}}
        requestAutoCheck(true);
      }};
    }}
    // キャッシュ済み結果を再表示
    const cached = window.__HIRIO_COLLOC_CACHE[cacheKey];
    if (cached && typeof window.__HIRIO_SHOW_COLLOC_CANDIDATES === 'function') {{
      window.__HIRIO_SHOW_COLLOC_CANDIDATES(cached);
    }} else if (
      isHardoff &&
      !checked &&
      missingBrands.length > 0 &&
      !store._autoCheckedOnce
    ) {{
      store._autoCheckedOnce = true;
      requestAutoCheck(false);
    }} else if (status && isHardoff && missingBrands.length <= 0) {{
      status.textContent = 'HA/HO/OF はDB上そろっています';
    }}
    if (unBtn) {{
      unBtn.onclick = function(ev) {{
        try {{ L.DomEvent.stop(ev); }} catch (err) {{}}
        notifyRouteAction(storeActionPayload(store, {{ action: 'unassign' }}));
        try {{ marker.closePopup(); }} catch (err2) {{}}
      }};
    }}
    if (delBtn) {{
      delBtn.onclick = function(ev) {{
        try {{ L.DomEvent.stop(ev); }} catch (errDel) {{}}
        notifyRouteAction(storeActionPayload(store, {{ action: 'delete' }}));
        try {{ marker.closePopup(); }} catch (errDel2) {{}}
      }};
    }}
    root.querySelectorAll('.hirio-btn-delete-one').forEach(function(btn) {{
      btn.onclick = function(ev) {{
        try {{ L.DomEvent.stop(ev); }} catch (errOne) {{}}
        const tid = btn.getAttribute('data-id') || '';
        const tcode = decodeURIComponent(btn.getAttribute('data-code') || '');
        const tname = decodeURIComponent(btn.getAttribute('data-name') || '');
        notifyRouteAction(
          storeActionPayload(store, {{
            action: 'delete_one',
            target_store_id: tid ? Number(tid) : null,
            target_store_code: tcode,
            target_store_name: tname
          }})
        );
        try {{ marker.closePopup(); }} catch (errOne2) {{}}
      }};
    }});
    if (collocBtn) {{
      collocBtn.onclick = function(ev) {{
        try {{ L.DomEvent.stop(ev); }} catch (errCol) {{}}
        notifyRouteAction(
          storeActionPayload(store, {{
            action: 'register_collocation',
            member_brands: memberBrands
          }})
        );
        try {{ marker.closePopup(); }} catch (errCol2) {{}}
      }};
    }}
    if (regBtn && candBox) {{
      regBtn.onclick = function(ev) {{
        try {{ L.DomEvent.stop(ev); }} catch (err) {{}}
        const cands = nearestRouteCandidates(store, 12);
        if (!cands.length) {{
          candBox.style.display = 'block';
          candBox.innerHTML =
            '<div class="cand-title">候補ルートがありません</div>';
          return;
        }}
        let html = '<div class="cand-title">近いルートから選択</div>';
        cands.forEach(function(c) {{
          const dist =
            c.km < 1
              ? Math.round(c.km * 1000) + 'm'
              : c.km.toFixed(1) + 'km';
          html +=
            '<a href="#" class="hirio-cand-route" data-code="' +
            encodeURIComponent(c.route_code) +
            '" data-name="' +
            encodeURIComponent(c.route_name) +
            '">' +
            (c.route_name || c.route_code) +
            '<span class="cand-dist">' +
            dist +
            '</span></a>';
        }});
        candBox.innerHTML = html;
        candBox.style.display = 'block';
        candBox.querySelectorAll('.hirio-cand-route').forEach(function(a) {{
          a.onclick = function(ev2) {{
            try {{ L.DomEvent.stop(ev2); }} catch (err3) {{}}
            try {{ ev2.preventDefault(); }} catch (err4) {{}}
            const rc = decodeURIComponent(a.getAttribute('data-code') || '');
            const rn = decodeURIComponent(a.getAttribute('data-name') || '');
            notifyRouteAction(
              storeActionPayload(store, {{
                action: 'register',
                route_code: rc,
                route_name: rn
              }})
            );
            try {{ marker.closePopup(); }} catch (err5) {{}}
          }};
        }});
      }};
    }}
  }});
  marker.on('click', function(e) {{
    if (!window.__HIRIO_PICK_MODE) return;
    try {{ L.DomEvent.stop(e); }} catch (err) {{}}
    try {{ marker.closePopup(); }} catch (err2) {{}}
    notifyStorePick(store);
  }});
}}

function pickIndexHtml(store) {{
  const n = store.pick_index;
  if (!n) return '';
  return '<div class="hirio-pick-num">' + n + '</div>';
}}

function checkedBadgeHtml(store) {{
  if (!store.is_hardoff_family || !store.collocation_checked) return '';
  return '<div class="hirio-checked" title="併設確認済み">✓</div>';
}}

function storeCacheKey(store) {{
  const id = store.id || store.store_code || '';
  const lat = Number(store.lat || 0).toFixed(5);
  const lng = Number(store.lng || 0).toFixed(5);
  return String(id) + '@' + lat + ',' + lng;
}}

window.__HIRIO_COLLOC_CACHE = window.__HIRIO_COLLOC_CACHE || {{}};

window.__HIRIO_SHOW_COLLOC_CANDIDATES = function(payload) {{
  const data = payload || {{}};
  const key = data.cache_key || '';
  if (key) {{
    window.__HIRIO_COLLOC_CACHE[key] = data;
  }}
  const root = document.querySelector('.leaflet-popup-content');
  if (!root) return;
  const box = root.querySelector('.popup-colloc-cand');
  const status = root.querySelector('.popup-colloc-status');
  if (!box) return;
  if (data.error) {{
    if (status) status.textContent = data.error;
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }}
  const cands = data.candidates || [];
  if (status) {{
    status.textContent = cands.length
      ? ('Google検索: ' + cands.length + '件の併設候補')
      : (data.message || '近くに未登録の併設は見つかりませんでした');
  }}
  if (!cands.length) {{
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }}
  let html = '<div class="cand-title">未登録の併設候補</div>';
  cands.forEach(function(c, idx) {{
    const dist = (c.distance_m != null)
      ? (c.distance_m < 1000
          ? Math.round(c.distance_m) + 'm'
          : (c.distance_m / 1000).toFixed(1) + 'km')
      : '';
    html +=
      '<div class="cand-row">' +
        '<div>' +
          '<div>' + (c.store_name || c.brand_label || '') + '</div>' +
          '<div class="cand-meta">' + (c.brand_label || '') +
            (dist ? (' · ' + dist) : '') + '</div>' +
        '</div>' +
        '<button type="button" class="hirio-btn-cand-reg" data-idx="' + idx + '">登録</button>' +
      '</div>';
  }});
  box.innerHTML = html;
  box.style.display = 'block';
  box.querySelectorAll('.hirio-btn-cand-reg').forEach(function(btn) {{
    btn.onclick = function(ev) {{
      try {{ L.DomEvent.stop(ev); }} catch (err) {{}}
      const i = parseInt(btn.getAttribute('data-idx') || '-1', 10);
      const cand = cands[i];
      if (!cand) return;
      notifyRouteAction({{
        action: 'register_collocation_candidate',
        store_id: data.store_id || null,
        store_code: data.store_code || '',
        store_name: data.store_name || '',
        member_codes: data.member_codes || [],
        member_ids: data.member_ids || [],
        member_brands: data.member_brands || [],
        candidate: cand
      }});
    }};
  }});
}};

function endpointLabel(endpoint) {{
  if (endpoint === 'start') return 'スタート';
  if (endpoint === 'goal') return 'ゴール';
  if (endpoint === 'both') return '始/終';
  return '';
}}

function endpointHtml(endpoint) {{
  const label = endpointLabel(endpoint);
  if (!label) return '';
  return '<div class="hirio-endpoint ' + endpoint + '">' + label + '</div>';
}}

// 画面上で近接するピンをずらし、本物座標へ脚を伸ばす
const OVERLAP_PX = 28;
const OFFSET_PX = 22;

function storeDisplayLatLng(store) {{
  const lat = Number.isFinite(store.displayLat) ? store.displayLat : store.lat;
  const lng = Number.isFinite(store.displayLng) ? store.displayLng : store.lng;
  return [lat, lng];
}}

function addOffsetStem(trueLat, trueLng, dispLat, dispLng, color) {{
  L.polyline(
    [[trueLat, trueLng], [dispLat, dispLng]],
    {{
      color: color || DEFAULT_PIN,
      weight: 2.5,
      opacity: 0.9,
      interactive: false
    }}
  ).addTo(layerGroup);
  L.circleMarker([trueLat, trueLng], {{
    radius: 3.5,
    color: '#ffffff',
    weight: 1.5,
    fillColor: color || DEFAULT_PIN,
    fillOpacity: 1,
    interactive: false
  }}).addTo(layerGroup);
}}

function applyOverlapOffsets(entries) {{
  // entries: {{ store, lat, lng }} — 画面ピクセル距離で近接グループ化し displayLat/Lng を付与
  entries.forEach(function(e) {{
    e.store.displayLat = e.lat;
    e.store.displayLng = e.lng;
    e.store.hasOffset = false;
  }});
  const n = entries.length;
  if (n < 2) return;
  try {{
    const sz = map.getSize();
    if (!sz || sz.x < 40 || sz.y < 40) {{
      try {{ map.invalidateSize(false); }} catch (e0) {{}}
      return; // サイズ未確定のときはずらさず本物座標のまま
    }}
  }} catch (e1) {{
    return;
  }}

  const points = [];
  for (let i = 0; i < n; i++) {{
    const pt = map.latLngToLayerPoint(L.latLng(entries[i].lat, entries[i].lng));
    points.push({{ x: pt.x, y: pt.y }});
  }}

  const parent = [];
  for (let i = 0; i < n; i++) parent[i] = i;
  function find(a) {{
    while (parent[a] !== a) {{
      parent[a] = parent[parent[a]];
      a = parent[a];
    }}
    return a;
  }}
  function union(a, b) {{
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent[ra] = rb;
  }}

  const thresh2 = OVERLAP_PX * OVERLAP_PX;
  for (let i = 0; i < n; i++) {{
    for (let j = i + 1; j < n; j++) {{
      const dx = points[i].x - points[j].x;
      const dy = points[i].y - points[j].y;
      if (dx * dx + dy * dy <= thresh2) union(i, j);
    }}
  }}

  const groups = {{}};
  for (let i = 0; i < n; i++) {{
    const r = find(i);
    if (!groups[r]) groups[r] = [];
    groups[r].push(i);
  }}

  Object.keys(groups).forEach(function(key) {{
    const idxs = groups[key];
    if (idxs.length < 2) return;
    const count = idxs.length;
    idxs.forEach(function(i, k) {{
      let ox = 0;
      let oy = 0;
      if (count === 2) {{
        ox = (k === 0) ? -OFFSET_PX : OFFSET_PX;
        oy = -10;
      }} else {{
        const start = -Math.PI * 0.85;
        const end = -Math.PI * 0.15;
        const t = k / (count - 1);
        const angle = start + (end - start) * t;
        const radius = OFFSET_PX + Math.min(count - 2, 5) * 5;
        ox = Math.cos(angle) * radius;
        oy = Math.sin(angle) * radius;
      }}
      const base = map.latLngToLayerPoint(L.latLng(entries[i].lat, entries[i].lng));
      const dispLl = map.layerPointToLatLng(L.point(base.x + ox, base.y + oy));
      entries[i].store.displayLat = dispLl.lat;
      entries[i].store.displayLng = dispLl.lng;
      entries[i].store.hasOffset = true;
    }});
  }});
}}

function bindRouteFocusOnDblClick(layer, routeCode) {{
  if (!layer || !routeCode) return;
  layer.on('dblclick', function(e) {{
    try {{ L.DomEvent.stop(e); }} catch (err) {{}}
    if (window.__HIRIO_PICK_MODE) return;
    const code = String(routeCode || '').trim();
    if (!code) return;
    notifyRouteAction({{ action: 'focus', route_code: code }});
  }});
}}

function bindStoreFocusOnDblClick(marker, store) {{
  if (!marker || !store) return;
  marker.on('dblclick', function(e) {{
    try {{ L.DomEvent.stop(e); }} catch (err) {{}}
    if (window.__HIRIO_PICK_MODE) return;
    const code = String(store.route_code || '').trim();
    if (!code) {{
      // 未所属はルート選択できない
      return;
    }}
    notifyRouteAction({{
      action: 'focus',
      route_code: code,
      store_code: store.store_code || '',
      store_id: store.id || null
    }});
  }});
}}

function addCircle(store, routeName) {{
  const skipped = store.will_visit === false;
  const selected = !!store.selected;
  const endpoint = store.endpoint || '';
  const radius = selected ? 12 : (endpoint ? 10 : 8);
  const fill = skipped ? '{SKIPPED_PIN_COLOR}' : (store.pin_color || DEFAULT_PIN);
  const disp = storeDisplayLatLng(store);
  if (store.hasOffset) {{
    addOffsetStem(store.lat, store.lng, disp[0], disp[1], fill);
  }}
  const marker = L.circleMarker(disp, {{
    radius: radius,
    color: selected ? '#ffeb3b' : '#ffffff',
    weight: selected ? 3 : 1.5,
    fillColor: fill,
    fillOpacity: skipped ? 0.75 : 0.95
  }});
  bindStorePopup(marker, store, routeName);
  bindStoreFocusOnDblClick(marker, store);
  marker.addTo(layerGroup);
  if (endpoint || (store.is_hardoff_family && store.collocation_checked)) {{
    const tip = L.marker(disp, {{
      icon: L.divIcon({{
        className: 'hirio-pin-wrap',
        html: '<div style="position:relative;width:1px;height:1px;">' +
              endpointHtml(endpoint) +
              checkedBadgeHtml(store) +
              '</div>',
        iconSize: [1, 1],
        iconAnchor: [0, 28]
      }}),
      interactive: false,
      keyboard: false
    }});
    tip.addTo(layerGroup);
  }}
}}

function addIconMarker(store, routeName, icons) {{
  const key = store.icon_key || 'other';
  const spec = (icons && icons[key]) || (icons && icons.other) || {{ bg: DEFAULT_PIN, text: '他', fg: '#ffffff' }};
  const skipped = store.will_visit === false;
  const selected = !!store.selected;
  const endpoint = store.endpoint || '';
  const bg = skipped ? '{SKIPPED_PIN_COLOR}' : (spec.bg || DEFAULT_PIN);
  const fg = skipped ? '#ffffff' : (spec.fg || '#ffffff');
  const text = spec.text || '他';
  const pinClass = 'hirio-pin' + (selected ? ' selected' : '');
  const size = selected ? [44, 56] : [34, 44];
  const anchor = selected ? [22, 54] : [17, 42];
  const disp = storeDisplayLatLng(store);
  if (store.hasOffset) {{
    addOffsetStem(store.lat, store.lng, disp[0], disp[1], bg);
  }}
  const html =
    '<div class="' + pinClass + '">' +
      endpointHtml(endpoint) +
      pickIndexHtml(store) +
      checkedBadgeHtml(store) +
      '<div class="hirio-pin-badge" style="background:' + bg + '">' +
        '<span class="hirio-pin-text" style="color:' + fg + '">' + text + '</span>' +
      '</div>' +
      '<div class="hirio-pin-pointer" style="border-top-color:' + bg + '"></div>' +
    '</div>';
  const marker = L.marker(disp, {{
    icon: L.divIcon({{
      className: 'hirio-pin-wrap',
      html: html,
      iconSize: size,
      iconAnchor: anchor,
      popupAnchor: [0, selected ? -48 : -36]
    }}),
    keyboard: false,
    opacity: skipped ? 0.85 : 1,
    zIndexOffset: selected ? 600 : (store.pick_index ? 500 : (endpoint ? 400 : (store.hasOffset ? 200 : 0)))
  }});
  bindStorePopup(marker, store, routeName);
  bindStoreFocusOnDblClick(marker, store);
  marker.addTo(layerGroup);
}}

function addRouteLine(pts, color, weight, opacity, dashed, routeCode) {{
  const optsHalo = {{
    color: '#ffffff',
    weight: weight + 2,
    opacity: dashed ? 0.35 : 0.7,
    interactive: false
  }};
  const optsMain = {{
    color: color,
    weight: weight,
    opacity: opacity,
    interactive: false
  }};
  if (dashed) {{
    optsHalo.dashArray = '4 8';
    optsMain.dashArray = '4 8';
  }}
  L.polyline(pts, optsHalo).addTo(layerGroup);
  L.polyline(pts, optsMain).addTo(layerGroup);
  // ダブルクリック用の透明な太いヒット領域
  const code = String(routeCode || '').trim();
  if (code) {{
    const hit = L.polyline(pts, {{
      color: color,
      weight: Math.max(weight + 12, 16),
      opacity: 0.0,
      interactive: true,
      bubblingMouseEvents: false
    }});
    hit.addTo(layerGroup);
    hit.bindTooltip('ダブルクリックでこのルートを選択', {{
      sticky: true,
      opacity: 0.85,
      direction: 'top'
    }});
    bindRouteFocusOnDblClick(hit, code);
  }}
}}

function hirioUpdateLegend(data) {{
  if (legendControl) {{
    map.removeControl(legendControl);
    legendControl = null;
  }}
  if (modeBadgeControl) {{
    map.removeControl(modeBadgeControl);
    modeBadgeControl = null;
  }}
  const useIcons = !!data.use_icons;
  const icons = data.map_icons || {{}};
  legendControl = L.control({{ position: 'bottomleft' }});
  legendControl.onAdd = function() {{
    const div = L.DomUtil.create('div', 'legend');
    let html = '<div style="font-weight:bold;margin-bottom:4px;">凡例</div>';
    if (useIcons) {{
      (data.icon_legend || []).forEach(function(row) {{
        const spec = icons[row.key] || icons.other || {{}};
        const bg = spec.bg || row.bg || '#888';
        const fg = spec.fg || '#fff';
        const text = spec.text || row.text || '';
        html += '<div><span class="legend-icon" style="background:' + bg + ';color:' + fg + '">' +
                text + '</span>' + (row.label || spec.label || '') + '</div>';
      }});
    }} else {{
      html += '<div><span class="swatch" style="background:' + DEFAULT_PIN + '"></span>標準（青）</div>';
      (data.tag_legend || []).forEach(function(t) {{
        html += '<div><span class="swatch" style="background:' + (t.color||'#888') + '"></span>' +
                (t.name||'') + '</div>';
      }});
    }}
    if (data.show_endpoints) {{
      html += '<div style="margin-top:6px;"><span class="legend-endpoint" style="background:#2e7d32;">スタート</span>開始店舗</div>';
      html += '<div><span class="legend-endpoint" style="background:#c62828;">ゴール</span>終了店舗</div>';
    }}
    if (data.show_collocation_checked) {{
      html += '<div style="margin-top:6px;"><span class="legend-checked">✓</span>併設確認済み</div>';
    }}
    div.innerHTML = html;
    return div;
  }};
  legendControl.addTo(map);

  modeBadgeControl = L.control({{ position: 'topright' }});
  modeBadgeControl.onAdd = function() {{
    const div = L.DomUtil.create('div', 'mode-badge');
    if (data.pick_mode) {{
      div.textContent = '訪問順クリック選択中';
      div.style.background = 'rgba(230,81,0,0.92)';
    }} else {{
      div.textContent = data.grayscale ? '白黒地図' : 'カラー地図';
    }}
    return div;
  }};
  modeBadgeControl.addTo(map);
}}

let hirioUpdating = false;
let hirioZoomRedrawTimer = null;
let hirioFromZoomRedraw = false;

// ピン・線だけ描き直す。fit=false なら拡大位置は絶対に変えない
window.__HIRIO_UPDATE = function(data, opts) {{
  opts = opts || {{}};
  if (hirioUpdating) return false;
  hirioUpdating = true;
  try {{
  try {{ map.invalidateSize(false); }} catch (eInv) {{}}
  window.__HIRIO_DATA = data || {{}};
  window.__HIRIO_PICK_MODE = !!data.pick_mode;
  try {{
    document.body.classList.toggle('hirio-pick-mode', !!data.pick_mode);
  }} catch (e) {{}}
  const useIcons = !!data.use_icons;
  const icons = data.map_icons || {{}};
  const grayscale = !!data.grayscale;
  const lineWeight = grayscale ? 5 : 4;
  const lineOpacity = grayscale ? 0.95 : 0.85;
  const dashWeight = grayscale ? 4 : 3;
  const bounds = [];

  hirioSetGrayscale(grayscale);
  layerGroup.clearLayers();
  const selectedCode = (data.selected_store_code || '').trim();

  // 1) 全ピンを集め、近接なら画面上でずらす（ルート線は本物座標のまま）
  const pinEntries = [];
  (data.routes || []).forEach(function(route) {{
    (route.stores || []).forEach(function(s) {{
      if (!Number.isFinite(s.lat) || !Number.isFinite(s.lng)) return;
      bounds.push([s.lat, s.lng]);
      if (s.suppress_pin) return;  // ルート線用のみ（クロスルート併設でピン統合済み）
      const codes = [s.store_code || ''].concat(s.member_codes || []);
      s.selected = !!(selectedCode && codes.indexOf(selectedCode) >= 0);
      s.route_code = route.route_code || '';
      s.route_name = route.route_name || '';
      pinEntries.push({{ store: s, lat: s.lat, lng: s.lng, routeName: route.route_name }});
    }});
  }});
  (data.unassigned || []).forEach(function(s) {{
    if (!Number.isFinite(s.lat) || !Number.isFinite(s.lng)) return;
    bounds.push([s.lat, s.lng]);
    if (s.suppress_pin) return;
    s.route_code = '';
    s.route_name = '';
    pinEntries.push({{ store: s, lat: s.lat, lng: s.lng, routeName: '未所属' }});
  }});
  applyOverlapOffsets(pinEntries);

  // 2) ルート線（本物の lat/lng）
  // 訪問順クリック選択中: 編集中ルートの既存線だけ消し、クリック順の線だけ伸ばす。
  // 他ルートの線はそのまま残して見やすくする。
  const editingCode = (data.editing_route_code || '').trim();
  (data.routes || []).forEach(function(route) {{
    const color = route.line_color || '#1e88e5';
    const routeCode = (route.route_code || '').trim();
    const visitPts = [];
    const skipStores = [];
    const pickPts = [];
    (route.stores || []).forEach(function(s) {{
      if (!Number.isFinite(s.lat) || !Number.isFinite(s.lng)) return;
      if (s.pick_index) {{
        pickPts.push({{ idx: s.pick_index, lat: s.lat, lng: s.lng }});
      }}
      if (s.will_visit === false) {{
        skipStores.push(s);
      }} else {{
        visitPts.push([s.lat, s.lng]);
      }}
    }});
    const isEditingRoute =
      !!data.pick_mode && !!editingCode && routeCode === editingCode;
    if (isEditingRoute) {{
      // 編集中ルート: 既存の周回線は出さない。クリックした分だけ線を伸ばす
      if (pickPts.length >= 2) {{
        pickPts.sort(function(a, b) {{ return a.idx - b.idx; }});
        const pts = pickPts.map(function(p) {{ return [p.lat, p.lng]; }});
        addRouteLine(pts, color, dashWeight, lineOpacity, false, routeCode);
      }}
    }} else if ((route.road_polyline || []).length >= 2) {{
      addRouteLine(route.road_polyline, color, lineWeight, lineOpacity, false, routeCode);
    }} else if (visitPts.length >= 2) {{
      addRouteLine(visitPts, color, dashWeight, lineOpacity, false, routeCode);
    }}
    // 行かない店: 最後に訪問する店から薄い点線（編集中ルートの選択モード中は非表示）
    if (!isEditingRoute && visitPts.length >= 1 && skipStores.length) {{
      const last = visitPts[visitPts.length - 1];
      skipStores.forEach(function(s) {{
        addRouteLine(
          [last, [s.lat, s.lng]],
          color,
          2,
          0.45,
          true,
          routeCode
        );
      }});
    }}
  }});

  // 3) ピン（ずらした表示座標。脚は本物へ）
  pinEntries.forEach(function(e) {{
    if (useIcons) addIconMarker(e.store, e.routeName, icons);
    else addCircle(e.store, e.routeName);
  }});

  hirioUpdateLegend(data);

  if (opts.fit) {{
    const savedView = data.saved_view || null;
    if (
      savedView &&
      Number.isFinite(savedView.lat) &&
      Number.isFinite(savedView.lng) &&
      Number.isFinite(savedView.zoom)
    ) {{
      map.setView([savedView.lat, savedView.lng], savedView.zoom);
    }} else if (bounds.length) {{
      map.fitBounds(bounds, {{ padding: [40, 40] }});
    }} else {{
      map.setView([35.68, 139.76], 10);
    }}
  }}
  hirioRememberView();
  window.__HIRIO_READY = true;
  return true;
  }} finally {{
    hirioUpdating = false;
  }}
}};

// ズームが変わると画面上の近接関係が変わるので、ずらしをやり直す
// fitBounds 中の zoomend は UPDATE 完了後に回す（ずらし量を最終ズームで再計算）
map.on('zoomend', function() {{
  if (!window.__HIRIO_DATA || hirioFromZoomRedraw) return;
  if (hirioZoomRedrawTimer) clearTimeout(hirioZoomRedrawTimer);
  hirioZoomRedrawTimer = setTimeout(function() {{
    hirioZoomRedrawTimer = null;
    if (!window.__HIRIO_DATA || hirioFromZoomRedraw || hirioUpdating) return;
    hirioFromZoomRedraw = true;
    try {{
      window.__HIRIO_UPDATE(window.__HIRIO_DATA, {{ fit: false }});
    }} finally {{
      hirioFromZoomRedraw = false;
    }}
  }}, 80);
}});

window.__HIRIO_FIT_BOUNDS = function(points) {{
  if (!points || !points.length) return false;
  try {{ map.invalidateSize(false); }} catch (eInv2) {{}}
  const bounds = [];
  points.forEach(function(p) {{
    if (p && Number.isFinite(p[0]) && Number.isFinite(p[1])) {{
      bounds.push([p[0], p[1]]);
    }}
  }});
  if (!bounds.length) return false;
  map.fitBounds(bounds, {{ padding: [48, 48], maxZoom: 14 }});
  hirioRememberView();
  return true;
}};

window.__HIRIO_UPDATE(window.__HIRIO_DATA, {{ fit: true }});
</script>
</body>
</html>
"""


class RouteMapWidget(QWidget):
    """ルート地図タブ。"""

    routes_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = StoreDatabase()
        self._payload_cache: Optional[Dict[str, Any]] = None
        self._route_checks: Dict[str, QCheckBox] = {}
        self._route_colors: Dict[str, str] = {}
        self._route_names: Dict[str, str] = {}
        self._tag_checks: Dict[int, QCheckBox] = {}
        self._editing_route_code: str = ""
        self._editing_route_name: str = ""
        self._selected_store_code: str = ""
        self._pick_mode: bool = False
        self._pick_order: List[str] = []
        self._pick_baseline_rows: List[Dict[str, Any]] = []
        self._pick_history: List[List[str]] = [[]]
        self._pick_history_index: int = 0
        self._visit_reorder_busy = False
        self._brand_tags_synced = False
        self._splitter_sizes_restored = False
        self._saved_map_view: Optional[Dict[str, float]] = None
        self._map_ready = False
        # 併設自動確認のセッションキャッシュ（API連打防止）
        self._colloc_search_cache: Dict[str, Dict[str, Any]] = {}
        self.setup_ui()
        self._saved_map_view = self._load_map_view_settings()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.reload_btn = QPushButton("再読込")
        self.reload_btn.clicked.connect(self.reload)
        toolbar.addWidget(self.reload_btn)

        self.tags_btn = QPushButton("タグ管理")
        self.tags_btn.clicked.connect(self.open_tags_dialog)
        toolbar.addWidget(self.tags_btn)

        self.show_unassigned_check = QCheckBox("未所属も表示")
        self.show_unassigned_check.setStyleSheet(_checkbox_style("#e0e0e0"))
        self.show_unassigned_check.toggled.connect(self._on_options_changed)
        toolbar.addWidget(self.show_unassigned_check)

        self.grayscale_check = QCheckBox("白黒地図")
        self.grayscale_check.setChecked(True)
        self.grayscale_check.setStyleSheet(_checkbox_style("#e0e0e0"))
        self.grayscale_check.setToolTip(
            "ON: 地図を白黒表示（ルート線・ピンの色はそのまま見やすくなります）\n"
            "OFF: 通常のカラー地図（OpenStreetMap）\n"
            "※追加の API キーは不要です"
        )
        self.grayscale_check.toggled.connect(self._on_options_changed)
        toolbar.addWidget(self.grayscale_check)

        self.icon_check = QCheckBox("店舗ラベル")
        self.icon_check.setChecked(True)
        self.icon_check.setStyleSheet(_checkbox_style("#e0e0e0"))
        self.icon_check.setToolTip(
            "ON: BO / SS / TR / H1〜H3 の文字ラベルで表示します\n"
            "OFF: 青い丸ピン（評価・メモタグがある店だけその色）"
        )
        self.icon_check.toggled.connect(self._on_options_changed)
        toolbar.addWidget(self.icon_check)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        left = QWidget()
        left.setObjectName("routeMapLeftPanel")
        left.setStyleSheet(
            """
            QWidget#routeMapLeftPanel { background: #1e1e1e; }
            QPushButton {
                background: #2e7d32; color: #ffffff; border: none;
                padding: 5px 10px; border-radius: 4px;
            }
            QPushButton:disabled { background: #424242; color: #9e9e9e; }
            QPushButton:hover:!disabled { background: #388e3c; }
            QLabel { color: #cfd8dc; }
            """
        )
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        settings = self._settings()
        routes_expanded = self._settings_bool(settings.value(SETTINGS_COLLAPSE_ROUTES, True), True)
        visits_expanded = self._settings_bool(settings.value(SETTINGS_COLLAPSE_VISITS, True), True)
        tags_expanded = self._settings_bool(settings.value(SETTINGS_COLLAPSE_TAGS, True), True)

        self.left_splitter = QSplitter(Qt.Vertical)
        self.left_splitter.setChildrenCollapsible(False)
        self.left_splitter.setHandleWidth(6)
        self.left_splitter.setStyleSheet(
            """
            QSplitter::handle:vertical {
                background: #3a3a3a;
                margin: 1px 0;
            }
            QSplitter::handle:vertical:hover { background: #5a5a5a; }
            """
        )

        self.route_section = CollapsibleSection(
            "ルート（チェックで表示）", expanded=bool(routes_expanded)
        )
        self.route_section.toggled.connect(self._on_route_section_toggled)
        route_btns = QHBoxLayout()
        self.select_all_btn = QPushButton("全選択")
        self.select_all_btn.clicked.connect(self.select_all_routes)
        route_btns.addWidget(self.select_all_btn)
        self.clear_btn = QPushButton("全解除")
        self.clear_btn.setToolTip("ルートの表示チェックをすべて外します")
        self.clear_btn.clicked.connect(self.clear_route_selection)
        route_btns.addWidget(self.clear_btn)
        self.clear_edit_route_btn = QPushButton("ルート選択解除")
        self.clear_edit_route_btn.setToolTip(
            "編集中ルートの選択だけ解除します（地図の拡大／位置はそのまま）"
        )
        self.clear_edit_route_btn.setStyleSheet(
            "QPushButton { background: #546e7a; color: #ffffff; border: none;"
            " padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:hover:!disabled { background: #607d8b; }"
            "QPushButton:disabled { background: #424242; color: #9e9e9e; }"
        )
        self.clear_edit_route_btn.clicked.connect(
            lambda: self.clear_editing_route_focus(fit_all=False)
        )
        route_btns.addWidget(self.clear_edit_route_btn)
        route_btns.addStretch()
        self.route_section.body_layout.addLayout(route_btns)

        self.route_scroll = QScrollArea()
        self.route_scroll.setWidgetResizable(True)
        self.route_scroll.setFrameShape(QFrame.NoFrame)
        self.route_scroll.setStyleSheet(
            "QScrollArea { background: #1e1e1e; border: none; }"
        )
        self.route_list_host = QWidget()
        self.route_list_host.setStyleSheet("background: #1e1e1e;")
        self.route_list_box = QVBoxLayout(self.route_list_host)
        self.route_list_box.setContentsMargins(4, 4, 4, 4)
        self.route_list_box.setSpacing(2)
        self.route_list_box.addStretch()
        self.route_scroll.setWidget(self.route_list_host)
        self.route_section.body_layout.addWidget(self.route_scroll, 1)
        self.left_splitter.addWidget(self.route_section)

        self.visit_section = CollapsibleSection(
            "店舗（ルートをダブルクリック）", expanded=bool(visits_expanded)
        )
        self.visit_section.toggled.connect(self._on_visit_section_toggled)
        self.visit_hint = QLabel(
            "ルート名をダブルクリック → 店舗一覧。\n"
            "地図の店舗ピン／ルート線をダブルクリックでも選択できます。\n"
            "チェックOFF＝行かない（地図でグレー＋最後尾から点線）。\n"
            "地図上で訪問順序選択では、選ばなかった店のチェックは自動でOFFになります。\n"
            "「ルートから外す」でこのグループから削除（店舗自体はDBに残ります）。\n"
            "「訪問順序反転」で周回順を逆にできます。\n"
            "ドラッグで周回順変更（マスタ表示順＋最新ルート登録へ保存）。\n"
            "区切り線をドラッグで各パネルの高さを変更できます。"
        )
        self.visit_hint.setWordWrap(True)
        self.visit_hint.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        self.visit_section.body_layout.addWidget(self.visit_hint)

        visit_btns = QHBoxLayout()
        self.reverse_visit_order_btn = QPushButton("訪問順序反転")
        self.reverse_visit_order_btn.setToolTip(
            "店舗の周回順を逆にします（スタート⇔ゴール）。\n"
            "反転後は自動で保存されます。"
        )
        self.reverse_visit_order_btn.setStyleSheet(
            "QPushButton { background: #1565c0; color: #ffffff; border: none;"
            " padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:disabled { background: #424242; color: #9e9e9e; }"
            "QPushButton:hover:!disabled { background: #1e88e5; }"
        )
        self.reverse_visit_order_btn.clicked.connect(self.reverse_editing_visit_order)
        self.reverse_visit_order_btn.setEnabled(False)
        visit_btns.addWidget(self.reverse_visit_order_btn)
        self.save_visit_order_btn = QPushButton("訪問順序保存")
        self.save_visit_order_btn.setToolTip(
            "いまの並びと訪問チェックを店舗マスタ表示順・"
            "テンプレート出力フラグ＋最新ルート登録の訪問順へ保存"
        )
        self.save_visit_order_btn.clicked.connect(self.save_editing_visit_order)
        self.save_visit_order_btn.setEnabled(False)
        visit_btns.addWidget(self.save_visit_order_btn)
        self.web_template_btn = QPushButton("WEBテンプレート作成")
        self.web_template_btn.setToolTip(
            "いまの訪問順（チェックONの店）で Webテンプレートを作成します。\n"
            "日付選択ダイアログが開き、GoogleマップURLも生成できます。"
        )
        self.web_template_btn.setStyleSheet(
            "QPushButton { background: #0d6efd; color: #ffffff; border: none;"
            " padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:disabled { background: #424242; color: #9e9e9e; }"
            "QPushButton:hover:!disabled { background: #0b5ed7; }"
        )
        self.web_template_btn.clicked.connect(self.open_web_template_dialog)
        self.web_template_btn.setEnabled(False)
        visit_btns.addWidget(self.web_template_btn)
        self.remove_from_route_btn = QPushButton("ルートから外す")
        self.remove_from_route_btn.setToolTip(
            "選んだ店舗を、いま編集中のルート（グループ）から外します。\n"
            "店舗データ自体はDBに残ります（地図ポップアップのDB削除とは違います）。\n"
            "リストを右クリック、または Delete キーでも同じ操作ができます。"
        )
        self.remove_from_route_btn.setStyleSheet(
            "QPushButton { background: #c62828; color: #ffffff; border: none;"
            " padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:disabled { background: #424242; color: #9e9e9e; }"
            "QPushButton:hover:!disabled { background: #e53935; }"
        )
        self.remove_from_route_btn.clicked.connect(
            self.remove_selected_store_from_editing_route
        )
        self.remove_from_route_btn.setEnabled(False)
        visit_btns.addWidget(self.remove_from_route_btn)
        visit_btns.addStretch()
        self.visit_section.body_layout.addLayout(visit_btns)

        self.visit_list = QListWidget()
        self.visit_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.visit_list.setDefaultDropAction(Qt.MoveAction)
        self.visit_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.visit_list.setAlternatingRowColors(True)
        self.visit_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.visit_list.setStyleSheet(
            """
            QListWidget {
                background: #252525; color: #f0f0f0;
                border: 1px solid #444444; alternate-background-color: #2c2c2c;
            }
            QListWidget::item:selected { background: #1565c0; color: #ffffff; }
            QListWidget::indicator {
                width: 16px; height: 16px;
                border: 2px solid #cfd8dc; border-radius: 3px;
                background: #2b2b2b;
            }
            QListWidget::indicator:checked {
                background: #4caf50; border: 2px solid #81c784;
            }
            QListWidget::indicator:unchecked {
                background: #2b2b2b; border: 2px solid #cfd8dc;
            }
            """
        )
        self.visit_list.model().rowsMoved.connect(self._on_visit_rows_moved)
        self.visit_list.itemChanged.connect(self._on_visit_item_changed)
        self.visit_list.currentItemChanged.connect(self._on_visit_current_changed)
        self.visit_list.customContextMenuRequested.connect(
            self._on_visit_list_context_menu
        )
        self._visit_delete_shortcut = QShortcut(QKeySequence.Delete, self.visit_list)
        self._visit_delete_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._visit_delete_shortcut.activated.connect(
            self.remove_selected_store_from_editing_route
        )
        self.visit_section.body_layout.addWidget(self.visit_list, 1)
        self.left_splitter.addWidget(self.visit_section)

        self.tag_section = CollapsibleSection(
            "タグで絞り込み（評価・メモ）", expanded=bool(tags_expanded)
        )
        self.tag_section.toggled.connect(self._on_tag_section_toggled)
        tag_btns = QHBoxLayout()
        self.tag_select_all_btn = QPushButton("全選択")
        self.tag_select_all_btn.setToolTip("評価・メモタグをすべて選択します")
        self.tag_select_all_btn.clicked.connect(self.select_all_tags)
        tag_btns.addWidget(self.tag_select_all_btn)
        self.tag_clear_btn = QPushButton("全解除")
        self.tag_clear_btn.setToolTip("評価・メモタグをすべて解除します")
        self.tag_clear_btn.clicked.connect(self.clear_tag_selection)
        tag_btns.addWidget(self.tag_clear_btn)
        tag_btns.addStretch()
        self.tag_section.body_layout.addLayout(tag_btns)

        self.quality_tag_scroll = QScrollArea()
        self.quality_tag_scroll.setWidgetResizable(True)
        self.quality_tag_scroll.setFrameShape(QFrame.NoFrame)
        self.quality_tag_scroll.setStyleSheet(
            "QScrollArea { background: #1e1e1e; border: none; }"
        )
        self.quality_tag_host = QWidget()
        self.quality_tag_host.setStyleSheet("background: #1e1e1e;")
        self.quality_tag_box = QVBoxLayout(self.quality_tag_host)
        self.quality_tag_box.setContentsMargins(4, 4, 4, 4)
        self.quality_tag_box.setSpacing(2)
        self.quality_tag_scroll.setWidget(self.quality_tag_host)
        self.tag_section.body_layout.addWidget(self.quality_tag_scroll, 1)

        self.tag_filter_box = self.quality_tag_box
        self.tag_tabs = None
        self.brand_tag_box = self.quality_tag_box

        self.include_untagged_check = QCheckBox("評価タグなし店舗も表示")
        self.include_untagged_check.setChecked(True)
        self.include_untagged_check.setStyleSheet(_checkbox_style("#e0e0e0"))
        self.include_untagged_check.setToolTip(
            "評価・メモタグが付いていない店舗も地図に出します"
        )
        self.include_untagged_check.toggled.connect(self._on_options_changed)
        self.tag_section.body_layout.addWidget(self.include_untagged_check)
        self.left_splitter.addWidget(self.tag_section)

        self.left_splitter.setStretchFactor(0, 2)
        self.left_splitter.setStretchFactor(1, 3)
        self.left_splitter.setStretchFactor(2, 2)
        self.left_splitter.splitterMoved.connect(self._save_splitter_sizes)
        left_layout.addWidget(self.left_splitter, 1)

        left.setMinimumWidth(220)

        self.main_splitter.addWidget(left)

        right = QGroupBox("地図")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(4)

        # 1行だけの細いツールバー（余白で地図を潰さない）
        map_toolbar_host = QWidget()
        map_toolbar_host.setObjectName("routeMapPickToolbar")
        map_toolbar_host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        map_toolbar_host.setFixedHeight(30)
        map_toolbar_host.setStyleSheet(
            "QWidget#routeMapPickToolbar { background: transparent; }"
        )
        map_toolbar = QHBoxLayout(map_toolbar_host)
        map_toolbar.setContentsMargins(0, 0, 0, 0)
        map_toolbar.setSpacing(4)
        _pick_btn_css = (
            "QPushButton {"
            " background: #455a64; color: #ffffff; border: none;"
            " padding: 2px 8px; border-radius: 4px; font-size: 12px;"
            "}"
            "QPushButton:hover:!disabled { background: #546e7a; }"
            "QPushButton:disabled { background: #37474f; color: #78909c; }"
        )
        self.pick_order_btn = QPushButton("地図上で訪問順序選択")
        self.pick_order_btn.setCheckable(True)
        self.pick_order_btn.setFixedHeight(26)
        self.pick_order_btn.setToolTip(
            "ONにすると、地図上の店舗を1件ずつクリックして周回順を決められます。\n"
            "編集中ルートの既存ラインは消し、クリックした順だけ線が伸びます。\n"
            "他のルートの線はそのまま表示されます。\n"
            "選ばなかった店は店舗リストのチェックが自動でOFF（スキップ）になります。\n"
            "同じ店をもう一度クリックすると選択解除できます。\n"
            "先にルート名をダブルクリックして編集対象を選んでください。\n"
            "もう一度押すと選択モードを終了します。"
        )
        self.pick_order_btn.setStyleSheet(
            """
            QPushButton {
                background: #6a1b9a; color: #ffffff; border: none;
                padding: 2px 10px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover:!disabled { background: #8e24aa; }
            QPushButton:checked {
                background: #e65100; color: #ffffff;
            }
            QPushButton:checked:hover { background: #ef6c00; }
            QPushButton:disabled { background: #424242; color: #9e9e9e; }
            """
        )
        self.pick_order_btn.toggled.connect(self._on_pick_order_toggled)
        map_toolbar.addWidget(self.pick_order_btn, 0)

        self.pick_undo_btn = QPushButton("戻る")
        self.pick_undo_btn.setFixedHeight(26)
        self.pick_undo_btn.setToolTip("ひとつ前の選択状態に戻します")
        self.pick_undo_btn.setStyleSheet(_pick_btn_css)
        self.pick_undo_btn.setEnabled(False)
        self.pick_undo_btn.clicked.connect(self._pick_undo)
        map_toolbar.addWidget(self.pick_undo_btn, 0)

        self.pick_redo_btn = QPushButton("進む")
        self.pick_redo_btn.setFixedHeight(26)
        self.pick_redo_btn.setToolTip("戻る前の選択状態に進みます")
        self.pick_redo_btn.setStyleSheet(_pick_btn_css)
        self.pick_redo_btn.setEnabled(False)
        self.pick_redo_btn.clicked.connect(self._pick_redo)
        map_toolbar.addWidget(self.pick_redo_btn, 0)

        self.pick_save_btn = QPushButton("訪問順序保存")
        self.pick_save_btn.setFixedHeight(26)
        self.pick_save_btn.setToolTip("いまの訪問順を保存します")
        self.pick_save_btn.setStyleSheet(
            "QPushButton {"
            " background: #2e7d32; color: #ffffff; border: none;"
            " padding: 2px 8px; border-radius: 4px; font-size: 12px;"
            "}"
            "QPushButton:hover:!disabled { background: #388e3c; }"
            "QPushButton:disabled { background: #37474f; color: #78909c; }"
        )
        self.pick_save_btn.setEnabled(False)
        self.pick_save_btn.clicked.connect(self._pick_save_order)
        map_toolbar.addWidget(self.pick_save_btn, 0)

        self.pick_status_label = QLabel("")
        self.pick_status_label.setWordWrap(False)
        self.pick_status_label.setFixedHeight(26)
        self.pick_status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pick_status_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.pick_status_label.setStyleSheet(
            "color: #ffcc80; font-size: 12px; background: transparent;"
        )
        map_toolbar.addWidget(self.pick_status_label, 1)
        right_layout.addWidget(map_toolbar_host, 0)

        if WEBENGINE_AVAILABLE and QWebEngineView is not None:
            self.map_view = QWebEngineView()
            self.map_view.setMinimumHeight(420)
            self.map_view.setMinimumWidth(360)
            self.map_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.map_view.loadFinished.connect(self._on_map_load_finished)
            self.map_view.titleChanged.connect(self._on_map_title_changed)
            right_layout.addWidget(self.map_view, 1)
        else:
            self.map_view = None
            fallback = QLabel(
                "地図表示には PySide6-WebEngine が必要です。\n"
                "pip install PySide6-WebEngine 後に再起動してください。"
            )
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setWordWrap(True)
            right_layout.addWidget(fallback, 1)
        self.main_splitter.addWidget(right)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 4)
        # 初回デフォルト: 地図を広めに
        self.main_splitter.setSizes([280, 920])
        self.main_splitter.splitterMoved.connect(self._save_splitter_sizes)

        layout.addWidget(self.main_splitter, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #adb5bd;")
        layout.addWidget(self.status_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._splitter_sizes_restored:
            QTimer.singleShot(0, self._restore_splitter_sizes)
        if self._payload_cache is None:
            self.reload()
        # 開いたときは「ルート選択解除」と同じ編集解除＋全体マップ状態にする（白画面回避）
        QTimer.singleShot(250, lambda: self.clear_editing_route_focus(fit_all=True))

    def hideEvent(self, event) -> None:
        self._save_splitter_sizes()
        super().hideEvent(event)

    def _settings(self) -> QSettings:
        return QSettings(SETTINGS_ORG, SETTINGS_APP)

    def _restore_splitter_sizes(self) -> None:
        settings = self._settings()
        main_sizes = settings.value(SETTINGS_MAIN_SPLITTER)
        try:
            if isinstance(main_sizes, list) and len(main_sizes) >= 2:
                self.main_splitter.setSizes([int(x) for x in main_sizes[:2]])
            elif main_sizes is not None:
                parsed = [int(x) for x in list(main_sizes)]
                if len(parsed) >= 2:
                    self.main_splitter.setSizes(parsed[:2])
        except Exception:
            pass
        try:
            self._redistribute_left_splitter()
        except Exception:
            pass
        self._splitter_sizes_restored = True

    @staticmethod
    def _settings_bool(value, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _on_route_section_toggled(self, on: bool) -> None:
        # 畳む前に現在の高さを保存（開き直したときの比率用）
        if not on:
            self._save_splitter_sizes()
        self._settings().setValue(SETTINGS_COLLAPSE_ROUTES, bool(on))
        QTimer.singleShot(0, self._redistribute_and_save_left)

    def _on_visit_section_toggled(self, on: bool) -> None:
        if not on:
            self._save_splitter_sizes()
        self._settings().setValue(SETTINGS_COLLAPSE_VISITS, bool(on))
        QTimer.singleShot(0, self._redistribute_and_save_left)

    def _on_tag_section_toggled(self, on: bool) -> None:
        if not on:
            self._save_splitter_sizes()
        self._settings().setValue(SETTINGS_COLLAPSE_TAGS, bool(on))
        QTimer.singleShot(0, self._redistribute_and_save_left)

    def _redistribute_and_save_left(self) -> None:
        self._redistribute_left_splitter()
        self._save_splitter_sizes()

    def _left_sections(self):
        return [self.route_section, self.visit_section, self.tag_section]

    def _redistribute_left_splitter(self) -> None:
        """畳んだパネルはヘッダー高さだけにし、残りを開いているパネルへ配分する。"""
        if self.left_splitter is None:
            return
        sections = self._left_sections()
        total = max(120, int(self.left_splitter.size().height() or 0))
        if total < 120:
            total = 400
        header_sizes = []
        expanded_idx = []
        for i, sec in enumerate(sections):
            if sec.is_expanded():
                header_sizes.append(0)
                expanded_idx.append(i)
            else:
                header_sizes.append(sec.header_height())
        fixed = sum(header_sizes)
        remain = max(0, total - fixed)
        sizes = list(header_sizes)
        if expanded_idx:
            saved = self._settings().value(SETTINGS_LEFT_SPLITTER)
            try:
                saved_list = [int(x) for x in list(saved)] if saved is not None else []
            except Exception:
                saved_list = []
            weights = []
            for i in expanded_idx:
                w = saved_list[i] if i < len(saved_list) and saved_list[i] > 40 else 100
                weights.append(max(40, w))
            wsum = sum(weights) or 1
            for i, idx in enumerate(expanded_idx):
                sizes[idx] = max(60, int(remain * weights[i] / wsum))
            diff = remain - sum(sizes[i] for i in expanded_idx)
            if expanded_idx and diff:
                sizes[expanded_idx[-1]] = max(60, sizes[expanded_idx[-1]] + diff)
        self.left_splitter.setSizes(sizes)

    def _save_splitter_sizes(self, *_args) -> None:
        try:
            settings = self._settings()
            settings.setValue(SETTINGS_MAIN_SPLITTER, self.main_splitter.sizes())
            if self.left_splitter is not None:
                current = [int(x) for x in self.left_splitter.sizes()]
                prev_raw = settings.value(SETTINGS_LEFT_SPLITTER)
                try:
                    prev = [int(x) for x in list(prev_raw)] if prev_raw is not None else []
                except Exception:
                    prev = []
                merged = []
                for i, sec in enumerate(self._left_sections()):
                    cur = current[i] if i < len(current) else 100
                    if sec.is_expanded():
                        merged.append(max(60, cur))
                    else:
                        # 畳んだパネルは「好みの高さ」を残す（開き直したとき用）
                        if i < len(prev) and prev[i] > 40:
                            merged.append(prev[i])
                        else:
                            merged.append(120)
                settings.setValue(SETTINGS_LEFT_SPLITTER, merged)
        except Exception:
            pass

    def open_tags_dialog(self) -> None:
        dialog = StoreTagsDialog(self, db=self.db)
        dialog.exec()
        self.reload()

    def select_all_routes(self) -> None:
        for cb in self._route_checks.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self._refresh_map()

    def clear_route_selection(self) -> None:
        for cb in self._route_checks.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._refresh_map()

    def select_all_tags(self) -> None:
        for tid in self._current_tab_tag_ids():
            cb = self._tag_checks.get(tid)
            if not cb:
                continue
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self._refresh_map()

    def clear_tag_selection(self) -> None:
        for tid in self._current_tab_tag_ids():
            cb = self._tag_checks.get(tid)
            if not cb:
                continue
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._refresh_map()

    def _current_tab_tag_ids(self) -> Set[int]:
        return set(getattr(self, "_quality_tag_ids", set())) or set(self._tag_checks.keys())

    def _on_options_changed(self, *_args) -> None:
        self._refresh_map()

    def eventFilter(self, obj, event) -> bool:
        """ルート名（チェック枠以外）のダブルクリックで地図を拡大する。"""
        if event.type() == QEvent.MouseButtonDblClick and isinstance(obj, RouteNameCheckBox):
            code = obj.property("route_code")
            if code is not None and str(code) and not obj._on_indicator(event):
                self._focus_route_on_map(str(code))
                return True
        return super().eventFilter(obj, event)

    def _focus_route_on_map(self, route_code: str) -> None:
        """指定ルートを編集対象にし、店舗リスト表示＋地図拡大。"""
        if self._pick_mode:
            # ルート切替前に選択モードを終了（現ルートの並びを保存）
            self.pick_order_btn.setChecked(False)
        self._selected_store_code = ""
        self._set_editing_route(route_code)
        cb = self._route_checks.get(route_code)
        if cb is not None and not cb.isChecked():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        # スタート／ゴール表示を反映してから拡大
        self._refresh_map()
        QTimer.singleShot(350, lambda c=route_code: self._fit_map_to_route(c))

    def _fit_map_to_route(self, route_code: str) -> None:
        if not self.map_view or not self._payload_cache:
            return
        points: List[List[float]] = []
        for route in self._payload_cache.get("routes") or []:
            if str(route.get("route_code") or "") != route_code:
                continue
            stores_raw = [
                s for s in (route.get("stores") or []) if self._store_passes_tag_filter(s)
            ]
            for marker in _markers_from_stores(stores_raw):
                try:
                    points.append([float(marker["lat"]), float(marker["lng"])])
                except (TypeError, ValueError, KeyError):
                    continue
            break
        if not points:
            self.status_label.setText("このルートに表示できる座標がありません")
            return
        payload = json.dumps(points, ensure_ascii=False)
        js = (
            "(function(){"
            "try {"
            "if (typeof window.__HIRIO_FIT_BOUNDS !== 'function') return false;"
            f"return window.__HIRIO_FIT_BOUNDS({payload});"
            "} catch (e) { return false; }"
            "})();"
        )
        try:
            self.map_view.page().runJavaScript(js)
            name = ""
            for route in self._payload_cache.get("routes") or []:
                if str(route.get("route_code") or "") == route_code:
                    name = str(route.get("route_name") or route_code)
                    break
            self.status_label.setText(f"拡大表示: {name or route_code}")
        except Exception as e:
            print(f"ルート拡大失敗: {e}")


    def reload(self) -> None:
        self._ensure_brand_tags_on_load()
        try:
            self._payload_cache = self.db.get_map_payload()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"地図データの読込に失敗しました:\n{e}")
            return
        self._rebuild_route_list()
        self._rebuild_tag_filters()
        self._refresh_map()
        self.status_label.setText(
            f"ルート {len(self._payload_cache.get('routes') or [])} ／ "
            f"タグ {len(self._payload_cache.get('tags') or [])}"
        )

    def _ensure_brand_tags_on_load(self) -> None:
        if self._brand_tags_synced:
            return
        self._brand_tags_synced = True
        try:
            from services.store_brand_tag_service import ensure_brand_store_tags
        except Exception:
            try:
                from store_brand_tag_service import ensure_brand_store_tags  # type: ignore
            except Exception:
                return
        try:
            ensure_brand_store_tags(self.db)
        except Exception as e:
            print(f"ブランドタグ準備エラー: {e}")
            return
        QTimer.singleShot(80, self._deferred_apply_missing_brand_tags)

    def _deferred_apply_missing_brand_tags(self) -> None:
        try:
            from services.store_brand_tag_service import apply_brand_tags_to_all_stores
        except Exception:
            try:
                from store_brand_tag_service import apply_brand_tags_to_all_stores  # type: ignore
            except Exception:
                return
        try:
            result = apply_brand_tags_to_all_stores(
                self.db, replace_existing_brand=False, fix_mismatch=True
            )
            if int(result.get("updated") or 0) > 0:
                self.reload()
        except Exception as e:
            print(f"ブランドタグ自動付与エラー: {e}")

    def _clear_layout_widgets(self, layout: QVBoxLayout, keep_stretch: bool = True) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if keep_stretch:
            layout.addStretch()

    def _rebuild_route_list(self) -> None:
        previously: Set[str] = {
            code for code, cb in self._route_checks.items() if cb.isChecked()
        }
        first_load = not self._route_checks

        self._clear_layout_widgets(self.route_list_box, keep_stretch=False)
        self._route_checks.clear()
        self._route_colors.clear()
        self._route_names.clear()

        routes = (self._payload_cache or {}).get("routes") or []
        for idx, route in enumerate(routes):
            code = str(route.get("route_code") or "")
            name = str(route.get("route_name") or "")
            count = int(route.get("store_count") or 0)
            color = ROUTE_LINE_COLORS[idx % len(ROUTE_LINE_COLORS)]
            cb = RouteNameCheckBox(f"{name}（{count}）")
            # 一覧は黒字。編集中ルートは青背景で区別
            editing = bool(code) and code == self._editing_route_code
            cb.setStyleSheet(
                _checkbox_style("#90caf9" if editing else "#e0e0e0")
                + ("\nQCheckBox { background: #0d47a1; border-radius: 4px; padding: 2px; }"
                   if editing else "")
            )
            cb.setToolTip(
                "チェック枠: 表示オン／オフ\n"
                "ルート名をダブルクリック: 店舗リスト表示＋地図拡大\n"
                "地図上の店舗ピン／ルート線をダブルクリックでも選択できます"
            )
            cb.setProperty("route_code", code)
            checked = first_load or code in previously
            cb.setChecked(checked)
            cb.toggled.connect(self._on_options_changed)
            cb.installEventFilter(self)
            self.route_list_box.addWidget(cb)
            self._route_checks[code] = cb
            self._route_colors[code] = color
            self._route_names[code] = name
        self.route_list_box.addStretch()
        # 編集中ルートの店舗リストを同期
        if self._editing_route_code:
            self._load_visit_list_for_route(self._editing_route_code)

    def _rebuild_tag_filters(self) -> None:
        previously: Set[int] = {
            tid for tid, cb in self._tag_checks.items() if cb.isChecked()
        }
        first_load = not self._tag_checks

        self._clear_layout_widgets(self.quality_tag_box, keep_stretch=False)
        self._tag_checks.clear()
        self._brand_tag_ids = set()
        self._quality_tag_ids = set()

        tags = (self._payload_cache or {}).get("tags") or []
        memo_tags = []
        for tag in tags:
            name = str(tag.get("name") or "")
            # 店舗種別（BOOKOFF系など）は店舗ラベル側。絞り込みは評価・メモのみ
            if is_brand_tag_name(name) or name == "その他":
                continue
            memo_tags.append(tag)

        for tag in memo_tags:
            tid = int(tag["id"])
            color = str(tag.get("color") or DEFAULT_PIN_COLOR)
            cb = QCheckBox(str(tag.get("name") or ""))
            cb.setStyleSheet(_checkbox_style(color))
            cb.setChecked(True if first_load else tid in previously)
            cb.toggled.connect(self._on_options_changed)
            self.quality_tag_box.addWidget(cb)
            self._tag_checks[tid] = cb
            self._quality_tag_ids.add(tid)
        self.quality_tag_box.addStretch()

    def _selected_route_codes(self) -> Set[str]:
        return {code for code, cb in self._route_checks.items() if cb.isChecked()}

    def _route_color_map(self) -> Dict[str, str]:
        return dict(self._route_colors)

    def _allowed_tag_ids(self) -> Set[int]:
        return {tid for tid, cb in self._tag_checks.items() if cb.isChecked()}

    def _store_passes_tag_filter(self, store: Dict[str, Any]) -> bool:
        """評価・メモタグだけで絞り込み（店舗種別タグは無視）。"""
        allowed = self._allowed_tag_ids()
        filterable = set(self._tag_checks.keys())
        quality_ids = []
        for t in store.get("tags") or []:
            try:
                tid = int(t["id"])
            except (TypeError, ValueError, KeyError):
                continue
            if tid in filterable:
                quality_ids.append(tid)
        if not quality_ids:
            return self.include_untagged_check.isChecked()
        return any(tid in allowed for tid in quality_ids)

    _JS_GET_MAP_VIEW = """
(function(){
  try {
    if (window.__HIRIO_MAP_VIEW &&
        Number.isFinite(window.__HIRIO_MAP_VIEW.lat) &&
        Number.isFinite(window.__HIRIO_MAP_VIEW.lng) &&
        Number.isFinite(window.__HIRIO_MAP_VIEW.zoom)) {
      return {
        lat: window.__HIRIO_MAP_VIEW.lat,
        lng: window.__HIRIO_MAP_VIEW.lng,
        zoom: window.__HIRIO_MAP_VIEW.zoom
      };
    }
    var m = window.__HIRIO_MAP;
    if (!m) return null;
    var c = m.getCenter();
    return {lat: c.lat, lng: c.lng, zoom: m.getZoom()};
  } catch (e) {
    return null;
  }
})();
"""

    @staticmethod
    def _normalize_map_view(view: Any) -> Optional[Dict[str, float]]:
        if not isinstance(view, dict):
            return None
        try:
            lat = float(view.get("lat"))
            lng = float(view.get("lng"))
            zoom = float(view.get("zoom"))
        except (TypeError, ValueError):
            return None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
            return None
        if zoom < 1 or zoom > 22:
            return None
        return {"lat": lat, "lng": lng, "zoom": zoom}

    def _load_map_view_settings(self) -> Optional[Dict[str, float]]:
        try:
            raw = self._settings().value(SETTINGS_MAP_VIEW)
        except Exception:
            return None
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return None
        return self._normalize_map_view(raw)

    def _persist_map_view(self, view: Optional[Dict[str, float]]) -> None:
        if not view:
            return
        try:
            self._settings().setValue(SETTINGS_MAP_VIEW, dict(view))
        except Exception:
            pass

    def _on_map_load_finished(self, ok: bool) -> None:
        self._map_ready = bool(ok)
        if ok:
            # HTML 初回読込直後はサイズ未確定で白くなりやすいので全体表示を当てる
            QTimer.singleShot(120, self._fit_map_to_all_visible)

    def _on_map_title_changed(self, title: str) -> None:
        """document.title 経由で地図操作・店舗クリックを受け取る。"""
        text = str(title or "")
        if text.startswith("HIRIO_PICK:"):
            try:
                raw = json.loads(text[len("HIRIO_PICK:") :])
            except Exception:
                return
            if isinstance(raw, dict):
                self._on_map_store_picked(raw)
            return
        if text.startswith("HIRIO_ROUTE:"):
            try:
                raw = json.loads(text[len("HIRIO_ROUTE:") :])
            except Exception:
                return
            if isinstance(raw, dict):
                self._on_map_route_action(raw)
            return
        if not text.startswith("HIRIO_MAP:"):
            return
        try:
            raw = json.loads(text[len("HIRIO_MAP:") :])
        except Exception:
            return
        view = self._normalize_map_view(raw)
        if view is None:
            return
        self._saved_map_view = view
        self._persist_map_view(view)

    def _resolve_store_ids_for_map_action(self, payload: Dict[str, Any]) -> List[int]:
        """ポップアップ操作対象の店舗ID（併設はまとめて）。"""
        ids: List[int] = []
        for raw in payload.get("member_ids") or []:
            try:
                sid = int(raw)
            except (TypeError, ValueError):
                continue
            if sid not in ids:
                ids.append(sid)
        if ids:
            return ids
        try:
            sid = int(payload.get("store_id"))
        except (TypeError, ValueError):
            sid = None
        if sid is not None:
            return [sid]

        codes = []
        sc = str(payload.get("store_code") or "").strip()
        if sc:
            codes.append(sc)
        for c in payload.get("member_codes") or []:
            cs = str(c or "").strip()
            if cs and cs not in codes:
                codes.append(cs)
        for code in codes:
            store = None
            try:
                store = self.db.get_store_by_code(code)
            except Exception:
                store = None
            if not store:
                continue
            try:
                sid = int(store.get("id"))
            except (TypeError, ValueError):
                continue
            if sid not in ids:
                ids.append(sid)
        return ids

    def _resolve_single_store_id_from_map(
        self, payload: Dict[str, Any]
    ) -> Optional[int]:
        """併設一覧の1店だけを特定する。"""
        try:
            tid = payload.get("target_store_id")
            if tid is not None and str(tid).strip() != "":
                return int(tid)
        except (TypeError, ValueError):
            pass
        code = str(payload.get("target_store_code") or "").strip()
        if not code:
            return None
        try:
            store = self.db.get_store_by_code(code)
        except Exception:
            store = None
        if not store:
            return None
        try:
            return int(store.get("id"))
        except (TypeError, ValueError):
            return None

    def _delete_one_store_from_map(self, payload: Dict[str, Any]) -> None:
        """併設ポップアップから1店だけDB削除する。"""
        sid = self._resolve_single_store_id_from_map(payload)
        if sid is None:
            QMessageBox.warning(self, "個別削除", "対象店舗を特定できませんでした。")
            return
        store = None
        try:
            store = self.db.get_store(sid)
        except Exception:
            store = None
        label = (
            str(payload.get("target_store_name") or "").strip()
            or str((store or {}).get("store_name") or "").strip()
            or str(payload.get("target_store_code") or "").strip()
            or f"id={sid}"
        )
        code = (
            str(payload.get("target_store_code") or "").strip()
            or str((store or {}).get("store_code") or "").strip()
        )
        code_note = f"\n店舗コード: {code}" if code else ""
        reply = QMessageBox.question(
            self,
            "個別削除の確認",
            f"店舗「{label}」だけをDBから削除しますか？\n"
            "（他の併設店はそのまま残ります。元に戻せません）"
            f"{code_note}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            ok = bool(self.db.delete_store(sid))
        except Exception as e:
            QMessageBox.warning(self, "個別削除", f"削除に失敗しました。\n{e}")
            return
        if not ok:
            QMessageBox.warning(self, "個別削除", "削除に失敗しました。")
            return
        if code and self._selected_store_code == code:
            self._selected_store_code = ""
        editing = self._editing_route_code
        self.reload()
        if editing and editing in self._route_checks:
            self._set_editing_route(editing)
        else:
            QTimer.singleShot(200, self._fit_map_to_all_visible)
        self.routes_changed.emit()
        self.status_label.setText(f"個別削除: {label}")

    def _on_map_route_action(self, payload: Dict[str, Any]) -> None:
        """地図ポップアップ／ラインからのルート操作。"""
        action = str(payload.get("action") or "").strip()

        # 地図上ダブルクリックでルート選択（店舗ピン・ルート線）
        if action == "focus":
            to_code = str(payload.get("route_code") or "").strip()
            if not to_code:
                QMessageBox.information(
                    self,
                    "ルート選択",
                    "この店舗はルート未所属のため選択できません。",
                )
                return
            self._focus_route_on_map(to_code)
            name = self._route_names.get(to_code) or to_code
            self.status_label.setText(f"地図からルート選択: {name}")
            return

        if action == "delete_one":
            self._delete_one_store_from_map(payload)
            return

        store_ids = self._resolve_store_ids_for_map_action(payload)
        if not store_ids:
            QMessageBox.warning(self, "ルート操作", "対象店舗を特定できませんでした。")
            return

        try:
            from services.store_route_membership_service import (
                move_store_to_route,
                remove_store_from_route,
                store_in_route,
                unassign_store_completely,
            )
        except Exception:
            try:
                from store_route_membership_service import (  # type: ignore
                    move_store_to_route,
                    remove_store_from_route,
                    store_in_route,
                    unassign_store_completely,
                )
            except Exception as e:
                QMessageBox.critical(self, "ルート操作", f"処理を読み込めませんでした:\n{e}")
                return

        label = (
            str(payload.get("store_name") or payload.get("store_code") or "").strip()
            or f"{len(store_ids)}店"
        )

        if action == "unassign":
            from_code = str(payload.get("from_route_code") or "").strip()
            from_name = str(payload.get("from_route_name") or "").strip()
            if not from_code and not from_name:
                QMessageBox.information(self, "ルート解除", "この店舗は未所属です。")
                return
            ok_count = 0
            for sid in store_ids:
                store = self.db.get_store(sid)
                if not store:
                    continue
                if from_code or from_name:
                    if remove_store_from_route(self.db, sid, from_name, from_code):
                        ok_count += 1
                    elif unassign_store_completely(self.db, sid):
                        ok_count += 1
                elif unassign_store_completely(self.db, sid):
                    ok_count += 1
            if ok_count <= 0:
                QMessageBox.warning(self, "ルート解除", "解除に失敗しました。")
                return
            editing = self._editing_route_code
            self.reload()
            if editing:
                self._set_editing_route(editing)
            self.routes_changed.emit()
            self.status_label.setText(
                f"ルート解除: {label}（{from_name or from_code or '所属'}）"
            )
            return

        if action == "register":
            to_code = str(payload.get("route_code") or "").strip()
            to_name = str(payload.get("route_name") or "").strip() or to_code
            if not to_code:
                QMessageBox.warning(self, "ルート登録", "登録先ルートがありません。")
                return
            already = 0
            moved = 0
            for sid in store_ids:
                store = self.db.get_store(sid)
                if not store:
                    continue
                if store_in_route(store, to_name, to_code):
                    already += 1
                    continue
                if move_store_to_route(self.db, sid, to_name, to_code):
                    moved += 1
            if moved <= 0:
                if already:
                    QMessageBox.information(
                        self,
                        "ルート登録",
                        f"「{label}」はすでに「{to_name}」に所属しています。",
                    )
                else:
                    QMessageBox.warning(self, "ルート登録", "登録に失敗しました。")
                return
            editing = self._editing_route_code
            self.reload()
            # 登録先を編集対象にして店舗リストも更新
            self._set_editing_route(to_code)
            cb = self._route_checks.get(to_code)
            if cb is not None and not cb.isChecked():
                cb.blockSignals(True)
                cb.setChecked(True)
                cb.blockSignals(False)
            self._refresh_map()
            self.routes_changed.emit()
            self.status_label.setText(f"ルート登録: {label} → {to_name}")
            return

        if action == "delete":
            member_note = ""
            if len(store_ids) > 1:
                member_note = (
                    f"\n\n併設としてまとまっている {len(store_ids)} 店を"
                    "まとめて削除します。"
                )
            reply = QMessageBox.question(
                self,
                "削除確認",
                f"店舗「{label}」をDBから削除しますか？\n"
                "（元に戻せません）"
                f"{member_note}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            ok_count = 0
            errors: List[str] = []
            for sid in store_ids:
                try:
                    if self.db.delete_store(sid):
                        ok_count += 1
                except Exception as e:
                    errors.append(str(e))
            if ok_count <= 0:
                detail = "\n".join(errors[:3]) if errors else ""
                QMessageBox.warning(
                    self,
                    "DBから削除",
                    "削除に失敗しました。" + (f"\n{detail}" if detail else ""),
                )
                return
            if self._selected_store_code:
                codes = {
                    str(c).strip()
                    for c in (
                        [payload.get("store_code")]
                        + list(payload.get("member_codes") or [])
                    )
                    if str(c or "").strip()
                }
                if self._selected_store_code in codes:
                    self._selected_store_code = ""
            editing = self._editing_route_code
            self.reload()
            if editing and editing in self._route_checks:
                self._set_editing_route(editing)
            else:
                QTimer.singleShot(200, self._fit_map_to_all_visible)
            self.routes_changed.emit()
            self.status_label.setText(f"DBから削除: {label}（{ok_count}店）")
            return

        if action == "register_collocation":
            self._register_collocated_store_from_map(payload)
            return

        if action == "register_collocation_candidate":
            self._register_collocated_store_from_map(payload)
            return

        if action == "set_collocation_checked":
            self._set_collocation_checked_from_map(payload)
            return

        if action == "auto_check_collocation":
            self._auto_check_collocation_from_map(payload)
            return

        QMessageBox.warning(self, "ルート操作", f"不明な操作です: {action}")

    def _merge_auto_brand_tag_ids(self, store_name: str, tag_ids: list) -> list:
        try:
            from services.store_brand_tag_service import merge_brand_tag_ids
        except Exception:
            try:
                from store_brand_tag_service import merge_brand_tag_ids  # type: ignore
            except Exception:
                return list(tag_ids or [])
        return merge_brand_tag_ids(self.db, store_name, tag_ids or [])

    def _pick_collocation_brand(
        self, member_brands: List[str], source_label: str
    ) -> Optional[str]:
        """未登録の HA/HO/OF から併設登録するブランドを選ぶ。"""
        missing = _missing_hardoff_brands(member_brands)
        if not missing:
            QMessageBox.information(
                self,
                "併設店舗登録",
                "ハードオフ／ホビーオフ／オフハウスは\n"
                "すでにすべて登録されています。",
            )
            return None
        if len(missing) == 1:
            return missing[0]

        labels = [
            f"{code}: {_HARDOFF_BRAND_LABELS.get(code, code)}" for code in missing
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "併設店舗登録",
            f"基準店: {source_label}\n\n"
            "まだDBにない併設ブランドを選んでください:",
            labels,
            0,
            False,
        )
        if not ok or not choice:
            return None
        code = str(choice).split(":", 1)[0].strip().upper()
        return code if code in missing else None

    def _resolve_source_store_for_collocation(
        self, payload: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], List[int], List[str]]:
        store_ids = self._resolve_store_ids_for_map_action(payload)
        source = None
        if store_ids:
            source = self.db.get_store(store_ids[0])
        if not source:
            code = str(payload.get("store_code") or "").strip()
            if code:
                try:
                    source = self.db.get_store_by_code(code)
                except Exception:
                    source = None
        member_brands = [
            str(b or "").strip().upper()
            for b in (payload.get("member_brands") or [])
            if str(b or "").strip()
        ]
        if not member_brands:
            brands: List[str] = []
            for sid in store_ids or []:
                st = self.db.get_store(sid)
                if not st:
                    continue
                b = _brand_of_store(st)
                if b and b not in brands:
                    brands.append(b)
            if not brands and source:
                b = _brand_of_store(source)
                if b:
                    brands.append(b)
            member_brands = brands
        return source, store_ids, member_brands

    def _push_colloc_candidates_to_map(self, payload_for_js: Dict[str, Any]) -> None:
        """ポップアップへ候補一覧を返す。"""
        if not WEBENGINE_AVAILABLE or not getattr(self, "map_view", None):
            return
        try:
            body = _json_for_js(payload_for_js)
            js = f"window.__HIRIO_SHOW_COLLOC_CANDIDATES && window.__HIRIO_SHOW_COLLOC_CANDIDATES({body});"
            self.map_view.page().runJavaScript(js)
        except Exception as e:
            print(f"併設候補の地図反映エラー: {e}")

    def _set_collocation_checked_from_map(self, payload: Dict[str, Any]) -> None:
        """ポップアップの併設確認済みチェックをDBへ保存。"""
        store_ids = self._resolve_store_ids_for_map_action(payload)
        if not store_ids:
            QMessageBox.warning(self, "併設確認済み", "対象店舗を特定できませんでした。")
            return
        checked = bool(payload.get("checked"))
        try:
            updated = self.db.set_collocation_checked(store_ids, checked)
        except Exception as e:
            QMessageBox.critical(self, "併設確認済み", f"保存に失敗しました:\n{e}")
            return
        if updated <= 0:
            QMessageBox.warning(self, "併設確認済み", "更新対象がありませんでした。")
            return
        editing = self._editing_route_code
        self.reload()
        if editing:
            self._set_editing_route(editing)
        self.routes_changed.emit()
        label = str(payload.get("store_name") or payload.get("store_code") or "").strip()
        state = "確認済み" if checked else "未確認"
        self.status_label.setText(f"併設{state}: {label or f'{len(store_ids)}店'}")

    def _auto_check_collocation_from_map(self, payload: Dict[str, Any]) -> None:
        """Google Places で未登録の併設候補を検索し、ポップアップへ返す。"""
        source, store_ids, member_brands = self._resolve_source_store_for_collocation(
            payload
        )
        cache_key = str(payload.get("cache_key") or "").strip()
        force = bool(payload.get("force"))
        base_js = {
            "cache_key": cache_key,
            "store_id": payload.get("store_id"),
            "store_code": payload.get("store_code") or "",
            "store_name": payload.get("store_name") or "",
            "member_codes": payload.get("member_codes") or [],
            "member_ids": store_ids or payload.get("member_ids") or [],
            "member_brands": member_brands,
        }
        if not force and cache_key and cache_key in self._colloc_search_cache:
            cached = dict(self._colloc_search_cache[cache_key])
            cached.update(base_js)
            self._push_colloc_candidates_to_map(cached)
            return

        if not source:
            out = {
                **base_js,
                "candidates": [],
                "error": "基準店舗を特定できませんでした",
            }
            if cache_key:
                self._colloc_search_cache[cache_key] = out
            self._push_colloc_candidates_to_map(out)
            return

        missing = _missing_hardoff_brands(member_brands)
        if not missing:
            out = {
                **base_js,
                "candidates": [],
                "message": "HA/HO/OF はDB上そろっています",
            }
            if cache_key:
                self._colloc_search_cache[cache_key] = out
            self._push_colloc_candidates_to_map(out)
            return

        try:
            lat = float(payload.get("lat") if payload.get("lat") is not None else source.get("latitude"))
            lng = float(payload.get("lng") if payload.get("lng") is not None else source.get("longitude"))
        except (TypeError, ValueError):
            out = {
                **base_js,
                "candidates": [],
                "error": "座標が無いためGoogle検索できません",
            }
            if cache_key:
                self._colloc_search_cache[cache_key] = out
            self._push_colloc_candidates_to_map(out)
            return

        existing_names = [
            str(n).strip()
            for n in (payload.get("member_names") or [])
            if str(n or "").strip()
        ]
        if not existing_names:
            for sid in store_ids or []:
                st = self.db.get_store(sid)
                if not st:
                    continue
                name = str(st.get("store_name") or "").strip()
                if name and name not in existing_names:
                    existing_names.append(name)

        try:
            from services.google_maps_service import search_nearby_hardoff_collocations
        except Exception:
            try:
                from google_maps_service import (  # type: ignore
                    search_nearby_hardoff_collocations,
                )
            except Exception as e:
                out = {
                    **base_js,
                    "candidates": [],
                    "error": f"Google検索を読み込めません: {e}",
                }
                self._push_colloc_candidates_to_map(out)
                return

        try:
            candidates = search_nearby_hardoff_collocations(
                latitude=lat,
                longitude=lng,
                source_store_name=str(source.get("store_name") or ""),
                missing_brands=missing,
                existing_member_names=existing_names,
            )
        except Exception as e:
            out = {
                **base_js,
                "candidates": [],
                "error": f"Google検索に失敗しました: {e}",
            }
            if cache_key:
                self._colloc_search_cache[cache_key] = out
            self._push_colloc_candidates_to_map(out)
            return

        out = {
            **base_js,
            "candidates": candidates,
            "message": (
                f"{len(candidates)}件の併設候補"
                if candidates
                else "近くに未登録の併設は見つかりませんでした"
            ),
        }
        if cache_key:
            self._colloc_search_cache[cache_key] = out
        self._push_colloc_candidates_to_map(out)
        self.status_label.setText(
            f"併設自動確認: {out['message']}（{source.get('store_name') or ''}）"
        )

    def _register_collocated_store_from_map(self, payload: Dict[str, Any]) -> None:
        """地図ポップアップからハードオフ系の併設店をDB登録する。"""
        source, store_ids, member_brands = self._resolve_source_store_for_collocation(
            payload
        )
        if not source:
            QMessageBox.warning(
                self, "併設店舗登録", "基準となる店舗を特定できませんでした。"
            )
            return

        candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else None
        source_label = (
            str(source.get("store_name") or source.get("store_code") or "").strip()
            or "選択店舗"
        )

        if candidate:
            brand = str(candidate.get("brand") or "").strip().upper()
            if brand not in _HARDOFF_BRAND_LABELS:
                QMessageBox.warning(self, "併設店舗登録", "候補のブランドが不正です。")
                return
            suggested_name = str(candidate.get("store_name") or "").strip() or (
                _suggest_collocated_store_name(str(source.get("store_name") or ""), brand)
            )
            prefill_address = str(candidate.get("address") or source.get("address") or "")
            prefill_phone = str(candidate.get("phone") or source.get("phone") or "")
            prefill_lat = StoreEditDialog._coerce_coordinate(
                candidate.get("latitude")
            )
            prefill_lng = StoreEditDialog._coerce_coordinate(
                candidate.get("longitude")
            )
            if prefill_lat is None:
                prefill_lat = StoreEditDialog._coerce_coordinate(source.get("latitude"))
            if prefill_lng is None:
                prefill_lng = StoreEditDialog._coerce_coordinate(source.get("longitude"))
        else:
            brand = self._pick_collocation_brand(member_brands, source_label)
            if not brand:
                return
            suggested_name = _suggest_collocated_store_name(
                str(source.get("store_name") or ""), brand
            )
            prefill_address = str(source.get("address") or "")
            prefill_phone = str(source.get("phone") or "")
            prefill_lat = StoreEditDialog._coerce_coordinate(source.get("latitude"))
            prefill_lng = StoreEditDialog._coerce_coordinate(source.get("longitude"))

        initial_route = str(source.get("affiliated_route_name") or "").strip()
        custom_fields_def = []
        try:
            custom_fields_def = self.db.list_custom_fields(active_only=True)
        except Exception:
            custom_fields_def = []

        dialog = StoreEditDialog(
            self,
            custom_fields_def=custom_fields_def,
            initial_route_name=initial_route if initial_route else "",
        )
        dialog.setWindowTitle(
            f"併設店舗登録（{_HARDOFF_BRAND_LABELS.get(brand, brand)}）"
        )
        dialog.store_name_edit.setText(suggested_name)
        dialog.address_edit.setText(prefill_address)
        dialog.phone_edit.setText(prefill_phone)
        dialog._latitude = prefill_lat
        dialog._longitude = prefill_lng
        dialog._refresh_store_code_suggestions(suggested_name, auto_pick_first=True)
        if not dialog._get_store_code_text():
            try:
                next_code = self.db.get_next_store_code_for_prefix(brand)
                if next_code:
                    dialog._set_store_code_text(next_code)
            except Exception:
                pass

        if dialog.exec() != QDialog.Accepted:
            return

        is_valid, error_msg = dialog.validate()
        if not is_valid:
            QMessageBox.warning(self, "エラー", error_msg)
            return

        try:
            data = dialog.get_data()
            if not data.get("store_code"):
                store_name = data.get("store_name", "")
                if store_name:
                    generated = self.db.get_next_store_code_from_store_name(store_name)
                    if generated:
                        data["store_code"] = generated
                if not data.get("store_code"):
                    next_code = self.db.get_next_store_code_for_prefix(brand)
                    if next_code:
                        data["store_code"] = next_code
            if data.get("latitude") is None or data.get("longitude") is None:
                if prefill_lat is not None and prefill_lng is not None:
                    data["latitude"] = prefill_lat
                    data["longitude"] = prefill_lng
            aff = (data.get("affiliated_route_name") or "").strip()
            if not aff:
                data["affiliated_route_name"] = None
                data["route_code"] = None
            tag_ids = data.pop("tag_ids", None) or []
            tag_ids = self._merge_auto_brand_tag_ids(
                str(data.get("store_name") or ""), tag_ids
            )
            new_id = self.db.add_store(data)
            if new_id:
                self.db.set_store_tag_ids(int(new_id), tag_ids)
            # 登録後は検索キャッシュを捨てて再確認できるようにする
            self._colloc_search_cache.clear()
            new_code = str(data.get("store_code") or "").strip()
            new_name = str(data.get("store_name") or "").strip()
            msg = f"併設店舗を登録しました。\n{new_name}"
            if new_code:
                msg += f"\n店舗コード: {new_code}"
            if aff:
                msg += f"\nルート: {aff}"
            else:
                msg += "\n（未所属。あとからルート登録できます）"
            QMessageBox.information(self, "完了", msg)

            editing = self._editing_route_code
            self.reload()
            if editing:
                self._set_editing_route(editing)
            if new_code:
                self._selected_store_code = new_code
            self.routes_changed.emit()
            self.status_label.setText(f"併設店舗登録: {new_name or new_code}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"登録に失敗しました:\n{e}")

    def _set_pick_status(self, text: str) -> None:
        """地図上ツールバーは1行固定。全文はツールチップへ。"""
        msg = str(text or "")
        self.pick_status_label.setText(msg)
        self.pick_status_label.setToolTip(msg)

    def _update_pick_nav_buttons(self) -> None:
        on = bool(self._pick_mode)
        self.pick_undo_btn.setEnabled(on and self._pick_history_index > 0)
        self.pick_redo_btn.setEnabled(
            on and self._pick_history_index < len(self._pick_history) - 1
        )
        self.pick_save_btn.setEnabled(on and bool(self._editing_route_code))

    def _refresh_pick_status_text(self) -> None:
        if not self._pick_mode:
            self._set_pick_status("")
            return
        total = len(self._pick_baseline_rows) or self.visit_list.count()
        picked = len(self._pick_order)
        if picked <= 0:
            self._set_pick_status("1件目からクリック（再クリックで解除）")
            self.status_label.setText("訪問順クリック選択中…")
        elif picked >= total:
            self._set_pick_status(f"全{total}店選択済み。保存 or もう一度ボタンで終了")
            self.status_label.setText("訪問順クリック選択: 完了")
        else:
            self._set_pick_status(
                f"{picked}/{total} 選択 → 次は{picked + 1}件目（再クリックで解除）"
            )
            self.status_label.setText(f"訪問順クリック選択中: {picked}/{total}")

    def _push_pick_history(self) -> None:
        self._pick_history = self._pick_history[: self._pick_history_index + 1]
        self._pick_history.append(list(self._pick_order))
        self._pick_history_index = len(self._pick_history) - 1
        self._update_pick_nav_buttons()

    def _apply_pick_order_to_ui(self, *, save: bool = True) -> None:
        """pick_order に合わせて店舗リスト・地図を更新。

        地図で選んだ店＝行く（チェックON）、未選択＝スキップ（チェックOFF）。
        """
        baseline = self._pick_baseline_rows or self._snapshot_visit_items()
        if not baseline:
            self._refresh_map()
            self._refresh_pick_status_text()
            self._update_pick_nav_buttons()
            return
        new_rows = _rows_for_pick_order(baseline, self._pick_order)
        self._rebuild_visit_list_from_rows(new_rows)
        if self._pick_order:
            self._selected_store_code = self._pick_order[-1]
        if save and self._editing_route_code:
            self.save_editing_visit_order(silent=True)
        else:
            self._refresh_map()
        self._refresh_pick_status_text()
        self._update_pick_nav_buttons()

    def _on_pick_order_toggled(self, checked: bool) -> None:
        if checked:
            if not self._editing_route_code:
                self.pick_order_btn.blockSignals(True)
                self.pick_order_btn.setChecked(False)
                self.pick_order_btn.blockSignals(False)
                QMessageBox.information(
                    self,
                    "地図上で訪問順序選択",
                    "先にルート名をダブルクリックして編集対象を選んでください。",
                )
                return
            if self.visit_list.count() < 1:
                self.pick_order_btn.blockSignals(True)
                self.pick_order_btn.setChecked(False)
                self.pick_order_btn.blockSignals(False)
                QMessageBox.information(
                    self, "地図上で訪問順序選択", "このルートに店舗がありません。"
                )
                return
            self._pick_mode = True
            self._pick_baseline_rows = self._snapshot_visit_items()
            self._pick_order = []
            self._pick_history = [[]]
            self._pick_history_index = 0
            self._refresh_pick_status_text()
            self._update_pick_nav_buttons()
            self._refresh_map()
            return

        # OFF: 選択モード終了（いまの並びを保存）
        was_picking = self._pick_mode
        self._pick_mode = False
        self._pick_order = []
        self._pick_baseline_rows = []
        self._pick_history = [[]]
        self._pick_history_index = 0
        self._set_pick_status("")
        self._update_pick_nav_buttons()
        if was_picking and self._editing_route_code and self.visit_list.count() > 0:
            self.save_editing_visit_order(silent=True)
            self.status_label.setText(
                f"訪問順クリック選択を終了: {self._editing_route_name or self._editing_route_code}"
            )
        else:
            self._refresh_map()

    def _pick_undo(self) -> None:
        if not self._pick_mode or self._pick_history_index <= 0:
            return
        self._pick_history_index -= 1
        self._pick_order = list(self._pick_history[self._pick_history_index])
        self._apply_pick_order_to_ui(save=True)

    def _pick_redo(self) -> None:
        if not self._pick_mode:
            return
        if self._pick_history_index >= len(self._pick_history) - 1:
            return
        self._pick_history_index += 1
        self._pick_order = list(self._pick_history[self._pick_history_index])
        self._apply_pick_order_to_ui(save=True)

    def _pick_save_order(self) -> None:
        if not self._editing_route_code:
            QMessageBox.information(
                self, "訪問順序保存", "先にルートを選んでください。"
            )
            return
        self.save_editing_visit_order(silent=False)

    def _snapshot_visit_items(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for i in range(self.visit_list.count()):
            item = self.visit_list.item(i)
            code = str(item.data(Qt.UserRole) or "").strip()
            if not code:
                continue
            rows.append(
                {
                    "store_code": code,
                    "store_name": str(item.data(Qt.UserRole + 1) or "").strip(),
                    "notes": str(item.data(Qt.UserRole + 2) or "").strip(),
                    "store_id": item.data(Qt.UserRole + 3),
                    "checked": item.checkState() == Qt.Checked,
                }
            )
        return rows

    def _set_visit_item_data(
        self,
        item: QListWidgetItem,
        *,
        store_code: str,
        store_name: str,
        notes: str,
        store_id: Any = None,
        tip_extra: str = "",
    ) -> None:
        item.setData(Qt.UserRole, store_code)
        item.setData(Qt.UserRole + 1, store_name)
        item.setData(Qt.UserRole + 2, notes)
        item.setData(Qt.UserRole + 3, store_id)
        tip = f"{store_name}"
        if store_code:
            tip += f" [{store_code}]"
        if notes:
            tip += f"\n備考: {notes}"
        if tip_extra:
            tip += tip_extra
        tip += "\n右クリックまたは「ルートから外す」でこのグループから削除"
        item.setToolTip(tip)
        item.setFlags(
            item.flags()
            | Qt.ItemIsEnabled
            | Qt.ItemIsSelectable
            | Qt.ItemIsDragEnabled
            | Qt.ItemIsUserCheckable
        )

    def _rebuild_visit_list_from_rows(self, rows: List[Dict[str, Any]]) -> None:
        self._visit_reorder_busy = True
        self.visit_list.clear()
        for idx, row in enumerate(rows, start=1):
            store_code = str(row.get("store_code") or "").strip()
            store_name = str(row.get("store_name") or "").strip()
            notes = str(row.get("notes") or "").strip()
            label = self._format_visit_item_label(idx, store_name, store_code, notes)
            item = QListWidgetItem(label)
            self._set_visit_item_data(
                item,
                store_code=store_code,
                store_name=store_name,
                notes=notes,
                store_id=row.get("store_id"),
            )
            item.setCheckState(Qt.Checked if row.get("checked", True) else Qt.Unchecked)
            self._apply_visit_item_style(item)
            self.visit_list.addItem(item)
        self._visit_reorder_busy = False

    def _codes_for_map_pick(
        self, store_code: str, member_codes: Optional[List[Any]] = None
    ) -> List[str]:
        """クリックしたピンに対応する店舗コード（併設はリスト上の相対順でまとめて）。"""
        code = (store_code or "").strip()
        members = [
            str(c).strip()
            for c in (member_codes or [])
            if str(c).strip()
        ]
        candidates = []
        for c in [code] + members:
            if c and c not in candidates:
                candidates.append(c)
        if not candidates:
            return []
        # 基準順（選択開始時）を優先
        baseline_codes = [
            str(r.get("store_code") or "").strip()
            for r in self._pick_baseline_rows
            if str(r.get("store_code") or "").strip()
        ]
        source = baseline_codes or self._ordered_store_codes_from_list()
        in_list = [c for c in source if c in set(candidates)]
        if in_list:
            return in_list
        return candidates[:1]

    def _on_map_store_picked(self, payload: Dict[str, Any]) -> None:
        if not self._pick_mode or not self._editing_route_code:
            return
        codes = self._codes_for_map_pick(
            str(payload.get("store_code") or ""),
            payload.get("member_codes") if isinstance(payload.get("member_codes"), list) else None,
        )
        if not codes:
            return
        picked_set = set(self._pick_order)
        # すべて選択済みなら再クリックで解除
        if codes and all(c in picked_set for c in codes):
            remove = set(codes)
            self._pick_order = [c for c in self._pick_order if c not in remove]
            self._push_pick_history()
            self._apply_pick_order_to_ui(save=True)
            return

        added = False
        for code in codes:
            if code not in picked_set:
                self._pick_order.append(code)
                picked_set.add(code)
                added = True
        if not added:
            return
        self._push_pick_history()
        self._apply_pick_order_to_ui(save=True)

    def clear_editing_route_focus(self, *, fit_all: bool = False) -> None:
        """編集中ルートを解除する。

        fit_all=True のときだけ全体が収まるようズームする（初回表示用）。
        ボタンからの解除では現在の地図位置・ズームを維持する。
        """
        if self._pick_mode:
            self.pick_order_btn.blockSignals(True)
            self.pick_order_btn.setChecked(False)
            self.pick_order_btn.blockSignals(False)
            self._pick_mode = False
            self._pick_order = []
            self._pick_baseline_rows = []
            self._pick_history = [[]]
            self._pick_history_index = 0
            self._set_pick_status("")
            self._update_pick_nav_buttons()

        self._editing_route_code = ""
        self._editing_route_name = ""
        self._selected_store_code = ""
        self._visit_reorder_busy = True
        self.visit_list.clear()
        self._visit_reorder_busy = False
        self.visit_section.set_title("店舗（ルートをダブルクリック）")
        self.save_visit_order_btn.setEnabled(False)
        self.reverse_visit_order_btn.setEnabled(False)
        self.web_template_btn.setEnabled(False)
        self._restyle_route_checks()
        self._refresh_map()
        if fit_all:
            QTimer.singleShot(200, self._fit_map_to_all_visible)
            self.status_label.setText("ルート選択を解除しました（全体マップ）")
        else:
            self.status_label.setText("ルート選択を解除しました")

    def _fit_map_to_all_visible(self) -> None:
        """表示中ルート全体が収まるように地図を拡大。"""
        if not self.map_view or not self._payload_cache:
            return
        selected = self._selected_route_codes()
        points: List[List[float]] = []
        for route in self._payload_cache.get("routes") or []:
            code = str(route.get("route_code") or "")
            if code not in selected:
                continue
            stores_raw = [
                s for s in (route.get("stores") or []) if self._store_passes_tag_filter(s)
            ]
            for marker in _markers_from_stores(stores_raw):
                try:
                    points.append([float(marker["lat"]), float(marker["lng"])])
                except (TypeError, ValueError, KeyError):
                    continue
        if self.show_unassigned_check.isChecked():
            for marker in _markers_from_stores(
                [
                    s
                    for s in (self._payload_cache.get("unassigned") or [])
                    if self._store_passes_tag_filter(s)
                ]
            ):
                try:
                    points.append([float(marker["lat"]), float(marker["lng"])])
                except (TypeError, ValueError, KeyError):
                    continue
        if not points:
            self.status_label.setText("表示できる座標がありません")
            return
        payload = json.dumps(points, ensure_ascii=False)
        js = (
            "(function(){"
            "try {"
            "if (typeof window.__HIRIO_FIT_BOUNDS !== 'function') return false;"
            f"return window.__HIRIO_FIT_BOUNDS({payload});"
            "} catch (e) { return false; }"
            "})();"
        )
        try:
            self.map_view.page().runJavaScript(js)
        except Exception as e:
            print(f"全体マップ拡大失敗: {e}")

    def _apply_leaflet_payload(self, leaflet_payload: Dict[str, Any]) -> None:
        """地図へ反映。既に表示中ならピンだけ差し替え（拡大位置は維持）。"""
        if self.map_view is None:
            return

        if self._saved_map_view is not None:
            leaflet_payload["saved_view"] = self._saved_map_view

        # 既に地図があるときは HTML を作り直さない（ここが全体表示に戻る主因だった）
        if self._map_ready:
            data_json = _json_for_js(leaflet_payload)
            js = (
                "(function(){"
                "try {"
                "if (typeof window.__HIRIO_UPDATE !== 'function') return false;"
                f"return window.__HIRIO_UPDATE({data_json}, {{fit:false}});"
                "} catch (e) { return false; }"
                "})();"
            )

            def _after_update(result: Any) -> None:
                if result is True:
                    return
                # 更新関数が無い／失敗時だけフル再読込
                self._map_ready = False
                html_doc = build_leaflet_html(leaflet_payload)
                self.map_view.setHtml(html_doc, QUrl("https://local.hirio/"))

            try:
                self.map_view.page().runJavaScript(js, _after_update)
                return
            except Exception:
                self._map_ready = False

        self._map_ready = False
        html_doc = build_leaflet_html(leaflet_payload)
        self.map_view.setHtml(html_doc, QUrl("https://local.hirio/"))


    def _set_editing_route(self, route_code: str) -> None:
        """編集中ルートを切り替え、店舗リストを読み込む。"""
        code = (route_code or "").strip()
        self._editing_route_code = code
        self._editing_route_name = self._route_names.get(code, "")
        if not self._editing_route_name and self._payload_cache:
            for route in self._payload_cache.get("routes") or []:
                if str(route.get("route_code") or "") == code:
                    self._editing_route_name = str(route.get("route_name") or "")
                    break
        title = "店舗（ルートをダブルクリック）"
        if self._editing_route_name:
            title = f"店舗（編集中: {self._editing_route_name}）"
        self.visit_section.set_title(title)
        self.visit_section.set_expanded(True)
        self.save_visit_order_btn.setEnabled(bool(code))
        self.reverse_visit_order_btn.setEnabled(bool(code))
        self.web_template_btn.setEnabled(bool(code))
        self.remove_from_route_btn.setEnabled(bool(code))
        QTimer.singleShot(0, self._redistribute_left_splitter)
        self._load_visit_list_for_route(code)
        # ルート一覧の見た目を更新（編集中ハイライト）
        self._restyle_route_checks()

    def _restyle_route_checks(self) -> None:
        for code, cb in self._route_checks.items():
            editing = bool(code) and code == self._editing_route_code
            cb.setStyleSheet(
                _checkbox_style("#90caf9" if editing else "#e0e0e0")
                + (
                    "\nQCheckBox { background: #0d47a1; border-radius: 4px; padding: 2px; }"
                    if editing
                    else ""
                )
            )

    def _visit_notes_from_store(self, store: Dict[str, Any]) -> str:
        """店舗一覧と同じ備考（stores.notes）。"""
        return str(store.get("notes") or "").strip()

    def _format_visit_item_label(
        self, index: int, store_name: str, store_code: str, notes: str
    ) -> str:
        label = f"{index}. {store_name}"
        if store_code:
            label += f"  [{store_code}]"
        if notes:
            # 1行表示用。長い備考は省略し、全文はツールチップへ
            short = notes.replace("\n", " ").strip()
            if len(short) > 40:
                short = short[:40] + "…"
            label += f"  ｜ {short}"
        return label

    def _load_visit_list_for_route(self, route_code: str) -> None:
        self._visit_reorder_busy = True
        self.visit_list.clear()
        code = (route_code or "").strip()
        if not code or not self._payload_cache:
            self._visit_reorder_busy = False
            return
        route_name = self._editing_route_name or self._route_names.get(code, "")
        stores = []
        for route in self._payload_cache.get("routes") or []:
            if str(route.get("route_code") or "") == code:
                stores = list(route.get("stores") or [])
                route_name = str(route.get("route_name") or route_name)
                break
        if not stores and route_name:
            try:
                stores = self.db.get_stores_for_route_ordered(route_name)
            except Exception:
                stores = []
        for idx, store in enumerate(stores, start=1):
            store_code = str(
                store.get("store_code") or store.get("supplier_code") or ""
            ).strip()
            store_name = str(store.get("store_name") or "").strip()
            notes = self._visit_notes_from_store(store)
            label = self._format_visit_item_label(idx, store_name, store_code, notes)
            item = QListWidgetItem(label)
            self._set_visit_item_data(
                item,
                store_code=store_code,
                store_name=store_name,
                notes=notes,
                store_id=store.get("id"),
            )
            will_visit = _will_visit_from_store(store)
            item.setCheckState(Qt.Checked if will_visit else Qt.Unchecked)
            self._apply_visit_item_style(item)
            self.visit_list.addItem(item)
        self._editing_route_name = route_name
        self._visit_reorder_busy = False

    def _on_visit_list_context_menu(self, pos: QPoint) -> None:
        item = self.visit_list.itemAt(pos)
        if item is None:
            return
        self.visit_list.setCurrentItem(item)
        menu = QMenu(self.visit_list)
        act = QAction("このルート（グループ）から外す", menu)
        act.triggered.connect(self.remove_selected_store_from_editing_route)
        menu.addAction(act)
        menu.exec(self.visit_list.mapToGlobal(pos))

    def remove_selected_store_from_editing_route(self) -> None:
        """店舗エリアで選んだ店を、編集中ルートのグループから外す。"""
        if not self._editing_route_code:
            QMessageBox.information(
                self,
                "ルートから外す",
                "先にルート名をダブルクリックして編集対象を選んでください。",
            )
            return
        item = self.visit_list.currentItem()
        if item is None:
            QMessageBox.information(
                self,
                "ルートから外す",
                "外したい店舗をリストで選んでから押してください。",
            )
            return
        self._remove_visit_item_from_editing_route(item)

    def _remove_visit_item_from_editing_route(self, item: QListWidgetItem) -> None:
        route_code = (self._editing_route_code or "").strip()
        route_name = (self._editing_route_name or "").strip()
        if not route_code:
            return
        store_code = str(item.data(Qt.UserRole) or "").strip()
        store_name = str(item.data(Qt.UserRole + 1) or "").strip()
        label = store_name or store_code or "店舗"
        code_note = f"\n店舗コード: {store_code}" if store_code else ""
        reply = QMessageBox.question(
            self,
            "ルートから外す確認",
            f"「{label}」をルート「{route_name or route_code}」から外しますか？\n"
            "店舗データ自体はDBに残ります（グループから外すだけです）。"
            f"{code_note}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        sid = None
        raw_id = item.data(Qt.UserRole + 3)
        try:
            if raw_id is not None and str(raw_id).strip() != "":
                sid = int(raw_id)
        except (TypeError, ValueError):
            sid = None
        if sid is None and store_code:
            try:
                store = self.db.get_store_by_code(store_code)
            except Exception:
                store = None
            if store and store.get("id") is not None:
                try:
                    sid = int(store.get("id"))
                except (TypeError, ValueError):
                    sid = None
        if sid is None:
            QMessageBox.warning(self, "ルートから外す", "対象店舗を特定できませんでした。")
            return

        try:
            from services.store_route_membership_service import (
                remove_store_from_route,
                unassign_store_completely,
            )
        except Exception:
            try:
                from store_route_membership_service import (  # type: ignore
                    remove_store_from_route,
                    unassign_store_completely,
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "ルートから外す", f"処理を読み込めませんでした:\n{e}"
                )
                return

        ok = False
        try:
            ok = bool(remove_store_from_route(self.db, sid, route_name, route_code))
            if not ok:
                ok = bool(unassign_store_completely(self.db, sid))
        except Exception as e:
            QMessageBox.warning(self, "ルートから外す", f"外す処理に失敗しました。\n{e}")
            return
        if not ok:
            QMessageBox.warning(self, "ルートから外す", "外す処理に失敗しました。")
            return

        if self._selected_store_code == store_code:
            self._selected_store_code = ""
        # 訪問順選択中ならベースラインからも外す
        if self._pick_mode:
            self._pick_order = [c for c in self._pick_order if c != store_code]
            self._pick_baseline_rows = [
                r
                for r in self._pick_baseline_rows
                if str(r.get("store_code") or "").strip() != store_code
            ]
        editing = route_code
        self.reload()
        if editing and editing in self._route_checks:
            self._set_editing_route(editing)
        self.routes_changed.emit()
        self.status_label.setText(
            f"ルートから外す: {label} ← {route_name or route_code}"
        )

    def _apply_visit_item_style(self, item: QListWidgetItem) -> None:
        if item.checkState() == Qt.Checked:
            item.setForeground(QBrush(QColor("#f0f0f0")))
        else:
            item.setForeground(QBrush(QColor("#9e9e9e")))

    def _ordered_store_codes_from_list(self) -> list:
        codes = []
        for i in range(self.visit_list.count()):
            item = self.visit_list.item(i)
            code = str(item.data(Qt.UserRole) or "").strip()
            if code:
                codes.append(code)
        return codes

    def _visit_includes_from_list(self) -> Dict[str, bool]:
        includes: Dict[str, bool] = {}
        for i in range(self.visit_list.count()):
            item = self.visit_list.item(i)
            code = str(item.data(Qt.UserRole) or "").strip()
            if code:
                includes[code] = item.checkState() == Qt.Checked
        return includes

    def _sync_visit_includes_to_payload(self) -> None:
        """編集中ルートの template_include をリストのチェック状態に合わせる。"""
        route_code = self._editing_route_code
        if not route_code or not self._payload_cache:
            return
        includes = self._visit_includes_from_list()
        for route in self._payload_cache.get("routes") or []:
            if str(route.get("route_code") or "") != route_code:
                continue
            for store in route.get("stores") or []:
                code = str(
                    store.get("store_code") or store.get("supplier_code") or ""
                ).strip()
                if code in includes:
                    store["template_include"] = 1 if includes[code] else 0
                    store["will_visit"] = includes[code]
            break

    def _renumber_visit_list_labels(self) -> None:
        self._visit_reorder_busy = True
        for i in range(self.visit_list.count()):
            item = self.visit_list.item(i)
            store_code = str(item.data(Qt.UserRole) or "").strip()
            store_name = str(item.data(Qt.UserRole + 1) or "").strip()
            notes = str(item.data(Qt.UserRole + 2) or "").strip()
            item.setText(
                self._format_visit_item_label(i + 1, store_name, store_code, notes)
            )
            self._set_visit_item_data(
                item,
                store_code=store_code,
                store_name=store_name,
                notes=notes,
                store_id=item.data(Qt.UserRole + 3),
            )
            self._apply_visit_item_style(item)
        self._visit_reorder_busy = False

    def _stores_for_web_template(self) -> List[Dict[str, Any]]:
        """訪問リストのチェックON店舗を、訪問順のフル店舗データで返す。"""
        if not self._editing_route_code or not self._payload_cache:
            return []
        includes = self._visit_includes_from_list()
        ordered = self._ordered_store_codes_from_list()
        by_code: Dict[str, Dict[str, Any]] = {}
        for route in self._payload_cache.get("routes") or []:
            if str(route.get("route_code") or "") != self._editing_route_code:
                continue
            for s in route.get("stores") or []:
                c = str(s.get("store_code") or s.get("supplier_code") or "").strip()
                if c:
                    by_code[c] = dict(s)
            break
        # payload に無い場合は DB から補完
        missing = [c for c in ordered if c not in by_code]
        if missing and self._editing_route_name:
            try:
                for s in self.db.get_stores_for_route_ordered(self._editing_route_name):
                    c = str(s.get("store_code") or s.get("supplier_code") or "").strip()
                    if c and c not in by_code:
                        by_code[c] = dict(s)
            except Exception:
                pass

        stores: List[Dict[str, Any]] = []
        visit_i = 0
        for code in ordered:
            if not includes.get(code, True):
                continue
            s = by_code.get(code)
            if not s:
                continue
            row = dict(s)
            visit_i += 1
            row["visit_order"] = visit_i
            row["template_include"] = 1
            # 備考はリスト側を優先
            for j in range(self.visit_list.count()):
                item = self.visit_list.item(j)
                if str(item.data(Qt.UserRole) or "").strip() == code:
                    notes = str(item.data(Qt.UserRole + 2) or "").strip()
                    if notes:
                        row["notes"] = notes
                    break
            stores.append(row)
        return stores

    def open_web_template_dialog(self) -> None:
        """店舗エリアから Webテンプレート作成ダイアログを開く。"""
        if not self._editing_route_code:
            QMessageBox.information(
                self,
                "WEBテンプレート作成",
                "先にルート名をダブルクリックして編集対象を選んでください。",
            )
            return
        # 最新のチェック状態を保存してから作成
        self.save_editing_visit_order(silent=True)
        stores = self._stores_for_web_template()
        if not stores:
            QMessageBox.warning(
                self,
                "WEBテンプレート作成",
                "出力する店舗がありません。\n"
                "訪問チェックがONの店舗があるか確認してください。",
            )
            return
        try:
            from .web_template_dialog import WebTemplateFromMapDialog
        except Exception:
            try:
                from web_template_dialog import WebTemplateFromMapDialog  # type: ignore
            except Exception as e:
                QMessageBox.critical(
                    self, "エラー", f"ダイアログを開けませんでした:\n{e}"
                )
                return
        dlg = WebTemplateFromMapDialog(
            self,
            route_code=self._editing_route_code,
            route_name=self._editing_route_name or self._editing_route_code,
            stores=stores,
        )
        dlg.exec()

    def reverse_editing_visit_order(self) -> None:
        """訪問順を反転して保存（スタート⇔ゴール）。"""
        if not self._editing_route_code:
            QMessageBox.information(
                self,
                "訪問順序反転",
                "先にルート名をダブルクリックして編集対象を選んでください。",
            )
            return
        count = self.visit_list.count()
        if count < 2:
            QMessageBox.information(
                self, "訪問順序反転", "反転する店舗が足りません（2店以上必要）。"
            )
            return
        self._visit_reorder_busy = True
        items = [self.visit_list.takeItem(0) for _ in range(count)]
        for item in reversed(items):
            self.visit_list.addItem(item)
        self._visit_reorder_busy = False
        self._renumber_visit_list_labels()
        self.save_editing_visit_order(silent=True)
        self.status_label.setText(
            f"訪問順を反転しました: {self._editing_route_name or self._editing_route_code}"
        )

    def _on_visit_item_changed(self, item: QListWidgetItem) -> None:
        if self._visit_reorder_busy:
            return
        # setForeground でも itemChanged が再発火することがあるためガード
        self._visit_reorder_busy = True
        try:
            self._apply_visit_item_style(item)
        finally:
            self._visit_reorder_busy = False
        self._sync_visit_includes_to_payload()
        # 保存処理内で地図も再描画する
        self.save_editing_visit_order(silent=True)

    def _on_visit_current_changed(
        self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]
    ) -> None:
        """店舗リストで選んだ店の地図アイコンを少し大きくする。"""
        if self._visit_reorder_busy:
            return
        code = ""
        if current is not None:
            code = str(current.data(Qt.UserRole) or "").strip()
        if code == self._selected_store_code:
            return
        self._selected_store_code = code
        self._refresh_map()

    def _on_visit_rows_moved(self, *_args) -> None:
        if self._visit_reorder_busy:
            return
        self._renumber_visit_list_labels()
        self.save_editing_visit_order(silent=True)

    def save_editing_visit_order(self, silent: bool = False) -> None:
        """店舗マスタ display_order ＋ 最新ルート登録の visit_order を保存。"""
        route_code = self._editing_route_code
        route_name = self._editing_route_name
        if not route_code or not route_name:
            if not silent:
                QMessageBox.information(
                    self, "訪問順序", "先にルート名をダブルクリックして編集対象を選んでください。"
                )
            return
        ordered = self._ordered_store_codes_from_list()
        includes = self._visit_includes_from_list()
        if not ordered:
            if not silent:
                QMessageBox.warning(self, "訪問順序", "保存する店舗がありません。")
            return

        # 1) 店舗マスタ表示順 ＋ テンプレート出力（訪問する／しない）
        master_ok = False
        try:
            from services.store_route_membership_service import reorder_route_stores
        except Exception:
            try:
                from store_route_membership_service import reorder_route_stores  # type: ignore
            except Exception:
                reorder_route_stores = None  # type: ignore
        if reorder_route_stores is not None:
            master_ok = bool(
                reorder_route_stores(
                    self.db, route_name, ordered, store_template_includes=includes
                )
            )
        else:
            master_ok = bool(
                self.db.update_store_display_order(
                    route_name,
                    {c: i + 1 for i, c in enumerate(ordered)},
                    includes,
                )
            )

        # 2) 最新ルート登録（route_summaries / store_visit_details）の訪問順
        visit_updated = 0
        try:
            from database.route_db import RouteDatabase
        except Exception:
            try:
                from desktop.database.route_db import RouteDatabase  # type: ignore
            except Exception:
                RouteDatabase = None  # type: ignore
        if RouteDatabase is not None:
            try:
                rdb = RouteDatabase()
                summary = rdb.get_latest_route_summary_for_code(route_code)
                if summary and summary.get("id") is not None:
                    visit_updated = rdb.update_visit_orders_for_summary(
                        int(summary["id"]),
                        {c: i + 1 for i, c in enumerate(ordered)},
                    )
                rdb.close()
            except Exception as e:
                print(f"ルート登録訪問順の同期エラー: {e}")

        # メモリ上の payload も並べ替え＋訪問フラグ反映（地図線をすぐ反映）
        if self._payload_cache:
            for route in self._payload_cache.get("routes") or []:
                if str(route.get("route_code") or "") != route_code:
                    continue
                by_code = {}
                for s in route.get("stores") or []:
                    c = str(s.get("store_code") or s.get("supplier_code") or "").strip()
                    if c:
                        by_code[c] = s
                new_stores = []
                for i, c in enumerate(ordered, start=1):
                    s = by_code.get(c)
                    if not s:
                        continue
                    s = dict(s)
                    s["display_order"] = i
                    if c in includes:
                        s["template_include"] = 1 if includes[c] else 0
                        s["will_visit"] = includes[c]
                    new_stores.append(s)
                # リストに無い店は末尾維持
                for c, s in by_code.items():
                    if c not in set(ordered):
                        new_stores.append(s)
                route["stores"] = new_stores
                break

        self._refresh_map()
        try:
            self.routes_changed.emit()
        except Exception:
            pass

        skip_count = sum(1 for v in includes.values() if not v)
        msg = (
            f"「{route_name}」の周回順を保存しました。\n"
            f"・店舗マスタ表示順: {'OK' if master_ok else '失敗'}\n"
            f"・訪問チェック（テンプレート出力）: "
            f"{len(includes) - skip_count}件行く / {skip_count}件スキップ\n"
            f"・最新ルート登録の訪問順: {visit_updated}件更新"
        )
        self.status_label.setText(
            f"訪問順保存: {route_name}（マスタ{'OK' if master_ok else 'NG'} / "
            f"スキップ{skip_count} / 登録{visit_updated}件）"
        )
        if not silent:
            QMessageBox.information(self, "訪問順序保存", msg)
        elif not master_ok:
            QMessageBox.warning(self, "訪問順序", "店舗マスタ表示順の保存に失敗しました。")

    def _refresh_map(self) -> None:
        if not self._payload_cache:
            return
        selected = self._selected_route_codes()
        colors = self._route_color_map()

        # 編集中ルートはリストのチェック状態を優先
        editing_includes: Optional[Dict[str, bool]] = None
        if self._editing_route_code and self.visit_list.count() > 0:
            editing_includes = self._visit_includes_from_list()

        map_routes: List[Dict[str, Any]] = []
        for route in self._payload_cache.get("routes") or []:
            code = str(route.get("route_code") or "")
            if code not in selected:
                continue
            stores_raw = []
            for s in route.get("stores") or []:
                if not self._store_passes_tag_filter(s):
                    continue
                s2 = dict(s)
                sc = str(
                    s2.get("store_code") or s2.get("supplier_code") or ""
                ).strip()
                if (
                    editing_includes is not None
                    and code == self._editing_route_code
                    and sc in editing_includes
                ):
                    s2["template_include"] = 1 if editing_includes[sc] else 0
                    s2["will_visit"] = editing_includes[sc]
                else:
                    s2["will_visit"] = _will_visit_from_store(s2)
                stores_raw.append(s2)
            stores = _markers_from_stores(stores_raw)
            # 編集中ルート: クリック選択中は番号、通常はスタート／ゴール
            if code and code == self._editing_route_code:
                if self._pick_mode and self._pick_order:
                    pick_rank = {
                        c: i + 1 for i, c in enumerate(self._pick_order) if c
                    }
                    for m in stores:
                        rank = None
                        codes = [str(m.get("store_code") or "").strip()] + [
                            str(x).strip() for x in (m.get("member_codes") or [])
                        ]
                        for c in codes:
                            if c in pick_rank:
                                r = pick_rank[c]
                                if rank is None or r < rank:
                                    rank = r
                        if rank is not None:
                            m["pick_index"] = rank
                    picked = sorted(
                        [m for m in stores if m.get("pick_index")],
                        key=lambda x: int(x.get("pick_index") or 0),
                    )
                    for m in stores:
                        m.pop("endpoint", None)
                    if len(picked) == 1:
                        picked[0]["endpoint"] = "both"
                    elif len(picked) >= 2:
                        picked[0]["endpoint"] = "start"
                        picked[-1]["endpoint"] = "goal"
                else:
                    _mark_route_endpoints(stores)
            # リスト選択中の店舗を強調
            if self._selected_store_code:
                for m in stores:
                    if _store_matches_code(m, self._selected_store_code):
                        m["selected"] = True

            map_routes.append(
                {
                    "route_name": route.get("route_name") or "",
                    "route_code": code,
                    "line_color": colors.get(code, ROUTE_LINE_COLORS[0]),
                    "stores": stores,
                    "road_polyline": [],
                }
            )

        unassigned: List[Dict[str, Any]] = []
        if self.show_unassigned_check.isChecked():
            unassigned_raw = [
                s
                for s in (self._payload_cache.get("unassigned") or [])
                if self._store_passes_tag_filter(s)
            ]
            unassigned = _markers_from_stores(unassigned_raw)
            if self._selected_store_code:
                for m in unassigned:
                    if _store_matches_code(m, self._selected_store_code):
                        m["selected"] = True

        # 別ルートでも近接 HA/HO/OF は1ピンにまとめる（座標0mでもルート違いで分裂しない）
        _merge_cross_route_hardoff_markers(map_routes, unassigned)

        tag_legend = []
        for tag in self._payload_cache.get("tags") or []:
            tid = int(tag["id"])
            if tid in self._allowed_tag_ids():
                tag_legend.append(
                    {"name": tag.get("name"), "color": tag.get("color")}
                )

        visible_stores: List[Dict[str, Any]] = []
        for route in map_routes:
            visible_stores.extend(route.get("stores") or [])
        visible_stores.extend(unassigned)
        present_keys = {
            str(s.get("icon_key") or "other") for s in visible_stores
        }
        icon_legend = []
        for key in MAP_ICON_ORDER:
            if key in present_keys:
                spec = MAP_ICON_DEFS.get(key) or {}
                icon_legend.append(
                    {
                        "key": key,
                        "label": spec.get("label") or key,
                        "bg": spec.get("bg") or DEFAULT_PIN_COLOR,
                    }
                )

        show_endpoints = bool(self._editing_route_code) and any(
            s.get("endpoint")
            for r in map_routes
            if str(r.get("route_code") or "") == self._editing_route_code
            for s in (r.get("stores") or [])
        )

        # 全ルートの中心（近い順の登録候補用。表示ON/OFFに関わらず）
        route_centers: List[Dict[str, Any]] = []
        for route in self._payload_cache.get("routes") or []:
            code = str(route.get("route_code") or "").strip()
            if not code:
                continue
            mean = _mean_lat_lng(list(route.get("stores") or []))
            if not mean:
                continue
            route_centers.append(
                {
                    "route_code": code,
                    "route_name": str(route.get("route_name") or code),
                    "lat": mean[0],
                    "lng": mean[1],
                }
            )

        show_collocation_checked = any(
            bool(s.get("collocation_checked")) and bool(s.get("is_hardoff_family"))
            for s in visible_stores
        )

        leaflet_payload: Dict[str, Any] = {
            "routes": map_routes,
            "unassigned": unassigned,
            "route_centers": route_centers,
            "tag_legend": tag_legend,
            "icon_legend": icon_legend,
            "map_icons": MAP_ICON_DEFS,
            "use_icons": bool(self.icon_check.isChecked()),
            "grayscale": bool(self.grayscale_check.isChecked()),
            "selected_store_code": self._selected_store_code,
            "show_endpoints": show_endpoints,
            "show_collocation_checked": show_collocation_checked,
            "pick_mode": bool(self._pick_mode),
            "editing_route_code": self._editing_route_code or "",
        }

        self._apply_leaflet_payload(leaflet_payload)
