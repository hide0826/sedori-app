from fastapi import APIRouter, UploadFile, File, Body, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Optional, Literal
import pandas as pd
from datetime import datetime
import json
import io, csv, os
import re
from services.repricer_weekly import apply_repricing_rules, preprocess_dataframe
from core.config import BASE_DIR
BASE_DIR_TMP = BASE_DIR / "python" / "tmp"
from core.csv_utils import read_csv_with_fallback, normalize_dataframe_for_cp932
from utils.csv_io import write_listing_csv_from_dataframe, write_repricer_csv
import numpy as np

# --- Trace関連のユーティリティ関数 ---
def _to_snake(camel: str) -> str:
    # priceTraceChange -> price_trace_change
    return re.sub(r'(?<!^)(?=[A-Z])', '_', camel).lower()

def _read_field(obj, camel: str, snake: str | None = None):
    snake = snake or _to_snake(camel)
    try:
        if isinstance(obj, dict):
            return obj.get(camel) if camel in obj else obj.get(snake)
        if hasattr(obj, camel):
            return getattr(obj, camel)
        if hasattr(obj, snake):
            return getattr(obj, snake)
        if hasattr(obj, "model_dump"):  # Pydantic v2
            d = obj.model_dump()
            return d.get(camel) if camel in d else d.get(snake)
        if hasattr(obj, "dict"):  # Pydantic v1
            d = obj.dict()
            return d.get(camel) if camel in d else d.get(snake)
    except Exception:
        pass
    return None

def _write_field(obj, camel: str, value, snake: str | None = None):
    snake = snake or _to_snake(camel)
    try:
        if isinstance(obj, dict):
            obj[camel] = value
            return
        if hasattr(obj, camel):
            setattr(obj, camel, value)
            return
        if hasattr(obj, snake):
            setattr(obj, snake, value)
            return
        if hasattr(obj, "__dict__"):
            obj.__dict__[camel] = value
            return
    except Exception:
        pass

def _fill_price_trace_change_on_items(result: dict | object, trace_label: str = "FBA譛€螳牙€､"):
    try:
        items = result.get("items") if isinstance(result, dict) else getattr(result, "items", None)
    except Exception:
        items = None
    if not items:
        return result

    for it in items:
        try:
            action = _read_field(it, "action")
            val = _read_field(it, "priceTraceChange")
            if action == "priceTrace" and (val is None or str(val).strip() == ""):
                _write_field(it, "priceTraceChange", trace_label)
        except Exception:
            continue

    return result
# --- /Trace関連のユーティリティ関数 ---

def _get_len(obj, key: str) -> int:
    try:
        v = getattr(obj, key, None)
        if v is None and isinstance(obj, dict):
            v = obj.get(key)
        return int(len(v)) if v is not None else 0
    except Exception:
        return 0

def _rebuild_report_csv_with_trace(items: list) -> str:
    buf = io.StringIO()
    # Always quote and use CRLF to avoid Excel column shifts
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    w.writerow(["sku", "days", "action", "reason", "price", "new_price", "trace"])
    for it in (items or []):
        rf = _read_field
        sku = (rf(it, "sku") or "")
        days = (rf(it, "days") or rf(it, "daysSinceListed") or "")
        action = (rf(it, "action") or "")
        reason = (rf(it, "reason") or "")
        price = (rf(it, "price") or rf(it, "currentPrice") or "")
        new_price = (rf(it, "new_price") or rf(it, "newPrice") or "")
        trace = (rf(it, "priceTraceChange") or rf(it, "price_trace_change") or "")
        w.writerow([sku, days, action, reason, price, new_price, trace])
    return buf.getvalue()

router = APIRouter(prefix="/repricer", tags=["repricer"])

CONFIG_PATH = BASE_DIR / "config" / "reprice_rules.json"

# --- Pydantic Models for Config ---
class RepriceRule(BaseModel):
    days_from: int
    action: Literal[
        "maintain",
        "priceTrace",
        "price_down_1",
        "price_down_2",
        "price_down_3",
        "price_down_4",
        "price_down_ignore",
        "exclude"
    ]
    value: Optional[float] = None

class RepriceConfig(BaseModel):
    profit_guard_percentage: float
    excluded_skus: list[str] = []
    q4_rule_enabled: bool = False
    reprice_rules: list[RepriceRule]
    updated_at: Optional[datetime] = None
# --- Config Endpoints ---
@router.get("/config")
def get_config():
    """Get repricer config and convert rules to a list."""
    try:
        if not CONFIG_PATH.exists():
            raise HTTPException(status_code=404, detail="Config file not found")
        
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        # Convert reprice_rules from dict to list (if needed)
        rules_data = config_data.get("reprice_rules", [])
        
        # 既にリスト形式の場合はそのまま返す
        if isinstance(rules_data, list):
            return config_data
        
        # 辞書形式の場合はリスト形式に変換
        if isinstance(rules_data, dict):
            rules_list = [
                {"days_from": int(k), "action": _read_field(v, "action"), "value": _read_field(v, "priceTrace")}
                for k, v in rules_data.items()
            ]
            config_data["reprice_rules"] = rules_list
        
        return config_data
        
    except Exception as e:
        print(f"[ERROR] Config取得エラー: {str(e)}")
        print(f"[ERROR] エラータイプ: {type(e).__name__}")
        import traceback
        print(f"[ERROR] トレースバック: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Config取得エラー: {str(e)}")

@router.put("/config", response_model=RepriceConfig)
def update_config(config: RepriceConfig = Body(...)):
    """Update repricer config"""
    config.updated_at = datetime.now()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config.dict(), f, indent=2, default=str)
        return config
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config file: {e}")

# --- Repricing Endpoints ---
@router.post("/preview")
async def preview(file: UploadFile = File(...)):
    try:
        print(f"[DEBUG] プレビューAPI呼び出し開始: ファイル名={file.filename}")
        content = await file.read()
        print(f"[DEBUG] ファイル読み込み完了: サイズ={len(content)} bytes")
        
        if not content:
            raise HTTPException(status_code=400, detail="CSVファイルが空です")
        
        print("[DEBUG] CSV読み込み開始...")
        df = read_csv_with_fallback(content)
        if df is None or df.empty:
            raise HTTPException(status_code=400, detail="CSVファイルの読み込みに失敗しました、またはデータが空です")
        print(f"[DEBUG] CSV読み込み完了: 行数={len(df)}, 列数={len(df.columns)}")
        print(f"[DEBUG] 列名: {list(df.columns)}")
        
        print("[DEBUG] 前処理開始...")
        df = preprocess_dataframe(df) # ここで前処理を実行
        print(f"[DEBUG] 前処理完了: 行数={len(df)}")

        print("[DEBUG] 価格改定ルール適用開始...")
        outputs = apply_repricing_rules(df, today=datetime.now())
        print(f"[DEBUG] 価格改定ルール適用完了")

        # ---- safe summary (no-attr errors) ----
        print("[DEBUG] サマリー生成開始...")
        summary = {
            'updated_rows': _get_len(outputs, 'updated_df'),
            'excluded_rows': _get_len(outputs, 'excluded_df'),
            'q4_switched': _get_len(outputs, 'q4_switched_df'),
            'date_unknown': _get_len(outputs, 'date_unknown_df'),
            'log_rows': _get_len(outputs, 'log_df'),
        }
        print(f"[DEBUG] サマリー: {summary}")
        
        # outputs.items を直接使用
        print("[DEBUG] items取得開始...")
        items = outputs.items if hasattr(outputs, 'items') else []
        print(f"[DEBUG] items取得完了: 件数={len(items)}")
        
        # JSONにシリアライズできない値（Infinity、NaN）をクリーンアップ
        print("[DEBUG] itemsの数値検証開始...")
        import math
        def clean_value(value):
            """JSONにシリアライズできない値を適切な値に変換"""
            if isinstance(value, (int, float)):
                if math.isnan(value):
                    return 0
                if math.isinf(value):
                    return 0 if value > 0 else 0
            return value
        
        def clean_item(item):
            """アイテムの数値をクリーンアップ"""
            if isinstance(item, dict):
                cleaned = {}
                for key, value in item.items():
                    if isinstance(value, (int, float)):
                        cleaned[key] = clean_value(value)
                    elif isinstance(value, dict):
                        cleaned[key] = clean_item(value)
                    elif isinstance(value, list):
                        cleaned[key] = [clean_item(v) if isinstance(v, dict) else clean_value(v) if isinstance(v, (int, float)) else v for v in value]
                    else:
                        cleaned[key] = value
                return cleaned
            return item
        
        cleaned_items = [clean_item(item) for item in items]
        print(f"[DEBUG] itemsの数値検証完了: {len(cleaned_items)}件")
        
        print("[DEBUG] レスポンス返却開始...")
        return {
            "summary": summary,
            "items": cleaned_items
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[ERROR] ========== 価格改定プレビューエラー ==========")
        print(f"[ERROR] エラーメッセージ: {str(e)}")
        print(f"[ERROR] エラータイプ: {type(e).__name__}")
        print(f"[ERROR] トレースバック:\n{error_trace}")
        print(f"[ERROR] ============================================")
        raise HTTPException(
            status_code=500,
            detail=f"価格改定プレビューに失敗しました: {str(e)}"
        )

@router.post("/apply")
async def apply(file: UploadFile = File(...)):
    try:
        print(f"[DEBUG] apply: 価格改定実行API呼び出し開始")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="CSVファイルが空です")
        
        print("[DEBUG] apply: CSV読み込み開始...")
        df = read_csv_with_fallback(content)
        if df is None or df.empty:
            raise HTTPException(status_code=400, detail="CSVファイルの読み込みに失敗しました、またはデータが空です")
        print(f"[DEBUG] apply: CSV読み込み完了: 行数={len(df)}, 列数={len(df.columns)}")

        print("[DEBUG] apply: 前処理開始...")
        df = preprocess_dataframe(df)
        print(f"[DEBUG] apply: 前処理完了: 行数={len(df)}")

        print("[DEBUG] apply: 価格改定ルール適用開始...")
        outputs = apply_repricing_rules(df, today=datetime.now())
        print(f"[DEBUG] apply: 価格改定ルール適用完了")
        _fill_price_trace_change_on_items(outputs, trace_label="FBA譛螳牙､")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        updated_path = BASE_DIR_TMP / f"updated_{stamp}.csv"
        excluded_path = BASE_DIR_TMP / f"excluded_{stamp}.csv"
        log_path = BASE_DIR_TMP / f"log_{stamp}.csv"

        # rename priceTrace -> trace + Excel formula removal
        try:
            # 列名は仕様に合わせてそのまま保持（priceTrace を維持）
            updated_df_renamed = outputs.updated_df.copy()

            # CSV出力直前: 全セルから ="..." 形式を除去（最終防衛ライン）
            def remove_formula_from_cell(x):
                """セル値から ="..." を除去"""
                if isinstance(x, str) and x.startswith('="') and x.endswith('"'):
                    return x[2:-1]  # =" と " を除去
                return x

            # updated_df の全列に適用
            for col in updated_df_renamed.columns:
                updated_df_renamed[col] = updated_df_renamed[col].apply(remove_formula_from_cell)

            # excluded_df の全列に適用
            excluded_df_cleaned = outputs.excluded_df.copy()
            for col in excluded_df_cleaned.columns:
                excluded_df_cleaned[col] = excluded_df_cleaned[col].apply(remove_formula_from_cell)

            # log_df の全列に適用
            log_df_cleaned = outputs.log_df.copy()
            for col in log_df_cleaned.columns:
                log_df_cleaned[col] = log_df_cleaned[col].apply(remove_formula_from_cell)

        except Exception as e:
            import traceback
            traceback.print_exc()
            # フォールバック: 元のDataFrameを使用
            updated_df_renamed = outputs.updated_df.copy()
            excluded_df_cleaned = outputs.excluded_df.copy()
            log_df_cleaned = outputs.log_df.copy()

        # Build report CSV with trace information
        items = outputs.get("items") if isinstance(outputs, dict) else getattr(outputs, "items", [])
        
        # JSONにシリアライズできない値（Infinity、NaN）をクリーンアップ
        print("[DEBUG] apply: itemsの数値検証開始...")
        import math
        def clean_value(value):
            """JSONにシリアライズできない値を適切な値に変換"""
            if isinstance(value, (int, float)):
                if math.isnan(value):
                    return 0
                if math.isinf(value):
                    return 0 if value > 0 else 0
            return value
        
        def clean_item(item):
            """アイテムの数値をクリーンアップ"""
            if isinstance(item, dict):
                cleaned = {}
                for key, value in item.items():
                    if isinstance(value, (int, float)):
                        cleaned[key] = clean_value(value)
                    elif isinstance(value, dict):
                        cleaned[key] = clean_item(value)
                    elif isinstance(value, list):
                        cleaned[key] = [clean_item(v) if isinstance(v, dict) else clean_value(v) if isinstance(v, (int, float)) else v for v in value]
                    else:
                        cleaned[key] = value
                return cleaned
            return item
        
        cleaned_items = [clean_item(item) for item in items]
        print(f"[DEBUG] apply: itemsの数値検証完了: {len(cleaned_items)}件")
        
        report_csv = _rebuild_report_csv_with_trace(cleaned_items) if cleaned_items else ""
        # Encode report CSV as cp932 base64 for Excel safety
        try:
            report_csv_bytes = report_csv.encode("cp932", errors="replace")
        except Exception:
            report_csv_bytes = report_csv.encode("utf-8", errors="replace")
        import base64 as _b64
        report_csv_content_b64 = _b64.b64encode(report_csv_bytes).decode("ascii")

        # Generate updated CSV content for download (Prister upload format)
        # Build a dataframe that matches the expected schema and values
        try:
            base_df = outputs.updated_df.copy()
        except Exception:
            base_df = updated_df_renamed.copy()

        # 入力CSV互換のための正規化（文字化け/列崩れ対策・決定版）
        base_df = normalize_dataframe_for_cp932(base_df)

        # Map and derive fields
        if "new_price" in base_df.columns:
            base_df["price"] = base_df["new_price"]
        if "new_priceTrace" in base_df.columns:
            base_df["priceTrace"] = base_df["new_priceTrace"]
        # number はそのまま
        if "number" not in base_df.columns:
            base_df["number"] = 1

        # 出力列（conditionNoteをJ列に追加、priceTraceを保持）
        desired_cols = [
            "SKU", "ASIN", "title", "number", "price", "cost", "akaji", "takane",
            "condition", "conditionNote", "priceTrace", "leadtime", "amazon-fee", "shipping-price", "profit", "add-delete",
        ]
        # Keep only desired columns in correct order (fill missing with empty string)
        for col in desired_cols:
            if col not in base_df.columns:
                base_df[col] = ""
        formatted_df = base_df[desired_cols]

        # Format numeric columns as integer-like strings (no trailing .0)
        num_cols = ["number", "price", "cost", "akaji", "takane", "condition", "priceTrace", "leadtime", "amazon-fee", "shipping-price", "profit"]
        for col in num_cols:
            if col in formatted_df.columns:
                try:
                    formatted_df[col] = pd.to_numeric(formatted_df[col], errors="coerce").fillna(0).astype(int).astype(str)
                except Exception:
                    formatted_df[col] = formatted_df[col].astype(str)

        # Force text columns to Excel-safe formula style ="..." (to match historical files)
        excel_text_cols = ["SKU", "ASIN", "title"]
        for col in excel_text_cols:
            if col in formatted_df.columns:
                def _wrap(v: str) -> str:
                    v = "" if v is None else str(v)
                    # 既に ="..." ならそのまま
                    if v.startswith('="') and v.endswith('"'):
                        return v
                    # 内部の"は2重化（CSVライタがさらに適切に処理）
                    v_escaped = v.replace('"', '""')
                    return f'="{v_escaped}"'
                formatted_df[col] = formatted_df[col].apply(_wrap)

        # conditionNote を空文字で追加（J列）
        if 'conditionNote' not in formatted_df.columns:
            formatted_df['conditionNote'] = ""

        # desired_colsのみに絞り直し（念のため）
        formatted_df = formatted_df[desired_cols]

        # leadtime を空白に（0ではなく空文字）
        if 'leadtime' in formatted_df.columns:
            formatted_df['leadtime'] = ""

        # ="..." 形式を除去（念のため）
        for col in formatted_df.columns:
            if formatted_df[col].dtype == 'object':
                formatted_df[col] = (formatted_df[col]
                                     .astype(str)
                                     .str.replace(r'^=\"', '', regex=True)
                                     .str.replace(r'\"$', '', regex=True))

        # Repricing用CSV（説明行なし、ヘッダー+データのみ）
        updated_csv_bytes = write_repricer_csv(formatted_df, desired_cols)
        import base64 as _b64
        updated_csv_content = _b64.b64encode(updated_csv_bytes).decode("ascii")

        # updated.csv はプライスター取込フォーマットで出力（writerの結果をそのまま保存）
        try:
            with open(updated_path, "wb") as f:
                f.write(updated_csv_bytes)
        except Exception:
            # フォールバック（従来方式）
            updated_df_renamed.to_csv(updated_path, index=False,
                encoding="cp932", lineterminator="\r\n", quoting=csv.QUOTE_ALL, errors='replace')
        excluded_df_cleaned.to_csv(excluded_path, index=False,
            encoding="cp932", lineterminator="\r\n", quoting=csv.QUOTE_ALL, errors='replace')
        log_df_cleaned.to_csv(log_path, index=False,
            encoding="cp932", lineterminator="\r\n", quoting=csv.QUOTE_ALL, errors='replace')

        response_data = {
            "ok": True,
            "reportCsvContent": report_csv_content_b64,
            "reportCsvEncoding": "cp932-base64",
            "updatedCsvContent": updated_csv_content,
            "updatedCsvEncoding": "cp932-base64",
            "files": {
                "updated": str(updated_path),
                "excluded": str(excluded_path),
                "log": str(log_path),
            },
            "items": cleaned_items,
            "summary": {
                'updated_rows': _get_len(outputs, 'updated_df'),
                'excluded_rows': _get_len(outputs, 'excluded_df'),
                'q4_switched': _get_len(outputs, 'q4_switched_df'),
                'date_unknown': _get_len(outputs, 'date_unknown_df'),
                'log_rows': _get_len(outputs, 'log_df'),
            }
        }
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[ERROR] ========== 価格改定実行エラー ==========")
        print(f"[ERROR] エラーメッセージ: {str(e)}")
        print(f"[ERROR] エラータイプ: {type(e).__name__}")
        print(f"[ERROR] トレースバック:\n{error_trace}")
        print(f"[ERROR] ============================================")
        raise HTTPException(
            status_code=500,
            detail=f"価格改定実行に失敗しました: {str(e)}"
        )

@router.post("/debug")
async def debug(file: UploadFile = File(...)):
    """
    SKU解析とデバッグ用のエンドポイント
    最初の10行のSKUを解析して結果を返す
    """
    content = await file.read()
    df = read_csv_with_fallback(content)

    # 謨ｰ蛟､邉ｻ縺ｮ繧ｫ繝ｩ繝蝙句､画鋤
    for col in ["price", "akaji", "priceTrace"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    today = datetime.now()

    # 譛€蛻昴・10莉ｶ繧定ｧ｣譫・    debug_results = []
    for i, row in df.head(10).iterrows():
        sku = row.get('SKU', '')

        # SKU譌･莉倩ｧ｣譫・        parsed_date = parse_listing_date_from_sku(sku)

        # 邨碁℃譌･謨ｰ險育ｮ・        days_since = None
        if parsed_date:
            days_since = (today - parsed_date).days

        # 蛻・｡槫愛螳・        category = "invalid"
        if parsed_date and days_since is not None:
            if days_since > 365:
                category = "long_term"
            elif days_since > 60:
                category = "switched_to_trace"
            elif days_since >= 0:
                category = "updated"
            else:
                category = "future_date"

        debug_results.append({
            "index": int(i),
            "sku": str(sku) if pd.notna(sku) else "",
            "parsed_date": parsed_date.strftime("%Y-%m-%d") if parsed_date else None,
            "days_since": days_since,
            "category": category
        })

    return {
        "total_rows": len(df),
        "debug_sample": debug_results,
        "analysis_date": today.strftime("%Y-%m-%d %H:%M:%S")
    }
