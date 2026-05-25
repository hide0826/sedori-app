#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フリマ出品情報ダイアログ（Gemini生成・画像ドラッグ・1枚文字入れ対応）
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QSize, QTimer
from PySide6.QtGui import QDrag, QPixmap, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
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
    from desktop.services.flea_market_image_overlay_service import (
        BOTTOM_TEXT_PRESETS,
        ImageOverlaySettings,
        SQUARE_FIT_MODE_OPTIONS,
        apply_text_overlay,
        default_overlay_settings,
        product_name_from_record,
    )
    from desktop.ui.flea_market_image_editor_dialog import FleaMarketImageEditorDialog
    from desktop.services.gemini_flea_market_service import (
        FLEA_STYLE_LABELS,
        GeminiFleaMarketService,
    )
except ImportError:
    from services.flea_market_record_utils import (  # type: ignore
        collect_product_image_paths,
        prepare_record_for_flea_images,
    )
    from services.flea_market_image_overlay_service import (  # type: ignore
        BOTTOM_TEXT_PRESETS,
        ImageOverlaySettings,
        SQUARE_FIT_MODE_OPTIONS,
        apply_text_overlay,
        default_overlay_settings,
        product_name_from_record,
    )
    from ui.flea_market_image_editor_dialog import FleaMarketImageEditorDialog  # type: ignore
    from services.gemini_flea_market_service import (  # type: ignore
        FLEA_STYLE_LABELS,
        GeminiFleaMarketService,
    )

logger = logging.getLogger(__name__)

_THUMB_SIZE = 140
_STYLE_OPTIONS = list(FLEA_STYLE_LABELS.keys())
_THUMB_STYLE_NORMAL = (
    "border: 1px dashed #888; background-color: #2a2a2a; color: #ccc;"
)
_THUMB_STYLE_OVERLAY = (
    "border: 2px solid #4caf50; background-color: #2a2a2a; color: #ccc;"
)
class DraggableImageLabel(QLabel):
    """ローカル画像ファイルをブラウザ（メルカリ等）へドラッグできるラベル。"""

    preview_requested = Signal(str)

    def __init__(self, image_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._image_path = image_path
        self._overlay_applied = False
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(_THUMB_SIZE, _THUMB_SIZE)
        self.setMaximumSize(_THUMB_SIZE, _THUMB_SIZE)
        self._apply_border_style()
        self.setToolTip(
            f"ドラッグしてフリマの画像欄へドロップ\n"
            f"ダブルクリックで大画面編集\n{image_path}"
        )
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self._load_thumbnail()

    @property
    def image_path(self) -> str:
        return self._image_path

    def set_image_path(self, path: str, *, overlay_applied: bool = False) -> None:
        self._image_path = path
        self._overlay_applied = overlay_applied
        self._apply_border_style()
        self.setToolTip(
            f"ドラッグしてフリマの画像欄へドロップ\n"
            f"ダブルクリックで大画面プレビュー\n{path}"
        )
        self._load_thumbnail()

    def reset_to_original(self, original_path: str) -> None:
        self.set_image_path(original_path, overlay_applied=False)

    def _apply_border_style(self) -> None:
        style = _THUMB_STYLE_OVERLAY if self._overlay_applied else _THUMB_STYLE_NORMAL
        self.setStyleSheet(style)

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

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.preview_requested.emit(self._image_path)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

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


class _FleaOverlayApplyThread(QThread):
    finished_ok = Signal(int, str, object)  # slot_index, output_path, settings
    finished_error = Signal(str)

    def __init__(
        self,
        source_path: str,
        slot_index: int,
        settings: ImageOverlaySettings,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._source_path = source_path
        self._slot_index = slot_index
        self._settings = copy.deepcopy(settings)

    def run(self) -> None:
        try:
            out = apply_text_overlay(self._source_path, settings=self._settings)
            self.finished_ok.emit(self._slot_index, out, self._settings)
        except Exception as e:
            logger.exception("Flea overlay apply")
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
        self._overlay_thread: Optional[_FleaOverlayApplyThread] = None
        self._has_generated = False
        self._image_slots: List[Dict[str, Any]] = []
        self._image_select_group = QButtonGroup(self)
        self._image_select_group.setExclusive(True)
        self.setWindowTitle("フリマ出品情報")
        self.setMinimumSize(800, 720)
        self.resize(980, 760)
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

        overlay_box = QGroupBox("画像への文字入れ（チェックした1枚のみ）")
        overlay_form = QFormLayout(overlay_box)
        overlay_form.setContentsMargins(8, 8, 8, 8)

        self.top_source_combo = QComboBox()
        self.top_source_combo.addItems(["商品名", "出品タイトル", "直接入力"])
        self.top_source_combo.setToolTip("画像上部に載せる文字の出どころ")
        overlay_form.addRow("上部テキスト:", self.top_source_combo)

        self.top_custom_edit = QLineEdit()
        self.top_custom_edit.setPlaceholderText("直接入力時のみ")
        self.top_custom_edit.setEnabled(False)
        self.top_source_combo.currentTextChanged.connect(self._on_top_source_changed)
        overlay_form.addRow("上部（直接）:", self.top_custom_edit)

        self.bottom_preset_combo = QComboBox()
        self.bottom_preset_combo.addItems(list(BOTTOM_TEXT_PRESETS))
        self.bottom_preset_combo.setToolTip("画像下部に載せる定型文")
        overlay_form.addRow("下部テキスト:", self.bottom_preset_combo)

        self.bottom_custom_edit = QLineEdit()
        self.bottom_custom_edit.setPlaceholderText("直接入力時のみ")
        self.bottom_custom_edit.setEnabled(False)
        self.bottom_preset_combo.currentTextChanged.connect(self._on_bottom_preset_changed)
        overlay_form.addRow("下部（直接）:", self.bottom_custom_edit)

        self.overlay_apply_btn = QPushButton("選択画像に文字を反映")
        self.overlay_apply_btn.setToolTip(
            "チェックした1枚にのみ、メイリオ黒字・半透明白帯で文字を入れます（元画像は変更しません）"
        )
        self.overlay_apply_btn.clicked.connect(self._apply_overlay_to_selected)
        overlay_form.addRow("", self.overlay_apply_btn)

        self.overlay_reset_btn = QPushButton("選択画像を元に戻す")
        self.overlay_reset_btn.clicked.connect(self._reset_overlay_on_selected)
        overlay_form.addRow("", self.overlay_reset_btn)

        self.export_square_chk = QCheckBox("フリマ用1:1で出力")
        self.export_square_chk.setChecked(True)
        self.export_square_chk.setToolTip("ON: 正方形JPEG（1080px等）で保存してドラッグ")
        self.export_square_chk.toggled.connect(self._on_export_square_toggled)
        overlay_form.addRow("", self.export_square_chk)

        self.square_fit_combo = QComboBox()
        for label, mode in SQUARE_FIT_MODE_OPTIONS:
            self.square_fit_combo.addItem(label, mode)
        self.square_fit_combo.setCurrentIndex(0)
        overlay_form.addRow("1:1の入れ方:", self.square_fit_combo)

        self.overlay_editor_btn = QPushButton("大画面で編集…")
        self.overlay_editor_btn.setToolTip("チェックした画像を大画面で編集（フォント・色・揃え等）")
        self.overlay_editor_btn.clicked.connect(self._open_editor_for_selected)
        overlay_form.addRow("", self.overlay_editor_btn)

        right_layout.addWidget(overlay_box)

        select_hint = QLabel(
            "1枚のみ文字入れ。1:1は「ズーム埋め」か「余白収め」を選択。詳細はダブルクリック／大画面で編集。"
        )
        select_hint.setStyleSheet("color: #aaa; font-size: 9pt;")
        select_hint.setWordWrap(True)
        right_layout.addWidget(select_hint)

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

    def _on_top_source_changed(self, label: str) -> None:
        self.top_custom_edit.setEnabled(label == "直接入力")

    def _on_bottom_preset_changed(self, label: str) -> None:
        self.bottom_custom_edit.setEnabled(label == "直接入力")

    def _on_export_square_toggled(self, checked: bool) -> None:
        self.square_fit_combo.setEnabled(checked)

    def _quick_apply_square_fit_mode(self) -> str:
        data = self.square_fit_combo.currentData()
        return str(data) if data else "cover"

    def _slot_caption(self, slot_index: int) -> str:
        slot = next((s for s in self._image_slots if s["index"] == slot_index), None)
        caption = f"画像{slot_index + 1}"
        if slot:
            cap: QLabel = slot["caption"]
            caption = (cap.text() or caption).strip()
        return caption

    def _initial_overlay_settings_for_slot(self, slot_index: int) -> ImageOverlaySettings:
        slot = next((s for s in self._image_slots if s["index"] == slot_index), None)
        if slot and slot.get("overlay_settings"):
            return copy.deepcopy(slot["overlay_settings"])
        return default_overlay_settings(
            self._resolve_top_overlay_text(),
            self._resolve_bottom_overlay_text(),
        )

    def _open_image_editor(self, _image_path: str, slot_index: int) -> None:
        slot = next((s for s in self._image_slots if s["index"] == slot_index), None)
        if not slot:
            return
        source = slot["original_path"]
        caption = self._slot_caption(slot_index)
        dlg = FleaMarketImageEditorDialog(
            source,
            initial_settings=self._initial_overlay_settings_for_slot(slot_index),
            window_title=f"画像編集 — {caption}",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            path = dlg.applied_path()
            settings = dlg.result_settings()
            if path:
                self._finish_overlay_slot(slot_index, path, settings)

    def _open_editor_for_selected(self) -> None:
        idx = self._selected_slot_index()
        if idx is None:
            QMessageBox.information(
                self,
                "画像編集",
                "編集する画像にチェックを付けてください。",
            )
            return
        self._open_image_editor("", idx)

    def _selected_slot_index(self) -> Optional[int]:
        for slot in self._image_slots:
            chk = slot.get("checkbox")
            if chk is not None and chk.isChecked():
                return int(slot["index"])
        return None

    def _resolve_top_overlay_text(self) -> str:
        source = self.top_source_combo.currentText()
        if source == "商品名":
            return product_name_from_record(self.record)
        if source == "出品タイトル":
            return (self.title_edit.text() or "").strip()
        return (self.top_custom_edit.text() or "").strip()

    def _resolve_bottom_overlay_text(self) -> str:
        preset = self.bottom_preset_combo.currentText()
        if preset == "（なし）":
            return ""
        if preset == "直接入力":
            return (self.bottom_custom_edit.text() or "").strip()
        return preset

    def _set_overlay_ui_busy(self, busy: bool) -> None:
        self.overlay_apply_btn.setEnabled(not busy)
        self.overlay_reset_btn.setEnabled(not busy)
        self.overlay_editor_btn.setEnabled(not busy)
        self.export_square_chk.setEnabled(not busy)
        self.square_fit_combo.setEnabled(not busy and self.export_square_chk.isChecked())
        self.top_source_combo.setEnabled(not busy)
        self.top_custom_edit.setEnabled(not busy and self.top_source_combo.currentText() == "直接入力")
        self.bottom_preset_combo.setEnabled(not busy)
        preset = self.bottom_preset_combo.currentText()
        self.bottom_custom_edit.setEnabled(not busy and preset == "直接入力")
        if busy:
            self.overlay_apply_btn.setText("処理中...")
        else:
            self.overlay_apply_btn.setText("選択画像に文字を反映")

    def _apply_overlay_to_selected(self) -> None:
        if self._overlay_thread and self._overlay_thread.isRunning():
            return
        idx = self._selected_slot_index()
        if idx is None:
            QMessageBox.information(
                self,
                "画像への文字入れ",
                "文字を入れる画像にチェックを付けてください（1枚のみ）。",
            )
            return
        slot = next((s for s in self._image_slots if s["index"] == idx), None)
        if not slot:
            return
        top = self._resolve_top_overlay_text()
        bottom = self._resolve_bottom_overlay_text()
        if not top and not bottom:
            QMessageBox.information(
                self,
                "画像への文字入れ",
                "上部または下部のテキストを指定してください。",
            )
            return
        settings = default_overlay_settings(top, bottom)
        settings.export_square = self.export_square_chk.isChecked()
        settings.square_fit_mode = self._quick_apply_square_fit_mode()  # type: ignore[assignment]
        self._set_overlay_ui_busy(True)
        self._overlay_thread = _FleaOverlayApplyThread(
            slot["original_path"],
            idx,
            settings,
            self,
        )
        self._overlay_thread.finished_ok.connect(self._on_overlay_ok)
        self._overlay_thread.finished_error.connect(self._on_overlay_error)
        self._overlay_thread.finished.connect(lambda: self._set_overlay_ui_busy(False))
        self._overlay_thread.start()

    def _finish_overlay_slot(
        self,
        slot_index: int,
        output_path: str,
        settings: ImageOverlaySettings,
    ) -> None:
        slot = next((s for s in self._image_slots if s["index"] == slot_index), None)
        if not slot:
            return
        thumb: DraggableImageLabel = slot["thumb"]
        thumb.set_image_path(output_path, overlay_applied=True)
        slot["overlay_path"] = output_path
        slot["overlay_settings"] = copy.deepcopy(settings)
        cap: QLabel = slot["caption"]
        cap.setText(f"画像{slot_index + 1}（文字入れ済）")
        cap.setStyleSheet("color: #4caf50; font-weight: bold;")

    def _on_overlay_ok(self, slot_index: int, output_path: str, settings: object) -> None:
        if isinstance(settings, ImageOverlaySettings):
            self._finish_overlay_slot(slot_index, output_path, settings)

    def _on_overlay_error(self, message: str) -> None:
        QMessageBox.warning(self, "画像への文字入れ", message)

    def _reset_overlay_on_selected(self) -> None:
        idx = self._selected_slot_index()
        if idx is None:
            QMessageBox.information(
                self,
                "画像への文字入れ",
                "元に戻す画像にチェックを付けてください。",
            )
            return
        slot = next((s for s in self._image_slots if s["index"] == idx), None)
        if not slot:
            return
        thumb: DraggableImageLabel = slot["thumb"]
        thumb.reset_to_original(slot["original_path"])
        slot["overlay_path"] = None
        slot["overlay_settings"] = None
        cap: QLabel = slot["caption"]
        cap.setText(f"画像{idx + 1}")
        cap.setStyleSheet("")

    def _populate_images(self) -> None:
        self.record = prepare_record_for_flea_images(self.record, self._product_widget)
        for slot in self._image_slots:
            chk = slot.get("checkbox")
            if chk is not None:
                self._image_select_group.removeButton(chk)
        self._image_slots.clear()

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
            thumb.preview_requested.connect(
                lambda path, i=idx: self._open_image_editor(path, i)
            )
            chk = QCheckBox("この画像に文字入れ")
            chk.setToolTip("1枚だけチェックできます")
            self._image_select_group.addButton(chk)
            chk.toggled.connect(lambda checked, i=idx: self._on_image_check_toggled(i, checked))

            cell = QVBoxLayout()
            cell_w = QWidget()
            cell_w.setLayout(cell)
            cell.addWidget(cap)
            cell.addWidget(chk, alignment=Qt.AlignCenter)
            cell.addWidget(thumb, alignment=Qt.AlignCenter)
            self._image_grid.addWidget(cell_w, row, col)

            self._image_slots.append(
                {
                    "index": idx,
                    "original_path": path,
                    "overlay_path": None,
                    "overlay_settings": None,
                    "thumb": thumb,
                    "caption": cap,
                    "checkbox": chk,
                }
            )

        if self._image_slots:
            first_chk = self._image_slots[0]["checkbox"]
            first_chk.setChecked(True)

    def _on_image_check_toggled(self, index: int, checked: bool) -> None:
        if not checked:
            return
        for slot in self._image_slots:
            if slot["index"] == index:
                continue
            other = slot.get("checkbox")
            if other is not None and other.isChecked():
                other.blockSignals(True)
                other.setChecked(False)
                other.blockSignals(False)

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
        if self._overlay_thread and self._overlay_thread.isRunning():
            self._overlay_thread.requestInterruption()
            self._overlay_thread.wait(3000)
        super().closeEvent(event)
