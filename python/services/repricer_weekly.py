import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Tuple, NamedTuple
import json
import re
import math
import sqlite3
from pathlib import Path
from core.config import CONFIG_PATH
from core.csv_utils import normalize_dataframe_for_cp932

# アクション名の日本語マッピング
ACTION_NAMES_JP = {
    "maintain": "維持",
    "priceTrace": "Trace変更",
    "tp_down": "TP値下げ",
    "price_down_1": "1%値下げ",
    "price_down_2": "2%値下げ",
    "profit_ignore_down": "1%値下げ(ガード無視)",
    "price_down_ignore": "1%値下げ(利益無視)",  # 設定ファイルで使用される名前
    "exclude": "除外",
}

# Trace値の日本語マッピング
TRACE_VALUE_NAMES_JP = {
    0: "維持",
    1: "FBA状態合わせ",
    2: "状態合わせ",
    3: "FBA最安値",
    4: "最安値",
    5: "カート価格",
}

def format_trace_value(trace_value):
    """Trace値を日本語に変換"""
    try:
        trace_int = int(float(trace_value)) if trace_value is not None else 0
        return TRACE_VALUE_NAMES_JP.get(trace_int, str(trace_value))
    except (ValueError, TypeError):
        return str(trace_value) if trace_value is not None else "維持"

def preprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrameの前処理: Excel数式記法の完全除去
    """
    print(f"[DEBUG preprocess] Called with shape: {df.shape}")
    
    # 処理前のサンプルを出力
    if len(df) > 0:
        print(f"[DEBUG preprocess] BEFORE - First row price (raw): {df['price'].iloc[0] if 'price' in df.columns else 'N/A'}")
        print(f"[DEBUG preprocess] BEFORE - First row conditionNote (raw): {df['conditionNote'].iloc[0] if 'conditionNote' in df.columns else 'N/A'}")
    
    # すべての列でExcel数式記法を除去（文字列列・数値列両方）
    for col in df.columns:
        # 文字列型またはオブジェクト型の列に対してのみ処理
        if df[col].dtype == 'object':
            # より確実な数式記法削除
            df[col] = df[col].astype(str).str.replace(r'^="(.*)"$', r'\1', regex=True)
            # 念のため、より広範囲なパターンも削除
            df[col] = df[col].str.replace(r'^="([^"]*)"$', r'\1', regex=True)
            if len(df) > 0:
                print(f"[DEBUG preprocess] AFTER Excel formula removal for {col}: {df[col].iloc[0]}")
    
    # 処理後のサンプルを出力
    if len(df) > 0:
        print(f"[DEBUG preprocess] AFTER Excel formula removal - price: {df['price'].iloc[0] if 'price' in df.columns else 'N/A'}")
        print(f"[DEBUG preprocess] AFTER Excel formula removal - conditionNote: {df['conditionNote'].iloc[0] if 'conditionNote' in df.columns else 'N/A'}")
        print(f"[DEBUG preprocess] AFTER Excel formula removal - SKU: {df['SKU'].iloc[0] if 'SKU' in df.columns else 'N/A'}")
    
    # 数値列を明示的に変換
    numeric_cols = ['price', 'cost', 'akaji', 'takane', 'number', 'priceTrace', 
                    'leadtime', 'amazon-fee', 'shipping-price', 'profit']
    for col in numeric_cols:
        if col in df.columns:
            # 数値変換前に、念のため再度Excel数式記法を除去
            df[col] = df[col].astype(str).str.replace(r'^="(.*)"$', r'\1', regex=True)
            df[col] = df[col].str.replace(r'^="([^"]*)"$', r'\1', regex=True)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            if len(df) > 0:
                print(f"[DEBUG preprocess] {col} after numeric conversion: {df[col].iloc[0]}")
    
    print(f"[DEBUG preprocess] Completed. Final shape: {df.shape}")
    return df


class RepriceOutputs(NamedTuple):
    log_df: pd.DataFrame
    updated_df: pd.DataFrame
    excluded_df: pd.DataFrame
    items: List[Dict[str, Any]]

def load_config(mode: str = "standard"):
    """設定ファイルを読み込む"""
    import os
    from pathlib import Path
    
    try:
        # 設定ファイルの存在確認
        if not os.path.exists(CONFIG_PATH):
            raise FileNotFoundError(f"設定ファイルが見つかりません: {CONFIG_PATH}")
        
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 必須キーの確認
        if 'reprice_rules' not in config:
            raise ValueError("設定ファイルに'reprice_rules'が含まれていません")
        
        # リスト形式のreprice_rulesを辞書形式に変換
        if isinstance(config['reprice_rules'], list):
            rules_dict = {}
            for rule in config['reprice_rules']:
                days_from = rule.get('days_from')
                if days_from:
                    rules_dict[str(days_from)] = {
                        'action': rule.get('action', 'maintain'),
                        'priceTrace': rule.get('value', 0)  # valueフィールドをpriceTraceにマッピング
                    }
            config['reprice_rules'] = rules_dict
        
        # 空のルール辞書の場合はデフォルト値を設定
        if not config.get('reprice_rules'):
            config['reprice_rules'] = {}
        
        # excluded_skusが存在しない場合は空リストを設定
        if 'excluded_skus' not in config:
            config['excluded_skus'] = []
        
        # 3-6-9モードで必要なキーのデフォルト補完
        if mode == "369":
            config.setdefault("rule_profiles", {
                "3": {"tp_rates": {"tp0": 95, "tp1": 75, "tp2": 60, "tp3": 0}},
                "6": {"tp_rates": {"tp0": 90, "tp1": 70, "tp2": 55, "tp3": 0}},
                "9": {"tp_rates": {"tp0": 85, "tp1": 65, "tp2": 50, "tp3": 0}},
            })
            config.setdefault("default_profile", "6")
            config.setdefault("interval_days", 7)
            config.setdefault("alerts", {"enabled": True, "reason_prefix": "ALERT"})
        
        return config
    except FileNotFoundError as e:
        print(f"[ERROR] 設定ファイルが見つかりません: {e}")
        raise
    except json.JSONDecodeError as e:
        print(f"[ERROR] 設定ファイルのJSON形式が正しくありません: {e}")
        raise ValueError(f"設定ファイルのJSON形式が正しくありません: {e}")
    except Exception as e:
        print(f"[ERROR] 設定ファイルの読み込みエラー: {e}")
        raise

def get_days_since_listed(sku: str, today: datetime) -> int:
    """
    SKUから正規表現パターンのリストを使用して日付を抽出 し、今日までの経過日数を計算する。
    日付が抽出できない場合は-1を返す。
    """
    # Excel数式記法を削除
    if isinstance(sku, str) and sku.startswith('="') and sku.endswith('"'):
        sku = sku[2:-1]  # =" と " を除去
    
    # 将来のパターン追加を容易にするための正規表現リスト
    # パターンは優先順位の高い順に並べる
    patterns = [
        # 2024_08_28 or 2024_0828
        r"^(?P<year>\d{4})_(?P<month>\d{2})_?(?P<day>\d{2})",
        # 20250201-... (ハイフン区切り)
        r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})-",
        # 20251108B... (YYYYMMDD + アルファベットで始まる文字列)
        r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})(?=[A-Za-z])",
        # hmk-20251108-... (プレフィックス-YYYYMMDD-形式)
        r"^[a-z]+-(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})-",
        # pr_..._20250217_...
        r"_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_",
        # 250518-... (YYMMDD形式)
        r"^(?P<year>\d{2})(?P<month>\d{2})(?P<day>\d{2})-",
    ]

    for pattern in patterns:
        match = re.search(pattern, sku)
        if match:
            try:
                parts = match.groupdict()
                year, month, day = int(parts["year"]), int(parts["month"]), int(parts["day"])
                
                # YYMMDD形式の場合、2000年代として解釈
                if len(parts["year"]) == 2:
                    year += 2000

                listed_date = datetime(year, month, day)
                return (today - listed_date).days
            except (ValueError, KeyError):
                continue
    
    return -1

def get_rule_for_days(days: int, rules: Dict[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """
    経過日数に応じたルールキーとルールデータを返す
    30日間隔設定システム対応
    """
    # rulesが辞書形式でない場合はデフォルトルールを返す
    if not isinstance(rules, dict):
        print(f"[WARNING] rulesが辞書形式ではありません: {type(rules)}")
        return "default", {"action": "maintain", "priceTrace": 0}
    
    # 30日間隔でのルール検索: 30, 60, 90, ..., 360
    for days_key in [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360]:
        if days <= days_key:
            rule_key = str(days_key)
            if rule_key in rules:
                rule = rules[rule_key]
                # ルールが辞書形式でない場合はデフォルトルールを返す
                if not isinstance(rule, dict):
                    print(f"[WARNING] ルール {rule_key} が辞書形式ではありません: {type(rule)}")
                    return rule_key, {"action": "maintain", "priceTrace": 0}
                return rule_key, rule

    # 365日超過の場合は対象外
    return "over_365", {"action": "exclude", "priceTrace": 0}

def calculate_new_price_and_trace(price: float, akaji: float, rule: Dict[str, Any], days_since_listed: int, config: Dict[str, Any], current_price_trace: int) -> Tuple[str, str, float, int]:
    """
    最新仕様：6種類のアクション対応
    1. maintain: 維持（価格もTraceも変更なし）
    2. priceTrace: Traceのみ変更（価格は変更なし）
    3. price_down_1: 価格のみ1%値下げ（Traceは変更なし）
    4. price_down_2: 価格のみ2%値下げ（Traceは変更なし）
    5. profit_ignore_down: 価格のみ1%値下げ・ガード無視（Traceは変更なし）
    6. exclude: 対象外（変更なし）
    """
    action = rule["action"]
    action_jp = ACTION_NAMES_JP.get(action, action)
    reason = f"{days_since_listed}日経過: {action_jp}"

    # 計算前にfloatに変換
    price = float(price)
    akaji = float(akaji)

    # デフォルト: 変更なし
    new_price = price
    new_price_trace = current_price_trace  # 現在値を維持

    if action == "maintain":
        # 価格変更なし、priceTraceも変更なし
        pass

    elif action == "priceTrace":
        # priceTraceのみ変更、価格は変更なし
        new_price_trace = rule.get("priceTrace", rule.get("value", 0))
        print(f"[DEBUG priceTrace] ルール: {rule}, 新しいpriceTrace: {new_price_trace}")

    elif action == "price_down_1":
        # 価格のみ1%値下げ、priceTraceは変更なし
        new_price = round(price * 0.99)
        guard_price = config.get("profit_guard_percentage", 1.1)
        if new_price < guard_price:
            new_price = round(guard_price)
            reason += "（利益ガード適用）"

    elif action == "price_down_2":
        # 価格のみ2%値下げ、priceTraceは変更なし
        new_price = round(price * 0.98)
        guard_price = config.get("profit_guard_percentage", 1.1)
        if new_price < guard_price:
            new_price = round(guard_price)
            reason += "（利益ガード適用）"

    elif action == "profit_ignore_down":
        # 価格のみ1%値下げ（利益率ガード無視）、priceTraceは変更なし
        new_price = round(price * 0.99)
        reason += "（利益ガード無視）"

    elif action == "price_down_ignore":
        # 価格のみ1%値下げ（利益率ガード無視）、priceTraceは変更なし
        # 設定ファイルで使用される名前（profit_ignore_downと同じ処理）
        new_price = round(price * 0.99)

    elif action == "exclude":
        # 対象外、変更なし
        reason = f"{days_since_listed}日経過: 除外（要手動対応）"

    return action, reason, new_price, new_price_trace

def _to_float_or_none(value: Any) -> float:
    try:
        if value is None:
            return None
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def detect_369_profile_from_sku(sku: str, default_profile: str) -> Tuple[str, bool]:
    """SKU文字列から3/6/9プロファイルを判定。判定不可時はdefault_profile。"""
    if not isinstance(sku, str):
        return default_profile, True
    text = sku.upper()
    patterns = [
        (r"(^|[-_])3([PN])?($|[-_])", "3"),
        (r"(^|[-_])6([PN])?($|[-_])", "6"),
        (r"(^|[-_])9([PN])?($|[-_])", "9"),
        (r"(3P|3N)", "3"),
        (r"(6P|6N)", "6"),
        (r"(9P|9N)", "9"),
    ]
    for pattern, profile in patterns:
        if re.search(pattern, text):
            return profile, False
    return default_profile, True


def _get_tp_band(days_since_listed: int) -> Tuple[str, int]:
    if days_since_listed <= 90:
        return "tp0", 90
    if days_since_listed <= 180:
        return "tp1", 180
    if days_since_listed <= 270:
        return "tp2", 270
    return "tp3", 365


def _get_tp_floor(price: float, akaji: float, tp_rate: float) -> float:
    base = akaji if akaji and akaji > 0 else price
    return round(max(0.0, base) * (max(0.0, tp_rate) / 100.0))


def _to_float_or_none_strict(value: Any) -> float:
    """数値化できる値のみfloatを返す。空/不正値はNone。"""
    try:
        if value is None:
            return None
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _csv_profit_from_inventory_row(row: Any) -> float:
    """在庫CSVの profit 列（見込み利益）を数値化。欠損・不正は0。"""
    try:
        if row is None:
            return 0.0
        v = row.get("profit") if hasattr(row, "get") else None
        if v is None:
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _resolve_purchase_db_path() -> Path:
    """仕入DB(hirio.db)の想定パスを返す。"""
    # python/services/repricer_weekly.py から python/desktop/data/hirio.db を参照
    return Path(__file__).resolve().parent.parent / "desktop" / "data" / "hirio.db"


def _load_tp_map_from_purchase_db(sku_list: List[str]) -> Dict[str, Dict[str, float]]:
    """仕入DBからSKU単位のTP0~TP3を読み込む。"""
    result: Dict[str, Dict[str, float]] = {}
    if not sku_list:
        return result

    db_path = _resolve_purchase_db_path()
    if not db_path.exists():
        return result

    unique_skus = []
    seen = set()
    for sku in sku_list:
        s = str(sku or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        unique_skus.append(s)

    if not unique_skus:
        return result

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        chunk_size = 900  # SQLite変数上限対策
        for i in range(0, len(unique_skus), chunk_size):
            chunk = unique_skus[i:i + chunk_size]
            placeholders = ",".join(["?"] * len(chunk))
            cur.execute(
                f"SELECT sku, tp0, tp1, tp2, tp3 FROM purchases WHERE sku IN ({placeholders})",
                tuple(chunk),
            )
            for row in cur.fetchall():
                sku = str(row["sku"] or "").strip()
                if not sku:
                    continue
                result[sku] = {
                    "tp0": _to_float_or_none_strict(row["tp0"]),
                    "tp1": _to_float_or_none_strict(row["tp1"]),
                    "tp2": _to_float_or_none_strict(row["tp2"]),
                    "tp3": _to_float_or_none_strict(row["tp3"]),
                }
        conn.close()
    except Exception as e:
        # 仕入DB参照で失敗しても改定処理自体は継続（従来%計算へフォールバック）
        print(f"[WARNING 3-6-9 TP] 仕入DBのTP読込に失敗: {e}")
    return result


def _is_repricing_off(value: Any) -> bool:
    """価格改定ON/OFF表現を判定。True=OFF（改定除外）。"""
    if value is None:
        return False
    s = str(value).strip().lower()
    if s == "":
        return False
    return s in {"0", "off", "false", "無効", "いいえ", "no"}


def _load_repricing_enabled_map_from_purchase_db(sku_list: List[str]) -> Dict[str, bool]:
    """仕入DBからSKU単位の価格改定フラグ（True=ON）を読み込む。"""
    result: Dict[str, bool] = {}
    if not sku_list:
        return result

    db_path = _resolve_purchase_db_path()
    if not db_path.exists():
        return result

    unique_skus = []
    seen = set()
    for sku in sku_list:
        s = str(sku or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        unique_skus.append(s)
    if not unique_skus:
        return result

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        chunk_size = 900
        for i in range(0, len(unique_skus), chunk_size):
            chunk = unique_skus[i:i + chunk_size]
            placeholders = ",".join(["?"] * len(chunk))
            cur.execute(
                f"SELECT sku, repricing_enabled FROM purchases WHERE sku IN ({placeholders})",
                tuple(chunk),
            )
            for row in cur.fetchall():
                sku = str(row["sku"] or "").strip()
                if not sku:
                    continue
                result[sku] = not _is_repricing_off(row["repricing_enabled"])
        conn.close()
    except Exception as e:
        print(f"[WARNING REPRICE FLAG] 仕入DBの価格改定フラグ読込に失敗: {e}")

    return result


def _get_profile_rule_for_days(days_since_listed: int, profile_rules: List[Dict[str, Any]]) -> Tuple[int, Dict[str, Any]]:
    """profile_rules(リスト)から経過日数に対応するルールを返す。"""
    if not isinstance(profile_rules, list) or not profile_rules:
        return -1, {"days_from": 999, "action": "maintain", "value": 0, "tp_target": "tp0", "akaji_drop_percent": 1, "takane_rise_percent": 0}
    sorted_rules = sorted(profile_rules, key=lambda r: int(r.get("days_from", 999)))
    for idx, rule in enumerate(sorted_rules):
        try:
            days_to = int(rule.get("days_from", 999))
        except Exception:
            days_to = 999
        if days_since_listed <= days_to:
            return idx, rule
    return len(sorted_rules) - 1, sorted_rules[-1]


def _get_tp_down_period_end(current_idx: int, current_rule: Dict[str, Any], profile_rules: List[Dict[str, Any]]) -> int:
    """同一アクション(tp_down)かつ同一TP指定が連続する終端日を返す。"""
    if current_idx < 0 or not profile_rules:
        return int(current_rule.get("days_from", 999) or 999)
    sorted_rules = sorted(profile_rules, key=lambda r: int(r.get("days_from", 999)))
    target_tp = str(current_rule.get("tp_target", "tp0")).lower()
    end_day = int(current_rule.get("days_from", 999) or 999)
    for i in range(current_idx + 1, len(sorted_rules)):
        rule = sorted_rules[i]
        action = str(rule.get("action", "maintain"))
        tp_target = str(rule.get("tp_target", "tp0")).lower()
        if action != "tp_down" or tp_target != target_tp:
            break
        end_day = int(rule.get("days_from", end_day) or end_day)
    return end_day


def _apply_repricing_rules_369(df: pd.DataFrame, today: datetime, config: Dict[str, Any]) -> RepriceOutputs:
    log_data = []
    updated_inventory_data = []
    excluded_inventory_data = []
    excluded_skus = set(config.get("excluded_skus", []))
    profiles = config.get("rule_profiles", {})
    exception_rules = config.get("exception_reprice_rules", []) or []
    default_profile = str(config.get("default_profile", "6"))
    interval_days = max(1, int(config.get("interval_days", 7)))
    alert_cfg = config.get("alerts", {}) or {}
    alert_enabled = bool(alert_cfg.get("enabled", True))
    alert_prefix = str(alert_cfg.get("reason_prefix", "ALERT")).strip() or "ALERT"
    # 3-6-9では仕入DBのTPを優先参照（無い場合のみ%計算にフォールバック）
    sku_candidates = []
    for _, _row in df.iterrows():
        _sku = _row.get("SKU", "")
        if isinstance(_sku, str) and _sku.startswith('="') and _sku.endswith('"'):
            _sku = _sku[2:-1]
        sku_candidates.append(str(_sku or "").strip())
    tp_map_by_sku = _load_tp_map_from_purchase_db(sku_candidates)
    repricing_enabled_map_by_sku = _load_repricing_enabled_map_from_purchase_db(sku_candidates)

    for _, row in df.iterrows():
        sku = row.get("SKU", "")
        if isinstance(sku, str) and sku.startswith('="') and sku.endswith('"'):
            sku = sku[2:-1]
        price = float(row.get("price", 0) or 0)
        akaji = float(row.get("akaji", 0) or 0)
        price_trace = row.get("priceTrace", 0)
        asin = row.get("ASIN", "")
        title = row.get("title", "")
        row_repricing_off = _is_repricing_off(row.get("価格改定"))
        db_repricing_enabled = repricing_enabled_map_by_sku.get(str(sku).strip(), True)
        if row_repricing_off or not db_repricing_enabled:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "除外",
                "reason": "価格改定OFF（仕入DB設定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": _csv_profit_from_inventory_row(row),
                "tp_floor": None,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        if sku in excluded_skus:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "除外",
                "reason": "除外SKU（設定で除外指定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": _csv_profit_from_inventory_row(row),
                "tp_floor": None,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        days_since_listed = get_days_since_listed(sku, today)
        if days_since_listed == -1:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "維持",
                "reason": "日付不明（維持）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": _csv_profit_from_inventory_row(row),
                "tp_floor": None,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            updated_inventory_data.append(row.to_dict())
            continue
        if days_since_listed > 365:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "除外",
                "reason": f"{days_since_listed}日経過: 365日超過（要手動対応）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": _csv_profit_from_inventory_row(row),
                "tp_floor": None,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        profile, is_fallback = detect_369_profile_from_sku(str(sku), default_profile)
        profile_data = profiles.get(profile) or {}
        profile_rules = profile_data.get("reprice_rules", []) or []

        # SKUタグ判定不可時の分岐:
        # - 仕入DBにSKUがあり、TPが1つでも入力されていれば「6ルール」
        # - 仕入DBにSKUがない or TP未入力なら「例外ルール」
        sku_key = str(sku).strip()
        db_tp_row = tp_map_by_sku.get(sku_key) or {}
        has_db_sku = sku_key in tp_map_by_sku
        has_any_db_tp = any(
            (v is not None and float(v) > 0)
            for v in [db_tp_row.get("tp0"), db_tp_row.get("tp1"), db_tp_row.get("tp2"), db_tp_row.get("tp3")]
        )

        fallback_to_profile6 = bool(is_fallback and has_db_sku and has_any_db_tp)
        using_exception_rules = bool(is_fallback and not fallback_to_profile6 and exception_rules)

        if fallback_to_profile6:
            profile = "6"
            profile_data = profiles.get(profile) or {}
            profile_rules = profile_data.get("reprice_rules", []) or []

        active_rules = exception_rules if using_exception_rules else profile_rules
        rule_idx, active_rule = _get_profile_rule_for_days(days_since_listed, active_rules)
        raw_action = str(active_rule.get("action", "maintain"))
        rule_trace_value = active_rule.get("value", 0)
        tp_key_default, period_end_default = _get_tp_band(days_since_listed)
        tp_key = str(active_rule.get("tp_target", tp_key_default)).lower()
        if tp_key not in ("tp0", "tp1", "tp2", "tp3"):
            tp_key = tp_key_default
        akaji_drop_percent = int(active_rule.get("akaji_drop_percent", 1) or 1)
        akaji_drop_percent = min(10, max(1, akaji_drop_percent))
        takane_rise_percent = int(active_rule.get("takane_rise_percent", 0) or 0)
        takane_rise_percent = min(10, max(0, takane_rise_percent))
        tp_rates = ((profiles.get(profile) or {}).get("tp_rates") or {})
        tp_rate = float(tp_rates.get(tp_key, 0) or 0)
        # TP下限は「仕入DBのTP0~TP3」を優先。未設定時のみ従来の%計算。
        db_tp_value = (db_tp_row.get(tp_key))
        use_db_tp = db_tp_value is not None and db_tp_value > 0
        tp_floor = round(db_tp_value) if use_db_tp else _get_tp_floor(price, akaji, tp_rate)
        period_end = _get_tp_down_period_end(rule_idx, active_rule, active_rules) if raw_action == "tp_down" else period_end_default

        action_jp = ACTION_NAMES_JP.get(raw_action, raw_action)
        rule_label = "例外ルール" if using_exception_rules else f"{profile}ルール"
        if using_exception_rules:
            # 例外適用時はTP表記を出さず、通常改定との差を明確化する
            reason_tokens = [f"{days_since_listed}日経過: 3-6-9改定({rule_label}/{action_jp})"]
        else:
            reason_tokens = [f"{days_since_listed}日経過: 3-6-9改定({rule_label}/{tp_key.upper()}/{action_jp})"]
        if is_fallback:
            if fallback_to_profile6:
                reason_tokens.append("PROFILE_FALLBACK: SKUタグ判定不可だが仕入DBのTP入力ありのため6ルール適用")
            elif using_exception_rules:
                reason_tokens.append("PROFILE_FALLBACK: SKUタグ判定不可のため例外タブルール適用")
            else:
                reason_tokens.append(f"PROFILE_FALLBACK: SKUタグ判定不可（例外ルール未設定のため{profile}ルール適用）")
        if use_db_tp:
            reason_tokens.append(f"TP_DB: 仕入DBの{tp_key.upper()}={tp_floor}を適用")
            if price <= tp_floor:
                reason_tokens.append(
                    f"{tp_key.upper()}は{round(tp_floor)}だが現在価格{round(price)}のためTP下限以下判定で{round(price)}維持"
                )
        else:
            reason_tokens.append(f"TP_RATE: {tp_key.upper()}={tp_rate}% で算出")

        keepa_min = _to_float_or_none(row.get("keepa_min_same_condition"))
        new_price_trace = price_trace
        if raw_action == "maintain":
            new_price = round(price)
        elif raw_action == "priceTrace":
            # 3-6-9運用:
            # 仕入DBにTP価格がある場合は、Trace変更アクションでも
            # 現在価格からTP下限へ期間内で段階的に近づける。
            # （例: 110日→TP1帯終端180日に向けて日割り/interval刻みで減算）
            if tp_key == "tp0":
                # TP0は段階的値下げを行わず、価格は維持（akaji/takaneのみ更新）
                new_price = round(price)
                reason_tokens.append("TP0は段階的値下げ対象外のため価格維持")
            elif use_db_tp and tp_floor > 0 and price > tp_floor:
                remaining_days = max(0, period_end - days_since_listed)
                steps = max(1, math.ceil(remaining_days / interval_days))
                delta = (price - tp_floor) / steps if steps > 0 else 0
                new_price = max(tp_floor, round(price - delta))
                reason_tokens.append(
                    f"TP_DAILY: {days_since_listed}日→{period_end}日で{tp_floor}へ段階調整"
                )
            else:
                new_price = round(price)
            new_price_trace = rule_trace_value
        elif raw_action == "tp_down":
            if tp_key == "tp0":
                # TP0は段階的値下げを行わず、価格は維持（akaji/takaneのみ更新）
                new_price = round(price)
                reason_tokens.append("TP0は段階的値下げ対象外のため価格維持")
            else:
                if keepa_min is None:
                    start_price = price
                    reason_tokens.append("KEEPA_MISSING: keepa_min_same_condition 未入力")
                elif keepa_min < tp_floor:
                    start_price = tp_floor
                    if alert_enabled:
                        reason_tokens.append(
                            f"{alert_prefix}: keepa_min({round(keepa_min)}) < {tp_key.upper()}_floor({tp_floor}) のためTP下限で固定"
                        )
                else:
                    start_price = min(price, keepa_min)
                remaining_days = max(0, period_end - days_since_listed)
                steps = max(1, math.ceil(remaining_days / interval_days))
                delta = (start_price - tp_floor) / steps if steps > 0 else 0
                new_price = max(tp_floor, round(start_price - delta))
        elif raw_action in ("price_down_1", "price_down_2", "price_down_3", "price_down_4"):
            down_percent = int(raw_action.replace("price_down_", ""))
            new_price = round(price * (1.0 - down_percent / 100.0))
        elif raw_action == "exclude":
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "除外",
                "reason": f"{days_since_listed}日経過: 除外（ルール設定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": _csv_profit_from_inventory_row(row),
                "rule_action": raw_action, "tp_target": tp_key, "akaji": akaji,
                "akaji_drop_percent": akaji_drop_percent, "keepa_min_same_condition": keepa_min,
                "tp_floor": tp_floor,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            excluded_inventory_data.append(row.to_dict())
            continue
        else:
            new_price = round(price)

        # akajiは改定ルールの%を優先して算出する
        # （TP下限に到達した場合でも、akajiは new_price からの%差を維持）
        akaji_guard_from_price = round(new_price * (1.0 - akaji_drop_percent / 100.0))
        final_akaji = max(0, akaji_guard_from_price)
        # TP/akaji下限ガード:
        # - 価格を下げる過程で下限を割り込む場合のみ下限で止める
        # - 既に現在価格が下限以下のときは値上げしない（現在価格維持）
        if price > final_akaji and new_price <= final_akaji:
            new_price = final_akaji
            reason_tokens.append("TP下限に到達（維持）")
        elif price <= final_akaji:
            new_price = round(price)
            reason_tokens.append(
                f"{tp_key.upper()}は{round(tp_floor)}だが現在価格{round(price)}のためTP下限以下判定で{round(price)}維持"
            )
        final_takane = max(new_price, round(new_price * (1.0 + takane_rise_percent / 100.0)))
        is_tp_floor_or_below = bool(tp_floor and tp_floor > 0 and (new_price <= tp_floor or price <= tp_floor))
        tp_reach_status = ""
        if is_tp_floor_or_below:
            # 期間外到達: 期日より前に既にTP以下（市場の想定外下落などを想定）
            if price <= tp_floor and days_since_listed < period_end:
                tp_reach_status = "期間外到達"
            else:
                tp_reach_status = "期間到達"

        reason = " / ".join(reason_tokens)
        row_dict = row.to_dict()
        row_dict["price"] = new_price
        row_dict["priceTrace"] = new_price_trace
        row_dict["akaji"] = final_akaji
        row_dict["takane"] = final_takane
        updated_inventory_data.append(row_dict)
        log_data.append({
            "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": action_jp,
            "reason": reason, "price": price, "new_price": new_price,
            "priceTrace": price_trace, "new_priceTrace": new_price_trace,
            "priceTraceChange": (new_price_trace if raw_action == "priceTrace" else 0),
            "priceTraceChangeDisplay": (format_trace_value(new_price_trace) if raw_action == "priceTrace" else "無し"),
            "csv_profit": _csv_profit_from_inventory_row(row),
            "rule_action": raw_action,
            "tp_target": tp_key,
            "akaji": final_akaji,
            "akaji_drop_percent": akaji_drop_percent,
            "takane": final_takane,
            "takane_rise_percent": takane_rise_percent,
            "keepa_min_same_condition": keepa_min,
            "tp_floor": tp_floor,
            "is_tp_floor_or_below": is_tp_floor_or_below,
            "tp_reach_status": tp_reach_status,
        })

    log_df = pd.DataFrame(log_data)
    updated_df = pd.DataFrame(updated_inventory_data)
    excluded_df = pd.DataFrame(excluded_inventory_data)
    items_list = log_df.to_dict(orient='records')
    return RepriceOutputs(log_df=log_df, updated_df=updated_df, excluded_df=excluded_df, items=items_list)


def apply_repricing_rules(df: pd.DataFrame, today: datetime, mode: str = "standard") -> RepriceOutputs:
    """
    30日間隔価格改定システム - 最新仕様対応
    注: preprocessは呼び出し元（repricer.py）で実行済み
    """
    normalized_mode = "369" if str(mode) == "369" else "standard"
    config = load_config(mode=normalized_mode)
    if normalized_mode == "369":
        return _apply_repricing_rules_369(df, today, config)
    log_data = []
    updated_inventory_data = []
    excluded_inventory_data = []
    excluded_skus = set(config.get("excluded_skus", []))
    sku_candidates = []
    for _, _row in df.iterrows():
        _sku = _row.get("SKU", "")
        if isinstance(_sku, str) and _sku.startswith('="') and _sku.endswith('"'):
            _sku = _sku[2:-1]
        sku_candidates.append(str(_sku or "").strip())
    repricing_enabled_map_by_sku = _load_repricing_enabled_map_from_purchase_db(sku_candidates)

    rules = config["reprice_rules"]

    for index, row in df.iterrows():
        sku = row.get("SKU", "")
        # SKUからExcel数式記法を削除（念のため）
        if isinstance(sku, str) and sku.startswith('="') and sku.endswith('"'):
            sku = sku[2:-1]  # =" と " を除去
        
        price = row.get("price", 0)
        akaji = row.get("akaji", 0)
        price_trace = row.get("priceTrace", 0)

        # 除外SKU処理
        if sku in excluded_skus:
            asin = row.get("ASIN", "")
            title = row.get("title", "")
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "除外",
                "reason": "除外SKU（設定で除外指定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0,
                "priceTraceChangeDisplay": "無し"  # Traceを行わない
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        days_since_listed = get_days_since_listed(sku, today)

        # 日付不明の場合は維持
        if days_since_listed == -1:
            asin = row.get("ASIN", "")
            title = row.get("title", "")
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "維持",
                "reason": "日付不明（維持）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0,
                "priceTraceChangeDisplay": "無し"  # Traceを行わない
            })
            row_dict = row.to_dict()
            updated_inventory_data.append(row_dict)
            continue

        # 365日超過の場合は対象外
        if days_since_listed > 365:
            asin = row.get("ASIN", "")
            title = row.get("title", "")
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "除外",
                "reason": f"{days_since_listed}日経過: 365日超過（要手動対応）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0,
                "priceTraceChangeDisplay": "無し"  # Traceを行わない
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        # ルール適用
        try:
            rule_key, rule = get_rule_for_days(days_since_listed, rules)
            if not rule:
                # ルールが見つからない場合は維持
                rule = {"action": "maintain", "priceTrace": 0}
            action, reason, new_price, new_price_trace = calculate_new_price_and_trace(
                price, akaji, rule, days_since_listed, config, price_trace
            )
        except Exception as e:
            # ルール適用エラーの場合は維持
            print(f"[WARNING] ルール適用エラー (SKU: {sku}): {e}")
            action = "maintain"
            reason = f"ルール適用エラー（維持）: {str(e)}"
            new_price = price
            new_price_trace = price_trace

        # ASINとTitleを取得
        asin = row.get("ASIN", "")
        title = row.get("title", "")
        row_repricing_off = _is_repricing_off(row.get("価格改定"))
        db_repricing_enabled = repricing_enabled_map_by_sku.get(str(sku).strip(), True)
        if row_repricing_off or not db_repricing_enabled:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "除外",
                "reason": "価格改定OFF（仕入DB設定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0,
                "priceTraceChangeDisplay": "無し"
            })
            excluded_inventory_data.append(row.to_dict())
            continue
        
        # priceTraceChangeの計算と表示文字列の決定
        # priceTraceアクションの場合:
        #   - new_price_trace != price_trace: 変更値（日本語表記）
        #   - new_price_trace == price_trace: "元のTrace値維持"（例: "FBA状態合わせ維持"）
        # priceTraceアクション以外: "無し"（文字列）
        if action == "priceTrace":
            if new_price_trace != price_trace:
                # Traceを変更する場合
                price_trace_change = new_price_trace
                price_trace_change_display = format_trace_value(new_price_trace)  # 数値を日本語に変換
            else:
                # Traceを維持する場合（元のTrace値を日本語に変換して表示）
                price_trace_change = price_trace  # 数値として保持（後方互換性のため）
                trace_name = format_trace_value(price_trace)  # 元のTrace値を日本語に変換
                price_trace_change_display = f"{trace_name}維持"  # 例: "FBA状態合わせ維持"
        else:
            # Traceを行わない場合
            price_trace_change = 0  # 数値として保持（後方互換性のため）
            price_trace_change_display = "無し"  # 表示用文字列
        
        # デバッグ出力
        if action == "priceTrace":
            print(f"[DEBUG priceTrace] SKU: {sku}, action: {action}, price_trace: {price_trace}, new_price_trace: {new_price_trace}, price_trace_change: {price_trace_change}, display: {price_trace_change_display}")
        
        # アクション名を日本語に変換
        action_jp = ACTION_NAMES_JP.get(action, action)
        
        # 利益無視（price_down_ignore）の場合はakajiを空白にする（akajiストッパー回避のため）
        akaji_value = "" if action == "price_down_ignore" else None  # Noneの場合は元の値を保持
        
        log_data.append({
            "sku": sku, "asin": asin, "title": title, "days": days_since_listed, 
            "action": action_jp, "reason": reason, "price": price, "new_price": new_price,
            "priceTrace": price_trace, "new_priceTrace": new_price_trace,
            "priceTraceChange": price_trace_change,  # 数値（後方互換性のため）
            "priceTraceChangeDisplay": price_trace_change_display,  # 表示用文字列
            "akaji": akaji_value  # price_down_ignoreの場合は空白、それ以外はNone（元の値を保持）
        })

        # Prister形式の全列を保持したまま価格とpriceTraceのみ更新
        row_dict = row.to_dict()
        if action == "exclude":
            excluded_inventory_data.append(row_dict)
        else:
            # 価格とpriceTraceの更新（Prister形式の16列すべてを保持）
            row_dict['price'] = new_price
            row_dict['priceTrace'] = new_price_trace
            
            # 利益無視（price_down_ignore）の場合はakajiを空白にする（akajiストッパー回避のため）
            if action == "price_down_ignore":
                row_dict['akaji'] = ""  # 空白に設定
            
            updated_inventory_data.append(row_dict)

    log_df = pd.DataFrame(log_data)
    updated_df = pd.DataFrame(updated_inventory_data)
    excluded_df = pd.DataFrame(excluded_inventory_data)

    # CSV出力前の正規化を無効化（元ファイルのフォーマットを完全保持するため）
    # 元のバイト列ベースの処理に切り替えたため、ここでの文字列変換は不要
    # log_df = normalize_dataframe_for_cp932(log_df)
    # updated_df = normalize_dataframe_for_cp932(updated_df)
    # excluded_df = normalize_dataframe_for_cp932(excluded_df)

    items_list = log_df.to_dict(orient='records')

    return RepriceOutputs(log_df=log_df, updated_df=updated_df, excluded_df=excluded_df, items=items_list)
