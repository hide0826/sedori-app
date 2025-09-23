
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from python.services.repricer_weekly import apply_repricing_rules
from python.core.config import CONFIG_PATH
import pandas as pd
from datetime import datetime
import io
import json

router = APIRouter()

@router.get("/repricer/config")
def get_reprice_config():
    """
    現在の価格改定設定をJSON形式で取得します。
    """
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading config file: {e}")

@router.put("/repricer/config")
async def update_reprice_config(request: Request):
    """
    新しい価格改定設定をJSON形式で更新します。
    """
    try:
        new_config = await request.json()
        # Basic validation
        if "reprice_rules" not in new_config:
            raise HTTPException(status_code=400, detail="Invalid config format: 'reprice_rules' key is missing.")
        
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        return {"message": "Reprice config updated successfully."}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing config file: {e}")


@router.post("/repricer/apply")
async def apply_repricing(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read CSV file: {e}")

    today = datetime.now()
    
    try:
        outputs = apply_repricing_rules(df, today)
        
        # For now, we'll just return a summary.
        # In the future, you might want to return the CSVs.
        return {
            "message": "Repricing applied successfully",
            "summary": {
                "updated_count": len(outputs.updated_df),
                "excluded_count": len(outputs.excluded_df),
                "q4_switched_count": len(outputs.q4_switched_df),
                "date_unknown_count": len(outputs.date_unknown_df),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during repricing: {e}")

