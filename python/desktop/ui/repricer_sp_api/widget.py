#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SP-API 価格改定タブ（既存「改定実行」とは独立）。

① SP-API取得 → ②プレビュー → ③目視 → ④実行 → ⑤Amazonへ価格反映
計算は既存 FastAPI /repricer（mode=369）を利用する。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .support import (
    AmazonPatchWorker,
    FollowRepriceWorker,
    InventoryFetchWorker,
    NumericTableWidgetItem,
    RepriceCalcWorker,
    _SP_API_ACTION_TO_PIPELINE_STEP,
    _format_status_prefix_html,
    _format_workflow_pipeline_html,
)


class RepricerSpApiWidget(QWidget):
    """価格改定 > SP-API改定 タブ。"""

    repricing_executed = Signal(str)

    def __init__(self, api_client, mode: str = "369"):
        super().__init__()
        self.api_client = api_client
        self.mode = "369"
        self.csv_path: Optional[str] = None
        self.preview_df: Optional[pd.DataFrame] = None
        self.repricing_result: Optional[Dict[str, Any]] = None
        self._worker = None
        self._workflow_status_text = "ワークフロー: 未実行"
        self._workflow_emphasize = False
        self._workflow_active_step: Optional[int] = None
        self._workflow_post_step: Optional[int] = None
        self.preview_collapsed = False
        self.result_collapsed = False
        self.settings = QSettings("HIRIO", "DesktopApp")
        self._follow_timer = QTimer(self)
        self._follow_timer.timeout.connect(self._on_follow_timer)
        self._follow_auto_run = False
        self.setup_ui()
        self._restore_follow_auto()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self._setup_action_panel()
        self._setup_preview_area()
        self._setup_result_area()

    def _green_button_style(self) -> str:
        return """
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #218838; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """

    def _setup_action_panel(self) -> None:
        group = QGroupBox("SP-API操作・アクション")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer = QVBoxLayout(group)
        outer.setSpacing(4)
        outer.setContentsMargins(5, 5, 5, 5)

        row = QHBoxLayout()
        row.setSpacing(5)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("①「SP-API取得」で Amazon 出品一覧を読み込みます")
        self.source_edit.setReadOnly(True)
        self.source_edit.setMaximumHeight(30)
        row.addWidget(self.source_edit, stretch=1)

        style = self._green_button_style()

        self.fetch_btn = QPushButton("SP-API取得")
        self.fetch_btn.setStyleSheet(style)
        self.fetch_btn.clicked.connect(
            lambda: self._run_action_with_status("SP-API取得", self.fetch_from_sp_api)
        )
        row.addWidget(self.fetch_btn)

        self.preview_btn = QPushButton("価格改定プレビュー")
        self.preview_btn.setEnabled(False)
        self.preview_btn.setStyleSheet(style)
        self.preview_btn.clicked.connect(
            lambda: self._run_action_with_status("価格改定プレビュー", self.preview_repricing)
        )
        row.addWidget(self.preview_btn)

        self.execute_btn = QPushButton("価格改定実行")
        self.execute_btn.setEnabled(False)
        self.execute_btn.setStyleSheet(style)
        self.execute_btn.clicked.connect(
            lambda: self._run_action_with_status("価格改定実行", self.execute_repricing)
        )
        row.addWidget(self.execute_btn)

        self.patch_btn = QPushButton("Amazonへ価格反映")
        self.patch_btn.setEnabled(False)
        self.patch_btn.setStyleSheet(style)
        self.patch_btn.setToolTip("④実行後の改定価格を Listings Items API で Amazon に送信します")
        self.patch_btn.clicked.connect(
            lambda: self._run_action_with_status("Amazonへ価格反映", self.apply_prices_to_amazon)
        )
        row.addWidget(self.patch_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(25)
        self.progress_bar.setMaximumWidth(160)
        row.addWidget(self.progress_bar)
        row.addStretch()

        self.clear_btn = QPushButton("クリア")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self.clear_state)
        row.addWidget(self.clear_btn)

        outer.addLayout(row)

        self.workflow_status_label = QLabel()
        self.workflow_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.workflow_status_label.setWordWrap(True)
        self.workflow_status_label.setStyleSheet("padding: 2px 0px;")
        self._sync_workflow_status_label()
        outer.addWidget(self.workflow_status_label)

        aux = QHBoxLayout()
        self.save_csv_btn = QPushButton("結果をCSV保存（監査用）")
        self.save_csv_btn.setEnabled(False)
        self.save_csv_btn.clicked.connect(
            lambda: self._run_action_with_status("結果をCSV保存", self.save_results_csv)
        )
        aux.addWidget(self.save_csv_btn)

        self.dry_run_cb = QCheckBox("試験: 先頭N件のみAmazon反映")
        self.dry_run_cb.setChecked(True)
        self.dry_run_cb.setToolTip("誤爆防止。外すと変更対象の全SKUへ PATCH します")
        aux.addWidget(self.dry_run_cb)

        self.dry_run_spin = QSpinBox()
        self.dry_run_spin.setRange(1, 500)
        self.dry_run_spin.setValue(1)
        self.dry_run_spin.setToolTip("試験モード時の最大反映件数")
        aux.addWidget(self.dry_run_spin)
        aux.addStretch()
        outer.addLayout(aux)

        follow_box = QGroupBox("最安追従（SP-API・既存3-6-9とは別）")
        follow_lay = QVBoxLayout(follow_box)
        follow_row = QHBoxLayout()
        self.follow_btn = QPushButton("最安追従を実行")
        self.follow_btn.setStyleSheet(style)
        self.follow_btn.setToolTip(
            "同コンディション最安を SP-API で取得し、\n"
            "150日未満は最安に揃え、以降は TP へ寄せつつライバルより100円安くします。"
        )
        self.follow_btn.clicked.connect(lambda: self.run_follow_repricer())
        follow_row.addWidget(self.follow_btn)

        self.follow_auto_cb = QCheckBox("自動巡回")
        self.follow_auto_cb.setToolTip("指定時間ごとに最安追従を自動実行します（アプリ起動中のみ）")
        self.follow_auto_cb.toggled.connect(self._on_follow_auto_toggled)
        follow_row.addWidget(self.follow_auto_cb)

        follow_row.addWidget(QLabel("間隔(時間)"))
        self.follow_hours_spin = QSpinBox()
        self.follow_hours_spin.setRange(4, 12)
        self.follow_hours_spin.setValue(int(self.settings.value("repricer/sp_api/follow_interval_hours", 8) or 8))
        self.follow_hours_spin.setToolTip("1日あたり 2〜6 回程度。アプリを起動したままにしてください")
        self.follow_hours_spin.valueChanged.connect(self._save_follow_settings)
        follow_row.addWidget(self.follow_hours_spin)

        self.follow_patch_cb = QCheckBox("巡回後にAmazonへ反映")
        self.follow_patch_cb.setChecked(
            str(self.settings.value("repricer/sp_api/follow_auto_patch", "false")).lower() in ("1", "true", "yes")
        )
        self.follow_patch_cb.setToolTip("ON にすると計算後に価格 PATCH します。OFF なら計算のみ")
        self.follow_patch_cb.toggled.connect(self._save_follow_settings)
        follow_row.addWidget(self.follow_patch_cb)

        follow_row.addWidget(QLabel("上限件数"))
        self.follow_max_spin = QSpinBox()
        self.follow_max_spin.setRange(1, 5000)
        self.follow_max_spin.setValue(int(self.settings.value("repricer/sp_api/follow_max_listings", 400) or 400))
        self.follow_max_spin.setToolTip("1回の巡回で最安調査する最大件数（先頭から）")
        self.follow_max_spin.valueChanged.connect(self._save_follow_settings)
        follow_row.addWidget(self.follow_max_spin)
        follow_row.addStretch()
        follow_lay.addLayout(follow_row)

        follow_note = QLabel(
            "150日未満: 同条件最安に揃える（TPより下げない）。"
            "150日以降: TPへ少しずつ下げ、自分より安い出品があればその価格−100円（下限はTP）。"
            "自動巡回は PC とアプリが起動しているときだけ動きます。"
        )
        follow_note.setWordWrap(True)
        follow_note.setStyleSheet("color: #9e9e9e;")
        follow_lay.addWidget(follow_note)
        outer.addWidget(follow_box)

        note = QLabel(
            "上段の①〜⑤は既存の 3-6-9 計算です。"
            "最安追従は別ロジックです。既存の「改定実行」タブ（プライスターCSV）とは独立です。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9e9e9e;")
        outer.addWidget(note)

        self.layout().addWidget(group)

    def _setup_preview_area(self) -> None:
        group = QGroupBox()
        v = QVBoxLayout(group)
        header = QHBoxLayout()
        self.preview_toggle_btn = QPushButton("出品データプレビュー －")
        self.preview_toggle_btn.setFlat(True)
        self.preview_toggle_btn.clicked.connect(self._toggle_preview)
        header.addWidget(self.preview_toggle_btn)
        header.addStretch()
        v.addLayout(header)

        self.preview_table = QTableWidget()
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setMinimumHeight(180)
        self.preview_table.setSortingEnabled(True)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectRows)
        v.addWidget(self.preview_table)
        self.layout().addWidget(group)

    def _setup_result_area(self) -> None:
        group = QGroupBox()
        v = QVBoxLayout(group)
        header = QHBoxLayout()
        self.result_toggle_btn = QPushButton("価格改定結果 －")
        self.result_toggle_btn.setFlat(True)
        self.result_toggle_btn.clicked.connect(self._toggle_result)
        header.addWidget(self.result_toggle_btn)
        header.addStretch()
        v.addLayout(header)

        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.setMinimumHeight(180)
        self.result_table.setSortingEnabled(True)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        v.addWidget(self.result_table)
        self.layout().addWidget(group)

    def _toggle_preview(self) -> None:
        self.preview_collapsed = not self.preview_collapsed
        self.preview_table.setVisible(not self.preview_collapsed)
        self.preview_toggle_btn.setText(
            "出品データプレビュー ＋" if self.preview_collapsed else "出品データプレビュー －"
        )

    def _toggle_result(self) -> None:
        self.result_collapsed = not self.result_collapsed
        self.result_table.setVisible(not self.result_collapsed)
        self.result_toggle_btn.setText(
            "価格改定結果 ＋" if self.result_collapsed else "価格改定結果 －"
        )

    def _sync_workflow_status_label(self) -> None:
        prefix = _format_status_prefix_html(self._workflow_status_text, self._workflow_emphasize)
        pipe = _format_workflow_pipeline_html(self._workflow_active_step)
        sep = '<span style="color:#cccccc;">　</span>'
        self.workflow_status_label.setText(prefix + sep + pipe)

    def _update_workflow_status(self, text: str, emphasize: bool = False) -> None:
        self._workflow_status_text = text
        self._workflow_emphasize = emphasize
        if "価格確認" in text:
            self._workflow_active_step = 3
        elif text.strip() == "ワークフロー: 未実行":
            self._workflow_active_step = None
        self._sync_workflow_status_label()

    def _run_action_with_status(self, action_name: str, action_func):
        step = _SP_API_ACTION_TO_PIPELINE_STEP.get(action_name)
        self._workflow_post_step = None
        try:
            if step is not None:
                self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 実行中", emphasize=True)
            QApplication.processEvents()
        except Exception:
            pass
        try:
            return action_func()
        finally:
            post = getattr(self, "_workflow_post_step", None)
            if post is not None:
                self._workflow_active_step = post
                self._workflow_post_step = None
            elif step is not None:
                self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 待機", emphasize=False)

    def clear_state(self) -> None:
        self.csv_path = None
        self.preview_df = None
        self.repricing_result = None
        self.source_edit.clear()
        self.preview_table.clear()
        self.preview_table.setRowCount(0)
        self.preview_table.setColumnCount(0)
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self.preview_btn.setEnabled(False)
        self.execute_btn.setEnabled(False)
        self.patch_btn.setEnabled(False)
        self.save_csv_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self._workflow_active_step = None
        self._update_workflow_status("ワークフロー: 未実行", emphasize=False)

    # ----- ① SP-API取得 -----
    def fetch_from_sp_api(self) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.fetch_btn.setEnabled(False)
        self._worker = InventoryFetchWorker()
        self._worker.progress_message.connect(self._on_fetch_progress)
        self._worker.result_ready.connect(self._on_fetch_ready)
        self._worker.error_occurred.connect(self._on_fetch_error)
        self._worker.start()

    def _on_fetch_progress(self, msg: str) -> None:
        self.source_edit.setText(msg)

    def _on_fetch_ready(self, df: pd.DataFrame, csv_path: str) -> None:
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.fetch_btn.setEnabled(True)
        self.preview_df = df
        self.csv_path = csv_path
        self.source_edit.setText(f"取得完了: {len(df)} 件 → {csv_path}")
        self._populate_preview_table(df)
        self.preview_btn.setEnabled(True)
        self.execute_btn.setEnabled(False)
        self.patch_btn.setEnabled(False)
        self.save_csv_btn.setEnabled(False)
        self.clear_btn.setEnabled(True)
        self.repricing_result = None
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self._workflow_post_step = 1
        QMessageBox.information(
            self,
            "SP-API取得完了",
            f"出品データを {len(df)} 件取得しました。\n次に「価格改定プレビュー」を実行してください。",
        )

    def _on_fetch_error(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.fetch_btn.setEnabled(True)
        QMessageBox.critical(self, "SP-API取得エラー", message)

    def _populate_preview_table(self, df: pd.DataFrame) -> None:
        self.preview_table.setSortingEnabled(False)
        self.preview_table.clear()
        show_cols = [c for c in ("SKU", "ASIN", "title", "number", "price", "cost", "priceTrace") if c in df.columns]
        if not show_cols:
            show_cols = list(df.columns)[:8]
        view = df[show_cols]
        self.preview_table.setRowCount(len(view))
        self.preview_table.setColumnCount(len(show_cols))
        self.preview_table.setHorizontalHeaderLabels(show_cols)
        for i in range(len(view)):
            for j, col in enumerate(show_cols):
                val = view.iloc[i][col]
                text = "" if pd.isna(val) else str(val)
                if col == "title" and len(text) > 50:
                    item = QTableWidgetItem(text[:50] + "...")
                    item.setToolTip(text)
                else:
                    item = QTableWidgetItem(text)
                self.preview_table.setItem(i, j, item)
        self.preview_table.setSortingEnabled(True)
        self.preview_table.resizeColumnsToContents()

    # ----- ② / ④ プレビュー・実行 -----
    def preview_repricing(self) -> None:
        if not self.csv_path:
            QMessageBox.warning(self, "エラー", "先に「SP-API取得」を実行してください")
            return
        self._start_calc_worker(is_preview=True)

    def execute_repricing(self) -> None:
        if not self.csv_path:
            QMessageBox.warning(self, "エラー", "先に「SP-API取得」を実行してください")
            return
        reply = QMessageBox.question(
            self,
            "価格改定実行確認",
            "価格改定を実行しますか？\n"
            "※この段階では Amazon へは書き込みません。\n"
            "※結果確認後に「Amazonへ価格反映」で送信します。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._start_calc_worker(is_preview=False)

    def _start_calc_worker(self, *, is_preview: bool) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.preview_btn.setEnabled(False)
        self.execute_btn.setEnabled(False)
        self._worker = RepriceCalcWorker(
            self.csv_path,
            self.api_client,
            is_preview=is_preview,
            mode=self.mode,
        )
        self._worker.progress_updated.connect(self.progress_bar.setValue)
        if is_preview:
            self._worker.result_ready.connect(self._on_preview_completed)
            self._worker.error_occurred.connect(self._on_preview_error)
        else:
            self._worker.result_ready.connect(self._on_execute_completed)
            self._worker.error_occurred.connect(self._on_execute_error)
        self._worker.start()

    def _on_preview_completed(self, result: Dict[str, Any]) -> None:
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        self.execute_btn.setEnabled(True)
        self.repricing_result = result
        self._update_result_table(result)
        self._workflow_post_step = 3
        self._update_workflow_status("ワークフロー: 価格確認（目視）", emphasize=False)
        summary = result.get("summary") or {}
        QMessageBox.information(
            self,
            "プレビュー完了",
            f"プレビューが完了しました。\n更新候補行数: {summary.get('updated_rows', '-')}",
        )

    def _on_preview_error(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        self.execute_btn.setEnabled(bool(self.csv_path))
        QMessageBox.critical(self, "プレビューエラー", message)

    def _on_execute_completed(self, result: Dict[str, Any]) -> None:
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        self.execute_btn.setEnabled(True)
        self.patch_btn.setEnabled(True)
        self.save_csv_btn.setEnabled(True)
        self.repricing_result = result
        self._update_result_table(result)
        try:
            from services.repricer_execution_store import record_repricer_execution

            record_repricer_execution(self.mode)
            self.repricing_executed.emit(self.mode)
        except Exception:
            pass
        self._workflow_post_step = 4
        summary = result.get("summary") or {}
        QMessageBox.information(
            self,
            "価格改定完了",
            f"価格改定（計算）が完了しました。\n更新行数: {summary.get('updated_rows', '-')}\n"
            "問題なければ「Amazonへ価格反映」を実行してください。",
        )

    def _on_execute_error(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.preview_btn.setEnabled(True)
        self.execute_btn.setEnabled(True)
        QMessageBox.critical(self, "実行エラー", message)

    def _update_result_table(self, result: Dict[str, Any]) -> None:
        items = list(result.get("items") or [])
        self.result_table.setSortingEnabled(False)
        columns = ["SKU", "ASIN", "Title", "日数", "フェーズ", "アクション", "理由", "現在価格", "改定価格", "最安", "TP"]
        self.result_table.setRowCount(len(items))
        self.result_table.setColumnCount(len(columns))
        self.result_table.setHorizontalHeaderLabels(columns)
        for i, item in enumerate(items):
            sku = str(item.get("sku", ""))
            asin = str(item.get("asin", ""))
            title = str(item.get("title", ""))
            days = item.get("days", 0) or 0
            action = str(item.get("action", ""))
            reason = str(item.get("reason", ""))
            phase = str(item.get("phase", "") or "")
            price = item.get("price", 0)
            new_price = item.get("new_price", 0)
            min_same = item.get("min_same_condition", item.get("akaji", ""))
            tp_floor = item.get("tp_floor", "")
            try:
                days_i = int(days)
            except (TypeError, ValueError):
                days_i = 0
            try:
                price_f = float(price or 0)
            except (TypeError, ValueError):
                price_f = 0.0
            try:
                new_f = float(new_price or 0)
            except (TypeError, ValueError):
                new_f = 0.0

            self.result_table.setItem(i, 0, QTableWidgetItem(sku))
            self.result_table.setItem(i, 1, QTableWidgetItem(asin))
            title_disp = title[:50] + "..." if len(title) > 50 else title
            title_item = QTableWidgetItem(title_disp)
            if len(title) > 50:
                title_item.setToolTip(title)
            self.result_table.setItem(i, 2, title_item)
            days_item = NumericTableWidgetItem(days_i)
            days_item.setText(str(days_i))
            self.result_table.setItem(i, 3, days_item)
            self.result_table.setItem(i, 4, QTableWidgetItem(phase))
            self.result_table.setItem(i, 5, QTableWidgetItem(action))
            self.result_table.setItem(i, 6, QTableWidgetItem(reason))
            p_item = NumericTableWidgetItem(price_f)
            p_item.setText(str(int(price_f) if price_f == int(price_f) else price_f))
            self.result_table.setItem(i, 7, p_item)
            n_item = NumericTableWidgetItem(new_f)
            n_item.setText(str(int(new_f) if new_f == int(new_f) else new_f))
            if new_f < price_f:
                n_item.setForeground(QColor(80, 180, 255))
            elif new_f > price_f:
                n_item.setForeground(QColor(255, 120, 80))
            self.result_table.setItem(i, 8, n_item)
            min_text = "" if min_same in (None, "") else str(min_same)
            self.result_table.setItem(i, 9, QTableWidgetItem(min_text))
            tp_text = "" if tp_floor in (None, "") else str(tp_floor)
            self.result_table.setItem(i, 10, QTableWidgetItem(tp_text))
        self.result_table.setSortingEnabled(True)
        self.result_table.resizeColumnsToContents()

    # ----- ⑤ Amazon反映 -----
    def apply_prices_to_amazon(self) -> None:
        if not self.repricing_result:
            QMessageBox.warning(self, "エラー", "先に「価格改定実行」を完了してください")
            return
        try:
            from services.sp_api_reprice import collect_price_patch_targets
        except ImportError:
            from desktop.services.sp_api_reprice import collect_price_patch_targets  # type: ignore

        targets = collect_price_patch_targets(self.repricing_result.get("items") or [])
        if not targets:
            QMessageBox.information(self, "対象なし", "価格が変わった SKU がありません。")
            return

        max_items = None
        limit_note = "全件"
        if self.dry_run_cb.isChecked():
            max_items = int(self.dry_run_spin.value())
            limit_note = f"先頭 {max_items} 件のみ"

        sample = targets[: min(5, len(targets))]
        sample_lines = "\n".join(
            f"  {t['sku']}: {t.get('price')} → {t['new_price']}" for t in sample
        )
        reply = QMessageBox.question(
            self,
            "Amazonへ価格反映の確認",
            f"変更対象: {len(targets)} 件（反映: {limit_note}）\n\n"
            f"例:\n{sample_lines}\n\n"
            "本当に Amazon へ価格を送信しますか？\n"
            "※取り消せません。Seller Central で結果を確認してください。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.patch_btn.setEnabled(False)
        self._worker = AmazonPatchWorker(targets, max_items=max_items)
        self._worker.progress_message.connect(lambda m: self.source_edit.setText(m))
        self._worker.result_ready.connect(self._on_patch_completed)
        self._worker.error_occurred.connect(self._on_patch_error)
        self._worker.start()

    def _on_patch_completed(self, result: Dict[str, Any]) -> None:
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.patch_btn.setEnabled(True)
        self._workflow_post_step = 5
        ok = result.get("success_count", 0)
        ng = result.get("failed_count", 0)
        failed = result.get("failed") or []
        fail_preview = ""
        if failed:
            fail_preview = "\n失敗例:\n" + "\n".join(
                f"  {f.get('sku')}: {f.get('error', '')[:120]}" for f in failed[:5]
            )
        QMessageBox.information(
            self,
            "Amazon反映完了",
            f"成功: {ok} 件 / 失敗: {ng} 件 / 送信: {result.get('total', 0)} 件"
            f"{fail_preview}",
        )

    def _on_patch_error(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.patch_btn.setEnabled(True)
        QMessageBox.critical(self, "Amazon反映エラー", message)

    # ----- 最安追従 -----
    def _save_follow_settings(self, *_args) -> None:
        self.settings.setValue("repricer/sp_api/follow_interval_hours", int(self.follow_hours_spin.value()))
        self.settings.setValue("repricer/sp_api/follow_auto_patch", bool(self.follow_patch_cb.isChecked()))
        self.settings.setValue("repricer/sp_api/follow_max_listings", int(self.follow_max_spin.value()))
        self.settings.setValue("repricer/sp_api/follow_auto", bool(self.follow_auto_cb.isChecked()))
        self.settings.sync()
        if self.follow_auto_cb.isChecked():
            self._start_follow_timer()

    def _restore_follow_auto(self) -> None:
        auto = str(self.settings.value("repricer/sp_api/follow_auto", "false")).lower() in ("1", "true", "yes")
        self.follow_auto_cb.blockSignals(True)
        self.follow_auto_cb.setChecked(auto)
        self.follow_auto_cb.blockSignals(False)
        if auto:
            self._start_follow_timer()

    def _start_follow_timer(self) -> None:
        hours = max(4, int(self.follow_hours_spin.value()))
        self._follow_timer.start(hours * 3600 * 1000)

    def _on_follow_auto_toggled(self, checked: bool) -> None:
        self._save_follow_settings()
        if checked:
            self._start_follow_timer()
            QMessageBox.information(
                self,
                "自動巡回",
                f"{int(self.follow_hours_spin.value())} 時間ごとに最安追従を実行します。\n"
                "アプリを閉じると止まります。今すぐ1回やる場合は「最安追従を実行」を押してください。",
            )
        else:
            self._follow_timer.stop()

    def _on_follow_timer(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._follow_auto_run = True
        self.run_follow_repricer(from_timer=True)

    def run_follow_repricer(self, from_timer: bool = False) -> None:
        if self._worker is not None and self._worker.isRunning():
            if not from_timer:
                QMessageBox.information(self, "実行中", "別の処理が終わるまで待ってください。")
            return
        apply_amazon = bool(self.follow_patch_cb.isChecked())
        if apply_amazon and not from_timer:
            reply = QMessageBox.question(
                self,
                "最安追従の確認",
                "同条件最安を取得して価格を計算し、Amazon へ反映します。\n"
                "「巡回後にAmazonへ反映」が ON です。続行しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        elif not from_timer and not apply_amazon:
            pass

        rows = []
        if self.preview_df is not None and not from_timer:
            rows = self.preview_df.to_dict(orient="records")

        hours = max(4, int(self.follow_hours_spin.value()))
        runs_per_day = max(1, int(round(24 / hours)))
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.follow_btn.setEnabled(False)
        self._follow_auto_run = bool(from_timer)
        self._worker = FollowRepriceWorker(
            rows,
            apply_amazon=apply_amazon,
            chase_yen=100,
            early_days=150,
            runs_per_day=runs_per_day,
            max_listings=int(self.follow_max_spin.value()),
            patch_max_items=None,
        )
        self._worker.progress_message.connect(lambda m: self.source_edit.setText(m))
        self._worker.result_ready.connect(self._on_follow_completed)
        self._worker.error_occurred.connect(self._on_follow_error)
        self._worker.start()

    def _on_follow_completed(self, result: Dict[str, Any]) -> None:
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.follow_btn.setEnabled(True)
        self.repricing_result = result
        self._update_result_table(result)
        self.save_csv_btn.setEnabled(True)
        self.patch_btn.setEnabled(not bool(self.follow_patch_cb.isChecked()))
        summary = result.get("summary") or {}
        patch = result.get("patch")
        extra = ""
        if isinstance(patch, dict):
            extra = f"\nAmazon反映 成功{patch.get('success_count', 0)} / 失敗{patch.get('failed_count', 0)}"
        self.settings.setValue("repricer/sp_api/follow_last_run", datetime.now().isoformat(timespec="seconds"))
        self.settings.sync()
        msg = (
            f"最安追従が完了しました。\n"
            f"対象: {summary.get('total_rows', '-')} 件 / 価格変更: {summary.get('updated_rows', '-')} 件"
            f"{extra}"
        )
        self.source_edit.setText(msg.replace("\n", " "))
        if not self._follow_auto_run:
            QMessageBox.information(self, "最安追従完了", msg)
        self._follow_auto_run = False

    def _on_follow_error(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.follow_btn.setEnabled(True)
        self.source_edit.setText(f"最安追従エラー: {message}")
        if not self._follow_auto_run:
            QMessageBox.critical(self, "最安追従エラー", message)
        self._follow_auto_run = False

    # ----- 監査用 CSV -----
    def save_results_csv(self) -> None:
        if not self.repricing_result:
            QMessageBox.warning(self, "エラー", "保存する結果がありません")
            return
        items = self.repricing_result.get("items") or []
        if not items:
            QMessageBox.warning(self, "エラー", "結果行が空です")
            return
        default_name = f"sp_api_reprice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "改定結果をCSV保存",
            str(Path.home() / default_name),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        rows = []
        for it in items:
            rows.append(
                {
                    "SKU": it.get("sku"),
                    "ASIN": it.get("asin"),
                    "title": it.get("title"),
                    "days": it.get("days"),
                    "action": it.get("action"),
                    "reason": it.get("reason"),
                    "price": it.get("price"),
                    "new_price": it.get("new_price"),
                    "akaji": it.get("akaji"),
                    "takane": it.get("takane"),
                }
            )
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
        QMessageBox.information(self, "保存完了", f"保存しました:\n{path}")
