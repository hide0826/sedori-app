"""
HIRIO 仕入管理システム
inventory_schemas.py

作成日: 2025-10-06
"""
from pydantic import BaseModel
from typing import Optional, List

class InventoryItem(BaseModel):
    """
    仕入リストCSVの1行に対応するPydanticモデル
    """
    purchase_date: Optional[str] = None
    condition: Optional[str] = None
    asin: Optional[str] = None
    jan: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[float] = None
    purchase_price: Optional[float] = None
    planned_price: Optional[float] = None
    expected_profit: Optional[float] = None
    break_even: Optional[float] = None
    comment: Optional[str] = None
    reference_price: Optional[float] = None
    shipping_method: Optional[str] = None
    supplier: Optional[str] = None
    condition_note: Optional[str] = None
    sku: Optional[str] = None
    other_cost: Optional[float] = None

class SKUGenerationRequest(BaseModel):
    """SKU生成リクエスト"""
    purchase_date: str  # "2024-10-07"
    condition: str      # "中古(非常に良い)"
    product_name: str   # 商品名
    
class SKUGenerationResponse(BaseModel):
    """SKU生成レスポンス"""
    sku: str
    condition_code: str
    q_tag: str
    sequence: int

class BulkSKUGenerationRequest(BaseModel):
    """一括SKU生成リクエスト"""
    products: List[dict]  # [{purchase_date, condition, product_name, ...}, ...]

class BulkSKUGenerationResponse(BaseModel):
    """一括SKU生成レスポンス"""
    success: bool
    processed: int
    results: List[dict]  # [{original_data..., sku, condition_code, q_tag}, ...]

class ProcessListingRequest(BaseModel):
    """出品CSV処理リクエスト"""
    products: List[dict]  # SKU生成済み商品データ

class ProcessListingResponse(BaseModel):
    """出品CSV処理レスポンス"""
    success: bool
    listing_count: int
    excluded_count: int
    listing_products: List[dict]
    excluded_products: List[dict]
    message: str