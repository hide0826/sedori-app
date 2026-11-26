#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
スタンバイ用: 3/6/9 ＋ TP0 の AI 提案ヘルパ。

本線は watcher の process_purchase_ai_plans.py（購入後〜届くまで Keepa 本取得→提案を台帳へ）。
ここはフォールバック／単体テスト用。自動で仕入一覧へは送らない。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:
    from services.hit_standby import (
        is_purchase_on_local_date,
        normalize_rule369,
        resolve_hirio_shared_dir,
    )
except ImportError:
    from desktop.services.hit_standby import (  # type: ignore
        is_purchase_on_local_date,
        normalize_rule369,
        resolve_hirio_shared_dir,
    )

_HIRIO_ROOT = Path(r"C:\HIRIO")
_WATCHER_ENV = _HIRIO_ROOT / "watcher" / ".env"
_TARGET_PRODUCTS = _HIRIO_ROOT / "watcher" / "target_products.json"
_LOG_NAME = "standby_ai_plan_log.jsonl"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, _, val = text.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        return


_load_dotenv(_WATCHER_ENV)

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-flash-latest").strip() or "gemini-flash-latest"


@dataclass
class StandbyAiPlan:
    token: str
    asin: str
    title: str
    buy_yen: Optional[int]
    sell_yen: Optional[int]
    rule369: str
    tp0_yen: int
    reason: str
    source: str  # gemini | fallback | ledger | gemini_error
    keepa_notes: str = ""
    at: str = ""
    tp1_yen: int = 0
    tp2_yen: int = 0
    tp3_yen: int = 0
    ai_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def log_path(shared: Optional[Path] = None) -> Path:
    root = shared or resolve_hirio_shared_dir()
    env = (os.getenv("STANDBY_AI_PLAN_LOG") or "").strip()
    return Path(env) if env else root / _LOG_NAME


def append_plan_log(plan: StandbyAiPlan, *, shared: Optional[Path] = None) -> None:
    path = log_path(shared)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = plan.to_dict()
    row["logged_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _lookup_keepa_notes(asin: str) -> str:
    """target_products.json にあれば Keepa 寄りの要約を返す（APIは叩かない）。"""
    asin_u = (asin or "").strip().upper()
    if not asin_u or not _TARGET_PRODUCTS.is_file():
        return ""
    try:
        data = json.loads(_TARGET_PRODUCTS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    products = data if isinstance(data, list) else data.get("products") or data.get("items") or []
    if not isinstance(products, list):
        return ""
    for row in products:
        if not isinstance(row, dict):
            continue
        if str(row.get("asin") or "").strip().upper() != asin_u:
            continue
        bits: List[str] = []
        for key, label in (
            ("used_price", "中古いま"),
            ("used_price_365_avg", "中古365平均"),
            ("used_price_min_365", "中古365最安"),
            ("sales_rank_drops_90", "落ち90"),
            ("sales_rank_drops_30", "落ち30"),
            ("count_used", "中古人数"),
            ("count_used_90_avg", "中古人数90平均"),
        ):
            val = row.get(key)
            if val is None:
                continue
            bits.append(f"{label}={val}")
        title = str(row.get("title") or row.get("product_title") or "").strip()
        if title:
            bits.insert(0, f"台帳名={title[:40]}")
        return " / ".join(bits[:10])
    return ""


def _call_gemini(system: str, user: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未設定（watcher/.env）")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": system + "\n\n" + user}]}],
        "generationConfig": {"temperature": 0.2},
    }
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(
                url,
                params={"key": GEMINI_API_KEY},
                json=body,
                timeout=90,
            )
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(min(2**attempt, 8))
            continue
        if resp.status_code in {429, 500, 502, 503, 504} and attempt < 3:
            time.sleep(min(2**attempt, 8))
            continue
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini 応答に candidates がありません")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        return "\n".join(t for t in texts if t).strip()
    if last_exc:
        raise RuntimeError(str(last_exc)) from last_exc
    return ""


def _parse_ai_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _fallback_plan(item: Dict[str, Any], *, reason: str, keepa_notes: str = "") -> StandbyAiPlan:
    buy = _as_int(item.get("buy_yen"))
    sell = _as_int(item.get("sell_yen")) or 0
    # 粗利が厚い／仕入が安い → 回転寄り(3)、薄い → 慎重(9)、それ以外6
    rule = "6"
    if buy and sell and sell > 0:
        margin = (sell - buy) / sell
        if margin >= 0.45 and buy <= 3000:
            rule = "3"
        elif margin < 0.25:
            rule = "9"
    return StandbyAiPlan(
        token=str(item.get("token") or ""),
        asin=str(item.get("asin") or "").upper(),
        title=str(item.get("title") or ""),
        buy_yen=buy,
        sell_yen=sell or None,
        rule369=rule,
        tp0_yen=sell if sell > 0 else max(buy or 0, 1),
        reason=reason,
        source="fallback",
        keepa_notes=keepa_notes,
        at=str(item.get("at") or ""),
    )


def suggest_plan_for_item(item: Dict[str, Any], *, use_ai: bool = True) -> StandbyAiPlan:
    """1件の 3/6/9＋TP0 提案。失敗時はフォールバック。"""
    asin = str(item.get("asin") or "").strip().upper()
    buy = _as_int(item.get("buy_yen"))
    sell = _as_int(item.get("sell_yen"))
    keepa_notes = _lookup_keepa_notes(asin)
    if not use_ai or not GEMINI_API_KEY:
        return _fallback_plan(
            item,
            reason="AI未使用（キー無しまたは use_ai=False）。販売予定を TP0、ルールは粗利ヒューリスティック。",
            keepa_notes=keepa_notes,
        )

    system = """あなたは Amazon 中古 FBA の価格改定アシスタントです。
HIRIO の 3/6/9 ルールは出品後の回転速度プロファイルです。
- 3: 早めに売り切りたい（回転重視）
- 6: 標準
- 9: 値崩れを避けて長く構える（特殊・維持寄り）
TP0 は出品直後〜約90日帯の目標販売価格（円）です。販売予定に近い値が多いです。

出力は JSON だけ:
{"rule369": "3" または "6" または "9", "tp0_yen": 整数, "reason": "日本語で簡潔"}
"""
    user = {
        "asin": asin,
        "title": str(item.get("title") or "")[:120],
        "buy_yen": buy,
        "sell_yen_planned": sell,
        "condition": (item.get("raw") or {}).get("condition_label")
        if isinstance(item.get("raw"), dict)
        else None,
        "keepa_cache": keepa_notes or None,
    }
    try:
        raw = _call_gemini(system, json.dumps(user, ensure_ascii=False))
        data = _parse_ai_json(raw)
        rule = normalize_rule369(data.get("rule369"), default="6")
        tp0 = _as_int(data.get("tp0_yen")) or sell or buy or 1
        reason = str(data.get("reason") or "").strip() or "AI提案"
        return StandbyAiPlan(
            token=str(item.get("token") or ""),
            asin=asin,
            title=str(item.get("title") or ""),
            buy_yen=buy,
            sell_yen=sell,
            rule369=rule,
            tp0_yen=int(tp0),
            reason=reason,
            source="gemini",
            keepa_notes=keepa_notes,
            at=str(item.get("at") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return _fallback_plan(
            item,
            reason=f"AI失敗のためフォールバック: {exc}",
            keepa_notes=keepa_notes,
        )


def suggest_plans_for_today(
    items: List[Dict[str, Any]],
    *,
    day: Optional[str] = None,
    only_unsent: bool = True,
    use_ai: bool = True,
    write_log: bool = True,
    shared: Optional[Path] = None,
    progress_cb=None,
) -> List[StandbyAiPlan]:
    """
    今日の仕入れ（未送信）へ AI 提案。
    progress_cb(done, total, plan) があれば都度呼ぶ。
    """
    targets: List[Dict[str, Any]] = []
    for item in items:
        if only_unsent and item.get("imported"):
            continue
        if not is_purchase_on_local_date(item, day):
            continue
        if not str(item.get("asin") or "").strip():
            continue
        targets.append(item)

    plans: List[StandbyAiPlan] = []
    total = len(targets)
    for i, item in enumerate(targets, start=1):
        plan = suggest_plan_for_item(item, use_ai=use_ai)
        if write_log:
            append_plan_log(plan, shared=shared)
        plans.append(plan)
        if progress_cb is not None:
            try:
                progress_cb(i, total, plan)
            except Exception:  # noqa: BLE001
                pass
        if use_ai and GEMINI_API_KEY and i < total:
            time.sleep(1.2)
    return plans


def ensure_judgment_on_path() -> None:
    """judgment を import したいとき用（現状は未使用・将来拡張）。"""
    judgment = _HIRIO_ROOT / "judgment"
    text = str(judgment)
    if judgment.is_dir() and text not in sys.path:
        sys.path.insert(0, text)
