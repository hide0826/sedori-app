# -*- coding: utf-8 -*-
"""仕入CSV 受信箱 → ルート箱（Phase 2）。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

CSV_DIR_NAME = "仕入CSV"
INBOX_DIR_NAME = "仕入CSV_受信"
LEDGER_PARENT = Path(r"D:\せどり総合\店舗せどり仕入リスト入れ")


def inbox_dir() -> Path:
    """固定受信箱。無ければ作成する。"""
    d = LEDGER_PARENT / INBOX_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def csv_dir(folder: Path) -> Path:
    d = folder / CSV_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(name: str) -> str:
    base = Path(name or "").name
    base = re.sub(r'[\\/:*?"<>|]+', "_", base).strip()
    if not base.lower().endswith(".csv"):
        base = f"{base}.csv" if base else "upload.csv"
    return base or "upload.csv"


def list_inbox_files() -> List[Dict[str, Any]]:
    root = inbox_dir()
    rows: List[Dict[str, Any]] = []
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".csv":
            continue
        st = p.stat()
        rows.append(
            {
                "filename": p.name,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
        )
    return rows


def list_route_csv_files(folder: Path) -> List[Dict[str, Any]]:
    dest = csv_dir(folder)
    rows: List[Dict[str, Any]] = []
    for p in sorted(dest.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file() or p.suffix.lower() != ".csv":
            continue
        st = p.stat()
        rows.append(
            {
                "filename": p.name,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
        )
    return rows


def _unique_dest(dest_dir: Path, filename: str) -> Path:
    target = dest_dir / filename
    if not target.exists():
        return target
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    n = 2
    while True:
        candidate = dest_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def move_from_inbox(folder: Path, filename: str) -> str:
    """受信箱の CSV をルート箱 仕入CSV/ へ移動。失敗時はコピーして元を残す。"""
    name = Path(filename).name
    src = inbox_dir() / name
    if not src.is_file():
        raise FileNotFoundError(f"inbox file not found: {name}")
    dest = _unique_dest(csv_dir(folder), name)
    try:
        shutil.move(str(src), str(dest))
    except OSError:
        shutil.copy2(str(src), str(dest))
        try:
            src.unlink()
        except OSError:
            pass
    return dest.name


def save_csv_upload(folder: Path, raw: bytes, original_name: str = "") -> str:
    if not raw:
        raise ValueError("empty upload")
    name = _safe_filename(original_name or "StockList_upload.csv")
    dest = _unique_dest(csv_dir(folder), name)
    dest.write_bytes(raw)
    return dest.name


def append_csv_file(doc: Dict[str, Any], filename: str) -> Dict[str, Any]:
    files = list(doc.get("csv_files") or [])
    if filename not in files:
        files.append(filename)
    out = dict(doc)
    out["csv_files"] = files
    return out


def find_stocklist_csv(route_folder: Path) -> Optional[Path]:
    """仕入CSV/ 優先、無ければルート箱直下の StockList_*.csv。"""
    sub = route_folder / CSV_DIR_NAME
    candidates: List[Path] = []
    if sub.is_dir():
        candidates.extend(sub.glob("StockList_*.csv"))
        if not candidates:
            candidates.extend(p for p in sub.glob("*.csv") if p.is_file())
    if not candidates:
        candidates.extend(route_folder.glob("StockList_*.csv"))
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except OSError:
        return candidates[0]
