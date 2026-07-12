#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""月別ラダー UI 連携。"""
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


class PurchaseLadderMixin:
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
