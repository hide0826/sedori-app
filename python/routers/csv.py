from fastapi import APIRouter, UploadFile, File
import pandas as pd
from io import BytesIO

router = APIRouter(prefix="/csv", tags=["csv"])

@router.post("/inspect")
async def inspect(file: UploadFile = File(...)):
    content = await file.read()
    # 文字コード自動判定は後回し。まずはUTF-8想定で読む
    df = pd.read_csv(BytesIO(content), dtype=str)
    return {"columns": list(df.columns), "rows": int(len(df))}

@router.post("/normalize")
async def normalize(file: UploadFile = File(...)):
    content = await file.read()
    try:
        df = pd.read_csv(BytesIO(content), encoding="shift_jis", dtype=str)
    except Exception:
        df = pd.read_csv(BytesIO(content), encoding="utf-8", dtype=str)
    # ここで将来の整形処理を追加予定。今はUTF-8で返すのみ。
    out = df.to_csv(index=False, encoding="utf-8-sig")
    return {"ok": True, "normalized_rows": int(len(df))}
