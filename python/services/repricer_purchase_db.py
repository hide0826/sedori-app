import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List


def _resolve_purchase_db_path() -> Path:
    """仕入DB(hirio.db)の想定パスを返す。"""
    return Path(__file__).resolve().parent.parent / "desktop" / "data" / "hirio.db"


def to_float_or_none_strict(value: Any) -> float:
    """数値化できる値のみfloatを返す。空/不正値はNone。"""
    try:
        if value is None:
            return None
        s = str(value).strip().replace(",", "")
        if s == "" or s.lower() in ("nan", "none"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def csv_profit_from_inventory_row(row: Any) -> float:
    """在庫CSVの現在見込み利益を取得。profit 欠損時は price/cost/手数料から補完する。"""
    try:
        if row is None:
            return 0.0
        get_value = row.get if hasattr(row, "get") else (lambda _key, _default=None: _default)

        profit = to_float_or_none_strict(get_value("profit"))
        if profit not in (None, 0):
            return float(profit)

        price = to_float_or_none_strict(get_value("price"))
        cost = to_float_or_none_strict(get_value("cost"))
        if price is None or cost is None:
            return float(profit or 0.0)

        amazon_fee = to_float_or_none_strict(get_value("amazon-fee")) or 0.0
        shipping_price = to_float_or_none_strict(get_value("shipping-price")) or 0.0
        return float(price - cost - amazon_fee - shipping_price)
    except Exception:
        return 0.0


def is_repricing_off(value: Any) -> bool:
    """価格改定ON/OFF表現を判定。True=OFF（改定除外）。"""
    if value is None:
        return False
    s = str(value).strip().lower()
    if s == "":
        return False
    return s in {"0", "off", "false", "無効", "いいえ", "no"}


def load_tp_map_from_purchase_db(sku_list: List[str]) -> Dict[str, Dict[str, float]]:
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
                    "tp0": to_float_or_none_strict(row["tp0"]),
                    "tp1": to_float_or_none_strict(row["tp1"]),
                    "tp2": to_float_or_none_strict(row["tp2"]),
                    "tp3": to_float_or_none_strict(row["tp3"]),
                }
        conn.close()
    except Exception as e:
        # 仕入DB参照で失敗しても改定処理自体は継続（従来%計算へフォールバック）
        print(f"[WARNING 3-6-9 TP] 仕入DBのTP読込に失敗: {e}")
    return result


def load_repricing_enabled_map_from_purchase_db(sku_list: List[str]) -> Dict[str, bool]:
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
                result[sku] = not is_repricing_off(row["repricing_enabled"])
        conn.close()
    except Exception as e:
        print(f"[WARNING REPRICE FLAG] 仕入DBの価格改定フラグ読込に失敗: {e}")

    return result


def load_ladder_map_from_purchase_db(sku_list: List[str]) -> Dict[str, Dict[str, Any]]:
    """仕入DBから月別運用（個別ラダー）設定を読み込む。"""
    result: Dict[str, Dict[str, Any]] = {}
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
                f"SELECT sku, ladder_enabled, ladder_rules FROM purchases WHERE sku IN ({placeholders})",
                tuple(chunk),
            )
            for row in cur.fetchall():
                sku = str(row["sku"] or "").strip()
                if not sku:
                    continue
                enabled_raw = row["ladder_enabled"]
                enabled = str(enabled_raw).strip().lower() in ("1", "true", "on", "yes")
                rules_raw = row["ladder_rules"]
                rules: List[Dict[str, Any]] = []
                if rules_raw:
                    try:
                        parsed = json.loads(rules_raw) if isinstance(rules_raw, str) else rules_raw
                        if isinstance(parsed, list):
                            rules = parsed
                    except (json.JSONDecodeError, TypeError):
                        rules = []
                result[sku] = {"enabled": enabled, "rules": rules}
        conn.close()
    except Exception as e:
        print(f"[WARNING LADDER] 仕入DBの月別運用読込に失敗: {e}")
    return result


# 後方互換のエイリアス（テスト monkeypatch 用）
_load_tp_map_from_purchase_db = load_tp_map_from_purchase_db
_load_repricing_enabled_map_from_purchase_db = load_repricing_enabled_map_from_purchase_db
_load_ladder_map_from_purchase_db = load_ladder_map_from_purchase_db
_csv_profit_from_inventory_row = csv_profit_from_inventory_row
_is_repricing_off = is_repricing_off
_to_float_or_none_strict = to_float_or_none_strict
