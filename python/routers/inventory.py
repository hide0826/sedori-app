"""
HIRIO 仕入管理システム
inventory.py

作成日: 2025-10-06
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, Response
import io

from services.inventory_service import (
    process_inventory_csv,
    generate_sku,
    convert_condition,
    detect_q_tag,
    split_by_comment,
    generate_listing_csv_content
)
from schemas.inventory_schemas import (
    SKUGenerationRequest,
    SKUGenerationResponse,
    BulkSKUGenerationRequest,
    BulkSKUGenerationResponse,
    ProcessListingRequest,
    ProcessListingResponse
)

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


@router.post("/process-listing", response_model=ProcessListingResponse)
async def process_listing(request: ProcessListingRequest):
    """
    出品CSV処理（振り分け + データ返却）
    
    1. コメント欄で振り分け
    2. 統計情報とデータを返却
    3. フロントでCSVダウンロード用
    """
    try:
        # コメント欄振り分け
        listing_products, excluded_products = split_by_comment(request.products)
        
        return ProcessListingResponse(
            success=True,
            listing_count=len(listing_products),
            excluded_count=len(excluded_products),
            listing_products=listing_products,
            excluded_products=excluded_products,
            message=f"出品対象: {len(listing_products)}件、除外: {len(excluded_products)}件"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export-listing-csv")
async def export_listing_csv(request: ProcessListingRequest):
    """
    出品用CSV直接ダウンロード
    
    コメント欄が空の商品のみをCSV出力（Shift-JIS）
    """
    try:
        # コメント欄振り分け
        listing_products, _ = split_by_comment(request.products)
        
        if not listing_products:
            raise HTTPException(status_code=400, detail="出品対象の商品がありません")
        
        # CSV生成
        csv_bytes = generate_listing_csv_content(listing_products)
        
        # StreamingResponse
        return Response(
            content=csv_bytes,
            media_type="application/octet-stream",  # バイナリとして扱う
            headers={
                "Content-Disposition": "attachment; filename=listing.csv"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
