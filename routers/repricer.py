from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from python.services.repricer_weekly import apply_repricing_rules, RepriceOutputs
from python.core.config import CONFIG_PATH
import pandas as pd
from datetime import datetime
import io
import json
from typing import Tuple, Dict, Any
import numpy as np
import math

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
    Prister形式CSVとの互換性を保つ。
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
            "priceTraceChange": f"{log_row.get('priceTrace', 0)} → {log_row.get('new_priceTrace', 0)}" if log_row.get('priceTrace', 0) != log_row.get('new_priceTrace', 0) else "変更なし"
        }
        sanitized_item = {k: clean_for_json(v) for k, v in item.items()}
        preview_items.append(sanitized_item)

    updated_count = sum(1 for item in preview_items if item['currentPrice'] != item['newPrice'])
    total_count = len(outputs.log_df) + len(outputs.excluded_df)

    # Prister形式を保持したCSV出力を生成
    def format_prister_csv(df):
        """Prister互換形式でCSVを出力"""
        csv_df = df.copy()
        # 文字列フィールドにExcel数式記法を適用
        string_cols = ['SKU', 'ASIN', 'title', 'condition', 'conditionNote', 'add-delete']
        for col in string_cols:
            if col in csv_df.columns:
                csv_df[col] = '="' + csv_df[col].astype(str) + '"'
        return csv_df.to_csv(index=False, encoding='cp932')

    return {
        "summary": {
            "total": total_count,
            "updated": updated_count,
            "excluded": len(outputs.excluded_df),
            "actionCounts": action_counts,
        },
        "items": preview_items,
        "updatedCsvContent": format_prister_csv(outputs.updated_df),
        "reportCsvContent": outputs.log_df.to_csv(index=False, encoding='cp932'),
    }

def preprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prister形式CSV（16列）の前処理を行う。
    Excelの数式記号(="value")を除去し、必要な列を数値型に変換する。
    """
    print("\n--- DataFrame Preprocessing START ---")
    print(f"DataFrame shape: {df.shape}")
    print(f"DataFrame columns: {list(df.columns)}")

    # Prister形式の期待される列
    expected_prister_cols = [
        'SKU', 'ASIN', 'title', 'number', 'price', 'cost', 'akaji', 'takane',
        'condition', 'conditionNote', 'priceTrace', 'leadtime', 'amazon-fee',
        'shipping-price', 'profit', 'add-delete'
    ]

    # 最低限必要な列の存在確認
    required_cols = ['SKU', 'price', 'akaji']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Required columns missing: {missing_cols}. Available columns: {list(df.columns)}")

    # データが空でないことを確認
    if df.empty:
        raise ValueError("CSV file is empty")

    # デバッグ情報出力
    if not df.empty:
        print(f"Sample data before cleaning:")
        for col in ['SKU', 'price', 'akaji', 'priceTrace']:
            if col in df.columns:
                sample_value = df[col].iloc[0]
                print(f"  {col}: '{sample_value}' (type: {type(sample_value)})")

    # DataFrame内の全文字列に対してExcel数式記号除去を試みる
    # Prister形式では ="value" の形式で文字列が格納される
    for col in df.select_dtypes(include=['object']).columns:
        original_series = df[col].copy()
        df[col] = df[col].astype(str).str.replace(r'^="', '', regex=True).str.replace(r'"$', '', regex=True)
        # 変更があった列をログ出力
        if not original_series.equals(df[col]):
            print(f"Excel formula cleaned for column: {col}")

    # 数値列を数値型に変換
    # Prister形式に対応した数値列
    numeric_cols = ['price', 'akaji', 'cost', 'takane', 'priceTrace', 'leadtime', 'amazon-fee', 'shipping-price', 'profit']
    for col in numeric_cols:
        if col in df.columns:
            original_type = df[col].dtype
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            print(f"Converted {col}: {original_type} -> {df[col].dtype}")

    # priceTraceがない場合は0で初期化（古いPristerファイル対応）
    if 'priceTrace' not in df.columns:
        df['priceTrace'] = 0
        print("Added missing priceTrace column with default value 0")

    # 整数型に変換すべき列を処理
    int_cols = ['priceTrace']
    for col in int_cols:
        if col in df.columns:
            df[col] = df[col].astype(int)

    print("\n--- After Preprocessing ---")
    if not df.empty:
        print(f"Sample data after cleaning:")
        for col in ['SKU', 'price', 'akaji', 'priceTrace']:
            if col in df.columns:
                sample_value = df[col].iloc[0]
                print(f"  {col}: '{sample_value}' (type: {type(sample_value)})")

        print("Head of cleaned DataFrame:")
        print(df[['SKU', 'price', 'akaji', 'priceTrace']].head())

    print("--- DataFrame Preprocessing END ---")
    return df

router = APIRouter()


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


@router.get("/repricer/config")
async def get_repricer_config():
    """
    現在の価格改定ルール設定を取得する
    """
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return {
            "success": True,
            "config": config,
            "message": "Configuration loaded successfully"
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Configuration file not found")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in configuration file: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading configuration: {e}")


@router.put("/repricer/config")
async def update_repricer_config(request: Request):
    """
    価格改定ルール設定を更新する
    """
    try:
        new_config = await request.json()

        # 基本的なバリデーション
        required_keys = ["profit_guard_percentage", "excluded_skus", "q4_rule_enabled", "reprice_rules"]
        for key in required_keys:
            if key not in new_config:
                raise HTTPException(status_code=400, detail=f"Missing required key: {key}")

        # reprice_rulesの形式確認
        rules = new_config["reprice_rules"]
        if not isinstance(rules, dict):
            raise HTTPException(status_code=400, detail="reprice_rules must be a dictionary")

        # 30日間隔のキー確認
        expected_keys = ["30", "60", "90", "120", "150", "180", "210", "240", "270", "300", "330", "360"]
        for key in expected_keys:
            if key not in rules:
                raise HTTPException(status_code=400, detail=f"Missing rule for {key} days")

        # 各ルールの形式確認
        valid_actions = ["maintain", "priceTrace", "price_down_1", "price_down_2", "profit_ignore_down", "exclude"]
        for days_key, rule in rules.items():
            if not isinstance(rule, dict):
                raise HTTPException(status_code=400, detail=f"Rule for {days_key} days must be a dictionary")
            if "action" not in rule or "priceTrace" not in rule:
                raise HTTPException(status_code=400, detail=f"Rule for {days_key} days must have 'action' and 'priceTrace' keys")
            if rule["action"] not in valid_actions:
                raise HTTPException(status_code=400, detail=f"Invalid action '{rule['action']}' for {days_key} days")

        # 設定ファイルに保存
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)

        return {
            "success": True,
            "message": "Configuration updated successfully",
            "config": new_config
        }

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating configuration: {e}")