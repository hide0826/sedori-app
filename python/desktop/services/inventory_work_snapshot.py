#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入一覧の作業スナップショット（仕入データ／ネット仕入を別々に保存）。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_WORK_SNAPSHOTS = 40


def work_snapshot_root(root: Optional[Path] = None) -> Path:
    base = root or (Path(__file__).resolve().parents[1] / "data" / "inventory_work_snapshots")
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize_work_snapshot_mode(mode: str) -> str:
    return "online" if str(mode or "").strip() == "online" else "store"


def _mode_dir(mode: str, root: Optional[Path] = None) -> Path:
    path = work_snapshot_root(root) / normalize_work_snapshot_mode(mode)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path(mode: str, root: Optional[Path] = None) -> Path:
    return _mode_dir(mode, root) / "index.json"


def list_work_snapshots(mode: str, root: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = _index_path(mode, root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data if isinstance(data, list) else []
    return sorted(
        items,
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")),
        reverse=True,
    )


def _write_index(mode: str, items: List[Dict[str, Any]], root: Optional[Path] = None) -> None:
    path = _index_path(mode, root)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def save_work_snapshot(
    mode: str,
    name: str,
    records: List[Dict[str, Any]],
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """一覧を1件保存し、古いものから上限を超えた分を消す。"""
    now = datetime.now()
    snap_id = now.strftime("%Y%m%d_%H%M%S")
    folder = _mode_dir(mode, root)
    path = folder / f"{snap_id}.json"
    if path.exists():
        snap_id = now.strftime("%Y%m%d_%H%M%S_%f")
        path = folder / f"{snap_id}.json"
    label = str(name or "").strip() or now.strftime("%Y-%m-%d %H:%M")
    payload = {
        "id": snap_id,
        "name": label,
        "mode": normalize_work_snapshot_mode(mode),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "item_count": len(records),
        "records": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "id": snap_id,
        "name": label,
        "mode": payload["mode"],
        "created_at": payload["created_at"],
        "item_count": len(records),
    }
    items = [meta] + [row for row in list_work_snapshots(mode, root) if row.get("id") != snap_id]
    dropped = items[MAX_WORK_SNAPSHOTS:]
    items = items[:MAX_WORK_SNAPSHOTS]
    for old in dropped:
        old_id = str(old.get("id") or "")
        if old_id:
            (folder / f"{old_id}.json").unlink(missing_ok=True)
    _write_index(mode, items, root)
    return meta


def load_work_snapshot(mode: str, snapshot_id: str, root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = _mode_dir(mode, root) / f"{snapshot_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def delete_work_snapshot(mode: str, snapshot_id: str, root: Optional[Path] = None) -> None:
    folder = _mode_dir(mode, root)
    (folder / f"{snapshot_id}.json").unlink(missing_ok=True)
    items = [row for row in list_work_snapshots(mode, root) if str(row.get("id")) != str(snapshot_id)]
    _write_index(mode, items, root)
