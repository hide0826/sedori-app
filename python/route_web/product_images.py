# -*- coding: utf-8 -*-
"""商品画像の保存（Phase 5）。"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

PRODUCT_DIR_NAME = "商品画像"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp"}


def product_dir(folder: Path) -> Path:
    d = folder / PRODUCT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def route_file_code(doc: Dict[str, Any]) -> str:
    """ファイル名に使うルート記号。店舗コードは使わない。"""
    raw = str(doc.get("route_code") or "").strip()
    code = _safe_store_code(raw)
    if not raw or code == "XX-00":
        return "RT"
    return code


def _safe_store_code(store_code: str) -> str:
    code = (store_code or "").strip().upper()
    code = re.sub(r"[^A-Z0-9\-]", "", code)
    return code or "XX-00"


def _safe_jan(jan: str) -> str:
    digits = re.sub(r"\D", "", jan or "")
    return digits[:32]


def _safe_asin(asin: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (asin or "").upper())[:16]


def next_product_filename(folder: Path, route_date: str, store_code: str) -> str:
    """YYYY-MM-DD-STORE-item-NN.jpg の次の連番。"""
    date = (route_date or "").strip() or "0000-00-00"
    code = _safe_store_code(store_code)
    dest = product_dir(folder)
    pattern = re.compile(
        rf"^{re.escape(date)}-{re.escape(code)}-item-(\d+)\.",
        re.IGNORECASE,
    )
    max_n = 0
    for p in dest.iterdir():
        if not p.is_file():
            continue
        m = pattern.match(p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{date}-{code}-item-{max_n + 1:02d}.jpg"


def _to_jpeg_bytes(raw: bytes, max_side: int = 1920) -> bytes:
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


def save_product_upload(
    folder: Path,
    route_date: str,
    store_code: str,
    raw: bytes,
    original_name: str = "",
) -> str:
    if not raw:
        raise ValueError("empty upload")
    filename = next_product_filename(folder, route_date, store_code)
    suffix = Path(original_name or "").suffix.lower()
    data = raw
    if suffix in IMAGE_SUFFIXES or not suffix:
        data = _to_jpeg_bytes(raw)
        if not filename.lower().endswith(".jpg"):
            filename = Path(filename).with_suffix(".jpg").name
    dest = product_dir(folder) / filename
    dest.write_bytes(data)
    return filename


def append_product_file(
    doc: Dict[str, Any],
    store_code: str,
    filename: str,
    jan: str = "",
) -> Dict[str, Any]:
    code = (store_code or "").strip()
    stores: List[Dict[str, Any]] = list(doc.get("stores") or [])
    found = False
    jan_s = _safe_jan(jan)
    for st in stores:
        if str(st.get("store_code") or "").strip().upper() == code.upper():
            files = list(st.get("product_files") or [])
            entry: Dict[str, Any] = {"file": filename}
            if jan_s:
                entry["jan"] = jan_s
            # 同名があれば上書き
            files = [f for f in files if not (
                (isinstance(f, dict) and f.get("file") == filename)
                or f == filename
            )]
            files.append(entry)
            st["product_files"] = files
            found = True
            break
    if not found:
        raise KeyError(f"store not found: {store_code}")
    doc = dict(doc)
    doc["stores"] = stores
    return doc


def confirm_product_group(doc: Dict[str, Any], store_code: str, jan: str) -> Dict[str, Any]:
    """同じ店舗・同じJANの商品画像を、撮影終了として確定する。"""
    code = (store_code or "").strip()
    jan_s = _safe_jan(jan)
    if not jan_s:
        raise ValueError("jan required")
    stores: List[Dict[str, Any]] = list(doc.get("stores") or [])
    found = False
    confirmed = 0
    for st in stores:
        if str(st.get("store_code") or "").strip().upper() != code.upper():
            continue
        found = True
        files: List[Any] = []
        for item in st.get("product_files") or []:
            if isinstance(item, dict) and _safe_jan(str(item.get("jan") or "")) == jan_s:
                updated = dict(item)
                updated["confirmed"] = True
                files.append(updated)
                confirmed += 1
            else:
                files.append(item)
        st["product_files"] = files
        break
    if not found:
        raise KeyError(f"store not found: {store_code}")
    if confirmed == 0:
        raise ValueError("confirm target not found")
    doc = dict(doc)
    doc["stores"] = stores
    return doc


def append_route_product_file(
    doc: Dict[str, Any],
    filename: str,
    jan: str = "",
    asin: str = "",
) -> Dict[str, Any]:
    """商品画像をルート直下に足す。店舗は覚えていなくても保存できる。"""
    files = list(doc.get("product_files") or [])
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    entry: Dict[str, Any] = {"file": filename}
    if jan_s:
        entry["jan"] = jan_s
    if asin_s:
        entry["asin"] = asin_s
    files = [
        item
        for item in files
        if not (
            (isinstance(item, dict) and item.get("file") == filename)
            or item == filename
        )
    ]
    files.append(entry)
    out = dict(doc)
    out["product_files"] = files
    return out


def _matches_product(item: Dict[str, Any], jan_s: str, asin_s: str) -> bool:
    """JANがあればJANで、無ければASINで同じ商品か見る。"""
    if not isinstance(item, dict):
        return False
    item_jan = _safe_jan(str(item.get("jan") or ""))
    item_asin = _safe_asin(str(item.get("asin") or ""))
    if jan_s:
        return item_jan == jan_s
    if asin_s:
        return (not item_jan) and item_asin == asin_s
    return False


def confirm_route_product_group(doc: Dict[str, Any], jan: str, asin: str = "") -> Dict[str, Any]:
    """同じ商品の画像を、ルート単位で撮影終了にする。JANが無ければASIN。"""
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    if not jan_s and not asin_s:
        raise ValueError("jan or asin required")
    confirmed = 0
    files: List[Any] = []
    for item in doc.get("product_files") or []:
        if _matches_product(item, jan_s, asin_s):
            updated = dict(item)
            updated["confirmed"] = True
            files.append(updated)
            confirmed += 1
        else:
            files.append(item)
    stores: List[Dict[str, Any]] = []
    for store in doc.get("stores") or []:
        if not isinstance(store, dict):
            stores.append(store)
            continue
        store_files: List[Any] = []
        for item in store.get("product_files") or []:
            if _matches_product(item, jan_s, asin_s):
                updated = dict(item)
                updated["confirmed"] = True
                store_files.append(updated)
                confirmed += 1
            else:
                store_files.append(item)
        copied = dict(store)
        copied["product_files"] = store_files
        stores.append(copied)
    if confirmed == 0:
        raise ValueError("confirm target not found")
    out = dict(doc)
    out["product_files"] = files
    out["stores"] = stores
    return out


def _iter_product_file_lists(doc: Dict[str, Any]):
    yield doc.get("product_files") or []
    for store in doc.get("stores") or []:
        if isinstance(store, dict):
            yield store.get("product_files") or []


def _product_link_key(jan: str, asin: str) -> str:
    jan_s = _safe_jan(jan)
    if jan_s:
        return "jan:" + jan_s
    asin_s = _safe_asin(asin)
    if asin_s:
        return "asin:" + asin_s
    return ""


def list_no_image_products(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    """写真を撮らないと決めた商品。撮影済み一覧へ出す。"""
    found: List[Dict[str, str]] = []
    seen = set()
    for item in doc.get("no_image_products") or []:
        if not isinstance(item, dict):
            continue
        jan = _safe_jan(str(item.get("jan") or ""))
        asin = _safe_asin(str(item.get("asin") or ""))
        key = _product_link_key(jan, asin)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append({"jan": jan, "asin": asin})
    return found


def mark_no_image(doc: Dict[str, Any], jan: str, asin: str = "") -> Dict[str, Any]:
    """新品などで写真が不要な商品を、画像なしの撮影済みにする。"""
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    if not _product_link_key(jan_s, asin_s):
        raise ValueError("jan or asin required")
    rows = list_no_image_products(doc)
    if not any(_product_link_key(row["jan"], row["asin"]) == _product_link_key(jan_s, asin_s) for row in rows):
        rows.append({"jan": jan_s, "asin": asin_s})
    out = dict(doc)
    out["no_image_products"] = rows
    return out


def clear_no_image(doc: Dict[str, Any], jan: str, asin: str = "") -> tuple[Dict[str, Any], bool]:
    """画像不要を取り消し、選ぶリストへ戻せるようにする。"""
    key = _product_link_key(jan, asin)
    if not key:
        raise ValueError("jan or asin required")
    kept: List[Dict[str, str]] = []
    removed = False
    for row in list_no_image_products(doc):
        if _product_link_key(row["jan"], row["asin"]) == key:
            removed = True
            continue
        kept.append(row)
    out = dict(doc)
    out["no_image_products"] = kept
    return out, removed


def confirmed_product_groups(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """撮影終了済みの商品と、その画像ファイル名。JANが無ければASIN。"""
    groups: Dict[str, Dict[str, Any]] = {}
    for items in _iter_product_file_lists(doc):
        for item in items:
            if not isinstance(item, dict) or not item.get("confirmed"):
                continue
            jan = _safe_jan(str(item.get("jan") or ""))
            asin = _safe_asin(str(item.get("asin") or ""))
            name = str(item.get("file") or "").strip()
            if not name or not (jan or asin):
                continue
            key = "jan:" + jan if jan else "asin:" + asin
            bucket = groups.setdefault(key, {"jan": jan, "asin": asin, "files": []})
            if name not in bucket["files"]:
                bucket["files"].append(name)
    return list(groups.values())


def discard_product_group(doc: Dict[str, Any], folder: Path, jan: str, asin: str = "") -> Dict[str, Any]:
    """再撮影のため、その商品の画像を記録とファイルから消す。"""
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    if not jan_s and not asin_s:
        raise ValueError("jan or asin required")
    removed: List[str] = []

    def strip(items: Any) -> List[Any]:
        kept: List[Any] = []
        for item in items or []:
            if _matches_product(item, jan_s, asin_s):
                name = str(item.get("file") or "").strip()
                if name:
                    removed.append(name)
                continue
            kept.append(item)
        return kept

    out = dict(doc)
    out["product_files"] = strip(doc.get("product_files"))
    stores: List[Any] = []
    for store in doc.get("stores") or []:
        if not isinstance(store, dict):
            stores.append(store)
            continue
        copied = dict(store)
        copied["product_files"] = strip(store.get("product_files"))
        stores.append(copied)
    out["stores"] = stores
    if not removed:
        raise ValueError("reshoot target not found")
    dest = product_dir(folder)
    for name in removed:
        path = dest / Path(name).name
        if path.is_file():
            path.unlink()
    return out


def product_filenames(store: Optional[Dict[str, Any]]) -> List[str]:
    if not store:
        return []
    out: List[str] = []
    for item in store.get("product_files") or []:
        if isinstance(item, dict):
            fn = str(item.get("file") or "").strip()
        else:
            fn = str(item).strip()
        if fn:
            out.append(fn)
    return out
