from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from python.services.repricer_weekly import apply_repricing_rules, RepriceOutputs
from python.core.config import CONFIG_PATH
import pandas as pd
from datetime import datetime
import io
import json
from typing import Tuple
import numpy as np

# Priority 1: エンコーディング自動判定ヘルパー関数
def read_csv_with_encoding_detection(contents: bytes) -> pd.DataFrame:
    """
    エンコーディングを自動判定してCSVを読み込む。
    cp932 -> utf-8 -> latin1 の順で試行する。
    """
    encodings_to_try = ['cp932', 'utf-8', 'latin1']
    for encoding in encodings_to_try:
        try:
            df = pd.read_csv(io.BytesIO(contents), encoding=encoding)
            # 最初の列が 'SKU' であることを期待する簡単なチェック
            if 'SKU' in df.columns:
                return df
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise HTTPException(status_code=400, detail="Failed to decode CSV with cp932, utf-8, or latin1 encoding.")

def clean_for_json(value):
    """
    JSONにシリアライズできないnumpy/pandasの値を変換する。
    """
    if pd.isna(value) or value is None:
        return None
    if isinstance(value, (np.int64, np.int32, np.int16, np.int8)):
        return int(value)
    if isinstance(value, (np.float64, np.float32, np.float16)):
        if np.isinf(value) or np.isnan(value):
            return None
        return float(value)
    return value

def format_outputs_to_json(outputs: RepriceOutputs) -> dict:
    """
    RepriceOutputsオブジェクトをフロントエンド用のJSONに変換する。
    """
    print("\n--- Formatting to JSON: First 5 log rows ---")
    print(outputs.log_df.head())
    print("--------------------------------------------\n")

    action_counts = {k: int(v) for k, v in outputs.log_df['action'].value_counts().to_dict().items()}
    
    preview_items = []
    # log_dfには計算結果がすべて含まれている
    for _, log_row in outputs.log_df.head(200).iterrows():
        item = {
            "sku": log_row.get("sku"),
            "daysSinceListed": log_row.get("days", 0),
            "currentPrice": log_row.get("price", 0), # ログに追加した改定前価格
            "newPrice": log_row.get("new_price", 0), # ログに追加した改定後価格
            "action": log_row.get("action", ""),
            "priceTraceChange": "" # ToDo
        }
        sanitized_item = {k: clean_for_json(v) for k, v in item.items()}
        preview_items.append(sanitized_item)

    updated_count = sum(1 for item in preview_items if item['currentPrice'] != item['newPrice'])
    total_count = len(outputs.log_df) + len(outputs.excluded_df)


    return {
        "summary": {
            "total": total_count,
            "updated": updated_count,
            "excluded": len(outputs.excluded_df),
            "actionCounts": action_counts,
        },
        "items": preview_items,
        "updatedCsvContent": outputs.updated_df.to_csv(index=False, encoding='cp932'),
        "reportCsvContent": outputs.log_df.to_csv(index=False, encoding='cp932'),
    }

def preprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Excelの数式記号を除去し、数値列を変換する前処理を行う。
    """
    print("\n--- DataFrame Preprocessing START ---")
    if not df.empty:
        print(f"Before SKU cleaning: {df['SKU'].iloc[0]}")
        print(f"Before price conversion: {df['price'].iloc[0]} (type: {type(df['price'].iloc[0])})")

    # DataFrame内の全文字列に対してExcel数式記号除去を試みる
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].astype(str).str.replace('^="', '', regex=True).str.replace('"$', '', regex=True)

    # 数値列を数値型に変換
    numeric_cols = ['price', 'akaji', 'cost']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    print("\n--- After Preprocessing ---")
    if not df.empty:
        print(f"After SKU cleaning: {df['SKU'].iloc[0]}")
        print(f"After price conversion: {df['price'].iloc[0]} (type: {type(df['price'].iloc[0])})")
    print("Head of cleaned DataFrame:")
    print(df.head())
    print("--- DataFrame Preprocessing END ---")
    return df

router = APIRouter()

@router.get("/repricer/config")
def get_reprice_config():
    """
    現在の価格改定設定をJSON形式で取得します。
    フロントエンドが期待する辞書形式に変換して返す。
    """
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # フロントエンドが期待する辞書形式 { "30": {...}, "60": {...} } に変換
        if isinstance(config.get("reprice_rules"), list):
            rules_dict = {str(rule["days_from"]): rule for rule in config["reprice_rules"]}
            config["reprice_rules"] = rules_dict
            
        return config
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading or processing config file: {e}")

@router.put("/repricer/config")
async def update_reprice_config(request: Request):
    """
    新しい価格改定設定をJSON形式で更新します。
    フロントエンドから送られてくる辞書形式のルールを、内部でリスト形式に変換して保存します。
    """
    try:
        new_config = await request.json()
        
        print("\n--- UPDATE CONFIG: RECEIVED DATA ---")
        print(json.dumps(new_config, indent=2, ensure_ascii=False))
        print("------------------------------------")

        # フロントエンドから送られてくる辞書形式のルールをリスト形式に変換
        if "reprice_rules" in new_config and isinstance(new_config["reprice_rules"], dict):
            print("--- UPDATE CONFIG: Converting rules from dict to list ---")
            rules_list = []
            # "days_from"キーを元に数値でソート
            sorted_days = sorted(new_config["reprice_rules"].keys(), key=int)
            
            for days_from_str in sorted_days:
                rule_details = new_config["reprice_rules"][days_from_str]
                # 必要なキーのみを持つ新しい辞書を作成し、不要なキー（例：priceTrace）を排除
                clean_rule = {
                    'days_from': int(days_from_str),
                    'action': rule_details.get('action'),
                    'value': rule_details.get('value')
                }
                rules_list.append(clean_rule)
            new_config["reprice_rules"] = rules_list
            print("--- UPDATE CONFIG: Conversion complete ---")

        print("\n--- UPDATE CONFIG: DATA TO BE SAVED ---")
        print(json.dumps(new_config, indent=2, ensure_ascii=False))
        print("---------------------------------------")

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
            
        return {"message": "Reprice config updated successfully."}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error writing config file: {e}")


@router.post("/repricer/preview")
async def preview_repricing(file: UploadFile = File(...)):
    """
    CSVファイルをアップロードして価格改定のプレビューを実行する。
    """
    print("\n--- PREVIEW ENDPOINT CALLED ---")
    try:
        contents = await file.read()
        df = read_csv_with_encoding_detection(contents)
        original_df = df.copy()
        df = preprocess_dataframe(df)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read or parse CSV file: {e}")

    today = datetime.now()
    
    try:
        outputs = apply_repricing_rules(df, today)
        response_json = format_outputs_to_json(outputs)
        return response_json
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error during repricing preview: {e}")


@router.post("/repricer/apply")
async def apply_repricing(file: UploadFile = File(...)):
    """
    CSVファイルをアップロードして価格改定を適用する。
    """
    try:
        contents = await file.read()
        df = read_csv_with_encoding_detection(contents)
        original_df = df.copy()
        df = preprocess_dataframe(df)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read or parse CSV file: {e}")

    today = datetime.now()
    
    try:
        outputs = apply_repricing_rules(df, today)
        response_json = format_outputs_to_json(outputs)
        return response_json
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error during repricing apply: {e}")