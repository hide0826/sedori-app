#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗マスタ「ルート地図」タブ: 文字ラベル／ピン＋ルート線＋全選択＋タグ色分け。"""
from __future__ import annotations

import json
import sys
import os
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, QUrl, Signal, QSettings, QTimer
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
    QTextEdit,
    QScrollArea,
    QFrame,
    QTabWidget,
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

try:
    from services.google_maps_directions_service import fetch_driving_route
except Exception:
    try:
        from google_maps_directions_service import (  # type: ignore
            fetch_driving_route,
        )
    except Exception:
        fetch_driving_route = None  # type: ignore

from .store_tags_dialog import StoreTagsDialog

try:
    from services.store_brand_tag_service import (
        MAP_ICON_DEFS,
        MAP_ICON_ORDER,
        hardoff_collocation_icon_key,
        resolve_map_icon_key,
    )
except Exception:
    try:
        from store_brand_tag_service import (  # type: ignore
            MAP_ICON_DEFS,
            MAP_ICON_ORDER,
            hardoff_collocation_icon_key,
            resolve_map_icon_key,
        )
    except Exception:
        MAP_ICON_DEFS = {}  # type: ignore
        MAP_ICON_ORDER = ()  # type: ignore

        def resolve_map_icon_key(store_name: str, tag_names=None) -> str:
            return "other"

        def hardoff_collocation_icon_key(member_count: int) -> str:
            return "hardoff1"

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
UNASSIGNED_KEY = "__unassigned__"

SETTINGS_ORG = "HIRIO"
SETTINGS_APP = "desktop"
SETTINGS_MAIN_SPLITTER = "store_master/route_map/main_splitter"
SETTINGS_LEFT_SPLITTER = "store_master/route_map/left_splitter"
SETTINGS_MAP_VIEW = "store_master/route_map/map_view"

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

# 白背景パネル用（タグ絞り込み）
CHECKBOX_LIGHT_BASE_STYLE = """
QCheckBox {
    spacing: 8px;
    padding: 3px 2px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #757575;
    border-radius: 3px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #4caf50;
    border: 2px solid #2e7d32;
}
QCheckBox::indicator:unchecked {
    background: #ffffff;
    border: 2px solid #757575;
}
"""

TAG_FILTER_GROUP_STYLE = """
QGroupBox {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #bdbdbd;
    border-radius: 6px;
    margin-top: 12px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #212121;
    background-color: #ffffff;
}
"""


def _checkbox_style(text_color: str) -> str:
    return CHECKBOX_BASE_STYLE + f"\nQCheckBox {{ color: {text_color}; font-weight: bold; }}"


def _checkbox_style_light(text_color: str) -> str:
    """白背景上でも色付き文字が読みやすいチェックボックス。"""
    return (
        CHECKBOX_LIGHT_BASE_STYLE
        + f"\nQCheckBox {{ color: {text_color}; font-weight: bold; }}"
    )


def _pin_color_for_store(store: Dict[str, Any]) -> str:
    tags = store.get("tags") or []
    if not tags:
        return DEFAULT_PIN_COLOR
    # attach_tags_to_stores は priority 昇順
    color = (tags[0].get("color") or "").strip()
    return color or DEFAULT_PIN_COLOR


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
  .hirio-pin-text {{
    color: #fff;
    font: 700 11px/1 "Segoe UI","Meiryo UI","Yu Gothic UI",sans-serif;
    letter-spacing: 0;
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
}}

function addCircle(store, routeName) {{
  const marker = L.circleMarker([store.lat, store.lng], {{
    radius: 8,
    color: '#ffffff',
    weight: 1.5,
    fillColor: store.pin_color || DEFAULT_PIN,
    fillOpacity: 0.95
  }});
  bindStorePopup(marker, store, routeName);
  marker.addTo(layerGroup);
}}

function addIconMarker(store, routeName, icons) {{
  const key = store.icon_key || 'other';
  const spec = (icons && icons[key]) || (icons && icons.other) || {{ bg: DEFAULT_PIN, text: '他', fg: '#ffffff' }};
  const bg = spec.bg || DEFAULT_PIN;
  const fg = spec.fg || '#ffffff';
  const text = spec.text || '他';
  const html =
    '<div class="hirio-pin">' +
      '<div class="hirio-pin-badge" style="background:' + bg + '">' +
        '<span class="hirio-pin-text" style="color:' + fg + '">' + text + '</span>' +
      '</div>' +
      '<div class="hirio-pin-pointer" style="border-top-color:' + bg + '"></div>' +
    '</div>';
  const marker = L.marker([store.lat, store.lng], {{
    icon: L.divIcon({{
      className: 'hirio-pin-wrap',
      html: html,
      iconSize: [34, 44],
      iconAnchor: [17, 42],
      popupAnchor: [0, -36]
    }}),
    keyboard: false
  }});
  bindStorePopup(marker, store, routeName);
  marker.addTo(layerGroup);
}}

function addRouteLine(pts, color, weight, opacity) {{
  L.polyline(pts, {{
    color: '#ffffff', weight: weight + 2, opacity: 0.7
  }}).addTo(layerGroup);
  L.polyline(pts, {{
    color: color, weight: weight, opacity: opacity
  }}).addTo(layerGroup);
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
      html += '<div><span class="swatch" style="background:' + DEFAULT_PIN + '"></span>タグなし</div>';
      (data.tag_legend || []).forEach(function(t) {{
        html += '<div><span class="swatch" style="background:' + (t.color||'#888') + '"></span>' +
                (t.name||'') + '</div>';
      }});
    }}
    div.innerHTML = html;
    return div;
  }};
  legendControl.addTo(map);

  modeBadgeControl = L.control({{ position: 'topright' }});
  modeBadgeControl.onAdd = function() {{
    const div = L.DomUtil.create('div', 'mode-badge');
    div.textContent = data.grayscale ? '白黒地図' : 'カラー地図';
    return div;
  }};
  modeBadgeControl.addTo(map);
}}

// ピン・線だけ描き直す。fit=false なら拡大位置は絶対に変えない
window.__HIRIO_UPDATE = function(data, opts) {{
  opts = opts || {{}};
  window.__HIRIO_DATA = data || {{}};
  const useIcons = !!data.use_icons;
  const icons = data.map_icons || {{}};
  const grayscale = !!data.grayscale;
  const lineWeight = grayscale ? 5 : 4;
  const lineOpacity = grayscale ? 0.95 : 0.85;
  const dashWeight = grayscale ? 4 : 3;
  const bounds = [];

  hirioSetGrayscale(grayscale);
  layerGroup.clearLayers();

  (data.routes || []).forEach(function(route) {{
    const color = route.line_color || '#1e88e5';
    const pts = [];
    (route.stores || []).forEach(function(s) {{
      if (useIcons) addIconMarker(s, route.route_name, icons);
      else addCircle(s, route.route_name);
      pts.push([s.lat, s.lng]);
      bounds.push([s.lat, s.lng]);
    }});
    if ((route.road_polyline || []).length >= 2) {{
      addRouteLine(route.road_polyline, color, lineWeight, lineOpacity);
    }} else if (pts.length >= 2) {{
      addRouteLine(pts, color, dashWeight, lineOpacity);
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
        self._road_cache: Dict[str, Dict[str, Any]] = {}
        self._route_checks: Dict[str, QCheckBox] = {}
        self._route_colors: Dict[str, str] = {}
        self._tag_checks: Dict[int, QCheckBox] = {}
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

        self.road_check = QCheckBox("道路沿いルート＋所要時間")
        self.road_check.setStyleSheet(_checkbox_style("#e0e0e0"))
        self.road_check.setToolTip(
            "ON: Google Directions API で道路沿いの線と所要時間を取得します。\n"
            "API キー（設定タブ）と Directions API の有効化が必要です。\n"
            "失敗時は直線ルートにフォールバックします。"
        )
        self.road_check.toggled.connect(self._on_options_changed)
        toolbar.addWidget(self.road_check)

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
            "OFF: 従来の色付き丸ピン（タグ色）"
        )
        self.icon_check.toggled.connect(self._on_options_changed)
        toolbar.addWidget(self.icon_check)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.left_splitter = QSplitter(Qt.Vertical)
        self.left_splitter.setChildrenCollapsible(False)

        route_group = QGroupBox("ルート（チェックで表示）")
        route_layout = QVBoxLayout(route_group)
        route_btns = QHBoxLayout()
        self.select_all_btn = QPushButton("全選択")
        self.select_all_btn.clicked.connect(self.select_all_routes)
        route_btns.addWidget(self.select_all_btn)
        self.clear_btn = QPushButton("全解除")
        self.clear_btn.clicked.connect(self.clear_route_selection)
        route_btns.addWidget(self.clear_btn)
        route_btns.addStretch()
        route_layout.addLayout(route_btns)

        self.route_scroll = QScrollArea()
        self.route_scroll.setWidgetResizable(True)
        self.route_scroll.setFrameShape(QFrame.NoFrame)
        self.route_list_host = QWidget()
        self.route_list_box = QVBoxLayout(self.route_list_host)
        self.route_list_box.setContentsMargins(4, 4, 4, 4)
        self.route_list_box.setSpacing(2)
        self.route_list_box.addStretch()
        self.route_scroll.setWidget(self.route_list_host)
        route_layout.addWidget(self.route_scroll)
        self.left_splitter.addWidget(route_group)

        tag_group = QGroupBox("タグで絞り込み（未チェックは非表示）")
        tag_group.setStyleSheet(TAG_FILTER_GROUP_STYLE)
        tag_layout = QVBoxLayout(tag_group)
        tag_btns = QHBoxLayout()
        self.tag_select_all_btn = QPushButton("全選択")
        self.tag_select_all_btn.setToolTip("いま表示中のタブ内だけ全選択します")
        self.tag_select_all_btn.clicked.connect(self.select_all_tags)
        tag_btns.addWidget(self.tag_select_all_btn)
        self.tag_clear_btn = QPushButton("全解除")
        self.tag_clear_btn.setToolTip("いま表示中のタブ内だけ全解除します")
        self.tag_clear_btn.clicked.connect(self.clear_tag_selection)
        tag_btns.addWidget(self.tag_clear_btn)
        tag_btns.addStretch()
        tag_layout.addLayout(tag_btns)

        self.tag_tabs = QTabWidget()
        self.tag_tabs.setStyleSheet(
            "QTabWidget::pane { background: #ffffff; border: 1px solid #bdbdbd; }"
            "QTabBar::tab { background: #eeeeee; color: #212121; padding: 6px 12px; }"
            "QTabBar::tab:selected { background: #ffffff; font-weight: bold; }"
        )

        # 店舗種別タブ
        brand_page = QWidget()
        brand_page.setStyleSheet("background: #ffffff;")
        brand_page_layout = QVBoxLayout(brand_page)
        brand_page_layout.setContentsMargins(0, 0, 0, 0)
        self.brand_tag_scroll = QScrollArea()
        self.brand_tag_scroll.setWidgetResizable(True)
        self.brand_tag_scroll.setFrameShape(QFrame.NoFrame)
        self.brand_tag_scroll.setStyleSheet(
            "QScrollArea { background: #ffffff; border: none; }"
        )
        self.brand_tag_host = QWidget()
        self.brand_tag_host.setStyleSheet("background: #ffffff;")
        self.brand_tag_box = QVBoxLayout(self.brand_tag_host)
        self.brand_tag_box.setContentsMargins(4, 4, 4, 4)
        self.brand_tag_box.setSpacing(2)
        self.brand_tag_scroll.setWidget(self.brand_tag_host)
        brand_page_layout.addWidget(self.brand_tag_scroll)
        self.tag_tabs.addTab(brand_page, "店舗種別")

        # 評価系タブ
        quality_page = QWidget()
        quality_page.setStyleSheet("background: #ffffff;")
        quality_page_layout = QVBoxLayout(quality_page)
        quality_page_layout.setContentsMargins(0, 0, 0, 0)
        self.quality_tag_scroll = QScrollArea()
        self.quality_tag_scroll.setWidgetResizable(True)
        self.quality_tag_scroll.setFrameShape(QFrame.NoFrame)
        self.quality_tag_scroll.setStyleSheet(
            "QScrollArea { background: #ffffff; border: none; }"
        )
        self.quality_tag_host = QWidget()
        self.quality_tag_host.setStyleSheet("background: #ffffff;")
        self.quality_tag_box = QVBoxLayout(self.quality_tag_host)
        self.quality_tag_box.setContentsMargins(4, 4, 4, 4)
        self.quality_tag_box.setSpacing(2)
        self.quality_tag_scroll.setWidget(self.quality_tag_host)
        quality_page_layout.addWidget(self.quality_tag_scroll)
        self.tag_tabs.addTab(quality_page, "評価・メモ")

        # 互換: 旧コード参照用（店舗種別ボックスをデフォルト）
        self.tag_filter_box = self.brand_tag_box
        tag_layout.addWidget(self.tag_tabs, 1)

        self.include_untagged_check = QCheckBox("タグなし店舗も表示")
        self.include_untagged_check.setChecked(True)
        self.include_untagged_check.setStyleSheet(_checkbox_style_light("#212121"))
        self.include_untagged_check.toggled.connect(self._on_options_changed)
        tag_layout.addWidget(self.include_untagged_check)
        self.left_splitter.addWidget(tag_group)

        summary_group = QGroupBox("所要時間・距離")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(80)
        summary_layout.addWidget(self.summary_text)
        self.left_splitter.addWidget(summary_group)

        self.left_splitter.setStretchFactor(0, 3)
        self.left_splitter.setStretchFactor(1, 2)
        self.left_splitter.setStretchFactor(2, 1)
        left_layout.addWidget(self.left_splitter)
        left.setMinimumWidth(220)

        self.main_splitter.addWidget(left)

        right = QGroupBox("地図")
        right_layout = QVBoxLayout(right)
        if WEBENGINE_AVAILABLE and QWebEngineView is not None:
            self.map_view = QWebEngineView()
            self.map_view.setMinimumHeight(420)
            self.map_view.setMinimumWidth(360)
            self.map_view.loadFinished.connect(self._on_map_load_finished)
            self.map_view.titleChanged.connect(self._on_map_title_changed)
            right_layout.addWidget(self.map_view)
        else:
            self.map_view = None
            fallback = QLabel(
                "地図表示には PySide6-WebEngine が必要です。\n"
                "pip install PySide6-WebEngine 後に再起動してください。"
            )
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setWordWrap(True)
            right_layout.addWidget(fallback)
        self.main_splitter.addWidget(right)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 4)
        # 初回デフォルト: 地図を広めに
        self.main_splitter.setSizes([280, 920])
        self.left_splitter.setSizes([260, 200, 120])

        self.main_splitter.splitterMoved.connect(self._save_splitter_sizes)
        self.left_splitter.splitterMoved.connect(self._save_splitter_sizes)

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
        left_sizes = settings.value(SETTINGS_LEFT_SPLITTER)
        try:
            if isinstance(main_sizes, list) and len(main_sizes) >= 2:
                self.main_splitter.setSizes([int(x) for x in main_sizes[:2]])
            elif main_sizes is not None:
                # QSettings が QVariantList / 文字列になる場合
                parsed = [int(x) for x in list(main_sizes)]
                if len(parsed) >= 2:
                    self.main_splitter.setSizes(parsed[:2])
        except Exception:
            pass
        try:
            if isinstance(left_sizes, list) and len(left_sizes) >= 3:
                self.left_splitter.setSizes([int(x) for x in left_sizes[:3]])
            elif left_sizes is not None:
                parsed = [int(x) for x in list(left_sizes)]
                if len(parsed) >= 3:
                    self.left_splitter.setSizes(parsed[:3])
        except Exception:
            pass
        self._splitter_sizes_restored = True

    def _save_splitter_sizes(self, *_args) -> None:
        try:
            settings = self._settings()
            settings.setValue(SETTINGS_MAIN_SPLITTER, self.main_splitter.sizes())
            settings.setValue(SETTINGS_LEFT_SPLITTER, self.left_splitter.sizes())
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
        if getattr(self, "tag_tabs", None) is not None and self.tag_tabs.currentIndex() == 1:
            return set(getattr(self, "_quality_tag_ids", set()))
        return set(getattr(self, "_brand_tag_ids", set()))

    def _on_options_changed(self, *_args) -> None:
        self._refresh_map()

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

        routes = (self._payload_cache or {}).get("routes") or []
        for idx, route in enumerate(routes):
            code = str(route.get("route_code") or "")
            name = str(route.get("route_name") or "")
            count = int(route.get("store_count") or 0)
            color = ROUTE_LINE_COLORS[idx % len(ROUTE_LINE_COLORS)]
            cb = QCheckBox(f"{name}（{count}）")
            cb.setStyleSheet(_checkbox_style(color))
            checked = first_load or code in previously
            cb.setChecked(checked)
            cb.toggled.connect(self._on_options_changed)
            self.route_list_box.addWidget(cb)
            self._route_checks[code] = cb
            self._route_colors[code] = color
        self.route_list_box.addStretch()

    def _rebuild_tag_filters(self) -> None:
        previously: Set[int] = {
            tid for tid, cb in self._tag_checks.items() if cb.isChecked()
        }
        first_load = not self._tag_checks

        self._clear_layout_widgets(self.brand_tag_box, keep_stretch=False)
        self._clear_layout_widgets(self.quality_tag_box, keep_stretch=False)
        self._tag_checks.clear()
        self._brand_tag_ids = set()
        self._quality_tag_ids = set()

        try:
            from services.store_brand_tag_service import (
                is_brand_tag_name,
                is_quality_tag_name,
            )
        except Exception:
            try:
                from store_brand_tag_service import (  # type: ignore
                    is_brand_tag_name,
                    is_quality_tag_name,
                )
            except Exception:
                def is_brand_tag_name(name: str) -> bool:
                    return False

                def is_quality_tag_name(name: str) -> bool:
                    return name in (
                        "大型店舗",
                        "値付け甘い",
                        "あまり行かなくて良い",
                    )

        tags = (self._payload_cache or {}).get("tags") or []
        brand_tags = []
        quality_tags = []
        other_tags = []
        for tag in tags:
            name = str(tag.get("name") or "")
            if is_brand_tag_name(name) or name == "その他":
                brand_tags.append(tag)
            elif is_quality_tag_name(name):
                quality_tags.append(tag)
            else:
                other_tags.append(tag)

        def _add_checks(tag_list, layout, id_bucket: Set[int]) -> None:
            for tag in tag_list:
                tid = int(tag["id"])
                color = str(tag.get("color") or DEFAULT_PIN_COLOR)
                cb = QCheckBox(str(tag.get("name") or ""))
                cb.setStyleSheet(_checkbox_style_light(color))
                cb.setChecked(True if first_load else tid in previously)
                cb.toggled.connect(self._on_options_changed)
                layout.addWidget(cb)
                self._tag_checks[tid] = cb
                id_bucket.add(tid)

        _add_checks(brand_tags, self.brand_tag_box, self._brand_tag_ids)
        _add_checks(quality_tags, self.quality_tag_box, self._quality_tag_ids)
        # 未分類タグは評価・メモ側へ
        _add_checks(other_tags, self.quality_tag_box, self._quality_tag_ids)
        self.brand_tag_box.addStretch()
        self.quality_tag_box.addStretch()

    def _selected_route_codes(self) -> Set[str]:
        return {code for code, cb in self._route_checks.items() if cb.isChecked()}

    def _route_color_map(self) -> Dict[str, str]:
        return dict(self._route_colors)

    def _allowed_tag_ids(self) -> Set[int]:
        return {tid for tid, cb in self._tag_checks.items() if cb.isChecked()}

    def _store_passes_tag_filter(self, store: Dict[str, Any]) -> bool:
        allowed = self._allowed_tag_ids()
        tag_ids = []
        for t in store.get("tags") or []:
            try:
                tag_ids.append(int(t["id"]))
            except (TypeError, ValueError, KeyError):
                pass
        if not tag_ids:
            return self.include_untagged_check.isChecked()
        # いずれかの表示タグがあればOK
        return any(tid in allowed for tid in tag_ids)

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
        """拡大・移動のたびに document.title 経由で位置を受け取る。"""
        text = str(title or "")
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

    def _refresh_map(self) -> None:
        if not self._payload_cache:
            return
        selected = self._selected_route_codes()
        colors = self._route_color_map()
        use_road = self.road_check.isChecked()
        summary_lines: List[str] = []

        map_routes: List[Dict[str, Any]] = []
        for route in self._payload_cache.get("routes") or []:
            code = str(route.get("route_code") or "")
            if code not in selected:
                continue
            stores_raw = [
                s for s in (route.get("stores") or []) if self._store_passes_tag_filter(s)
            ]
            stores = _markers_from_stores(stores_raw)

            entry: Dict[str, Any] = {
                "route_name": route.get("route_name") or "",
                "route_code": code,
                "line_color": colors.get(code, ROUTE_LINE_COLORS[0]),
                "stores": stores,
                "road_polyline": [],
            }

            if use_road and len(stores_raw) >= 2 and fetch_driving_route:
                cache_key = code + "|" + ",".join(
                    str(s.get("id")) for s in stores_raw if s.get("id") is not None
                )
                road = self._road_cache.get(cache_key)
                if road is None:
                    result = fetch_driving_route(stores_raw)
                    if result.ok:
                        road = {
                            "polyline": result.polyline,
                            "distance_km": result.distance_km,
                            "duration_text": result.duration_text,
                            "error": "",
                        }
                    else:
                        road = {
                            "polyline": [],
                            "distance_km": 0,
                            "duration_text": "",
                            "error": result.error,
                        }
                    self._road_cache[cache_key] = road
                entry["road_polyline"] = road.get("polyline") or []
                name = route.get("route_name") or code
                if road.get("duration_text"):
                    summary_lines.append(
                        f"・{name}: {road['duration_text']} / {road['distance_km']} km"
                    )
                elif road.get("error"):
                    summary_lines.append(f"・{name}: 直線表示（{road['error']}）")
            elif use_road and len(stores) >= 2:
                summary_lines.append(
                    f"・{route.get('route_name') or code}: 直線表示（座標不足）"
                )

            map_routes.append(entry)

        unassigned: List[Dict[str, Any]] = []
        if self.show_unassigned_check.isChecked():
            unassigned_raw = [
                s
                for s in (self._payload_cache.get("unassigned") or [])
                if self._store_passes_tag_filter(s)
            ]
            unassigned = _markers_from_stores(unassigned_raw)

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

        leaflet_payload: Dict[str, Any] = {
            "routes": map_routes,
            "unassigned": unassigned,
            "tag_legend": tag_legend,
            "icon_legend": icon_legend,
            "map_icons": MAP_ICON_DEFS,
            "use_icons": bool(self.icon_check.isChecked()),
            "grayscale": bool(self.grayscale_check.isChecked()),
        }

        if not summary_lines:
            if use_road:
                self.summary_text.setPlainText(
                    "道路ルート情報はありません。ルートを選択するか API キーを確認してください。"
                )
            else:
                self.summary_text.setPlainText(
                    "直線ルート表示中。道路沿い・所要時間が必要なときは左上のチェックをONにしてください。"
                )
        else:
            self.summary_text.setPlainText("\n".join(summary_lines))

        self._apply_leaflet_payload(leaflet_payload)
