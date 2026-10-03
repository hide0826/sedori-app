# -*- coding: utf-8 -*-
"""店舗マスタ備考と route.json stores[].notes の同期。"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _store_code(store: Dict[str, Any]) -> str:
    return str(store.get("store_code") or store.get("supplier_code") or "").strip()


def _notes_text(store: Dict[str, Any]) -> str:
    return str(store.get("notes") or "").strip()


def enrich_store_notes_from_master(doc: Dict[str, Any]) -> Dict[str, Any]:
    """route.json の店舗備考が空のとき、店舗マスタ備考で補完する（表示用）。"""
    stores = doc.get("stores")
    if not isinstance(stores, list) or not stores:
        return doc
    need_codes = [_store_code(st) for st in stores if isinstance(st, dict) and not _notes_text(st)]
    need_codes = [c for c in need_codes if c]
    if not need_codes:
        return doc
    try:
        from route_web.desktop_bridge import ensure_desktop_importable

        ensure_desktop_importable()
        from database.store_db import StoreDatabase

        db = StoreDatabase()
    except Exception as exc:
        print(f"店舗マスタ備考の読込をスキップ: {exc}")
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

    try:
        from route_web.desktop_bridge import ensure_desktop_importable

        ensure_desktop_importable()
        from database.store_db import StoreDatabase

        db = StoreDatabase()
    except Exception as exc:
        print(f"店舗マスタ備考の同期をスキップ: {exc}")
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
