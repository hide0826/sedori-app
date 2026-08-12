#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""チャネル・手数料・SKU日付。"""
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


class PurchaseFeeChannelMixin:
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

        # 古物台帳（ledger_entries / purchase_rows）の SKU も同時に更新
        if old_sku and new_sku and old_sku != new_sku:
            self._sync_ledger_sku_rename(old_sku, new_sku)

        self.record["SKU"] = new_sku
        self.record["sku"] = new_sku
        self._last_committed_sku = new_sku
        return True

    def _sync_ledger_sku_rename(self, old_sku: str, new_sku: str) -> None:
        """仕入SKU変更に合わせて古物台帳DBのSKUを更新し、表示中なら再読込する。"""
        try:
            from database.ledger_db import LedgerDatabase
        except ImportError:
            try:
                from desktop.database.ledger_db import LedgerDatabase  # type: ignore
            except ImportError:
                return
        try:
            LedgerDatabase().rename_sku(old_sku, new_sku)
        except Exception:
            # 台帳同期失敗でも仕入DB側の変更は維持する
            return
        # 古物台帳タブが既に読み込み済みなら表示を追従
        try:
            pw = self._product_widget
            inv = getattr(pw, "inventory_widget", None) if pw is not None else None
            antique = getattr(inv, "antique_widget", None) if inv is not None else None
            if antique is not None and getattr(antique, "_ledger_loaded", False):
                if hasattr(antique, "reload_ledger_rows"):
                    antique.reload_ledger_rows()
        except Exception:
            pass

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
