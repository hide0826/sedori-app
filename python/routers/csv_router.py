from fastapi import APIRouter, UploadFile, File
router = APIRouter(prefix="/csv", tags=["csv"])

@router.post("/inspect")
async def inspect(file: UploadFile = File(...)):
    return {"filename": file.filename}

@router.post("/normalize")
async def normalize(file: UploadFile = File(...)):
    return {"normalized": True, "filename": file.filename}
