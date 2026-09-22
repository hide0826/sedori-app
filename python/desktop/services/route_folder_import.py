# -*- coding: utf-8 -*-
"""ルート箱から仕入／画像／証憑へ振り分ける（Phase 3）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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
