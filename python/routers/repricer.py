from fastapi import APIRouter, UploadFile, File
import pandas as pd
from datetime import datetime
from services.repricer_weekly import weekly_reprice
from core.config import TMP_DIR

router = APIRouter(prefix="/repricer", tags=["repricer"])

@router.post("/preview")
async def preview(file: UploadFile = File(...)):
    content = await file.read()
    df = pd.read_csv(
        filepath_or_buffer=bytes(content),
        encoding="utf-8",
        dtype=str
    )
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
    df = pd.read_csv(
        filepath_or_buffer=bytes(content),
        encoding="utf-8",
        dtype=str
    )
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
