
from fastapi import APIRouter

router = APIRouter()

@router.get("/csv/placeholder")
def csv_placeholder():
    return {"message": "CSV router is active"}
