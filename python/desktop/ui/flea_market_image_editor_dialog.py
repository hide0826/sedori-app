#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ出品用: 画像テキスト帯の大画面編集ダイアログ。"""
from __future__ import annotations

import copy
import logging
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)

try:
    from desktop.services.flea_market_image_overlay_service import (
        Align,
        DEFAULT_BOTTOM_EDGE_INSET,
        DEFAULT_FLEA_SQUARE_SIZE,
        MAX_FLEA_SQUARE_SIZE,
        MIN_FLEA_SQUARE_SIZE,
        SQUARE_FIT_MODE_OPTIONS,
        ImageOverlaySettings,
        TextBandStyle,
        apply_text_overlay,
        default_overlay_settings,
        enumerate_font_choices,
        resolve_meiryo_font_path,
    )
except ImportError:
    from services.flea_market_image_overlay_service import (  # type: ignore
        Align,
        DEFAULT_BOTTOM_EDGE_INSET,
        DEFAULT_FLEA_SQUARE_SIZE,
        MAX_FLEA_SQUARE_SIZE,
        MIN_FLEA_SQUARE_SIZE,
        SQUARE_FIT_MODE_OPTIONS,
        ImageOverlaySettings,
        TextBandStyle,
        apply_text_overlay,
        default_overlay_settings,
        enumerate_font_choices,
        resolve_meiryo_font_path,
    )

logger = logging.getLogger(__name__)

_PREVIEW_MAX_SCREEN_RATIO = 0.55
_DEBOUNCE_MS = 350


class _OverlayPreviewThread(QThread):
    finished_ok = Signal(str)
    finished_error = Signal(str)

    def __init__(
        self,
        source_path: str,
        settings: ImageOverlaySettings,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._source_path = source_path
        self._settings = copy.deepcopy(settings)

    def run(self) -> None:
        try:
            if not self._settings.has_any_text():
                self.finished_error.emit("上部または下部にテキストを入力してください。")
                return
            out = apply_text_overlay(self._source_path, settings=self._settings)
            self.finished_ok.emit(out)
        except Exception as e:
            logger.exception("overlay preview")
            self.finished_error.emit(str(e))


class _BandStylePanel(QGroupBox):
    """上部または下部のスタイル編集パネル。"""

    changed = Signal()

    def __init__(
        self,
        title: str,
        *,
        band_position: str = "top",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(title, parent)
        self._band_position = band_position
        self._font_choices: List[Tuple[str, str]] = enumerate_font_choices()
        self._block_signals = False
        self._edge_inset_spin: Optional[QSpinBox] = None
        self._build_ui()

    def _build_ui(self) -> None:
        form = QFormLayout(self)

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("表示するテキスト")
        self.text_edit.textChanged.connect(self._emit_changed)
        form.addRow("テキスト:", self.text_edit)

        self.font_combo = QComboBox()
        for label, path in self._font_choices:
            self.font_combo.addItem(label, path)
        meiryo = resolve_meiryo_font_path()
        if meiryo:
            for i in range(self.font_combo.count()):
                if self.font_combo.itemData(i) == meiryo:
                    self.font_combo.setCurrentIndex(i)
                    break
        self.font_combo.currentIndexChanged.connect(self._emit_changed)
        form.addRow("フォント:", self.font_combo)

        size_row = QWidget()
        size_lay = QHBoxLayout(size_row)
        size_lay.setContentsMargins(0, 0, 0, 0)
        self.auto_size_chk = QCheckBox("自動")
        self.auto_size_chk.setChecked(True)
        self.auto_size_chk.setToolTip("ON: 帯の高さに合わせてサイズ自動調整")
        self.auto_size_chk.toggled.connect(self._on_auto_toggled)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(10, 120)
        self.size_spin.setValue(36)
        self.size_spin.setEnabled(False)
        self.size_spin.setSuffix(" px")
        self.size_spin.valueChanged.connect(self._emit_changed)
        size_lay.addWidget(self.auto_size_chk)
        size_lay.addWidget(self.size_spin)
        form.addRow("文字サイズ:", size_row)

        self.bold_chk = QCheckBox("太字 (BOLD)")
        self.bold_chk.toggled.connect(self._emit_changed)
        form.addRow("", self.bold_chk)

        align_row = QWidget()
        align_lay = QHBoxLayout(align_row)
        align_lay.setContentsMargins(0, 0, 0, 0)
        self.align_group = QButtonGroup(self)
        self.align_left = QRadioButton("左")
        self.align_center = QRadioButton("中央")
        self.align_right = QRadioButton("右")
        self.align_center.setChecked(True)
        for i, btn in enumerate((self.align_left, self.align_center, self.align_right)):
            self.align_group.addButton(btn, i)
            btn.toggled.connect(self._emit_changed)
            align_lay.addWidget(btn)
        form.addRow("揃え:", align_row)

        color_row = QWidget()
        color_lay = QHBoxLayout(color_row)
        color_lay.setContentsMargins(0, 0, 0, 0)
        self.text_color_btn = QPushButton("文字色")
        self.text_color_btn.clicked.connect(self._pick_text_color)
        self._text_color = QColor(0, 0, 0)
        self._update_text_color_btn()
        self.bg_color_btn = QPushButton("帯の色")
        self.bg_color_btn.clicked.connect(self._pick_bg_color)
        self._bg_color = QColor(255, 255, 255)
        self._update_bg_color_btn()
        color_lay.addWidget(self.text_color_btn)
        color_lay.addWidget(self.bg_color_btn)
        form.addRow("色:", color_row)

        opacity_row = QWidget()
        opacity_lay = QHBoxLayout(opacity_row)
        opacity_lay.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(75)
        self.opacity_label = QLabel("75%")
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_lay.addWidget(self.opacity_slider, stretch=1)
        opacity_lay.addWidget(self.opacity_label)
        form.addRow("帯の透過率:", opacity_row)

        if self._band_position == "bottom":
            self._edge_inset_spin = QSpinBox()
            self._edge_inset_spin.setRange(0, 120)
            self._edge_inset_spin.setValue(DEFAULT_BOTTOM_EDGE_INSET)
            self._edge_inset_spin.setSuffix(" px")
            self._edge_inset_spin.setToolTip(
                "帯全体を下辺から離して上にずらします（未指定時も最低約44px相当は確保）"
            )
            self._edge_inset_spin.valueChanged.connect(self._emit_changed)
            form.addRow("下からの余白:", self._edge_inset_spin)
        elif self._band_position == "top":
            self._edge_inset_spin = QSpinBox()
            self._edge_inset_spin.setRange(0, 120)
            self._edge_inset_spin.setValue(0)
            self._edge_inset_spin.setSuffix(" px")
            self._edge_inset_spin.setToolTip("帯全体を上辺から離します")
            self._edge_inset_spin.valueChanged.connect(self._emit_changed)
            form.addRow("上からの余白:", self._edge_inset_spin)

    def _on_auto_toggled(self, checked: bool) -> None:
        self.size_spin.setEnabled(not checked)
        self._emit_changed()

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_label.setText(f"{value}%")
        self._emit_changed()

    def _pick_text_color(self) -> None:
        c = QColorDialog.getColor(self._text_color, self, "文字色を選択")
        if c.isValid():
            self._text_color = c
            self._update_text_color_btn()
            self._emit_changed()

    def _pick_bg_color(self) -> None:
        c = QColorDialog.getColor(self._bg_color, self, "帯の背景色を選択")
        if c.isValid():
            self._bg_color = c
            self._update_bg_color_btn()
            self._emit_changed()

    def _update_text_color_btn(self) -> None:
        self.text_color_btn.setStyleSheet(
            f"background-color: {self._text_color.name()}; color: "
            f"{'#fff' if self._text_color.lightness() < 128 else '#000'};"
        )

    def _update_bg_color_btn(self) -> None:
        self.bg_color_btn.setStyleSheet(
            f"background-color: {self._bg_color.name()}; color: "
            f"{'#fff' if self._bg_color.lightness() < 128 else '#000'};"
        )

    def _emit_changed(self, *_args) -> None:
        if not self._block_signals:
            self.changed.emit()

    def _align(self) -> Align:
        if self.align_left.isChecked():
            return "left"
        if self.align_right.isChecked():
            return "right"
        return "center"

    def _set_align(self, align: Align) -> None:
        if align == "left":
            self.align_left.setChecked(True)
        elif align == "right":
            self.align_right.setChecked(True)
        else:
            self.align_center.setChecked(True)

    def to_style(self) -> TextBandStyle:
        font_path = self.font_combo.currentData()
        return TextBandStyle(
            text=self.text_edit.text().strip(),
            font_path=str(font_path) if font_path else None,
            font_size=None if self.auto_size_chk.isChecked() else self.size_spin.value(),
            bold=self.bold_chk.isChecked(),
            align=self._align(),
            text_color=(
                self._text_color.red(),
                self._text_color.green(),
                self._text_color.blue(),
            ),
            bg_color=(
                self._bg_color.red(),
                self._bg_color.green(),
                self._bg_color.blue(),
            ),
            bg_opacity_percent=self.opacity_slider.value(),
            edge_inset=self._edge_inset_spin.value() if self._edge_inset_spin else 0,
        )

    def load_style(self, style: TextBandStyle) -> None:
        self._block_signals = True
        try:
            self.text_edit.setText(style.text or "")
            if style.font_path:
                for i in range(self.font_combo.count()):
                    if self.font_combo.itemData(i) == style.font_path:
                        self.font_combo.setCurrentIndex(i)
                        break
            self.auto_size_chk.setChecked(style.auto_size)
            self.size_spin.setEnabled(not style.auto_size)
            if style.font_size is not None:
                self.size_spin.setValue(style.font_size)
            self.bold_chk.setChecked(style.bold)
            self._set_align(style.align)
            self._text_color = QColor(*style.text_color)
            self._bg_color = QColor(*style.bg_color)
            self._update_text_color_btn()
            self._update_bg_color_btn()
            self.opacity_slider.setValue(style.bg_opacity_percent)
            self.opacity_label.setText(f"{style.bg_opacity_percent}%")
            if self._edge_inset_spin is not None:
                if self._band_position == "bottom":
                    inset_val = style.edge_inset
                    if inset_val < DEFAULT_BOTTOM_EDGE_INSET:
                        inset_val = DEFAULT_BOTTOM_EDGE_INSET
                    self._edge_inset_spin.setValue(inset_val)
                else:
                    self._edge_inset_spin.setValue(style.edge_inset)
        finally:
            self._block_signals = False


class FleaMarketImageEditorDialog(QDialog):
    """大画面でテキスト帯を編集し、適用した画像パスを返す。"""

    def __init__(
        self,
        source_path: str,
        *,
        initial_settings: Optional[ImageOverlaySettings] = None,
        window_title: str = "画像編集",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._source_path = source_path
        self._settings = copy.deepcopy(
            initial_settings or default_overlay_settings()
        )
        self._preview_path: Optional[str] = None
        self._applied_path: Optional[str] = None
        self._preview_thread: Optional[_OverlayPreviewThread] = None

        self.setWindowTitle(window_title)
        self.setMinimumSize(960, 640)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._refresh_preview)

        self._build_ui()
        self.top_panel.load_style(self._settings.top)
        self.bottom_panel.load_style(self._settings.bottom)
        self._load_square_options(self._settings)
        QTimer.singleShot(100, self._refresh_preview)

    def applied_path(self) -> Optional[str]:
        return self._applied_path

    def result_settings(self) -> ImageOverlaySettings:
        return copy.deepcopy(self._collect_settings())

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)

        left = QVBoxLayout()
        self._status_label = QLabel("プレビュー更新中...")
        self._status_label.setStyleSheet("color: #aaa; font-size: 9pt;")
        left.addWidget(self._status_label)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        self._preview_scroll.setAlignment(Qt.AlignCenter)
        self._preview_label = QLabel("プレビュー")
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setMinimumSize(320, 240)
        self._preview_label.setStyleSheet("background-color: #1a1a1a;")
        self._preview_scroll.setWidget(self._preview_label)
        left.addWidget(self._preview_scroll, stretch=1)
        root.addLayout(left, stretch=3)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setMinimumWidth(300)
        right_scroll.setMaximumWidth(380)
        right_host = QWidget()
        right = QVBoxLayout(right_host)

        self.top_panel = _BandStylePanel("上部テキスト", band_position="top")
        self.top_panel.changed.connect(self._schedule_preview)
        right.addWidget(self.top_panel)

        self.bottom_panel = _BandStylePanel("下部テキスト", band_position="bottom")
        self.bottom_panel.changed.connect(self._schedule_preview)
        right.addWidget(self.bottom_panel)

        square_box = QGroupBox("フリマ用 1:1 出力")
        square_form = QFormLayout(square_box)
        self.export_square_chk = QCheckBox("1:1（正方形）で書き出す")
        self.export_square_chk.setChecked(True)
        self.export_square_chk.setToolTip("メルカリ等の出品画像向けに正方形JPEGで保存します")
        self.export_square_chk.toggled.connect(self._on_export_square_toggled)
        square_form.addRow("", self.export_square_chk)

        self.square_fit_combo = QComboBox()
        for label, mode in SQUARE_FIT_MODE_OPTIONS:
            self.square_fit_combo.addItem(label, mode)
        self.square_fit_combo.setToolTip(
            "ズーム埋め: 写真を1:1にしてから文字を載せる（余白なし・推奨）\n"
            "余白収め: 文字込み全体を1:1に収める（余白が付く場合あり）"
        )
        self.square_fit_combo.currentIndexChanged.connect(self._on_square_fit_changed)
        square_form.addRow("1:1の入れ方:", self.square_fit_combo)

        self.square_size_spin = QSpinBox()
        self.square_size_spin.setRange(MIN_FLEA_SQUARE_SIZE, MAX_FLEA_SQUARE_SIZE)
        self.square_size_spin.setSingleStep(60)
        self.square_size_spin.setValue(DEFAULT_FLEA_SQUARE_SIZE)
        self.square_size_spin.setSuffix(" px")
        self.square_size_spin.valueChanged.connect(self._schedule_preview)
        square_form.addRow("辺の長さ:", self.square_size_spin)

        self.square_bg_btn = QPushButton("余白色")
        self._square_bg = QColor(255, 255, 255)
        self._update_square_bg_btn()
        self.square_bg_btn.clicked.connect(self._pick_square_bg)
        square_form.addRow("余白:", self.square_bg_btn)

        self.square_hint = QLabel()
        self.square_hint.setWordWrap(True)
        self.square_hint.setStyleSheet("color: #888; font-size: 9pt;")
        square_form.addRow(self.square_hint)

        right.addWidget(square_box)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("プレビュー更新")
        refresh_btn.clicked.connect(self._refresh_preview)
        btn_row.addWidget(refresh_btn)
        right.addLayout(btn_row)

        apply_btn = QPushButton("適用して閉じる")
        apply_btn.setStyleSheet("font-weight: bold;")
        apply_btn.clicked.connect(self._apply_and_close)
        right.addWidget(apply_btn)

        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        right.addWidget(cancel_btn)

        right.addStretch()
        right_scroll.setWidget(right_host)
        root.addWidget(right_scroll, stretch=1)

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            self.resize(int(g.width() * 0.85), int(g.height() * 0.88))

    def _load_square_options(self, settings: ImageOverlaySettings) -> None:
        self.export_square_chk.setChecked(settings.export_square)
        self.square_size_spin.setValue(settings.square_size)
        for i in range(self.square_fit_combo.count()):
            if self.square_fit_combo.itemData(i) == settings.square_fit_mode:
                self.square_fit_combo.setCurrentIndex(i)
                break
        self._square_bg = QColor(*settings.square_bg_color)
        self._update_square_bg_btn()
        self._sync_square_controls_enabled()
        self._update_square_hint()

    def _pick_square_bg(self) -> None:
        c = QColorDialog.getColor(self._square_bg, self, "1:1余白の色")
        if c.isValid():
            self._square_bg = c
            self._update_square_bg_btn()
            self._schedule_preview()

    def _update_square_bg_btn(self) -> None:
        self.square_bg_btn.setStyleSheet(
            f"background-color: {self._square_bg.name()}; color: "
            f"{'#fff' if self._square_bg.lightness() < 128 else '#000'};"
        )

    def _current_square_fit_mode(self) -> str:
        data = self.square_fit_combo.currentData()
        return str(data) if data else "cover"

    def _is_letterbox_mode(self) -> bool:
        return self._current_square_fit_mode() == "letterbox"

    def _update_square_hint(self) -> None:
        if not self.export_square_chk.isChecked():
            self.square_hint.setText("プレビューは元の縦横比のままです。")
            return
        if self._is_letterbox_mode():
            self.square_hint.setText(
                "余白で全体を収めます。上下の文字は切れにくいですが、メルカリ上で余白が目立つことがあります。"
            )
        else:
            self.square_hint.setText(
                "先に写真を1:1にズームしてから、上下に文字帯を載せます（余白なし・文字は切れにくい）。"
            )

    def _sync_square_controls_enabled(self) -> None:
        on = self.export_square_chk.isChecked()
        letterbox = on and self._is_letterbox_mode()
        self.square_fit_combo.setEnabled(on)
        self.square_size_spin.setEnabled(on)
        self.square_bg_btn.setEnabled(letterbox)

    def _collect_settings(self) -> ImageOverlaySettings:
        return ImageOverlaySettings(
            top=self.top_panel.to_style(),
            bottom=self.bottom_panel.to_style(),
            export_square=self.export_square_chk.isChecked(),
            square_size=self.square_size_spin.value(),
            square_fit_mode=self._current_square_fit_mode(),  # type: ignore[arg-type]
            square_bg_color=(
                self._square_bg.red(),
                self._square_bg.green(),
                self._square_bg.blue(),
            ),
        )

    def _on_square_fit_changed(self, _index: int) -> None:
        self._sync_square_controls_enabled()
        self._update_square_hint()
        self._schedule_preview()

    def _on_export_square_toggled(self, _checked: bool) -> None:
        self._sync_square_controls_enabled()
        self._update_square_hint()
        self._schedule_preview()

    def _schedule_preview(self) -> None:
        self._debounce.start()

    def _set_preview_pixmap(self, path: str) -> None:
        pix = QPixmap(path)
        if pix.isNull():
            self._preview_label.setText("プレビューを表示できません")
            return
        screen = QGuiApplication.primaryScreen()
        max_w, max_h = 900, 700
        if screen is not None:
            g = screen.availableGeometry()
            max_w = int(g.width() * _PREVIEW_MAX_SCREEN_RATIO)
            max_h = int(g.height() * _PREVIEW_MAX_SCREEN_RATIO)
        scaled = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._preview_label.setPixmap(scaled)
        if pix.width() == pix.height():
            mode = "余白収め" if self._is_letterbox_mode() else "ズーム埋め"
            size_note = f"出力 {pix.width()}×{pix.height()} px（1:1・{mode}）"
        else:
            size_note = f"出力 {pix.width()}×{pix.height()} px"
        self._status_label.setText(
            f"{size_note}　画面表示: {scaled.width()}×{scaled.height()} px"
        )

    def _refresh_preview(self) -> None:
        settings = self._collect_settings()
        if not settings.has_any_text():
            self._status_label.setText("上部または下部にテキストを入力してください")
            return
        if self._preview_thread and self._preview_thread.isRunning():
            return
        self._status_label.setText("プレビュー生成中...")
        self._preview_thread = _OverlayPreviewThread(
            self._source_path,
            settings,
            self,
        )
        self._preview_thread.finished_ok.connect(self._on_preview_ok)
        self._preview_thread.finished_error.connect(self._on_preview_error)
        self._preview_thread.start()

    def _on_preview_ok(self, path: str) -> None:
        self._preview_path = path
        self._set_preview_pixmap(path)

    def _on_preview_error(self, message: str) -> None:
        self._status_label.setText(message)

    def _apply_and_close(self) -> None:
        settings = self._collect_settings()
        if not settings.has_any_text():
            QMessageBox.information(self, "画像編集", "上部または下部にテキストを入力してください。")
            return
        try:
            if self._preview_thread and self._preview_thread.isRunning():
                self._preview_thread.wait(5000)
            path = apply_text_overlay(self._source_path, settings=settings)
            self._applied_path = path
            self._settings = settings
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "画像編集", str(e))

    def closeEvent(self, event) -> None:
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.wait(3000)
        super().closeEvent(event)
