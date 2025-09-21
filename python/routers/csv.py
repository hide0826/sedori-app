from fastapi import APIRouter, UploadFile, File
from core.csv_utils import read_csv_with_fallback

router = APIRouter(prefix="/csv", tags=["csv"])

@router.post("/inspect")
async def inspect(file: UploadFile = File(...)):
    content = await file.read()
    df = read_csv_with_fallback(content)
    return {"columns": list(df.columns), "rows": int(len(df))}

@router.post("/normalize")
async def normalize(file: UploadFile = File(...)):
    content = await file.read()
    df = read_csv_with_fallback(content)
    # ここで将来の整形処理を追加予定。今はUTF-8で返すのみ。
    out = df.to_csv(index=False, encoding="utf-8-sig")
    return {"ok": True, "normalized_rows": int(len(df))}
