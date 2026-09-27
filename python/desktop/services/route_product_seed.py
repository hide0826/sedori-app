# -*- coding: utf-8 -*-
"""確定済み商品画像の JAN を画像DBへ先に書き、次のスキャンでバーコードを読ませない。"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PRODUCT_DIR_NAME = "商品画像"


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _product_files(folder: Path, *, confirmed_only: bool) -> List[Tuple[Path, str]]:
    route_json = Path(folder) / "route.json"
    if not route_json.is_file():
        return []
    try:
        doc = json.loads(route_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(doc, dict):
        return []
    found: List[Tuple[Path, str]] = []
    product_dir = Path(folder) / PRODUCT_DIR_NAME

    def take(items: Any) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            if confirmed_only and not item.get("confirmed"):
                continue
            jan = _digits(item.get("jan"))
            name = str(item.get("file") or "").strip()
            if not jan.isdigit() or not name:
                continue
            found.append((product_dir / name, jan))

    take(doc.get("product_files"))
    for store in doc.get("stores") or []:
        if isinstance(store, dict):
            take(store.get("product_files"))
    return found


def confirmed_product_files(folder: Path) -> List[Tuple[Path, str]]:
    return _product_files(folder, confirmed_only=True)


def linked_product_files(folder: Path) -> List[Tuple[Path, str]]:
    """JANが付いている商品画像。撮影終了前も含む。"""
    return _product_files(folder, confirmed_only=False)


def seed_product_jan(path: Path, jan: str, *, db: Any = None) -> bool:
    """1枚を画像DBへ書く。スキャンはこのJANを使い、バーコードを読み直さない。"""
    jan_s = _digits(jan)
    image = Path(path)
    if not jan_s.isdigit() or not image.is_file():
        return False
    own = db is None
    if own:
        from database.image_db import ImageDatabase

        db = ImageDatabase()
    try:
        last_error: Optional[BaseException] = None
        for _attempt in range(6):
            try:
                db.upsert({"file_path": str(image), "jan": jan_s, "rotation": 0})
                return True
            except sqlite3.OperationalError as exc:
                last_error = exc
                time.sleep(0.4)
        if last_error is not None:
            raise last_error
        return False
    finally:
        if own:
            db.close()


def _seed_pairs(pairs: List[Tuple[Path, str]], *, db: Any = None) -> int:
    if not pairs:
        return 0
    own = db is None
    if own:
        from database.image_db import ImageDatabase

        db = ImageDatabase()
    count = 0
    try:
        for path, jan in pairs:
            if seed_product_jan(path, jan, db=db):
                count += 1
    finally:
        if own:
            db.close()
    return count


def seed_confirmed_jans(folder: Path, *, db: Any = None) -> int:
    return _seed_pairs(confirmed_product_files(folder), db=db)


def seed_linked_jans(folder: Path, *, db: Any = None) -> int:
    """撮影済みでJANがある画像を、撮影終了前でも画像DBへ書く。"""
    return _seed_pairs(linked_product_files(folder), db=db)


def consume_one_scan_request(
    image_widget: Any = None,
    *,
    pending_path: Optional[Path] = None,
    db: Any = None,
) -> Optional[Dict[str, Any]]:
    """依頼が1件あれば JAN を種まきし、画像管理が来ていればスキャンする。"""
    from route_web.scan_requests import peek_scans, remove_scan

    rows = peek_scans(pending_path)
    if not rows:
        return None
    item = rows[0]
    folder = Path(str(item.get("folder") or ""))
    result: Dict[str, Any] = {
        "web_id": item.get("web_id"),
        "folder": str(folder),
        "seeded": 0,
        "scanned": False,
        "error": "",
    }
    try:
        result["seeded"] = seed_linked_jans(folder, db=db)
        product_dir = folder / PRODUCT_DIR_NAME
        if image_widget is not None and product_dir.is_dir() and hasattr(image_widget, "set_directory"):
            image_widget.set_directory(str(product_dir), scan=True)
            result["scanned"] = True
        elif image_widget is None:
            result["error"] = "画像管理がまだ開いていません"
            return result
    except Exception as exc:
        result["error"] = str(exc)
    result_path = folder / "scan_result.json"
    try:
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    remove_scan(str(folder), path=pending_path)
    return result
