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
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
    QVBoxLayout,
    QWidget,
)

# ダークUI向け：TP0〜TP3 でラベル・入力・概算の色を分ける
_TP_DIALOG_TIER_COLORS = ("#6ecff6", "#7ae495", "#f0c674", "#e8a0bf")


def _style_tp_tier_text(color: str, *widgets: QWidget) -> None:
    for w in widgets:
        w.setStyleSheet(f"color: {color};")

try:
    from desktop.services.purchase_tp_autofill_369 import (
        ta_price_from_target_margin_percent,
        break_even_price_int_for_record,
    )
except ImportError:
    from services.purchase_tp_autofill_369 import (  # type: ignore
        ta_price_from_target_margin_percent,
        break_even_price_int_for_record,
    )

try:
    from desktop.services.keepa_service import KeepaService
    from desktop.ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog
except ImportError:
    from services.keepa_service import KeepaService  # type: ignore
    from ui.keepa_offer_detail_dialog import KeepaOfferDetailDialog  # type: ignore


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
        self._tp_field_sync_guard = False
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
        self._condition_label = QLabel(self._record_condition_label_text())
        self._condition_label.setWordWrap(True)
        self._condition_label.setMaximumWidth(340)
        info_layout.addRow("コンディション:", self._condition_label)
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
        layout.addLayout(keepa_btn_row)

        # --- TP0 / TP1 / TP2 / TP3 編集（各帯：価格 → 目標利益率 → 概算利益、色分け）---
        ta_group = QGroupBox("TP 価格（Keepa で確認しながら入力）")
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
            ta_layout.addRow(lbl_price, edit)
            ta_layout.addRow(lbl_rate, rate_spin)
            ta_layout.addRow(lbl_profit, profit_lbl)

            setattr(self, f"_ta{tier}_edit", edit)
            setattr(self, f"_ta{tier}_rate_spin", rate_spin)
            setattr(self, f"_ta{tier}_profit_label", profit_lbl)

        _add_tp_block(0, ("TP0", "tp0", "TA0", "ta0"), "例: 6400")
        _add_tp_block(1, ("TP1", "tp1", "TA1", "ta1"), "例: 6200")
        _add_tp_block(2, ("TP2", "tp2", "TA2", "ta2"), "例: 5800")
        _add_tp_block(3, ("TP3", "tp3", "TA3", "ta3"), "例: 5600")

        ta_group.setLayout(ta_layout)
        layout.addWidget(ta_group)
        self._update_ta_labels()
        for tr in range(4):
            self._sync_rate_spin_from_price(tr)

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

    def _ta_price_edit(self, which: int) -> QLineEdit:
        return (self._ta0_edit, self._ta1_edit, self._ta2_edit, self._ta3_edit)[which]

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

    def _apply(self) -> None:
        """仕入DBに反映する（ダイアログは閉じない＝ブラウザを見たまま続けられる）"""
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
                        "tp0": tp0,
                        "tp1": tp1,
                        "tp2": tp2,
                        "tp3": tp3,
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
        QMessageBox.information(self, "反映", "TP0/TP1/TP2/TP3 を仕入DBに反映しました。\nダイアログは開いたままです。閉じる場合は「閉じる」を押してください。")

    def accept(self) -> None:
        """閉じる時に Keepa ブラウザも最小化する（閉じた後に遅延実行）"""
        super().accept()
        QTimer.singleShot(250, _minimize_keepa_browser_win)

    def reject(self) -> None:
        """キャンセル時も Keepa ブラウザを最小化する（閉じた後に遅延実行）"""
        super().reject()
        QTimer.singleShot(250, _minimize_keepa_browser_win)
