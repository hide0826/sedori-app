import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Tuple

import pandas as pd

from core.config import CONFIG_PATH

# アクション名の日本語マッピング
ACTION_NAMES_JP = {
    "maintain": "維持",
    "priceTrace": "Trace変更",
    "instant_reprice": "即時改定",
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
            config.setdefault("repricer_preset_369", "custom")
            preset = str(config.get("repricer_preset_369") or "").strip().lower()
            if "tp0_floor_guard" not in config:
                config["tp0_floor_guard"] = preset == "profit"
            if "tp0_gradual_follow" not in config:
                config["tp0_gradual_follow"] = preset == "turnover"

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


def to_float_or_none(value: Any) -> float:
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
