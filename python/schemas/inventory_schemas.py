"""
HIRIO 仕入管理システム
inventory_schemas.py

作成日: 2025-10-06
"""
from pydantic import BaseModel
from typing import Optional

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