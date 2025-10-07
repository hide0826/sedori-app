from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from python.services.repricer_weekly import apply_repricing_rules, RepriceOutputs
from python.core.config import CONFIG_PATH
from python.core.csv_utils import normalize_string_for_cp932
import pandas as pd
from datetime import datetime
import io
import json
from typing import Optional, Dict, List, Tuple
import numpy as np
import base64
import csv

# Constants
ENCODINGS = ['cp932', 'utf-8', 'latin1']
NUMERIC_COLUMNS = ['price', 'priceTrace', 'number', 'cost', 'akaji', 'takane',
                   'leadtime', 'amazon-fee', 'shipping-price', 'profit']
REQUIRED_COLUMNS = ['SKU', 'price', 'akaji']
PRISTER_COLUMNS = [
    'SKU', 'ASIN', 'title', 'number', 'price', 'cost', 'akaji', 'takane',
    'condition', 'conditionNote', 'priceTrace', 'leadtime', 'amazon-fee',
    'shipping-price', 'profit', 'add-delete'
]


def _detect_encoding(contents: bytes) -> Tuple[str, str]:
    """
    CSVのエンコーディングを自動判定する。

    Args:
        contents: CSVファイルのバイト列

    Returns:
        (デコードされたテキスト, 検出されたエンコーディング)

    Raises:
        HTTPException: すべてのエンコーディングで失敗した場合
    """
    for encoding in ENCODINGS:
        try:
            text = contents.decode(encoding)
            return text, encoding
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=400,
        detail=f"Failed to decode CSV. Tried encodings: {', '.join(ENCODINGS)}"
    )


def _normalize_excel_formula(value: str) -> str:
    """
    Excel数式記法を除去する。

    Args:
        value: 元の文字列

    Returns:
        正規化された文字列
    """
    value = value.strip()
    if value.startswith('="') and value.endswith('"'):
        return value[2:-1]
    elif value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    elif value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _build_sku_update_map(updated_df: pd.DataFrame) -> Dict[str, pd.Series]:
    """
    SKUをキーとした更新データのマップを構築する。

    Args:
        updated_df: 更新後のDataFrame

    Returns:
        SKU → 行データのマップ
    """
    updates_by_sku = {}
    for _, row in updated_df.iterrows():
        sku = _normalize_excel_formula(str(row['SKU']))
        updates_by_sku[sku] = row
    return updates_by_sku


def _should_skip_empty_to_zero(original_value: str, new_value) -> bool:
    """
    空欄から0への変更をスキップすべきか判定する。

    Args:
        original_value: 元の値
        new_value: 新しい値

    Returns:
        スキップすべき場合True
    """
    is_originally_empty = original_value in ('', '""')
    is_new_zero = new_value in (0, 0.0, '0', '0.0')
    return is_originally_empty and is_new_zero


def _update_numeric_cells(cells: List[str], headers: List[str],
                          updated_row: pd.Series, numeric_indices: Dict[str, int]) -> None:
    """
    セル配列の数値列を更新する（インプレース）。

    Args:
        cells: セル配列
        headers: ヘッダー配列
        updated_row: 更新データ
        numeric_indices: 数値列のインデックスマップ
    """
    for col_name, col_idx in numeric_indices.items():
        if col_idx >= len(cells) or col_name not in updated_row.index:
            continue

        original_value = cells[col_idx].strip()
        new_value = updated_row[col_name]

        if _should_skip_empty_to_zero(original_value, new_value):
            continue

        if pd.notna(new_value):
            cells[col_idx] = str(new_value)

    # conditionNote をクリア
    try:
        conditionnote_idx = headers.index('conditionNote')
        if conditionnote_idx < len(cells):
            cells[conditionnote_idx] = ''
    except ValueError:
        pass


def _cells_to_csv_line(cells: List[str]) -> str:
    """
    セル配列をCSV行文字列に変換する。

    Args:
        cells: セル配列

    Returns:
        CSV形式の文字列（改行なし）
    """
    output_buffer = io.StringIO()
    writer = csv.writer(output_buffer)
    writer.writerow(cells)
    return output_buffer.getvalue().rstrip('\r\n')


def read_csv_with_encoding_detection(contents: bytes) -> pd.DataFrame:
    """
    エンコーディングを自動判定してCSVを読み込む。

    Args:
        contents: CSVファイルのバイト列

    Returns:
        読み込まれたDataFrame

    Raises:
        HTTPException: 読み込みに失敗した場合
    """
    for encoding in ENCODINGS:
        try:
            df = pd.read_csv(io.BytesIO(contents), encoding=encoding)
            if 'SKU' in df.columns:
                return df
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise HTTPException(
        status_code=400,
        detail=f"Failed to decode CSV. Tried encodings: {', '.join(ENCODINGS)}"
    )


def merge_numeric_updates_into_original_csv(original_bytes: bytes,
                                            updated_df: pd.DataFrame) -> str:
    """
    元のCSVフォーマットを保持したまま数値列のみを更新する。

    文字列列（title, conditionNote等）は元のバイト列から一切変更せず、
    数値列（price, priceTrace等）のみを置換する。

    Args:
        original_bytes: 元のCSVファイルのバイト列
        updated_df: 数値が更新されたDataFrame

    Returns:
        Base64エンコードされたCP932形式のCSV文字列
    """
    # エンコーディング検出とデコード
    original_text, detected_encoding = _detect_encoding(original_bytes)
    original_lines = original_text.splitlines()

    if not original_lines:
        return updated_df.to_csv(index=False, encoding='cp932', errors='replace')

    # ヘッダー解析
    header_line = original_lines[0]
    headers = next(csv.reader([header_line]))
    headers = [h.strip() for h in headers]

    try:
        sku_idx = headers.index('SKU')
    except ValueError:
        return updated_df.to_csv(index=False, encoding='cp932', errors='replace')

    # 数値列インデックスマップ構築
    numeric_indices = {}
    for col in NUMERIC_COLUMNS:
        try:
            numeric_indices[col] = headers.index(col)
        except ValueError:
            pass

    # SKU更新マップ構築
    updates_by_sku = _build_sku_update_map(updated_df)

    # 出力行構築
    output_lines = [header_line]

    for line in original_lines[1:]:
        if not line.strip():
            continue

        cells = next(csv.reader([line]))

        if len(cells) <= sku_idx:
            output_lines.append(line)
            continue

        # SKU取得と正規化
        original_sku = _normalize_excel_formula(cells[sku_idx])

        # 更新処理
        if original_sku in updates_by_sku:
            updated_row = updates_by_sku[original_sku]
            _update_numeric_cells(cells, headers, updated_row, numeric_indices)
            output_lines.append(_cells_to_csv_line(cells))
        else:
            output_lines.append(line)

    result = '\n'.join(output_lines)

    # CP932バイナリに変換してBase64エンコード
    try:
        csv_bytes = result.encode('cp932', errors='replace')
        csv_base64 = base64.b64encode(csv_bytes).decode('ascii')
        return csv_base64
    except Exception:
        return result


def clean_for_json(value):
    """
    JSONにシリアライズできないnumpy/pandas値を変換する。

    Args:
        value: 変換対象の値

    Returns:
        JSONシリアライズ可能な値
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


def _format_preview_items(log_df: pd.DataFrame, limit: int = 200) -> List[Dict]:
    """
    プレビューアイテムリストを生成する。

    Args:
        log_df: ログDataFrame
        limit: 最大件数

    Returns:
        プレビューアイテムのリスト
    """
    preview_items = []
    for _, log_row in log_df.head(limit).iterrows():
        item = {
            "sku": log_row.get("sku"),
            "daysSinceListed": log_row.get("days", 0),
            "currentPrice": log_row.get("price", 0),
            "newPrice": log_row.get("new_price", 0),
            "action": log_row.get("action", ""),
            "priceTraceChange": (
                f"{log_row.get('priceTrace', 0)} → {log_row.get('new_priceTrace', 0)}"
                if log_row.get('priceTrace', 0) != log_row.get('new_priceTrace', 0)
                else "変更なし"
            )
        }
        preview_items.append({k: clean_for_json(v) for k, v in item.items()})
    return preview_items


def format_outputs_to_json(outputs: RepriceOutputs,
                           original_csv_bytes: Optional[bytes] = None) -> dict:
    """
    RepriceOutputsをフロントエンド用JSONに変換する。

    Args:
        outputs: 価格改定結果
        original_csv_bytes: 元のCSVバイト列（オプション）

    Returns:
        JSON形式の辞書
    """
    action_counts = {
        k: int(v)
        for k, v in outputs.log_df['action'].value_counts().to_dict().items()
    }

    preview_items = _format_preview_items(outputs.log_df)
    updated_count = sum(
        1 for item in preview_items
        if item['currentPrice'] != item['newPrice']
    )
    total_count = len(outputs.log_df) + len(outputs.excluded_df)

    # CSV出力
    if original_csv_bytes:
        updated_csv_content = merge_numeric_updates_into_original_csv(
            original_csv_bytes, outputs.updated_df
        )
    else:
        updated_csv_content = outputs.updated_df.to_csv(
            index=False, encoding='cp932', errors='replace'
        )

    return {
        "summary": {
            "total": total_count,
            "updated": updated_count,
            "excluded": len(outputs.excluded_df),
            "actionCounts": action_counts,
        },
        "items": preview_items,
        "updatedCsvContent": updated_csv_content,
        "updatedCsvEncoding": "cp932-base64",
        "reportCsvContent": outputs.log_df.to_csv(index=False, encoding='cp932'),
    }


def preprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prister形式CSVの前処理を実行する。

    - Excel数式記法(="value")を除去
    - 数値列を適切な型に変換
    - 必要な列の存在チェック

    Args:
        df: 元のDataFrame

    Returns:
        前処理済みのDataFrame

    Raises:
        ValueError: 必要な列が欠けている場合
    """
    # 必須列チェック
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Required columns missing: {missing_cols}. "
            f"Available: {list(df.columns)}"
        )

    if df.empty:
        raise ValueError("CSV file is empty")

    # Excel数式記法除去
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = (df[col]
                   .astype(str)
                   .str.replace(r'^="', '', regex=True)
                   .str.replace(r'"$', '', regex=True))

    # 数値列変換
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # priceTrace列の初期化（存在しない場合）
    if 'priceTrace' not in df.columns:
        df['priceTrace'] = 0

    # 整数型変換
    if 'priceTrace' in df.columns:
        df['priceTrace'] = df['priceTrace'].astype(int)

    return df


router = APIRouter()


@router.post("/repricer/preview")
async def preview_repricing(file: UploadFile = File(...)):
    """
    CSVファイルをアップロードして価格改定のプレビューを実行する。

    Args:
        file: アップロードされたCSVファイル

    Returns:
        プレビュー結果のJSON

    Raises:
        HTTPException: 処理中にエラーが発生した場合
    """
    try:
        contents = await file.read()
        df = read_csv_with_encoding_detection(contents)
        df = preprocess_dataframe(df)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read or parse CSV file: {e}"
        )

    try:
        outputs = apply_repricing_rules(df, datetime.now())
        return format_outputs_to_json(outputs, original_csv_bytes=contents)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error during repricing preview: {e}"
        )


@router.post("/repricer/apply")
async def apply_repricing(file: UploadFile = File(...)):
    """
    CSVファイルをアップロードして価格改定を適用する。

    Args:
        file: アップロードされたCSVファイル

    Returns:
        適用結果のJSON

    Raises:
        HTTPException: 処理中にエラーが発生した場合
    """
    try:
        contents = await file.read()
        df = read_csv_with_encoding_detection(contents)
        df = preprocess_dataframe(df)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read or parse CSV file: {e}"
        )

    try:
        outputs = apply_repricing_rules(df, datetime.now())
        return format_outputs_to_json(outputs, original_csv_bytes=contents)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error during repricing apply: {e}"
        )


@router.get("/repricer/config")
async def get_repricer_config():
    """
    現在の価格改定ルール設定を取得する。

    Returns:
        設定情報のJSON

    Raises:
        HTTPException: 設定ファイルの読み込みに失敗した場合
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
        raise HTTPException(
            status_code=404,
            detail="Configuration file not found"
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON in configuration file: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading configuration: {e}"
        )


@router.put("/repricer/config")
async def update_repricer_config(request: Request):
    """
    価格改定ルール設定を更新する。

    Args:
        request: 新しい設定を含むリクエスト

    Returns:
        更新結果のJSON

    Raises:
        HTTPException: バリデーションまたは保存に失敗した場合
    """
    try:
        new_config = await request.json()

        # 必須キーバリデーション
        required_keys = [
            "profit_guard_percentage", "excluded_skus",
            "q4_rule_enabled", "reprice_rules"
        ]
        for key in required_keys:
            if key not in new_config:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required key: {key}"
                )

        # reprice_rulesバリデーション
        rules = new_config["reprice_rules"]
        if not isinstance(rules, dict):
            raise HTTPException(
                status_code=400,
                detail="reprice_rules must be a dictionary"
            )

        # 30日間隔キー確認
        expected_keys = [
            "30", "60", "90", "120", "150", "180",
            "210", "240", "270", "300", "330", "360"
        ]
        for key in expected_keys:
            if key not in rules:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing rule for {key} days"
                )

        # 各ルールの形式確認
        valid_actions = [
            "maintain", "priceTrace", "price_down_1",
            "price_down_2", "profit_ignore_down", "exclude"
        ]
        for days_key, rule in rules.items():
            if not isinstance(rule, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Rule for {days_key} days must be a dictionary"
                )
            if "action" not in rule or "priceTrace" not in rule:
                raise HTTPException(
                    status_code=400,
                    detail=f"Rule for {days_key} days must have 'action' and 'priceTrace' keys"
                )
            if rule["action"] not in valid_actions:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid action '{rule['action']}' for {days_key} days"
                )

        # 設定ファイルに保存
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)

        return {
            "success": True,
            "message": "Configuration updated successfully",
            "config": new_config
        }

    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid JSON format: {e}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating configuration: {e}"
        )
