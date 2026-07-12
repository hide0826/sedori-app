#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amazonテンプレート・ブラウザ連携 mixin。"""
from __future__ import annotations

import sys
import os
import json
import re
import io
import uuid
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import logging
from html import escape
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QMimeData, QUrl, QSettings, QFileInfo
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QListWidget,
    QListWidgetItem, QSplitter, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QSizePolicy, QTextEdit, QProgressDialog,
    QInputDialog, QMenu, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QTabWidget, QSpinBox, QComboBox, QFrame, QFileIconProvider, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem,
)
from PySide6.QtGui import (
    QPixmap, QFont, QDrag, QDropEvent, QImageReader, QImage, QDesktopServices, QCursor,
    QColor, QBrush, QPainter,
)
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_flags_from_folder
from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget
from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front

try:
    from utils.amazon_image_naming import (
        extract_sku_from_image_path as _amazon_extract_sku_from_path,
        infer_sku_from_sorted_images,
        needs_amazon_sequence_rerename,
        plan_amazon_rename_targets,
        plan_amazon_rerename_targets,
    )
except ImportError:
    from desktop.utils.amazon_image_naming import (
        extract_sku_from_image_path as _amazon_extract_sku_from_path,
        infer_sku_from_sorted_images,
        needs_amazon_sequence_rerename,
        plan_amazon_rename_targets,
        plan_amazon_rerename_targets,
    )

try:
    from utils.settings_helper import get_amazon_inventory_loader_upload_url
except ImportError:
    from desktop.utils.settings_helper import (  # type: ignore
        get_amazon_inventory_loader_upload_url,
    )

try:
    from services.image_service import (
        ImageService,
        ImageRecord,
        JanGroup,
        DEFAULT_AUTO_CORRECT_PRESET,
    )
    from services.ocr_service import OCRService
except Exception:
    from desktop.services.image_service import (
        ImageService,
        ImageRecord,
        JanGroup,
        DEFAULT_AUTO_CORRECT_PRESET,
    )
    from desktop.services.ocr_service import OCRService

from database.image_db import ImageDatabase


from .support import (
    ScanCancelledError,
    CandidateSelectionDialog,
    PurchaseCandidateDialog,
    JanGroupTreeWidget,
    ImageListWidget,
    RegistrationTableWidget,
    ImageLoadThread,
    _WORKFLOW_PIPELINE_SEGMENTS,
    _WORKFLOW_PIPELINE_SEP,
    _ACTION_TO_PIPELINE_STEP,
    _REGISTRATION_WORKFLOW_PIPELINE_SEGMENTS,
    _REGISTRATION_ACTION_TO_PIPELINE_STEP,
    _AMAZON_UPLOAD_BROWSER_TITLE_KEYWORDS,
    _UNLINKED_HIGHLIGHT_BG,
    _UNLINKED_HIGHLIGHT_FG,
    _PURCHASE_IMAGE_COLUMNS,
    _normalize_jan_for_match,
    _normalize_image_path,
    _record_has_any_image_paths,
    _apply_unlinked_item_style,
    _record_jan_matches_group,
    _candidate_is_known_linked_product,
    _candidate_should_highlight_in_dialog,
    _format_status_prefix_html,
    _format_workflow_pipeline_html,
)

class ImageManagerAmazonTemplateMixin:
    def _load_amazon_inventory_loader_service(self):
        """amazon_inventory_loader_service をファイルパスから読み込む"""
        import importlib.util
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # ui/image_manager/ → desktop/services または python/services
        desktop_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))
        python_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
        service_candidates = [
            os.path.join(desktop_dir, 'services', 'amazon_inventory_loader_service.py'),
            os.path.join(python_dir, 'services', 'amazon_inventory_loader_service.py'),
        ]
        service_file = next((p for p in service_candidates if os.path.exists(p)), None)
        if not service_file:
            raise FileNotFoundError(
                f"amazon_inventory_loader_service が見つかりません: {service_candidates}"
            )
        spec = importlib.util.spec_from_file_location("amazon_inventory_loader_service", service_file)
        loader_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loader_module)
        return loader_module.AmazonInventoryLoaderService


    def _is_template_layout_manual_mode(self) -> bool:
        return self.template_layout_mode_combo.currentIndex() == 1


    def _on_template_layout_mode_changed(self, _index: int = 0):
        manual = self._is_template_layout_manual_mode()
        self._set_template_layout_fields_enabled(manual)
        self._save_template_layout_settings()
        if not manual:
            self.analyze_amazon_template_layout(show_errors=False)


    def _set_template_layout_fields_enabled(self, manual: bool):
        for widget in (
            self.template_sku_col_edit,
            self.template_image_start_col_edit,
            self.template_image_end_col_edit,
            self.template_start_row_spin,
        ):
            widget.setEnabled(manual)


    def _column_index_from_ui_letter(self, letter_edit: QLineEdit) -> Optional[int]:
        AmazonInventoryLoaderService = self._load_amazon_inventory_loader_service()
        return AmazonInventoryLoaderService._parse_column_letter(letter_edit.text())


    def _apply_detected_layout_to_ui(self, layout: Dict[str, Any]):
        AmazonInventoryLoaderService = self._load_amazon_inventory_loader_service()
        sku_col = int(layout.get("sku_col") or 1)
        image_start = int(layout.get("image_start_col") or 16)
        image_end = int(layout.get("image_end_col") or image_start)
        start_row = int(layout.get("start_row") or 7)

        self.template_sku_col_edit.setText(AmazonInventoryLoaderService._column_letter(sku_col))
        self.template_image_start_col_edit.setText(AmazonInventoryLoaderService._column_letter(image_start))
        self.template_image_end_col_edit.setText(AmazonInventoryLoaderService._column_letter(image_end))
        self.template_start_row_spin.setValue(start_row)

        status = layout.get("message") or "テンプレートを解析しました。"
        if layout.get("warnings"):
            status += "\n" + "\n".join(f"・{w}" for w in layout["warnings"])
        if not layout.get("success", True):
            status = f"⚠ {status}\n（フォールバック: P〜U列、7行目を使用します）"
        self.template_layout_status_label.setText(status)


    def analyze_amazon_template_layout(self, show_errors: bool = True):
        """選択中テンプレートから書き込み位置を自動検出してUIに反映"""
        template_path_str = self.template_file_edit.text().strip()
        if not template_path_str:
            self.template_layout_status_label.setText("テンプレートファイルが未選択です。")
            if show_errors:
                QMessageBox.warning(self, "警告", "先にテンプレートファイルを選択してください。")
            return

        template_path = Path(template_path_str)
        if not template_path.exists():
            self.template_layout_status_label.setText("テンプレートファイルが見つかりません。")
            if show_errors:
                QMessageBox.warning(self, "警告", f"テンプレートファイルが見つかりません:\n{template_path}")
            return

        try:
            AmazonInventoryLoaderService = self._load_amazon_inventory_loader_service()
            layout = AmazonInventoryLoaderService.detect_template_layout(str(template_path))
            if not self._is_template_layout_manual_mode():
                self._apply_detected_layout_to_ui(layout)
            else:
                message = layout.get("message") or "テンプレートを解析しました。"
                if layout.get("warnings"):
                    message += "\n" + "\n".join(f"・{w}" for w in layout["warnings"])
                self.template_layout_status_label.setText(
                    f"{message}\n（手動モードのため、右側の値は変更していません）"
                )
            self._save_template_layout_settings()
        except Exception as e:
            logger.error(f"Amazon template layout analyze failed: {e}", exc_info=True)
            self.template_layout_status_label.setText(f"テンプレート解析エラー: {e}")
            if show_errors:
                QMessageBox.warning(self, "警告", f"テンプレート解析に失敗しました:\n{e}")


    def _build_image_cols_from_ui(self) -> Optional[List[int]]:
        start_col = self._column_index_from_ui_letter(self.template_image_start_col_edit)
        end_col = self._column_index_from_ui_letter(self.template_image_end_col_edit)
        if start_col is None or end_col is None:
            return None
        if end_col < start_col:
            start_col, end_col = end_col, start_col
        return list(range(start_col, end_col + 1))[:6]


    def _get_template_write_params(self) -> Dict[str, Any]:
        sku_col = self._column_index_from_ui_letter(self.template_sku_col_edit)
        image_cols = self._build_image_cols_from_ui()
        start_row = self.template_start_row_spin.value()
        manual = self._is_template_layout_manual_mode()
        return {
            "start_row": start_row,
            "sku_col": sku_col,
            "image_cols": image_cols,
            "auto_detect": not manual,
        }


    def _save_template_layout_settings(self):
        settings = QSettings("HIRIO", "SedoriApp")
        settings.setValue("image_manager/template_layout_mode", self.template_layout_mode_combo.currentIndex())
        settings.setValue("image_manager/template_sku_col", self.template_sku_col_edit.text().strip().upper())
        settings.setValue("image_manager/template_image_start_col", self.template_image_start_col_edit.text().strip().upper())
        settings.setValue("image_manager/template_image_end_col", self.template_image_end_col_edit.text().strip().upper())
        settings.setValue("image_manager/template_start_row", self.template_start_row_spin.value())


    def _load_template_layout_settings(self):
        settings = QSettings("HIRIO", "SedoriApp")
        mode_index = int(settings.value("image_manager/template_layout_mode", 0))
        self.template_layout_mode_combo.setCurrentIndex(mode_index)
        self.template_sku_col_edit.setText(str(settings.value("image_manager/template_sku_col", "A")))
        self.template_image_start_col_edit.setText(str(settings.value("image_manager/template_image_start_col", "P")))
        self.template_image_end_col_edit.setText(str(settings.value("image_manager/template_image_end_col", "U")))
        self.template_start_row_spin.setValue(int(settings.value("image_manager/template_start_row", 7)))
        self._set_template_layout_fields_enabled(mode_index == 1)


    def _format_template_layout_message(self, layout: Dict[str, Any], product_count: int, output_path: str) -> str:
        AmazonInventoryLoaderService = self._load_amazon_inventory_loader_service()
        sku_col = int(layout.get("sku_col") or 1)
        image_cols = layout.get("image_cols") or [16, 17, 18, 19, 20, 21]
        start_row = int(layout.get("start_row") or 7)
        sku_letter = AmazonInventoryLoaderService._column_letter(sku_col)

        lines = [
            f"AmazonテンプレートExcelファイルを保存しました:\n{output_path}",
            f"\n商品数: {product_count}件",
            "\n書き込まれたデータ:",
            f"  - SKU: {sku_letter}列 {start_row}行目から",
        ]
        for idx, col in enumerate(image_cols[:6]):
            letter = AmazonInventoryLoaderService._column_letter(col)
            lines.append(f"  - 画像URL: {letter}列 {start_row}行目から（{idx + 1}枚目）")
        lines.append("\n👉 このファイルをAmazon Seller Centralにアップロードしてください。")
        lines.append(
            "\n※ アップロード時に「最新のファイルに変更してください」と表示された場合は、"
            "新しいテンプレートをダウンロードして差し替えてください。"
        )
        return "\n".join(lines)


    def write_to_amazon_template(self):
        """AmazonテンプレートExcelファイルに商品データを書き込む"""
        if not self.registration_records:
            QMessageBox.warning(self, "警告", "登録されている商品がありません。")
            return
        
        # テーブルから最新のデータを取得
        products = []
        for row in range(self.registration_table.rowCount()):
            if row >= len(self.registration_records):
                continue
            
            entry = self.registration_records[row]
            
            # SKUを取得
            sku = entry.get("sku", "")
            if not sku:
                continue
            
            # 画像URLを取得（最大6枚まで）
            # GCSアップロード後のURLをエントリから取得
            image_urls = []
            
            # 1. image_urlsリスト形式を優先的に確認
            if 'image_urls' in entry and isinstance(entry.get('image_urls'), list):
                image_urls = [url for url in entry['image_urls'] if url]
            else:
                # 2. image_url_1～6の個別キー形式を確認
                for i in range(1, 7):  # 6枚まで取得
                    img_key = f'image_url_{i}'
                    img_url = entry.get(img_key, '')
                    if img_url:
                        image_urls.append(img_url)
            
            # 3. テーブルの画像URL列からも取得（画像URL1～5列、列15-19）
            for img_idx in range(5):  # 画像URL1～5
                col = 15 + img_idx  # 画像URL1列は15列目（0-indexed）
                item = self.registration_table.item(row, col)
                if item and item.text():
                    image_url = item.text().strip()
                    if image_url and image_url not in image_urls:
                        image_urls.append(image_url)
            
            # 商品データを作成（SKUと画像URLのみ）
            product = {
                "sku": sku,
            }
            
            # 画像URLを追加（最大6枚まで）
            if image_urls:
                product["image_urls"] = image_urls[:6]  # 最大6枚まで
            
            products.append(product)
        
        if not products:
            QMessageBox.warning(self, "警告", "有効な商品データがありません。")
            return

        write_params = self._get_template_write_params()
        if write_params["auto_detect"] is False:
            if write_params["sku_col"] is None:
                QMessageBox.warning(self, "警告", "SKU列の指定が不正です。例: A")
                return
            if not write_params["image_cols"]:
                QMessageBox.warning(self, "警告", "画像列の指定が不正です。例: P 〜 U")
                return
        
        # テンプレートファイルのパスを取得
        try:
            AmazonInventoryLoaderService = self._load_amazon_inventory_loader_service()
            # テンプレートファイルのパス（設定から読み込む）
            template_path_str = self.template_file_edit.text().strip()
            if not template_path_str:
                QMessageBox.warning(
                    self, "警告",
                    "テンプレートファイルが指定されていません。\n"
                    "「参照...」ボタンからテンプレートファイルを選択してください。"
                )
                return
            
            template_path = Path(template_path_str)
            
            if not template_path.exists():
                QMessageBox.critical(
                    self, "エラー",
                    f"Amazonテンプレートファイルが見つかりません:\n{template_path}\n\n"
                    f"テンプレートファイルを配置してください。"
                )
                return
            
            # 出力ファイルの保存先を選択
            from datetime import datetime
            default_filename = f"ListingLoader_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsm"

            # 保存ダイアログの起点となるフォルダを決定
            # 1. ユーザーが「保存先デフォルト」で設定したルートフォルダ（仕入れフォルダなど）
            # 2. 未設定の場合はテンプレートファイルと同じフォルダ
            settings = QSettings("HIRIO", "SedoriApp")
            root_dir = settings.value("amazon_template_root_dir", "")
            base_dir = root_dir or str(template_path.parent)
            initial_path = str(Path(base_dir) / default_filename)

            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "AmazonテンプレートExcelファイルを保存",
                initial_path,
                "Excelマクロ有効ファイル (*.xlsm);;すべてのファイル (*)"
            )
            
            if not file_path:
                return  # ユーザーがキャンセル
            
            # テンプレートに書き込み
            output_path, layout_used = AmazonInventoryLoaderService.write_to_amazon_template_excel(
                template_path=str(template_path),
                products=products,
                output_path=file_path,
                start_row=write_params["start_row"] if not write_params["auto_detect"] else None,
                sku_col=write_params["sku_col"] if not write_params["auto_detect"] else None,
                image_cols=write_params["image_cols"] if not write_params["auto_detect"] else None,
                auto_detect=write_params["auto_detect"],
            )
            
            self._set_amazon_template_upload_file(output_path)

            summary = self._format_template_layout_message(layout_used, len(products), output_path)
            reply = QMessageBox.question(
                self,
                "書き込み完了",
                summary
                + "\n\n"
                "次の手順:\n"
                "① Amazonアップロードページを開く\n"
                "② 表示されたExcelアイコンをブラウザのドロップ欄にドラッグ\n\n"
                "Amazonアップロードページを今すぐ開きますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.open_amazon_upload_page()

            # ルートタブ側の「画像」チェックをONにする（対応するルートサマリーが判定できた場合）
            try:
                self._mark_route_images_completed_for_folders(
                    Path(file_path).parent,
                    self.current_directory,
                    self.default_root_dir,
                )
            except Exception as e:
                # ルート判定に失敗しても致命的ではないのでログのみ
                logger.warning(f"画像フラグ更新エラー: {e}")
        
        except Exception as e:
            logger.error(f"Failed to write to Amazon template Excel: {e}", exc_info=True)
            QMessageBox.critical(
                self, "エラー",
                f"AmazonテンプレートExcelファイルの書き込み中にエラーが発生しました:\n{str(e)}"
            )


    def browse_template_file(self):
        """テンプレートファイルを選択する"""
        settings = QSettings("HIRIO", "SedoriApp")
        last_dir = settings.value("amazon_template_last_dir", str(Path.home()))
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "AmazonテンプレートExcelファイルを選択",
            last_dir,
            "Excelマクロ有効ファイル (*.xlsm);;すべてのファイル (*)"
        )
        
        if file_path:
            template_path = Path(file_path)
            if template_path.exists():
                self.template_file_edit.setText(str(template_path))
                # 設定に保存
                self.save_template_file_setting(str(template_path))
                # 最後に開いたディレクトリを保存
                settings.setValue("amazon_template_last_dir", str(template_path.parent))
                self.analyze_amazon_template_layout(show_errors=False)
            else:
                QMessageBox.warning(
                    self, "警告",
                    f"選択したファイルが見つかりません:\n{file_path}"
                )


    def load_template_file_setting(self):
        """設定からテンプレートファイルパスを読み込む"""
        settings = QSettings("HIRIO", "SedoriApp")
        template_path = settings.value("amazon_template_file_path", "")
        
        if template_path:
            template_path_obj = Path(template_path)
            if template_path_obj.exists():
                self.template_file_edit.setText(template_path)
            else:
                # ファイルが存在しない場合は設定をクリア
                settings.remove("amazon_template_file_path")
                self.template_file_edit.clear()
        else:
            # デフォルトパスを試す
            default_path = Path(__file__).resolve().parents[3] / "ListingLoader.xlsm"
            if default_path.exists():
                self.template_file_edit.setText(str(default_path))
                self.save_template_file_setting(str(default_path))

        self._load_template_layout_settings()
        if self.template_file_edit.text().strip():
            QTimer.singleShot(0, lambda: self.analyze_amazon_template_layout(show_errors=False))


    def save_template_file_setting(self, template_path: str):
        """テンプレートファイルパスを設定に保存する"""
        settings = QSettings("HIRIO", "SedoriApp")
        settings.setValue("amazon_template_file_path", template_path)
        settings.sync()


    def set_amazon_template_root_dir(self):
        """Amazonテンプレート書き出し用のデフォルト（起点）フォルダを設定する"""
        settings = QSettings("HIRIO", "SedoriApp")
        # 既に設定があればそこから、なければホームディレクトリから開始
        start_dir = settings.value("amazon_template_root_dir", str(Path.home()))
        
        directory = QFileDialog.getExistingDirectory(
            self,
            "Amazonテンプレート保存用のデフォルトフォルダを選択",
            start_dir
        )
        if not directory:
            return
        
        settings.setValue("amazon_template_root_dir", directory)
        settings.sync()
        
        QMessageBox.information(
            self,
            "保存先デフォルトを設定しました",
            f"今後、AmazonテンプレートExcelを書き出すときの起点フォルダは次の場所になります:\n\n{directory}\n\n"
            "毎回このフォルダの中から、ルート別フォルダなどを書き出し先として選んでください。"
        )


    def _set_amazon_template_upload_file(self, file_path: str) -> None:
        """テンプレート書き込み後、Amazonへドラッグするファイルをパネルに表示"""
        path = str(file_path or "").strip()
        self._last_amazon_template_output_path = path
        if not path or not os.path.isfile(path):
            if hasattr(self, "amazon_upload_drop_panel"):
                self.amazon_upload_drop_panel.setVisible(False)
            if hasattr(self, "amazon_template_drag_icon"):
                self.amazon_template_drag_icon.clear_file()
            return

        self.amazon_template_drag_icon.set_file_path(path)
        self.amazon_upload_drop_filename.setText(path)
        self.amazon_upload_drop_panel.setVisible(True)
        self.amazon_upload_drop_hint.setText(
            "「Amazonアップロードページを開く」後、左のExcelアイコンをドラッグしてください"
        )


    def _bring_amazon_upload_browser_to_front(self) -> None:
        """ブラウザ起動後に Seller Central を前面へ（読み込み待ちで複数回試行）。"""
        schedule_bring_browser_to_front(
            _AMAZON_UPLOAD_BROWSER_TITLE_KEYWORDS,
            pin_topmost_until_ms=8000,
        )


    def _open_last_amazon_template_folder(self) -> None:
        """直近に書き出したAmazonテンプレートの保存フォルダを開く"""
        path = self._last_amazon_template_output_path
        if not path or not os.path.isfile(path):
            QMessageBox.information(
                self,
                "情報",
                "まだテンプレートファイルが書き出されていません。\n"
                "先に「amazon（出品ファイルL）テンプレートに書き込み」を実行してください。",
            )
            return
        folder = str(Path(path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


    def open_amazon_upload_page(self):
        """Amazon Seller Centralの出品ファイルアップロードページをブラウザで開く"""
        amazon_url = get_amazon_inventory_loader_upload_url()
        try:
            QDesktopServices.openUrl(QUrl(amazon_url))
            if (
                self._last_amazon_template_output_path
                and os.path.isfile(self._last_amazon_template_output_path)
                and hasattr(self, "amazon_upload_drop_panel")
            ):
                self.amazon_upload_drop_panel.setVisible(True)
            self.amazon_upload_drop_hint.setText(
                "ブラウザでアップロードページを開きました。"
                "左のExcelアイコンをドラッグしてドロップ欄へ送ってください。"
                "（ドラッグ中はブラウザが最前面に出ます）"
            )
            QTimer.singleShot(900, self._bring_amazon_upload_browser_to_front)
        except Exception as e:
            QMessageBox.critical(
                self, "エラー",
                f"ブラウザでAmazonアップロードページを開けませんでした:\n{str(e)}\n\n"
                f"手動で以下のURLにアクセスしてください:\n{amazon_url}"
            )


