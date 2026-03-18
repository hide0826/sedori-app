#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入DB行編集ダイアログ

商品情報と TP1/TP2 価格を編集するコンパクトなダイアログ。
Keepa はブラウザで開き、このウィンドウは前面に保ったまま TA を入力できる。
"""

from __future__ import annotations

import re
import sys
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
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
    ):
        # parent=None で作成し、メイン画面を前面に出さない（編集時もブラウザが隠れないようにする）
        super().__init__(None)
        self.record = record
        self._product_widget = product_widget if product_widget is not None else parent
        self.setWindowTitle("仕入行の編集（Keepa）")
        self.setMinimumSize(380, 280)
        self.setMaximumSize(420, 420)
        self._positioned_at_topleft = False
        self._setup_ui()

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
        info_layout.addRow("SKU:", QLabel(self._record_str("SKU") or "-"))
        sale_price = _parse_number(self.record.get("販売予定価格") or self.record.get("expected_price"))
        self._sale_price_value = sale_price
        purchase_price = _parse_number(self.record.get("仕入れ価格") or self.record.get("purchase_price") or self.record.get("仕入価格"))
        self._purchase_price_value = purchase_price
        info_layout.addRow("販売予定価格:", QLabel(_format_price(sale_price)))
        profit = _parse_number(self.record.get("見込み利益") or self.record.get("expected_profit"))
        self._current_profit_value = profit  # 今出てる見込み利益（値下げ時の概算の基準）
        base_rate = (profit / sale_price * 100.0) if sale_price > 0 and profit != 0 else 0.0
        profit_text = _format_price(profit)
        if base_rate:
            profit_text = f"{profit_text}（{base_rate:.1f}%）"
        info_layout.addRow("見込み利益（利益率）:", QLabel(profit_text))
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # --- Keepaを開くボタン ---
        open_keepa_btn = QPushButton("Keepa をブラウザで開く")
        open_keepa_btn.setToolTip("Keepa を開きます。Windows では約2秒後にブラウザを前面に出し、画面の右半分にリサイズします（編集ダイアログは左上に表示）。")
        open_keepa_btn.clicked.connect(self._open_keepa_in_browser)
        layout.addWidget(open_keepa_btn)

        # --- TP1 / TP2 編集 ---
        ta_group = QGroupBox("TP 価格（Keepa で確認しながら入力）")
        ta_layout = QFormLayout()
        self._ta1_edit = QLineEdit()
        self._ta1_edit.setPlaceholderText("例: 6200")
        self._ta1_edit.setText(self._record_str("TP1") or self._record_str("tp1") or self._record_str("TA1") or self._record_str("ta1") or "")
        self._ta1_edit.textChanged.connect(self._update_ta_labels)
        ta_layout.addRow("TP1 価格:", self._ta1_edit)
        self._ta1_profit_label = QLabel("-")
        ta_layout.addRow("TP1 概算利益（利益率）:", self._ta1_profit_label)
        self._ta1_rate_edit = QLineEdit()
        self._ta1_rate_edit.setPlaceholderText("例: 20（%）")
        self._ta1_rate_edit.textChanged.connect(lambda _text: self._on_ta_rate_changed(1))
        ta_layout.addRow("TP1 目標利益率(%):", self._ta1_rate_edit)
        self._ta2_edit = QLineEdit()
        self._ta2_edit.setPlaceholderText("例: 5800")
        self._ta2_edit.setText(self._record_str("TP2") or self._record_str("tp2") or self._record_str("TA2") or self._record_str("ta2") or "")
        self._ta2_edit.textChanged.connect(self._update_ta_labels)
        ta_layout.addRow("TP2 価格:", self._ta2_edit)
        self._ta2_profit_label = QLabel("-")
        ta_layout.addRow("TP2 概算利益（利益率）:", self._ta2_profit_label)
        self._ta2_rate_edit = QLineEdit()
        self._ta2_rate_edit.setPlaceholderText("例: 25（%）")
        self._ta2_rate_edit.textChanged.connect(lambda _text: self._on_ta_rate_changed(2))
        ta_layout.addRow("TP2 目標利益率(%):", self._ta2_rate_edit)
        ta_group.setLayout(ta_layout)
        layout.addWidget(ta_group)
        self._update_ta_labels()

        # --- ボタン（反映後もダイアログは開いたまま＝ブラウザを参照し続けられる）---
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        self._apply_btn = QPushButton("仕入DBに反映")
        self._apply_btn.setDefault(True)
        self._apply_btn.setToolTip("保存します。ダイアログは開いたままなので、ブラウザを見ながら続けて入力できます。")
        self._apply_btn.clicked.connect(self._apply)
        buttons.addButton(self._apply_btn, QDialogButtonBox.ActionRole)
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        buttons.addButton(close_btn, QDialogButtonBox.AcceptRole)
        layout.addWidget(buttons)

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

    def _record_str(self, key: str) -> str:
        v = self.record.get(key)
        if v is None:
            return ""
        return str(v).strip()

    def _update_ta_labels(self) -> None:
        # 概算利益 = 今出てる見込み利益 - (値下げ幅 × 0.89)、その横に想定利益率 = 概算利益/TA価格×100
        current_profit = self._current_profit_value
        sale = self._sale_price_value
        ta1 = _parse_number(self._ta1_edit.text())
        ta2 = _parse_number(self._ta2_edit.text())

        def _ta_profit_and_rate(ta_price: float) -> tuple:
            if not ta_price or sale <= 0:
                return None, None
            drop = max(0.0, sale - ta_price)  # 値下げ幅（TAが販売予定より高い場合は0）
            profit = current_profit - (drop * 0.89)
            rate = (profit / ta_price * 100) if ta_price else None
            return profit, rate

        p1, r1 = _ta_profit_and_rate(ta1)
        p2, r2 = _ta_profit_and_rate(ta2)
        self._ta1_profit_label.setText(
            f"{_format_price(p1)}（{r1:.1f}%）" if p1 is not None and r1 is not None else "-"
        )
        self._ta2_profit_label.setText(
            f"{_format_price(p2)}（{r2:.1f}%）" if p2 is not None and r2 is not None else "-"
        )

    def _on_ta_rate_changed(self, which: int) -> None:
        """TA目標利益率(%)から逆算して TA 価格を自動入力する"""
        sale = self._sale_price_value
        current_profit = self._current_profit_value
        if sale <= 0:
            return

        if which == 1:
            edit = self._ta1_rate_edit
            target_edit = self._ta1_edit
        else:
            edit = self._ta2_rate_edit
            target_edit = self._ta2_edit

        rate_percent = _parse_number(edit.text())
        if rate_percent <= 0:
            return

        r = rate_percent / 100.0  # 利益率(小数)
        # 概算利益 = current_profit - 0.89*(sale - ta)
        # 想定利益率 r = 概算利益 / ta
        # => (current_profit - 0.89*sale + 0.89*ta) = r * ta
        # => (r - 0.89) * ta = current_profit - 0.89*sale
        denom = r - 0.89
        if abs(denom) < 1e-6:
            return
        ta_price = (current_profit - 0.89 * sale) / denom
        if ta_price <= 0:
            return
        target_edit.setText(str(int(ta_price)))

    def _apply(self) -> None:
        """仕入DBに反映する（ダイアログは閉じない＝ブラウザを見たまま続けられる）"""
        tp1 = self._ta1_edit.text().strip()
        tp2 = self._ta2_edit.text().strip()
        self.record["TP1"] = tp1
        self.record["tp1"] = tp1
        self.record["TP2"] = tp2
        self.record["tp2"] = tp2
        # 親が ProductWidget なら hirio.db とスナップショットにも保存
        if self._product_widget and hasattr(self._product_widget, "purchase_history_db"):
            sku = self._record_str("SKU") or self._record_str("sku")
            if sku:
                try:
                    status = self.record.get("ステータス") or self.record.get("status") or "ready"
                    reason = self.record.get("ステータス理由") or self.record.get("status_reason") or ""
                    self._product_widget.purchase_history_db.upsert({
                        "sku": sku,
                        "status": status,
                        "status_reason": reason,
                        "tp1": tp1,
                        "tp2": tp2,
                    })
                except Exception as e:
                    QMessageBox.warning(self, "反映", f"DB 保存でエラー: {e}")
                    return
        if self._product_widget and hasattr(self._product_widget, "save_purchase_snapshot"):
            try:
                self._product_widget.save_purchase_snapshot()
            except Exception:
                pass
        if self._product_widget and hasattr(self._product_widget, "populate_purchase_table"):
            records = getattr(self._product_widget, "purchase_records", None) or getattr(self._product_widget, "purchase_all_records", [])
            if records:
                self._product_widget.populate_purchase_table(records)
        QMessageBox.information(self, "反映", "TP1/TP2 を仕入DBに反映しました。\nダイアログは開いたままです。閉じる場合は「閉じる」を押してください。")

    def accept(self) -> None:
        """閉じる時に Keepa ブラウザも最小化する（閉じた後に遅延実行）"""
        super().accept()
        QTimer.singleShot(250, _minimize_keepa_browser_win)

    def reject(self) -> None:
        """キャンセル時も Keepa ブラウザを最小化する（閉じた後に遅延実行）"""
        super().reject()
        QTimer.singleShot(250, _minimize_keepa_browser_win)
