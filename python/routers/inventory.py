"""
HIRIO 仕入管理システム
inventory.py

作成日: 2025-10-06
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Body
from fastapi.responses import StreamingResponse, Response
from typing import Any, Dict, List
import io
import pandas as pd
import math
import json
from pathlib import Path

from services.inventory_service import InventoryService
from desktop.database.route_db import RouteDatabase
from desktop.services.route_matching_service import RouteMatchingService
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

@router.post("/match-stores")
async def match_stores_with_route(
    file: UploadFile = File(...),
    route_summary_id: int = Form(...),
    time_tolerance_minutes: int = Form(30)
):
    """
    仕入CSVの仕入れ日時を参照し、指定ルートの店舗IN/OUTの間にある場合は
    仕入先へ店舗コードを自動付与してプレビューを返却する。
    """
    try:
        content = await file.read()

        # CSV読込・正規化（既存）
        df, stats = await InventoryService.process_inventory_csv(content)

        # 仕入日時カラムの推定
        purchase_date_candidates = ["仕入れ日", "purchaseDate", "purchase_date"]
        purchase_date_col = next((c for c in purchase_date_candidates if c in df.columns), None)
        if not purchase_date_col:
            raise HTTPException(status_code=400, detail="仕入れ日カラムが見つかりません（例: 仕入れ日, purchaseDate）")

        # 仕入先カラム（なければ作成）
        supplier_candidates = ["仕入先", "supplier"]
        supplier_col = next((c for c in supplier_candidates if c in df.columns), None)
        if not supplier_col:
            supplier_col = "仕入先"
            df[supplier_col] = ""

        # ルート訪問詳細
        route_db = RouteDatabase()
        route_summary = route_db.get_route_summary(route_summary_id)
        if not route_summary:
            raise HTTPException(status_code=400, detail="指定ルートが見つかりません")
        
        store_visits = route_db.get_store_visits_by_route(route_summary_id)
        if not store_visits:
            raise HTTPException(status_code=400, detail="指定ルートに店舗訪問詳細がありません")

        # ルート日付を取得して店舗IN/OUT時間に結合（既存データがHH:MM形式の場合）
        route_date = route_summary.get('route_date', '')
        if route_date:
            for visit in store_visits:
                in_time = visit.get('store_in_time', '')
                out_time = visit.get('store_out_time', '')
                
                # HH:MM形式（日付なし）の場合、ルート日付を結合
                if in_time and ':' in in_time and len(in_time.split(' ')) == 1:
                    # すでに日付が含まれていない場合のみ結合
                    visit['store_in_time'] = f"{route_date} {in_time}:00" if ':' in in_time else in_time
                if out_time and ':' in out_time and len(out_time.split(' ')) == 1:
                    # すでに日付が含まれていない場合のみ結合
                    visit['store_out_time'] = f"{route_date} {out_time}:00" if ':' in out_time else out_time

        # 照合
        items = df.to_dict(orient="records")
        matcher = RouteMatchingService()
        matched = matcher.match_store_code_by_time_and_profit(
            purchase_items=items,
            store_visits=store_visits,
            time_tolerance_minutes=time_tolerance_minutes
        )

        # DataFrameへ反映（順序対応）
        # インデックスをリセットして0から始まる連番に保証
        df = df.reset_index(drop=True)
        matched_rows = 0
        for idx, res in enumerate(matched):
            code = res.get("matched_store_code")
            if code:
                # ilocを使うか、リセット済みインデックスを使う
                df.at[idx, supplier_col] = code
                matched_rows += 1

        preview = df.head(10).to_dict(orient="records")
        return {
            "status": "success",
            "stats": {**stats, "matched_rows": matched_rows},
            "preview": preview
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sku-template")
async def get_sku_template_settings():
    """SKUテンプレート設定の取得"""
    try:
        cfg_path = Path(__file__).resolve().parents[2] / "config" / "inventory_settings.json"
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        else:
            data = {
                "skuTemplate": "{date:YYYYMMDD}-{ASIN|JAN}-{supplier}-{seq:3}-{condNum}",
                "seqScope": "day",
                "seqStart": 1
            }
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sku-template")
async def update_sku_template_settings(payload: Dict[str, Any]):
    """SKUテンプレート設定の更新（簡易バリデーション付）"""
    try:
        tpl = str(payload.get("skuTemplate", ""))
        if not tpl:
            raise HTTPException(status_code=400, detail="skuTemplate is required")
        if len(tpl) > 200:
            raise HTTPException(status_code=400, detail="skuTemplate too long")
        if any(ord(c) < 32 for c in tpl):
            raise HTTPException(status_code=400, detail="invalid characters in template")

        cfg_path = Path(__file__).resolve().parents[2] / "config" / "inventory_settings.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({
            "skuTemplate": tpl,
            "seqScope": payload.get("seqScope", "day"),
            "seqStart": int(payload.get("seqStart", 1))
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/match-stores-from-data")
async def match_stores_from_data(
    purchase_data: List[Dict[str, Any]] = Body(...),
    route_summary_id: int = Body(...),
    time_tolerance_minutes: int = Body(30)
):
    """
    仕入データ（JSON）とルートサマリーを照合して店舗コードを自動付与
    CSVファイルではなく、フロントエンドから送信されたJSONデータを処理
    """
    try:
        # JSONデータをDataFrameに変換
        df = pd.DataFrame(purchase_data)
        
        # 仕入日時カラムの推定
        purchase_date_candidates = ["仕入れ日", "purchaseDate", "purchase_date"]
        purchase_date_col = next((c for c in purchase_date_candidates if c in df.columns), None)
        if not purchase_date_col:
            raise HTTPException(status_code=400, detail="仕入れ日カラムが見つかりません")
        
        # 仕入先カラム（なければ作成）
        supplier_candidates = ["仕入先", "supplier"]
        supplier_col = next((c for c in supplier_candidates if c in df.columns), None)
        if not supplier_col:
            supplier_col = "仕入先"
            df[supplier_col] = ""
        
        # ルート訪問詳細取得
        route_db = RouteDatabase()
        route_summary = route_db.get_route_summary(route_summary_id)
        if not route_summary:
            raise HTTPException(status_code=400, detail="指定ルートが見つかりません")
        
        store_visits = route_db.get_store_visits_by_route(route_summary_id)
        if not store_visits:
            raise HTTPException(status_code=400, detail="指定ルートに店舗訪問詳細がありません")
        
        # ルート日付を取得して店舗IN/OUT時間に結合（既存データがHH:MM形式の場合）
        route_date = route_summary.get('route_date', '')
        if route_date:
            for visit in store_visits:
                in_time = visit.get('store_in_time', '')
                out_time = visit.get('store_out_time', '')
                
                # HH:MM形式（日付なし）の場合、ルート日付を結合
                if in_time and ':' in in_time and len(in_time.split(' ')) == 1:
                    # すでに日付が含まれていない場合のみ結合
                    visit['store_in_time'] = f"{route_date} {in_time}:00" if ':' in in_time else in_time
                if out_time and ':' in out_time and len(out_time.split(' ')) == 1:
                    # すでに日付が含まれていない場合のみ結合
                    visit['store_out_time'] = f"{route_date} {out_time}:00" if ':' in out_time else out_time
        
        # 照合処理
        items = df.to_dict(orient="records")
        matcher = RouteMatchingService()
        matched = matcher.match_store_code_by_time_and_profit(
            purchase_items=items,
            store_visits=store_visits,
            time_tolerance_minutes=time_tolerance_minutes
        )
        
        # DataFrameへ反映
        df = df.reset_index(drop=True)
        matched_rows = 0
        for idx, res in enumerate(matched):
            code = res.get("matched_store_code")
            if code:
                df.at[idx, supplier_col] = code
                matched_rows += 1
        
        # 結果をJSON化（全データ）
        # NaN値をNoneに置換してJSONシリアライズ可能にする
        df = df.fillna('')
        result_data = df.to_dict(orient="records")
        
        # NaN値が残っている場合はNoneに置換
        for record in result_data:
            for key, value in record.items():
                if isinstance(value, float) and math.isnan(value):
                    record[key] = None
        
        return {
            "status": "success",
            "stats": {
                "total_rows": len(df),
                "matched_rows": matched_rows
            },
            "data": result_data  # 全データを返却
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
