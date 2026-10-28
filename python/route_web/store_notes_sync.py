# -*- coding: utf-8 -*-
"""店舗マスタ備考・座標と route.json stores[] の同期。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _store_code(store: Dict[str, Any]) -> str:
    return str(store.get("store_code") or store.get("supplier_code") or "").strip()


def _notes_text(store: Dict[str, Any]) -> str:
    return str(store.get("notes") or "").strip()


def _parse_coord(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN
        return None
    return num


def _has_coords(store: Dict[str, Any]) -> bool:
    return (
        _parse_coord(store.get("latitude")) is not None
        and _parse_coord(store.get("longitude")) is not None
    )


def _open_store_db():
    try:
        from route_web.desktop_bridge import ensure_desktop_importable

        ensure_desktop_importable()
        from database.store_db import StoreDatabase

        return StoreDatabase()
    except Exception as exc:
        print(f"店舗マスタの読込をスキップ: {exc}")
        return None


def enrich_store_notes_from_master(doc: Dict[str, Any]) -> Dict[str, Any]:
    """route.json の店舗備考が空のとき、店舗マスタ備考で補完する（表示用）。"""
    stores = doc.get("stores")
    if not isinstance(stores, list) or not stores:
        return doc
    need_codes = [_store_code(st) for st in stores if isinstance(st, dict) and not _notes_text(st)]
    need_codes = [c for c in need_codes if c]
    if not need_codes:
        return doc
    db = _open_store_db()
    if db is None:
        return doc

    out = dict(doc)
    new_stores: List[Dict[str, Any]] = []
    for st in stores:
        if not isinstance(st, dict):
            new_stores.append(st)
            continue
        copy = dict(st)
        if not _notes_text(copy):
            code = _store_code(copy)
            if code:
                try:
                    master = db.get_store_by_code(code)
                except Exception:
                    master = None
                if master:
                    sql_notes = str(master.get("notes", "") or "").strip()
                    cf_notes = str((master.get("custom_fields") or {}).get("notes", "") or "").strip()
                    merged = sql_notes or cf_notes
                    if sql_notes and cf_notes and sql_notes != cf_notes:
                        merged = f"{sql_notes}, {cf_notes}"
                    if merged:
                        copy["notes"] = merged
        new_stores.append(copy)
    out["stores"] = new_stores
    return out


def enrich_store_coords_from_master(doc: Dict[str, Any]) -> Dict[str, Any]:
    """route.json の店舗に緯度経度／住所が無いとき、店舗マスタから補完する（Maps案内用）。"""
    stores = doc.get("stores")
    if not isinstance(stores, list) or not stores:
        return doc

    need = False
    for st in stores:
        if not isinstance(st, dict):
            continue
        if not _store_code(st):
            continue
        if not _has_coords(st) or not str(st.get("address") or "").strip():
            need = True
            break
    if not need:
        return doc

    db = _open_store_db()
    if db is None:
        return doc

    out = dict(doc)
    new_stores: List[Dict[str, Any]] = []
    for st in stores:
        if not isinstance(st, dict):
            new_stores.append(st)
            continue
        copy = dict(st)
        code = _store_code(copy)
        if code and (not _has_coords(copy) or not str(copy.get("address") or "").strip()):
            try:
                master = db.get_store_by_code(code)
            except Exception:
                master = None
            if master:
                if not _has_coords(copy):
                    lat = _parse_coord(master.get("latitude"))
                    lng = _parse_coord(master.get("longitude"))
                    if lat is not None and lng is not None:
                        copy["latitude"] = lat
                        copy["longitude"] = lng
                if not str(copy.get("address") or "").strip():
                    addr = str(master.get("address") or "").strip()
                    if addr:
                        copy["address"] = addr
        new_stores.append(copy)
    out["stores"] = new_stores
    return out


def sync_changed_store_notes_to_master(
    existing: Dict[str, Any],
    body: Dict[str, Any],
) -> Tuple[int, int]:
    """備考が変わった店舗だけ店舗マスタへ上書きする。

    Returns:
        (updated, skipped)
    """
    old_by_code: Dict[str, str] = {}
    for st in existing.get("stores") or []:
        if not isinstance(st, dict):
            continue
        code = _store_code(st)
        if code:
            old_by_code[code] = _notes_text(st)

    changed: List[Tuple[str, str]] = []
    for st in body.get("stores") or []:
        if not isinstance(st, dict):
            continue
        code = _store_code(st)
        if not code:
            continue
        new_notes = _notes_text(st)
        old_notes = old_by_code.get(code, "")
        if new_notes != old_notes:
            changed.append((code, new_notes))

    if not changed:
        return 0, 0

    db = _open_store_db()
    if db is None:
        return 0, len(changed)

    updated = 0
    skipped = 0
    for code, notes in changed:
        try:
            if db.set_store_notes_by_code(code, notes):
                updated += 1
            else:
                skipped += 1
                print(f"店舗マスタ備考の上書きをスキップ（店舗未登録）: {code}")
        except Exception as exc:
            skipped += 1
            print(f"店舗マスタ備考の上書き失敗 ({code}): {exc}")
    return updated, skipped
