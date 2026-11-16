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


def _safe_sku(sku: str) -> str:
    """仕入1点の識別子。同JANでもSKUは別になる。"""
    text = str(sku or "").strip()
    if not text or text == "未実装":
        return ""
    text = re.sub(r"[^A-Za-z0-9\-_.]", "", text)
    return text[:96]


def is_tmp_sku(sku: str) -> bool:
    """仮SKU（TMP-…）かどうか。"""
    return _safe_sku(sku).upper().startswith("TMP-")


_SKU_INDEXED_NAME_RE = re.compile(
    r"^(.+)_(\d+)(\.[^.]+)$",
    re.IGNORECASE,
)


def is_sku_indexed_product_filename(filename: str) -> bool:
    """
    {SKU}_数字.拡張子 形式か。
    ルート日付変更時に本SKUの日付部分を誤って書き換えないための判定に使う。
    旧形式 YYYY-MM-DD-CODE-item-NN は対象外。
    """
    name = Path(str(filename or "")).name
    match = _SKU_INDEXED_NAME_RE.match(name)
    if not match:
        return False
    prefix = match.group(1)
    # 旧 item 連番（…-item-01）を SKU 扱いしない
    if re.search(r"-item$", prefix, re.IGNORECASE):
        return False
    sku = _safe_sku(prefix)
    return bool(sku) and ("-" in sku or sku.upper().startswith("TMP-"))


def next_sku_product_filename(folder: Path, sku: str) -> str:
    """{SKU}_1.jpg, {SKU}_2.jpg … の次の連番。"""
    sku_s = _safe_sku(sku)
    if not sku_s:
        raise ValueError("sku required")
    dest = product_dir(folder)
    pattern = re.compile(
        rf"^{re.escape(sku_s)}_(\d+)\.",
        re.IGNORECASE,
    )
    max_n = 0
    for p in dest.iterdir():
        if not p.is_file():
            continue
        m = pattern.match(p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{sku_s}_{max_n + 1}.jpg"


def next_product_filename(folder: Path, route_date: str, store_code: str) -> str:
    """YYYY-MM-DD-STORE-item-NN.jpg の次の連番（SKU未指定時の互換用）。"""
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


def _mint_tmp_sku(route_date: str, jan: str = "", asin: str = "", hint: str = "") -> str:
    """仕入処理前でもファイル名に刻む仮SKUを作る。"""
    ymd = "".join(ch for ch in str(route_date or "") if ch.isdigit())[:8]
    if len(ymd) != 8:
        from datetime import date as _date

        ymd = _date.today().strftime("%Y%m%d")
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    hint_s = re.sub(r"[^A-Za-z0-9]", "", str(hint or "").upper())[:8]
    if jan_s:
        tail = jan_s[-6:]
    elif asin_s:
        tail = asin_s[-6:]
    elif hint_s:
        tail = hint_s
    else:
        tail = "X"
    return f"TMP-{ymd}-{tail}"


def _sku_from_product_entries(
    entries: List[Any],
    *,
    jan: str = "",
    asin: str = "",
) -> str:
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    if not jan_s and not asin_s:
        return ""
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        item_sku = _safe_sku(str(item.get("sku") or ""))
        if not item_sku:
            continue
        item_jan = _safe_jan(str(item.get("jan") or ""))
        item_asin = _safe_asin(str(item.get("asin") or ""))
        if jan_s and item_jan and item_jan == jan_s:
            return item_sku
        if asin_s and item_asin and item_asin == asin_s:
            return item_sku
    return ""


def resolve_sku_for_product_upload(
    doc: Optional[Dict[str, Any]],
    *,
    sku: str = "",
    jan: str = "",
    asin: str = "",
    route_date: str = "",
) -> str:
    """
    商品画像保存用のSKUを決める。

    仕入CSVの撮影候補だけで撮る（仕入管理未処理）ときも、仮SKUを必ず返す。
    優先: 送信SKU → 撮影候補 → 既存 product_files → 新規仮SKU。
    """
    sku_s = _safe_sku(sku)
    if sku_s:
        return sku_s

    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    doc = doc if isinstance(doc, dict) else {}

    candidates = list(doc.get("photo_candidates") or [])
    found = _sku_from_product_entries(candidates, jan=jan_s, asin=asin_s)
    if found:
        return found

    found = _sku_from_product_entries(
        list(doc.get("product_files") or []), jan=jan_s, asin=asin_s
    )
    if found:
        return found
    for store in doc.get("stores") or []:
        if not isinstance(store, dict):
            continue
        found = _sku_from_product_entries(
            list(store.get("product_files") or []), jan=jan_s, asin=asin_s
        )
        if found:
            return found

    # 仕入CSVリスト由来（JAN/ASIN付き）は仕入管理前でも必ず仮SKUを付ける
    if jan_s or asin_s:
        return _mint_tmp_sku(
            route_date or str(doc.get("route_date") or ""),
            jan=jan_s,
            asin=asin_s,
        )
    return ""


def save_product_upload(
    folder: Path,
    route_date: str,
    store_code: str,
    raw: bytes,
    original_name: str = "",
    sku: str = "",
) -> str:
    """
    商品画像を保存する。
    sku（仮SKU含む）があれば {SKU}_N.jpg。
    CSV撮影候補からの保存では resolve_sku_for_product_upload で仮SKUを先に決めること。
    """
    if not raw:
        raise ValueError("empty upload")
    sku_s = _safe_sku(sku)
    if sku_s:
        filename = next_sku_product_filename(folder, sku_s)
    else:
        # 識別子が一切無いレガシー経路のみ。CSVリスト撮影では使わない。
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


def _rewrite_product_file_entries(
    files: List[Any],
    *,
    name_map: Dict[str, str],
    old_sku: str,
    new_sku: str,
) -> List[Any]:
    """product_files 配列の file / sku を付け替える。"""
    out: List[Any] = []
    for item in files or []:
        if isinstance(item, dict):
            updated = dict(item)
            fname = str(updated.get("file") or "")
            if fname in name_map:
                updated["file"] = name_map[fname]
            item_sku = _safe_sku(str(updated.get("sku") or ""))
            if item_sku and item_sku.upper() == old_sku.upper():
                updated["sku"] = new_sku
            out.append(updated)
        elif isinstance(item, str) and item in name_map:
            out.append(name_map[item])
        else:
            out.append(item)
    return out


def remap_product_files_sku(
    folder: Path,
    doc: Dict[str, Any],
    old_sku: str,
    new_sku: str,
) -> tuple[Dict[str, Any], int]:
    """
    仮SKU→本SKU（またはSKU変更）に合わせて商品画像ファイル名と route.json を更新する。

    - 対象ファイル: {old_sku}_N.ext
    - 本SKUファイルを誤って TMP に戻さない（new が TMP で old が本SKUなら何もしない）
    - 行き先が既存ならその1枚はスキップ（壊さない）
    """
    old_s = _safe_sku(old_sku)
    new_s = _safe_sku(new_sku)
    if not old_s or not new_s or old_s.upper() == new_s.upper():
        return doc, 0
    # 本SKU → 仮SKU への逆変換は拒否
    if (not is_tmp_sku(old_s)) and is_tmp_sku(new_s):
        return doc, 0

    dest = product_dir(folder)
    pattern = re.compile(
        rf"^{re.escape(old_s)}_(\d+)(\.[^.]+)$",
        re.IGNORECASE,
    )
    name_map: Dict[str, str] = {}
    renamed = 0
    if dest.is_dir():
        for path in list(dest.iterdir()):
            if not path.is_file():
                continue
            match = pattern.match(path.name)
            if not match:
                continue
            new_name = f"{new_s}_{match.group(1)}{match.group(2)}"
            target = dest / new_name
            if target.exists() and target.resolve() != path.resolve():
                continue
            if path.name == new_name:
                name_map[path.name] = new_name
                continue
            path.rename(target)
            name_map[path.name] = new_name
            renamed += 1

    out = dict(doc or {})
    if "product_files" in out or name_map:
        out["product_files"] = _rewrite_product_file_entries(
            list(out.get("product_files") or []),
            name_map=name_map,
            old_sku=old_s,
            new_sku=new_s,
        )
    stores: List[Dict[str, Any]] = []
    for store in out.get("stores") or []:
        if not isinstance(store, dict):
            stores.append(store)
            continue
        copied = dict(store)
        if copied.get("product_files") is not None or name_map:
            copied["product_files"] = _rewrite_product_file_entries(
                list(copied.get("product_files") or []),
                name_map=name_map,
                old_sku=old_s,
                new_sku=new_s,
            )
        stores.append(copied)
    if stores or out.get("stores") is not None:
        out["stores"] = stores

    candidates = list(out.get("photo_candidates") or [])
    if candidates:
        updated_rows: List[Any] = []
        for row in candidates:
            if isinstance(row, dict):
                copied = dict(row)
                if _safe_sku(str(copied.get("sku") or "")).upper() == old_s.upper():
                    copied["sku"] = new_s
                updated_rows.append(copied)
            else:
                updated_rows.append(row)
        out["photo_candidates"] = updated_rows

    # メタデータだけ（ファイル無し）でも sku フィールドは更新したい
    if renamed == 0 and name_map:
        renamed = len(name_map)
    return out, renamed


def apply_sku_upgrades_to_box(
    folder: Path,
    doc: Dict[str, Any],
    upgrades: List[tuple[str, str]],
) -> tuple[Dict[str, Any], int]:
    """複数の old→new SKU 付け替えを順に適用する。"""
    out = dict(doc or {})
    total = 0
    seen: set[tuple[str, str]] = set()
    for old_sku, new_sku in upgrades:
        key = (_safe_sku(old_sku).upper(), _safe_sku(new_sku).upper())
        if not key[0] or not key[1] or key[0] == key[1] or key in seen:
            continue
        seen.add(key)
        out, n = remap_product_files_sku(folder, out, old_sku, new_sku)
        total += n
    return out, total


def append_product_file(
    doc: Dict[str, Any],
    store_code: str,
    filename: str,
    jan: str = "",
    asin: str = "",
    sku: str = "",
) -> Dict[str, Any]:
    code = (store_code or "").strip()
    stores: List[Dict[str, Any]] = list(doc.get("stores") or [])
    found = False
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    sku_s = _safe_sku(sku)
    for st in stores:
        if str(st.get("store_code") or "").strip().upper() == code.upper():
            files = list(st.get("product_files") or [])
            entry: Dict[str, Any] = {"file": filename}
            if sku_s:
                entry["sku"] = sku_s
            if jan_s:
                entry["jan"] = jan_s
            if asin_s:
                entry["asin"] = asin_s
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


def confirm_product_group(
    doc: Dict[str, Any],
    store_code: str,
    jan: str = "",
    asin: str = "",
    sku: str = "",
) -> Dict[str, Any]:
    """同じ店舗・同じSKU（無ければJAN/ASIN）の商品画像を撮影終了にする。"""
    code = (store_code or "").strip()
    sku_s = _safe_sku(sku)
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    if not _product_link_key(sku_s, jan_s, asin_s):
        raise ValueError("sku, jan, or asin required")
    stores: List[Dict[str, Any]] = list(doc.get("stores") or [])
    found = False
    confirmed = 0
    for st in stores:
        if str(st.get("store_code") or "").strip().upper() != code.upper():
            continue
        found = True
        files: List[Any] = []
        for item in st.get("product_files") or []:
            if _matches_product(item, sku_s, jan_s, asin_s):
                updated = dict(item)
                updated["confirmed"] = True
                if sku_s and not _safe_sku(str(updated.get("sku") or "")):
                    updated["sku"] = sku_s
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
    sku: str = "",
) -> Dict[str, Any]:
    """商品画像をルート直下に足す。店舗は覚えていなくても保存できる。"""
    files = list(doc.get("product_files") or [])
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    sku_s = _safe_sku(sku)
    entry: Dict[str, Any] = {"file": filename}
    if sku_s:
        entry["sku"] = sku_s
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


def _matches_product(
    item: Dict[str, Any],
    sku_s: str = "",
    jan_s: str = "",
    asin_s: str = "",
) -> bool:
    """SKUがあればSKUで1点を特定。無ければ従来どおりJAN→ASIN。"""
    if not isinstance(item, dict):
        return False
    item_sku = _safe_sku(str(item.get("sku") or ""))
    item_jan = _safe_jan(str(item.get("jan") or ""))
    item_asin = _safe_asin(str(item.get("asin") or ""))
    if sku_s:
        # 同JAN複数点があるので、SKU指定時はSKU一致のみ（JANへフォールバックしない）
        return item_sku == sku_s
    if jan_s:
        return (not item_sku) and item_jan == jan_s
    if asin_s:
        return (not item_sku) and (not item_jan) and item_asin == asin_s
    return False


def confirm_route_product_group(
    doc: Dict[str, Any],
    jan: str = "",
    asin: str = "",
    sku: str = "",
) -> Dict[str, Any]:
    """同じ商品の画像をルート単位で撮影終了にする。優先: SKU → JAN → ASIN。"""
    sku_s = _safe_sku(sku)
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    if not _product_link_key(sku_s, jan_s, asin_s):
        raise ValueError("sku, jan, or asin required")
    confirmed = 0
    files: List[Any] = []
    for item in doc.get("product_files") or []:
        if _matches_product(item, sku_s, jan_s, asin_s):
            updated = dict(item)
            updated["confirmed"] = True
            if sku_s and not _safe_sku(str(updated.get("sku") or "")):
                updated["sku"] = sku_s
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
            if _matches_product(item, sku_s, jan_s, asin_s):
                updated = dict(item)
                updated["confirmed"] = True
                if sku_s and not _safe_sku(str(updated.get("sku") or "")):
                    updated["sku"] = sku_s
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


def _product_link_key(sku: str = "", jan: str = "", asin: str = "") -> str:
    sku_s = _safe_sku(sku)
    if sku_s:
        return "sku:" + sku_s
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
        sku = _safe_sku(str(item.get("sku") or ""))
        jan = _safe_jan(str(item.get("jan") or ""))
        asin = _safe_asin(str(item.get("asin") or ""))
        key = _product_link_key(sku, jan, asin)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append({"sku": sku, "jan": jan, "asin": asin})
    return found


def mark_no_image(
    doc: Dict[str, Any],
    jan: str = "",
    asin: str = "",
    sku: str = "",
) -> Dict[str, Any]:
    """新品などで写真が不要な商品を、画像なしの撮影済みにする。"""
    sku_s = _safe_sku(sku)
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    key = _product_link_key(sku_s, jan_s, asin_s)
    if not key:
        raise ValueError("sku, jan, or asin required")
    rows = list_no_image_products(doc)
    if not any(_product_link_key(row.get("sku", ""), row.get("jan", ""), row.get("asin", "")) == key for row in rows):
        rows.append({"sku": sku_s, "jan": jan_s, "asin": asin_s})
    out = dict(doc)
    out["no_image_products"] = rows
    return out


def clear_no_image(
    doc: Dict[str, Any],
    jan: str = "",
    asin: str = "",
    sku: str = "",
) -> tuple[Dict[str, Any], bool]:
    """画像不要を取り消し、選ぶリストへ戻せるようにする。"""
    key = _product_link_key(sku, jan, asin)
    if not key:
        raise ValueError("sku, jan, or asin required")
    kept: List[Dict[str, str]] = []
    removed = False
    for row in list_no_image_products(doc):
        if _product_link_key(row.get("sku", ""), row.get("jan", ""), row.get("asin", "")) == key:
            removed = True
            continue
        kept.append(row)
    out = dict(doc)
    out["no_image_products"] = kept
    return out, removed


def confirmed_product_groups(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """撮影終了済みの商品と、その画像ファイル名。優先: SKU → JAN → ASIN。"""
    groups: Dict[str, Dict[str, Any]] = {}
    for items in _iter_product_file_lists(doc):
        for item in items:
            if not isinstance(item, dict) or not item.get("confirmed"):
                continue
            sku = _safe_sku(str(item.get("sku") or ""))
            jan = _safe_jan(str(item.get("jan") or ""))
            asin = _safe_asin(str(item.get("asin") or ""))
            name = str(item.get("file") or "").strip()
            key = _product_link_key(sku, jan, asin)
            if not name or not key:
                continue
            bucket = groups.setdefault(
                key,
                {"sku": sku, "jan": jan, "asin": asin, "files": []},
            )
            if name not in bucket["files"]:
                bucket["files"].append(name)
    return list(groups.values())


def discard_product_group(
    doc: Dict[str, Any],
    folder: Path,
    jan: str = "",
    asin: str = "",
    sku: str = "",
) -> Dict[str, Any]:
    """再撮影のため、その商品の画像を記録とファイルから消す。"""
    sku_s = _safe_sku(sku)
    jan_s = _safe_jan(jan)
    asin_s = _safe_asin(asin)
    if not _product_link_key(sku_s, jan_s, asin_s):
        raise ValueError("sku, jan, or asin required")
    removed: List[str] = []

    def strip(items: Any) -> List[Any]:
        kept: List[Any] = []
        for item in items or []:
            if _matches_product(item, sku_s, jan_s, asin_s):
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
