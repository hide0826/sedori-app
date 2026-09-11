#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗マスタ「ルート地図」タブ: ピン＋ルート線＋全選択＋タグ色分け。"""
from __future__ import annotations

import json
import sys
import os
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor
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

ROUTE_LINE_COLORS = [
    "#1e88e5",
    "#fb8c00",
    "#8e24aa",
    "#00897b",
    "#d81b60",
    "#3949ab",
    "#f4511e",
    "#00acc1",
    "#7cb342",
    "#5e35b1",
    "#c0ca33",
    "#546e7a",
]

DEFAULT_PIN_COLOR = "#1976d2"
UNASSIGNED_KEY = "__unassigned__"

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
    return CHECKBOX_BASE_STYLE + f"\nQCheckBox {{ color: {text_color}; font-weight: bold; }}"


def _pin_color_for_store(store: Dict[str, Any]) -> str:
    tags = store.get("tags") or []
    if not tags:
        return DEFAULT_PIN_COLOR
    # attach_tags_to_stores は priority 昇順
    color = (tags[0].get("color") or "").strip()
    return color or DEFAULT_PIN_COLOR


def _store_map_dict(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        lat = float(store.get("latitude"))
        lng = float(store.get("longitude"))
    except (TypeError, ValueError):
        return None
    tags = store.get("tags") or []
    return {
        "id": store.get("id"),
        "store_code": store.get("store_code") or store.get("supplier_code") or "",
        "store_name": store.get("store_name") or "",
        "lat": lat,
        "lng": lng,
        "pin_color": _pin_color_for_store(store),
        "tag_names": [t.get("name") for t in tags if t.get("name")],
        "tag_ids": [int(t["id"]) for t in tags if t.get("id") is not None],
    }


def build_leaflet_html(payload: Dict[str, Any]) -> str:
    """Leaflet 地図 HTML（CDN）。payload は JSON 埋め込み。"""
    data_json = json.dumps(payload, ensure_ascii=False)
    # </script> を壊さない
    data_json = data_json.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body, #map {{ margin:0; padding:0; height:100%; width:100%; background:#1a1a1a; }}
  .legend {{
    background: rgba(30,30,30,0.9); color:#eee; padding:8px 10px;
    border-radius:6px; font: 12px/1.4 sans-serif; max-width:220px;
  }}
  .legend .swatch {{
    display:inline-block; width:12px; height:12px; border-radius:50%;
    margin-right:6px; border:1px solid #fff; vertical-align:middle;
  }}
  .popup-title {{ font-weight:bold; margin-bottom:4px; }}
  .popup-tags {{ color:#90caf9; }}
</style>
</head>
<body>
<div id="map"></div>
<script>
const DATA = {data_json};
const map = L.map('map', {{ zoomControl: true }});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap'
}}).addTo(map);

const layerGroup = L.layerGroup().addTo(map);
const bounds = [];

function addCircle(store, routeName) {{
  const marker = L.circleMarker([store.lat, store.lng], {{
    radius: 8,
    color: '#ffffff',
    weight: 1.5,
    fillColor: store.pin_color || '{DEFAULT_PIN_COLOR}',
    fillOpacity: 0.95
  }});
  const tags = (store.tag_names || []).join(' / ') || '（タグなし）';
  const code = store.store_code ? '[' + store.store_code + '] ' : '';
  marker.bindPopup(
    '<div class="popup-title">' + code + (store.store_name || '') + '</div>' +
    '<div>ルート: ' + (routeName || '未所属') + '</div>' +
    '<div class="popup-tags">タグ: ' + tags + '</div>'
  );
  marker.addTo(layerGroup);
  bounds.push([store.lat, store.lng]);
}}

(DATA.routes || []).forEach(function(route) {{
  const color = route.line_color || '#1e88e5';
  const pts = [];
  (route.stores || []).forEach(function(s) {{
    addCircle(s, route.route_name);
    pts.push([s.lat, s.lng]);
  }});
  if ((route.road_polyline || []).length >= 2) {{
    L.polyline(route.road_polyline, {{
      color: color, weight: 4, opacity: 0.85
    }}).addTo(layerGroup);
  }} else if (pts.length >= 2) {{
    L.polyline(pts, {{
      color: color, weight: 3, opacity: 0.75, dashArray: null
    }}).addTo(layerGroup);
  }}
}});

(DATA.unassigned || []).forEach(function(s) {{
  addCircle(s, '未所属');
}});

if (bounds.length) {{
  map.fitBounds(bounds, {{ padding: [40, 40] }});
}} else {{
  map.setView([35.68, 139.76], 10);
}}

const legend = L.control({{ position: 'bottomleft' }});
legend.onAdd = function() {{
  const div = L.DomUtil.create('div', 'legend');
  let html = '<div style="font-weight:bold;margin-bottom:4px;">凡例</div>';
  html += '<div><span class="swatch" style="background:{DEFAULT_PIN_COLOR}"></span>タグなし</div>';
  (DATA.tag_legend || []).forEach(function(t) {{
    html += '<div><span class="swatch" style="background:' + (t.color||'#888') + '"></span>' +
            (t.name||'') + '</div>';
  }});
  div.innerHTML = html;
  return div;
}};
legend.addTo(map);
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
        self.setup_ui()

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

        toolbar.addStretch()
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

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
        left_layout.addWidget(route_group, 3)

        tag_group = QGroupBox("タグで絞り込み（未チェックは非表示）")
        tag_layout = QVBoxLayout(tag_group)
        tag_btns = QHBoxLayout()
        self.tag_select_all_btn = QPushButton("全選択")
        self.tag_select_all_btn.clicked.connect(self.select_all_tags)
        tag_btns.addWidget(self.tag_select_all_btn)
        self.tag_clear_btn = QPushButton("全解除")
        self.tag_clear_btn.clicked.connect(self.clear_tag_selection)
        tag_btns.addWidget(self.tag_clear_btn)
        tag_btns.addStretch()
        tag_layout.addLayout(tag_btns)

        self.tag_filter_box = QVBoxLayout()
        self.tag_filter_box.setSpacing(2)
        tag_layout.addLayout(self.tag_filter_box)
        self.include_untagged_check = QCheckBox("タグなし店舗も表示")
        self.include_untagged_check.setChecked(True)
        self.include_untagged_check.setStyleSheet(_checkbox_style("#e0e0e0"))
        self.include_untagged_check.toggled.connect(self._on_options_changed)
        tag_layout.addWidget(self.include_untagged_check)
        left_layout.addWidget(tag_group, 2)

        summary_group = QGroupBox("所要時間・距離")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(140)
        summary_layout.addWidget(self.summary_text)
        left_layout.addWidget(summary_group, 1)

        splitter.addWidget(left)

        right = QGroupBox("地図")
        right_layout = QVBoxLayout(right)
        if WEBENGINE_AVAILABLE and QWebEngineView is not None:
            self.map_view = QWebEngineView()
            self.map_view.setMinimumHeight(420)
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
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #adb5bd;")
        layout.addWidget(self.status_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._payload_cache is None:
            self.reload()

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
        for cb in self._tag_checks.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self.include_untagged_check.blockSignals(True)
        self.include_untagged_check.setChecked(True)
        self.include_untagged_check.blockSignals(False)
        self._refresh_map()

    def clear_tag_selection(self) -> None:
        for cb in self._tag_checks.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.include_untagged_check.blockSignals(True)
        self.include_untagged_check.setChecked(False)
        self.include_untagged_check.blockSignals(False)
        self._refresh_map()

    def _on_options_changed(self, *_args) -> None:
        self._refresh_map()

    def reload(self) -> None:
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

        self._clear_layout_widgets(self.tag_filter_box, keep_stretch=False)
        self._tag_checks.clear()
        tags = (self._payload_cache or {}).get("tags") or []
        for tag in tags:
            tid = int(tag["id"])
            color = str(tag.get("color") or DEFAULT_PIN_COLOR)
            cb = QCheckBox(str(tag.get("name") or ""))
            cb.setStyleSheet(_checkbox_style(color))
            cb.setChecked(True if first_load else tid in previously)
            cb.toggled.connect(self._on_options_changed)
            self.tag_filter_box.addWidget(cb)
            self._tag_checks[tid] = cb

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
            stores = []
            for s in stores_raw:
                mapped = _store_map_dict(s)
                if mapped:
                    stores.append(mapped)

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
            for s in self._payload_cache.get("unassigned") or []:
                if not self._store_passes_tag_filter(s):
                    continue
                mapped = _store_map_dict(s)
                if mapped:
                    unassigned.append(mapped)

        tag_legend = []
        for tag in self._payload_cache.get("tags") or []:
            tid = int(tag["id"])
            if tid in self._allowed_tag_ids():
                tag_legend.append(
                    {"name": tag.get("name"), "color": tag.get("color")}
                )

        html_doc = build_leaflet_html(
            {
                "routes": map_routes,
                "unassigned": unassigned,
                "tag_legend": tag_legend,
            }
        )
        if self.map_view is not None:
            self.map_view.setHtml(html_doc, QUrl("https://local.hirio/"))

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
