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
        # アマサーチCSV突合で Amazon 登録済みになったものはスタンバイ送信対象外
        if str(row.get("amazon_registered_at") or "").strip():
            seen_tokens.add(token)
            continue
        seen_tokens.add(token)
        ai_status = str(row.get("ai_plan_status") or "").strip().lower()
        if not ai_status:
            if row.get("ai_rule369") and row.get("ai_tp0_yen"):
                ai_status = "done"
            else:
                ai_status = "pending"
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
                "ai_plan_status": ai_status,
                "ai_rule369": str(row.get("ai_rule369") or "").strip(),
                "ai_tp0_yen": _as_int(row.get("ai_tp0_yen")),
                "ai_reason": str(row.get("ai_reason") or "").strip(),
                "ai_source": str(row.get("ai_source") or "").strip(),
                "keepa_notes": str(row.get("keepa_notes") or "").strip(),
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


def normalize_rule369(value: Any, *, default: str = "6") -> str:
    """3 / 6 / 9 のいずれかに正規化（SKUコメント先頭用）。"""
    text = str(value or "").strip().lower()
    if text in ("3", "3p", "4", "3n") or text.startswith("3"):
        return "3"
    if text in ("9", "9p", "10", "9n") or text.startswith("9"):
        return "9"
    if text in ("6", "6p", "7", "6n") or text.startswith("6"):
        return "6"
    return default if default in ("3", "6", "9") else "6"


def purchase_date_yyyy_mm_dd(item: Dict[str, Any]) -> str:
    """購入レコードの日付（YYYY-MM-DD）。"""
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    at = str(item.get("at") or raw.get("at") or "")
    return _date_from_iso(at) or ""


def is_purchase_on_local_date(item: Dict[str, Any], day: Optional[str] = None) -> bool:
    """購入日が指定日（既定はローカル今日）か。"""
    want = (day or datetime.now().strftime("%Y-%m-%d")).strip()[:10]
    got = purchase_date_yyyy_mm_dd(item)
    return bool(want and got == want)


def purchase_to_inventory_row(
    item: Dict[str, Any],
    *,
    rule369: Optional[str] = None,
    tp0: Optional[int] = None,
) -> Dict[str, Any]:
    """
    スタンバイ1件 → ネット仕入一覧（出品CSV生成可能）の1行。

    単品仕入の get_row_data と同じ列名を使う。
    rule369 はコメント先頭に置き、SKU の {rule369} が読めるようにする。
    tp0 は TP0 / tp0 列に載せる（DB保存側が読めば引き継ぐ）。
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

    rule = normalize_rule369(
        rule369
        if rule369 is not None
        else item.get("rule369")
        or raw.get("rule369")
        or raw.get("rule_369")
    )
    tp0_val: Optional[int] = None
    if tp0 is not None:
        try:
            tp0_val = int(tp0)
        except (TypeError, ValueError):
            tp0_val = None
    if tp0_val is None:
        for key in ("tp0", "TP0"):
            raw_tp = item.get(key)
            if raw_tp is None and isinstance(raw, dict):
                raw_tp = raw.get(key)
            try:
                n = int(raw_tp)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if n > 0:
                tp0_val = n
                break
    if tp0_val is None or tp0_val <= 0:
        tp0_val = sell if sell > 0 else None

    def _pick_repricing_raw() -> Any:
        if item.get("repricing_enabled") is not None:
            return item.get("repricing_enabled")
        if item.get("価格改定") is not None:
            return item.get("価格改定")
        if isinstance(raw, dict) and raw.get("repricing_enabled") is not None:
            return raw.get("repricing_enabled")
        if isinstance(raw, dict) and raw.get("価格改定") is not None:
            return raw.get("価格改定")
        return None

    def _pick_ladder_enabled() -> Any:
        if item.get("ladder_enabled") is not None:
            return item.get("ladder_enabled")
        if isinstance(raw, dict) and raw.get("ladder_enabled") is not None:
            return raw.get("ladder_enabled")
        return None

    def _pick_ladder_rules() -> Any:
        if item.get("ladder_rules") is not None:
            return item.get("ladder_rules")
        if isinstance(raw, dict):
            return raw.get("ladder_rules")
        return None

    def _as_on_off(value: Any, *, default_on: bool = True) -> str:
        if value is None or value == "":
            return "ON" if default_on else "OFF"
        text = str(value).strip().lower()
        if text in ("0", "off", "false", "no", "無効"):
            return "OFF"
        if text in ("1", "on", "true", "yes", "有効"):
            return "ON"
        try:
            return "ON" if int(float(text)) else "OFF"
        except (TypeError, ValueError):
            return "ON" if default_on else "OFF"

    def _as_flag01(value: Any, *, default: int = 0) -> int:
        return 1 if _as_on_off(value, default_on=bool(default)) == "ON" else 0

    def _ladder_rules_text(value: Any) -> str:
        if value is None or value == "":
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                return ""
        return str(value)

    repricing_label = _as_on_off(_pick_repricing_raw(), default_on=True)
    ladder_on = _as_flag01(_pick_ladder_enabled(), default=0)
    ladder_rules_text = _ladder_rules_text(_pick_ladder_rules()) if ladder_on else ""

    comment = f"{rule} [監視][フリマ:{channel}][{action_label}]"
    if keyword:
        comment += f"[KW:{keyword}]"
    token = str(item.get("token") or "")
    if token:
        comment += f"[token:{token[:12]}]"
    if tp0_val:
        comment += f"[TP0:{tp0_val}]"
    if ladder_on:
        comment += "[月別ON]"

    row: Dict[str, Any] = {
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
        "価格改定": repricing_label,
        "repricing_enabled": 1 if repricing_label == "ON" else 0,
        "ladder_enabled": ladder_on,
        "ladder_rules": ladder_rules_text,
        "コンディション説明": str(raw.get("condition_note") or "").strip(),
        "3-6-9": rule,
        "TP0": tp0_val if tp0_val else "",
        "tp0": tp0_val if tp0_val else "",
    }
    return row


def _date_from_iso(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        # 2026-10-21T21:00:00+09:00
        return text[:10]
    except Exception:
        return ""
