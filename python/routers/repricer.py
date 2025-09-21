from fastapi import APIRouter, UploadFile, File
router = APIRouter(prefix="/repricer", tags=["repricer"])

@router.post("/preview")
async def preview(file: UploadFile = File(...)):
    return {"preview": True, "filename": file.filename}

@router.post("/apply")
async def apply(file: UploadFile = File(...)):
    return {"applied": True, "filename": file.filename}
