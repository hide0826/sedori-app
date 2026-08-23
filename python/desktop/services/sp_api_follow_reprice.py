#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同コンディション最安追従（5か月以内は最安揃え、以降は TP へ寄せつつ −100円）。
既存 3-6-9 エンジンとは独立。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

try:
    from services.repricer_common import get_days_since_listed
except ImportError:
    from desktop.services.repricer_common import get_days_since_listed  # type: ignore

try:
    from services.repricer_purchase_db import (
        load_repricing_enabled_map_from_purchase_db,
        load_tp_map_from_purchase_db,
    )
except ImportError:
    from desktop.services.repricer_purchase_db import (  # type: ignore
        load_repricing_enabled_map_from_purchase_db,
        load_tp_map_from_purchase_db,
    )

try:
    from services.sp_api_offers import fetch_min_prices_for_asins, parse_listing_condition_code
except ImportError:
    from desktop.services.sp_api_offers import (  # type: ignore
        fetch_min_prices_for_asins,
        parse_listing_condition_code,
    )

try:
    from services.sp_api_reprice import apply_price_patches, collect_price_patch_targets
except ImportError:
    from desktop.services.sp_api_reprice import (  # type: ignore
        apply_price_patches,
        collect_price_patch_targets,
    )


EARLY_DAYS = 150  # 5か月
MAX_DAYS = 365
CHASE_YEN = 100
DEFAULT_RUNS_PER_DAY = 3


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in ("nan", "none", "-"):
        return default
    try:
        return int(round(float(text)))
    except (TypeError, ValueError):
        return default


def tp_key_for_days(days: int) -> str:
    if days <= 90:
        return "tp0"
    if days <= 180:
        return "tp1"
    if days <= 270:
        return "tp2"
    return "tp3"


def resolve_tp_floor(days: int, tp_row: Optional[Mapping[str, Any]]) -> Optional[int]:
    if not tp_row:
        return None
    key = tp_key_for_days(days)
    val = tp_row.get(key)
    if val is None:
        return None
    n = _to_int(val, 0)
    return n if n > 0 else None


def compute_follow_price(
    *,
    price: int,
    days: int,
    min_same: Optional[int],
    tp_floor: Optional[int],
    chase_yen: int = CHASE_YEN,
    early_days: int = EARLY_DAYS,
    max_days: int = MAX_DAYS,
    runs_per_day: int = DEFAULT_RUNS_PER_DAY,
) -> Dict[str, Any]:
    """
    1 SKU の追従価格を決める（副作用なし）。

    〜150日: 同条件最安に揃える（TP未満にはしない）
    151日〜: TPへ段階接近。自分より安い出品があればその価格-100円（下限はTP）
    """
    price = max(0, int(price or 0))
    days = int(days)
    chase_yen = max(0, int(chase_yen))
    runs = max(1, int(runs_per_day or 1))
    floor = int(tp_floor) if tp_floor is not None and int(tp_floor) > 0 else None

    def _clamp(n: int) -> int:
        n = max(1, int(n))
        if floor is not None:
            n = max(floor, n)
        return n

    if days < 0:
        return {
            "new_price": price,
            "action": "維持",
            "phase": "不明",
            "reason": "出品日がSKUから読めないため維持",
        }

    if days <= early_days:
        phase = f"前半({early_days}日以内)"
        if min_same is None or min_same <= 0:
            return {
                "new_price": price,
                "action": "維持",
                "phase": phase,
                "reason": "同条件最安が取れないため維持",
            }
        target = int(min_same)
        if floor is not None and target < floor:
            return {
                "new_price": _clamp(floor),
                "action": "TP下限",
                "phase": phase,
                "reason": f"最安{target}がTP{floor}未満のためTPで固定",
            }
        if target == price:
            return {
                "new_price": price,
                "action": "維持",
                "phase": phase,
                "reason": f"既に同条件最安({target})",
            }
        return {
            "new_price": _clamp(target),
            "action": "最安揃え",
            "phase": phase,
            "reason": f"同条件最安{target}に揃える",
        }

    # 後半: TPへ寄せ + ライバルより chase_yen 安
    phase = f"後半({early_days}日超)"
    remaining = max(1, int(max_days) - days)
    if floor is None:
        gradual = price
        gradual_note = "TP未設定のため段階下げなし"
    elif price <= floor:
        gradual = price
        gradual_note = f"既にTP{floor}以下のため維持"
    else:
        step = max(1, int(round((price - floor) / remaining / runs)))
        gradual = max(floor, price - step)
        gradual_note = f"TP{floor}へ段階接近({remaining}日/{runs}回, 下げ{step}円)"

    chase = None
    if min_same is not None and min_same > 0 and min_same < price:
        chase = int(min_same) - chase_yen
        if floor is not None:
            chase = max(floor, chase)
        chase = max(1, chase)

    candidates = [gradual]
    notes = [gradual_note]
    if chase is not None:
        candidates.append(chase)
        notes.append(f"ライバル最安{min_same}より{chase_yen}円安={chase}")

    new_price = min(candidates)
    new_price = _clamp(new_price)
    if new_price >= price and (floor is None or price <= floor):
        action = "維持"
    elif chase is not None and new_price == _clamp(chase) and chase < gradual:
        action = "ライバル-100"
    else:
        action = "TP接近"
    return {
        "new_price": new_price,
        "action": action,
        "phase": phase,
        "reason": " / ".join(notes),
    }


def _row_get(row: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    for k in keys:
        v = lower.get(str(k).strip().lower())
        if v not in (None, ""):
            return v
    return None


def build_follow_items_from_listings(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_by_asin: Mapping[str, Optional[int]],
    tp_map: Mapping[str, Mapping[str, Any]],
    enabled_map: Mapping[str, bool],
    today: Optional[datetime] = None,
    chase_yen: int = CHASE_YEN,
    early_days: int = EARLY_DAYS,
    runs_per_day: int = DEFAULT_RUNS_PER_DAY,
    max_items: Optional[int] = None,
) -> Dict[str, Any]:
    """出品行 + 最安マップから改定 items を組み立てる。"""
    now = today or datetime.now()
    items: List[Dict[str, Any]] = []
    skipped = 0
    for row in rows:
        sku = str(_row_get(row, "SKU", "sku") or "").strip()
        if not sku:
            continue
        if enabled_map and enabled_map.get(sku) is False:
            skipped += 1
            continue
        asin = str(_row_get(row, "ASIN", "asin") or "").strip().upper()
        title = str(_row_get(row, "title", "Title") or "")
        price = _to_int(_row_get(row, "price"), 0)
        days = get_days_since_listed(sku, now)
        tp_floor = resolve_tp_floor(days, tp_map.get(sku))
        min_same = min_by_asin.get(asin) if asin else None
        calc = compute_follow_price(
            price=price,
            days=days,
            min_same=min_same,
            tp_floor=tp_floor,
            chase_yen=chase_yen,
            early_days=early_days,
            runs_per_day=runs_per_day,
        )
        items.append(
            {
                "sku": sku,
                "asin": asin,
                "title": title,
                "days": days,
                "price": price,
                "new_price": calc["new_price"],
                "action": calc["action"],
                "reason": calc["reason"],
                "phase": calc["phase"],
                "tp_floor": tp_floor,
                "min_same_condition": min_same,
                "akaji": tp_floor if tp_floor is not None else "",
            }
        )
        if max_items is not None and len(items) >= int(max_items):
            break

    updated = sum(1 for it in items if it["new_price"] != it["price"])
    return {
        "items": items,
        "summary": {
            "updated_rows": updated,
            "total_rows": len(items),
            "skipped_off": skipped,
        },
    }


def run_follow_repricer(
    listings_rows: Sequence[Mapping[str, Any]],
    *,
    client: Optional[Any] = None,
    apply_amazon: bool = False,
    chase_yen: int = CHASE_YEN,
    early_days: int = EARLY_DAYS,
    runs_per_day: int = DEFAULT_RUNS_PER_DAY,
    max_listings: Optional[int] = None,
    patch_max_items: Optional[int] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    出品行に対して最安取得→追従計算（任意で PATCH）。
    """
    rows = list(listings_rows)
    if max_listings is not None:
        rows = rows[: int(max_listings)]
    skus = [str(_row_get(r, "SKU", "sku") or "").strip() for r in rows]
    skus = [s for s in skus if s]
    if on_progress:
        on_progress("仕入DBのTP・改定ON/OFFを読込中…")
    tp_map = load_tp_map_from_purchase_db(skus)
    enabled_map = load_repricing_enabled_map_from_purchase_db(skus)

    specs = []
    for r in rows:
        sku = str(_row_get(r, "SKU", "sku") or "").strip()
        if enabled_map.get(sku) is False:
            continue
        asin = str(_row_get(r, "ASIN", "asin") or "").strip()
        if not asin:
            continue
        specs.append(
            {
                "asin": asin,
                "condition": _row_get(r, "condition", "condition_code"),
            }
        )
    if on_progress:
        on_progress(f"同条件最安を取得中… {len(specs)} ASIN")
    min_by_asin = fetch_min_prices_for_asins(
        specs,
        client=client,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )
    result = build_follow_items_from_listings(
        rows,
        min_by_asin=min_by_asin,
        tp_map=tp_map,
        enabled_map=enabled_map,
        chase_yen=chase_yen,
        early_days=early_days,
        runs_per_day=runs_per_day,
    )
    patch_result = None
    if apply_amazon:
        targets = collect_price_patch_targets(result.get("items") or [])
        if on_progress:
            on_progress(f"Amazonへ価格反映 {len(targets)} 件…")
        if targets:
            patch_result = apply_price_patches(
                targets,
                client=client,
                should_cancel=should_cancel,
                on_progress=on_progress,
                max_items=patch_max_items,
            )
        else:
            patch_result = {
                "success": [],
                "failed": [],
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
            }
    result["patch"] = patch_result
    return result
