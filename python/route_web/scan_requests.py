# -*- coding: utf-8 -*-
"""商品スキャン依頼。ルートWebとデスクトップは別プロセスなのでファイルで渡す。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from route_web.registry import DATA_DIR

try:
    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # pragma: no cover
    JST = timezone(timedelta(hours=9))

PENDING_NAME = "pending_scans.json"


def pending_scans_path(path: Optional[Path] = None) -> Path:
    return Path(path) if path is not None else DATA_DIR / PENDING_NAME


def _read(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("requests") or []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"requests": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def enqueue_scan(web_id: str, folder: Path, *, path: Optional[Path] = None) -> Dict[str, Any]:
    dest = pending_scans_path(path)
    rows = _read(dest)
    item = {
        "web_id": web_id,
        "folder": str(Path(folder)),
        "requested_at": datetime.now(JST).isoformat(timespec="seconds"),
    }
    rows.append(item)
    _write(dest, rows)
    return item


def peek_scans(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    return _read(pending_scans_path(path))


def remove_scan(folder: str, *, path: Optional[Path] = None) -> None:
    dest = pending_scans_path(path)
    rows = [row for row in _read(dest) if str(row.get("folder") or "") != str(folder)]
    _write(dest, rows)
