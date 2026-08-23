#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入行編集ダイアログ共通（定数・ヘルパー）。"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

try:
    from utils._purchase_repricer_imports import (
        apply_even_margin_descent_to_ladder_table,
        apply_ladder_rules_to_table,
        apply_ladder_row_elapsed_lock,
        calc_elapsed_days_for_purchase_record,
        collect_ladder_rules_from_table,
        create_ladder_rules_table,
        format_elapsed_days_for_purchase_record,
        get_amazon_fba_simulator_url,
        ladder_rules_to_json,
        load_reprice_config_for_template,
        margin_percent_from_target_price,
        parse_ladder_rules_json,
        populate_ladder_table_rows,
        set_ladder_table_profit_context,
        template_rules_from_default_profile,
        update_ladder_profit_labels,
    )
    from utils._desktop_import_compat import (
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        KeepaOfferDetailDialog,
        KeepaService,
        PurchaseDatabase,
        TP_SOURCE_AUTO,
        TP_SOURCE_MANUAL,
        apply_fee_values_to_record,
        break_even_price_int_for_record,
        condition_code_from_value,
        flea_fee_rate_percent_for_channel,
        is_amazon_sales_channel,
        normalize_condition_display,
        platform_fee_from_sale_price,
        read_fee_fields,
        ta_price_from_target_margin_percent,
    )
except ImportError:
    from desktop.utils._purchase_repricer_imports import (  # type: ignore
        apply_even_margin_descent_to_ladder_table,
        apply_ladder_rules_to_table,
        apply_ladder_row_elapsed_lock,
        calc_elapsed_days_for_purchase_record,
        collect_ladder_rules_from_table,
        create_ladder_rules_table,
        format_elapsed_days_for_purchase_record,
        get_amazon_fba_simulator_url,
        ladder_rules_to_json,
        load_reprice_config_for_template,
        margin_percent_from_target_price,
        parse_ladder_rules_json,
        populate_ladder_table_rows,
        set_ladder_table_profit_context,
        template_rules_from_default_profile,
        update_ladder_profit_labels,
    )
    from desktop.utils._desktop_import_compat import (  # type: ignore
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        KeepaOfferDetailDialog,
        KeepaService,
        PurchaseDatabase,
        TP_SOURCE_AUTO,
        TP_SOURCE_MANUAL,
        apply_fee_values_to_record,
        break_even_price_int_for_record,
        condition_code_from_value,
        flea_fee_rate_percent_for_channel,
        is_amazon_sales_channel,
        normalize_condition_display,
        platform_fee_from_sale_price,
        read_fee_fields,
        ta_price_from_target_margin_percent,
    )

_TP_DIALOG_TIER_COLORS = ("#6ecff6", "#7ae495", "#f0c674", "#e8a0bf")
_TP_BAND_END_DAYS = (90, 180, 270, 365)
_TP_BAND_LABELS = {
    "tp0": "TP0（〜90日帯）",
    "tp1": "TP1（91〜180日帯）",
    "tp2": "TP2（181〜270日帯）",
    "tp3": "TP3（271日〜）",
}
_TRACE_LABELS_JP = {
    0: "維持",
    1: "FBA状態合わせ",
    2: "状態合わせ",
    3: "FBA最安値",
    4: "最安値",
    5: "カート価格",
}
_CHECKBOX_INDICATOR_STYLE = (
    "QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #888888; "
    "background-color: #252525; border-radius: 3px; }"
    "QCheckBox::indicator:checked { background-color: #3d7ec4; border-color: #5a9ee0; }"
)
_CHECKBOX_DARK_STYLE = (
    "QCheckBox {"
    "  background-color: #1a1a1a;"
    "  color: #ffffff;"
    "  border: 1px solid #555555;"
    "  border-radius: 4px;"
    "  padding: 6px 10px;"
    "  spacing: 8px;"
    "}"
    + _CHECKBOX_INDICATOR_STYLE
    + "QCheckBox:disabled { color: #888888; background-color: #2a2a2a; }"
)
_LADDER_ROW_WRAP_STYLE = "background-color: #1a1a1a; border: 1px solid #555555; border-radius: 4px;"
_LADDER_LABEL_STYLE = "color: #ffffff; background-color: transparent; font-size: 13px;"
def _apply_checkbox_dark_style(checkbox: QCheckBox) -> None:
    checkbox.setStyleSheet(_CHECKBOX_DARK_STYLE)
def _create_ladder_checkbox_row(
    label_text: str,
    *,
    tooltip: str = "",
) -> Tuple[QWidget, QCheckBox]:
    """月別運用用: チェックとラベルを分離し、黒背景でラベルを必ず表示する。"""
    wrap = QWidget()
    wrap.setStyleSheet(_LADDER_ROW_WRAP_STYLE)
    row = QHBoxLayout(wrap)
    row.setContentsMargins(8, 6, 8, 6)
    row.setSpacing(10)
    cb = QCheckBox()
    cb.setStyleSheet(_CHECKBOX_INDICATOR_STYLE)
    lbl = QLabel(label_text)
    lbl.setStyleSheet(_LADDER_LABEL_STYLE)
    lbl.setWordWrap(True)
    if tooltip:
        cb.setToolTip(tooltip)
        lbl.setToolTip(tooltip)
        wrap.setToolTip(tooltip)
    row.addWidget(cb, 0)
    row.addWidget(lbl, 1)
    return wrap, cb
_SALES_CHANNEL_OPTIONS = ["Amazon", "メルカリ", "ヤフオク", "ラクマ", "その他"]
_SHIPPING_METHOD_OPTIONS = ["FBA", "自己発送"]
_CONDITION_OPTIONS = [
    "新品",
    "新品(新品)",
    "中古(ほぼ新品)",
    "中古(非常に良い)",
    "中古(良い)",
    "中古(可)",
    "コレクター商品(ほぼ新品)",
    "コレクター商品(非常に良い)",
    "コレクター商品(良い)",
    "コレクター商品(可)",
    "再生品",
]
_SKU_DATE_BLOCKED_STATUS_CODES = frozenset({"sold", "partially_sold"})
_SKU_DATE_BLOCKED_LABELS = frozenset({"販売済み", "一部販売済み"})
def _normalized_purchase_status_code(record: Dict[str, Any]) -> str:
    raw = record.get("ステータス") if record.get("ステータス") is not None else record.get("status")
    if raw is None or str(raw).strip() == "":
        return "ready"
    s = str(raw).strip()
    if s in _SKU_DATE_BLOCKED_LABELS:
        return {
            "販売済み": "sold",
            "一部販売済み": "partially_sold",
        }[s]
    if s == "販売中":
        return "selling"
    return s.lower()
def _sku_date_edit_locked(record: Dict[str, Any]) -> bool:
    return _normalized_purchase_status_code(record) in _SKU_DATE_BLOCKED_STATUS_CODES
def _split_sku_leading_date(sku: str) -> Tuple[Optional[str], str]:
    """先頭が YYYYMMDD のとき (8桁, 残り) を返す。それ以外は (None, 全体)。"""
    sku = (sku or "").strip()
    if len(sku) >= 8 and sku[:8].isdigit():
        return sku[:8], sku[8:]
    return None, sku
def _is_valid_yyyymmdd(s: str) -> bool:
    if len(s) != 8 or not s.isdigit():
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
        return True
    except ValueError:
        return False
def _style_tp_tier_text(color: str, *widgets: QWidget) -> None:
    for w in widgets:
        w.setStyleSheet(f"color: {color};")
def _tp_band_from_days(days: int) -> Tuple[str, int, str]:
    """経過日数から TP 帯キー・帯終端日・表示ラベルを返す。"""
    if days <= 0 or days == -1:
        return "tp0", 90, _TP_BAND_LABELS["tp0"]
    if days <= 90:
        return "tp0", 90, _TP_BAND_LABELS["tp0"]
    if days <= 180:
        return "tp1", 180, _TP_BAND_LABELS["tp1"]
    if days <= 270:
        return "tp2", 270, _TP_BAND_LABELS["tp2"]
    return "tp3", 365, _TP_BAND_LABELS["tp3"]
def _tp_tier_index_from_key(tp_key: str) -> Optional[int]:
    mapping = {"tp0": 0, "tp1": 1, "tp2": 2, "tp3": 3}
    raw = str(tp_key or "").strip().lower()
    if raw in ("tp0_maintain", "tp0_follow"):
        return 0
    return mapping.get(raw)
def _format_trace_change_label(raw: Any) -> str:
    if raw is None or str(raw).strip() == "":
        return "-"
    text = str(raw).strip()
    if text in ("無し", "なし", "-"):
        return "無し"
    try:
        trace_int = int(float(text))
        return _TRACE_LABELS_JP.get(trace_int, text)
    except (TypeError, ValueError):
        return text
def _has_repricer_preview_fields(snap: Dict[str, Any]) -> bool:
    if not snap:
        return False
    for key in ("new_price", "action", "tp_target", "reason", "rule_action"):
        if snap.get(key) not in (None, ""):
            return True
    return False
def _parse_number(val: Any) -> float:
    """文字列や数値から float を取得。空・不正は 0。"""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(re.sub(r"[^\d.\-]", "", s))
    except (ValueError, TypeError):
        return 0.0
def _format_price(val: float) -> str:
    if val == 0:
        return "-"
    return f"{int(val):,}"
def _try_resize_browser_half_screen_win() -> None:
    """Windows のみ: Keepa のブラウザウィンドウを前面に出し、モニターの右半分にリサイズする"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        found_hwnd: List[wintypes.HWND] = []

        def enum_cb(hwnd: wintypes.HWND, _: wintypes.LPARAM) -> wintypes.BOOL:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value or ""
            # 「keepa」を含むが、編集ダイアログ（仕入行の編集）は除外＝ブラウザだけリサイズする
            if "keepa" in title.lower() and "仕入行の編集" not in title:
                found_hwnd.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        if not found_hwnd:
            return
        hwnd = found_hwnd[0]

        # メインモニターの作業領域（タスクバー除く）を取得
        SPI_GETWORKAREA = 0x0030
        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
        work = RECT()
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        w = work.right - work.left
        h = work.bottom - work.top
        half_w = w // 2

        # 前面に出す
        user32.SetForegroundWindow(hwnd)
        # 右半分に移動・リサイズ（編集ダイアログは左上に表示されるので左半分が空く）
        user32.MoveWindow(hwnd, work.left + half_w, work.top, half_w, h, True)
        # 注: ブラウザを HWND_TOPMOST にすると全画面になることがあるため行わない
    except Exception:
        pass
def _minimize_keepa_browser_win() -> None:
    """Windows のみ: タイトルに Keepa を含むブラウザウィンドウをすべて最小化する"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        SW_MINIMIZE = 6
        GA_ROOT = 2

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        targets: list[wintypes.HWND] = []

        def enum_cb(hwnd: wintypes.HWND, _: wintypes.LPARAM) -> wintypes.BOOL:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value or ""
            if "keepa" in title.lower() and "仕入行の編集" not in title:
                targets.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        for hwnd in targets:
            root = user32.GetAncestor(hwnd, GA_ROOT)
            if root:
                user32.ShowWindow(root, SW_MINIMIZE)
            else:
                user32.ShowWindow(hwnd, SW_MINIMIZE)
    except Exception:
        pass

__all__ = [
    "_TP_DIALOG_TIER_COLORS",
    "_TP_BAND_END_DAYS",
    "_TP_BAND_LABELS",
    "_TRACE_LABELS_JP",
    "_CHECKBOX_INDICATOR_STYLE",
    "_CHECKBOX_DARK_STYLE",
    "_LADDER_ROW_WRAP_STYLE",
    "_LADDER_LABEL_STYLE",
    "_apply_checkbox_dark_style",
    "_create_ladder_checkbox_row",
    "_SALES_CHANNEL_OPTIONS",
    "_SHIPPING_METHOD_OPTIONS",
    "_CONDITION_OPTIONS",
    "_SKU_DATE_BLOCKED_STATUS_CODES",
    "_SKU_DATE_BLOCKED_LABELS",
    "_normalized_purchase_status_code",
    "_sku_date_edit_locked",
    "_split_sku_leading_date",
    "_is_valid_yyyymmdd",
    "_style_tp_tier_text",
    "_tp_band_from_days",
    "_tp_tier_index_from_key",
    "_format_trace_change_label",
    "_has_repricer_preview_fields",
    "_parse_number",
    "_format_price",
    "_try_resize_browser_half_screen_win",
    "_minimize_keepa_browser_win",
]
