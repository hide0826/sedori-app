# -*- coding: utf-8 -*-
"""web_id ↔ ルートフォルダの対応表。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
INDEX_PATH = DATA_DIR / "index.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_index() -> Dict[str, Any]:
    _ensure_data_dir()
    if not INDEX_PATH.is_file():
        return {"routes": {}}
    try:
        raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"routes": {}}
    if not isinstance(raw, dict):
        return {"routes": {}}
    routes = raw.get("routes")
    if not isinstance(routes, dict):
        raw["routes"] = {}
    return raw


def save_index(data: Dict[str, Any]) -> None:
    _ensure_data_dir()
    INDEX_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def register_route(
    web_id: str,
    folder_path: str,
    route_name: str = "",
    route_date: str = "",
) -> None:
    data = load_index()
    data.setdefault("routes", {})[web_id] = {
        "folder_path": str(folder_path),
        "route_name": route_name or "",
        "route_date": route_date or "",
    }
    save_index(data)


def list_route_summaries() -> List[Dict[str, Any]]:
    """一覧用。新しい日付が上。route.json があればそちらを優先。"""
    data = load_index()
    rows: List[Dict[str, Any]] = []
    for web_id, entry in (data.get("routes") or {}).items():
        if not isinstance(entry, dict):
            continue
        folder = Path(str(entry.get("folder_path") or ""))
        route_date = str(entry.get("route_date") or "")
        route_name = str(entry.get("route_name") or "")
        route_code = ""
        updated_at = ""
        available = False
        if folder.is_dir():
            path = route_json_path(folder)
            if path.is_file():
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    doc = None
                if isinstance(doc, dict):
                    available = True
                    route_date = str(doc.get("route_date") or route_date)
                    route_name = str(doc.get("route_name") or route_name)
                    route_code = str(doc.get("route_code") or "")
                    updated_at = str(doc.get("updated_at") or "")
        rows.append(
            {
                "web_id": web_id,
                "route_date": route_date,
                "route_name": route_name,
                "route_code": route_code,
                "updated_at": updated_at,
                "available": available,
                "folder_path": str(folder),
            }
        )
    rows.sort(
        key=lambda r: (r.get("route_date") or "", r.get("web_id") or ""),
        reverse=True,
    )
    return rows


def resolve_folder(web_id: str) -> Optional[Path]:
    data = load_index()
    entry = (data.get("routes") or {}).get(web_id)
    if not entry:
        return None
    folder = Path(str(entry.get("folder_path") or ""))
    if not folder.is_dir():
        return None
    return folder


def route_json_path(folder: Path) -> Path:
    return folder / "route.json"


def load_route_json(web_id: str) -> Optional[Dict[str, Any]]:
    folder = resolve_folder(web_id)
    if folder is None:
        return None
    path = route_json_path(folder)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def save_route_json(web_id: str, payload: Dict[str, Any]) -> Path:
    folder = resolve_folder(web_id)
    if folder is None:
        raise FileNotFoundError(f"unknown web_id: {web_id}")
    path = route_json_path(folder)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def make_web_id(route_date_ymd: str, route_name: str) -> str:
    """YYYYMMDD + 安全化したルート名。"""
    unsafe = '\\/:*?"<>|'
    safe = "".join("_" if ch in unsafe else ch for ch in (route_name or "").strip())
    safe = re.sub(r"\s+", "_", safe)
    safe = re.sub(r"[^\w\-一-龥ぁ-んァ-ン]", "_", safe, flags=re.UNICODE)
    safe = safe.strip("_") or "route"
    return f"{route_date_ymd}_{safe}"
