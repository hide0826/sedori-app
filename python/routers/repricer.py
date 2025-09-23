from fastapi import APIRouter, UploadFile, File, Body, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Optional, Literal
import pandas as pd
from datetime import datetime
import json
from services.repricer_weekly import weekly_reprice, parse_listing_date_from_sku
from core.config import TMP_DIR, BASE_DIR
from core.csv_utils import read_csv_with_fallback

router = APIRouter(prefix="/repricer", tags=["repricer"])

CONFIG_PATH = BASE_DIR / "config" / "reprice_rules.json"

# --- Pydantic Models for Config ---
class RepriceRule(BaseModel):
    action: Literal[
        "maintain", 
        "priceTrace", 
        "price_down_1", 
        "price_down_2", 
        "price_down_ignore", 
        "exclude"
    ]
    priceTrace: Optional[int] = Field(None, ge=0, le=5)

class RepriceConfig(BaseModel):
    reprice_rules: Dict[str, RepriceRule]
    updated_at: datetime

# --- Config Endpoints ---
@router.get("/config", response_model=RepriceConfig)
def get_config():
    """現在の価格改定設定を取得"""
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="Config file not found")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

@router.put("/config", response_model=RepriceConfig)
def update_config(config: RepriceConfig = Body(...)):
    """価格改定設定を更新"""
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
    return {
        "updated_rows": int(len(outputs.updated_df)),
        "excluded_rows": int(len(outputs.excluded_df)),
        "q4_switched": int(len(outputs.q4_switched_df)),
        "date_unknown": int(len(outputs.date_unknown_df)),
        "log_rows": int(len(outputs.log_df)),
    }

@router.post("/apply")
async def apply(file: UploadFile = File(...)):
    content = await file.read()
    df = read_csv_with_fallback(content)
    
    outputs = apply_repricing_rules(df, today=datetime.now())

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    updated_path = TMP_DIR / f"updated_{stamp}.csv"
    excluded_path = TMP_DIR / f"excluded_{stamp}.csv"
    log_path = TMP_DIR / f"log_{stamp}.csv"

    outputs.updated_df.to_csv(updated_path, index=False, encoding="utf-8-sig")
    outputs.excluded_df.to_csv(excluded_path, index=False, encoding="utf-8-sig")
    outputs.log_df.to_csv(log_path, index=False, encoding="utf-8-sig")

    return {
        "ok": True,
        "files": {
            "updated": str(updated_path),
            "excluded": str(excluded_path),
            "log": str(log_path),
        }
    }

@router.post("/debug")
async def debug(file: UploadFile = File(...)):
    """
    SKU日付解析のデバッグ用エンドポイント
    最初の10件のSKUについて解析状況を返す
    """
    content = await file.read()
    df = read_csv_with_fallback(content)

    # 数値系のカラム型変換
    for col in ["price", "akaji", "priceTrace"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    today = datetime.now()

    # 最初の10件を解析
    debug_results = []
    for i, row in df.head(10).iterrows():
        sku = row.get('SKU', '')

        # SKU日付解析
        parsed_date = parse_listing_date_from_sku(sku)

        # 経過日数計算
        days_since = None
        if parsed_date:
            days_since = (today - parsed_date).days

        # 分類判定
        category = "invalid"
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
