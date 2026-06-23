#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入DBレコードからフリマ出品用の JAN・コンディション説明・画像パスを取り出す。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from PySide6.QtCore import Qt
except ImportError:
    Qt = None  # type: ignore


def normalize_jan(value: Any) -> str:
    """JAN列の値から8桁または13桁のコードを取り出す。"""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    s = re.sub(r"[^\d]", "", s)
    if len(s) in (8, 13):
        return s
    m = re.search(r"\b(\d{13}|\d{8})\b", str(value))
    return m.group(1) if m else ""


def extract_jan_from_record(record: Dict[str, Any]) -> str:
    for key in ("JAN", "jan", "JANコード", "jan_code"):
        jan = normalize_jan(record.get(key))
        if jan:
            return jan
    return ""


def extract_condition_note_from_record(record: Dict[str, Any]) -> str:
    """コンディション説明列のテキスト（コメント・テンプレート反映済みの説明文）。"""
    for key in (
        "コンディション説明",
        "condition_note",
        "condition_description",
        "conditionNote",
    ):
        v = record.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def extract_condition_label_from_record(record: Dict[str, Any]) -> str:
    for key in ("コンディション", "condition", "状態"):
        v = record.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _inventory_settings_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "inventory_settings.json"


def _image_search_roots(record: Dict[str, Any]) -> List[Path]:
    """ファイル名のみのときに探すディレクトリ候補。"""
    roots: List[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            resolved = str(p.resolve())
        except OSError:
            resolved = str(p)
        if resolved not in seen and p.exists() and p.is_dir():
            seen.add(resolved)
            roots.append(p)

    for i in range(1, 7):
        for key in (f"画像{i}", f"image_{i}"):
            v = record.get(key)
            if not v:
                continue
            p = Path(str(v).strip())
            if p.is_file():
                add(p.parent)
            elif p.parent and str(p.parent) not in (".", ""):
                add(p.parent)

    try:
        cfg_path = _inventory_settings_path()
        if cfg_path.is_file():
            with cfg_path.open(encoding="utf-8") as f:
                cfg = json.load(f)
            for key in ("image_manager_last_directory", "image_manager_default_root_dir"):
                d = (cfg.get(key) or "").strip()
                if d:
                    p = Path(d)
                    add(p)
                    if p.parent and p.parent.exists():
                        add(p.parent)
    except Exception:
        pass

    return roots


def _find_file_in_roots(basename: str, roots: List[Path], max_depth: int = 5) -> Optional[str]:
    """ルート配下を浅く探索してファイル名一致を探す。"""
    for root in roots:
        for sub in ("", "商品画像"):
            direct = (root / sub / basename) if sub else (root / basename)
            if direct.is_file():
                return str(direct.resolve())

        walk_root = root / "商品画像" if (root / "商品画像").is_dir() else root
        if not walk_root.is_dir():
            continue
        try:
            base_depth = len(walk_root.resolve().parts)
        except OSError:
            base_depth = len(walk_root.parts)
        for dirpath, dirnames, filenames in os.walk(walk_root):
            try:
                depth = len(Path(dirpath).resolve().parts) - base_depth
            except OSError:
                depth = len(Path(dirpath).parts) - base_depth
            if depth > max_depth:
                dirnames.clear()
                continue
            if basename in filenames:
                return str((Path(dirpath) / basename).resolve())

    # ファイル名先頭8桁が日付のとき、ルート直下のルートフォルダ名で絞る（例: 20240516-...）
    date_prefix = basename[:8] if len(basename) >= 8 and basename[:8].isdigit() else ""
    if date_prefix:
        for root in roots:
            if not root.is_dir():
                continue
            try:
                children = list(root.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_dir() and date_prefix in child.name:
                    found = _find_file_in_roots(basename, [child], max_depth=3)
                    if found:
                        return found
    return None


def resolve_local_image_path(raw: str, record: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """レコードの画像値（フルパス・相対パス・ファイル名）を実在ファイルパスに解決。"""
    s = (raw or "").strip()
    if not s:
        return None

    for candidate in (s, os.path.expanduser(s), os.path.normpath(s)):
        p = Path(candidate)
        if p.is_file():
            return str(p.resolve())

    name = Path(s).name
    if not name:
        return None

    rec = record if record is not None else {}
    roots = _image_search_roots(rec)
    return _find_file_in_roots(name, roots)


def _image_keys_for_slot(i: int) -> Sequence[str]:
    return (f"画像{i}", f"image_{i}")


def merge_record_image_paths_from_product_db(record: Dict[str, Any]) -> Dict[str, Any]:
    """SKU から商品DBの image_1〜6 をレコードへ補完し、可能ならフルパスに解決。"""
    sku = (record.get("SKU") or record.get("sku") or "").strip()
    if not sku:
        return record
    try:
        from database.product_db import ProductDatabase
    except ImportError:
        try:
            from desktop.database.product_db import ProductDatabase
        except ImportError:
            return record
    try:
        product = ProductDatabase().get_by_sku(sku)
    except Exception:
        return record
    if not product:
        return record
    for i in range(1, 7):
        col_key = f"画像{i}"
        prod_key = f"image_{i}"
        db_path = (product.get(prod_key) or "").strip()
        current = (record.get(col_key) or record.get(prod_key) or "").strip()
        candidate = db_path or current
        if not candidate:
            continue
        resolved = resolve_local_image_path(candidate, record)
        if resolved:
            record[col_key] = resolved
            record[prod_key] = resolved
        elif db_path:
            record[col_key] = db_path
    return record


def resolve_record_product_images(record: Dict[str, Any]) -> Dict[str, Any]:
    """仕入レコードの画像1〜6を、可能な限り実在するフルパスへ揃える。"""
    merge_record_image_paths_from_product_db(record)
    for i in range(1, 7):
        for key in _image_keys_for_slot(i):
            raw = (record.get(key) or "").strip()
            if not raw:
                continue
            resolved = resolve_local_image_path(raw, record)
            if resolved:
                record[key] = resolved
                if key.startswith("画像"):
                    record[f"image_{key[2:]}"] = resolved
            break
    return record


def _find_purchase_table_row_index(
    product_widget: Any,
    sku: str,
    *,
    row_id: Any = None,
) -> Optional[int]:
    """仕入DBテーブルで SKU（または _row_id）に一致する行番号を返す。"""
    if product_widget is None or Qt is None:
        return None
    sku_key = (sku or "").strip()
    table = getattr(product_widget, "purchase_table", None)
    columns: List[str] = list(getattr(product_widget, "purchase_columns", None) or [])
    if table is None or table.rowCount() == 0 or not columns:
        return None

    def _row_matches(row: int) -> bool:
        if row_id is not None:
            for c in range(table.columnCount()):
                it = table.item(row, c)
                if it is None:
                    continue
                rid = it.data(Qt.UserRole + 1)
                try:
                    if int(rid) == int(row_id):
                        return True
                except (TypeError, ValueError):
                    continue
        if sku_key:
            for c, hdr in enumerate(columns):
                if hdr.upper() != "SKU":
                    continue
                it = table.item(row, c)
                if it is None:
                    continue
                cell_sku = it.data(Qt.UserRole)
                if cell_sku is not None and str(cell_sku).strip():
                    text = str(cell_sku).strip()
                else:
                    text = (it.text() or "").strip()
                if text == sku_key:
                    return True
        return False

    for row in range(table.rowCount()):
        if _row_matches(row):
            return row
    return None


_PURCHASE_TABLE_FILE_PATH_HEADERS = frozenset({
    "レシート画像", "保証書画像",
    "画像1", "画像2", "画像3", "画像4", "画像5", "画像6",
})
_PURCHASE_TABLE_URL_HEADERS = frozenset({
    "レシート画像URL",
    "画像URL1", "画像URL2", "画像URL3", "画像URL4", "画像URL5", "画像URL6",
})


def _purchase_table_cell_value(header: str, item: Any) -> str:
    """仕入DBテーブルセルから UserRole 優先で値を取り出す。"""
    if item is None:
        return ""
    if header == "SKU":
        full = item.data(Qt.UserRole)
        if full is not None and str(full).strip():
            return str(full).strip()
        return (item.text() or "").strip()
    if header == "商品名":
        full = item.data(Qt.UserRole)
        if full is not None and str(full).strip():
            return str(full).strip()
        return (item.text() or "").strip()
    if header in _PURCHASE_TABLE_FILE_PATH_HEADERS or header in _PURCHASE_TABLE_URL_HEADERS:
        full = item.data(Qt.UserRole)
        if full is not None and str(full).strip():
            return str(full).strip()
    return (item.text() or "").strip()


def extract_purchase_record_from_purchase_table(
    product_widget: Any,
    sku: str,
) -> Optional[Dict[str, Any]]:
    """
    仕入DBテーブルの該当 SKU 行から全列を取り出す（UserRole のフルパスを優先）。
    ソート後でも SKU 列の UserRole で正確に行を特定する。
    """
    if product_widget is None or Qt is None:
        return None
    sku_key = (sku or "").strip()
    if not sku_key:
        return None
    table = getattr(product_widget, "purchase_table", None)
    columns: List[str] = list(getattr(product_widget, "purchase_columns", None) or [])
    if table is None or not columns:
        return None

    row_index = _find_purchase_table_row_index(product_widget, sku_key)
    if row_index is None:
        return None

    row_id: Optional[int] = None
    for c in range(table.columnCount()):
        it = table.item(row_index, c)
        if it is None:
            continue
        rid = it.data(Qt.UserRole + 1)
        if rid is None:
            continue
        try:
            row_id = int(rid)
            break
        except (TypeError, ValueError):
            continue

    base: Dict[str, Any] = {}
    row_map = getattr(product_widget, "_purchase_row_map", None) or {}
    if row_id is not None and row_id in row_map:
        base = dict(row_map[row_id])

    record: Dict[str, Any] = dict(base)
    for col, header in enumerate(columns):
        if not header or header == "経過日数":
            continue
        item = table.item(row_index, col)
        value = _purchase_table_cell_value(header, item)
        if value or header not in record:
            record[header] = value

    record["SKU"] = sku_key
    record["sku"] = sku_key
    return record


def resolve_record_product_images_preserve_sources(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    レコード内の画像1〜6のみをフルパスへ解決する（商品DBで上書きしない）。
    仕入DB行・テーブル由来の画像を他SKUの商品DB画像で置き換えないために使う。
    """
    for i in range(1, 7):
        for key in _image_keys_for_slot(i):
            raw = (record.get(key) or "").strip()
            if not raw:
                continue
            resolved = resolve_local_image_path(raw, record)
            if resolved:
                record[f"画像{i}"] = resolved
                record[f"image_{i}"] = resolved
            break
    return record


def merge_record_image_paths_from_purchase_table(
    record: Dict[str, Any],
    product_widget: Any,
) -> Dict[str, Any]:
    """仕入DBテーブルセルの UserRole（フルパス）をレコードへ反映。"""
    if product_widget is None or Qt is None:
        return record
    table = getattr(product_widget, "purchase_table", None)
    columns: List[str] = list(getattr(product_widget, "purchase_columns", None) or [])
    if table is None or not columns:
        return record

    sku = (record.get("SKU") or record.get("sku") or "").strip()
    target_row_id = record.get("_row_id")
    row_index = _find_purchase_table_row_index(
        product_widget, sku, row_id=target_row_id
    )
    if row_index is None:
        return record

    for col, header in enumerate(columns):
        if not (header.startswith("画像") and header[2:].isdigit()):
            continue
        it = table.item(row_index, col)
        if it is None:
            continue
        path = it.data(Qt.UserRole)
        if path and str(path).strip():
            record[header] = str(path).strip()
            record[f"image_{header[2:]}"] = str(path).strip()

    return record


def prepare_record_for_flea_images(
    record: Dict[str, Any],
    product_widget: Any = None,
) -> Dict[str, Any]:
    """フリマ出品ダイアログ用に画像パスをレコードへ揃える。"""
    rec = dict(record) if record else {}
    resolve_record_product_images(rec)
    if product_widget is not None:
        merge_record_image_paths_from_purchase_table(rec, product_widget)
        resolve_record_product_images(rec)
    return rec


def collect_product_image_paths(record: Dict[str, Any]) -> List[str]:
    """画像1〜6のローカルファイルパス（存在するもののみ、順序維持）。"""
    paths: List[str] = []
    seen: set[str] = set()
    for i in range(1, 7):
        raw: Optional[str] = None
        for key in _image_keys_for_slot(i):
            v = record.get(key)
            if v is not None and str(v).strip():
                raw = str(v).strip()
                break
        if not raw:
            continue
        resolved = resolve_local_image_path(raw, record)
        if not resolved:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        paths.append(resolved)
    return paths


def build_product_description_block(
    body: str,
    jan: str,
    condition_note: str,
) -> str:
    """
    商品説明欄用: 本文 + JANコード行 + コンディション説明（あれば）。
    """
    parts: List[str] = []
    if body and body.strip():
        parts.append(body.strip())
    if jan:
        parts.append(f"JANコード: {jan}")
    if condition_note and condition_note.strip():
        if parts:
            parts.append("")
        parts.append("【コンディション・状態】")
        parts.append(condition_note.strip())
    return "\n".join(parts).strip()
