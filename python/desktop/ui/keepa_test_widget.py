#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa テスト用ウィジェット

ASIN を入力して、Keepa API から以下の情報を取得して表示するタブ:
- タイトル
- 画像URL
- 新品・中古（非常に良い/良い/可）: **live offers** の **本体+送料** 合計でコンディション別最安（円。1/100 返却時は 100 倍）
- 該当コンディションの出品が無いときは「無し」（offers が空のときは「-」）
- ランキング
- カテゴリ名
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QSettings
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QMenu,
    QGroupBox,
    QFormLayout,
    QDoubleSpinBox,
    QTextEdit,
)

# プロジェクトルートをパスに追加（python/desktop を sys.path に含める）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# デスクトップ側servicesを優先して読み込む
try:
    from services.keepa_service import KeepaService, KeepaProductInfo  # python/desktop/services
    from ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog
except Exception:
    # 明示的パス指定のフォールバック
    from desktop.services.keepa_service import KeepaService, KeepaProductInfo
    from desktop.ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog


class KeepaTestWidget(QWidget):
    """ASIN から Keepa 情報を取得するテストタブ"""

    EXTRA_COLUMNS = [
        "コンディション",
        "ASIN",
        "SKU",
        "仕入れ価格",
        "販売予定価格",
        "見込み利益",
        "損益分岐点",
        "想定利益率",
        "想定ROI",
        "TP0",
        "TP1",
        "TP2",
        "TP3",
        "下限TP0",
        "下限TP1",
        "下限TP2",
        "下限TP3",
        "AITP0",
        "AITP1",
        "AITP2",
        "AITP3",
        "AI根拠",
    ]
    SNAPSHOT_FILE_NAME = "keepa_test_snapshot.json"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        product_widget: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.keepa_service = KeepaService()
        self.product_widget = product_widget
        self._last_raw_product: Optional[Dict[str, Any]] = None
        self._last_title: str = ""
        self._selected_purchase_record: Optional[Dict[str, Any]] = None
        self._snapshot_path = self._resolve_snapshot_path()
        self._setup_ui()
        # 起動時に前回の検証状態を復元（失敗しても無視）
        self._load_snapshot_silent()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # --- 上部: ASIN 入力 + 取得ボタン ---
        top_layout = QHBoxLayout()

        top_layout.addWidget(QLabel("ASIN:"))

        self.asin_edit = QLineEdit()
        self.asin_edit.setPlaceholderText("例: B00007B4DM")
        top_layout.addWidget(self.asin_edit, 1)

        self.fetch_button = QPushButton("Keepa から取得")
        self.fetch_button.clicked.connect(self.on_fetch_clicked)
        top_layout.addWidget(self.fetch_button)

        layout.addLayout(top_layout)

        # --- TP利益率設定 + 下限TP入力ボタン ---
        tp_group = QGroupBox("TP利益率設定（見込み利益ベース）")
        tp_form = QFormLayout(tp_group)

        self.tp0_rate_spin = QDoubleSpinBox()
        self.tp0_rate_spin.setRange(0.0, 300.0)
        self.tp0_rate_spin.setDecimals(1)
        self.tp0_rate_spin.setSuffix("%")
        self.tp0_rate_spin.setValue(90.0)
        tp_form.addRow("TP0 利益率:", self.tp0_rate_spin)

        self.tp1_rate_spin = QDoubleSpinBox()
        self.tp1_rate_spin.setRange(0.0, 300.0)
        self.tp1_rate_spin.setDecimals(1)
        self.tp1_rate_spin.setSuffix("%")
        self.tp1_rate_spin.setValue(70.0)
        tp_form.addRow("TP1 利益率:", self.tp1_rate_spin)

        self.tp2_rate_spin = QDoubleSpinBox()
        self.tp2_rate_spin.setRange(0.0, 300.0)
        self.tp2_rate_spin.setDecimals(1)
        self.tp2_rate_spin.setSuffix("%")
        self.tp2_rate_spin.setValue(60.0)
        tp_form.addRow("TP2 利益率:", self.tp2_rate_spin)

        self.tp3_rate_spin = QDoubleSpinBox()
        self.tp3_rate_spin.setRange(0.0, 300.0)
        self.tp3_rate_spin.setDecimals(1)
        self.tp3_rate_spin.setSuffix("%")
        self.tp3_rate_spin.setValue(10.0)
        tp_form.addRow("TP3 利益率:", self.tp3_rate_spin)

        self.apply_lower_tp_btn = QPushButton("下限TP入力")
        self.apply_lower_tp_btn.setToolTip(
            "仕入れ価格・販売予定価格・見込み利益から実質コスト率を逆算し、"
            "設定した利益率で下限TP0〜TP3を自動入力します。"
        )
        self.apply_lower_tp_btn.clicked.connect(self._apply_lower_tp_by_rates)
        tp_form.addRow("", self.apply_lower_tp_btn)

        self.apply_ai_tp_btn = QPushButton("AI判定（AITP入力）")
        self.apply_ai_tp_btn.setToolTip(
            "GeminiでTP0〜TP3の提案価格を算出し、AITP0〜AITP3に反映します。"
        )
        self.apply_ai_tp_btn.clicked.connect(self._apply_ai_tp_judgement)
        tp_form.addRow("", self.apply_ai_tp_btn)

        snapshot_buttons_layout = QHBoxLayout()
        self.save_snapshot_btn = QPushButton("スナップショット保存")
        self.save_snapshot_btn.setToolTip("現在のKeepaテスト表示内容を保存します。")
        self.save_snapshot_btn.clicked.connect(self._save_snapshot_with_message)
        snapshot_buttons_layout.addWidget(self.save_snapshot_btn)

        self.load_snapshot_btn = QPushButton("スナップショット呼び出し")
        self.load_snapshot_btn.setToolTip("保存済みのKeepaテスト表示内容を復元します。")
        self.load_snapshot_btn.clicked.connect(self._load_snapshot_with_message)
        snapshot_buttons_layout.addWidget(self.load_snapshot_btn)
        tp_form.addRow("", snapshot_buttons_layout)
        layout.addWidget(tp_group)

        # --- 下部: 結果テーブル（1行固定） ---
        headers = [
            "タイトル",
            "画像URL",
            "新品価格",
            "中古・ほぼ新品",
            "中古・非常に良い",
            "中古・良い",
            "中古・可",
            "ランキング",
            "カテゴリ名",
            "詳細",
        ] + self.EXTRA_COLUMNS
        self.result_table = QTableWidget(1, len(headers))
        self.result_table.setHorizontalHeaderLabels(headers)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setSelectionMode(QTableWidget.SingleSelection)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.result_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.result_table.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self.result_table)

        # --- AI根拠の全文表示エリア ---
        ai_reason_group = QGroupBox("AI根拠（全文）")
        ai_reason_layout = QVBoxLayout(ai_reason_group)
        self.ai_reason_text = QTextEdit()
        self.ai_reason_text.setReadOnly(True)
        self.ai_reason_text.setPlaceholderText("AI判定を実行すると、ここに根拠全文が表示されます。")
        self.ai_reason_text.setMinimumHeight(90)
        ai_reason_layout.addWidget(self.ai_reason_text)
        layout.addWidget(ai_reason_group)

        # 初期メッセージ
        self._set_info_row("ASIN を入力して『Keepa から取得』を押してください。")
        # AI根拠列は長文になりやすいので、初期幅を広めにしておく
        ai_reason_col = self._get_table_column_index("AI根拠")
        if ai_reason_col >= 0:
            self.result_table.horizontalHeader().resizeSection(ai_reason_col, 420)

    # ------------------------------------------------------------------
    # UI ヘルパー
    # ------------------------------------------------------------------
    def _set_info_row(self, message: str) -> None:
        """テーブルに情報メッセージだけを表示する。"""
        self.result_table.clearContents()
        self.result_table.removeCellWidget(0, self._detail_column_index())
        self._last_raw_product = None
        self._last_title = ""
        self._selected_purchase_record = None
        self._set_ai_reason_text("")
        info_item = QTableWidgetItem(message)
        info_item.setFlags(Qt.ItemIsEnabled)
        self.result_table.setItem(0, 0, info_item)
        # 他の列は空のまま

    def _set_product_row(self, info: KeepaProductInfo) -> None:
        """取得した商品情報をテーブルに反映する。"""
        self.result_table.clearContents()
        self.result_table.removeCellWidget(0, self._detail_column_index())

        def _set(col: int, text: str) -> None:
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.result_table.setItem(0, col, item)

        def _format_price_jpy(
            state: Literal["ok", "no_seller", "no_data"],
            value: Optional[float],
        ) -> str:
            if state == "no_seller":
                return "無し"
            if state != "ok" or value is None:
                return "-"
            return str(int(round(value)))

        _set(0, info.title or "(タイトルなし)")
        _set(1, info.image_url or "-")
        _set(2, _format_price_jpy(info.new_price_state, info.new_price))
        _set(3, _format_price_jpy(info.used_like_new_state, info.used_like_new))
        _set(4, _format_price_jpy(info.used_very_good_state, info.used_very_good))
        _set(5, _format_price_jpy(info.used_good_state, info.used_good))
        _set(6, _format_price_jpy(info.used_acceptable_state, info.used_acceptable))
        _set(7, str(info.sales_rank) if info.sales_rank is not None else "-")
        _set(8, info.category_name or "-")
        self._set_extra_columns(self._selected_purchase_record)

        detail_btn = QPushButton("詳細")
        detail_btn.setToolTip("live offers の出品者別・価格・送料を表示します")
        detail_btn.clicked.connect(self._on_detail_clicked)
        self.result_table.setCellWidget(0, self._detail_column_index(), detail_btn)

    def _set_extra_columns(self, record: Optional[Dict[str, Any]]) -> None:
        record = record or {}
        column_keys = {
            "コンディション": ["コンディション", "condition", "condition_note"],
            "ASIN": ["ASIN", "asin"],
            "SKU": ["SKU", "sku"],
            "仕入れ価格": ["仕入れ価格", "仕入価格", "purchase_price", "cost"],
            "販売予定価格": ["販売予定価格", "planned_price", "price"],
            "見込み利益": ["見込み利益", "expected_profit", "profit"],
            "損益分岐点": ["損益分岐点", "break_even"],
            "想定利益率": ["想定利益率", "expected_margin"],
            "想定ROI": ["想定ROI", "expected_roi"],
            "TP0": ["TP0", "tp0", "TA0", "ta0"],
            "TP1": ["TP1", "tp1", "TA1", "ta1"],
            "TP2": ["TP2", "tp2", "TA2", "ta2"],
            "TP3": ["TP3", "tp3", "TA3", "ta3"],
            "下限TP0": ["下限TP0", "lower_tp0", "lowerTp0"],
            "下限TP1": ["下限TP1", "lower_tp1", "lowerTp1"],
            "下限TP2": ["下限TP2", "lower_tp2", "lowerTp2"],
            "下限TP3": ["下限TP3", "lower_tp3", "lowerTp3"],
            "AITP0": ["AITP0", "ai_tp0", "aiTp0"],
            "AITP1": ["AITP1", "ai_tp1", "aiTp1"],
            "AITP2": ["AITP2", "ai_tp2", "aiTp2"],
            "AITP3": ["AITP3", "ai_tp3", "aiTp3"],
            "AI根拠": ["AI根拠", "ai_reason", "aiReason", "ai_rationale", "rationale"],
        }
        for idx, col_name in enumerate(self.EXTRA_COLUMNS):
            value = self._get_record_value(record, column_keys.get(col_name, [col_name]))
            if value in (None, "") and col_name == "ASIN":
                value = self.asin_edit.text().strip()
            # 既存DBの TP 値を「下限TP」の初期値として使えるようにする
            if value in (None, "") and col_name.startswith("下限TP"):
                suffix = col_name.replace("下限TP", "")
                value = self._get_record_value(
                    record,
                    [f"TP{suffix}", f"tp{suffix}", f"TA{suffix}", f"ta{suffix}"],
                )
            txt = "" if value in (None, "") else str(value)
            item = QTableWidgetItem(txt)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if col_name == "AI根拠" and txt:
                item.setToolTip(txt)
            self.result_table.setItem(0, self._detail_column_index() + 1 + idx, item)
            if col_name == "AI根拠":
                self._set_ai_reason_text(txt)

    def _get_record_value(self, record: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            for record_key, value in record.items():
                if str(record_key).upper() == str(key).upper():
                    return value
        return None

    def _resolve_snapshot_path(self) -> Path:
        """スナップショット保存先を解決"""
        base_dir = Path(__file__).resolve().parents[1]  # python/desktop
        data_dir = base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / self.SNAPSHOT_FILE_NAME

    def _collect_current_snapshot_data(self) -> Dict[str, Any]:
        row: Dict[str, str] = {}
        for col in range(self.result_table.columnCount()):
            header_item = self.result_table.horizontalHeaderItem(col)
            if not header_item:
                continue
            header = header_item.text()
            item = self.result_table.item(0, col)
            row[header] = item.text() if item else ""

        data = {
            "asin_input": self.asin_edit.text().strip(),
            "tp_rates": {
                "tp0": self.tp0_rate_spin.value(),
                "tp1": self.tp1_rate_spin.value(),
                "tp2": self.tp2_rate_spin.value(),
                "tp3": self.tp3_rate_spin.value(),
            },
            "row": row,
            "selected_purchase_record": self._selected_purchase_record or {},
        }
        return data

    def _apply_snapshot_data(self, data: Dict[str, Any]) -> None:
        self.asin_edit.setText(str(data.get("asin_input", "") or ""))

        rates = data.get("tp_rates", {}) or {}
        self.tp0_rate_spin.setValue(float(rates.get("tp0", 90.0) or 90.0))
        self.tp1_rate_spin.setValue(float(rates.get("tp1", 70.0) or 70.0))
        self.tp2_rate_spin.setValue(float(rates.get("tp2", 60.0) or 60.0))
        self.tp3_rate_spin.setValue(float(rates.get("tp3", 10.0) or 10.0))

        self._selected_purchase_record = data.get("selected_purchase_record", {}) or None
        row = data.get("row", {}) or {}

        self.result_table.clearContents()
        self.result_table.removeCellWidget(0, self._detail_column_index())
        for col in range(self.result_table.columnCount()):
            header_item = self.result_table.horizontalHeaderItem(col)
            if not header_item:
                continue
            header = header_item.text()
            text = str(row.get(header, "") or "")
            if header == "詳細":
                # ここは通常ボタン列。スナップショット復元時は説明テキストを表示しておく
                text = text or "※ Keepa価格は『Keepa から取得』で更新できます。"
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.result_table.setItem(0, col, item)
        self._set_ai_reason_text(str(row.get("AI根拠", "") or ""))

    def _save_snapshot(self) -> None:
        data = self._collect_current_snapshot_data()
        self._snapshot_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_snapshot(self) -> bool:
        if not self._snapshot_path.exists():
            return False
        try:
            raw = self._snapshot_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return False
            self._apply_snapshot_data(data)
            return True
        except Exception:
            return False

    def _save_snapshot_with_message(self) -> None:
        try:
            self._save_snapshot()
            QMessageBox.information(
                self,
                "スナップショット保存",
                f"保存しました。\n{self._snapshot_path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "スナップショット保存", f"保存に失敗しました。\n{e}")

    def _load_snapshot_with_message(self) -> None:
        if self._load_snapshot():
            QMessageBox.information(self, "スナップショット呼び出し", "保存済みスナップショットを復元しました。")
        else:
            QMessageBox.information(self, "スナップショット呼び出し", "復元できるスナップショットがありません。")

    def _load_snapshot_silent(self) -> None:
        self._load_snapshot()

    def _get_table_column_index(self, header_name: str) -> int:
        for col in range(self.result_table.columnCount()):
            header_item = self.result_table.horizontalHeaderItem(col)
            if header_item and header_item.text() == header_name:
                return col
        return -1

    def _detail_column_index(self) -> int:
        idx = self._get_table_column_index("詳細")
        return idx if idx >= 0 else 9

    def _parse_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        s = str(value).strip().replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    def _get_numeric_value_for_calc(self, header_name: str, record_keys: List[str]) -> Optional[float]:
        # まず仕入DB呼び出しレコードを優先
        if self._selected_purchase_record:
            rv = self._get_record_value(self._selected_purchase_record, record_keys)
            f = self._parse_float(rv)
            if f is not None:
                return f
        # 次にテーブル表示値
        idx = self._get_table_column_index(header_name)
        if idx >= 0:
            item = self.result_table.item(0, idx)
            if item:
                f = self._parse_float(item.text())
                if f is not None:
                    return f
        return None

    def _set_table_cell_text(self, header_name: str, text: str) -> None:
        idx = self._get_table_column_index(header_name)
        if idx < 0:
            return
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        if header_name == "AI根拠" and text:
            item.setToolTip(text)
        self.result_table.setItem(0, idx, item)
        if header_name == "AI根拠":
            self._set_ai_reason_text(text)

    def _set_ai_reason_text(self, text: str) -> None:
        if hasattr(self, "ai_reason_text"):
            self.ai_reason_text.setPlainText((text or "").strip())

    def _safe_int_price(self, value: Any) -> Optional[int]:
        fv = self._parse_float(value)
        if fv is None:
            return None
        return int(round(fv))

    def _extract_json_candidate(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Gemini 応答テキストから JSON オブジェクトをできるだけ頑健に抽出する。
        - そのまま json.loads
        - ```json ... ``` を抽出
        - 最初の { から最後の } を抽出
        """
        if not text:
            return None
        raw = text.strip()

        # 1) まずそのまま
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # 2) fenced code block
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE)
        if fence:
            block = fence.group(1).strip()
            try:
                parsed = json.loads(block)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        # 3) 最初の { ... 最後の } を抽出
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            candidate = raw[start : end + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return None
        return None

    def _build_keepa_fallback_reason(
        self,
        *,
        keepa_summary: Dict[str, Any],
        keepa_369_analysis: Dict[str, Any],
        lower_tp: Dict[str, Optional[int]],
        planned_price: float,
    ) -> str:
        """AI根拠が不十分なときに、取得済みKeepa情報で最低限の根拠文を組み立てる。"""
        parts: List[str] = []
        cp = (keepa_summary.get("condition_prices") or {}) if isinstance(keepa_summary, dict) else {}
        used_count = keepa_summary.get("used_offer_count") if isinstance(keepa_summary, dict) else None
        drops = keepa_369_analysis.get("total_effective_drop_count") if isinstance(keepa_369_analysis, dict) else None
        used_avg = keepa_369_analysis.get("used_price_avg") if isinstance(keepa_369_analysis, dict) else None
        offer_delta = keepa_369_analysis.get("used_offer_count_delta") if isinstance(keepa_369_analysis, dict) else None

        if cp:
            vg = cp.get("used_very_good")
            g = cp.get("used_good")
            a = cp.get("used_acceptable")
            if vg is not None or g is not None or a is not None:
                parts.append(f"Keepa中古価格は 非常に良い:{vg or '-'} / 良い:{g or '-'} / 可:{a or '-'} を参照。")
        if used_count is not None:
            parts.append(f"中古出品者数は {used_count} 件を基準に競合状況を評価。")
        if drops is not None:
            parts.append(f"180日分析の実売推測込みドロップ数は {drops} 回。")
        if used_avg is not None:
            parts.append(f"中古価格平均は約 {int(round(float(used_avg)))} 円。")
        if offer_delta is not None:
            parts.append(f"出品者数の増減は {offer_delta:+} 件。")

        parts.append(
            f"下限TP（{lower_tp.get('lower_tp0')}/{lower_tp.get('lower_tp1')}/{lower_tp.get('lower_tp2')}/{lower_tp.get('lower_tp3')}）"
            f"と販売予定価格 {int(round(planned_price))} 円を踏まえてAITPを設定。"
        )
        return " ".join(parts)

    def _apply_lower_tp_by_rates(self) -> None:
        """
        「実質コスト率を逆算して目標販売価格を算出する」方式で
        下限TP0〜下限TP3を自動入力する。
        """
        purchase_price = self._get_numeric_value_for_calc(
            "仕入れ価格", ["仕入れ価格", "仕入価格", "purchase_price", "cost"]
        )
        planned_price = self._get_numeric_value_for_calc(
            "販売予定価格", ["販売予定価格", "planned_price", "price"]
        )
        expected_profit = self._get_numeric_value_for_calc(
            "見込み利益", ["見込み利益", "expected_profit", "profit"]
        )

        if purchase_price is None or planned_price is None or expected_profit is None:
            QMessageBox.warning(
                self,
                "下限TP入力",
                "仕入れ価格・販売予定価格・見込み利益の値が不足しているため計算できません。",
            )
            return
        if planned_price <= 0:
            QMessageBox.warning(self, "下限TP入力", "販売予定価格が0以下のため計算できません。")
            return

        # 実質コスト率 r ≒ 1 - (仕入れ価格 + 見込み利益) / 販売予定価格
        r = 1.0 - ((purchase_price + expected_profit) / planned_price)
        # 分母 1-r が 0 付近になる異常値を防御
        denom = 1.0 - r
        if denom <= 1e-6:
            QMessageBox.warning(
                self,
                "下限TP入力",
                "実質コスト率の推定に失敗しました（分母が0に近い）。元データを確認してください。",
            )
            return

        rates = {
            "下限TP0": self.tp0_rate_spin.value() / 100.0,
            "下限TP1": self.tp1_rate_spin.value() / 100.0,
            "下限TP2": self.tp2_rate_spin.value() / 100.0,
            "下限TP3": self.tp3_rate_spin.value() / 100.0,
        }

        # 目標販売価格 ≒ (仕入れ価格 + 見込み利益×rate) / (1-r)
        calculated: Dict[str, int] = {}
        for key, rate in rates.items():
            target_price = (purchase_price + (expected_profit * rate)) / denom
            calculated[key] = int(round(target_price))
            self._set_table_cell_text(key, str(calculated[key]))

        # 仕入DB呼び出し元レコードにも保持（同一セッション内の参照用）
        if self._selected_purchase_record is not None:
            self._selected_purchase_record["下限TP0"] = calculated["下限TP0"]
            self._selected_purchase_record["下限TP1"] = calculated["下限TP1"]
            self._selected_purchase_record["下限TP2"] = calculated["下限TP2"]
            self._selected_purchase_record["下限TP3"] = calculated["下限TP3"]
        try:
            self._save_snapshot()
        except Exception:
            pass

        QMessageBox.information(
            self,
            "下限TP入力",
            (
                "下限TPを入力しました。\n"
                f"下限TP0: {calculated['下限TP0']} / "
                f"下限TP1: {calculated['下限TP1']} / "
                f"下限TP2: {calculated['下限TP2']} / "
                f"下限TP3: {calculated['下限TP3']}"
            ),
        )

    def _apply_ai_tp_judgement(self) -> None:
        """
        Gemini に TP価格の判定を依頼し、AITP0〜AITP3 と AI根拠を反映する。
        """
        purchase_price = self._get_numeric_value_for_calc(
            "仕入れ価格", ["仕入れ価格", "仕入価格", "purchase_price", "cost"]
        )
        planned_price = self._get_numeric_value_for_calc(
            "販売予定価格", ["販売予定価格", "planned_price", "price"]
        )
        expected_profit = self._get_numeric_value_for_calc(
            "見込み利益", ["見込み利益", "expected_profit", "profit"]
        )
        if purchase_price is None or planned_price is None or expected_profit is None:
            QMessageBox.warning(
                self,
                "AI判定",
                "仕入れ価格・販売予定価格・見込み利益が不足しているため、AI判定できません。",
            )
            return

        lower_tp = {
            "lower_tp0": self._safe_int_price(
                self._get_numeric_value_for_calc("下限TP0", ["下限TP0", "lower_tp0", "lowerTp0"])
            ),
            "lower_tp1": self._safe_int_price(
                self._get_numeric_value_for_calc("下限TP1", ["下限TP1", "lower_tp1", "lowerTp1"])
            ),
            "lower_tp2": self._safe_int_price(
                self._get_numeric_value_for_calc("下限TP2", ["下限TP2", "lower_tp2", "lowerTp2"])
            ),
            "lower_tp3": self._safe_int_price(
                self._get_numeric_value_for_calc("下限TP3", ["下限TP3", "lower_tp3", "lowerTp3"])
            ),
        }
        rates = {
            "tp0_ratio": self.tp0_rate_spin.value() / 100.0,
            "tp1_ratio": self.tp1_rate_spin.value() / 100.0,
            "tp2_ratio": self.tp2_rate_spin.value() / 100.0,
            "tp3_ratio": self.tp3_rate_spin.value() / 100.0,
        }

        asin = self.asin_edit.text().strip()
        keepa_summary: Dict[str, Any] = {}
        keepa_369_analysis: Dict[str, Any] = {}
        sell_probability_estimates: List[Dict[str, Any]] = []
        if self._last_raw_product:
            keepa_summary["condition_prices"] = self.keepa_service.extract_condition_prices_jp(
                self._last_raw_product,
                reference_jpy=planned_price,
            )
            keepa_summary["used_offer_count"] = self.keepa_service.extract_used_offer_count(
                self._last_raw_product
            )
            try:
                # 3-6-9解析は履歴(stats/csv)が必要なため、必要に応じて履歴データを再取得する
                analysis_source = self._last_raw_product
                keepa_369_analysis = self.keepa_service.analyze_keepa_for_369(
                    analysis_source,
                    window_days=180,
                )
                # 履歴不足（ドロップ数/価格平均が取れない）なら、stats付きで再取得して再解析
                if (
                    not keepa_369_analysis
                    or (
                        keepa_369_analysis.get("sales_drop_count", 0) == 0
                        and keepa_369_analysis.get("used_price_avg") in (None, 0)
                    )
                ):
                    raw_with_stats = self.keepa_service.fetch_raw_product_by_asin(
                        asin,
                        stats=180,
                        offers=60,
                        only_live_offers=False,
                    )
                    if raw_with_stats:
                        analysis_source = raw_with_stats
                        keepa_369_analysis = self.keepa_service.analyze_keepa_for_369(
                            analysis_source,
                            window_days=180,
                        )
                        # AI判定時にも履歴を参照できるよう、最後に取得したrawを保持
                        self._last_raw_product = raw_with_stats

                sell_probability_estimates = self.keepa_service.build_price_sell_probability_estimates(
                    keepa_369_analysis,
                    lower_price=lower_tp.get("lower_tp0"),
                    planned_price=planned_price,
                    step_count=7,
                )
            except Exception:
                keepa_369_analysis = {}
                sell_probability_estimates = []

        settings = QSettings("HIRIO", "DesktopApp")
        api_key = (settings.value("ocr/gemini_api_key", "") or "").strip()
        configured_model = (settings.value("ocr/gemini_model", "gemini-flash-latest") or "gemini-flash-latest").strip()
        if not api_key:
            QMessageBox.warning(self, "AI判定", "Gemini APIキーが未設定です。設定タブで入力してください。")
            return

        payload = {
            "asin": asin,
            "purchase_price": purchase_price,
            "planned_price": planned_price,
            "expected_profit": expected_profit,
            "configured_ratios": rates,
            "lower_tp": lower_tp,
            "keepa_summary": keepa_summary,
            "keepa_369_analysis": keepa_369_analysis,
            "sell_probability_estimates": sell_probability_estimates,
            "rules": {
                "must_keep_at_least_lower_tp": True,
                "tp0_to_tp3_should_be_non_increasing_or_equal": True,
                "must_not_copy_existing_tp_values": True,
            },
        }
        prompt = (
            "あなたは中古せどり価格最適化アシスタントです。"
            "以下の入力値から、AITP0〜AITP3を提案してください。"
            "出力はJSONのみ（説明文をJSON外に書かない）。\n\n"
            "必須出力スキーマ:\n"
            "{\n"
            '  "aitp0": integer,\n'
            '  "aitp1": integer,\n'
            '  "aitp2": integer,\n'
            '  "aitp3": integer,\n'
            '  "reason": "日本語で2〜4文程度。根拠を簡潔に"\n'
            "}\n\n"
            "制約:\n"
            "- 価格はすべて整数円\n"
            "- lower_tp がある場合はそれ未満にしない\n"
            "- aitp0 >= aitp1 >= aitp2 >= aitp3 を守る\n"
            "- 過度に高い価格にならないよう planned_price を考慮\n"
            "- 既存TP（手入力値）には引っ張られず、Keepa状況とlower_tpと利益率設定だけで判断\n"
            "- 理由文で『既存TPを維持』という表現を使わない\n\n"
            "分析指示:\n"
            "- keepa_369_analysis の drop_count系、offer_count増減、価格帯推移を使って判断する\n"
            "- sell_probability_estimates から、どの価格帯が売れやすいかを根拠に含める\n"
            "- reasonには必ず『売れる確率が高い価格帯』を1つ以上具体的に書く\n\n"
            "禁止表現:\n"
            "- 『Keepa分析データがない』という断定\n"
            "- 『今回Keepaが無効』など、データ未取得を前提にした文\n\n"
            f"入力データ:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        retry_prompt = (
            "前回の出力形式が不正でした。"
            "今度は必ず1つのJSONオブジェクトのみを返してください。"
            "先頭を{、末尾を}にし、改行以外の余計な文を一切書かないでください。\n\n"
            + prompt
        )

        try:
            import google.generativeai as genai  # type: ignore
        except ImportError:
            QMessageBox.warning(
                self,
                "AI判定",
                "google-generativeai が未インストールです。`pip install google-generativeai` を実行してください。",
            )
            return

        # モデル名の互換ゆらぎに備え、候補を順に試す（404 model not found 対策）
        candidate_models: List[str] = []
        for m in [
            configured_model,
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-flash-latest",
        ]:
            mm = (m or "").strip()
            if mm and mm not in candidate_models:
                candidate_models.append(mm)

        self.apply_ai_tp_btn.setEnabled(False)
        self.apply_ai_tp_btn.setText("AI判定中...")
        last_error: Optional[Exception] = None
        result: Optional[Dict[str, Any]] = None
        used_model_name: Optional[str] = None
        try:
            genai.configure(api_key=api_key)

            # APIが返す利用可能モデルから、generateContent対応モデルを追加
            # 環境差分で固定候補が404になるケースを吸収する
            discovered_candidates: List[str] = []
            try:
                for model_info in genai.list_models():
                    methods = getattr(model_info, "supported_generation_methods", None) or []
                    if "generateContent" not in methods:
                        continue
                    model_name_full = str(getattr(model_info, "name", "") or "").strip()
                    if not model_name_full:
                        continue
                    # "models/xxx" -> "xxx" に正規化
                    normalized = model_name_full
                    if normalized.startswith("models/"):
                        normalized = normalized.split("/", 1)[1]
                    if normalized and normalized not in discovered_candidates:
                        discovered_candidates.append(normalized)
            except Exception:
                discovered_candidates = []

            # 優先順位:
            # 1) 設定/固定候補
            # 2) APIで見つかった flash 系
            # 3) APIで見つかったその他
            flash_discovered = [m for m in discovered_candidates if "flash" in m.lower()]
            other_discovered = [m for m in discovered_candidates if m not in flash_discovered]
            for m in flash_discovered + other_discovered:
                if m not in candidate_models:
                    candidate_models.append(m)

            for model_name in candidate_models:
                try:
                    model = genai.GenerativeModel(
                        model_name,
                        generation_config={
                            "temperature": 0.2,
                            "max_output_tokens": 1024,
                            "response_mime_type": "application/json",
                        },
                    )
                    response = model.generate_content(prompt)
                    text = getattr(response, "text", "") or ""
                    if not text and getattr(response, "candidates", None):
                        parts = response.candidates[0].content.parts  # type: ignore[attr-defined]
                        if parts:
                            text = parts[0].text
                    parsed = self._extract_json_candidate(text)
                    if parsed is None:
                        # 1回だけ厳格フォーマットで再試行
                        response_retry = model.generate_content(retry_prompt)
                        text_retry = getattr(response_retry, "text", "") or ""
                        if not text_retry and getattr(response_retry, "candidates", None):
                            parts_retry = response_retry.candidates[0].content.parts  # type: ignore[attr-defined]
                            if parts_retry:
                                text_retry = parts_retry[0].text
                        parsed = self._extract_json_candidate(text_retry)
                    if isinstance(parsed, dict):
                        result = parsed
                        used_model_name = model_name
                        break
                except Exception as e:
                    last_error = e
                    continue
            if result is None:
                raise RuntimeError(
                    f"利用可能なGeminiモデルが見つかりませんでした。"
                    f"設定モデル: {configured_model}\n候補: {', '.join(candidate_models)}\n"
                    f"最後のエラー: {last_error}"
                )
        except Exception as e:
            QMessageBox.critical(self, "AI判定エラー", f"AI判定に失敗しました。\n{e}")
            return
        finally:
            self.apply_ai_tp_btn.setEnabled(True)
            self.apply_ai_tp_btn.setText("AI判定（AITP入力）")

        def _clamp_aitp(value: Any, lower: Optional[int]) -> int:
            v = self._safe_int_price(value)
            if v is None:
                v = int(round(planned_price))
            if lower is not None:
                v = max(v, lower)
            if v <= 0:
                v = 1
            return int(v)

        result = result or {}
        ai0 = _clamp_aitp(result.get("aitp0"), lower_tp.get("lower_tp0"))
        ai1 = _clamp_aitp(result.get("aitp1"), lower_tp.get("lower_tp1"))
        ai2 = _clamp_aitp(result.get("aitp2"), lower_tp.get("lower_tp2"))
        ai3 = _clamp_aitp(result.get("aitp3"), lower_tp.get("lower_tp3"))
        # 単調性を強制
        ai1 = min(ai1, ai0)
        ai2 = min(ai2, ai1)
        ai3 = min(ai3, ai2)

        reason_text = str(result.get("reason", "")).strip()
        low_reason = reason_text.lower()
        if (
            not reason_text
            or "keepa分析データがない" in reason_text
            or "keepaが無効" in reason_text
            or "分析データがない" in reason_text
            or "no keepa data" in low_reason
        ):
            reason_text = self._build_keepa_fallback_reason(
                keepa_summary=keepa_summary,
                keepa_369_analysis=keepa_369_analysis,
                lower_tp=lower_tp,
                planned_price=planned_price,
            )

        self._set_table_cell_text("AITP0", str(ai0))
        self._set_table_cell_text("AITP1", str(ai1))
        self._set_table_cell_text("AITP2", str(ai2))
        self._set_table_cell_text("AITP3", str(ai3))
        self._set_table_cell_text("AI根拠", reason_text)

        if self._selected_purchase_record is not None:
            self._selected_purchase_record["AITP0"] = ai0
            self._selected_purchase_record["AITP1"] = ai1
            self._selected_purchase_record["AITP2"] = ai2
            self._selected_purchase_record["AITP3"] = ai3
            self._selected_purchase_record["AI根拠"] = reason_text
        try:
            self._save_snapshot()
        except Exception:
            pass

        QMessageBox.information(
            self,
            "AI判定",
            (
                f"AITPを入力しました。（モデル: {used_model_name or configured_model}）\n"
                f"AITP0={ai0}, AITP1={ai1}, AITP2={ai2}, AITP3={ai3}"
            ),
        )

    def _show_context_menu(self, position) -> None:
        menu = QMenu(self)
        select_action = menu.addAction("仕入DB一覧から商品を呼び出し")
        select_action.triggered.connect(self._open_purchase_selector_dialog)
        open_keepa_action = menu.addAction("該当ASINでKeepaを開く")
        open_keepa_action.triggered.connect(self._open_keepa_for_current_asin)
        menu.exec_(self.result_table.viewport().mapToGlobal(position))

    def _open_keepa_for_current_asin(self) -> None:
        asin = ""
        # 1) 仕入DB呼び出し済みのレコードがあればそこを優先
        if self._selected_purchase_record:
            v = self._get_record_value(self._selected_purchase_record, ["ASIN", "asin"])
            if v not in (None, ""):
                asin = str(v).strip()

        # 2) テーブルのASIN列（表示値）
        if not asin:
            asin_col = -1
            for col in range(self.result_table.columnCount()):
                header_item = self.result_table.horizontalHeaderItem(col)
                if header_item and header_item.text() == "ASIN":
                    asin_col = col
                    break
            if asin_col >= 0:
                item = self.result_table.item(0, asin_col)
                if item and item.text().strip():
                    asin = item.text().strip()

        # 3) 入力欄
        if not asin:
            asin = self.asin_edit.text().strip()

        if not asin:
            QMessageBox.warning(self, "Keepa", "ASINが見つかりません。先に商品を呼び出すかASINを入力してください。")
            return

        QDesktopServices.openUrl(QUrl(f"https://keepa.com/#!product/5-{asin}"))

    def _open_purchase_selector_dialog(self) -> None:
        records = self._get_purchase_records_for_picker()
        if not records:
            QMessageBox.information(
                self,
                "仕入DB",
                "仕入DBに表示可能なデータがありません。",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("仕入DBから商品を選択")
        dialog.resize(1100, 520)
        layout = QVBoxLayout(dialog)

        info_label = QLabel("右クリックから呼び出した商品は Keepa テスト欄に反映されます。")
        layout.addWidget(info_label)

        table = QTableWidget(len(records), 9, dialog)
        table.setHorizontalHeaderLabels([
            "仕入れ日",
            "SKU",
            "ASIN",
            "JAN",
            "商品名",
            "コンディション",
            "仕入れ価格",
            "販売予定価格",
            "見込み利益",
        ])
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)

        for row_idx, record in enumerate(records):
            values = [
                self._get_record_value(record, ["仕入れ日", "purchase_date"]),
                self._get_record_value(record, ["SKU", "sku"]),
                self._get_record_value(record, ["ASIN", "asin"]),
                self._get_record_value(record, ["JAN", "jan"]),
                self._get_record_value(record, ["商品名", "product_name", "title"]),
                self._get_record_value(record, ["コンディション", "condition", "condition_note"]),
                self._get_record_value(record, ["仕入れ価格", "仕入価格", "purchase_price", "cost"]),
                self._get_record_value(record, ["販売予定価格", "planned_price", "price"]),
                self._get_record_value(record, ["見込み利益", "expected_profit", "profit"]),
            ]
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem("" if value in (None, "") else str(value))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setData(Qt.UserRole, record)
                table.setItem(row_idx, col_idx, item)

        layout.addWidget(table)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        button_box.button(QDialogButtonBox.Ok).setText("呼び出し")
        button_box.button(QDialogButtonBox.Cancel).setText("キャンセル")
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        table.cellDoubleClicked.connect(lambda *_: dialog.accept())

        if dialog.exec() != QDialog.Accepted:
            return

        row = table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "選択エラー", "商品を1件選択してください。")
            return

        first_item = table.item(row, 0)
        if first_item is None:
            QMessageBox.warning(self, "選択エラー", "選択した行のデータを取得できませんでした。")
            return
        record = first_item.data(Qt.UserRole) or {}
        self._apply_selected_purchase_record(record)
        try:
            self._save_snapshot()
        except Exception:
            pass

    def _get_purchase_records_for_picker(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        try:
            if self.product_widget is not None:
                ensure = getattr(self.product_widget, "ensure_initial_data_loaded", None)
                if callable(ensure):
                    ensure()
                for attr_name in ("purchase_all_records_master", "purchase_all_records", "purchase_records"):
                    attr_val = getattr(self.product_widget, attr_name, None)
                    if isinstance(attr_val, list) and attr_val:
                        records = attr_val
                        break
        except Exception:
            records = []

        if records:
            return records

        try:
            from database.purchase_db import PurchaseDatabase
            return PurchaseDatabase().list_all()
        except Exception:
            return []

    def _apply_selected_purchase_record(self, record: Dict[str, Any]) -> None:
        self._selected_purchase_record = record or {}
        asin = self._get_record_value(self._selected_purchase_record, ["ASIN", "asin"])
        if asin not in (None, ""):
            self.asin_edit.setText(str(asin).strip())

        title = self._get_record_value(self._selected_purchase_record, ["商品名", "product_name", "title"])
        self._last_title = "" if title in (None, "") else str(title)
        self._last_raw_product = None

        self.result_table.clearContents()
        self.result_table.removeCellWidget(0, self._detail_column_index())
        base_values = [
            self._last_title or "(タイトルなし)",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
        ]
        for idx, text in enumerate(base_values):
            item = QTableWidgetItem(str(text))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.result_table.setItem(0, idx, item)
        self._set_extra_columns(self._selected_purchase_record)

        info_item = QTableWidgetItem("※ Keepa価格は『Keepa から取得』で更新できます。")
        info_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.result_table.setItem(0, self._detail_column_index(), info_item)
        try:
            self._save_snapshot()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # スロット
    # ------------------------------------------------------------------
    def _on_detail_clicked(self) -> None:
        if not self._last_raw_product:
            QMessageBox.information(
                self,
                "出品詳細",
                "先に「Keepa から取得」でデータを読み込んでください。",
            )
            return
        new_rows, used_rows = self.keepa_service.build_live_offer_display_rows(self._last_raw_product)
        dlg = KeepaOfferDetailDialog(
            self,
            asin=self.asin_edit.text().strip(),
            title=self._last_title,
            new_rows=new_rows,
            used_rows=used_rows,
        )
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def on_fetch_clicked(self) -> None:
        asin = self.asin_edit.text().strip()
        if not asin:
            QMessageBox.warning(self, "入力エラー", "ASIN を入力してください。")
            return

        try:
            info, raw = self.keepa_service.fetch_product_with_raw(asin)
        except RuntimeError as e:
            QMessageBox.critical(self, "Keepa エラー", str(e))
            return

        self._last_raw_product = raw
        self._last_title = info.title or ""
        self._set_product_row(info)
        try:
            self._save_snapshot()
        except Exception:
            pass








