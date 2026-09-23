# -*- coding: utf-8 -*-
"""ルート箱から仕入／画像／証憑へ振り分ける（Phase 3）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

CSV_DIR_NAME = "仕入CSV"
PRODUCT_DIR_NAME = "商品画像"
RECEIPT_DIR_NAME = "レシート画像"


@dataclass
class RouteFolderLayout:
    root: Path
    csv_path: Optional[Path] = None
    product_dir: Optional[Path] = None
    receipt_dir: Optional[Path] = None
    route_template: Optional[Path] = None
    route_json: Optional[Path] = None
    notes: List[str] = field(default_factory=list)


def find_stocklist_csv(route_folder: Path) -> Optional[Path]:
    """仕入CSV/ 優先、無ければ直下の StockList_*.csv。"""
    sub = route_folder / CSV_DIR_NAME
    candidates: List[Path] = []
    if sub.is_dir():
        candidates.extend(sorted(sub.glob("StockList_*.csv")))
        if not candidates:
            candidates.extend(sorted(p for p in sub.glob("*.csv") if p.is_file()))
    if not candidates:
        candidates.extend(sorted(route_folder.glob("StockList_*.csv")))
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except OSError:
        return candidates[0]


def find_route_template(route_folder: Path) -> Optional[Path]:
    candidates = sorted(
        list(route_folder.glob("route_template_*.xlsx"))
        + list(route_folder.glob("route_template_*.xls"))
    )
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except OSError:
        return candidates[0]


def resolve_route_folder_layout(route_folder: Path) -> RouteFolderLayout:
    root = Path(route_folder)
    layout = RouteFolderLayout(root=root)
    if not root.is_dir():
        layout.notes.append("フォルダが存在しません")
        return layout

    layout.csv_path = find_stocklist_csv(root)
    if layout.csv_path is None:
        layout.notes.append("StockList CSV が見つかりません（仕入CSV/ または直下）")

    product = root / PRODUCT_DIR_NAME
    if product.is_dir():
        layout.product_dir = product
    else:
        layout.notes.append("商品画像/ がありません")

    receipt = root / RECEIPT_DIR_NAME
    if receipt.is_dir():
        layout.receipt_dir = receipt
    else:
        layout.notes.append("レシート画像/ がありません")

    layout.route_template = find_route_template(root)
    rj = root / "route.json"
    if rj.is_file():
        layout.route_json = rj

    return layout


def choose_route_time_source(layout: RouteFolderLayout) -> str:
    """時刻の読み込み元。route.json があれば Excel より優先する。"""
    if layout.route_json is not None and Path(layout.route_json).is_file():
        return "json"
    if layout.route_template is not None and Path(layout.route_template).is_file():
        return "xlsx"
    return "none"


def _hhmm(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if " " in text:
        text = text.split()[-1]
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return ""


def _fee(value: Any) -> float:
    text = str(value or "").strip().replace(",", "").replace("円", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def route_json_to_ui_model(doc: Dict[str, Any]) -> Dict[str, Any]:
    """route.json を、ルート画面が持つ項目の辞書にする（Qt 不要）。"""
    if not isinstance(doc, dict):
        raise ValueError("route.json がオブジェクトではありません")
    route_date = str(doc.get("route_date") or "").strip()
    departure = _hhmm(doc.get("departure_time"))
    returning = _hhmm(doc.get("return_time"))

    def _combine(hhmm: str) -> str:
        if not hhmm:
            return ""
        if route_date:
            return f"{route_date} {hhmm}:00"
        return hhmm

    visits: List[Dict[str, str]] = []
    stores = list(doc.get("stores") or [])
    stores.sort(key=lambda s: ((s or {}).get("order") or 0, str((s or {}).get("store_code") or "")))
    for store in stores:
        if not isinstance(store, dict):
            continue
        code = str(store.get("store_code") or "").strip()
        if not code:
            continue
        visits.append(
            {
                "store_code": code,
                "store_name": str(store.get("store_name") or "").strip(),
                "in_time": _hhmm(store.get("in_time")),
                "out_time": _hhmm(store.get("out_time")),
                "notes": str(store.get("notes") or "").strip(),
            }
        )
    return {
        "source": "json",
        "route_date": route_date,
        "route_name": str(doc.get("route_name") or "").strip(),
        "route_code": str(doc.get("route_code") or "").strip(),
        "departure_time": _combine(departure),
        "return_time": _combine(returning),
        "toll_fee_outbound": _fee(doc.get("toll_outbound")),
        "toll_fee_return": _fee(doc.get("toll_return")),
        "visits": visits,
    }


def load_route_json_model(path: Path) -> Dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return route_json_to_ui_model(doc)
