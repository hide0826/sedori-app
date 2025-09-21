from fastapi import APIRouter, UploadFile, File
import pandas as pd
from datetime import datetime
from services.repricer_weekly import weekly_reprice, parse_listing_date_from_sku
from core.config import TMP_DIR
from core.csv_utils import read_csv_with_fallback

router = APIRouter(prefix="/repricer", tags=["repricer"])

@router.post("/preview")
async def preview(file: UploadFile = File(...)):
    content = await file.read()
    df = read_csv_with_fallback(content)
    
    # 数値系のカラム型変換
    for col in ["price", "akaji", "priceTrace"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    outputs = weekly_reprice(df, today=datetime.now())
    return {
        "updated_rows": int(len(outputs.updated_df)),
        "red_list": int(len(outputs.red_list_df)),
        "long_term": int(len(outputs.long_term_df)),
        "switched_to_trace": int(len(outputs.switched_to_trace_df)),
    }

@router.post("/apply")
async def apply(file: UploadFile = File(...)):
    content = await file.read()
    df = read_csv_with_fallback(content)
    
    for col in ["price", "akaji", "priceTrace"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    outputs = weekly_reprice(df, today=datetime.now())

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    updated_path = TMP_DIR / f"updated_{stamp}.csv"
    red_path = TMP_DIR / f"red_{stamp}.csv"
    longterm_path = TMP_DIR / f"longterm_{stamp}.csv"
    switched_path = TMP_DIR / f"switched_{stamp}.csv"

    outputs.updated_df.to_csv(updated_path, index=False, encoding="utf-8-sig")
    outputs.red_list_df.to_csv(red_path, index=False, encoding="utf-8-sig")
    outputs.long_term_df.to_csv(longterm_path, index=False, encoding="utf-8-sig")
    outputs.switched_to_trace_df.to_csv(switched_path, index=False, encoding="utf-8-sig")

    return {
        "ok": True,
        "files": {
            "updated": str(updated_path),
            "red": str(red_path),
            "longterm": str(longterm_path),
            "switched": str(switched_path),
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
