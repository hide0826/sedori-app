#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
併記店舗名（ハードオフ・オフハウス など）をブランドごとに分離する。

例:
  ハードオフ・オフハウス久喜店
    → ハードオフ久喜店 / オフハウス久喜店

- 元店舗は代表ブランド（HA→HO→OF 優先）にリネーム＋コード再採番
- 他ブランドは新規店舗として追加（未所属）
- 緯度経度は元店舗を流用
- 住所・電話は Google Places で再取得（失敗時は元の値をコピー）
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

FetchInfoFn = Callable[[str], Optional[Dict[str, Any]]]

# 検出順（長い名称を先に）
BRAND_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("ハードオフ", "HA"),
    ("ホビーオフ", "HO"),
    ("オフハウス", "OF"),
    ("HARD OFF", "HA"),
    ("HOBBY OFF", "HO"),
    ("OFF HOUSE", "OF"),
    ("HARDOFF", "HA"),
    ("HOBBYOFF", "HO"),
    ("OFFHOUSE", "OF"),
)

BRAND_LABEL = {
    "HA": "ハードオフ",
    "HO": "ホビーオフ",
    "OF": "オフハウス",
}

BRAND_PRIORITY = {"HA": 0, "HO": 1, "OF": 2}

SEP_RE = re.compile(r"[・･/／|｜]+")


@dataclass
class SplitBrandPlan:
    brand: str  # HA/HO/OF
    store_name: str
    store_code: str = ""


@dataclass
class CombinedSplitPlan:
    source_store: Dict[str, Any]
    brands: List[SplitBrandPlan] = field(default_factory=list)
    location_suffix: str = ""

    @property
    def is_splittable(self) -> bool:
        return len(self.brands) >= 2


@dataclass
class CombinedSplitResult:
    scanned: int = 0
    split_count: int = 0
    created: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    created_ids: List[int] = field(default_factory=list)
    updated_ids: List[int] = field(default_factory=list)

    @property
    def affected_ids(self) -> List[int]:
        seen = set()
        out: List[int] = []
        for sid in list(self.updated_ids) + list(self.created_ids):
            try:
                i = int(sid)
            except (TypeError, ValueError):
                continue
            if i and i not in seen:
                seen.add(i)
                out.append(i)
        return out


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", (s or "").strip())


def detect_combined_brands(store_name: str) -> List[str]:
    """店舗名に含まれる HA/HO/OF ブランドコードを優先順で返す。"""
    name = _norm(store_name)
    if not name:
        return []
    upper = name.upper()
    found: Dict[str, int] = {}
    for pattern, brand in BRAND_PATTERNS:
        if pattern.upper() in upper or pattern in name:
            found[brand] = BRAND_PRIORITY.get(brand, 99)
    return [b for b, _ in sorted(found.items(), key=lambda x: x[1])]


def extract_location_suffix(store_name: str) -> str:
    """ブランド名と区切りを除いた地名部分（例: 久喜店 / 杉戸店）。"""
    name = _norm(store_name)
    for pattern, _brand in BRAND_PATTERNS:
        name = re.sub(re.escape(pattern), " ", name, flags=re.IGNORECASE)
    name = SEP_RE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def build_split_names(store_name: str) -> Optional[CombinedSplitPlan]:
    """分離プランを作成。分離不可なら None。"""
    raw = _norm(store_name)
    brands = detect_combined_brands(raw)
    if len(brands) < 2:
        return None

    # 区切り or 「ハードオフ…オフハウス」の併記パターンが必要
    has_sep = bool(SEP_RE.search(raw))
    has_pair = bool(
        re.search(
            r"ハードオフ.*(オフハウス|ホビーオフ)|ホビーオフ.*オフハウス|"
            r"HARD\s*OFF.*(OFF\s*HOUSE|HOBBY\s*OFF)",
            raw,
            flags=re.IGNORECASE,
        )
    )
    if not has_sep and not has_pair:
        return None

    location = extract_location_suffix(raw)
    # 元名が「ブランド 地名」のようにスペースを含むならスペース付きで生成
    use_space = bool(re.search(r"(ハウス|オフ)\s+\S", raw))

    plans: List[SplitBrandPlan] = []
    for brand in brands:
        label = BRAND_LABEL[brand]
        if not location:
            new_name = label
        elif use_space:
            new_name = f"{label} {location}".strip()
        else:
            new_name = f"{label}{location}".strip()
        new_name = re.sub(r"\s+", " ", new_name).strip()
        plans.append(SplitBrandPlan(brand=brand, store_name=new_name))

    return CombinedSplitPlan(
        source_store={},
        brands=plans,
        location_suffix=location,
    )


def find_combined_unassigned_stores(db) -> List[Dict[str, Any]]:
    stores = db.list_stores()
    out = []
    for store in stores:
        aff = (store.get("affiliated_route_name") or "").strip()
        if aff:
            continue
        plan = build_split_names(str(store.get("store_name") or ""))
        if plan and plan.is_splittable:
            out.append(store)
    return out


def _normalize_name_key(name: str) -> str:
    s = _norm(name).lower()
    return re.sub(r"[\s\u3000]+", "", s)


def _existing_by_name(db) -> Dict[str, Dict[str, Any]]:
    mapping = {}
    for store in db.list_stores():
        key = _normalize_name_key(str(store.get("store_name") or ""))
        if key:
            mapping[key] = store
    return mapping


def _assign_code(db, store_name: str, brand: Optional[str] = None) -> str:
    code = db.get_next_store_code_from_store_name(store_name)
    if code:
        return code
    # マッピング未整備でも HA/HO/OF はプレフィックスで採番
    if brand in BRAND_LABEL:
        code = db.get_next_store_code_for_prefix(brand)
        if code:
            return code
    default_prefix = db.find_default_chain_code_for_others()
    if default_prefix:
        code = db.get_next_store_code_for_prefix(default_prefix)
        if code:
            return code
    return ""


def split_combined_store(
    db,
    store: Dict[str, Any],
    *,
    fetch_info: Optional[FetchInfoFn] = None,
    dry_run: bool = False,
) -> CombinedSplitResult:
    """1店舗を分離する。"""
    result = CombinedSplitResult(scanned=1)
    name = str(store.get("store_name") or "")
    plan = build_split_names(name)
    if not plan or not plan.is_splittable:
        result.skipped.append(f"{name}: 分離対象外")
        return result

    plan.source_store = store
    existing = _existing_by_name(db)
    source_id = int(store.get("id") or 0)
    if not source_id:
        result.failed.append(f"{name}: ID不正")
        return result

    lat = store.get("latitude")
    lng = store.get("longitude")
    old_code = store.get("store_code") or store.get("supplier_code") or ""

    # 代表 = 優先度最高（リスト先頭）
    primary = plan.brands[0]
    others = plan.brands[1:]

    old_prefix = ""
    if old_code and "-" in str(old_code):
        old_prefix = str(old_code).split("-", 1)[0].strip().upper()
    elif old_code:
        old_prefix = re.sub(r"[^A-Z]", "", str(old_code).upper())[:2]

    if not dry_run:
        if primary.brand == old_prefix and old_code:
            primary.store_code = str(old_code)
        else:
            primary.store_code = _assign_code(db, primary.store_name, primary.brand)
    else:
        primary.store_code = str(old_code) if primary.brand == old_prefix and old_code else "(自動)"
        for bp in others:
            bp.store_code = "(自動)"

    if dry_run:
        result.split_count = 1
        result.updated.append(
            f"{name} → {primary.store_name} [{primary.store_code or old_code}]"
        )
        for bp in others:
            result.created.append(f"{bp.store_name} [{bp.store_code}]")
        return result

    try:
        # 1) 元店舗を代表ブランドへ更新
        primary_info = None
        if fetch_info:
            try:
                primary_info = fetch_info(primary.store_name)
            except Exception:
                primary_info = None

        update_data: Dict[str, Any] = {
            "store_name": primary.store_name,
            "store_code": primary.store_code or old_code,
            "affiliated_route_name": None,
            "route_code": None,
        }
        if primary_info:
            if primary_info.get("address"):
                update_data["address"] = primary_info.get("address")
            if primary_info.get("phone"):
                update_data["phone"] = primary_info.get("phone")
        # 緯度経度は維持（明示セット）
        if lat is not None and lng is not None:
            update_data["latitude"] = lat
            update_data["longitude"] = lng

        if not db.update_store(source_id, update_data):
            result.failed.append(f"{name}: 代表店舗の更新失敗")
            return result
        result.updated.append(
            f"{name} → {primary.store_name} [{update_data['store_code']}]"
        )
        result.updated_ids.append(source_id)

        # 既存名マップ更新
        existing.pop(_normalize_name_key(name), None)
        existing[_normalize_name_key(primary.store_name)] = {
            "id": source_id,
            "store_name": primary.store_name,
        }

        # 2) 他ブランドを新規追加
        for bp in others:
            key = _normalize_name_key(bp.store_name)
            if key in existing:
                result.skipped.append(
                    f"{bp.store_name}: 同名店舗が既にあるためスキップ"
                )
                continue

            info = None
            if fetch_info:
                try:
                    info = fetch_info(bp.store_name)
                except Exception:
                    info = None

            # 採番は追加直前に再取得（連番ズレ防止）
            code = _assign_code(db, bp.store_name, bp.brand)
            new_data: Dict[str, Any] = {
                "store_name": bp.store_name,
                "store_code": code or None,
                "affiliated_route_name": None,
                "route_code": None,
                "supplier_code": None,
                "address": (info or {}).get("address") or store.get("address") or "",
                "phone": (info or {}).get("phone") or store.get("phone") or "",
                "custom_fields": {},
                "notes": f"併記分離元: {name} (id={source_id})",
            }
            if lat is not None and lng is not None:
                new_data["latitude"] = lat
                new_data["longitude"] = lng

            new_id = db.add_store(new_data)
            existing[key] = {"id": new_id, "store_name": bp.store_name}
            result.created.append(f"{bp.store_name} [{code}]")
            if new_id:
                result.created_ids.append(int(new_id))

        result.split_count = 1
    except Exception as e:
        result.failed.append(f"{name}: {e}")

    return result


def split_all_combined_unassigned(
    db,
    *,
    fetch_info: Optional[FetchInfoFn] = None,
    progress_callback: Optional[Callable[[int, int, str], bool]] = None,
    dry_run: bool = False,
) -> CombinedSplitResult:
    """未所属の併記店舗をすべて分離。"""
    targets = find_combined_unassigned_stores(db)
    total = CombinedSplitResult(scanned=len(targets))
    for i, store in enumerate(targets):
        if progress_callback is not None:
            if progress_callback(i, len(targets), str(store.get("store_name") or "")) is False:
                total.failed.append("途中キャンセル")
                break
        one = split_combined_store(
            db, store, fetch_info=fetch_info, dry_run=dry_run
        )
        total.split_count += one.split_count
        total.created.extend(one.created)
        total.updated.extend(one.updated)
        total.skipped.extend(one.skipped)
        total.failed.extend(one.failed)
        total.created_ids.extend(one.created_ids)
        total.updated_ids.extend(one.updated_ids)
    if progress_callback is not None:
        progress_callback(len(targets), len(targets), "完了")
    return total
