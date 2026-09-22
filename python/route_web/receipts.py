# -*- coding: utf-8 -*-
"""レシート画像の保存（Phase 1.5）。"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

RECEIPT_DIR_NAME = "レシート画像"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp"}


def receipt_dir(folder: Path) -> Path:
    d = folder / RECEIPT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_store_code(store_code: str) -> str:
    code = (store_code or "").strip().upper()
    code = re.sub(r"[^A-Z0-9\-]", "", code)
    return code or "XX-00"


def next_receipt_filename(folder: Path, route_date: str, store_code: str) -> str:
    """YYYY-MM-DD-STORE-NN.jpg の次の連番。"""
    date = (route_date or "").strip() or "0000-00-00"
    code = _safe_store_code(store_code)
    dest = receipt_dir(folder)
    pattern = re.compile(
        rf"^{re.escape(date)}-(?:war-)?{re.escape(code)}-(\d+)\.",
        re.IGNORECASE,
    )
    max_n = 0
    for p in dest.iterdir():
        if not p.is_file():
            continue
        m = pattern.match(p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{date}-{code}-{max_n + 1:02d}.jpg"


def _to_jpeg_bytes(raw: bytes, max_side: int = 1920) -> bytes:
    """可能なら JPEG に直し、長辺を縮小。失敗時は元バイトを返す。"""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return raw

    try:
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except Exception:
            pass
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")
        w, h = img.size
        long_side = max(w, h)
        if long_side > max_side:
            scale = max_side / float(long_side)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue()
    except Exception:
        return raw


def save_receipt_upload(
    folder: Path,
    route_date: str,
    store_code: str,
    raw: bytes,
    original_name: str = "",
) -> str:
    """画像を保存し、ファイル名を返す。"""
    if not raw:
        raise ValueError("empty upload")
    filename = next_receipt_filename(folder, route_date, store_code)
    # 拡張子ヒント
    suffix = Path(original_name or "").suffix.lower()
    data = raw
    if suffix in IMAGE_SUFFIXES or not suffix:
        data = _to_jpeg_bytes(raw)
        if not filename.lower().endswith(".jpg"):
            filename = Path(filename).with_suffix(".jpg").name
    dest = receipt_dir(folder) / filename
    dest.write_bytes(data)
    return filename


def append_receipt_file(doc: Dict[str, Any], store_code: str, filename: str) -> Dict[str, Any]:
    code = (store_code or "").strip()
    stores: List[Dict[str, Any]] = list(doc.get("stores") or [])
    found = False
    for st in stores:
        if str(st.get("store_code") or "").strip().upper() == code.upper():
            files = list(st.get("receipt_files") or [])
            if filename not in files:
                files.append(filename)
            st["receipt_files"] = files
            found = True
            break
    if not found:
        raise KeyError(f"store not found: {store_code}")
    doc = dict(doc)
    doc["stores"] = stores
    return doc


def find_store(doc: Dict[str, Any], store_code: str) -> Optional[Dict[str, Any]]:
    code = (store_code or "").strip().upper()
    for st in doc.get("stores") or []:
        if str(st.get("store_code") or "").strip().upper() == code:
            return st
    return None
