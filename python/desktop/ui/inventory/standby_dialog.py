#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ネット仕入のスタンバイ画面。

購入台帳（Discord／電脳拡張）→ ここに表示 → ネット仕入一覧へ送る。
購入済みだけを表示し、チェックした複数件をまとめて送れる。
3/6/9・TP0〜TP3 を指定可能。

AI提案は「届くまでの数日」に Keepa 本取得してから裏で用意する（即時必須ではない）。
定時タスク HIRIO_purchase_ai_plan／手動「準備中を今すぐ消化」。
失敗時は「失敗」表示＋理由。再度判定で1件だけ再実行できる。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from services.hit_standby import (
        load_standby_items,
        mark_imported,
        normalize_rule369,
        purchase_to_inventory_row,
        resolve_hirio_shared_dir,
    )
    from services.standby_ai_plan import StandbyAiPlan
except ImportError:
    from desktop.services.hit_standby import (  # type: ignore
        load_standby_items,
        mark_imported,
        normalize_rule369,
        purchase_to_inventory_row,
        resolve_hirio_shared_dir,
    )
    from desktop.services.standby_ai_plan import StandbyAiPlan  # type: ignore

_WATCHER_DIR = Path(r"C:\HIRIO\watcher")
_PROCESS_CMD = _WATCHER_DIR / "process_purchase_ai_plans.cmd"

# 列: 0=選, 1=状態, 2=日時, 3=商品名, 4=仕入, 5=販売予定, 6=粗利, 7=ルール, 8=TP0
_COL_CHECK = 0
_COL_RULE = 7
_COL_TP0 = 8


def _delete_purchase(token: str) -> tuple[str, Optional[Dict[str, Any]]]:
    shared = resolve_hirio_shared_dir()
    text = str(shared)
    if text not in sys.path:
        sys.path.insert(0, text)
    import hit_snapshot as hs  # noqa: WPS433

    return hs.delete_purchase_by_token(token, remove_snapshot=True)


class _ProcessPendingWorker(QThread):
    """watcher の Keepa本取得＋AI キューを実行（届く前の準備用）。"""

    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        limit: int = 10,
        *,
        token: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._limit = max(1, int(limit))
        self._token = (token or "").strip()

    def run(self) -> None:
        try:
            py = _WATCHER_DIR / ".venv" / "Scripts" / "python.exe"
            script = _WATCHER_DIR / "process_purchase_ai_plans.py"
            if not py.is_file() or not script.is_file():
                raise RuntimeError(
                    f"watcher の実行環境が見つかりません:\n{py}\n{script}"
                )
            cmd = [str(py), "-u", str(script)]
            if self._token:
                cmd.extend(["--token", self._token])
            else:
                cmd.extend(["--limit", str(self._limit)])
            proc = subprocess.run(
                cmd,
                cwd=str(_WATCHER_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60 * 30,
                check=False,
            )
            out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            if proc.returncode != 0:
                raise RuntimeError(out[-2000:] or f"exit {proc.returncode}")
            self.finished_ok.emit(out[-1500:] if out else "完了")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


def _reset_ai_plan(token: str) -> tuple[str, Optional[Dict[str, Any]]]:
    shared = resolve_hirio_shared_dir()
    text = str(shared)
    if text not in sys.path:
        sys.path.insert(0, text)
    import hit_snapshot as hs  # noqa: WPS433

    return hs.reset_purchase_ai_plan(token)


def _ai_plan_enabled() -> bool:
    shared = resolve_hirio_shared_dir()
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    import hit_snapshot as hs  # noqa: WPS433

    return bool(hs.is_purchase_ai_plan_enabled())


def _set_ai_plan_enabled(enabled: bool) -> Dict[str, Any]:
    shared = resolve_hirio_shared_dir()
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    import hit_snapshot as hs  # noqa: WPS433

    return hs.set_purchase_ai_plan_enabled(bool(enabled))


def _ai_plan_env_overrides() -> bool:
    shared = resolve_hirio_shared_dir()
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    import hit_snapshot as hs  # noqa: WPS433

    return bool(hs.purchase_ai_plan_env_overrides())


def _status_label(item: Dict[str, Any]) -> str:
    if item.get("imported"):
        return "送済"
    shared = resolve_hirio_shared_dir()
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    import hit_snapshot as hs  # noqa: WPS433

    return hs.ai_plan_display_status(item)


class HitStandbyDialog(QDialog):
    """購入候補のスタンバイ一覧（購入済みのみ）。"""

    def __init__(
        self,
        *,
        on_send_row: Callable[[Dict[str, Any]], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("スタンバイ（購入候補）")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.resize(1100, 700)
        self._on_send_row = on_send_row
        self._items: List[Dict[str, Any]] = []
        self._current: Optional[Dict[str, Any]] = None
        self._current_idx: int = -1
        # token -> {rule369, tp0..tp3, ai: StandbyAiPlan|None}
        self._plans: Dict[str, Dict[str, Any]] = {}
        self._ai_worker: Optional[_ProcessPendingWorker] = None
        self._updating_editors = False

        root = QVBoxLayout(self)
        shared = resolve_hirio_shared_dir()
        self.hint = QLabel(
            "購入入力済みの候補だけを表示します。"
            "「選」にチェック →「仕入一覧に送る」。3/6/9 と TP0〜TP3 は送信時にコメント／行へ載せます。\n"
            "AI提案は届くまでの数日で Keepa 本取得してから用意します。"
            "失敗時は「失敗」表示＋理由。再判定できます。自動では仕入一覧へ送りません。\n"
            f"データ場所: {shared}"
        )
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        check_row = QHBoxLayout()
        self.select_all_btn = QPushButton("未送信を全選択")
        self.select_all_btn.setToolTip("まだ送っていない購入済みにチェックを付けます")
        self.select_all_btn.clicked.connect(self._select_all_unsent)
        check_row.addWidget(self.select_all_btn)
        self.clear_check_btn = QPushButton("チェック解除")
        self.clear_check_btn.clicked.connect(self._clear_checks)
        check_row.addWidget(self.clear_check_btn)
        self.ai_today_btn = QPushButton("準備中を今すぐ消化")
        self.ai_today_btn.setToolTip(
            "届く前の準備用。Keepa を本取得してから Gemini で 3/6/9・TP0〜TP3 を台帳に書きます。\n"
            "通常は定時タスク（6時間ごと）で十分です。急ぐときだけ押してください。\n"
            "入力欄への反映は「提案を反映」を押したときだけです。"
        )
        self.ai_today_btn.clicked.connect(self._run_process_pending)
        check_row.addWidget(self.ai_today_btn)
        self.ai_enabled_cb = QCheckBox("AI判定ON")
        self.ai_enabled_cb.setToolTip(
            "オフにすると Keepa／Gemini の自動判定と「再度判定」を止めます。\n"
            "料金を抑えたいときや、しばらく使わないときにOFF。\n"
            "ONに戻すと、準備中の商品は定時タスク／手動消化で再開します。"
        )
        self.ai_enabled_cb.toggled.connect(self._on_ai_enabled_toggled)
        check_row.addWidget(self.ai_enabled_cb)
        check_row.addStretch()
        left_layout.addLayout(check_row)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["選", "状態", "日時", "商品名", "仕入", "販売予定", "粗利", "ルール", "TP0"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        left_layout.addWidget(self.table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.detail_title = QLabel("（行を選んでください）")
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        right_layout.addWidget(self.detail_title)

        self.detail_meta = QLabel("")
        self.detail_meta.setWordWrap(True)
        self.detail_meta.setStyleSheet("color: #9aa8c0;")
        right_layout.addWidget(self.detail_meta)

        plan_row = QHBoxLayout()
        plan_row.addWidget(QLabel("3-6-9"))
        self.rule_combo = QComboBox()
        self.rule_combo.addItem("3ルール", "3")
        self.rule_combo.addItem("6ルール", "6")
        self.rule_combo.addItem("9ルール", "9")
        self.rule_combo.setCurrentIndex(1)
        self.rule_combo.currentIndexChanged.connect(self._on_editors_changed)
        plan_row.addWidget(self.rule_combo)
        plan_row.addStretch()
        right_layout.addLayout(plan_row)

        tp_row = QHBoxLayout()
        self.tp0_spin = QSpinBox()
        self.tp1_spin = QSpinBox()
        self.tp2_spin = QSpinBox()
        self.tp3_spin = QSpinBox()
        for label, spin in (
            ("TP0", self.tp0_spin),
            ("TP1", self.tp1_spin),
            ("TP2", self.tp2_spin),
            ("TP3", self.tp3_spin),
        ):
            spin.setRange(0, 9_999_999)
            spin.setSingleStep(100)
            spin.setSuffix(" 円")
            spin.valueChanged.connect(self._on_editors_changed)
            tp_row.addWidget(QLabel(label))
            tp_row.addWidget(spin)
        right_layout.addLayout(tp_row)

        self.ai_label = QLabel("AI提案: （Keepa取得後に定時／手動消化で用意）")
        self.ai_label.setWordWrap(True)
        self.ai_label.setStyleSheet("color: #a5b4c8; font-size: 11px;")
        right_layout.addWidget(self.ai_label)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #fca5a5; font-size: 11px;")
        self.error_label.hide()
        right_layout.addWidget(self.error_label)

        ai_btn_row = QHBoxLayout()
        self.apply_ai_btn = QPushButton("提案を反映")
        self.apply_ai_btn.setToolTip(
            "台帳に保存済みの AI提案（ルール／TP0〜TP3）を上の入力欄に入れます（まだ送信しません）"
        )
        self.apply_ai_btn.clicked.connect(self._apply_ai_suggestion)
        self.apply_ai_btn.setEnabled(False)
        ai_btn_row.addWidget(self.apply_ai_btn)
        self.rejudge_btn = QPushButton("再度判定")
        self.rejudge_btn.setToolTip(
            "この1件だけ Keepa 再取得→AI判定し直します。失敗時や見直したいときに使います。"
        )
        self.rejudge_btn.clicked.connect(self._rejudge_current)
        self.rejudge_btn.setEnabled(False)
        ai_btn_row.addWidget(self.rejudge_btn)
        ai_btn_row.addStretch()
        right_layout.addLayout(ai_btn_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.thumbs_host = QWidget()
        self.thumbs_layout = QHBoxLayout(self.thumbs_host)
        self.thumbs_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.thumbs_host)
        scroll.setMinimumHeight(140)
        right_layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        self.open_url_btn = QPushButton("商品ページを開く")
        self.open_url_btn.clicked.connect(self._open_url)
        self.open_url_btn.setEnabled(False)
        btn_row.addWidget(self.open_url_btn)

        self.delete_btn = QPushButton("この購入を削除")
        self.delete_btn.setToolTip("間違えて購入登録したものなどを台帳から削除します（画像フォルダも削除）")
        self.delete_btn.setStyleSheet(
            "QPushButton { background-color: #7f1d1d; color: white; font-weight: bold; "
            "padding: 8px 12px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #991b1b; }"
            "QPushButton:disabled { background-color: #555; color: #aaa; }"
        )
        self.delete_btn.clicked.connect(self._delete_current)
        self.delete_btn.setEnabled(False)
        btn_row.addWidget(self.delete_btn)

        self.send_btn = QPushButton("チェックした商品を仕入一覧に送る")
        self.send_btn.setToolTip(
            "チェックした購入済み候補を、ネット仕入一覧のうしろへまとめて足します。"
        )
        self.send_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; "
            "padding: 8px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1b5e20; }"
            "QPushButton:disabled { background-color: #555; color: #aaa; }"
        )
        self.send_btn.clicked.connect(self._send_checked)
        self.send_btn.setEnabled(False)
        btn_row.addWidget(self.send_btn)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)
        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([620, 480])

        bottom = QHBoxLayout()
        self.refresh_btn = QPushButton("再読込")
        self.refresh_btn.clicked.connect(self.reload)
        bottom.addWidget(self.refresh_btn)
        self.ai_status = QLabel("")
        self.ai_status.setStyleSheet("color: #94a3b8;")
        bottom.addWidget(self.ai_status, 1)
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self._sync_ai_enabled_ui()
        self.reload()

    def _sync_ai_enabled_ui(self) -> None:
        """チェックボックスと消化／再判定ボタンを AI ON/OFF に合わせる。"""
        try:
            enabled = _ai_plan_enabled()
            env_lock = _ai_plan_env_overrides()
        except Exception as exc:  # noqa: BLE001
            self.ai_status.setText(f"AI設定の読込失敗: {exc}")
            return
        self.ai_enabled_cb.blockSignals(True)
        try:
            self.ai_enabled_cb.setChecked(enabled)
            self.ai_enabled_cb.setEnabled(not env_lock)
            if env_lock:
                self.ai_enabled_cb.setToolTip(
                    "環境変数 PURCHASE_AI_PLAN_ENABLED で固定されています。\n"
                    "画面からは変更できません（.env を編集してください）。"
                )
            else:
                self.ai_enabled_cb.setToolTip(
                    "オフにすると Keepa／Gemini の自動判定と「再度判定」を止めます。\n"
                    "料金を抑えたいときや、しばらく使わないときにOFF。\n"
                    "ONに戻すと、準備中の商品は定時タスク／手動消化で再開します。"
                )
        finally:
            self.ai_enabled_cb.blockSignals(False)
        busy = self._ai_worker is not None and self._ai_worker.isRunning()
        self.ai_today_btn.setEnabled(bool(enabled) and not busy)
        # 再判定は行選択時に別途有効化。ここではOFFなら必ず無効
        if not enabled:
            self.rejudge_btn.setEnabled(False)
        if not enabled:
            self.ai_status.setText("AI判定OFF（自動・手動とも停止）")
        elif env_lock:
            self.ai_status.setText("AI判定ON（環境変数で固定）")

    def _on_ai_enabled_toggled(self, checked: bool) -> None:
        try:
            info = _set_ai_plan_enabled(bool(checked))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "スタンバイ", f"AI判定の設定保存に失敗しました:\n{exc}")
            self._sync_ai_enabled_ui()
            return
        if info.get("env_overrides"):
            QMessageBox.information(
                self,
                "スタンバイ",
                "設定ファイルは更新しましたが、環境変数 PURCHASE_AI_PLAN_ENABLED が優先されます。\n"
                "画面のON/OFFを効かせるには .env からその行を削除してください。",
            )
        self._sync_ai_enabled_ui()
        self._plans.clear()
        self.reload()
        if checked:
            self.ai_status.setText("AI判定ON → 準備中は定時／手動消化で判定します")
        else:
            self.ai_status.setText("AI判定OFF → Keepa／Gemini を止めました")

    def _token_of(self, item: Dict[str, Any]) -> str:
        return str(item.get("token") or "").strip()

    def _pick_tp(self, item: Dict[str, Any], *keys: str, default: int = 0) -> int:
        for key in keys:
            raw = item.get(key)
            try:
                n = int(raw) if raw is not None else 0
            except (TypeError, ValueError):
                continue
            if n > 0:
                return n
        return max(int(default or 0), 0)

    def _plan_from_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """台帳の AI 結果があれば初期値にする。"""
        sell = item.get("sell_yen")
        try:
            default_tp0 = int(sell) if sell is not None else 0
        except (TypeError, ValueError):
            default_tp0 = 0
        rule = normalize_rule369(item.get("ai_rule369") or "6")
        tp0_n = self._pick_tp(item, "ai_tp0_yen", "tp0", "TP0", default=default_tp0)
        if tp0_n <= 0:
            tp0_n = default_tp0
        tp1_n = self._pick_tp(item, "ai_tp1_yen", "tp1", "TP1", default=int(tp0_n * 0.85) if tp0_n else 0)
        tp2_n = self._pick_tp(item, "ai_tp2_yen", "tp2", "TP2", default=int(tp0_n * 0.70) if tp0_n else 0)
        tp3_n = self._pick_tp(item, "ai_tp3_yen", "tp3", "TP3", default=int(tp0_n * 0.55) if tp0_n else 0)
        ai: Optional[StandbyAiPlan] = None
        status = str(item.get("ai_plan_status") or "").lower()
        has_plan = bool(item.get("ai_rule369") and item.get("ai_tp0_yen"))
        if status in ("done", "error") or has_plan:
            ai = StandbyAiPlan(
                token=self._token_of(item),
                asin=str(item.get("asin") or ""),
                title=str(item.get("title") or ""),
                buy_yen=item.get("buy_yen") if isinstance(item.get("buy_yen"), int) else None,
                sell_yen=item.get("sell_yen") if isinstance(item.get("sell_yen"), int) else None,
                rule369=rule,
                tp0_yen=tp0_n if tp0_n > 0 else max(default_tp0, 1),
                tp1_yen=tp1_n,
                tp2_yen=tp2_n,
                tp3_yen=tp3_n,
                reason=str(item.get("ai_reason") or "台帳のAI提案"),
                source=str(item.get("ai_source") or "ledger"),
                keepa_notes=str(item.get("keepa_notes") or ""),
                ai_error=str(item.get("ai_error") or ""),
                at=str(item.get("at") or ""),
            )
        return {
            "rule369": rule,
            "tp0": tp0_n if tp0_n > 0 else 0,
            "tp1": tp1_n if tp1_n > 0 else 0,
            "tp2": tp2_n if tp2_n > 0 else 0,
            "tp3": tp3_n if tp3_n > 0 else 0,
            "ai": ai,
        }

    def _ensure_plan(self, item: Dict[str, Any]) -> Dict[str, Any]:
        token = self._token_of(item)
        if token not in self._plans:
            self._plans[token] = self._plan_from_item(item)
        return self._plans[token]

    def reload(self) -> None:
        try:
            self._items = load_standby_items(include_pending=False)
        except Exception as exc:  # noqa: BLE001
            self._items = []
            QMessageBox.warning(self, "スタンバイ", f"読込に失敗しました:\n{exc}")
        # 台帳の Keepa／AI 結果を優先して作り直す
        self._plans = {}
        for it in self._items:
            self._ensure_plan(it)
        self._fill_table()

    def _fill_table(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._items))
            for row, item in enumerate(self._items):
                status = _status_label(item)
                plan = self._ensure_plan(item)
                imported = bool(item.get("imported"))

                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                if imported:
                    check.setFlags(Qt.ItemFlag.ItemIsSelectable)
                    check.setCheckState(Qt.CheckState.Unchecked)
                else:
                    check.setCheckState(Qt.CheckState.Unchecked)
                check.setData(Qt.ItemDataRole.UserRole, row)
                check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, _COL_CHECK, check)

                values = [
                    status,
                    str(item.get("at") or "")[:19],
                    (str(item.get("title") or ""))[:60],
                    f"{int(item['buy_yen']):,}円"
                    if isinstance(item.get("buy_yen"), int)
                    else "-",
                    f"{int(item['sell_yen']):,}円"
                    if isinstance(item.get("sell_yen"), int)
                    else "-",
                    f"{int(item['profit_yen']):,}円"
                    if isinstance(item.get("profit_yen"), int)
                    else "-",
                    str(plan.get("rule369") or "6"),
                    f"{int(plan['tp0']):,}" if int(plan.get("tp0") or 0) > 0 else "-",
                ]
                for col, text in enumerate(values, start=1):
                    cell = QTableWidgetItem(text)
                    cell.setData(Qt.ItemDataRole.UserRole, row)
                    self.table.setItem(row, col, cell)
            self.table.resizeColumnsToContents()
            self.table.setColumnWidth(_COL_CHECK, 42)
            if self._items:
                self.table.selectRow(0)
        finally:
            self.table.blockSignals(False)

        if self._items:
            self._show_item(0)
        else:
            self._clear_detail()
        self._update_send_btn()

    def _refresh_row_plan_cells(self, row: int) -> None:
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        plan = self._ensure_plan(item)
        rule_cell = self.table.item(row, _COL_RULE)
        tp_cell = self.table.item(row, _COL_TP0)
        if rule_cell is not None:
            rule_cell.setText(str(plan.get("rule369") or "6"))
        if tp_cell is not None:
            tp0 = int(plan.get("tp0") or 0)
            tp_cell.setText(f"{tp0:,}" if tp0 > 0 else "-")

    def _clear_detail(self) -> None:
        self._current = None
        self._current_idx = -1
        self.detail_title.setText("（行を選んでください）")
        self.detail_meta.setText("")
        self.open_url_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.apply_ai_btn.setEnabled(False)
        self.ai_label.setText("AI提案: （今日分をAI提案で取得）")
        self._updating_editors = True
        try:
            self.rule_combo.setCurrentIndex(1)
            self.tp0_spin.setValue(0)
        finally:
            self._updating_editors = False
        self._set_thumbs([])

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item is not None and item.column() == _COL_CHECK:
            self._update_send_btn()

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column == _COL_CHECK:
            cell = self.table.item(row, _COL_CHECK)
            if cell is not None and (cell.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                self.table.blockSignals(True)
                try:
                    if cell.checkState() == Qt.CheckState.Checked:
                        cell.setCheckState(Qt.CheckState.Unchecked)
                    else:
                        cell.setCheckState(Qt.CheckState.Checked)
                finally:
                    self.table.blockSignals(False)
                self._update_send_btn()
        self._show_item(row)

    def _on_select(self) -> None:
        idx = self.table.currentRow()
        if idx < 0:
            model = self.table.selectionModel()
            rows = model.selectedRows() if model is not None else []
            if not rows:
                self._clear_detail()
                return
            idx = rows[0].row()
        self._show_item(idx)

    def _show_item(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._items):
            self._clear_detail()
            return
        item = self._items[idx]
        self._current = item
        self._current_idx = idx
        plan = self._ensure_plan(item)
        self.detail_title.setText(str(item.get("title") or "(無題)"))
        buy = item.get("buy_yen")
        sell = item.get("sell_yen")
        profit = item.get("profit_yen")
        margin = item.get("margin_rate")
        margin_txt = (
            f"{float(margin) * 100:.1f}%" if isinstance(margin, (int, float)) else "-"
        )
        status_txt = _status_label(item)
        if item.get("imported"):
            status = f"ネット仕入へ送済（{status_txt}）"
        else:
            status = f"購入済・未送信（{status_txt}）"
        buy_txt = f"{buy:,}円" if isinstance(buy, int) else "-"
        sell_txt = f"{sell:,}円" if isinstance(sell, int) else "-"
        profit_txt = f"{profit:,}円（{margin_txt}）" if isinstance(profit, int) else "-"
        memo = str(item.get("memo") or "").strip()
        memo_line = f"\nメモ: {memo}" if memo else ""
        self.detail_meta.setText(
            f"状態: {status}\n"
            f"ASIN: {item.get('asin') or '-'}　KW: {item.get('keyword') or '-'}\n"
            f"仕入: {buy_txt}　販売予定: {sell_txt}　粗利: {profit_txt}\n"
            f"{item.get('fee_note') or ''}"
            f"{memo_line}"
        )
        self.open_url_btn.setEnabled(bool(str(item.get("url") or "").strip()))
        self.delete_btn.setEnabled(bool(self._token_of(item)))
        try:
            ai_on = _ai_plan_enabled()
        except Exception:  # noqa: BLE001
            ai_on = True
        self.rejudge_btn.setEnabled(
            bool(ai_on) and bool(self._token_of(item)) and not item.get("imported")
        )

        self._updating_editors = True
        try:
            rule = normalize_rule369(plan.get("rule369"))
            idx_map = {"3": 0, "6": 1, "9": 2}
            self.rule_combo.setCurrentIndex(idx_map.get(rule, 1))
            self.tp0_spin.setValue(int(plan.get("tp0") or 0))
            self.tp1_spin.setValue(int(plan.get("tp1") or 0))
            self.tp2_spin.setValue(int(plan.get("tp2") or 0))
            self.tp3_spin.setValue(int(plan.get("tp3") or 0))
        finally:
            self._updating_editors = False

        ai: Optional[StandbyAiPlan] = plan.get("ai")
        ai_st = str(item.get("ai_plan_status") or "").lower()
        err_txt = str(item.get("ai_error") or "").strip()
        if ai_st == "error" or err_txt:
            self.error_label.setText(f"失敗理由: {err_txt or (ai.ai_error if ai else '') or '不明'}")
            self.error_label.show()
        else:
            self.error_label.hide()
            self.error_label.setText("")

        if ai is not None and ai_st == "done":
            self.ai_label.setText(
                f"AI提案: ルール{ai.rule369} / "
                f"TP0 {ai.tp0_yen:,} / TP1 {ai.tp1_yen:,} / TP2 {ai.tp2_yen:,} / TP3 {ai.tp3_yen:,}円"
                f"（{ai.source}）\n{ai.reason}"
                + (f"\nKeepa: {ai.keepa_notes}" if ai.keepa_notes else "")
            )
            self.apply_ai_btn.setEnabled(True)
        elif ai is not None and ai_st == "error":
            self.ai_label.setText(
                "AI提案: 失敗しています。下の失敗理由を確認し、「再度判定」でやり直せます。\n"
                f"（仮値ルール{ai.rule369} TP0 {ai.tp0_yen:,}円は参考。判定済ではありません）"
            )
            self.apply_ai_btn.setEnabled(False)
        else:
            self.ai_label.setText(
                "AI提案: まだありません。"
                "届くまでの間に定時タスクが Keepa 本取得→判定します。"
                "急ぐときだけ「準備中を今すぐ消化」。"
            )
            self.apply_ai_btn.setEnabled(False)

        self._set_thumbs(list(item.get("image_files") or []))

    def _on_editors_changed(self, *_args) -> None:
        if self._updating_editors or not self._current:
            return
        plan = self._ensure_plan(self._current)
        plan["rule369"] = normalize_rule369(self.rule_combo.currentData())
        plan["tp0"] = int(self.tp0_spin.value())
        plan["tp1"] = int(self.tp1_spin.value())
        plan["tp2"] = int(self.tp2_spin.value())
        plan["tp3"] = int(self.tp3_spin.value())
        if self._current_idx >= 0:
            self._refresh_row_plan_cells(self._current_idx)

    def _apply_ai_suggestion(self) -> None:
        if not self._current:
            return
        plan = self._ensure_plan(self._current)
        ai: Optional[StandbyAiPlan] = plan.get("ai")
        if ai is None:
            return
        if str(self._current.get("ai_plan_status") or "").lower() == "error":
            QMessageBox.information(
                self,
                "スタンバイ",
                "失敗状態のため「提案を反映」は使えません。先に「再度判定」してください。",
            )
            return
        plan["rule369"] = normalize_rule369(ai.rule369)
        plan["tp0"] = int(ai.tp0_yen)
        plan["tp1"] = int(ai.tp1_yen or 0)
        plan["tp2"] = int(ai.tp2_yen or 0)
        plan["tp3"] = int(ai.tp3_yen or 0)
        self._updating_editors = True
        try:
            idx_map = {"3": 0, "6": 1, "9": 2}
            self.rule_combo.setCurrentIndex(idx_map.get(plan["rule369"], 1))
            self.tp0_spin.setValue(plan["tp0"])
            self.tp1_spin.setValue(plan["tp1"])
            self.tp2_spin.setValue(plan["tp2"])
            self.tp3_spin.setValue(plan["tp3"])
        finally:
            self._updating_editors = False
        if self._current_idx >= 0:
            self._refresh_row_plan_cells(self._current_idx)

    def _rejudge_current(self) -> None:
        if not self._current:
            return
        if not _ai_plan_enabled():
            QMessageBox.information(
                self,
                "スタンバイ",
                "AI判定がOFFです。上の「AI判定ON」にチェックを入れてから再度判定してください。",
            )
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            QMessageBox.information(self, "スタンバイ", "いま Keepa／AI 消化を実行中です。")
            return
        token = self._token_of(self._current)
        if not token:
            return
        title = (str(self._current.get("title") or "")[:40]) or "(無題)"
        ok = QMessageBox.question(
            self,
            "再度判定",
            f"この商品を Keepa＋AI で再判定しますか？\n\n{title}\nASIN: {self._current.get('asin') or '-'}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            status, _ = _reset_ai_plan(token)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "スタンバイ", f"再判定の準備に失敗しました:\n{exc}")
            return
        if status != "updated":
            QMessageBox.warning(self, "スタンバイ", f"再判定を開始できません（{status}）")
            return

        self.ai_today_btn.setEnabled(False)
        self.rejudge_btn.setEnabled(False)
        self.ai_status.setText(f"再度判定中… {token[:12]}")
        worker = _ProcessPendingWorker(token=token, parent=self)
        self._ai_worker = worker

        def on_ok(msg: str) -> None:
            self.ai_status.setText("再判定完了 → 再読込")
            self._plans.clear()
            self.reload()
            self._sync_ai_enabled_ui()
            QMessageBox.information(
                self,
                "スタンバイ",
                "再判定が終わりました。状態が「判定済」か「失敗」かを確認してください。\n\n"
                f"（ログ抜粋）\n{msg[-800:]}",
            )

        def on_fail(err: str) -> None:
            self.ai_status.setText("再判定失敗")
            self._plans.clear()
            self.reload()
            self._sync_ai_enabled_ui()
            QMessageBox.warning(self, "スタンバイ", f"再判定に失敗しました:\n{err}")

        worker.finished_ok.connect(on_ok)
        worker.failed.connect(on_fail)
        worker.start()

    def _checked_rows(self) -> List[int]:
        rows: List[int] = []
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, _COL_CHECK)
            if cell is None:
                continue
            if cell.checkState() == Qt.CheckState.Checked:
                rows.append(row)
        return rows

    def _update_send_btn(self) -> None:
        n = len(self._checked_rows())
        self.send_btn.setEnabled(n > 0)
        if n > 0:
            self.send_btn.setText(f"チェックした商品を仕入一覧に送る（{n}件）")
        else:
            self.send_btn.setText("チェックした商品を仕入一覧に送る")

    def _select_all_unsent(self) -> None:
        self.table.blockSignals(True)
        try:
            for row, item in enumerate(self._items):
                cell = self.table.item(row, _COL_CHECK)
                if cell is None:
                    continue
                if item.get("imported"):
                    cell.setCheckState(Qt.CheckState.Unchecked)
                    continue
                if cell.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    cell.setCheckState(Qt.CheckState.Checked)
        finally:
            self.table.blockSignals(False)
        self._update_send_btn()

    def _clear_checks(self) -> None:
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                cell = self.table.item(row, _COL_CHECK)
                if cell is not None:
                    cell.setCheckState(Qt.CheckState.Unchecked)
        finally:
            self.table.blockSignals(False)
        self._update_send_btn()

    def _set_thumbs(self, paths: List[Path]) -> None:
        while self.thumbs_layout.count():
            child = self.thumbs_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
        for path in paths[:5]:
            label = QLabel()
            label.setFixedSize(110, 110)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "background:#1a2438; border:1px solid #2a3650; border-radius:8px;"
            )
            pix = QPixmap(str(path))
            if not pix.isNull():
                label.setPixmap(
                    pix.scaled(
                        110,
                        110,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                label.setText("画像")
            self.thumbs_layout.addWidget(label)
        self.thumbs_layout.addStretch()

    def _open_url(self) -> None:
        if not self._current:
            return
        url = str(self._current.get("url") or "").strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _delete_current(self) -> None:
        if not self._current:
            return
        token = self._token_of(self._current)
        if not token:
            return
        title = (str(self._current.get("title") or "")[:50]) or "(無題)"
        ok = QMessageBox.question(
            self,
            "購入を削除",
            f"この購入を台帳から削除しますか？\n\n{title}\nASIN: {self._current.get('asin') or '-'}\n\n"
            "画像フォルダも削除します。取り消せません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            status, _deleted = _delete_purchase(token)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "スタンバイ", f"削除に失敗しました:\n{exc}")
            return
        if status != "deleted":
            QMessageBox.warning(self, "スタンバイ", f"削除できませんでした（{status}）")
            return
        self._plans.pop(token, None)
        QMessageBox.information(self, "スタンバイ", "削除しました。")
        self.reload()

    def _run_process_pending(self) -> None:
        if not _ai_plan_enabled():
            QMessageBox.information(
                self,
                "スタンバイ",
                "AI判定がOFFです。上の「AI判定ON」にチェックを入れると再開できます。",
            )
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            QMessageBox.information(self, "スタンバイ", "いま Keepa／AI 消化を実行中です。")
            return
        pending_n = sum(
            1
            for it in self._items
            if (not it.get("imported"))
            and _status_label(it) == "準備中"
            and it.get("asin")
        )
        if pending_n <= 0:
            QMessageBox.information(
                self,
                "スタンバイ",
                "準備中の購入がありません。\n"
                "失敗の再実行は行を選んで「再度判定」を使ってください。\n"
                "新しい仕入れは自動で pending になり、定時タスクが Keepa→AI します。",
            )
            return
        self.ai_today_btn.setEnabled(False)
        self.rejudge_btn.setEnabled(False)
        self.ai_status.setText(f"Keepa本取得＋AI消化中…（最大10件・準備中 {pending_n}）")
        worker = _ProcessPendingWorker(limit=10, parent=self)
        self._ai_worker = worker

        def on_ok(msg: str) -> None:
            self.ai_status.setText("消化完了 → 再読込")
            self._plans.clear()
            self.reload()
            self._sync_ai_enabled_ui()
            QMessageBox.information(
                self,
                "スタンバイ",
                "Keepa本取得とAI提案の消化が終わりました。\n"
                "「判定済」は提案を反映、「失敗」は理由を確認して再度判定できます。\n"
                "自動では仕入一覧へ送りません。\n\n"
                f"（ログ抜粋）\n{msg[-800:]}",
            )

        def on_fail(err: str) -> None:
            self.ai_status.setText("消化失敗")
            self._sync_ai_enabled_ui()
            QMessageBox.warning(self, "スタンバイ", f"消化に失敗しました:\n{err}")

        worker.finished_ok.connect(on_ok)
        worker.failed.connect(on_fail)
        worker.start()

    def _send_checked(self) -> None:
        rows = self._checked_rows()
        if not rows:
            QMessageBox.information(
                self, "スタンバイ", "送る商品にチェックを付けてください。"
            )
            return

        ok_count = 0
        skip: List[str] = []
        errors: List[str] = []
        for row in rows:
            if row < 0 or row >= len(self._items):
                continue
            item = self._items[row]
            title = (str(item.get("title") or "")[:40]) or "(無題)"
            if item.get("imported"):
                skip.append(f"{title}（送済）")
                continue
            asin = str(item.get("asin") or "").strip()
            if not asin:
                skip.append(f"{title}（ASINなし）")
                continue
            plan = self._ensure_plan(item)
            try:
                inv_row = purchase_to_inventory_row(
                    item,
                    rule369=str(plan.get("rule369") or "6"),
                    tp0=int(plan.get("tp0") or 0) or None,
                    tp1=int(plan.get("tp1") or 0) or None,
                    tp2=int(plan.get("tp2") or 0) or None,
                    tp3=int(plan.get("tp3") or 0) or None,
                )
                self._on_send_row(inv_row)
                mark_imported(str(item.get("token") or ""))
                item["imported"] = True
                ok_count += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{title}: {exc}")

        self._fill_table()

        parts = [f"{ok_count} 件をネット仕入一覧に送りました。"]
        if skip:
            parts.append("スキップ: " + " / ".join(skip[:8]))
            if len(skip) > 8:
                parts.append(f"ほか {len(skip) - 8} 件")
        if errors:
            parts.append("失敗: " + " / ".join(errors[:5]))
        if ok_count > 0 and not errors:
            QMessageBox.information(self, "スタンバイ", "\n".join(parts))
        elif ok_count > 0:
            QMessageBox.warning(self, "スタンバイ", "\n".join(parts))
        else:
            QMessageBox.warning(
                self,
                "スタンバイ",
                "送れる商品がありませんでした。\n" + "\n".join(parts[1:]),
            )
