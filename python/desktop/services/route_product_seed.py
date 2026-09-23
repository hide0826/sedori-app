# -*- coding: utf-8 -*-
"""確定済み商品画像の JAN を画像DBへ先に書き、次のスキャンでバーコードを読ませない。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PRODUCT_DIR_NAME = "商品画像"


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def confirmed_product_files(folder: Path) -> List[Tuple[Path, str]]:
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
    for store in doc.get("stores") or []:
        if not isinstance(store, dict):
            continue
        for item in store.get("product_files") or []:
            if not isinstance(item, dict) or not item.get("confirmed"):
                continue
            jan = _digits(item.get("jan"))
            name = str(item.get("file") or "").strip()
            if not jan.isdigit() or not name:
                continue
            found.append((product_dir / name, jan))
    return found


def seed_confirmed_jans(folder: Path, *, db: Any = None) -> int:
    pairs = confirmed_product_files(folder)
    if not pairs:
        return 0
    if db is None:
        from database.image_db import ImageDatabase

        db = ImageDatabase()
    count = 0
    for path, jan in pairs:
        if not path.is_file():
            continue
        db.upsert({"file_path": str(path), "jan": jan, "rotation": 0})
        count += 1
    return count


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
        result["seeded"] = seed_confirmed_jans(folder, db=db)
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
