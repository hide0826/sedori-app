#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入行編集用のフリマ証憑パネル（3枚貼付・OCR・日時確認）。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.flea_market_evidence_ocr import (
    FleaTransactionOcrResult,
    parse_transaction_ocr_text,
    pick_transaction_text,
)
from services.flea_market_evidence_service import EVIDENCE_SLOT_SPECS
from services.ocr_service import OCRService


class _SlotWidget(QWidget):
    """1枚分のサムネ・貼り付け・ファイル追加。"""

    selected = Signal(int)

    def __init__(self, index: int, title: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.title = title
        self.image: Optional[QImage] = None
        self.source_path: str = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.caption = QLabel(title)
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)
        self.thumb = QLabel("未設定")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setMinimumSize(160, 110)
        self.thumb.setStyleSheet(
            "QLabel { background:#2b2b2b; border:1px solid #555; color:#aaa; }"
        )
        self.thumb.setScaledContents(False)
        self.thumb.setToolTip("ダブルクリックで拡大します")
        self.thumb.installEventFilter(self)
        layout.addWidget(self.thumb)
        btn_row = QHBoxLayout()
        paste_btn = QPushButton("貼り付け")
        paste_btn.setToolTip("クリップボードの画像をこの枠に貼ります（Win+Shift+S のあと）")
        paste_btn.clicked.connect(self._paste_here)
        file_btn = QPushButton("ファイル")
        file_btn.clicked.connect(self._choose_file)
        clear_btn = QPushButton("削除")
        clear_btn.clicked.connect(self.clear)
        btn_row.addWidget(paste_btn)
        btn_row.addWidget(file_btn)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

    def eventFilter(self, watched, event):
        if watched is self.thumb and event.type() == QEvent.Type.MouseButtonDblClick:
            self._open_large()
            return True
        return super().eventFilter(watched, event)

    def _open_large(self) -> None:
        if self.image is None or self.image.isNull():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.title)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap.fromImage(self.image)
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            pixmap = pixmap.scaled(
                int(area.width() * 0.9),
                int(area.height() * 0.9),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        label.setPixmap(pixmap)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label)
        dialog.resize(pixmap.width() + 24, pixmap.height() + 24)
        dialog.exec()

    def mousePressEvent(self, event):
        self.selected.emit(self.index)
        super().mousePressEvent(event)

    def set_selected_style(self, on: bool) -> None:
        border = "#5aa2ff" if on else "#555"
        self.thumb.setStyleSheet(
            f"QLabel {{ background:#2b2b2b; border:2px solid {border}; color:#aaa; }}"
        )

    def set_image(self, image: QImage, source_path: str = "") -> None:
        if image is None or image.isNull():
            return
        self.image = QImage(image)
        self.source_path = source_path
        pix = QPixmap.fromImage(self.image)
        scaled = pix.scaled(160, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb.setPixmap(scaled)
        self.thumb.setText("")

    def load_path(self, path: str) -> None:
        p = (path or "").strip()
        if not p or not Path(p).is_file():
            return
        img = QImage(p)
        if img.isNull():
            return
        self.set_image(img, p)

    def clear(self) -> None:
        self.image = None
        self.source_path = ""
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText("未設定")

    def _paste_here(self) -> None:
        panel = self.parent()
        while panel is not None and not isinstance(panel, FleaEvidencePanel):
            panel = panel.parent()
        if isinstance(panel, FleaEvidencePanel):
            panel.paste_clipboard_into(self.index)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"{self.title}を選択",
            "",
            "画像ファイル (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if path:
            self.load_path(path)


class FleaEvidencePanel(QGroupBox):
    """商品ページ2枚＋取引画面1枚の貼付と OCR 提案。"""

    ocr_finished = Signal(object)

    def __init__(self, current_purchase_datetime: str, parent=None):
        super().__init__("フリマ仕入証憑（商品ページ2枚＋取引画面）", parent)
        self._current_datetime = (current_purchase_datetime or "").strip()
        self._ocr_result = FleaTransactionOcrResult()
        self._selected_index = 0
        self._ocr_service: Optional[OCRService] = None
        self._temp_files: List[str] = []

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Win+Shift+S でスクショしたあと、この画面で Ctrl+V するか「貼り付け」を押します。\n"
            "取引画面をOCRすると、購入日時・商品ID・出品者を下に提案します。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        slots_row = QHBoxLayout()
        self.slots: List[_SlotWidget] = []
        for i, spec in enumerate(EVIDENCE_SLOT_SPECS):
            slot = _SlotWidget(i, spec[2], self)
            slot.selected.connect(self._on_slot_selected)
            self.slots.append(slot)
            slots_row.addWidget(slot)
        layout.addLayout(slots_row)

        btn_row = QHBoxLayout()
        self.ocr_btn = QPushButton("取引画面をOCRして入力")
        self.ocr_btn.clicked.connect(self.run_ocr)
        btn_row.addWidget(self.ocr_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.status_label = QLabel("OCR未実行")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.datetime_check = QCheckBox("メルカリの購入日時に直す")
        self.datetime_check.setChecked(False)
        self.datetime_check.setEnabled(False)
        layout.addWidget(self.datetime_check)

        self.price_hint = QLabel("")
        self.price_hint.setWordWrap(True)
        self.price_hint.setStyleSheet("color:#adb5bd;")
        layout.addWidget(self.price_hint)

        self._on_slot_selected(0)

    def load_existing_row(self, row_data: dict) -> None:
        from services.flea_market_evidence_service import EVIDENCE_IMAGE_COLS

        for i, col in enumerate(EVIDENCE_IMAGE_COLS):
            path = str(row_data.get(col) or "").strip()
            if path:
                self.slots[i].load_path(path)

    def has_any_image(self) -> bool:
        return any(s.image is not None and not s.image.isNull() for s in self.slots)

    def ocr_result(self) -> FleaTransactionOcrResult:
        return self._ocr_result

    def should_apply_datetime(self) -> bool:
        return bool(self.datetime_check.isChecked() and self._ocr_result.purchase_datetime)

    def paste_clipboard_into(self, index: int) -> bool:
        clip = QApplication.clipboard()
        img = clip.image() if clip else QImage()
        if img is None or img.isNull():
            return False
        if 0 <= index < len(self.slots):
            self.slots[index].set_image(img)
            self._on_slot_selected(index)
            return True
        return False

    def paste_clipboard_to_next(self) -> bool:
        clip = QApplication.clipboard()
        img = clip.image() if clip else QImage()
        if img is None or img.isNull():
            return False
        target = self._selected_index
        if self.slots[target].image is not None:
            for i, slot in enumerate(self.slots):
                if slot.image is None:
                    target = i
                    break
        return self.paste_clipboard_into(target)

    def export_slot_temp_paths(self) -> List[Optional[str]]:
        """保存処理用に、各スロットのファイルパスを返す。"""
        paths: List[Optional[str]] = []
        for slot in self.slots:
            if slot.image is None or slot.image.isNull():
                paths.append(None)
                continue
            if slot.source_path and Path(slot.source_path).is_file():
                paths.append(slot.source_path)
                continue
            fd, tmp = tempfile.mkstemp(prefix="hirio_evidence_", suffix=".png")
            os.close(fd)
            if not slot.image.save(tmp, "PNG"):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                paths.append(None)
                continue
            self._temp_files.append(tmp)
            paths.append(tmp)
        return paths

    def cleanup_temps(self) -> None:
        for p in self._temp_files:
            try:
                if p and os.path.exists(p):
                    os.unlink(p)
            except OSError:
                pass
        self._temp_files = []

    def run_ocr(self) -> FleaTransactionOcrResult:
        texts: List[str] = []
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            service = self._get_ocr_service()
            temps = self.export_slot_temp_paths()
            for path in temps:
                if not path:
                    texts.append("")
                    continue
                try:
                    result = service.extract_text(path, use_preprocessing=True)
                    texts.append(str(result.get("text") or ""))
                except Exception as exc:
                    texts.append("")
                    self.status_label.setText(f"OCR失敗: {exc}")
            chosen = pick_transaction_text(texts)
            parsed = parse_transaction_ocr_text(chosen or "")
            self._ocr_result = parsed
            self._show_ocr_result(parsed)
            self.ocr_finished.emit(parsed)
            return parsed
        finally:
            QApplication.restoreOverrideCursor()

    def _show_ocr_result(self, parsed: FleaTransactionOcrResult) -> None:
        if not parsed.has_core_fields():
            self.status_label.setText(
                "取引画面から日時・商品IDを読めませんでした。3枚目に取引画面を貼って再度OCRしてください。"
            )
            self.datetime_check.setEnabled(False)
            self.datetime_check.setChecked(False)
            self.price_hint.setText("")
            return
        lines = [
            f"OCR購入日時: {parsed.purchase_datetime or '（なし）'}",
            f"アマサーチの仕入れ日: {self._current_datetime or '（なし）'}",
            f"商品ID: {parsed.item_id or '（なし）'}",
            f"出品者: {parsed.seller_name or '（なし）'}",
        ]
        self.status_label.setText("\n".join(lines))
        differ = bool(
            parsed.purchase_datetime
            and self._current_datetime
            and parsed.purchase_datetime != self._current_datetime
        )
        self.datetime_check.setEnabled(bool(parsed.purchase_datetime))
        self.datetime_check.setChecked(bool(parsed.purchase_datetime) and (
            differ or not self._current_datetime
        ))
        if parsed.item_price is not None:
            self.price_hint.setText(
                f"商品代金の読み取り: {parsed.item_price}円（仕入れ価格は自動では変えません）"
            )
        else:
            self.price_hint.setText("")

    def _on_slot_selected(self, index: int) -> None:
        self._selected_index = index
        for i, slot in enumerate(self.slots):
            slot.set_selected_style(i == index)

    def _on_shortcut_paste(self) -> None:
        self.paste_clipboard_to_next()

    def _get_ocr_service(self) -> OCRService:
        if self._ocr_service is None:
            self._ocr_service = OCRService()
        return self._ocr_service
