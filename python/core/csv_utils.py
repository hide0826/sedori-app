import pandas as pd
from io import BytesIO
from fastapi import HTTPException

def read_csv_with_fallback(content: bytes) -> pd.DataFrame:
    """
    Reads CSV content with multiple encoding fallbacks.
    Tries cp932, then utf-8, then latin1.
    """
    encodings = ["cp932", "utf-8", "latin1"]
    for encoding in encodings:
        try:
            # on_bad_lines='warn' は問題を警告しつつも処理を継続させる
            df = pd.read_csv(BytesIO(content), encoding=encoding, dtype=str, on_bad_lines='warn')
            return df
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    
    raise HTTPException(
        status_code=400, 
        detail="Failed to decode CSV with cp932, utf-8, and latin1 encodings."
    )
