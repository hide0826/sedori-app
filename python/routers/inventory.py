"""
HIRIO 仕入管理システム
inventory.py

作成日: 2025-10-06
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from services.inventory_service import process_inventory_csv
from schemas.inventory_schemas import (
    SKUGenerationRequest,
    SKUGenerationResponse,
    BulkSKUGenerationRequest,
    BulkSKUGenerationResponse
)
from services.inventory_service import generate_sku, convert_condition, detect_q_tag

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

@router.post("/generate-sku", response_model=SKUGenerationResponse)
async def generate_single_sku(request: SKUGenerationRequest):
    """
    単一商品のSKU生成
    """
    sku = generate_sku(
        request.purchase_date,
        request.condition,
        request.product_name
    )
    
    condition_code = convert_condition(request.condition)
    q_tag = detect_q_tag(request.product_name)
    
    # 連番抽出（SKUから）
    parts = sku.split("-")
    sequence = int(parts[2])
    
    return SKUGenerationResponse(
        sku=sku,
        condition_code=condition_code,
        q_tag=q_tag,
        sequence=sequence
    )


@router.post("/generate-sku-bulk", response_model=BulkSKUGenerationResponse)
async def generate_bulk_sku(request: BulkSKUGenerationRequest):
    """
    一括SKU生成（アップロードされた全商品）
    """
    results = []
    
    for product in request.products:
        try:
            sku = generate_sku(
                product.get("仕入日", ""),
                product.get("コンディション", ""),
                product.get("商品名", "")
            )
            
            result = {
                **product,  # 元データ維持
                "sku": sku,
                "condition_code": convert_condition(product.get("コンディション", "")),
                "q_tag": detect_q_tag(product.get("商品名", ""))
            }
            results.append(result)
            
        except Exception as e:
            # エラー時も元データ保持
            results.append({
                **product,
                "sku": f"ERROR: {str(e)}",
                "condition_code": "",
                "q_tag": ""
            })
    
    return BulkSKUGenerationResponse(
        success=True,
        processed=len(results),
        results=results
    )