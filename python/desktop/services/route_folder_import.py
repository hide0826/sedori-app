# -*- coding: utf-8 -*-
"""ルート箱から仕入／画像／証憑へ振り分ける（Phase 3）。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CSV_DIR_NAME = "仕入CSV"
PRODUCT_DIR_NAME = "商品画像"
RECEIPT_DIR_NAME = "レシート画像"
# 仕入帳（画像込みで大きい）は同期しない。ここだけ Google ドライブに載せる。
ROUTE_INSURANCE_ROOT = Path(r"D:\せどり総合\店舗せどり仕入リスト入れ\ルート保険")


@dataclass
class RouteFolderLayout:
    root: Path
    csv_path: Optional[Path] = None
    product_dir: Optional[Path] = None
    receipt_dir: Optional[Path] = None
    route_template: Optional[Path] = None
    route_json: Optional[Path] = None
    notes: List[str] = field(default_factory=list)


def is_under_route_insurance(path: Path) -> bool:
    """パスがルート保険の中か。"""
    try:
        Path(path).resolve().relative_to(ROUTE_INSURANCE_ROOT.resolve())
        return True
    except (ValueError, OSError):
        return False


def matching_insurance_dir(route_folder: Path) -> Optional[Path]:
    """仕入帳の箱と同じ名前のルート保険フォルダ。保険の中を選んでいるときは None。"""
    root = Path(route_folder)
    if is_under_route_insurance(root) or is_under_route_insurance(root.parent):
        return None
    candidate = ROUTE_INSURANCE_ROOT / root.name
    if not candidate.is_dir():
        return None
    try:
        if candidate.resolve() == root.resolve():
            return None
    except OSError:
        return None
    return candidate


def publish_route_insurance(
    route_folder: Path,
    excel_path: Optional[Path] = None,
) -> Tuple[Optional[Path], str]:
    """Excel と空の仕入CSVだけをルート保険へ置く。画像はコピーしない。"""
    dest = ROUTE_INSURANCE_ROOT / Path(route_folder).name
    try:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / CSV_DIR_NAME).mkdir(exist_ok=True)
        src = Path(excel_path) if excel_path else None
        if src is not None and src.is_file():
            shutil.copy2(src, dest / src.name)
        return dest, ""
    except OSError as exc:
        return None, str(exc)


def _newer_file(primary: Optional[Path], extra: Optional[Path]) -> Optional[Path]:
    """更新が新しい方。同時刻なら primary（仕入帳側）を残す。"""
    if extra is None:
        return primary
    if primary is None:
        return extra
    try:
        if extra.stat().st_mtime > primary.stat().st_mtime:
            return extra
    except OSError:
        return primary
    return primary


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

    insurance = matching_insurance_dir(root)
    layout.csv_path = _newer_file(
        find_stocklist_csv(root),
        find_stocklist_csv(insurance) if insurance is not None else None,
    )
    if layout.csv_path is None:
        layout.notes.append("StockList CSV が見つかりません（仕入CSV/ または直下）")
    elif is_under_route_insurance(layout.csv_path):
        layout.notes.append("仕入CSVはルート保険から読みます")

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

    layout.route_template = _newer_file(
        find_route_template(root),
        find_route_template(insurance) if insurance is not None else None,
    )
    if layout.route_template is not None and is_under_route_insurance(layout.route_template):
        layout.notes.append("時刻の Excel はルート保険の新しいファイルを使います")
    rj = root / "route.json"
    if rj.is_file():
        layout.route_json = rj

    return layout


def route_json_is_usable(path: Path) -> bool:
    """route.json に、人が入れた時刻・メモ・高速代・仕入点数があるか。

    箱を作っただけの JSON（店名だけ）は False。そのときは Excel を開く。
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    if not isinstance(doc, dict):
        return False
    if _hhmm(doc.get("departure_time")) or _hhmm(doc.get("return_time")):
        return True
    if _fee(doc.get("toll_outbound")) or _fee(doc.get("toll_return")):
        return True
    for store in doc.get("stores") or []:
        if not isinstance(store, dict):
            continue
        if not str(store.get("store_code") or "").strip():
            continue
        if _hhmm(store.get("in_time")) or _hhmm(store.get("out_time")):
            return True
        if str(store.get("notes") or "").strip():
            return True
        count = store.get("purchase_item_count")
        if count not in (None, "", 0):
            return True
    return False


def choose_route_time_source(layout: RouteFolderLayout) -> str:
    """時刻の読み込み元。中身のある route.json を Excel より優先する。"""
    json_path = layout.route_json
    xlsx_path = layout.route_template
    json_file = json_path is not None and Path(json_path).is_file()
    xlsx_file = xlsx_path is not None and Path(xlsx_path).is_file()
    if json_file and route_json_is_usable(Path(json_path)):
        return "json"
    if xlsx_file:
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
