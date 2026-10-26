# -*- coding: utf-8 -*-
"""とりあえず中古画像を残す（ルート／商品紐付けなし）。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from route_web.product_images import IMAGE_SUFFIXES, _to_jpeg_bytes

# USB SSD 上の仮置き場。あとでルート箱や出品用に振り分ける。
QUICK_PHOTOS_ROOT = Path(r"D:\せどり総合\中古画像一時")
MAX_LIST = 40


def ensure_root() -> Path:
    QUICK_PHOTOS_ROOT.mkdir(parents=True, exist_ok=True)
    return QUICK_PHOTOS_ROOT


def _today_dir() -> Path:
    day = datetime.now().strftime("%Y-%m-%d")
    dest = ensure_root() / day
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _safe_note(note: str) -> str:
    """ファイル名に使える短いメモ（空なら空文字）。"""
    text = (note or "").strip()
    text = re.sub(r"[\\/:*?\"<>|\s]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text[:40]


def save_quick_upload(raw: bytes, original_name: str = "", note: str = "") -> Dict[str, Any]:
    if not raw:
        raise ValueError("empty upload")

    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:6]
    memo = _safe_note(note)
    base = f"{stamp}-{short}"
    if memo:
        base = f"{stamp}-{memo}-{short}"

    suffix = Path(original_name or "").suffix.lower()
    data = raw
    filename = f"{base}.jpg"
    if suffix in IMAGE_SUFFIXES or not suffix:
        data = _to_jpeg_bytes(raw)
    elif suffix:
        # 変換できない形式はそのまま拡張子を残す
        filename = f"{base}{suffix}"

    dest = _today_dir() / filename
    dest.write_bytes(data)
    rel = f"{dest.parent.name}/{dest.name}"
    return {
        "filename": dest.name,
        "relative_path": rel,
        "saved_at": now.isoformat(timespec="seconds"),
        "bytes": len(data),
        "folder": str(dest.parent),
    }


def list_recent(limit: int = MAX_LIST) -> List[Dict[str, Any]]:
    root = ensure_root()
    files: List[Path] = []
    if root.is_dir():
        for day_dir in root.iterdir():
            if not day_dir.is_dir():
                continue
            for p in day_dir.iterdir():
                if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES | {".jpg", ".jpeg"}:
                    files.append(p)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Dict[str, Any]] = []
    for p in files[: max(1, min(limit, 100))]:
        st = p.stat()
        out.append(
            {
                "filename": p.name,
                "relative_path": f"{p.parent.name}/{p.name}",
                "saved_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "bytes": st.st_size,
            }
        )
    return out
