# -*- coding: utf-8 -*-
"""ネット仕入用の日付箱（仕入CSV / 商品画像 / 証憑スクショ）を作る。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

CSV_DIR_NAME = "仕入CSV"
PRODUCT_DIR_NAME = "商品画像"
EVIDENCE_DIR_NAME = "証憑スクショ"
PHOTO_CANDIDATES_FILE = "photo_candidates.json"
ONLINE_ROUTE_CODE = "NET"
ONLINE_BOX_KIND = "online"

ONLINE_BOX_SUBDIRS: Sequence[str] = (
    CSV_DIR_NAME,
    PRODUCT_DIR_NAME,
    EVIDENCE_DIR_NAME,
)

# ユーザー環境の実フォルダ名は「ネット仕入れリスト」（「れ」あり）。
# 表記ゆれにも対応する。
DEFAULT_ONLINE_ROOT_CANDIDATES: Sequence[Path] = (
    Path(r"D:\せどり総合\ネット仕入れリスト"),
    Path(r"D:\せどり総合\ネット仕入リスト"),
)

_UNSAFE_FOLDER_CHARS = '\\/:*?"<>|'


@dataclass(frozen=True)
class OnlineBoxResult:
    box_dir: Path
    evidence_dir: Path
    csv_dir: Path
    product_dir: Path
    created_box: bool
    created_subdirs: List[str]
    web_id: str = ""
    route_json: Optional[Path] = None


def sanitize_folder_label(label: str) -> str:
    """フォルダ名に使えない文字を _ に置換する。"""
    text = (label or "").strip() or "フリマ"
    return "".join("_" if ch in _UNSAFE_FOLDER_CHARS else ch for ch in text)


def format_box_date(value: Optional[Union[date, datetime, str]] = None) -> str:
    """箱名用の YYYYMMDD を返す。"""
    if value is None:
        return date.today().strftime("%Y%m%d")
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return date.today().strftime("%Y%m%d")


def box_date_iso(value: Optional[Union[date, datetime, str]] = None) -> str:
    """YYYY-MM-DD。"""
    ymd = format_box_date(value)
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def build_online_box_name(
    label: str = "フリマ",
    box_date: Optional[Union[date, datetime, str]] = None,
) -> str:
    """例: フリマ20261001"""
    return f"{sanitize_folder_label(label)}{format_box_date(box_date)}"


def resolve_default_online_root(
    candidates: Optional[Iterable[Path]] = None,
) -> Optional[Path]:
    """存在するデフォルト親フォルダを返す。無ければ None。"""
    for path in candidates or DEFAULT_ONLINE_ROOT_CANDIDATES:
        try:
            if Path(path).is_dir():
                return Path(path)
        except OSError:
            continue
    return None


def _ensure_route_web_importable() -> None:
    """desktop/services から route_web を import できるようにする。"""
    desktop_dir = Path(__file__).resolve().parents[1]
    python_dir = desktop_dir.parent
    for path in (str(python_dir), str(desktop_dir)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


def create_online_purchase_box(
    base_dir: Union[str, Path],
    *,
    label: str = "フリマ",
    box_date: Optional[Union[date, datetime, str]] = None,
    box_name: Optional[str] = None,
    register_web: bool = True,
) -> OnlineBoxResult:
    """
    親フォルダ配下に日付箱とサブフォルダを作る。

    既にあっても不足サブだけ追加する（exist_ok）。
    register_web=True のとき route.json を書き route_web に登録する。
    """
    root = Path(base_dir)
    if not str(root).strip():
        raise ValueError("親フォルダが空です")

    if box_name and str(box_name).strip():
        name = "".join(
            "_" if ch in _UNSAFE_FOLDER_CHARS else ch for ch in str(box_name).strip()
        )
        if not name:
            name = build_online_box_name(label=label, box_date=box_date)
    else:
        name = build_online_box_name(label=label, box_date=box_date)

    box_dir = root / name
    created_box = not box_dir.exists()
    box_dir.mkdir(parents=True, exist_ok=True)

    created_subdirs: List[str] = []
    sub_paths = {}
    for sub in ONLINE_BOX_SUBDIRS:
        sub_dir = box_dir / sub
        if not sub_dir.exists():
            created_subdirs.append(sub)
        sub_dir.mkdir(exist_ok=True)
        sub_paths[sub] = sub_dir

    web_id = ""
    route_json: Optional[Path] = None
    if register_web:
        web_id, route_json = ensure_online_route_registration(
            box_dir,
            box_date=box_date or format_box_date(name[-8:] if len(name) >= 8 else None),
            route_name=name,
        )

    return OnlineBoxResult(
        box_dir=box_dir,
        evidence_dir=sub_paths[EVIDENCE_DIR_NAME],
        csv_dir=sub_paths[CSV_DIR_NAME],
        product_dir=sub_paths[PRODUCT_DIR_NAME],
        created_box=created_box,
        created_subdirs=created_subdirs,
        web_id=web_id,
        route_json=route_json,
    )


def ensure_online_route_registration(
    box_dir: Union[str, Path],
    *,
    box_date: Optional[Union[date, datetime, str]] = None,
    route_name: Optional[str] = None,
) -> tuple[str, Path]:
    """ネット箱に route.json を書き、route_web の index に登録する。"""
    _ensure_route_web_importable()
    from route_web.registry import make_web_id, register_route, route_json_path
    from route_web.schema import build_route_document, stamp_updated

    folder = Path(box_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = route_name or folder.name
    ymd = format_box_date(box_date)
    if box_date is None:
        # 箱名末尾の YYYYMMDD を優先
        digits = "".join(ch for ch in name if ch.isdigit())
        if len(digits) >= 8:
            ymd = digits[-8:]
    iso = box_date_iso(ymd)
    web_id = make_web_id(ymd, name)

    existing: Dict[str, Any] = {}
    path = route_json_path(folder)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except (OSError, json.JSONDecodeError):
            existing = {}

    doc = build_route_document(
        web_id=web_id,
        folder_path=str(folder),
        route_date=iso,
        route_code=ONLINE_ROUTE_CODE,
        route_name=name,
        stores=[],
        notes=str(existing.get("notes") or ""),
        box_kind=ONLINE_BOX_KIND,
    )
    if isinstance(existing.get("product_files"), list):
        doc["product_files"] = existing["product_files"]
    if isinstance(existing.get("no_image_products"), list):
        doc["no_image_products"] = existing["no_image_products"]
    if isinstance(existing.get("photo_candidates"), list):
        doc["photo_candidates"] = existing["photo_candidates"]
    doc = stamp_updated(doc)

    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    register_route(web_id, str(folder), route_name=name, route_date=iso)
    return web_id, path


def _cell(record: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    return ""


def build_photo_candidate_rows(
    records: Iterable[Dict[str, Any]],
    *,
    route_date: str = "",
    route_name: str = "",
    route_code: str = ONLINE_ROUTE_CODE,
) -> List[Dict[str, Any]]:
    """仕入一覧行から撮影候補を作る。"""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        sku = _cell(record, "SKU", "sku")
        jan = "".join(ch for ch in _cell(record, "JAN", "jan") if ch.isdigit())
        asin = "".join(
            ch for ch in _cell(record, "ASIN", "asin").upper() if ch.isalnum()
        )[:16]
        name = _cell(record, "商品名", "product_name", "title")
        if not (sku or jan or asin or name):
            continue
        key = (sku, jan, asin, name)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "sku": sku,
                "jan": jan,
                "asin": asin,
                "product_name": name,
                "store_code": ONLINE_ROUTE_CODE,
                "store_name": "ネット仕入",
                "purchase_date": route_date or _cell(record, "仕入れ日", "purchase_date"),
                "route_name": route_name,
                "route_code": route_code,
                "route_date": route_date,
            }
        )
    return rows


def write_photo_candidates(
    box_dir: Union[str, Path],
    records: Iterable[Dict[str, Any]],
    *,
    route_date: str = "",
    route_name: str = "",
) -> tuple[Path, List[Dict[str, Any]]]:
    """撮影候補を photo_candidates.json と route.json に書く。"""
    folder = Path(box_dir)
    name = route_name or folder.name
    iso = route_date or box_date_iso(name[-8:] if len(name) >= 8 else None)
    rows = build_photo_candidate_rows(
        records,
        route_date=iso,
        route_name=name,
        route_code=ONLINE_ROUTE_CODE,
    )
    payload = {
        "box_kind": ONLINE_BOX_KIND,
        "route_date": iso,
        "route_name": name,
        "candidates": rows,
    }
    candidates_path = folder / PHOTO_CANDIDATES_FILE
    candidates_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    route_path = folder / "route.json"
    if route_path.is_file():
        try:
            doc = json.loads(route_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = {}
        if isinstance(doc, dict):
            doc["photo_candidates"] = rows
            doc["box_kind"] = ONLINE_BOX_KIND
            route_path.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return candidates_path, rows


def load_photo_candidates(
    box_dir: Optional[Union[str, Path]] = None,
    doc: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """route.json または photo_candidates.json から候補を読む。"""
    if isinstance(doc, dict):
        embedded = doc.get("photo_candidates")
        if isinstance(embedded, list) and embedded:
            return [row for row in embedded if isinstance(row, dict)]

    folder: Optional[Path] = None
    if box_dir is not None:
        folder = Path(box_dir)
    elif isinstance(doc, dict) and doc.get("folder_path"):
        folder = Path(str(doc.get("folder_path")))
    if folder is None or not folder.is_dir():
        return []

    path = folder / PHOTO_CANDIDATES_FILE
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        rows = raw.get("candidates")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def is_online_box_doc(doc: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(doc, dict):
        return False
    kind = str(doc.get("box_kind") or "").strip().lower()
    if kind == ONLINE_BOX_KIND:
        return True
    return str(doc.get("route_code") or "").strip().upper() == ONLINE_ROUTE_CODE


def looks_like_online_box_dir(path: Path) -> bool:
    """ネット仕入の日付箱っぽいか。"""
    if not path.is_dir():
        return False
    name = path.name.strip()
    if not name or name.startswith("."):
        return False
    if (path / "route.json").is_file():
        return True
    if (path / PRODUCT_DIR_NAME).is_dir() or (path / CSV_DIR_NAME).is_dir():
        return True
    if (path / EVIDENCE_DIR_NAME).is_dir():
        return True
    # フリマ20261001 のような日付入り名
    digits = "".join(ch for ch in name if ch.isdigit())
    return len(digits) >= 8


def sync_online_boxes_into_registry(
    root: Optional[Union[str, Path]] = None,
) -> List[str]:
    """
    ネット仕入れリスト配下の箱を route.json 付きで Web 一覧に載せる。
    戻り値は登録した web_id のリスト。
    """
    base = Path(root) if root else resolve_default_online_root()
    if base is None or not Path(base).is_dir():
        return []

    registered: List[str] = []
    for child in sorted(Path(base).iterdir(), key=lambda p: p.name, reverse=True):
        if not looks_like_online_box_dir(child):
            continue
        # サブフォルダが無ければ揃える（既存フリマ箱向け）
        for sub in ONLINE_BOX_SUBDIRS:
            (child / sub).mkdir(exist_ok=True)
        try:
            web_id, _ = ensure_online_route_registration(child, route_name=child.name)
        except Exception:
            continue
        if web_id:
            registered.append(web_id)
    return registered
