#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗名から店舗種別（ブランド系）タグを自動判別・付与する。

店舗種別:
  BOOKOFF系 / セカンドストリート系 / ハードオフ系 / トレジャーファクトリー系 / その他

評価系（手動）とは別グループ:
  大型店舗 / 値付け甘い / あまり行かなくて良い
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

# 評価・メモ系（手動タグ）
QUALITY_TAG_NAMES: Tuple[str, ...] = (
    "大型店舗",
    "値付け甘い",
    "あまり行かなくて良い",
)

# 旧名称 → 正式名称（既存DBのリネーム用）
BRAND_TAG_RENAMES: Dict[str, str] = {
    "bookoff系": "BOOKOFF系",
    "Bookoff系": "BOOKOFF系",
    "セカスト系": "セカンドストリート系",
    "オフモール系": "ハードオフ系",
    "トレファク系": "トレジャーファクトリー系",
}

# (タグ名, 色, 優先度, 表示順)
BRAND_TAG_DEFS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "BOOKOFF系",
        "color": "#c62828",
        "priority": 40,
        "display_order": 10,
    },
    {
        "name": "セカンドストリート系",
        "color": "#00695c",
        "priority": 41,
        "display_order": 11,
    },
    {
        "name": "ハードオフ系",
        "color": "#1565c0",
        "priority": 42,
        "display_order": 12,
    },
    {
        "name": "トレジャーファクトリー系",
        "color": "#ef6c00",
        "priority": 43,
        "display_order": 13,
    },
    {
        "name": "その他",
        "color": "#607d8b",
        "priority": 90,
        "display_order": 14,
    },
)

BRAND_TAG_NAMES: Tuple[str, ...] = tuple(t["name"] for t in BRAND_TAG_DEFS)

# 地図ラベル（文字コード。公式ロゴは使わない）
# ハードオフ系は併設数で H1 / H2 / H3
MAP_ICON_ORDER: Tuple[str, ...] = (
    "secondstreet",
    "treasurefactory",
    "bookoff",
    "hardoff1",
    "hardoff2",
    "hardoff3",
    "other",
)

_MAP_ICON_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "hardoff",
        (
            "ホビーオフ",
            "ホビー・オフ",
            "HOBBY OFF",
            "HOBBYOFF",
            "オフハウス",
            "オフ・ハウス",
            "OFF HOUSE",
            "OFFHOUSE",
            "オフモール",
            "オフ・モール",
            "OFF MALL",
            "OFFMALL",
            "ハードオフ",
            "HARD OFF",
            "HARDOFF",
            "モードオフ",
            "MODE OFF",
            "MODEOFF",
        ),
    ),
    (
        "treasurefactory",
        (
            "トレジャーファクトリー",
            "トレファク",
            "TREASURE FACTORY",
            "TREASUREFACTORY",
            "TREFAC",
        ),
    ),
    (
        "secondstreet",
        (
            "セカンドストリート",
            "セカンド・ストリート",
            "セカスト",
            "2ND STREET",
            "2NDSTREET",
            "SECOND STREET",
            "SECONDSTREET",
        ),
    ),
    (
        "bookoff",
        ("ブックオフ", "BOOKOFF", "BOOK OFF", "BOOK-OFF"),
    ),
)

_BRAND_TAG_TO_ICON: Dict[str, str] = {
    "BOOKOFF系": "bookoff",
    "セカンドストリート系": "secondstreet",
    "ハードオフ系": "hardoff",
    "トレジャーファクトリー系": "treasurefactory",
    "その他": "other",
}

MAP_ICON_DEFS: Dict[str, Dict[str, str]] = {
    "secondstreet": {
        "label": "セカンドストリート系",
        "text": "SS",
        "bg": "#00897b",
        "fg": "#ffffff",
    },
    "treasurefactory": {
        "label": "トレジャーファクトリー系",
        "text": "TR",
        "bg": "#ef6c00",
        "fg": "#ffffff",
    },
    "bookoff": {
        "label": "BOOKOFF系",
        "text": "BO",
        "bg": "#c62828",
        "fg": "#ffffff",
    },
    "hardoff1": {
        "label": "ハードオフ系",
        "text": "H1",
        "bg": "#1565c0",
        "fg": "#ffffff",
    },
    "hardoff2": {
        "label": "ハードオフ系2店舗併設",
        "text": "H2",
        "bg": "#0d47a1",
        "fg": "#ffffff",
    },
    "hardoff3": {
        "label": "ハードオフ系3店舗併設",
        "text": "H3",
        "bg": "#1a237e",
        "fg": "#ffffff",
    },
    "other": {
        "label": "その他",
        "text": "他",
        "bg": "#607d8b",
        "fg": "#ffffff",
    },
}

# 長い／具体的な表記を先に判定
_BRAND_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "トレジャーファクトリー系",
        (
            "トレジャーファクトリー",
            "トレファク",
            "TREASURE FACTORY",
            "TREASUREFACTORY",
            "TREFAC",
        ),
    ),
    (
        "セカンドストリート系",
        (
            "セカンドストリート",
            "セカンド・ストリート",
            "セカスト",
            "2ND STREET",
            "2NDSTREET",
            "SECOND STREET",
            "SECONDSTREET",
        ),
    ),
        (
            "ハードオフ系",
            (
                "ハードオフ",
                "ホビーオフ",
                "ホビー・オフ",
                "オフハウス",
                "オフ・ハウス",
                "オフモール",
                "HARD OFF",
                "HARDOFF",
                "HOBBY OFF",
                "HOBBYOFF",
                "OFF HOUSE",
                "OFFHOUSE",
                "OFF MALL",
                "OFFMALL",
            ),
        ),
    (
        "BOOKOFF系",
        (
            "ブックオフ",
            "BOOKOFF",
            "BOOK OFF",
            "BOOK-OFF",
        ),
    ),
)


def _norm(s: str) -> str:
    text = unicodedata.normalize("NFKC", (s or "").strip())
    text = text.upper()
    text = re.sub(r"[\s\u3000]+", " ", text)
    return text


def detect_brand_tag_name(store_name: str) -> str:
    """店舗名から店舗種別タグ名を返す（該当なしは「その他」）。"""
    name = _norm(store_name)
    if not name:
        return "その他"
    compact = name.replace(" ", "").replace("・", "")
    for tag_name, patterns in _BRAND_PATTERNS:
        for pat in patterns:
            p = _norm(pat)
            p_compact = p.replace(" ", "").replace("・", "")
            if p and (p in name or p_compact in compact):
                return tag_name
    return "その他"


def detect_map_icon_key(store_name: str) -> str:
    """店舗名から地図ラベル種別を返す（ハードオフ系は hardoff）。"""
    name = _norm(store_name)
    if not name:
        return "other"
    compact = name.replace(" ", "").replace("・", "")
    for key, patterns in _MAP_ICON_PATTERNS:
        for pat in patterns:
            p = _norm(pat)
            p_compact = p.replace(" ", "").replace("・", "")
            if p and (p in name or p_compact in compact):
                return key
    return "other"


def icon_key_from_brand_tag_name(tag_name: str) -> Optional[str]:
    """店舗種別タグ名から地図ラベル種別へ。該当しなければ None。"""
    return _BRAND_TAG_TO_ICON.get((tag_name or "").strip())


def hardoff_collocation_icon_key(member_count: int) -> str:
    """併設店舗数から H1 / H2 / H3 のキーを返す。"""
    try:
        n = int(member_count)
    except (TypeError, ValueError):
        n = 1
    if n >= 3:
        return "hardoff3"
    if n == 2:
        return "hardoff2"
    return "hardoff1"


def normalize_map_icon_key(key: str) -> str:
    """hardoff を単独表示用の hardoff1 にそろえる。"""
    k = (key or "").strip() or "other"
    if k == "hardoff":
        return "hardoff1"
    return k


def resolve_map_icon_key(
    store_name: str, tag_names: Optional[Sequence[str]] = None
) -> str:
    """店名を優先し、判別できなければ店舗種別タグからラベルを決める。"""
    key = detect_map_icon_key(store_name)
    if key != "other":
        return normalize_map_icon_key(key)
    for raw in tag_names or []:
        mapped = icon_key_from_brand_tag_name(str(raw or ""))
        if mapped:
            return normalize_map_icon_key(mapped)
    return "other"


def is_brand_tag_name(name: str) -> bool:
    n = (name or "").strip()
    return n in BRAND_TAG_NAMES or n in BRAND_TAG_RENAMES


def is_quality_tag_name(name: str) -> bool:
    return (name or "").strip() in QUALITY_TAG_NAMES


def _rename_legacy_brand_tags(db) -> None:
    """旧ブランドタグ名を正式名称へリネーム（必要なときだけ）。"""
    tags = db.list_store_tags(active_only=False)
    by_name = {str(t.get("name") or "").strip(): t for t in tags}
    # 旧名が1つも無ければ何もしない（毎回の全店舗走査を避ける）
    if not any(old in by_name for old in BRAND_TAG_RENAMES if old != BRAND_TAG_RENAMES[old]):
        return

    # リンクを一括取得（N+1回避）
    links_by_store: Dict[int, List[int]] = {}
    try:
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT store_id, tag_id FROM store_tag_links")
        for row in cursor.fetchall():
            sid = int(row[0])
            tid = int(row[1])
            links_by_store.setdefault(sid, []).append(tid)
    except Exception:
        links_by_store = {}

    for old_name, new_name in BRAND_TAG_RENAMES.items():
        old = by_name.get(old_name)
        if not old or old_name == new_name:
            continue
        new = by_name.get(new_name)
        if new is not None:
            try:
                old_id = int(old["id"])
                new_id = int(new["id"])
                for sid, ids in list(links_by_store.items()):
                    if old_id not in ids:
                        continue
                    merged = [i for i in ids if i != old_id]
                    if new_id not in merged:
                        merged.append(new_id)
                    db.set_store_tag_ids(int(sid), merged)
                    links_by_store[sid] = merged
                db.update_store_tag(
                    old_id,
                    {
                        "name": str(old.get("name") or old_name),
                        "color": old.get("color") or "#607d8b",
                        "priority": int(old.get("priority") or 99),
                        "display_order": int(old.get("display_order") or 99),
                        "is_active": 0,
                    },
                )
            except Exception:
                pass
            continue
        try:
            color = old.get("color") or next(
                (d["color"] for d in BRAND_TAG_DEFS if d["name"] == new_name),
                "#607d8b",
            )
            db.update_store_tag(
                int(old["id"]),
                {
                    "name": new_name,
                    "color": color,
                    "priority": int(old.get("priority") or 40),
                    "display_order": int(old.get("display_order") or 10),
                    "is_active": 1 if old.get("is_active", 1) else 0,
                },
            )
            by_name[new_name] = {**old, "name": new_name}
            by_name.pop(old_name, None)
        except Exception:
            pass


def ensure_brand_store_tags(db) -> Dict[str, int]:
    """店舗種別タグが無ければ追加し、名前→ID を返す（既存は触らない）。"""
    _rename_legacy_brand_tags(db)
    existing_rows = {
        str(t.get("name") or "").strip(): t
        for t in db.list_store_tags(active_only=False)
        if t.get("id") is not None and str(t.get("name") or "").strip()
    }
    existing_ids = {
        name: int(row["id"]) for name, row in existing_rows.items()
    }
    for tag in BRAND_TAG_DEFS:
        name = tag["name"]
        if name in existing_ids:
            continue
        new_id = db.add_store_tag(
            {
                "name": name,
                "color": tag["color"],
                "priority": tag["priority"],
                "display_order": tag["display_order"],
                "is_active": 1,
            }
        )
        existing_ids[name] = int(new_id)
    return {name: existing_ids[name] for name in BRAND_TAG_NAMES if name in existing_ids}


def brand_tag_id_set(db) -> Set[int]:
    mapping = ensure_brand_store_tags(db)
    return set(mapping.values())


def quality_tag_id_set(db) -> Set[int]:
    ids: Set[int] = set()
    for t in db.list_store_tags(active_only=False):
        if is_quality_tag_name(str(t.get("name") or "")) and t.get("id") is not None:
            ids.add(int(t["id"]))
    return ids


def merge_brand_tag_ids(
    db,
    store_name: str,
    current_tag_ids: Optional[Sequence[int]] = None,
    *,
    replace_existing_brand: bool = False,
    fix_mismatch: bool = False,
    mapping: Optional[Dict[str, int]] = None,
) -> List[int]:
    """
    既存タグに店舗種別をマージした ID リストを返す。

    - replace_existing_brand=False: 既に店舗種別が付いていればそのまま
    - fix_mismatch=True: 付いている種別が店名判定と違うときだけ付け直す
      （例: ホビーオフ／オフハウスが「その他」のまま → ハードオフ系）
    - replace_existing_brand=True: 常に判定結果で付け直す
    """
    mapping = mapping or ensure_brand_store_tags(db)
    brand_ids = set(mapping.values())
    brand_name = detect_brand_tag_name(store_name)
    brand_id = mapping.get(brand_name)
    if brand_id is None:
        return list(dict.fromkeys(int(x) for x in (current_tag_ids or []) if x is not None))

    current: List[int] = []
    seen: Set[int] = set()
    for raw in current_tag_ids or []:
        try:
            tid = int(raw)
        except (TypeError, ValueError):
            continue
        if tid in seen:
            continue
        seen.add(tid)
        current.append(tid)

    current_brand = [tid for tid in current if tid in brand_ids]
    if current_brand and not replace_existing_brand:
        if fix_mismatch and set(current_brand) != {int(brand_id)}:
            pass  # 付け直しへ進む
        else:
            return current

    kept = [tid for tid in current if tid not in brand_ids]
    kept.append(int(brand_id))
    return kept


def apply_brand_tag_to_store(
    db,
    store_id: int,
    store_name: str,
    *,
    replace_existing_brand: bool = False,
    fix_mismatch: bool = False,
    mapping: Optional[Dict[str, int]] = None,
) -> Optional[str]:
    """1店舗に店舗種別タグを付与。付与したタグ名を返す（変更なしなら None）。"""
    mapping = mapping or ensure_brand_store_tags(db)
    before = set(db.get_store_tag_ids(int(store_id)))
    after = merge_brand_tag_ids(
        db,
        store_name,
        list(before),
        replace_existing_brand=replace_existing_brand,
        fix_mismatch=fix_mismatch,
        mapping=mapping,
    )
    if set(after) == before:
        return None
    db.set_store_tag_ids(int(store_id), after)
    return detect_brand_tag_name(store_name)


def apply_brand_tags_to_all_stores(
    db,
    *,
    replace_existing_brand: bool = False,
    fix_mismatch: bool = True,
    progress_callback: Optional[Callable[[int, int, str], bool]] = None,
) -> Dict[str, int]:
    """全店舗へ店舗種別タグを自動付与（リンクは一括読込して高速化）。"""
    mapping = ensure_brand_store_tags(db)
    brand_ids = set(mapping.values())
    stores = db.list_stores()

    links_by_store: Dict[int, List[int]] = {}
    try:
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT store_id, tag_id FROM store_tag_links")
        for row in cursor.fetchall():
            links_by_store.setdefault(int(row[0]), []).append(int(row[1]))
    except Exception:
        links_by_store = {}

    updated = 0
    skipped = 0
    for i, store in enumerate(stores):
        name = str(store.get("store_name") or "")
        if progress_callback is not None:
            if progress_callback(i, len(stores), name) is False:
                break
        sid = store.get("id")
        if sid is None:
            skipped += 1
            continue
        sid_i = int(sid)
        current = list(links_by_store.get(sid_i, []))
        after = merge_brand_tag_ids(
            db,
            name,
            current,
            replace_existing_brand=replace_existing_brand,
            fix_mismatch=fix_mismatch,
            mapping=mapping,
        )
        if set(after) == set(current):
            skipped += 1
            continue
        if db.set_store_tag_ids(sid_i, after):
            links_by_store[sid_i] = list(after)
            updated += 1
        else:
            skipped += 1
    if progress_callback is not None:
        progress_callback(len(stores), len(stores), "完了")
    return {"scanned": len(stores), "updated": updated, "skipped": skipped}
