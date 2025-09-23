
from fastapi import APIRouter

router = APIRouter()

@router.get("/ssot/placeholder")
def ssot_placeholder():
    return {"message": "SSOT Rules router is active"}
