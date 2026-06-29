#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入DB行編集ダイアログ

商品情報と TP0/TP1/TP2/TP3 価格を編集するコンパクトなダイアログ。
Keepa はブラウザで開き、このウィンドウは前面に保ったまま TA を入力できる。
"""

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
    from utils.repricer_ladder_table import (
        apply_even_margin_descent_to_ladder_table,
        apply_ladder_rules_to_table,
        apply_ladder_row_elapsed_lock,
        collect_ladder_rules_from_table,
        create_ladder_rules_table,
        ladder_rules_to_json,
        load_reprice_config_for_template,
        margin_percent_from_target_price,
        parse_ladder_rules_json,
        populate_ladder_table_rows,
        set_ladder_table_profit_context,
        template_rules_from_default_profile,
        update_ladder_profit_labels,
    )
except ImportError:
    from desktop.utils.repricer_ladder_table import (  # type: ignore
        apply_even_margin_descent_to_ladder_table,
        apply_ladder_rules_to_table,
        apply_ladder_row_elapsed_lock,
        collect_ladder_rules_from_table,
        create_ladder_rules_table,
        ladder_rules_to_json,
        load_reprice_config_for_template,
        margin_percent_from_target_price,
        parse_ladder_rules_json,
        populate_ladder_table_rows,
        set_ladder_table_profit_context,
        template_rules_from_default_profile,
        update_ladder_profit_labels,
    )

try:
    from utils.purchase_elapsed_days import (
        calc_elapsed_days_for_purchase_record,
        format_elapsed_days_for_purchase_record,
    )
    from utils.settings_helper import get_amazon_fba_simulator_url
except ImportError:
    from desktop.utils.purchase_elapsed_days import (  # type: ignore
        calc_elapsed_days_for_purchase_record,
        format_elapsed_days_for_purchase_record,
    )
    from desktop.utils.settings_helper import get_amazon_fba_simulator_url  # type: ignore

# ダークUI向け：TP0〜TP3 でラベル・入力・概算の色を分ける
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
# チェックボックス（OS標準の白ラベル背景で文字が消えるのを防ぐ）
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

try:
    from services.condition_labels import condition_code_from_value, normalize_condition_display
except ImportError:
    from desktop.services.condition_labels import (  # type: ignore
        condition_code_from_value,
        normalize_condition_display,
    )

# SKU 先頭日付の編集を禁止するステータス（内部コードおよび表示ラベル）
_SKU_DATE_BLOCKED_STATUS_CODES = frozenset({"selling", "sold", "partially_sold"})
_SKU_DATE_BLOCKED_LABELS = frozenset({"販売中", "販売済み", "一部販売済み"})


def _normalized_purchase_status_code(record: Dict[str, Any]) -> str:
    raw = record.get("ステータス") if record.get("ステータス") is not None else record.get("status")
    if raw is None or str(raw).strip() == "":
        return "ready"
    s = str(raw).strip()
    if s in _SKU_DATE_BLOCKED_LABELS:
        return {
            "販売中": "selling",
            "販売済み": "sold",
            "一部販売済み": "partially_sold",
        }[s]
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

try:
    from desktop.services.purchase_tp_autofill_369 import (
        ta_price_from_target_margin_percent,
        break_even_price_int_for_record,
    )
    from desktop.services.repricer_369_presets import TP_SOURCE_AUTO, TP_SOURCE_MANUAL
except ImportError:
    from services.purchase_tp_autofill_369 import (  # type: ignore
        ta_price_from_target_margin_percent,
        break_even_price_int_for_record,
    )
    from services.repricer_369_presets import TP_SOURCE_AUTO, TP_SOURCE_MANUAL  # type: ignore

try:
    from desktop.services.keepa_service import KeepaService
    from desktop.ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog
except ImportError:
    from services.keepa_service import KeepaService  # type: ignore
    from ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog  # type: ignore

try:
    from services.purchase_cost_calc import COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST, read_fee_fields
    from services.purchase_channel_cost import (
        apply_fee_values_to_record,
        flea_fee_rate_percent_for_channel,
        is_amazon_sales_channel,
        platform_fee_from_sale_price,
    )
except ImportError:
    from desktop.services.purchase_cost_calc import (  # type: ignore
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        read_fee_fields,
    )
    from desktop.services.purchase_channel_cost import (  # type: ignore
        apply_fee_values_to_record,
        flea_fee_rate_percent_for_channel,
        is_amazon_sales_channel,
        platform_fee_from_sale_price,
    )


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


class PurchaseRowEditDialog(QDialog):
    """仕入DBの1行を編集するコンパクトなダイアログ。Keepa はブラウザで開き、この窓は前面に保つ。"""

    def __init__(
        self,
        record: Dict[str, Any],
        parent: Optional[QWidget] = None,
        *,
        product_widget: Optional[QWidget] = None,
        csv_inventory_snapshot: Optional[Dict[str, Any]] = None,
        repricer_widget: Optional[QWidget] = None,
    ):
        # parent=None で作成し、メイン画面を前面に出さない（編集時もブラウザが隠れないようにする）
        super().__init__(None)
        self.record = record
        self._last_committed_sku = str(record.get("SKU") or record.get("sku") or "").strip()
        self._sku_date_edit: Optional[QLineEdit] = None
        self._sku_suffix_rest: str = ""
        self._product_widget = product_widget if product_widget is not None else parent
        self._csv_inventory_snapshot = csv_inventory_snapshot or {}
        self._repricer_widget = repricer_widget
        self._manual_export_price_edit: Optional[QLineEdit] = None
        self._fee_recalc_guard = False
        self._tp_source_labels: Dict[int, QLabel] = {}
        self._platform_fee_spin: Optional[QSpinBox] = None
        self._shipping_cost_spin: Optional[QSpinBox] = None
        self._total_cost_lbl: Optional[QLabel] = None
        self._profit_summary_lbl: Optional[QLabel] = None
        self._margin_lbl: Optional[QLabel] = None
        self._roi_lbl: Optional[QLabel] = None
        # 通常ウィンドウとして表示（最大化・最小化可）＋ Keepa 参照用に最前面
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowCloseButtonHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowStaysOnTopHint
        )
        self._update_window_title()
        self.setMinimumSize(380, 320)
        self.resize(480, 560)
        self._positioned_at_topleft = False
        self._tp_field_sync_guard = False
        self._tp_tier_widgets: Dict[int, List[QWidget]] = {}
        self._merge_ladder_from_db()
        self._setup_ui()

    def _update_window_title(self) -> None:
        base = "仕入行の編集（Keepa）"
        st = str(self.record.get("ステータス") or self.record.get("status") or "").strip().lower()
        if st == "inventory_only":
            self.setWindowTitle(f"[在庫専用] {base}")
        else:
            self.setWindowTitle(base)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._positioned_at_topleft:
            screen = QApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                self.move(geom.left(), geom.top())
            self._positioned_at_topleft = True

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- 商品情報（読み取り専用）---
        info_group = QGroupBox("商品情報")
        info_layout = QFormLayout()
        self._title_label = QLabel(self._record_str("商品名") or "-")
        self._title_label.setWordWrap(True)
        self._title_label.setMaximumWidth(340)
        info_layout.addRow("商品名:", self._title_label)
        info_layout.addRow("ASIN:", QLabel(self._record_str("ASIN") or "-"))
        sku_full = self._record_str("SKU") or self._record_str("sku") or ""
        date_prefix, rest_suffix = _split_sku_leading_date(sku_full)
        locked = _sku_date_edit_locked(self.record)
        if locked or date_prefix is None:
            sku_lbl = QLabel(sku_full or "-")
            if locked:
                sku_lbl.setToolTip(
                    "販売中・販売済み・一部販売済みの商品は、SKU先頭の日付（8桁）を変更できません。"
                )
            elif not sku_full:
                sku_lbl.setToolTip("")
            else:
                sku_lbl.setToolTip(
                    "SKUが先頭8桁の日付（YYYYMMDD）形式ではないため、日付のみの変更はできません。"
                )
            info_layout.addRow("SKU:", sku_lbl)
        else:
            self._sku_suffix_rest = rest_suffix
            sku_row = QHBoxLayout()
            self._sku_date_edit = QLineEdit()
            self._sku_date_edit.setMaxLength(8)
            self._sku_date_edit.setFixedWidth(92)
            self._sku_date_edit.setText(date_prefix)
            self._sku_date_edit.setPlaceholderText("YYYYMMDD")
            self._sku_date_edit.setToolTip(
                "先頭8桁（仕入日など）のみ変更できます。出品日と見なされる場合の調整・自社寝かせ在庫向けです。"
            )
            self._sku_date_edit.textChanged.connect(self._on_sku_date_text_changed)
            suf_lbl = QLabel(rest_suffix if rest_suffix else "")
            suf_lbl.setStyleSheet("color: #b0b0b0;")
            suf_lbl.setWordWrap(False)
            suf_lbl.setToolTip("SKUのこの部分は変更できません（日付8桁のみ編集可）。")
            sku_row.addWidget(self._sku_date_edit, 0)
            sku_row.addWidget(suf_lbl, 1)
            sku_wrap = QWidget()
            sku_wrap.setLayout(sku_row)
            info_layout.addRow("SKU:", sku_wrap)
        self._condition_combo = QComboBox()
        self._condition_combo.addItems(_CONDITION_OPTIONS)
        condition_text = self._record_condition_label_text()
        if condition_text == "-":
            condition_text = ""
        condition_display = normalize_condition_display(condition_text) if condition_text else ""
        cond_idx = self._condition_combo.findText(condition_display)
        if cond_idx < 0 and condition_display:
            self._condition_combo.addItem(condition_display)
            cond_idx = self._condition_combo.findText(condition_display)
        self._condition_combo.setCurrentIndex(max(0, cond_idx))
        info_layout.addRow("コンディション:", self._condition_combo)

        elapsed_text, elapsed_tip = format_elapsed_days_for_purchase_record(self.record)
        elapsed_lbl = QLabel(elapsed_text)
        elapsed_lbl.setToolTip(elapsed_tip)
        info_layout.addRow("経過日数:", elapsed_lbl)

        sale_price = _parse_number(self.record.get("販売予定価格") or self.record.get("expected_price"))
        self._sale_price_value = sale_price
        purchase_price = _parse_number(self.record.get("仕入れ価格") or self.record.get("purchase_price") or self.record.get("仕入価格"))
        self._purchase_price_value = purchase_price
        purchase_price_lbl = QLabel(_format_price(purchase_price))
        purchase_price_lbl.setToolTip(
            "仕入DB（purchases.purchase_price）に保存されている仕入れ価格です。"
        )
        info_layout.addRow("仕入れ価格（仕入DB）:", purchase_price_lbl)
        profit = _parse_number(self.record.get("見込み利益") or self.record.get("expected_profit"))
        self._current_profit_value = profit  # 今出てる見込み利益（値下げ時の概算の基準）
        base_rate = (profit / sale_price * 100.0) if sale_price > 0 and profit != 0 else 0.0
        profit_text = _format_price(profit)
        if base_rate:
            profit_text = f"{profit_text}（{base_rate:.1f}%）"
        planned_lbl = QLabel(_format_price(sale_price))
        planned_lbl.setToolTip(
            "仕入スナップショット／仕入データに保存されている販売予定価格（仕入時点の見込み）です。"
        )
        info_layout.addRow("販売予定価格（仕入時）:", planned_lbl)
        self._repricing_enabled_cb = QCheckBox("価格改定の対象にする（ON）")
        _apply_checkbox_dark_style(self._repricing_enabled_cb)
        repricing_val = self.record.get("価格改定")
        if repricing_val in (None, ""):
            repricing_val = self.record.get("repricing_enabled")
        is_enabled = str(repricing_val).strip().lower() not in ("0", "off", "false", "無効", "no")
        self._repricing_enabled_cb.setChecked(is_enabled)
        info_layout.addRow("価格改定:", self._repricing_enabled_cb)
        self._shipping_method_combo = QComboBox()
        self._shipping_method_combo.addItems(_SHIPPING_METHOD_OPTIONS)
        shipping_method = str(
            self.record.get("発送方法")
            or self.record.get("shippingMethod")
            or self.record.get("shipping_method")
            or "FBA"
        ).strip()
        ship_idx = self._shipping_method_combo.findText(shipping_method)
        if ship_idx < 0 and shipping_method:
            self._shipping_method_combo.addItem(shipping_method)
            ship_idx = self._shipping_method_combo.findText(shipping_method)
        self._shipping_method_combo.setCurrentIndex(max(0, ship_idx))
        info_layout.addRow("発送方法:", self._shipping_method_combo)
        self._sales_channel_combo = QComboBox()
        self._sales_channel_combo.addItems(_SALES_CHANNEL_OPTIONS)
        sales_channel = str(
            self.record.get("販売チャネル")
            or self.record.get("sales_channel")
            or self.record.get("platform")
            or "Amazon"
        ).strip()
        idx = self._sales_channel_combo.findText(sales_channel)
        if idx < 0 and sales_channel:
            self._sales_channel_combo.addItem(sales_channel)
            idx = self._sales_channel_combo.findText(sales_channel)
        self._sales_channel_combo.setCurrentIndex(max(0, idx))
        self._sales_channel_combo.currentTextChanged.connect(self._on_sales_channel_changed)
        info_layout.addRow("販売チャネル:", self._sales_channel_combo)

        platform_init, shipping_init, _total_init = read_fee_fields(self.record)
        self._platform_fee_spin = QSpinBox()
        self._platform_fee_spin.setRange(0, 10_000_000)
        self._platform_fee_spin.setSingleStep(10)
        self._platform_fee_spin.setValue(int(round(platform_init)))
        self._platform_fee_spin.setToolTip(
            "Amazon: FBA料金シミュ等で確認した手数料。\n"
            "メルカリ等: フリマ設定の手数料率×販売予定で自動入力（チャネル変更時）。"
        )
        self._platform_fee_spin.valueChanged.connect(self._on_fee_spin_changed)
        info_layout.addRow("プラットフォーム手数料:", self._platform_fee_spin)

        self._shipping_cost_spin = QSpinBox()
        self._shipping_cost_spin.setRange(0, 10_000_000)
        self._shipping_cost_spin.setSingleStep(10)
        self._shipping_cost_spin.setValue(int(round(shipping_init)))
        self._shipping_cost_spin.setToolTip("自己発送時の梱包・配送などの出荷費用。入力すると費用合計に加算されます。")
        self._shipping_cost_spin.valueChanged.connect(self._on_fee_spin_changed)
        info_layout.addRow("出荷費用:", self._shipping_cost_spin)

        self._total_cost_lbl = QLabel("-")
        self._total_cost_lbl.setToolTip("プラットフォーム手数料 + 出荷費用 の合計（自動計算）。")
        info_layout.addRow("費用合計:", self._total_cost_lbl)

        self._profit_summary_lbl = QLabel(profit_text)
        self._profit_summary_lbl.setToolTip(
            "販売予定 − (仕入れ + 費用合計) に基づく見込み利益。手数料・出荷を変えると自動更新します。"
        )
        info_layout.addRow("見込み利益:", self._profit_summary_lbl)

        self._margin_lbl = QLabel("-")
        self._margin_lbl.setToolTip("見込み利益 ÷ 販売予定価格 × 100（%）")
        info_layout.addRow("想定利益率:", self._margin_lbl)

        self._roi_lbl = QLabel("-")
        self._roi_lbl.setToolTip("見込み利益 ÷ 仕入れ価格 × 100（%）")
        info_layout.addRow("想定ROI:", self._roi_lbl)

        self._refresh_cost_summary()

        snap = self._csv_inventory_snapshot
        if snap:
            days_raw = snap.get("days")
            d_int: Optional[int] = None
            if days_raw is not None and str(days_raw).strip() != "":
                try:
                    d_int = int(float(days_raw))
                except (TypeError, ValueError):
                    d_int = None
            if d_int is None:
                days_text = "-"
            elif d_int == -1:
                days_text = "日付不明（-1）"
            else:
                days_text = f"{d_int} 日"
            days_lbl = QLabel(days_text)
            days_lbl.setToolTip(
                "価格改定結果テーブルの「日数」列と同じ値です（SKU の出品からの経過日数）。"
            )
            info_layout.addRow("日数（価格改定結果）:", days_lbl)

            csv_price = _parse_number(snap.get("price"))
            csv_profit = _parse_number(snap.get("profit"))
            csv_price_lbl = QLabel(_format_price(csv_price))
            csv_price_lbl.setToolTip(
                "価格改定で読み込んだ在庫CSVの price 列（改定前の現在価格）です。仕入DBの販売予定価格とは別の値です。"
            )
            info_layout.addRow("現在価格（CSV・price）:", csv_price_lbl)
            if self._repricer_widget is not None:
                self._manual_export_price_edit = QLineEdit()
                manual_val = snap.get("manual_export_price")
                if manual_val is not None:
                    try:
                        self._manual_export_price_edit.setText(
                            str(int(round(float(manual_val))))
                        )
                    except (TypeError, ValueError):
                        pass
                preview_np = _parse_number(snap.get("new_price"))
                if preview_np > 0 and not self._manual_export_price_edit.text().strip():
                    self._manual_export_price_edit.setPlaceholderText(
                        f"空欄＝改定プレビューどおり（{int(round(preview_np)):,}円）"
                    )
                else:
                    self._manual_export_price_edit.setPlaceholderText(
                        "空欄＝改定プレビューどおり（手動上書きなし）"
                    )
                self._manual_export_price_edit.setToolTip(
                    "プライスターに返す在庫CSVの price 列に書く価格です。\n"
                    "反映後に「価格改定プレビュー」を再実行すると、改定価格・akaji・takane が\n"
                    "この価格とルール%で更新され、理由は「ユーザー手動変更」になります。\n"
                    "空欄のまま反映すると手動上書きを解除します。"
                )
                info_layout.addRow("プライスター送付価格（手動）:", self._manual_export_price_edit)
            if csv_profit == 0 and csv_price > 0 and sale_price > 0:
                csv_profit = profit - 0.89 * (sale_price - csv_price)
            if csv_price > 0:
                rate = csv_profit / csv_price * 100.0
                prof_text = f"{int(round(csv_profit)):,}（{rate:.1f}%）"
            else:
                prof_text = (
                    f"{int(round(csv_profit)):,}（-）" if csv_profit else "-"
                )
            csv_profit_lbl = QLabel(prof_text)
            csv_profit_lbl.setToolTip(
                "在庫CSVの profit 列と、現在価格に対する利益率（profit ÷ price）です。"
            )
            info_layout.addRow("現在見込み利益（CSV・利益率）:", csv_profit_lbl)
            self._append_repricer_preview_rows(info_layout, snap)
        elif not self._record_ladder_enabled():
            self._append_repricer_preview_rows(info_layout, {})

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # --- Keepa：ブラウザ / API 出品者一覧 ---
        keepa_btn_row = QHBoxLayout()
        keepa_btn_row.setSpacing(8)
        open_keepa_btn = QPushButton("Keepa をブラウザで開く")
        open_keepa_btn.setToolTip("Keepa を開きます。Windows では約2秒後にブラウザを前面に出し、画面の右半分にリサイズします（編集ダイアログは左上に表示）。")
        open_keepa_btn.clicked.connect(self._open_keepa_in_browser)
        keepa_btn_row.addWidget(open_keepa_btn, 1)
        seller_info_btn = QPushButton("出品者情報取得")
        seller_info_btn.setToolTip(
            "Keepa API で live offers（出品者・価格・送料）を取得し、Keepaテストの「詳細」と同じ一覧ウィンドウで表示します。"
        )
        seller_info_btn.clicked.connect(self._show_keepa_offer_details)
        keepa_btn_row.addWidget(seller_info_btn, 1)
        flea_btn = QPushButton("フリマ情報生成")
        flea_btn.setToolTip(
            "Gemini でフリマ向けのタイトル・商品説明を生成します。"
            "商品説明には JANコードとコンディション説明を含めます。画像1〜6はドラッグでメルカリ等へ登録できます。"
        )
        flea_btn.clicked.connect(self._open_flea_market_listing)
        keepa_btn_row.addWidget(flea_btn, 1)
        fba_sim_btn = QPushButton("FBA料金シミュレーター")
        fba_sim_btn.setToolTip(
            "設定タブ → 詳細設定 → Amazon の「FBA料金シミュレーターURL」をブラウザで開きます。"
        )
        fba_sim_btn.clicked.connect(self._open_fba_simulator_in_browser)
        keepa_btn_row.addWidget(fba_sim_btn, 1)
        layout.addLayout(keepa_btn_row)

        _ladder_tip = (
            "ON にすると、価格改定タブの改定ルールと同じ形式で、このSKU専用の\n"
            "出品日数別ルール（アクション・priceTrace・目標価格）を使います。\n"
            "OFF のときは従来の TP0〜TP3（4段）を使います。"
        )
        ladder_cb_row, self._ladder_enabled_cb = _create_ladder_checkbox_row(
            "月別運用（30日刻みの個別改定ルール）",
            tooltip=_ladder_tip,
        )
        ladder_on = self._record_ladder_enabled()
        self._ladder_enabled_cb.setChecked(ladder_on)
        self._ladder_enabled_cb.toggled.connect(self._on_ladder_mode_toggled)
        layout.addWidget(ladder_cb_row)

        # --- 月別運用: 改定ルール同型の表（TP列→目標到達価格）---
        self._ladder_group = QGroupBox("月別運用ルール（このSKU専用）")
        ladder_outer = QVBoxLayout(self._ladder_group)
        ladder_btn_row = QHBoxLayout()
        copy_tpl_btn = QPushButton("デフォルトプロファイルからコピー")
        copy_tpl_btn.setToolTip(
            "価格改定タブの「3-6-9共通設定」のデフォルトプロファイル（例: 6ルール）の\n"
            "アクション・priceTrace をコピーし、目標到達価格列には TP0〜TP3 を帯ごとに当てはめます。"
        )
        copy_tpl_btn.clicked.connect(self._copy_ladder_from_default_profile)
        ladder_btn_row.addWidget(copy_tpl_btn)

        even_desc_btn = QPushButton("等間隔値下げ")
        even_desc_btn.setToolTip(
            "現在以降の最初の出品日数帯から12行目（331-360日）まで、\n"
            "概算利益率を等間隔で下げながら目標到達価格を自動入力します。\n"
            "開始利益率: 開始帯に価格があればその利益率、なければ販売予定価格時の利益率。"
        )
        even_desc_btn.clicked.connect(self._on_ladder_even_margin_descent)
        ladder_btn_row.addWidget(even_desc_btn)

        ladder_btn_row.addWidget(QLabel("最終利益率:"))
        self._ladder_even_final_margin_spin = QDoubleSpinBox()
        self._ladder_even_final_margin_spin.setRange(-99.0, 200.0)
        self._ladder_even_final_margin_spin.setDecimals(1)
        self._ladder_even_final_margin_spin.setSuffix(" %")
        self._ladder_even_final_margin_spin.setToolTip(
            "331-360日帯で到達させたい概算利益率(%)（TP価格欄と同じ計算式）。"
        )
        self._ladder_even_final_margin_spin.setFixedWidth(100)
        ladder_btn_row.addWidget(self._ladder_even_final_margin_spin)

        ladder_btn_row.addStretch()
        ladder_outer.addLayout(ladder_btn_row)
        self._ladder_table = create_ladder_rules_table()
        self._ladder_table.setMinimumHeight(220)
        ladder_scroll = QScrollArea()
        ladder_scroll.setWidgetResizable(True)
        ladder_scroll.setWidget(self._ladder_table)
        ladder_scroll.setMinimumHeight(200)
        ladder_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        ladder_outer.addWidget(ladder_scroll, 1)
        self._ladder_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._ladder_group, 1)
        populate_ladder_table_rows(self._ladder_table, connect_action_signals=True)
        saved_rules = parse_ladder_rules_json(
            self.record.get("ladder_rules") or self.record.get("LadderRules")
        )
        if saved_rules:
            apply_ladder_rules_to_table(self._ladder_table, saved_rules)
        set_ladder_table_profit_context(
            self._ladder_table,
            self._sale_price_value,
            self._current_profit_value,
        )
        update_ladder_profit_labels(self._ladder_table)
        self._apply_ladder_elapsed_row_lock()
        self._init_ladder_even_final_margin_default()

        # --- TP0 / TP1 / TP2 / TP3 編集（各帯：価格 → 目標利益率 → 概算利益、色分け）---
        self._ta_group = QGroupBox("TP 価格（Keepa で確認しながら入力）")
        ta_group = self._ta_group
        ta_layout = QFormLayout()

        def _add_tp_block(
            tier: int,
            price_key_variants: tuple[str, ...],
            price_placeholder: str,
        ) -> None:
            color = _TP_DIALOG_TIER_COLORS[tier]
            lbl_price = QLabel(f"TP{tier} 価格:")
            edit = QLineEdit()
            edit.setPlaceholderText(price_placeholder)
            txt = ""
            for k in price_key_variants:
                v = self._record_str(k)
                if v:
                    txt = v
                    break
            edit.setText(txt)
            edit.textChanged.connect(lambda _t=None, tr=tier: self._on_ta_price_text_changed(tr))
            edit.editingFinished.connect(lambda tr=tier: self._sync_rate_spin_from_price(tr))
            edit.editingFinished.connect(lambda tr=tier: self._on_tp_price_editing_finished(tr))

            source_lbl = QLabel("")
            source_lbl.setStyleSheet("color: #999999; font-size: 11px; padding-left: 6px;")
            self._tp_source_labels[tier] = source_lbl
            price_row = QWidget()
            price_row_layout = QHBoxLayout(price_row)
            price_row_layout.setContentsMargins(0, 0, 0, 0)
            price_row_layout.addWidget(edit, 1)
            price_row_layout.addWidget(source_lbl)

            lbl_rate = QLabel(f"TP{tier} 目標利益率(%):")
            rate_spin = QDoubleSpinBox()
            rate_spin.setRange(-100.0, 300.0)
            rate_spin.setDecimals(2)
            rate_spin.setSingleStep(0.5)
            rate_spin.setSuffix(" %")
            rate_spin.setKeyboardTracking(False)
            rate_spin.setMinimumWidth(118)
            rate_spin.setToolTip(
                "現在の TP 価格に対する概算利益率(%)が表示されます。▲▼ で増減すると価格が連動します。\n"
                "価格をキーで直したときは、Enter か別の欄へ移動して確定すると利益率も更新されます。"
            )
            rate_spin.valueChanged.connect(lambda _v, tr=tier: self._on_ta_rate_spin_changed(tr))

            lbl_profit = QLabel(f"TP{tier} 概算利益（利益率）:")
            profit_lbl = QLabel("-")

            _style_tp_tier_text(color, lbl_price, edit, lbl_rate, rate_spin, lbl_profit, profit_lbl)
            ta_layout.addRow(lbl_price, price_row)
            ta_layout.addRow(lbl_rate, rate_spin)
            ta_layout.addRow(lbl_profit, profit_lbl)

            self._tp_tier_widgets[tier] = [
                lbl_price,
                edit,
                lbl_rate,
                rate_spin,
                lbl_profit,
                profit_lbl,
            ]
            setattr(self, f"_ta{tier}_edit", edit)
            setattr(self, f"_ta{tier}_rate_spin", rate_spin)
            setattr(self, f"_ta{tier}_profit_label", profit_lbl)

        _add_tp_block(0, ("TP0", "tp0"), "例: 6400")
        _add_tp_block(1, ("TP1", "tp1", "TA1", "ta1"), "例: 6200")
        _add_tp_block(2, ("TP2", "tp2", "TA2", "ta2"), "例: 5800")
        _add_tp_block(3, ("TP3", "tp3"), "例: 5600")

        ta_group.setLayout(ta_layout)
        layout.addWidget(ta_group)
        self._update_ta_labels()
        for tr in range(4):
            self._sync_rate_spin_from_price(tr)
            self._update_tp_source_label(tr)
        self._on_ladder_mode_toggled(self._ladder_enabled_cb.isChecked())
        if not self._ladder_enabled_cb.isChecked():
            self._apply_tp_phase_highlight(
                self._resolve_active_tp_tier(self._csv_inventory_snapshot)
            )

        # --- ボタン（反映後もダイアログは開いたまま＝ブラウザを参照し続けられる）---
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        if self._repricer_widget is not None and self._manual_export_price_edit is not None:
            self._manual_export_btn = QPushButton("プライスター送付価格を反映")
            self._manual_export_btn.setToolTip(
                "入力した価格を保存します（空欄で反映すると上書き解除）。\n"
                "プレビュー済みなら結果表を即更新し、再プレビュー時も同じ価格が反映されます。"
            )
            self._manual_export_btn.clicked.connect(self._apply_manual_export_price)
            buttons.addButton(self._manual_export_btn, QDialogButtonBox.ActionRole)
        self._apply_btn = QPushButton("仕入DBに反映")
        self._apply_btn.setDefault(True)
        self._apply_btn.setToolTip(
            "TP・月別運用・価格改定ON/OFF・販売チャネル・発送方法・\n"
            "プラットフォーム手数料・出荷費用・見込み利益・想定利益率/ROI を仕入DBに保存します。"
        )
        self._apply_btn.clicked.connect(self._apply)
        buttons.addButton(self._apply_btn, QDialogButtonBox.ActionRole)
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        buttons.addButton(close_btn, QDialogButtonBox.AcceptRole)
        layout.addWidget(buttons)

    def _open_flea_market_listing(self) -> None:
        """フリマ出品情報ダイアログを開く（Gemini文案・画像ドラッグ）。"""
        try:
            from ui.flea_market_listing_dialog import FleaMarketListingDialog
        except ImportError:
            from desktop.ui.flea_market_listing_dialog import FleaMarketListingDialog
        dlg = FleaMarketListingDialog(
            self.record,
            parent=self,
            product_widget=self._product_widget,
            auto_generate=False,
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.setModal(False)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _open_fba_simulator_in_browser(self) -> None:
        """設定タブ（詳細設定 → Amazon）の FBA料金シミュレーターURL を開く。"""
        url = get_amazon_fba_simulator_url()
        if not re.match(r"^https?://", url, flags=re.IGNORECASE):
            QMessageBox.warning(
                self,
                "URL確認",
                "FBA料金シミュレーターURLが不正です。\n"
                "設定タブ → 詳細設定 → Amazon で確認してください。",
            )
            return
        QDesktopServices.openUrl(QUrl(url))

    def _open_keepa_in_browser(self) -> None:
        """選択行の ASIN で Keepa を既定ブラウザで開き、Windows の場合はブラウザを前面・左半分にリサイズ"""
        asin = self._record_str("ASIN") or self._record_str("asin")
        if not asin:
            QMessageBox.warning(self, "Keepa", "ASIN がありません。")
            return
        url = f"https://keepa.com/#!product/5-{asin}"
        QDesktopServices.openUrl(QUrl(url))
        # ブラウザが開いてタブタイトルが Keepa になるまで待ってから、前面に出して左半分にリサイズ（Windows のみ・2回試行）
        QTimer.singleShot(1500, _try_resize_browser_half_screen_win)
        QTimer.singleShot(3500, _try_resize_browser_half_screen_win)

    def _show_keepa_offer_details(self) -> None:
        """Keepa API から live offers を取得し、詳細ダイアログで表示（Keepaテストタブの「詳細」と同じ）。"""
        asin = self._record_str("ASIN") or self._record_str("asin")
        if not asin:
            QMessageBox.warning(self, "出品者情報", "ASIN がありません。")
            return
        title = (self._title_label.text() or "").strip() or "(タイトルなし)"
        try:
            svc = KeepaService()
            _info, raw = svc.fetch_product_with_raw(asin)
        except RuntimeError as e:
            QMessageBox.critical(self, "Keepa エラー", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "出品者情報", f"取得に失敗しました:\n{e}")
            return
        new_rows, used_rows = svc.build_live_offer_display_rows(raw)
        dlg = KeepaOfferDetailDialog(
            self,
            asin=asin,
            title=title,
            new_rows=new_rows,
            used_rows=used_rows,
        )
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _condition_grade_only_for_label(self, text: str) -> str:
        """
        コンディション列に Amazon 風の長文（【動作確認】…）が1本で入っている場合でも、
        グレード名（例: 中古(非常に良い)）だけをラベル用に切り出す。
        """
        if not text:
            return ""
        t = str(text).replace("\\n", "\n").strip()
        line = t.split("\n")[0].strip()
        if " (" in line:
            head, tail = line.split(" (", 1)
            if len(tail) > 40 or "【" in tail:
                line = head.strip()
        elif ")（" in line and "【" in line:
            head, _ = line.split(")（", 1)
            line = head.rstrip()
            if line and not line.endswith(")"):
                line = line + ")"
        return line.strip()

    def _record_condition_label_text(self) -> str:
        """仕入DBのコンディション列（と同義キー）のみ。コンディション説明列とは混ぜない。"""
        main = ""
        for k in ("コンディション", "condition", "状態"):
            v = self._record_str(k)
            if v:
                main = v
                break
        if not main:
            return "-"
        # 過去データで1セルに長文が入っていた場合の保険（通常の「中古(非常に良い)」はそのまま通る）
        short = self._condition_grade_only_for_label(main)
        return short if short else main

    def _record_str(self, key: str) -> str:
        v = self.record.get(key)
        if v is None:
            return ""
        return str(v).strip()

    def _on_sku_date_text_changed(self, text: str) -> None:
        """SKU日付欄は数字8桁のみ。"""
        if self._sku_date_edit is None:
            return
        digits = "".join(c for c in text if c.isdigit())[:8]
        if digits != text:
            self._sku_date_edit.blockSignals(True)
            self._sku_date_edit.setText(digits)
            self._sku_date_edit.blockSignals(False)

    def _apply_sku_date_change(self) -> bool:
        """
        日付編集ありの場合に record と DB の SKU を更新する。
        失敗時は False（メッセージ表示済み想定）。
        """
        if self._sku_date_edit is None:
            return True
        raw = self._sku_date_edit.text().strip()
        raw = "".join(c for c in raw if c.isdigit())
        if len(raw) != 8:
            QMessageBox.warning(self, "SKU", "日付は YYYYMMDD の8桁で入力してください。")
            return False
        if not _is_valid_yyyymmdd(raw):
            QMessageBox.warning(self, "SKU", "日付が有効な暦日ではありません（YYYYMMDD を確認してください）。")
            return False
        new_sku = raw + self._sku_suffix_rest
        old_sku = self._last_committed_sku
        if new_sku == old_sku:
            self.record["SKU"] = new_sku
            self.record["sku"] = new_sku
            return True

        pw = self._product_widget
        pdb = getattr(pw, "purchase_history_db", None) if pw else None
        if pdb:
            row_new = pdb.get_by_sku(new_sku)
            row_old = pdb.get_by_sku(old_sku) if old_sku else None
            if row_new is not None and (row_old is None or row_new.get("id") != row_old.get("id")):
                QMessageBox.warning(
                    self,
                    "SKU",
                    f"SKU「{new_sku}」は既に別の仕入データで使用されています。別の日付を指定してください。",
                )
                return False
            if row_old is not None:
                try:
                    pdb.rename_sku(old_sku, new_sku)
                except ValueError as e:
                    QMessageBox.warning(self, "SKU", str(e))
                    return False

        self.record["SKU"] = new_sku
        self.record["sku"] = new_sku
        self._last_committed_sku = new_sku
        return True

    def _ta_price_edit(self, which: int) -> QLineEdit:
        return (self._ta0_edit, self._ta1_edit, self._ta2_edit, self._ta3_edit)[which]

    def _tp_price_for_tier(self, tier: int) -> float:
        """仕入DB（または作成済みの TP 入力欄）から TP 価格を取得。"""
        key_map = {
            0: ("TP0", "tp0"),
            1: ("TP1", "tp1", "TA1", "ta1"),
            2: ("TP2", "tp2", "TA2", "ta2"),
            3: ("TP3", "tp3"),
        }
        for k in key_map.get(tier, ()):
            v = self._record_str(k)
            if v:
                p = _parse_number(v)
                if p > 0:
                    return p
        if hasattr(self, "_ta0_edit"):
            return _parse_number(self._ta_price_edit(tier).text())
        return 0.0

    def _ta_rate_spin(self, which: int) -> QDoubleSpinBox:
        return (self._ta0_rate_spin, self._ta1_rate_spin, self._ta2_rate_spin, self._ta3_rate_spin)[which]

    def _implied_margin_percent(self, ta_price: float) -> Optional[float]:
        """TP 価格 ta に対する概算利益率(%) = 概算利益 / ta × 100（_update_ta_labels と同じ利益定義）。"""
        sale = self._sale_price_value
        if not ta_price or sale <= 0:
            return None
        current_profit = self._current_profit_value
        profit = current_profit - 0.89 * (sale - ta_price)
        return (profit / ta_price * 100) if ta_price else None

    def _sync_rate_spin_from_price(self, which: int) -> None:
        """TP 価格から逆算した利益率(%)をスピンに反映（概算利益行と同じ値）。編集確定時・初期表示用。"""
        if self._tp_field_sync_guard:
            return
        price_edit = self._ta_price_edit(which)
        spin = self._ta_rate_spin(which)
        raw = price_edit.text().strip()
        spin.blockSignals(True)
        try:
            if not raw:
                spin.setValue(0.0)
                return
            ta = _parse_number(raw)
            if ta <= 0:
                spin.setValue(0.0)
                return
            imp = self._implied_margin_percent(ta)
            if imp is None:
                spin.setValue(0.0)
            else:
                lo, hi = spin.minimum(), spin.maximum()
                spin.setValue(max(lo, min(hi, imp)))
        finally:
            spin.blockSignals(False)

    def _on_ta_price_text_changed(self, which: int) -> None:
        """価格のキー入力では利益率スピンを書き換えない（バックスペースと競合しない）。"""
        if self._tp_field_sync_guard:
            self._update_ta_labels()
            return
        self._update_ta_labels()

    def _on_tp_price_editing_finished(self, tier: int) -> None:
        if self._tp_field_sync_guard:
            return
        edit = getattr(self, f"_ta{tier}_edit", None)
        if edit is None:
            return
        if not edit.text().strip():
            self.record[f"tp{tier}_source"] = ""
            self._update_tp_source_label(tier)
            return
        self.record[f"tp{tier}_source"] = TP_SOURCE_MANUAL
        self._update_tp_source_label(tier)

    def _tp_source_display_text(self, tier: int) -> str:
        src = str(self.record.get(f"tp{tier}_source") or "").strip().lower()
        edit = getattr(self, f"_ta{tier}_edit", None)
        has_val = bool(edit and edit.text().strip())
        if src == TP_SOURCE_AUTO:
            return "（自動）"
        if src == TP_SOURCE_MANUAL or (has_val and not src):
            return "（手動）"
        return ""

    def _update_tp_source_label(self, tier: int) -> None:
        lbl = self._tp_source_labels.get(tier)
        if lbl is not None:
            lbl.setText(self._tp_source_display_text(tier))

    def _update_ta_labels(self) -> None:
        # 販売予定 sale での見込み利益を基準に、TP 価格との差を 0.89 倍して利益に反映する。
        # 概算利益 = 見込み利益 - 0.89 × (販売予定 - TP価格) ＝ 価格が上がれば利益も増える（対称）。
        current_profit = self._current_profit_value
        sale = self._sale_price_value
        ta0 = _parse_number(self._ta0_edit.text())
        ta1 = _parse_number(self._ta1_edit.text())
        ta2 = _parse_number(self._ta2_edit.text())
        ta3 = _parse_number(self._ta3_edit.text())

        def _ta_profit_and_rate(ta_price: float) -> tuple:
            if not ta_price or sale <= 0:
                return None, None
            profit = current_profit - 0.89 * (sale - ta_price)
            rate = (profit / ta_price * 100) if ta_price else None
            return profit, rate

        p0, r0 = _ta_profit_and_rate(ta0)
        p1, r1 = _ta_profit_and_rate(ta1)
        p2, r2 = _ta_profit_and_rate(ta2)
        p3, r3 = _ta_profit_and_rate(ta3)
        self._ta0_profit_label.setText(
            f"{_format_price(p0)}（{r0:.1f}%）" if p0 is not None and r0 is not None else "-"
        )
        self._ta1_profit_label.setText(
            f"{_format_price(p1)}（{r1:.1f}%）" if p1 is not None and r1 is not None else "-"
        )
        self._ta2_profit_label.setText(
            f"{_format_price(p2)}（{r2:.1f}%）" if p2 is not None and r2 is not None else "-"
        )
        self._ta3_profit_label.setText(
            f"{_format_price(p3)}（{r3:.1f}%）" if p3 is not None and r3 is not None else "-"
        )

    def _on_ta_rate_spin_changed(self, which: int) -> None:
        """スピン（▲▼ または確定したキー入力）で目標利益率が変わったときだけ TP 価格を逆算する。"""
        if self._tp_field_sync_guard:
            return
        sale = self._sale_price_value
        current_profit = self._current_profit_value
        if sale <= 0:
            return

        spin = self._ta_rate_spin(which)
        target_edit = self._ta_price_edit(which)
        rate_percent = float(spin.value())
        if rate_percent <= 0:
            return

        ta_price = ta_price_from_target_margin_percent(sale, current_profit, rate_percent)
        if ta_price is None:
            ta_price = break_even_price_int_for_record(self.record)
        if ta_price is None:
            return

        self._tp_field_sync_guard = True
        try:
            target_edit.setText(str(ta_price))
            imp = self._implied_margin_percent(float(ta_price))
            if imp is not None:
                lo, hi = spin.minimum(), spin.maximum()
                spin.blockSignals(True)
                spin.setValue(max(lo, min(hi, imp)))
                spin.blockSignals(False)
        finally:
            self._tp_field_sync_guard = False
        self._update_ta_labels()

    def _merge_ladder_from_db(self) -> None:
        """レコードに無い月別運用設定を仕入DBから補完する。"""
        if self.record.get("ladder_rules") or self.record.get("ladder_enabled") is not None:
            return
        sku = self._record_str("SKU") or self._record_str("sku")
        if not sku:
            return
        try:
            if self._product_widget and hasattr(self._product_widget, "purchase_history_db"):
                db = self._product_widget.purchase_history_db
            else:
                try:
                    from database.purchase_db import PurchaseDatabase
                except ImportError:
                    from desktop.database.purchase_db import PurchaseDatabase  # type: ignore
                db = PurchaseDatabase()
            row = db.get_by_sku(sku)
            if not row:
                return
            if row.get("ladder_rules"):
                self.record["ladder_rules"] = row.get("ladder_rules")
            le = row.get("ladder_enabled")
            if le is not None:
                self.record["ladder_enabled"] = le
        except Exception:
            pass

    def _record_ladder_enabled(self) -> bool:
        raw = self.record.get("ladder_enabled")
        if raw is None:
            return False
        return str(raw).strip().lower() in ("1", "true", "on", "yes")

    def _apply_ladder_elapsed_row_lock(self) -> None:
        """月別運用表で、経過済みの出品日数帯をグレー表示・編集不可にする。"""
        elapsed = calc_elapsed_days_for_purchase_record(self.record)
        apply_ladder_row_elapsed_lock(self._ladder_table, elapsed)

    def _init_ladder_even_final_margin_default(self) -> None:
        """等間隔値下げの最終利益率の初期値（0%台）。"""
        spin = getattr(self, "_ladder_even_final_margin_spin", None)
        if spin is None:
            return
        spin.setValue(0.0)

    def _on_ladder_even_margin_descent(self) -> None:
        """現在以降の帯から331-360日帯まで、利益率を等間隔で下げて目標到達価格を埋める。"""
        if not getattr(self, "_ladder_enabled_cb", None) or not self._ladder_enabled_cb.isChecked():
            QMessageBox.information(
                self,
                "等間隔値下げ",
                "月別運用がOFFです。ONにしてから実行してください。",
            )
            return
        final_margin = self._ladder_even_final_margin_spin.value()
        elapsed = calc_elapsed_days_for_purchase_record(self.record)
        ok, msg, _filled = apply_even_margin_descent_to_ladder_table(
            self._ladder_table,
            elapsed_days=elapsed,
            final_margin_percent=final_margin,
            sale_price=self._sale_price_value,
            base_profit=self._current_profit_value,
        )
        if not ok:
            QMessageBox.warning(self, "等間隔値下げ", msg)
            return
        QMessageBox.information(self, "等間隔値下げ", msg)

    def _on_ladder_mode_toggled(self, checked: bool) -> None:
        self._ladder_group.setVisible(checked)
        self._ta_group.setVisible(not checked)
        if checked:
            self.setMinimumSize(440, 480)
            if not self.isMaximized():
                self.resize(max(self.width(), 520), max(self.height(), 640))
            self._apply_tp_phase_highlight(None)
        else:
            self.setMinimumSize(380, 320)
            self._apply_tp_phase_highlight(
                self._resolve_active_tp_tier(self._csv_inventory_snapshot)
            )

    def _resolve_active_tp_tier(self, snap: Dict[str, Any]) -> Optional[int]:
        """価格改定プレビューまたは経過日数から、いま編集すべき TP 段（0〜3）を返す。"""
        if self._record_ladder_enabled():
            return None
        tp_target = str(snap.get("tp_target") or "").strip().lower()
        if tp_target == "ladder":
            return None
        tier = _tp_tier_index_from_key(tp_target)
        if tier is not None:
            return tier
        days_raw = snap.get("days")
        if days_raw is None:
            days_raw = calc_elapsed_days_for_purchase_record(self.record)
        try:
            days_int = int(float(days_raw)) if days_raw is not None else -1
        except (TypeError, ValueError):
            days_int = -1
        if days_int >= 0:
            band_key, _, _ = _tp_band_from_days(days_int)
            return _tp_tier_index_from_key(band_key)
        return None

    def _append_repricer_preview_rows(
        self, info_layout: QFormLayout, snap: Dict[str, Any]
    ) -> None:
        """現在TPフェーズ（常時）と、プレビュー時の改定予定価格などを表示。"""
        snap = snap or {}

        if self._record_ladder_enabled() or str(snap.get("tp_target") or "").lower() == "ladder":
            if not _has_repricer_preview_fields(snap):
                return
            phase_text = "月別運用（個別ルール）"
            phase_tip = "月別運用ONのため、TP0〜TP3 ではなく月別運用表のルールが改定に使われます。"
        else:
            active_tier = self._resolve_active_tp_tier(snap)
            if active_tier is not None:
                band_key = f"tp{active_tier}"
                phase_text = _TP_BAND_LABELS.get(band_key, band_key.upper())
                db_tp = self._tp_price_for_tier(active_tier)
                if db_tp > 0:
                    phase_text += f" ／ 仕入DBのTP{active_tier}={_format_price(db_tp)}"
            else:
                days_raw = snap.get("days")
                try:
                    days_int = int(float(days_raw)) if days_raw is not None else -1
                except (TypeError, ValueError):
                    days_int = -1
                if days_int >= 0:
                    _, _, phase_text = _tp_band_from_days(days_int)
                else:
                    phase_text = "-"
            phase_tip = (
                "価格改定プレビューの tp_target と日数から判定した、いまの改定フェーズです。\n"
                "下の TP 価格欄の該当段がハイライトされます。"
            )
            if not _has_repricer_preview_fields(snap):
                phase_tip = (
                    "仕入DBの経過日数から推定した TP 帯です。\n"
                    "下の TP 価格欄の該当段がハイライトされます。"
                )

        phase_lbl = QLabel(phase_text)
        phase_lbl.setWordWrap(True)
        phase_lbl.setStyleSheet("color: #7ae495; font-weight: bold;")
        phase_lbl.setToolTip(phase_tip)
        info_layout.addRow("現在TPフェーズ:", phase_lbl)

        if not _has_repricer_preview_fields(snap):
            return

        action_text = str(snap.get("action") or "-").strip() or "-"
        action_lbl = QLabel(action_text)
        action_lbl.setToolTip("直近の価格改定プレビューで決まったアクション（日本語表示）です。")
        info_layout.addRow("適用アクション:", action_lbl)

        tp_floor = _parse_number(snap.get("tp_floor"))
        if tp_floor > 0:
            floor_lbl = QLabel(_format_price(tp_floor))
            floor_lbl.setToolTip(
                "改定ロジックが参照した TP 下限（仕入DBの TP 価格を優先）です。\n"
                "この画面で TP を下げて「仕入DBに反映」→ プレビュー再実行すると反映されます。"
            )
            info_layout.addRow("TP下限（プレビュー）:", floor_lbl)

        new_price = _parse_number(snap.get("new_price"))
        new_price_lbl = QLabel(_format_price(new_price) if new_price > 0 else "-")
        reason = str(snap.get("reason") or "").strip()
        new_price_lbl.setToolTip(
            "直近プレビューの改定後価格（new_price）です。"
            + (f"\n理由: {reason}" if reason else "")
        )
        info_layout.addRow("改定予定価格（プレビュー）:", new_price_lbl)

        manual_ep = snap.get("manual_export_price")
        if manual_ep not in (None, ""):
            try:
                manual_int = int(round(float(manual_ep)))
            except (TypeError, ValueError):
                manual_int = 0
            if manual_int > 0:
                manual_lbl = QLabel(_format_price(manual_int))
                manual_lbl.setStyleSheet("color: #f0c674; font-weight: bold;")
                manual_lbl.setToolTip(
                    "プライスター返却CSVに書く手動上書き価格です。CSV保存時はこちらが優先されます。"
                )
                info_layout.addRow("プライスター送付（手動）:", manual_lbl)

        trace_text = _format_trace_change_label(
            snap.get("priceTraceChangeDisplay") or snap.get("priceTraceChange")
        )
        if trace_text != "無し" and trace_text != "-":
            trace_lbl = QLabel(trace_text)
            trace_lbl.setToolTip("Trace（priceTrace）の変更内容です。")
            info_layout.addRow("Trace変更:", trace_lbl)

        reach = str(snap.get("tp_reach_status") or "").strip()
        if reach:
            reach_lbl = QLabel(reach)
            reach_lbl.setToolTip("TP下限への到達状況（期間到達・期間外到達など）です。")
            info_layout.addRow("TP到達状態:", reach_lbl)

        keepa_ref = snap.get("keepa_ref_price")
        if keepa_ref not in (None, ""):
            keepa_lbl = QLabel(str(keepa_ref))
            keepa_lbl.setToolTip(
                "価格改定結果の Keepa価格(参考) 列です。改定計算には使われません（参考表示のみ）。"
            )
            info_layout.addRow("Keepa参考価格:", keepa_lbl)

    def _apply_tp_phase_highlight(self, active_tier: Optional[int]) -> None:
        """現在の TP フェーズに対応する入力欄をハイライトする。"""
        for tier, widgets in self._tp_tier_widgets.items():
            color = _TP_DIALOG_TIER_COLORS[tier]
            if tier == active_tier:
                for w in widgets:
                    if isinstance(w, QLineEdit):
                        w.setStyleSheet(
                            f"color: {color}; background-color: #1a2f22;"
                            f" border: 2px solid {color}; padding: 2px;"
                        )
                    else:
                        w.setStyleSheet(
                            f"color: {color}; font-weight: bold;"
                            f" background-color: #152218;"
                        )
            else:
                _style_tp_tier_text(color, *widgets)

    def _copy_ladder_from_default_profile(self) -> None:
        config = load_reprice_config_for_template()
        if not config:
            QMessageBox.warning(self, "コピー", "改定ルール設定ファイルが見つかりません。")
            return
        tp_prices = {
            "tp0": self._ta0_edit.text().strip() if hasattr(self, "_ta0_edit") else "",
            "tp1": self._ta1_edit.text().strip() if hasattr(self, "_ta1_edit") else "",
            "tp2": self._ta2_edit.text().strip() if hasattr(self, "_ta2_edit") else "",
            "tp3": self._ta3_edit.text().strip() if hasattr(self, "_ta3_edit") else "",
        }
        rules = template_rules_from_default_profile(config, tp_prices=tp_prices)
        if not rules:
            QMessageBox.warning(self, "コピー", "デフォルトプロファイルのルールが空です。")
            return
        apply_ladder_rules_to_table(self._ladder_table, rules)
        update_ladder_profit_labels(self._ladder_table)
        self._apply_ladder_elapsed_row_lock()
        QMessageBox.information(
            self,
            "コピー",
            "デフォルトプロファイルのルールを表に反映しました。\n目標到達価格列は TP0〜TP3 を帯に合わせて入れています。必要に応じて編集してください。",
        )

    def _store_db(self) -> Any:
        pw = self._product_widget
        if pw is not None and hasattr(pw, "store_db"):
            return pw.store_db
        return None

    def _on_sales_channel_changed(self, _channel_text: str = "") -> None:
        if self._fee_recalc_guard:
            return
        channel = self._sales_channel_combo.currentText().strip() if self._sales_channel_combo else ""
        if not is_amazon_sales_channel(channel):
            if self._shipping_method_combo is not None:
                idx = self._shipping_method_combo.findText("自己発送")
                if idx >= 0:
                    self._shipping_method_combo.setCurrentIndex(idx)
            rate = flea_fee_rate_percent_for_channel(channel, self._store_db())
            if rate is not None and self._platform_fee_spin is not None and self._sale_price_value > 0:
                fee = platform_fee_from_sale_price(self._sale_price_value, rate)
                self._fee_recalc_guard = True
                try:
                    self._platform_fee_spin.setValue(fee)
                finally:
                    self._fee_recalc_guard = False
        self._refresh_cost_summary()

    def _on_fee_spin_changed(self, _value: int = 0) -> None:
        if self._fee_recalc_guard:
            return
        self._refresh_cost_summary()

    def _refresh_cost_summary(self) -> None:
        if self._platform_fee_spin is None or self._shipping_cost_spin is None:
            return
        platform = float(self._platform_fee_spin.value())
        shipping = float(self._shipping_cost_spin.value())

        fields = apply_fee_values_to_record(
            self.record,
            purchase_price=self._purchase_price_value,
            planned_price=self._sale_price_value,
            platform_fee=platform,
            shipping_cost=shipping,
        )
        total = int(fields.get(COL_TOTAL_COST, 0) or 0)
        if self._total_cost_lbl is not None:
            self._total_cost_lbl.setText(_format_price(total) if total > 0 else "-")

        profit = float(fields.get("見込み利益", 0))
        self._current_profit_value = profit
        margin = float(fields.get("想定利益率", 0))
        roi = float(fields.get("想定ROI", 0))

        if self._profit_summary_lbl is not None:
            prof_text = _format_price(profit)
            if self._sale_price_value > 0:
                prof_text += f"（{margin:.1f}%）"
            self._profit_summary_lbl.setText(prof_text)
        if self._margin_lbl is not None:
            self._margin_lbl.setText(f"{margin:.2f} %" if self._sale_price_value > 0 else "-")
        if self._roi_lbl is not None:
            self._roi_lbl.setText(f"{roi:.2f} %" if self._purchase_price_value > 0 else "-")

    def _apply_manual_export_price(self) -> None:
        """プライスター返却CSV用の手動 price を価格改定タブに保存する。"""
        rw = self._repricer_widget
        edit = self._manual_export_price_edit
        if rw is None or edit is None:
            return
        sku = self._record_str("SKU") or self._record_str("sku")
        if not sku:
            QMessageBox.warning(self, "手動価格", "SKU がありません。")
            return
        raw = edit.text().strip().replace(",", "")
        if not raw:
            if hasattr(rw, "clear_manual_export_price"):
                rw.clear_manual_export_price(sku)
            if hasattr(rw, "refresh_manual_override_display"):
                rw.refresh_manual_override_display()
            self._csv_inventory_snapshot.pop("manual_export_price", None)
            QMessageBox.information(
                self,
                "手動価格",
                "手動上書きを解除しました。\n"
                "価格改定プレビューを再実行すると、通常の改定結果に戻ります。",
            )
            return
        price = _parse_number(raw)
        if price <= 0:
            QMessageBox.warning(self, "手動価格", "1円以上の整数で入力してください。")
            return
        price_int = int(round(price))
        if hasattr(rw, "set_manual_export_price"):
            rw.set_manual_export_price(sku, price_int)
        if hasattr(rw, "refresh_manual_override_display"):
            rw.refresh_manual_override_display()
        self._csv_inventory_snapshot["manual_export_price"] = price_int
        self._csv_inventory_snapshot["new_price"] = price_int
        QMessageBox.information(
            self,
            "手動価格",
            f"プライスター送付価格を {price_int:,} 円に設定しました。\n\n"
            "価格改定タブの結果表を更新しました（プレビュー済みの場合）。\n"
            "改定価格・akaji・takane はルール%で再計算され、理由は「ユーザー手動変更」です。\n"
            "CSV保存でもこの価格が price 列に書かれます。",
        )

    def _apply(self) -> None:
        """仕入DBに反映する（ダイアログは閉じない＝ブラウザを見たまま続けられる）"""
        old_sku = self._last_committed_sku
        if not self._apply_sku_date_change():
            return
        ladder_on = self._ladder_enabled_cb.isChecked()
        ladder_rules_json = ""
        if ladder_on:
            ladder_rules_json = ladder_rules_to_json(collect_ladder_rules_from_table(self._ladder_table))
        tp0 = self._ta0_edit.text().strip()
        tp1 = self._ta1_edit.text().strip()
        tp2 = self._ta2_edit.text().strip()
        tp3 = self._ta3_edit.text().strip()
        self.record["TP0"] = tp0
        self.record["tp0"] = tp0
        self.record["TP1"] = tp1
        self.record["tp1"] = tp1
        self.record["TP2"] = tp2
        self.record["tp2"] = tp2
        self.record["TP3"] = tp3
        self.record["tp3"] = tp3
        for tier, val in enumerate((tp0, tp1, tp2, tp3)):
            src_key = f"tp{tier}_source"
            if not val:
                self.record[src_key] = ""
            elif str(self.record.get(src_key) or "").strip().lower() != TP_SOURCE_AUTO:
                self.record[src_key] = TP_SOURCE_MANUAL
        repricing_enabled = bool(self._repricing_enabled_cb.isChecked())
        condition = self._condition_combo.currentText().strip()
        if condition:
            self.record["コンディション"] = condition
            self.record["condition"] = condition
            condition_code = condition_code_from_value(condition)
            if condition_code is not None:
                self.record["condition_code"] = condition_code
        shipping_method = self._shipping_method_combo.currentText().strip() or "FBA"
        self.record["発送方法"] = shipping_method
        self.record["shippingMethod"] = shipping_method
        self.record["shipping_method"] = shipping_method
        sales_channel = self._sales_channel_combo.currentText().strip() or "Amazon"
        self.record["販売チャネル"] = sales_channel
        self.record["sales_channel"] = sales_channel
        self.record["価格改定"] = "ON" if repricing_enabled else "OFF"
        self.record["repricing_enabled"] = 1 if repricing_enabled else 0
        self.record["ladder_enabled"] = 1 if ladder_on else 0
        self.record["ladder_rules"] = ladder_rules_json if ladder_on else ""
        self._refresh_cost_summary()
        # 親が ProductWidget なら hirio.db とスナップショットにも保存
        if self._product_widget and hasattr(self._product_widget, "purchase_history_db"):
            sku = self._record_str("SKU") or self._record_str("sku")
            if sku:
                try:
                    status = self.record.get("ステータス") or self.record.get("status") or "ready"
                    reason = self.record.get("ステータス理由") or self.record.get("status_reason") or ""
                    upsert_payload = {
                        "sku": sku,
                        "status": self.record.get("status") or self.record.get("ステータス") or status,
                        "status_reason": self.record.get("status_reason")
                        or self.record.get("ステータス理由")
                        or reason,
                        "tp0": tp0,
                        "tp1": tp1,
                        "tp2": tp2,
                        "tp3": tp3,
                        "tp0_source": self.record.get("tp0_source") or "",
                        "tp1_source": self.record.get("tp1_source") or "",
                        "tp2_source": self.record.get("tp2_source") or "",
                        "tp3_source": self.record.get("tp3_source") or "",
                        "sales_channel": sales_channel,
                        "repricing_enabled": 1 if repricing_enabled else 0,
                        "ladder_enabled": 1 if ladder_on else 0,
                        "ladder_rules": ladder_rules_json if ladder_on else "",
                        "expected_margin": self.record.get("expected_margin"),
                        "expected_roi": self.record.get("expected_roi"),
                    }
                    if condition:
                        condition_code = condition_code_from_value(condition)
                        if condition_code is not None:
                            upsert_payload["condition_code"] = condition_code
                    self._product_widget.purchase_history_db.upsert(upsert_payload)
                except Exception as e:
                    QMessageBox.warning(self, "反映", f"DB 保存でエラー: {e}")
                    return
        pw = self._product_widget
        if pw is not None:
            if hasattr(pw, "apply_purchase_row_edit_to_memory"):
                try:
                    pw.apply_purchase_row_edit_to_memory(self.record, old_sku=old_sku)
                except Exception:
                    pass
            if hasattr(pw, "save_purchase_snapshot"):
                try:
                    pw.save_purchase_snapshot()
                except Exception:
                    pass
            if hasattr(pw, "refresh_purchase_display_after_row_edit"):
                try:
                    pw.refresh_purchase_display_after_row_edit(self.record)
                except Exception:
                    pass
        self._update_window_title()
        fee_parts = []
        if self._platform_fee_spin is not None:
            pf = int(self._platform_fee_spin.value())
            if pf > 0:
                fee_parts.append(f"手数料 {pf:,}円")
        if self._shipping_cost_spin is not None:
            sh = int(self._shipping_cost_spin.value())
            if sh > 0:
                fee_parts.append(f"出荷 {sh:,}円")
        profit = int(round(self._current_profit_value or 0))
        fee_line = " / ".join(fee_parts) if fee_parts else "手数料・出荷は未入力"
        msg = (
            "仕入DB（一覧・スナップショット）に反映しました。\n"
            f"コンディション: {condition or '-'} ／ 販売チャネル: {sales_channel} ／ 発送: {shipping_method}\n"
            f"{fee_line} ／ 見込み利益: {profit:,}円\n"
        )
        if ladder_on:
            msg += "月別運用ルール・"
        else:
            msg += "TP0〜TP3・"
        msg += "価格改定設定を保存しました。\nダイアログは開いたままです。閉じる場合は「閉じる」を押してください。"
        QMessageBox.information(self, "反映", msg)

    def accept(self) -> None:
        """閉じる時に Keepa ブラウザも最小化する（閉じた後に遅延実行）"""
        super().accept()
        QTimer.singleShot(250, _minimize_keepa_browser_win)

    def reject(self) -> None:
        """キャンセル時も Keepa ブラウザを最小化する（閉じた後に遅延実行）"""
        super().reject()
        QTimer.singleShot(250, _minimize_keepa_browser_win)
