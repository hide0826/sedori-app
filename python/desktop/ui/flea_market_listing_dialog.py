#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フリマ出品情報ダイアログ（Gemini生成・画像ドラッグ対応）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QSize, QTimer
from PySide6.QtGui import QDrag, QPixmap, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from desktop.services.flea_market_record_utils import (
        collect_product_image_paths,
        prepare_record_for_flea_images,
    )
    from desktop.services.gemini_flea_market_service import (
        FLEA_STYLE_LABELS,
        GeminiFleaMarketService,
    )
except ImportError:
    from services.flea_market_record_utils import (  # type: ignore
        collect_product_image_paths,
        prepare_record_for_flea_images,
    )
    from services.gemini_flea_market_service import (  # type: ignore
        FLEA_STYLE_LABELS,
        GeminiFleaMarketService,
    )

logger = logging.getLogger(__name__)

_THUMB_SIZE = 140
_STYLE_OPTIONS = list(FLEA_STYLE_LABELS.keys())


class DraggableImageLabel(QLabel):
    """ローカル画像ファイルをブラウザ（メルカリ等）へドラッグできるラベル。"""

    def __init__(self, image_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._image_path = image_path
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(_THUMB_SIZE, _THUMB_SIZE)
        self.setMaximumSize(_THUMB_SIZE, _THUMB_SIZE)
        self.setStyleSheet(
            "border: 1px dashed #888; background-color: #2a2a2a; color: #ccc;"
        )
        self.setToolTip(f"ドラッグしてフリマの画像欄へドロップ\n{image_path}")
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self._load_thumbnail()

    def _load_thumbnail(self) -> None:
        pix = QPixmap(self._image_path)
        if pix.isNull():
            self.setText("読込失敗")
            return
        scaled = pix.scaled(
            QSize(_THUMB_SIZE - 8, _THUMB_SIZE - 8),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setCursor(QCursor(Qt.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.setCursor(QCursor(Qt.OpenHandCursor))
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton):
            return
        if event.position().toPoint().manhattanLength() < QApplication.startDragDistance():
            return
        from PySide6.QtCore import QMimeData

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self._image_path)])
        mime.setText(self._image_path)
        drag = QDrag(self)
        drag.setMimeData(mime)
        pix = self.pixmap()
        if pix and not pix.isNull():
            drag.setPixmap(pix.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        drag.exec(Qt.CopyAction)


class _FleaMarketGenerateThread(QThread):
    finished_ok = Signal(dict)
    finished_error = Signal(str)

    def __init__(
        self,
        record: Dict[str, Any],
        style: str,
        one_time_text: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._record = record
        self._style = style
        self._one_time_text = one_time_text

    def run(self) -> None:
        try:
            svc = GeminiFleaMarketService()
            if not svc.is_available():
                self.finished_error.emit(
                    "Gemini API が利用できません。\n"
                    "設定タブで API キーを登録するか、pip install google-generativeai を確認してください。"
                )
                return
            result = svc.generate_listing(
                self._record,
                style=self._style,
                one_time_text=self._one_time_text,
            )
            if not result:
                self.finished_error.emit("文案の生成に失敗しました。ログを確認してください。")
                return
            self.finished_ok.emit(result)
        except Exception as e:
            logger.exception("Flea market generate thread")
            self.finished_error.emit(str(e))


class FleaMarketListingDialog(QDialog):
    """フリマ出品情報 — 生成ボタンで文案作成、右: 画像ドラッグ。"""

    def __init__(
        self,
        record: Dict[str, Any],
        parent: Optional[QWidget] = None,
        *,
        product_widget: Optional[QWidget] = None,
        auto_generate: bool = False,
    ):
        super().__init__(parent)
        self._product_widget = product_widget
        self.record = prepare_record_for_flea_images(
            dict(record) if record else {},
            product_widget,
        )
        self._generate_thread: Optional[_FleaMarketGenerateThread] = None
        self._has_generated = False
        self.setWindowTitle("フリマ出品情報")
        self.setMinimumSize(760, 640)
        self.resize(920, 680)
        self._build_ui()
        self._populate_images()
        if auto_generate:
            self._start_generate()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.record = prepare_record_for_flea_images(self.record, self._product_widget)
        self._populate_images()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        options = QGroupBox("生成オプション")
        options.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        options.setMaximumHeight(72)
        opt_row = QHBoxLayout(options)
        opt_row.setContentsMargins(8, 4, 8, 4)
        opt_row.setSpacing(10)

        opt_row.addWidget(QLabel("文案スタイル:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(_STYLE_OPTIONS)
        self.style_combo.setCurrentText("標準")
        self.style_combo.setToolTip("出品文案の文体・長さのスタイル")
        self.style_combo.setFixedWidth(100)
        opt_row.addWidget(self.style_combo)

        opt_row.addWidget(QLabel("今回だけ含める文言:"))
        self.one_time_edit = QLineEdit()
        self.one_time_edit.setPlaceholderText("例: 即購入OK・値下げ不可")
        self.one_time_edit.setClearButtonEnabled(True)
        opt_row.addWidget(self.one_time_edit, stretch=1)
        root.addWidget(options, stretch=0)

        hint = QLabel(
            "右の画像サムネをドラッグして、メルカリ・ヤフフリ等の出品画面の画像欄へドロップできます。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaa; font-size: 9pt; padding: 0 2px;")
        root.addWidget(hint, stretch=0)

        body = QHBoxLayout()
        body.setSpacing(12)

        left = QGroupBox("出品文案")
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(6)

        title_form = QFormLayout()
        title_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("生成後に表示されます（40文字目安）")
        self.title_edit.setMaxLength(80)
        title_form.addRow(
            "タイトル:",
            self._wrap_field_with_copy(self.title_edit, lambda: self.title_edit.text()),
        )
        left_layout.addLayout(title_form)

        listing_label = QLabel("出品説明:")
        left_layout.addWidget(listing_label)
        self.listing_desc_edit = QTextEdit()
        self.listing_desc_edit.setPlaceholderText(
            "下部の「出品文案を生成」を押すと、AIがタイトル・出品説明・価格案を作成します。"
        )
        self.listing_desc_edit.setMinimumHeight(280)
        self.listing_desc_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(
            self._wrap_field_with_copy(
                self.listing_desc_edit,
                lambda: self.listing_desc_edit.toPlainText(),
            ),
            stretch=1,
        )

        price_form = QFormLayout()
        self.price_spin = QSpinBox()
        self.price_spin.setRange(0, 9_999_999)
        self.price_spin.setSingleStep(100)
        self.price_spin.setSuffix(" 円")
        price_form.addRow("販売価格提案:", self.price_spin)
        left_layout.addLayout(price_form)

        body.addWidget(left, stretch=4)

        right = QGroupBox("商品画像（画像1〜6）")
        right_layout = QVBoxLayout(right)
        drag_hint_btn = QPushButton("画像をメルカリへドラッグ")
        drag_hint_btn.setEnabled(False)
        drag_hint_btn.setToolTip("各サムネイルをドラッグしてブラウザの出品画面へドロップしてください")
        right_layout.addWidget(drag_hint_btn)

        self._image_grid_host = QWidget()
        self._image_grid = QGridLayout(self._image_grid_host)
        self._image_grid.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._image_grid_host)
        scroll.setMinimumWidth(320)
        right_layout.addWidget(scroll, stretch=1)
        body.addWidget(right, stretch=2)

        root.addLayout(body, stretch=1)

        footer = QHBoxLayout()
        self.generate_btn = QPushButton("出品文案を生成")
        self.generate_btn.setMinimumWidth(140)
        self.generate_btn.clicked.connect(self._start_generate)
        footer.addWidget(self.generate_btn)
        footer.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer, stretch=0)

    @staticmethod
    def _wrap_field_with_copy(field: QWidget, get_text) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(field, stretch=1)
        copy_btn = QPushButton("コピー")
        copy_btn.setFixedWidth(56)
        copy_btn.setToolTip("クリップボードにコピー")
        copy_btn.clicked.connect(
            lambda _checked=False, g=get_text, b=copy_btn: FleaMarketListingDialog._copy_to_clipboard(g(), b)
        )
        lay.addWidget(copy_btn, 0)
        return row

    @staticmethod
    def _copy_to_clipboard(text: str, button: Optional[QPushButton] = None) -> None:
        content = (text or "").strip()
        if not content:
            QMessageBox.information(None, "コピー", "コピーする内容がありません。")
            return
        QApplication.clipboard().setText(text)
        if button is None:
            return
        original = button.text()
        button.setText("コピー済")
        button.setEnabled(False)

        def _restore() -> None:
            button.setText(original)
            button.setEnabled(True)

        QTimer.singleShot(1200, _restore)

    def _current_style_key(self) -> str:
        label = self.style_combo.currentText()
        return FLEA_STYLE_LABELS.get(label, "standard")

    def _set_generating_ui(self, generating: bool) -> None:
        self.generate_btn.setEnabled(not generating)
        self.style_combo.setEnabled(not generating)
        self.one_time_edit.setEnabled(not generating)
        if generating:
            self.generate_btn.setText("生成中...")
        elif self._has_generated:
            self.generate_btn.setText("出品文案を再生成")
        else:
            self.generate_btn.setText("出品文案を生成")

    def _populate_images(self) -> None:
        self.record = prepare_record_for_flea_images(self.record, self._product_widget)
        while self._image_grid.count():
            item = self._image_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        paths = collect_product_image_paths(self.record)
        if not paths:
            empty = QLabel("画像1〜6が未設定か、ファイルが見つかりません。")
            empty.setWordWrap(True)
            self._image_grid.addWidget(empty, 0, 0, 1, 2)
            return

        for idx, path in enumerate(paths):
            row, col = divmod(idx, 2)
            cap = QLabel(f"画像{idx + 1}")
            cap.setAlignment(Qt.AlignCenter)
            thumb = DraggableImageLabel(path)
            cell = QVBoxLayout()
            cell_w = QWidget()
            cell_w.setLayout(cell)
            cell.addWidget(cap)
            cell.addWidget(thumb, alignment=Qt.AlignCenter)
            self._image_grid.addWidget(cell_w, row, col)

    def _start_generate(self) -> None:
        if self._generate_thread and self._generate_thread.isRunning():
            return
        self._set_generating_ui(True)
        self._generate_thread = _FleaMarketGenerateThread(
            self.record,
            self._current_style_key(),
            self.one_time_edit.text(),
            self,
        )
        self._generate_thread.finished_ok.connect(self._on_generate_ok)
        self._generate_thread.finished_error.connect(self._on_generate_error)
        self._generate_thread.finished.connect(self._on_generate_thread_finished)
        self._generate_thread.start()

    def _on_generate_thread_finished(self) -> None:
        self._set_generating_ui(False)

    def _on_generate_ok(self, data: dict) -> None:
        self._has_generated = True
        self.setWindowTitle("フリマ出品情報（生成済）")
        self.title_edit.setText(data.get("title") or "")
        listing = data.get("listing_description") or ""
        if not listing:
            short = (data.get("short_description") or "").strip()
            detail = (data.get("detailed_description") or "").strip()
            parts = [p for p in (short, detail) if p]
            listing = "\n\n".join(parts)
        self.listing_desc_edit.setPlainText(listing)
        price = data.get("suggested_price")
        if price is not None:
            try:
                self.price_spin.setValue(int(price))
            except (TypeError, ValueError):
                pass

    def _on_generate_error(self, message: str) -> None:
        QMessageBox.warning(self, "フリマ情報生成", message)

    def closeEvent(self, event) -> None:
        if self._generate_thread and self._generate_thread.isRunning():
            self._generate_thread.requestInterruption()
            self._generate_thread.wait(3000)
        super().closeEvent(event)
