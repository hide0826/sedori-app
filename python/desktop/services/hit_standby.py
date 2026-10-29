#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord 仕入れ候補のスタンバイ（購入台帳・画像スナップショット）を読む。

データは miniPC の `C:\\HIRIO\\shared`（Git 外）。
ネット仕入一覧へ送る行は、単品仕入と同じ列イメージにする。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set


def resolve_hirio_shared_dir() -> Path:
    """shared フォルダを探す（環境変数 → よくあるパス）。"""
    env = (os.getenv("HIRIO_SHARED_DIR") or "").strip()
    if env:
        path = Path(env)
        if path.is_dir():
            return path
    here = Path(__file__).resolve()
    # .../repo/sedori-app.github/python/desktop/services → HIRIO
    for parent in here.parents:
        candidate = parent / "shared"
        if candidate.is_dir() and (candidate / "hit_actions.py").is_file():
            return candidate
        if parent.name.upper() == "HIRIO" and (parent / "shared").is_dir():
            return parent / "shared"
    for root in (Path(r"C:\HIRIO\shared"), Path(r"D:\HIRIO\shared")):
        if root.is_dir():
            return root
    return Path(r"C:\HIRIO\shared")


def purchases_path(shared: Optional[Path] = None) -> Path:
    root = shared or resolve_hirio_shared_dir()
    env = (os.getenv("HIT_PURCHASES_PATH") or "").strip()
    return Path(env) if env else root / "hit_purchases.jsonl"


def imported_path(shared: Optional[Path] = None) -> Path:
    root = shared or resolve_hirio_shared_dir()
    env = (os.getenv("HIT_PURCHASES_IMPORTED_PATH") or "").strip()
    return Path(env) if env else root / "hit_purchases_imported.jsonl"


def snapshots_dir(shared: Optional[Path] = None) -> Path:
    root = shared or resolve_hirio_shared_dir()
    env = (os.getenv("HIT_SNAPSHOTS_DIR") or "").strip()
    return Path(env) if env else root / "hit_snapshots"


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                text = line.strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_imported_tokens(shared: Optional[Path] = None) -> Set[str]:
    tokens: Set[str] = set()
    for row in _iter_jsonl(imported_path(shared)):
        token = str(row.get("token") or "").strip()
        if token:
            tokens.add(token)
    return tokens


def mark_imported(token: str, *, shared: Optional[Path] = None) -> None:
    token = (token or "").strip()
    if not token:
        return
    _append_jsonl(
        imported_path(shared),
        {
            "token": token,
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def _image_abs_paths(row: Dict[str, Any], shared: Optional[Path] = None) -> List[Path]:
    root = snapshots_dir(shared)
    out: List[Path] = []
    for rel in row.get("image_paths") or []:
        text = str(rel or "").replace("\\", "/").strip().lstrip("/")
        if not text:
            continue
        path = root / text
        if path.is_file():
            out.append(path)
            continue
        # token/01.jpg 形式でない場合の保険
        alt = root / Path(text).name
        if alt.is_file():
            out.append(alt)
    return out


def load_standby_items(
    *,
    shared: Optional[Path] = None,
    include_pending: bool = False,
) -> List[Dict[str, Any]]:
    """
    スタンバイ一覧（新しい順）。

    既定は購入入力済みだけ（ネット仕入へ送る対象）。
    include_pending=True のときだけ未購入スナップショットも混ぜる。

    各要素:
      kind: purchased | pending
      token, title, asin, url, buy_yen, sell_yen, ...
      image_files: List[Path]
      imported: bool（ネット仕入へ送済）
      raw: 元レコード
    """
    shared_root = shared or resolve_hirio_shared_dir()
    imported = load_imported_tokens(shared_root)
    items: List[Dict[str, Any]] = []
    seen_tokens: Set[str] = set()

    for row in _iter_jsonl(purchases_path(shared_root)):
        token = str(row.get("token") or "").strip()
        if not token:
            continue
        seen_tokens.add(token)
        items.append(
            {
                "kind": "purchased",
                "token": token,
                "at": str(row.get("at") or ""),
                "action": str(row.get("action") or "purchased"),
                "title": str(row.get("title") or ""),
                "asin": str(row.get("asin") or "").upper(),
                "url": str(row.get("url") or ""),
                "keyword": str(row.get("keyword") or ""),
                "source": str(row.get("source") or ""),
                "buy_yen": _as_int(row.get("buy_yen")),
                "sell_yen": _as_int(row.get("sell_yen")),
                "profit_yen": _as_int(row.get("profit_yen")),
                "margin_rate": _as_float(row.get("margin_rate")),
                "fee_note": str(row.get("fee_note") or row.get("fee_source") or ""),
                "image_files": _image_abs_paths(row, shared_root),
                "imported": token in imported,
                "raw": row,
            }
        )

    if include_pending:
        # 未購入スナップショット（購入台帳に無いもの）
        snap_root = snapshots_dir(shared_root)
        if snap_root.is_dir():
            for child in snap_root.iterdir():
                if not child.is_dir():
                    continue
                token = child.name
                if token in seen_tokens:
                    continue
                meta_path = child / "meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(meta, dict):
                    continue
                if meta.get("kept"):
                    continue
                items.append(
                    {
                        "kind": "pending",
                        "token": token,
                        "at": str(meta.get("notified_at") or ""),
                        "action": "",
                        "title": str(meta.get("title") or ""),
                        "asin": str(meta.get("asin") or "").upper(),
                        "url": str(meta.get("url") or ""),
                        "keyword": str(meta.get("keyword") or ""),
                        "source": str(meta.get("source") or ""),
                        "buy_yen": _as_int(
                            meta.get("buy_default_yen") or meta.get("price_yen")
                        ),
                        "sell_yen": _as_int(meta.get("sell_estimate_yen")),
                        "profit_yen": None,
                        "margin_rate": None,
                        "fee_note": "未購入（Discord通知のスナップショット）",
                        "image_files": _image_abs_paths(meta, shared_root),
                        "imported": False,
                        "raw": meta,
                    }
                )

    items.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    return items


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Discord 購入フォーム Cond. → 仕入一覧の Amazon ラベル
_CONDITION_AMAZON_BY_KEY = {
    "new": "新品(新品)",
    "very_good": "中古(非常に良い)",
    "good": "中古(良い)",
    "acceptable": "中古(可)",
}
_CONDITION_AMAZON_BY_SHORT = {
    "新品": "新品(新品)",
    "非常に良い": "中古(非常に良い)",
    "良い": "中古(良い)",
    "可": "中古(可)",
}
_DEFAULT_CONDITION_AMAZON = "中古(良い)"


def _condition_for_inventory(raw: Dict[str, Any]) -> str:
    """購入台帳の Cond. を仕入一覧用ラベルにする（無ければ従来どおり良い）。"""
    amazon = str(raw.get("condition_amazon") or "").strip()
    if amazon.startswith("中古(") or amazon.startswith("新品") or amazon == "再生品":
        return amazon
    key = str(raw.get("condition") or "").strip().lower().replace("-", "_")
    if key in _CONDITION_AMAZON_BY_KEY:
        return _CONDITION_AMAZON_BY_KEY[key]
    short = str(raw.get("condition_label") or "").strip()
    if short in _CONDITION_AMAZON_BY_SHORT:
        return _CONDITION_AMAZON_BY_SHORT[short]
    if short.startswith("中古(") or short.startswith("新品"):
        return short
    return _DEFAULT_CONDITION_AMAZON


def purchase_to_inventory_row(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    スタンバイ1件 → ネット仕入一覧（出品CSV生成可能）の1行。

    単品仕入の get_row_data と同じ列名を使う。
    """
    # purchase_cost_calc は pandas 依存のため、列名だけここに持つ
    col_platform_fee = "プラットフォーム手数料"
    col_shipping = "出荷費用"
    col_total_cost = "費用合計"

    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    buy = int(item.get("buy_yen") or raw.get("buy_yen") or 0)
    sell = int(item.get("sell_yen") or raw.get("sell_yen") or 0)
    referral = int(raw.get("referral_fee_yen") or 0)
    fba = int(raw.get("fba_fulfillment_yen") or 0)
    inbound = int(raw.get("fba_inbound_shipping_yen") or 0)
    outbound = int(raw.get("outbound_shipping_yen") or 0)
    mode = str(raw.get("fulfillment_mode") or "fba").strip().lower() or "fba"

    amazon_fee = max(0, referral + fba)
    shipping_cost = max(0, inbound if mode != "fbm" else outbound)
    storage_fee = int(raw.get("misc_cost_yen") or 0)
    break_even = buy + amazon_fee + shipping_cost
    total_cost = amazon_fee + shipping_cost
    expected_profit = sell - break_even
    expected_margin = round((expected_profit / sell) * 100, 2) if sell > 0 else 0.0
    expected_roi = round((expected_profit / buy) * 100, 2) if buy > 0 else 0.0

    at = str(item.get("at") or raw.get("at") or "")
    purchase_date = _date_from_iso(at) or datetime.now().strftime("%Y-%m-%d")

    title = str(item.get("title") or raw.get("title") or "").strip()
    asin = str(item.get("asin") or raw.get("asin") or "").strip().upper()
    url = str(item.get("url") or raw.get("url") or "").strip()
    keyword = str(item.get("keyword") or raw.get("keyword") or "").strip()
    source = str(item.get("source") or raw.get("source") or "mercari").strip().lower()
    channel = "メルカリ" if "mercari" in source else ("ヤフオク" if "yahoo" in source else "フリマ")

    action = str(item.get("action") or raw.get("action") or "purchased")
    action_label = "購入" if action == "purchased" else ("入札" if action == "bid" else action)
    comment = f"[Discord監視][フリマ:{channel}][{action_label}]"
    if keyword:
        comment += f"[KW:{keyword}]"
    token = str(item.get("token") or "")
    if token:
        comment += f"[token:{token[:12]}]"

    return {
        "仕入れ日": purchase_date,
        "コンディション": _condition_for_inventory(raw),
        "SKU": "未実装",
        "ASIN": asin,
        "JAN": "",
        "商品名": title,
        "仕入れ個数": 1,
        "仕入れ価格": buy,
        "販売予定価格": sell,
        "見込み利益": expected_profit,
        "損益分岐点": break_even,
        "想定利益率": expected_margin,
        "想定ROI": expected_roi,
        "コメント": comment,
        "発送方法": "FBA" if mode != "fbm" else "自己発送",
        "販売チャネル": "Amazon",
        "仕入チャネル": channel,
        col_platform_fee: amazon_fee if amazon_fee else "",
        col_shipping: shipping_cost if shipping_cost else "",
        col_total_cost: total_cost if total_cost else "",
        "在庫保管手数料": storage_fee,
        "仕入先": f"フリマ:{channel}",
        "プラットフォーム": channel,
        "取引ID": "",
        "ユーザー名": "",
        "出品URL": url,
        "伝票番号": "",
        "受取都道府県": "東京都",
        "価格改定": "ON",
        "コンディション説明": "",
    }


def _date_from_iso(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        # 2026-10-21T21:00:00+09:00
        return text[:10]
    except Exception:
        return ""
