#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フリマ設定（設定タブ）

- フリマコードで登録したプラットフォームごとの手数料率
- AI出品文案: 必ず含める文・追加プロンプト
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.store_db import StoreDatabase

try:
    from desktop.services.flea_market_settings import (
        load_flea_market_ai_settings,
        save_flea_market_ai_settings,
    )
except ImportError:
    from services.flea_market_settings import (  # type: ignore
        load_flea_market_ai_settings,
        save_flea_market_ai_settings,
    )


class FleaMarketSettingsWidget(QWidget):
    """設定タブ > フリマ設定"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = StoreDatabase()
        self._fee_spins: Dict[int, QDoubleSpinBox] = {}
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)

        fee_group = QGroupBox("プラットフォーム別手数料率")
        fee_layout = QVBoxLayout(fee_group)
        fee_hint = QLabel(
            "プラットフォームの追加・削除は「店舗コード設定 > フリマコード」で行います。\n"
            "ここでは各プラットフォームの販売手数料率（%）を設定します。"
        )
        fee_hint.setWordWrap(True)
        fee_hint.setStyleSheet("color: #666; font-size: 9pt;")
        fee_layout.addWidget(fee_hint)

        self._fee_form_host = QWidget()
        self._fee_form = QFormLayout(self._fee_form_host)
        self._fee_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        fee_layout.addWidget(self._fee_form_host)

        self._fee_empty_label = QLabel("フリマプラットフォームが未登録です。")
        self._fee_empty_label.setWordWrap(True)
        self._fee_empty_label.setStyleSheet("color: #ffc107;")
        fee_layout.addWidget(self._fee_empty_label)

        fee_btn_row = QHBoxLayout()
        self.fee_save_btn = QPushButton("手数料率を保存")
        self.fee_save_btn.clicked.connect(self._save_fee_rates)
        fee_btn_row.addWidget(self.fee_save_btn)
        self.fee_refresh_btn = QPushButton("一覧を更新")
        self.fee_refresh_btn.clicked.connect(self.reload)
        fee_btn_row.addWidget(self.fee_refresh_btn)
        fee_btn_row.addStretch()
        fee_layout.addLayout(fee_btn_row)
        layout.addWidget(fee_group)

        ai_group = QGroupBox("AI出品文案")
        ai_layout = QVBoxLayout(ai_group)
        ai_hint = QLabel(
            "「フリマ情報生成」で Gemini が文案を作るときに使います。\n"
            "・必ず含める文 … 生成後の出品説明の末尾に必ず追加されます。\n"
            "・追加プロンプト … AIへの指示として追記されます（省略・改変されないよう固定文は上欄へ）。"
        )
        ai_hint.setWordWrap(True)
        ai_hint.setStyleSheet("color: #666; font-size: 9pt;")
        ai_layout.addWidget(ai_hint)

        ai_form = QFormLayout()
        ai_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.mandatory_text_edit = QTextEdit()
        self.mandatory_text_edit.setPlaceholderText(
            "例: 匿名配送でお送りします。即購入OKです。値下げ交渉はご遠慮ください。"
        )
        self.mandatory_text_edit.setMinimumHeight(80)
        ai_form.addRow("必ず含める文:", self.mandatory_text_edit)

        self.additional_prompt_edit = QTextEdit()
        self.additional_prompt_edit.setPlaceholderText(
            "例: 丁寧語で。絵文字は使わない。発送は平日2日以内と明記する。"
        )
        self.additional_prompt_edit.setMinimumHeight(80)
        ai_form.addRow("追加プロンプト:", self.additional_prompt_edit)
        ai_layout.addLayout(ai_form)

        ai_btn_row = QHBoxLayout()
        self.ai_save_btn = QPushButton("AI設定を保存")
        self.ai_save_btn.clicked.connect(self._save_ai_settings)
        ai_btn_row.addWidget(self.ai_save_btn)
        ai_btn_row.addStretch()
        ai_layout.addLayout(ai_btn_row)
        layout.addWidget(ai_group)

        layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()

    def reload(self) -> None:
        self._rebuild_fee_form()
        ai = load_flea_market_ai_settings()
        self.mandatory_text_edit.setPlainText(ai.get("mandatory_text", ""))
        self.additional_prompt_edit.setPlainText(ai.get("additional_prompt", ""))

    def _rebuild_fee_form(self) -> None:
        while self._fee_form.count():
            item = self._fee_form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._fee_spins.clear()

        rows: List[Dict[str, Any]] = self.db.list_flea_markets(active_only=False)
        has_rows = bool(rows)
        self._fee_empty_label.setVisible(not has_rows)
        self._fee_form_host.setVisible(has_rows)
        self.fee_save_btn.setEnabled(has_rows)

        for row in rows:
            mid = int(row["id"])
            name = (row.get("platform_name") or row.get("platform_code") or "").strip()
            active = bool(row.get("is_active", 1))
            label_text = name
            if not active:
                label_text += "（無効）"

            spin = QDoubleSpinBox()
            spin.setRange(-1.0, 100.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setSuffix(" %")
            spin.setSpecialValueText("未設定")
            spin.setEnabled(active)
            fr = row.get("fee_rate")
            if fr is None:
                spin.setValue(-1.0)
            else:
                try:
                    spin.setValue(float(fr))
                except (TypeError, ValueError):
                    spin.setValue(-1.0)

            self._fee_spins[mid] = spin
            lbl = QLabel(label_text)
            if not active:
                lbl.setStyleSheet("color: #888;")
            self._fee_form.addRow(lbl, spin)

    def _save_fee_rates(self) -> None:
        if not self._fee_spins:
            QMessageBox.information(self, "手数料率", "保存するプラットフォームがありません。")
            return
        try:
            for mid, spin in self._fee_spins.items():
                v = spin.value()
                fee = None if v < 0 else float(v)
                self.db.update_flea_market_fee_rate(mid, fee)
            QMessageBox.information(self, "手数料率", "手数料率を保存しました。")
        except Exception as e:
            QMessageBox.warning(self, "手数料率", f"保存に失敗しました:\n{e}")

    def _save_ai_settings(self) -> None:
        try:
            save_flea_market_ai_settings(
                self.mandatory_text_edit.toPlainText(),
                self.additional_prompt_edit.toPlainText(),
            )
            QMessageBox.information(self, "AI設定", "AI出品文案の設定を保存しました。")
        except Exception as e:
            QMessageBox.warning(self, "AI設定", f"保存に失敗しました:\n{e}")

    def save_all(self) -> None:
        """設定タブ全体の「設定を保存」から呼ぶ。"""
        if self._fee_spins:
            for mid, spin in self._fee_spins.items():
                v = spin.value()
                fee = None if v < 0 else float(v)
                self.db.update_flea_market_fee_rate(mid, fee)
        save_flea_market_ai_settings(
            self.mandatory_text_edit.toPlainText(),
            self.additional_prompt_edit.toPlainText(),
        )
