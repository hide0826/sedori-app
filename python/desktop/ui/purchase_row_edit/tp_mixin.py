#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TP 入力・利益率・帯ハイライト。"""
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
from .support import (
    _TP_DIALOG_TIER_COLORS,
    _TP_BAND_END_DAYS,
    _TP_BAND_LABELS,
    _TRACE_LABELS_JP,
    _CHECKBOX_INDICATOR_STYLE,
    _CHECKBOX_DARK_STYLE,
    _LADDER_ROW_WRAP_STYLE,
    _LADDER_LABEL_STYLE,
    _apply_checkbox_dark_style,
    _create_ladder_checkbox_row,
    _SALES_CHANNEL_OPTIONS,
    _SHIPPING_METHOD_OPTIONS,
    _CONDITION_OPTIONS,
    _SKU_DATE_BLOCKED_STATUS_CODES,
    _SKU_DATE_BLOCKED_LABELS,
    _normalized_purchase_status_code,
    _sku_date_edit_locked,
    _split_sku_leading_date,
    _is_valid_yyyymmdd,
    _style_tp_tier_text,
    _tp_band_from_days,
    _tp_tier_index_from_key,
    _format_trace_change_label,
    _has_repricer_preview_fields,
    _parse_number,
    _format_price,
    _try_resize_browser_half_screen_win,
    _minimize_keepa_browser_win,
)


class PurchaseTpMixin:
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
