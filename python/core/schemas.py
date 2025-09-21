from pydantic import BaseModel
from typing import Optional, List

class RepricePreviewItem(BaseModel):
    sku: str
    current_price: float
    new_price: float
    reason: Optional[str] = None

class RepricePreviewResponse(BaseModel):
    items: List[RepricePreviewItem]
    notes: Optional[str] = None
