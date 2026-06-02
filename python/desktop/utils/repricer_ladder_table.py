#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
個別SKUの月別（30日刻み）改定ルール表 — 改定ルールUIと同型で TP列のみ「目標到達価格」に差し替え。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

REPRICER_DAY_RANGES: List[tuple[int, int]] = [
    (1, 30), (31, 60), (61, 90), (91, 120), (121, 150),
    (151, 180), (181, 210), (211, 240), (241, 270),
    (271, 300), (301, 330), (331, 360), (361, 999),
]

# 月別運用表の12行目（1始まり）= 331-360日帯（0始まり index 11）
LADDER_ROW_INDEX_331_360 = 11


def band_start_day_for_period_end(period_end: int) -> int:
    """ルールの days_from（帯の終端日）から、その帯の開始日を返す。"""
    for start, end in REPRICER_DAY_RANGES:
        if end == period_end:
            return start
    return 361 if period_end >= 999 else 1

# 帯終端(days_from) → TP0〜TP3 へのざっくり対応（テンプレコピー時の価格初期値用）
_DAYS_FROM_TO_TP_KEY: Dict[int, str] = {}
for _end in (30, 60, 90):
    _DAYS_FROM_TO_TP_KEY[_end] = "tp0"
for _end in (120, 150, 180):
    _DAYS_FROM_TO_TP_KEY[_end] = "tp1"
for _end in (210, 240, 270):
    _DAYS_FROM_TO_TP_KEY[_end] = "tp2"
for _end in (300, 330, 360, 999):
    _DAYS_FROM_TO_TP_KEY[_end] = "tp3"


# 月別運用テーブル列インデックス
COL_LADDER_DAYS = 0
COL_LADDER_ACTION = 1
COL_LADDER_TRACE = 2
COL_LADDER_TARGET_PRICE = 3
COL_LADDER_AKAJI = 4
COL_LADDER_TAKANE = 5
COL_LADDER_PROFIT_EST = 6

_LADDER_PROFIT_CTX_SALE = "ladder_sale_price"
_LADDER_PROFIT_CTX_BASE = "ladder_base_profit"


def set_ladder_table_profit_context(
    table: QTableWidget,
    sale_price: float,
    base_profit: float,
) -> None:
    """TP概算と同じ基準（販売予定・見込み利益）を月別運用表に渡す。"""
    table.setProperty(_LADDER_PROFIT_CTX_SALE, float(sale_price or 0))
    table.setProperty(_LADDER_PROFIT_CTX_BASE, float(base_profit or 0))


def _ladder_profit_context(table: QTableWidget) -> tuple[float, float]:
    sale = table.property(_LADDER_PROFIT_CTX_SALE)
    base = table.property(_LADDER_PROFIT_CTX_BASE)
    try:
        sale_f = float(sale) if sale is not None else 0.0
    except (TypeError, ValueError):
        sale_f = 0.0
    try:
        base_f = float(base) if base is not None else 0.0
    except (TypeError, ValueError):
        base_f = 0.0
    return sale_f, base_f


def _parse_ladder_price_text(text: str) -> float:
    if not text or not str(text).strip():
        return 0.0
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return 0.0


def format_ladder_estimated_profit(
    sale_price: float,
    base_profit: float,
    target_price: float,
) -> str:
    """TP価格欄と同式: 概算利益 = 見込み利益 - 0.89 × (販売予定 - 目標到達価格)。"""
    if target_price <= 0 or sale_price <= 0:
        return "-"
    profit = base_profit - 0.89 * (sale_price - target_price)
    rate = (profit / target_price * 100.0) if target_price else None
    if rate is None:
        return "-"
    return f"{int(round(profit)):,}（{rate:.1f}%）"


def update_ladder_profit_labels(table: QTableWidget, row: Optional[int] = None) -> None:
    sale_price, base_profit = _ladder_profit_context(table)
    rows = [row] if row is not None else range(table.rowCount())
    for i in rows:
        lbl = table.cellWidget(i, COL_LADDER_PROFIT_EST)
        if not isinstance(lbl, QLabel):
            continue
        price_edit = table.cellWidget(i, COL_LADDER_TARGET_PRICE)
        target = _parse_ladder_price_text(price_edit.text()) if price_edit else 0.0
        lbl.setText(format_ladder_estimated_profit(sale_price, base_profit, target))
        lbl.setToolTip(
            "販売予定価格・見込み利益を基準に、目標到達価格での概算利益（TP価格欄と同じ計算式）"
        )


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


def get_action_options(include_tp_down: bool = True) -> List[tuple[str, str]]:
    actions = [
        ("maintain", "維持"),
        ("priceTrace", "priceTrace"),
        ("instant_reprice", "即時改定"),
        ("price_down_1", "1%値下げ"),
        ("price_down_2", "2%値下げ"),
        ("price_down_3", "3%値下げ"),
        ("price_down_4", "4%値下げ"),
        ("price_down_ignore_1", "1%利益無視値下げ"),
        ("price_down_ignore_2", "2%利益無視値下げ"),
        ("price_down_ignore_3", "3%利益無視値下げ"),
        ("price_down_ignore_4", "4%利益無視値下げ"),
        ("exclude", "対象外"),
    ]
    if include_tp_down:
        actions.insert(2, ("tp_down", "TP値下げ"))
    return actions


def get_price_trace_options() -> List[tuple[int, str]]:
    return [
        (0, "追従無し"),
        (1, "FBA状態合わせ"),
        (2, "状態合わせ"),
        (3, "FBA最安値"),
        (4, "最安値"),
        (5, "カート価格"),
    ]


def create_ladder_rules_table(parent: Optional[QWidget] = None) -> QTableWidget:
    table = QTableWidget(parent)
    columns = [
        "出品日数", "アクション", "priceTrace設定", "目標到達価格",
        "akaji下限(%)", "takane上限(%)", "概算利益（利益率）",
    ]
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setAlternatingRowColors(True)
    table.setProperty("is_ladder_table", True)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    populate_ladder_table_rows(table, connect_action_signals=False)
    return table


def populate_ladder_table_rows(table: QTableWidget, *, connect_action_signals: bool = False) -> None:
    actions = get_action_options(include_tp_down=True)
    price_trace_options = get_price_trace_options()
    akaji_options = [(v, f"{v}%") for v in range(1, 11)]
    takane_options = [(v, f"{v}%") for v in range(0, 11)]

    table.setRowCount(len(REPRICER_DAY_RANGES))
    for i, (start_day, end_day) in enumerate(REPRICER_DAY_RANGES):
        if end_day == 999:
            days_text = f"{start_day}日～"
        else:
            days_text = f"{start_day}-{end_day}日"
        days_item = QTableWidgetItem(days_text)
        days_item.setFlags(days_item.flags() & ~Qt.ItemIsEditable)
        table.setItem(i, 0, days_item)

        action_combo = NoWheelComboBox()
        for key, label in actions:
            action_combo.addItem(label, key)
        action_combo.setEditable(False)
        if connect_action_signals:
            action_combo.currentTextChanged.connect(
                lambda _t, row=i, tbl=table: update_price_trace_visibility(tbl, row)
            )
        table.setCellWidget(i, COL_LADDER_ACTION, action_combo)

        trace_combo = NoWheelComboBox()
        for val, label in price_trace_options:
            trace_combo.addItem(label, val)
        trace_combo.setEditable(False)
        table.setCellWidget(i, COL_LADDER_TRACE, trace_combo)

        price_edit = QLineEdit()
        price_edit.setPlaceholderText("例: 6400")
        price_edit.textChanged.connect(
            lambda _t, tbl=table, row=i: update_ladder_profit_labels(tbl, row)
        )
        table.setCellWidget(i, COL_LADDER_TARGET_PRICE, price_edit)

        akaji_combo = NoWheelComboBox()
        for val, label in akaji_options:
            akaji_combo.addItem(label, val)
        akaji_combo.setCurrentIndex(1)  # 2%
        table.setCellWidget(i, COL_LADDER_AKAJI, akaji_combo)

        takane_combo = NoWheelComboBox()
        for val, label in takane_options:
            takane_combo.addItem(label, val)
        table.setCellWidget(i, COL_LADDER_TAKANE, takane_combo)

        profit_lbl = QLabel("-")
        profit_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        profit_lbl.setStyleSheet("color: #e0e0e0; padding-right: 4px;")
        table.setCellWidget(i, COL_LADDER_PROFIT_EST, profit_lbl)

    update_price_trace_visibility(table)
    update_ladder_profit_labels(table)


_LADDER_PAST_ROW_BG = QColor(38, 38, 38)
_LADDER_PAST_ROW_FG = QColor(105, 105, 105)
_LADDER_PAST_ROW_MARKER = "elapsed_past"


def _is_ladder_row_elapsed_past(elapsed_days: Optional[int], end_day: int) -> bool:
    """経過日数が帯の終了日を超えていれば、その帯は編集不可（経過済み）。"""
    if elapsed_days is None:
        return False
    return elapsed_days > end_day


def apply_ladder_row_elapsed_lock(table: QTableWidget, elapsed_days: Optional[int]) -> None:
    """経過済みの出品日数帯の行をグレー表示・編集不可にする。"""
    for i, (_start_day, end_day) in enumerate(REPRICER_DAY_RANGES):
        is_past = _is_ladder_row_elapsed_past(elapsed_days, end_day)
        days_item = table.item(i, 0)
        if days_item:
            days_item.setData(Qt.UserRole, _LADDER_PAST_ROW_MARKER if is_past else None)
            if is_past:
                days_item.setBackground(QBrush(_LADDER_PAST_ROW_BG))
                days_item.setForeground(QBrush(_LADDER_PAST_ROW_FG))
                days_item.setToolTip(f"経過日数 {elapsed_days} 日のため、この期間（{days_item.text()}）は編集できません。")
            else:
                days_item.setBackground(QBrush())
                days_item.setForeground(QBrush())
                days_item.setToolTip("")

        for col in range(1, table.columnCount()):
            if col == COL_LADDER_PROFIT_EST:
                continue
            widget = table.cellWidget(i, col)
            if widget is None:
                continue
            widget.setEnabled(not is_past)
            if isinstance(widget, QLineEdit):
                widget.setReadOnly(is_past)
                if is_past:
                    widget.setStyleSheet("color: #696969; background-color: #262626;")
                else:
                    widget.setStyleSheet("")

    update_price_trace_visibility(table)
    update_ladder_profit_labels(table)


def _set_trace_combo_to_no_follow(trace_combo: QComboBox) -> None:
    """priceTrace設定を「追従無し」(0) にリセットする。"""
    idx = trace_combo.findData(0)
    if idx >= 0:
        trace_combo.setCurrentIndex(idx)


def update_price_trace_visibility(table: QTableWidget, row: Optional[int] = None) -> None:
    rows = [row] if row is not None else range(table.rowCount())
    for i in rows:
        days_item = table.item(i, 0)
        if days_item and days_item.data(Qt.UserRole) == _LADDER_PAST_ROW_MARKER:
            trace_combo = table.cellWidget(i, 2)
            if trace_combo:
                trace_combo.setEnabled(False)
            continue
        action_combo = table.cellWidget(i, 1)
        trace_combo = table.cellWidget(i, 2)
        if not action_combo or not trace_combo:
            continue
        action = action_combo.currentData()
        if action == "priceTrace":
            trace_combo.setEnabled(True)
            trace_combo.setStyleSheet("")
        else:
            _set_trace_combo_to_no_follow(trace_combo)
            trace_combo.setEnabled(False)
            trace_combo.setStyleSheet("background-color: #262626; color: #696969;")


def _end_day_from_row(table: QTableWidget, row: int) -> int:
    days_item = table.item(row, 0)
    if not days_item:
        return 999
    days_text = days_item.text()
    if "～" in days_text:
        return 999
    return int(days_text.split("-")[1].replace("日", ""))


def collect_ladder_rules_from_table(table: QTableWidget) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    for i in range(table.rowCount()):
        action_combo = table.cellWidget(i, COL_LADDER_ACTION)
        trace_combo = table.cellWidget(i, COL_LADDER_TRACE)
        price_edit = table.cellWidget(i, COL_LADDER_TARGET_PRICE)
        akaji_combo = table.cellWidget(i, COL_LADDER_AKAJI)
        takane_combo = table.cellWidget(i, COL_LADDER_TAKANE)
        if not action_combo or not trace_combo:
            continue
        action = action_combo.currentData()
        if isinstance(action, str) and action.startswith("price_down_ignore_"):
            action = "price_down_ignore"
        price_text = price_edit.text().strip() if price_edit else ""
        target_price: Optional[float] = None
        if price_text:
            try:
                target_price = float(price_text.replace(",", ""))
            except ValueError:
                target_price = None
        rule: Dict[str, Any] = {
            "days_from": _end_day_from_row(table, i),
            "action": action,
            "value": trace_combo.currentData(),
            "target_price": target_price,
            "akaji_drop_percent": int(akaji_combo.currentData()) if akaji_combo else 1,
            "takane_rise_percent": int(takane_combo.currentData()) if takane_combo else 0,
        }
        rules.append(rule)
    return rules


def apply_ladder_rules_to_table(table: QTableWidget, rules: List[Dict[str, Any]]) -> None:
    rules_by_end: Dict[str, Dict[str, Any]] = {}
    for rule in rules or []:
        df = rule.get("days_from")
        if df is not None:
            rules_by_end[str(int(df))] = rule

    for i in range(table.rowCount()):
        end_key = str(_end_day_from_row(table, i))
        rule = rules_by_end.get(end_key)
        if not rule:
            continue
        action_combo = table.cellWidget(i, COL_LADDER_ACTION)
        trace_combo = table.cellWidget(i, COL_LADDER_TRACE)
        price_edit = table.cellWidget(i, COL_LADDER_TARGET_PRICE)
        akaji_combo = table.cellWidget(i, COL_LADDER_AKAJI)
        takane_combo = table.cellWidget(i, COL_LADDER_TAKANE)

        if action_combo:
            action = rule.get("action", "maintain")
            if action == "price_down_ignore":
                action = "price_down_ignore_1"
            idx = action_combo.findData(action)
            if idx >= 0:
                action_combo.setCurrentIndex(idx)

        if trace_combo:
            val = rule.get("value", rule.get("priceTrace", 0))
            idx = trace_combo.findData(val)
            if idx >= 0:
                trace_combo.setCurrentIndex(idx)

        if price_edit:
            tp = rule.get("target_price")
            if tp is not None and float(tp) > 0:
                price_edit.setText(str(int(round(float(tp)))))
            else:
                price_edit.clear()

        if akaji_combo:
            ap = int(rule.get("akaji_drop_percent", 1) or 1)
            idx = akaji_combo.findData(ap)
            if idx >= 0:
                akaji_combo.setCurrentIndex(idx)

        if takane_combo:
            tr = int(rule.get("takane_rise_percent", 0) or 0)
            idx = takane_combo.findData(tr)
            if idx >= 0:
                takane_combo.setCurrentIndex(idx)

    update_price_trace_visibility(table)
    update_ladder_profit_labels(table)


def parse_ladder_rules_json(raw: Any) -> List[Dict[str, Any]]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
    return []


def ladder_rules_to_json(rules: List[Dict[str, Any]]) -> str:
    return json.dumps(rules, ensure_ascii=False)


def margin_percent_from_target_price(
    sale_price: float,
    base_profit: float,
    target_price: float,
) -> Optional[float]:
    """目標到達価格での概算利益率(%)（TP欄・月別表と同式）。"""
    if target_price <= 0 or sale_price <= 0:
        return None
    profit = base_profit - 0.89 * (sale_price - target_price)
    return (profit / target_price) * 100.0


def target_price_from_margin_percent(
    sale_price: float,
    base_profit: float,
    margin_percent: float,
) -> Optional[float]:
    """概算利益率(%)から目標到達価格を逆算（TP欄・月別表と同式）。"""
    m = float(margin_percent) / 100.0
    denom = m - 0.89
    if abs(denom) < 1e-9:
        return None
    price = (base_profit - 0.89 * sale_price) / denom
    if price <= 0:
        return None
    return price


def compute_ladder_even_margin_prices(
    *,
    elapsed_days: Optional[int],
    sale_price: float,
    base_profit: float,
    final_margin_percent: float = 0.0,
    end_row_index: int = LADDER_ROW_INDEX_331_360,
    start_price_hint: Optional[float] = None,
) -> tuple[Dict[int, Optional[float]], str, int]:
    """
    現在以降の最初の帯から end_row_index まで等間隔で利益率を下げ、
    各帯の終了日(days_from) → 目標到達価格 の辞書を返す。
    """
    prices_by_end: Dict[int, Optional[float]] = {}
    if sale_price <= 0:
        return prices_by_end, "販売予定価格が0以下のため計算できません。", 0

    row_count = len(REPRICER_DAY_RANGES)
    end_row = min(max(0, end_row_index), row_count - 1)

    start_row: Optional[int] = None
    for i in range(row_count):
        _start, end_day = REPRICER_DAY_RANGES[i]
        if not _is_ladder_row_elapsed_past(elapsed_days, end_day):
            start_row = i
            break

    if start_row is None:
        return prices_by_end, "経過済みの帯のみで、入力できる帯がありません。", 0

    if start_row > end_row:
        return prices_by_end, "現在以降の帯が331-360日帯より後になっています。", 0

    if start_price_hint and start_price_hint > 0:
        start_margin = margin_percent_from_target_price(sale_price, base_profit, start_price_hint)
    else:
        start_margin = margin_percent_from_target_price(sale_price, base_profit, sale_price)

    if start_margin is None:
        return prices_by_end, "開始帯の利益率を計算できません。", 0

    final_margin = float(final_margin_percent)
    n_steps = end_row - start_row
    filled = 0

    for i in range(row_count):
        _start, end_day = REPRICER_DAY_RANGES[i]
        if _is_ladder_row_elapsed_past(elapsed_days, end_day):
            prices_by_end[end_day] = None
            continue
        if i < start_row or i > end_row:
            prices_by_end[end_day] = None
            continue

        if n_steps <= 0:
            margin = final_margin
        else:
            k = i - start_row
            t = k / n_steps
            margin = start_margin + (final_margin - start_margin) * t

        price = target_price_from_margin_percent(sale_price, base_profit, margin)
        if price is None:
            prices_by_end[end_day] = None
            continue
        if sale_price > 0 and price > sale_price:
            price = sale_price
        prices_by_end[end_day] = float(int(round(price)))
        filled += 1

    return prices_by_end, "", filled


def build_ladder_rules_with_standard_trace(
    *,
    elapsed_days: Optional[int],
    sale_price: float,
    base_profit: float,
    final_margin_percent: float = 0.0,
    end_row_index: int = LADDER_ROW_INDEX_331_360,
    action: str = "priceTrace",
    trace_value: int = 1,
    akaji_drop_percent: int = 2,
    takane_rise_percent: int = 1,
) -> tuple[List[Dict[str, Any]], str, int]:
    """月別運用ルール JSON 用のルール配列を生成（一括・UIなし）。"""
    prices_by_end, err, filled = compute_ladder_even_margin_prices(
        elapsed_days=elapsed_days,
        sale_price=sale_price,
        base_profit=base_profit,
        final_margin_percent=final_margin_percent,
        end_row_index=end_row_index,
    )
    if err and filled == 0:
        return [], err, 0

    rules: List[Dict[str, Any]] = []
    for _start, end_day in REPRICER_DAY_RANGES:
        tp = prices_by_end.get(end_day)
        rules.append(
            {
                "days_from": end_day,
                "action": action,
                "value": trace_value,
                "target_price": tp,
                "akaji_drop_percent": akaji_drop_percent,
                "takane_rise_percent": takane_rise_percent,
            }
        )
    return rules, err, filled


def apply_even_margin_descent_to_ladder_table(
    table: QTableWidget,
    *,
    elapsed_days: Optional[int],
    final_margin_percent: float,
    sale_price: float,
    base_profit: float,
    end_row_index: int = LADDER_ROW_INDEX_331_360,
) -> tuple[bool, str, int]:
    """
    現在以降の最初の帯から end_row_index（既定: 331-360日）まで、
    概算利益率を等間隔で下げながら目標到達価格を埋める。
    """
    if sale_price <= 0:
        return False, "販売予定価格が0以下のため計算できません。", 0

    row_count = table.rowCount()
    if row_count == 0:
        return False, "月別運用ルール表が空です。", 0

    end_row = min(max(0, end_row_index), row_count - 1)

    start_row: Optional[int] = None
    for i in range(row_count):
        if i >= len(REPRICER_DAY_RANGES):
            break
        _start, end_day = REPRICER_DAY_RANGES[i]
        if not _is_ladder_row_elapsed_past(elapsed_days, end_day):
            start_row = i
            break

    if start_row is None:
        return False, "経過済みの帯のみで、入力できる帯がありません。", 0

    if start_row > end_row:
        return False, "現在以降の帯が331-360日帯より後になっています。", 0

    price_edit0 = table.cellWidget(start_row, COL_LADDER_TARGET_PRICE)
    start_price = _parse_ladder_price_text(price_edit0.text()) if price_edit0 else 0.0

    prices_by_end, err, filled = compute_ladder_even_margin_prices(
        elapsed_days=elapsed_days,
        sale_price=sale_price,
        base_profit=base_profit,
        final_margin_percent=final_margin_percent,
        end_row_index=end_row_index,
        start_price_hint=start_price if start_price > 0 else None,
    )
    if filled == 0:
        return False, err or "価格を設定できた帯がありません。", 0

    skipped: List[str] = []
    applied = 0
    for i in range(start_row, end_row + 1):
        if i >= len(REPRICER_DAY_RANGES):
            break
        _start, end_day = REPRICER_DAY_RANGES[i]
        price = prices_by_end.get(end_day)
        if price is None:
            continue
        price_edit = table.cellWidget(i, COL_LADDER_TARGET_PRICE)
        if not isinstance(price_edit, QLineEdit):
            skipped.append(f"行{i + 1}")
            continue
        price_edit.setText(str(int(round(price))))
        applied += 1

    filled = applied
    update_ladder_profit_labels(table, row=None)

    start_label = table.item(start_row, 0)
    end_label = table.item(end_row, 0)
    start_txt = start_label.text() if start_label else str(start_row + 1)
    end_txt = end_label.text() if end_label else str(end_row + 1)

    msg = (
        f"{start_txt}〜{end_txt} の {filled} 帯に目標到達価格を設定しました。\n"
        f"最終利益率 {float(final_margin_percent):.1f}% まで等間隔で配分しました。"
    )
    if skipped:
        msg += f"\n（スキップ: {', '.join(skipped)}）"
    if filled == 0:
        return False, "価格を設定できた帯がありません。", 0
    return True, msg, filled


def load_reprice_config_for_template() -> Dict[str, Any]:
    from pathlib import Path
    try:
        from core.config import CONFIG_PATH
        path = CONFIG_PATH
    except ImportError:
        path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "reprice_rules.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def template_rules_from_default_profile(
    config: Dict[str, Any],
    *,
    tp_prices: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """デフォルトプロファイルの改定ルールを個別ラダー用に変換（TP→target_price）。"""
    profile_key = str(config.get("default_profile", "6"))
    profiles = config.get("rule_profiles", {}) or {}
    profile_rules = (profiles.get(profile_key) or {}).get("reprice_rules", [])
    if not profile_rules:
        return []

    tp_prices = tp_prices or {}
    out: List[Dict[str, Any]] = []
    for rule in profile_rules:
        days_from = int(rule.get("days_from", 999) or 999)
        tp_key = _DAYS_FROM_TO_TP_KEY.get(days_from, str(rule.get("tp_target", "tp0")).lower())
        target: Optional[float] = None
        raw_tp = tp_prices.get(tp_key) or tp_prices.get(tp_key.upper())
        if raw_tp not in (None, ""):
            try:
                target = float(str(raw_tp).replace(",", ""))
            except ValueError:
                target = None
        item = {
            "days_from": days_from,
            "action": rule.get("action", "maintain"),
            "value": rule.get("value", 0),
            "target_price": target,
            "akaji_drop_percent": int(rule.get("akaji_drop_percent", 1) or 1),
            "takane_rise_percent": int(rule.get("takane_rise_percent", 0) or 0),
        }
        out.append(item)
    return out
