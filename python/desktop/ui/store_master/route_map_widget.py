#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗マスタ「ルート地図」タブ: 文字ラベル／ピン＋ルート線＋全選択＋タグ色分け。"""
from __future__ import annotations

import json
import sys
import os
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, QUrl, Signal, QSettings, QTimer, QEvent
from PySide6.QtGui import QBrush, QColor
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
        detect_hardoff_family_brand,
        group_hardoff_family_stores,
    )
except Exception:
    try:
        from hardoff_collocation_groups import (  # type: ignore
            detect_hardoff_family_brand,
            group_hardoff_family_stores,
        )
    except Exception:
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


def _store_map_dict(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        lat = float(store.get("latitude"))
        lng = float(store.get("longitude"))
    except (TypeError, ValueError):
        return None
    tags = store.get("tags") or []
    tag_names = [t.get("name") for t in tags if t.get("name")]
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
        "member_names": [],
        "will_visit": _will_visit_from_store(store),
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
        for m in members:
            mc = str(m.get("store_code") or m.get("supplier_code") or "").strip()
            if mc and mc not in member_codes:
                member_codes.append(mc)
        mapped["member_codes"] = member_codes
        if detect_hardoff_family_brand is not None and detect_hardoff_family_brand(
            group.representative
        ):
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
  .popup-tags {{ color:#90caf9; }}
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

function bindStorePopup(marker, store, routeName) {{
  const tags = (store.tag_names || []).join(' / ') || '（タグなし）';
  const code = store.store_code ? '[' + store.store_code + '] ' : '';
  const members = store.member_names || [];
  let extra = '';
  if (members.length > 1) {{
    extra = '<div>併設: ' + members.join(' / ') + '</div>';
  }}
  marker.bindPopup(
    '<div class="popup-title">' + code + (store.store_name || '') + '</div>' +
    extra +
    '<div>ルート: ' + (routeName || '未所属') + '</div>' +
    '<div class="popup-tags">タグ: ' + tags + '</div>'
  );
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

function addCircle(store, routeName) {{
  const skipped = store.will_visit === false;
  const selected = !!store.selected;
  const endpoint = store.endpoint || '';
  const radius = selected ? 12 : (endpoint ? 10 : 8);
  const marker = L.circleMarker([store.lat, store.lng], {{
    radius: radius,
    color: selected ? '#ffeb3b' : '#ffffff',
    weight: selected ? 3 : 1.5,
    fillColor: skipped ? '{SKIPPED_PIN_COLOR}' : (store.pin_color || DEFAULT_PIN),
    fillOpacity: skipped ? 0.75 : 0.95
  }});
  bindStorePopup(marker, store, routeName);
  marker.addTo(layerGroup);
  if (endpoint) {{
    const tip = L.marker([store.lat, store.lng], {{
      icon: L.divIcon({{
        className: 'hirio-pin-wrap',
        html: '<div style="position:relative;width:1px;height:1px;">' +
              endpointHtml(endpoint) + '</div>',
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
  const html =
    '<div class="' + pinClass + '">' +
      endpointHtml(endpoint) +
      pickIndexHtml(store) +
      '<div class="hirio-pin-badge" style="background:' + bg + '">' +
        '<span class="hirio-pin-text" style="color:' + fg + '">' + text + '</span>' +
      '</div>' +
      '<div class="hirio-pin-pointer" style="border-top-color:' + bg + '"></div>' +
    '</div>';
  const marker = L.marker([store.lat, store.lng], {{
    icon: L.divIcon({{
      className: 'hirio-pin-wrap',
      html: html,
      iconSize: size,
      iconAnchor: anchor,
      popupAnchor: [0, selected ? -48 : -36]
    }}),
    keyboard: false,
    opacity: skipped ? 0.85 : 1,
    zIndexOffset: selected ? 600 : (store.pick_index ? 500 : (endpoint ? 400 : 0))
  }});
  bindStorePopup(marker, store, routeName);
  marker.addTo(layerGroup);
}}

function addRouteLine(pts, color, weight, opacity, dashed) {{
  const optsHalo = {{
    color: '#ffffff', weight: weight + 2, opacity: dashed ? 0.35 : 0.7
  }};
  const optsMain = {{
    color: color, weight: weight, opacity: opacity
  }};
  if (dashed) {{
    optsHalo.dashArray = '4 8';
    optsMain.dashArray = '4 8';
  }}
  L.polyline(pts, optsHalo).addTo(layerGroup);
  L.polyline(pts, optsMain).addTo(layerGroup);
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

// ピン・線だけ描き直す。fit=false なら拡大位置は絶対に変えない
window.__HIRIO_UPDATE = function(data, opts) {{
  opts = opts || {{}};
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

  (data.routes || []).forEach(function(route) {{
    const color = route.line_color || '#1e88e5';
    const visitPts = [];
    const skipStores = [];
    const pickPts = [];
    (route.stores || []).forEach(function(s) {{
      const codes = [s.store_code || ''].concat(s.member_codes || []);
      s.selected = !!(selectedCode && codes.indexOf(selectedCode) >= 0);
      if (useIcons) addIconMarker(s, route.route_name, icons);
      else addCircle(s, route.route_name);
      bounds.push([s.lat, s.lng]);
      if (s.pick_index) {{
        pickPts.push({{ idx: s.pick_index, lat: s.lat, lng: s.lng }});
      }}
      if (s.will_visit === false) {{
        skipStores.push(s);
      }} else {{
        visitPts.push([s.lat, s.lng]);
      }}
    }});
    // クリック選択中は、選んだ順の線だけ伸ばす（未選択時は線なし）
    if (data.pick_mode) {{
      if (pickPts.length) {{
        pickPts.sort(function(a, b) {{ return a.idx - b.idx; }});
        const pts = pickPts.map(function(p) {{ return [p.lat, p.lng]; }});
        if (pts.length >= 2) {{
          addRouteLine(pts, color, dashWeight, lineOpacity, false);
        }}
      }}
    }} else if ((route.road_polyline || []).length >= 2) {{
      addRouteLine(route.road_polyline, color, lineWeight, lineOpacity, false);
    }} else if (visitPts.length >= 2) {{
      addRouteLine(visitPts, color, dashWeight, lineOpacity, false);
    }}
    // 行かない店: 最後に訪問する店から薄い点線（選択モード中は非表示）
    if (!data.pick_mode && visitPts.length >= 1 && skipStores.length) {{
      const last = visitPts[visitPts.length - 1];
      skipStores.forEach(function(s) {{
        addRouteLine(
          [last, [s.lat, s.lng]],
          color,
          2,
          0.45,
          true
        );
      }});
    }}
  }});

  (data.unassigned || []).forEach(function(s) {{
    if (useIcons) addIconMarker(s, '未所属', icons);
    else addCircle(s, '未所属');
    bounds.push([s.lat, s.lng]);
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
}};

window.__HIRIO_FIT_BOUNDS = function(points) {{
  if (!points || !points.length) return false;
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
            "編集中ルートの選択を解除し、全体マップ表示に戻します"
        )
        self.clear_edit_route_btn.setStyleSheet(
            "QPushButton { background: #546e7a; color: #ffffff; border: none;"
            " padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:hover:!disabled { background: #607d8b; }"
            "QPushButton:disabled { background: #424242; color: #9e9e9e; }"
        )
        self.clear_edit_route_btn.clicked.connect(self.clear_editing_route_focus)
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
            "チェックOFF＝行かない（地図でグレー＋最後尾から点線）。\n"
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
        visit_btns.addStretch()
        self.visit_section.body_layout.addLayout(visit_btns)

        self.visit_list = QListWidget()
        self.visit_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.visit_list.setDefaultDropAction(Qt.MoveAction)
        self.visit_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.visit_list.setAlternatingRowColors(True)
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
                "ルート名をダブルクリック: 店舗リスト表示＋地図拡大"
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
        """pick_order に合わせて店舗リスト・地図を更新。"""
        baseline = self._pick_baseline_rows or self._snapshot_visit_items()
        if not baseline:
            self._refresh_map()
            self._refresh_pick_status_text()
            self._update_pick_nav_buttons()
            return
        by_code = {r["store_code"]: dict(r) for r in baseline}
        # いまのチェック状態を優先
        for row in self._snapshot_visit_items():
            code = row["store_code"]
            if code in by_code:
                by_code[code]["checked"] = row["checked"]
        remaining = [
            by_code[r["store_code"]]
            for r in baseline
            if r["store_code"] not in set(self._pick_order)
        ]
        new_rows = [
            by_code[c] for c in self._pick_order if c in by_code
        ] + remaining
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
                    "checked": item.checkState() == Qt.Checked,
                }
            )
        return rows

    def _rebuild_visit_list_from_rows(self, rows: List[Dict[str, Any]]) -> None:
        self._visit_reorder_busy = True
        self.visit_list.clear()
        for idx, row in enumerate(rows, start=1):
            store_code = str(row.get("store_code") or "").strip()
            store_name = str(row.get("store_name") or "").strip()
            notes = str(row.get("notes") or "").strip()
            label = self._format_visit_item_label(idx, store_name, store_code, notes)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, store_code)
            item.setData(Qt.UserRole + 1, store_name)
            item.setData(Qt.UserRole + 2, notes)
            tip = f"{store_name}"
            if store_code:
                tip += f" [{store_code}]"
            if notes:
                tip += f"\n備考: {notes}"
            item.setToolTip(tip)
            item.setFlags(
                item.flags()
                | Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsDragEnabled
                | Qt.ItemIsUserCheckable
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

    def clear_editing_route_focus(self) -> None:
        """編集中ルートを解除して全体マップ表示に戻す。"""
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
        QTimer.singleShot(200, self._fit_map_to_all_visible)
        self.status_label.setText("ルート選択を解除しました（全体マップ）")

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
            item.setData(Qt.UserRole, store_code)
            item.setData(Qt.UserRole + 1, store_name)
            item.setData(Qt.UserRole + 2, notes)
            tip = f"{store_name}"
            if store_code:
                tip += f" [{store_code}]"
            if notes:
                tip += f"\n備考: {notes}"
            item.setToolTip(tip)
            item.setFlags(
                item.flags()
                | Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsDragEnabled
                | Qt.ItemIsUserCheckable
            )
            will_visit = _will_visit_from_store(store)
            item.setCheckState(Qt.Checked if will_visit else Qt.Unchecked)
            self._apply_visit_item_style(item)
            self.visit_list.addItem(item)
        self._editing_route_name = route_name
        self._visit_reorder_busy = False

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
            tip = f"{store_name}"
            if store_code:
                tip += f" [{store_code}]"
            if notes:
                tip += f"\n備考: {notes}"
            item.setToolTip(tip)
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

        leaflet_payload: Dict[str, Any] = {
            "routes": map_routes,
            "unassigned": unassigned,
            "tag_legend": tag_legend,
            "icon_legend": icon_legend,
            "map_icons": MAP_ICON_DEFS,
            "use_icons": bool(self.icon_check.isChecked()),
            "grayscale": bool(self.grayscale_check.isChecked()),
            "selected_store_code": self._selected_store_code,
            "show_endpoints": show_endpoints,
            "pick_mode": bool(self._pick_mode),
        }

        self._apply_leaflet_payload(leaflet_payload)
