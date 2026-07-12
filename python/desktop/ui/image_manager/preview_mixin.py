#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像リスト・プレビュー・回転 mixin。"""
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

class ImageManagerPreviewMixin:
    @staticmethod
    def _pil_image_to_qpixmap(pil_img: Image.Image) -> QPixmap:
        buffer = io.BytesIO()
        pil_img.save(buffer, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        return pixmap


    def _scale_pixmap_for_label(self, pixmap: QPixmap, label: QLabel) -> QPixmap:
        if pixmap.isNull():
            return pixmap
        size = label.size()
        if size.width() < 32 or size.height() < 32:
            size = label.minimumSize()
        return pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


    def _refresh_image_previews(self) -> None:
        """選択中画像の元／補正後プレビューを更新"""
        if not self.selected_image_path or not os.path.isfile(self.selected_image_path):
            self._clear_image_preview_panels()
            return
        try:
            with Image.open(self.selected_image_path) as src:
                original = ImageOps.exif_transpose(src)
            orig_pix = self._scale_pixmap_for_label(
                self._pil_image_to_qpixmap(original.convert("RGB")),
                self.preview_original_label,
            )
            self.preview_original_label.setPixmap(orig_pix)
            self.preview_original_label.setText("")

            preset_id = self._auto_correct_preset_id()
            corrected = self.image_service.apply_product_auto_correct(original, preset_id)
            corr_pix = self._scale_pixmap_for_label(
                self._pil_image_to_qpixmap(corrected),
                self.preview_corrected_label,
            )
            self.preview_corrected_label.setPixmap(corr_pix)
            self.preview_corrected_label.setText("")
        except Exception as e:
            logger.warning("プレビュー更新エラー: %s", e)
            self.preview_original_label.setText("プレビュー失敗")
            self.preview_corrected_label.setText("プレビュー失敗")


    def _clear_image_preview_panels(self) -> None:
        self.preview_original_label.clear()
        self.preview_original_label.setText("画像を選択")
        self.preview_corrected_label.clear()
        self.preview_corrected_label.setText("画像を選択")


    def update_image_list(self, records: List[ImageRecord], show_progress: bool = False):
        """画像リストを更新
        
        Args:
            records: 画像レコードのリスト
            show_progress: Trueの場合、プログレスダイアログを表示（デフォルト: False）
        """
        self.image_list.clear()
        
        if not records:
            return
        
        # 画像読み込みをスレッドで実行
        image_paths = [r.path for r in records]
        
        # 既存のスレッドがあれば終了を待つ
        if self.load_thread:
            if self.load_thread.isRunning():
                # 強制terminate()は不安定要因になるため、キャンセルフラグ＋waitで終了させる
                try:
                    if hasattr(self.load_thread, "cancel"):
                        self.load_thread.cancel()
                    self.load_thread.wait(3000)  # 最大3秒待つ
                except Exception as e:
                    logger.debug(f"Failed to gracefully stop ImageLoadThread: {e}")
            self.load_thread = None
        
        # プログレスダイアログは必要に応じて表示（通常は非表示で高速化）
        if show_progress:
            if self.progress_dialog:
                self.progress_dialog.close()
            self.progress_dialog = QProgressDialog(
                "画像を読み込み中...", "キャンセル", 0, len(image_paths), self
            )
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.show()
        else:
            # プログレスダイアログなしでバックグラウンド読み込み
            self.progress_dialog = None
        
        self.load_thread = ImageLoadThread(image_paths, max_size=192)
        if show_progress:
            self.load_thread.progress.connect(self.on_load_progress)
        self.load_thread.finished.connect(self.on_load_finished)
        self.load_thread.start()


    def on_load_progress(self, current: int, total: int):
        """画像読み込み進捗更新"""
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.setValue(current)


    def on_load_finished(self, results: List[tuple]):
        """画像読み込み完了"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        for path, image in results:
            item = QListWidgetItem(Path(path).name)
            pixmap = QPixmap.fromImage(image)
            item.setIcon(pixmap)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.image_list.addItem(item)


    def on_image_clicked(self, item: QListWidgetItem):
        """画像クリック時の処理"""
        image_path = item.data(Qt.UserRole)
        if not image_path:
            return
        
        self.selected_image_path = image_path
        self._refresh_image_previews()

        # 詳細情報を更新
        record = next((r for r in self.image_records if r.path == image_path), None)
        if record:
            # JANコード
            jan = record.jan_candidate or ""
            if self.selected_group:
                jan = self.selected_group.jan if self.selected_group.jan != "unknown" else ""
            self.jan_edit.setText(jan)
            
            # 撮影日時
            if record.capture_dt:
                self.capture_time_label.setText(record.capture_dt.strftime("%Y/%m/%d %H:%M:%S"))
            else:
                self.capture_time_label.setText("（不明）")
            
            # ファイル名
            self.file_name_label.setText(Path(image_path).name)
            
            # サイズ
            self.file_size_label.setText(f"{record.width} × {record.height} px")
        else:
            # DBから取得を試みる
            db_record = self.image_db.get_by_file_path(image_path)
            if db_record:
                self.jan_edit.setText(db_record.get("jan", "") or "")
                self.capture_time_label.setText(db_record.get("capture_time", "（不明）"))
                self.file_name_label.setText(Path(image_path).name)
                self.file_size_label.setText("-")
        
        # ボタンを有効化
        self.rotate_left_btn.setEnabled(True)
        self.rotate_right_btn.setEnabled(True)
        self.read_barcode_btn.setEnabled(self.image_service.is_barcode_reader_available())
        self.save_jan_btn.setEnabled(True)


    def rotate_image(self, degrees: int):
        """画像を回転"""
        if not self.selected_image_path:
            return
        
        try:
            success = self.image_service.rotate_image(self.selected_image_path, degrees)
            if success:
                # DBを更新
                db_record = self.image_db.get_by_file_path(self.selected_image_path)
                if db_record:
                    current_rotation = db_record.get("rotation", 0)
                    new_rotation = (current_rotation + degrees) % 360
                    self.image_db.update_rotation(self.selected_image_path, new_rotation)
                
                # プレビューとリストを更新
                self.on_image_clicked(self.image_list.currentItem())
                QMessageBox.information(self, "完了", f"画像を{degrees}度回転しました。")
            else:
                QMessageBox.warning(self, "エラー", "画像の回転に失敗しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"回転中にエラーが発生しました:\n{str(e)}")


    def read_barcode_from_image(self):
        """画像からバーコードを読み取る"""
        if not self.selected_image_path:
            return
        
        if not self.image_service.is_barcode_reader_available():
            QMessageBox.warning(
                self,
                "バーコードリーダー未インストール",
                "バーコードリーダーを使用するには、以下のいずれかをインストールしてください:\n\n"
                "【推奨】pyzxing（ZXingベース）:\n"
                "1. Java JRE 8以上をインストール\n"
                "   https://www.java.com/ja/download/\n"
                "2. pip install pyzxing\n\n"
                "【代替】pyzbar（ZBarベース）:\n"
                "1. pip install pyzbar\n"
                "2. zbarライブラリをインストール:\n"
                "   - Windows: zbar-w64をダウンロードしてインストール\n"
                "   - Linux: sudo apt-get install libzbar0\n"
                "   - macOS: brew install zbar"
            )
            return
        
        try:
            # プログレスダイアログを表示
            QMessageBox.information(self, "読み取り中", "バーコードを読み取っています...")
            
            # バーコードを読み取る
            jan = self.image_service.read_barcode_from_image(self.selected_image_path)
            
            if jan:
                # JANコードを入力欄に設定
                self.jan_edit.setText(jan)
                QMessageBox.information(self, "読み取り完了", f"JANコードを読み取りました: {jan}")
            else:
                QMessageBox.information(self, "読み取り失敗", "画像からバーコードを読み取れませんでした。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"バーコード読み取り中にエラーが発生しました:\n{str(e)}")


    def save_jan(self):
        """JANコードを保存し、4分以内に撮影された画像を同じグループにまとめる"""
        if not self.selected_image_path:
            return
        
        jan = self.jan_edit.text().strip()
        
        # JANコードの検証（8桁または13桁の数字）
        if jan and not re.match(r'^\d{8}$|^\d{13}$', jan):
            QMessageBox.warning(self, "エラー", "JANコードは8桁または13桁の数字である必要があります。")
            return
        
        try:
            # 選択された画像のレコードを取得
            selected_record = next((r for r in self.image_records if r.path == self.selected_image_path), None)
            if not selected_record:
                QMessageBox.warning(self, "エラー", "画像レコードが見つかりませんでした。")
                return
            
            # 選択された画像のEXIFから撮影日時を取得（正確な撮影日時を使用）
            selected_capture_dt = self.image_service.get_exif_datetime(self.selected_image_path)
            if not selected_capture_dt:
                # EXIFが取得できない場合は、既存の撮影日時を使用（フォールバック）
                selected_capture_dt = selected_record.capture_dt
                if not selected_capture_dt:
                    QMessageBox.warning(self, "エラー", "撮影日時が取得できませんでした。")
                    return
            
            # DBを更新
            self.image_db.update_jan(self.selected_image_path, jan if jan else None)
            
            # 選択された画像のJANコードを更新（EXIFから取得した撮影日時を使用）
            selected_record = ImageRecord(
                path=selected_record.path,
                capture_dt=selected_capture_dt,
                jan_candidate=jan,
                width=selected_record.width,
                height=selected_record.height
            )
            
            # JAN画像の撮影時間の後3分以内に撮影された画像を検索して同じJANコードを付与
            time_window = 3 * 60  # 3分 = 180秒
            selected_time = selected_capture_dt
            
            updated_count = 0
            updated_records = []
            for record in self.image_records:
                if record.path == self.selected_image_path:
                    # 選択された画像を更新
                    updated_records.append(selected_record)
                    continue
                
                # 撮影日時がJAN画像の後3分以内の画像を同じJANグループに追加（前は含めない）
                # 各画像のEXIFから撮影日時を取得（正確な撮影日時を使用）
                record_capture_dt = self.image_service.get_exif_datetime(record.path)
                if not record_capture_dt:
                    # EXIFが取得できない場合は、既存の撮影日時を使用（フォールバック）
                    record_capture_dt = record.capture_dt
                
                if record_capture_dt:
                    time_diff = (record_capture_dt - selected_time).total_seconds()
                    if 0 < time_diff <= time_window:
                        db_record = self.image_db.get_by_file_path(record.path)
                        assigned_jan = db_record.get("jan") if db_record else None
                        if assigned_jan:
                            updated_records.append(record)
                            continue
                        # この画像も同じJANコードを付与（EXIFから取得した撮影日時を使用）
                        updated_record = ImageRecord(
                            path=record.path,
                            capture_dt=record_capture_dt,  # EXIFから取得した撮影日時を使用
                            jan_candidate=jan,
                            width=record.width,
                            height=record.height
                        )
                        updated_records.append(updated_record)
                        # DBも更新
                        self.image_db.update_jan(record.path, jan)
                        updated_count += 1
                    else:
                        updated_records.append(record)
                else:
                    updated_records.append(record)
            
            # image_recordsを更新（撮影日時順にソート）
            self.image_records = sorted(
                updated_records, 
                key=lambda r: r.capture_dt if r.capture_dt else datetime.min
            )
            
            # JANグループを再構築
            self.jan_groups = self.image_service.group_by_jan(self.image_records)
            self._jan_title_cache.pop(jan, None)
            
            # UIを更新
            self.update_tree_widget()
            
            # JANコードでSKU候補を検索して提示
            sku_candidates = []
            if jan and self.product_widget:
                sku_candidates = self._search_sku_candidates_by_jan(jan)
            
            # メッセージ表示用のベース文言を組み立て
            message = f"JANコードを保存しました。\n"
            if updated_count > 0:
                message += f"JAN画像の後3分以内に撮影された{updated_count}件の画像を同じグループに追加しました。\n"
            
            if sku_candidates:
                message += f"\n仕入DBから{len(sku_candidates)}件のSKU候補が見つかりました:\n"
                for i, candidate in enumerate(sku_candidates[:5], 1):  # 最大5件表示
                    sku = candidate.get("SKU") or candidate.get("sku") or "（SKUなし）"
                    product_name = candidate.get("商品名") or candidate.get("product_name") or "（商品名なし）"
                    message += f"{i}. {sku} - {product_name}\n"
                if len(sku_candidates) > 5:
                    message += f"... 他{len(sku_candidates) - 5}件"

            QMessageBox.information(self, "完了", message)

            # SKU候補が複数ある場合は、ユーザーにどの仕入レコードと紐付けるか選択してもらう
            if jan and sku_candidates and self.product_widget:
                # 現在のJANグループを特定
                current_group = None
                for group in self.jan_groups:
                    if group.jan == jan:
                        # 選択中の画像を含むグループを優先
                        if any(img.path == self.selected_image_path for img in group.images):
                            current_group = group
                            break
                        if current_group is None:
                            current_group = group

                if current_group and current_group.images:
                    # 選択画像の撮影日時を基準日時として使用
                    base_dt = selected_capture_dt

                    # SKU候補選択ダイアログを表示
                    dialog = PurchaseCandidateDialog(
                        current_group,
                        base_dt,
                        sku_candidates,
                        group_image_paths=self._group_image_paths(current_group),
                        linked_session_jans=self._collect_linked_jan_codes_from_groups(),
                        parent=self,
                    )
                    if dialog.exec_() == QDialog.Accepted and dialog.selected_record:
                        selected_record = dialog.selected_record
                        target_sku = str(
                            selected_record.get("SKU") or selected_record.get("sku") or ""
                        ).strip()

                        if target_sku:
                            try:
                                all_records = self.product_widget.get_all_purchase_records()
                                image_paths = [img.path for img in current_group.images]
                                success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                                    jan,
                                    image_paths,
                                    all_records,
                                    skip_existing=True,
                                    target_sku=target_sku,
                                    defer_table_refresh_and_snapshot=True,
                                )
                                if success:
                                    self._finalize_purchase_db_after_image_link()
                                if success and added_count > 0 and record_snapshot:
                                    # 画像登録タブ用の一覧に1件追加
                                    self.add_registration_entry(record_snapshot)
                            except Exception as e:
                                QMessageBox.critical(
                                    self,
                                    "エラー",
                                    f"仕入DBへの画像紐付け中にエラーが発生しました:\n{str(e)}",
                                )
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存中にエラーが発生しました:\n{str(e)}")


    def on_image_list_context_menu(self, position):
        """画像リストのコンテキストメニュー"""
        item = self.image_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu(self)
        
        delete_action = menu.addAction("画像を削除")
        delete_action.triggered.connect(lambda: self.delete_image_from_list(item))
        
        assign_menu = menu.addMenu("JANグループに追加")
        has_assignable = False
        image_path = item.data(Qt.UserRole)
        for group in self.jan_groups:
            if group.jan == "unknown":
                continue
            has_assignable = True
            title = self._get_product_title_by_jan(group.jan)
            label = f"{group.jan}"
            if title:
                label += f" - {title}"
            action = assign_menu.addAction(label)
            jan_value = group.jan
            action.triggered.connect(lambda _, j=jan_value, path=image_path: self.assign_image_to_jan(path, j, show_message=True))
        if not has_assignable:
            assign_menu.setEnabled(False)
        
        menu.exec_(self.image_list.mapToGlobal(position))


    def delete_image_from_list(self, item: QListWidgetItem):
        """画像一覧から画像を削除（ファイルも削除）"""
        image_path = item.data(Qt.UserRole)
        if not image_path:
            return

        file_name = Path(image_path).name
        reply = QMessageBox.question(
            self,
            "削除の確認",
            f"画像ファイル '{file_name}' を完全に削除しますか？\n\nこの操作は元に戻せません。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # 1. ファイルを物理的に削除
                if os.path.exists(image_path):
                    os.remove(image_path)

                # 2. データベースから削除
                self.image_db.delete_by_file_path(image_path)

                # 3. メモリ上のデータから削除
                record = next((r for r in self.image_records if r.path == image_path), None)
                original_jan = record.jan_candidate if record and record.jan_candidate else None
                self.image_records = [r for r in self.image_records if r.path != image_path]

                # 4. UIを更新
                self.jan_groups = self.image_service.group_by_jan(self.image_records)
                if original_jan:
                    self._jan_title_cache.pop(original_jan, None)

                self.update_tree_widget()
                self.update_image_list(self.image_records)

                # 5. 詳細パネルをクリア
                if self.selected_image_path == image_path:
                    self.selected_image_path = None
                    self._clear_image_preview_panels()
                    self.jan_edit.clear()
                    self.capture_time_label.setText("-")
                    self.file_name_label.setText("-")
                    self.file_size_label.setText("-")
                    self.rotate_left_btn.setEnabled(False)
                    self.rotate_right_btn.setEnabled(False)
                    self.read_barcode_btn.setEnabled(False)
                    self.save_jan_btn.setEnabled(False)
                
                QMessageBox.information(self, "完了", f"画像 '{file_name}' を削除しました。")

            except Exception as e:
                QMessageBox.critical(self, "エラー", f"画像の削除中にエラーが発生しました:\n{str(e)}")


