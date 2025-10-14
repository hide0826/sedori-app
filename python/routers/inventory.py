"""
HIRIO 仕入管理システム
inventory.py

作成日: 2025-10-06
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, Response
import io

from services.inventory_service import InventoryService
from schemas.inventory_schemas import (
    SKUGenerationRequest,
    SKUGenerationResponse,
    BulkSKUGenerationRequest,
    BulkSKUGenerationResponse,
    ProcessListingRequest,
    ProcessListingResponse
)
# Note: The following imports were removed/handled due to ImportError as they are not
# currently defined or accessible directly from services.inventory_service
# generate_sku, convert_condition, detect_q_tag, split_by_comment, generate_listing_csv_content

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
        df, stats = await InventoryService.process_inventory_csv(content)
        
        # DataFrameをJSON化（先頭10行のみプレビュー）
        preview = df.head(10).to_dict(orient='records')
        
        return {
            "status": "success",
            "stats": stats,
            "preview": preview
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/generate-sku", response_model=SKUGenerationResponse)
async def generate_single_sku(request: SKUGenerationRequest):
    """
    単一商品のSKU生成
    """
    # generate_sku, convert_condition, detect_q_tag functions are not defined in InventoryService
    # Temporarily returning a mock response or handling error.
    raise HTTPException(status_code=500, detail="Single SKU generation not implemented yet or missing dependencies.")


@router.post("/generate-sku-bulk", response_model=BulkSKUGenerationResponse)
async def generate_bulk_sku(request: BulkSKUGenerationRequest):
    """
    一括SKU生成（アップロードされた全商品）
    """
    # Delegate to InventoryService class
    response_data = InventoryService.generate_sku_bulk(request.products)
    return BulkSKUGenerationResponse(**response_data)


@router.post("/process-listing", response_model=ProcessListingResponse)
async def process_listing(request: ProcessListingRequest):
    """
    出品CSV処理（振り分け + データ返却）
    
    1. コメント欄で振り分け
    2. 統計情報とデータを返却
    3. フロントでCSVダウンロード用
    """
    raise HTTPException(status_code=500, detail="Process listing not implemented yet or missing dependencies.")


@router.post("/export-listing-csv")
async def export_listing_csv(request: ProcessListingRequest):
    """
    出品用CSV直接ダウンロード
    
    コメント欄が空の商品のみをCSV出力（Shift-JIS）
    """
    raise HTTPException(status_code=500, detail="Listing CSV generation not implemented yet or missing dependencies.")
