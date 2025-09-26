from fastapi import APIRouter, UploadFile, File, Body, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Optional, Literal
import pandas as pd
from datetime import datetime
import json
import io, csv, os
import re
from services.repricer_weekly import apply_repricing_rules
from core.config import BASE_DIR
BASE_DIR_TMP = BASE_DIR / "python" / "tmp"
from core.csv_utils import read_csv_with_fallback

# --- Trace蛻励・譛邨ょ沂繧・ｼ・ict/繧ｪ繝悶ず繧ｧ繧ｯ繝井ｸ｡蟇ｾ蠢懶ｼ・---
def _to_snake(camel: str) -> str:
    # priceTraceChange -> price_trace_change
    return re.sub(r'(?<!^)(?=[A-Z])', '_', camel).lower()

def _read_field(obj, camel: str, snake: str | None = None):
    snake = snake or _to_snake(camel)
    try:
        if isinstance(obj, dict):
            return obj.get(camel) if camel in obj else obj.get(snake)
        if hasattr(obj, camel):
            return getattr(obj, camel)
        if hasattr(obj, snake):
            return getattr(obj, snake)
        if hasattr(obj, "model_dump"):  # Pydantic v2
            d = obj.model_dump()
            return d.get(camel) if camel in d else d.get(snake)
        if hasattr(obj, "dict"):  # Pydantic v1
            d = obj.dict()
            return d.get(camel) if camel in d else d.get(snake)
    except Exception:
        pass
    return None

def _write_field(obj, camel: str, value, snake: str | None = None):
    snake = snake or _to_snake(camel)
    try:
        if isinstance(obj, dict):
            obj[camel] = value
            return
        if hasattr(obj, camel):
            setattr(obj, camel, value)
            return
        if hasattr(obj, snake):
            setattr(obj, snake, value)
            return
        if hasattr(obj, "__dict__"):
            obj.__dict__[camel] = value
            return
    except Exception:
        pass

def _fill_price_trace_change_on_items(result: dict | object, trace_label: str = "FBA譛螳牙､"):
    try:
        items = result.get("items") if isinstance(result, dict) else getattr(result, "items", None)
    except Exception:
        pass
        items = None
    if not items:
        print("[TRACE_PATCH] no items")
        return result

    filled = 0
    for it in items:
        try:
            action = _read_field(it, "action")
            val = _read_field(it, "priceTraceChange")
            if action == "priceTrace" and (val is None or str(val).strip() == ""):
                _write_field(it, "priceTraceChange", trace_label)
                filled += 1
        except Exception:
            pass
            continue

    print(f"[TRACE_PATCH] filled={filled} items; label={trace_label}")
    return result
# --- /Trace蛻励・譛邨ょ沂繧・---

# --- audit / csv helpers ---
def _tap(msg: str):
    # BASE_DIR/python/tmp/trace_patch.log に書き込む（失敗しても無視）
    try:
        logp = (BASE_DIR / "python" / "tmp") / "trace_patch.log"
        logp.parent.mkdir(parents=True, exist_ok=True)
        with open(logp, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass

def _get_len(obj, key: str) -> int:
    try:
        v = getattr(obj, key, None)
        if v is None and isinstance(obj, dict):
            v = obj.get(key)
        return int(len(v)) if v is not None else 0
    except Exception:
        return 0
# --- /audit / csv helpers ---
def _rebuild_report_csv_with_trace(items: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["sku", "days", "action", "reason", "price", "new_price", "trace"])
    for it in (items or []):
        rf = _read_field  # 譌｢蟄倥・隱ｭ縺ｿ髢｢謨ｰ繧貞・蛻ｩ逕ｨ
        sku = (rf(it, "sku") or "")
        days = (rf(it, "days") or rf(it, "daysSinceListed") or "")
        action = (rf(it, "action") or "")
        reason = (rf(it, "reason") or "")
        price = (rf(it, "price") or rf(it, "currentPrice") or "")
        new_price = (rf(it, "new_price") or rf(it, "newPrice") or "")
        trace = (rf(it, "priceTraceChange") or rf(it, "price_trace_change") or "")
        w.writerow([sku, days, action, reason, price, new_price, trace])
    return buf.getvalue()
# --- /audit / csv helpers ---

router = APIRouter(prefix="/repricer", tags=["repricer"])

CONFIG_PATH = BASE_DIR / "config" / "reprice_rules.json"

# --- Pydantic Models for Config ---
class RepriceRule(BaseModel):
    days_from: int
    action: Literal[
        "maintain",
        "priceTrace",
        "price_down_1",
        "price_down_2",
        "price_down_3",
        "price_down_4",
        "price_down_ignore",
        "exclude"
    ]
    value: Optional[float] = None

class RepriceConfig(BaseModel):
    profit_guard_percentage: float
    excluded_skus: list[str] = []
    q4_rule_enabled: bool = False
    reprice_rules: list[RepriceRule]
    updated_at: Optional[datetime] = None
# --- Config Endpoints ---
@router.get("/config", response_model=RepriceConfig)
def get_config():
    """Get repricer config"""
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="Config file not found")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

@router.put("/config", response_model=RepriceConfig)
def update_config(config: RepriceConfig = Body(...)):
    """Update repricer config"""
    config.updated_at = datetime.now()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config.dict(), f, indent=2, default=str)
        return config
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config file: {e}")

# --- Repricing Endpoints ---
@router.post("/preview")
async def preview(file: UploadFile = File(...)):
    content = await file.read()
    df = read_csv_with_fallback(content)
    
    outputs = apply_repricing_rules(df, today=datetime.now())

    # ---- safe summary (no-attr errors) ----
    summary = {
        'updated_rows': _get_len(outputs, 'updated_df'),
        'excluded_rows': _get_len(outputs, 'excluded_df'),
        'q4_switched': _get_len(outputs, 'q4_switched_df'),
        'date_unknown': _get_len(outputs, 'date_unknown_df'),
        'log_rows': _get_len(outputs, 'log_df'),
    }
    return summary

@router.post("/apply")
async def apply(file: UploadFile = File(...)):
    content = await file.read()
    df = read_csv_with_fallback(content)
    
    # a) 蜿ｩ縺九ｌ縺溯ｨ倬鹸
    _tap("[HIT] /repricer/apply")

    # 譌｢蟄・
    outputs = apply_repricing_rules(df, today=datetime.now())

    # b) 蜻ｼ縺ｳ蜃ｺ縺礼峩蠕後・逶｣譟ｻ
    try:
        _items = outputs.get("items") if isinstance(outputs, dict) else getattr(outputs, "items", [])
        _blank = 0
        if _items:
            for _it in _items:
                act = _read_field(_it, "action")
                val = _read_field(_it, "priceTraceChange")
                if act == "priceTrace" and (val is None or str(val).strip() == ""):
                    _blank += 1
        _tap(f"[AUDIT] before blank={_blank}, total={len(_items) if _items else 0}")
    except Exception as e:
        _tap(f"[AUDIT] before error={e}")

    # c) 遨ｺ繧貞沂繧√ｋ・・BA譛螳牙､縺ｧ・・    _fill_price_trace_change_on_items(outputs, trace_label="FBA譛螳牙､")

    # d) 蝓九ａ縺溷ｾ後・逶｣譟ｻ
    try:
        _items = outputs.get("items") if isinstance(outputs, dict) else getattr(outputs, "items", [])
        _blank = 0
        if _items:
            for _it in _items:
                act = _read_field(_it, "action")
                val = _read_field(_it, "priceTraceChange")
                if act == "priceTrace" and (val is None or str(val).strip() == ""):
                    _blank += 1
        _tap(f"[AUDIT] after blank={_blank}, total={len(_items) if _items else 0}")
    except Exception as e:
        _tap(f"[AUDIT] after error={e}")

    # e) CSV 繧剃ｸ頑嶌縺榊・逕滓・
    try:
        items = outputs.get("items") if isinstance(outputs, dict) else getattr(outputs, "items", [])
        if items is not None:
            report_csv = _rebuild_report_csv_with_trace(items)
            _tap(f"[TRACE_CSV] rebuilt reportCsvContent rows={len(items) if items else 0}")
    except Exception as e:
        _tap(f"[TRACE_CSV] rebuild skipped: {e}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    updated_path = BASE_DIR_TMP / f"updated_{stamp}.csv"
    excluded_path = BASE_DIR_TMP / f"excluded_{stamp}.csv"
    log_path = BASE_DIR_TMP / f"log_{stamp}.csv"

    # rename priceTrace -> trace


    if "priceTrace" in outputs.updated_df.columns and "trace" not in outputs.updated_df.columns:


        outputs.updated_df = outputs.updated_df.rename(columns={"priceTrace": "trace"})


    outputs.updated_df.to_csv(updated_path, index=False, encoding="utf-8-sig")
    outputs.excluded_df.to_csv(excluded_path, index=False, encoding="utf-8-sig")
    outputs.log_df.to_csv(log_path, index=False, encoding="utf-8-sig")

    return {
        "ok": True,
          "reportCsvContent": report_csv,
        "files": {
            "updated": str(updated_path),
            "excluded": str(excluded_path),
            "log": str(log_path),
        }
    }

@router.post("/debug")
async def debug(file: UploadFile = File(...)):
    """
    SKU譌･莉倩ｧ｣譫舌・繝・ヰ繝・げ逕ｨ繧ｨ繝ｳ繝峨・繧､繝ｳ繝・    譛蛻昴・10莉ｶ縺ｮSKU縺ｫ縺､縺・※隗｣譫千憾豕√ｒ霑斐☆
    """
    content = await file.read()
    df = read_csv_with_fallback(content)

    # 謨ｰ蛟､邉ｻ縺ｮ繧ｫ繝ｩ繝蝙句､画鋤
    for col in ["price", "akaji", "priceTrace"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    today = datetime.now()

    # 譛蛻昴・10莉ｶ繧定ｧ｣譫・    debug_results = []
    for i, row in df.head(10).iterrows():
        sku = row.get('SKU', '')

        # SKU譌･莉倩ｧ｣譫・        parsed_date = parse_listing_date_from_sku(sku)

        # 邨碁℃譌･謨ｰ險育ｮ・        days_since = None
        if parsed_date:
            days_since = (today - parsed_date).days

        # 蛻・｡槫愛螳・        category = "invalid"
        if parsed_date and days_since is not None:
            if days_since > 365:
                category = "long_term"
            elif days_since > 60:
                category = "switched_to_trace"
            elif days_since >= 0:
                category = "updated"
            else:
                category = "future_date"

        debug_results.append({
            "index": int(i),
            "sku": str(sku) if pd.notna(sku) else "",
            "parsed_date": parsed_date.strftime("%Y-%m-%d") if parsed_date else None,
            "days_since": days_since,
            "category": category
        })

    return {
        "total_rows": len(df),
        "debug_sample": debug_results,
        "analysis_date": today.strftime("%Y-%m-%d %H:%M:%S")
    }












