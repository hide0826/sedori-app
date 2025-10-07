"""
HIRIO 仕入管理システム
inventory.py

作成日: 2025-10-06
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from services.inventory_service import process_inventory_csv

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

@router.get("/health")
async def health_check():
    """
    仕入管理システムのヘルスチェック
    """
    return {
        "status": "ok",
        "service": "inventory",
        "version": "1.0.0"
    }

@router.post("/upload")
async def upload_inventory_csv(file: UploadFile = File(...)):
    """
    仕入リストCSVをアップロード
    """
    try:
        # ファイル読み込み
        content = await file.read()
        
        # 処理
        df, stats = await process_inventory_csv(content)
        
        # DataFrameをJSON化（先頭10行のみプレビュー）
        preview = df.head(10).to_dict(orient='records')
        
        return {
            "status": "success",
            "stats": stats,
            "preview": preview
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))