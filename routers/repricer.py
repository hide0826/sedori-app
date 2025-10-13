from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from python.services.repricer_weekly import apply_repricing_rules, RepriceOutputs
from python.core.config import CONFIG_PATH
from python.core.csv_utils import normalize_string_for_cp932
import pandas as pd
from datetime import datetime
import io
import json
from typing import Tuple, Dict, Any
import numpy as np
import math
import base64
import csv

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

def merge_numeric_updates_into_original_csv(original_bytes: bytes, updated_df: pd.DataFrame) -> str:
    """
    元のCSVバイト列を保持したまま、変更された数値列だけを置換する。
    文字列列（title, conditionNote等）は元のバイト列から一切変更しない。

    Args:
        original_bytes: 元のCSVファイルのバイト列
        updated_df: 数値が更新されたDataFrame

    Returns:
        元のフォーマットを保持したCSV文字列
    """
    print(f"=== DEBUG: merge_numeric_updates_into_original_csv START ===")

    # 元のCSVを行単位で読み込み（エンコーディング自動判定）
    encodings_to_try = ['cp932', 'utf-8', 'latin1']
    original_lines = None
    detected_encoding = None

    for encoding in encodings_to_try:
        try:
            original_text = original_bytes.decode(encoding)
            original_lines = original_text.splitlines()
            detected_encoding = encoding
            print(f"=== DEBUG: Original CSV decoded with {encoding} ===")
            break
        except UnicodeDecodeError:
            continue

    if not original_lines:
        print(f"=== ERROR: Could not decode original CSV ===")
        return updated_df.to_csv(index=False, encoding='cp932', errors='replace')

    # ヘッダー行を取得（csv.readerでダブルクォート対応）
    header_line = original_lines[0]
    headers = next(csv.reader([header_line]))
    headers = [h.strip() for h in headers]

    # SKUの列インデックスを取得
    try:
        sku_idx = headers.index('SKU')
    except ValueError:
        print(f"=== ERROR: SKU column not found in headers ===")
        return updated_df.to_csv(index=False, encoding='cp932', errors='replace')

    # 数値列のインデックスを取得（これらの列だけ更新する）
    numeric_columns = ['price', 'priceTrace', 'number', 'cost', 'akaji', 'takane',
                       'leadtime', 'amazon-fee', 'shipping-price', 'profit']
    numeric_indices = {}
    for col in numeric_columns:
        try:
            numeric_indices[col] = headers.index(col)
        except ValueError:
            pass

    print(f"=== DEBUG: Will update columns at indices: {numeric_indices} ===")

    # updated_df を SKU でインデックス化
    updates_by_sku = {}
    for _, row in updated_df.iterrows():
        sku = str(row['SKU']).strip()
        # Excel数式記法の除去
        if sku.startswith('="') and sku.endswith('"'):
            sku = sku[2:-1]
        updates_by_sku[sku] = row
        print(f"=== DEBUG: Mapped SKU: '{sku}' ===")

    print(f"=== DEBUG: Created updates map for {len(updates_by_sku)} SKUs ===")

    # 出力行を構築
    output_lines = [header_line]  # ヘッダーはそのまま

    for line_num, line in enumerate(original_lines[1:], start=2):
        if not line.strip():
            continue

        # CSVパース（csv.readerでダブルクォート内のカンマを正しく処理）
        cells = next(csv.reader([line]))

        if len(cells) <= sku_idx:
            output_lines.append(line)
            continue

        # SKUを取得して Excel数式記法を除去
        original_sku = cells[sku_idx].strip()
        # パターン1: ="..." 形式
        if original_sku.startswith('="') and original_sku.endswith('"'):
            original_sku = original_sku[2:-1]
        # パターン2: "..." 形式
        elif original_sku.startswith('"') and original_sku.endswith('"'):
            original_sku = original_sku[1:-1]
        # パターン3: '...' 形式
        elif original_sku.startswith("'") and original_sku.endswith("'"):
            original_sku = original_sku[1:-1]

        print(f"=== DEBUG: Line {line_num}: Original SKU='{original_sku}', in map={original_sku in updates_by_sku} ===")

        # 更新データがあるかチェック
        if original_sku in updates_by_sku:
            updated_row = updates_by_sku[original_sku]

            # 数値列だけ置換
            for col_name, col_idx in numeric_indices.items():
                if col_idx < len(cells) and col_name in updated_row.index:
                    original_value = cells[col_idx].strip()
                    new_value = updated_row[col_name]

                    # 元が空欄で、新しい値が0または0.0の場合はスキップ（空欄を保持）
                    if (original_value == '' or original_value == '""') and (new_value == 0 or new_value == 0.0 or new_value == '0' or new_value == '0.0'):
                        print(f"=== DEBUG: Skipped {col_name} (keeping original empty value) ===")
                        continue

                    if pd.notna(new_value):
                        cells[col_idx] = str(new_value)
                        print(f"=== DEBUG: Updated {col_name}={new_value} ===")

            # conditionNote を空白にする
            try:
                conditionnote_idx = headers.index('conditionNote')
                if conditionnote_idx < len(cells):
                    cells[conditionnote_idx] = ''
                    print(f"=== DEBUG: Cleared conditionNote ===")
            except ValueError:
                pass

            # csv.writerで正しくエスケープして出力
            output_buffer = io.StringIO()
            writer = csv.writer(output_buffer)
            writer.writerow(cells)
            output_lines.append(output_buffer.getvalue().rstrip('\r\n'))
            print(f"=== DEBUG: Updated line appended ===")
        elif not line.strip():
            # 空行はスキップ
            continue
        else:
            # 更新データがない行はそのまま
            output_lines.append(line)

    result = '\n'.join(output_lines)
    print(f"=== DEBUG: merge_numeric_updates_into_original_csv COMPLETE ({len(output_lines)} lines) ===")

    # CP932 バイナリに変換して Base64 エンコード
    try:
        # 元のエンコーディング（CP932）でエンコード
        csv_bytes = result.encode('cp932', errors='replace')
        # Base64 エンコード
        csv_base64 = base64.b64encode(csv_bytes).decode('ascii')
        print(f"=== DEBUG: Encoded as CP932 and converted to Base64 ({len(csv_base64)} chars) ===")
        return csv_base64
    except Exception as e:
        print(f"=== ERROR: Failed to encode as CP932: {e} ===")
        # フォールバック: UTF-8文字列をそのまま返す
        return result

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

def format_outputs_to_json(outputs: RepriceOutputs, original_csv_bytes: bytes = None) -> dict:
    """
    RepriceOutputsオブジェクトをフロントエンド用のJSONに変換する。
    Prister形式CSVとの互換性を保つ。
    """
    print(f"\n=== DEBUG: format_outputs_to_json called with original_csv_bytes: {original_csv_bytes is not None} ===")
    if original_csv_bytes:
        print(f"=== DEBUG: original_csv_bytes size: {len(original_csv_bytes)} bytes ===")
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

    # 元ファイルのフォーマットを完全保持して出力（数値だけ変更）
    def format_prister_csv(df):
        """
        元のCSVフォーマットを完全保持したまま、変更が必要な数値だけ更新する。
        - 元のCSVバイト列を保持
        - 文字列列（title, conditionNote等）は一切触らない
        - 数値列（price, priceTrace等）のみ置換
        - エンコーディング: CP932（元ファイルと同じ）
        """
        print(f"=== DEBUG: format_prister_csv - Preserving original format, updating numeric columns only ===")
        print(f"=== DEBUG: DataFrame shape: {df.shape} ===")
        print(f"=== DEBUG: original_csv_bytes is None: {original_csv_bytes is None} ===")
        if original_csv_bytes:
            print(f"=== DEBUG: original_csv_bytes length: {len(original_csv_bytes)} bytes ===")

        # 元のCSVバイト列がある場合は、それをベースに数値だけ更新
        if original_csv_bytes:
            print(f"=== DEBUG: Using original CSV bytes to preserve format ===")
            return merge_numeric_updates_into_original_csv(original_csv_bytes, df)

        # フォールバック: 元のバイト列がない場合は通常出力
        print(f"=== DEBUG: No original bytes, using standard CSV output ===")
        return df.to_csv(index=False, encoding='cp932', errors='replace')

    updated_csv_content = format_prister_csv(outputs.updated_df)

    return {
        "summary": {
            "total": total_count,
            "updated": updated_count,
            "excluded": len(outputs.excluded_df),
            "actionCounts": action_counts,
        },
        "items": preview_items,
        "updatedCsvContent": updated_csv_content,
        "updatedCsvEncoding": "cp932-base64",  # エンコーディング情報を追加
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
        response_json = format_outputs_to_json(outputs, original_csv_bytes=contents)
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
        response_json = format_outputs_to_json(outputs, original_csv_bytes=contents)
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