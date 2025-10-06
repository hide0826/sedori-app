"""
HIRIO 仕入管理システム
inventory.py

作成日: 2025-10-06
"""
from fastapi import APIRouter

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