#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GCSアップロード mixin。"""
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

class ImageManagerGcsMixin:
    def force_upload_single_image_to_gcs(self, row: int, image_idx: int):
        """
        画像1〜6セルを右クリックしたときに呼び出される、
        単一画像のGCS「強制」アップロード処理。

        - バーコードかどうかの判定は一切行わない
        - 既にURLが入っていても上書きしたい場合に使える
        """
        if row >= len(self.registration_records):
            return

        # 対象セルからローカル画像パスを取得
        column = 5 + image_idx  # 画像1〜6列
        item = self.registration_table.item(row, column)
        if not item:
            QMessageBox.warning(self, "エラー", "画像パスが見つかりません。")
            return

        image_path = item.data(Qt.UserRole)
        if not image_path:
            QMessageBox.warning(self, "エラー", "画像パスが設定されていません。")
            return

        image_path = str(image_path)
        if not Path(image_path).exists():
            QMessageBox.warning(self, "エラー", f"画像ファイルが見つかりません:\n{image_path}")
            return

        entry = self.registration_records[row]
        sku = entry.get("sku") or ""

        # 確認ダイアログ
        reply = QMessageBox.question(
            self,
            "GCS強制アップロード",
            f"この画像をGCSに強制アップロードしますか？\n\n"
            f"SKU: {sku or '（未設定）'}\n"
            f"画像: {Path(image_path).name}\n\n"
            f"※ バーコード画像かどうかに関係なくアップロードします。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # gcs_uploaderの読み込み（通常アップロードと同等の処理を簡略化）
        try:
            import sys
            import os
            import importlib.util

            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            # ui/image_manager/ → python/ は3階層上（分割前は2階層）
            python_dir = os.path.abspath(os.path.join(current_file_dir, "..", "..", ".."))
            desktop_dir = os.path.abspath(os.path.join(current_file_dir, "..", ".."))
            candidate_paths = [
                python_dir,
                desktop_dir,
                os.path.join(python_dir, "python"),
                os.path.join(desktop_dir, "python"),
            ]

            found_path = None
            for candidate in candidate_paths:
                gcs_uploader_path = os.path.join(candidate, "utils", "gcs_uploader.py")
                if os.path.exists(gcs_uploader_path):
                    found_path = candidate
                    break

            if found_path:
                if found_path in sys.path:
                    sys.path.remove(found_path)
                sys.path.insert(0, found_path)
                sys.path[0] = found_path

                gcs_uploader_file = os.path.join(found_path, "utils", "gcs_uploader.py")
                if not os.path.exists(gcs_uploader_file):
                    raise ImportError(f"gcs_uploader.py not found at {gcs_uploader_file}")

                spec = importlib.util.spec_from_file_location("gcs_uploader", gcs_uploader_file)
                gcs_uploader_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gcs_uploader_module)
                upload_image_to_gcs = gcs_uploader_module.upload_image_to_gcs
                GCS_AVAILABLE = gcs_uploader_module.GCS_AVAILABLE
                check_gcs_authentication = gcs_uploader_module.check_gcs_authentication
                find_existing_public_url_for_local_file = getattr(
                    gcs_uploader_module, "find_existing_public_url_for_local_file", None
                )
            else:
                from utils.gcs_uploader import upload_image_to_gcs, GCS_AVAILABLE, check_gcs_authentication
                try:
                    from utils.gcs_uploader import find_existing_public_url_for_local_file
                except Exception:
                    find_existing_public_url_for_local_file = None

            if not GCS_AVAILABLE:
                QMessageBox.critical(
                    self,
                    "エラー",
                    "google-cloud-storageがインストールされていません。\n"
                    "pip install google-cloud-storage を実行してください。",
                )
                return

            auth_success, auth_error = check_gcs_authentication()
            if not auth_success:
                QMessageBox.critical(
                    self,
                    "認証エラー",
                    f"GCSへの認証に失敗しました。\n\n{auth_error}\n\n"
                    f"サービスアカウントキーの設定を確認してください。",
                )
                return
        except ImportError as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"GCSアップロード機能の読み込みに失敗しました:\n\n{str(e)}",
            )
            return

        # 実際のアップロード処理（既存URLチェックも実施）
        try:
            if find_existing_public_url_for_local_file:
                try:
                    existing_url = find_existing_public_url_for_local_file(image_path)
                except Exception:
                    existing_url = None
                if existing_url:
                    public_url = existing_url
                else:
                    public_url = upload_image_to_gcs(image_path)
            else:
                public_url = upload_image_to_gcs(image_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "アップロード失敗",
                f"GCSへのアップロードに失敗しました:\n{e}",
            )
            logger.error(f"Force upload failed for {image_path}: {e}", exc_info=True)
            return

        # registration_records の image_urls を更新
        if "image_urls" not in entry:
            entry["image_urls"] = [""] * 5
        while len(entry["image_urls"]) <= image_idx:
            entry["image_urls"].append("")
        entry["image_urls"][image_idx] = public_url

        # テーブル（画像URL列）にも反映
        url_col_offset = 11
        url_col = url_col_offset + image_idx
        if url_col < self.registration_table.columnCount():
            url_item = self.registration_table.item(row, url_col)
            if url_item:
                url_item.setText(public_url)
            else:
                url_item = QTableWidgetItem(public_url)
                url_item.setFlags(url_item.flags() | Qt.ItemIsEditable)
                self.registration_table.setItem(row, url_col, url_item)

        # 仕入DB（purchase_db）の image_url_n も更新
        try:
            if sku:
                from database.purchase_db import PurchaseDatabase

                purchase_db = PurchaseDatabase()
                purchase_record = purchase_db.get_by_sku(sku)

                image_url_key = f"image_url_{image_idx + 1}"
                if purchase_record:
                    update_data = dict(purchase_record)
                    update_data[image_url_key] = public_url
                    purchase_db.upsert(update_data)
                else:
                    new_data = {"sku": sku, image_url_key: public_url}
                    purchase_db.upsert(new_data)
        except Exception as e:
            logger.warning(f"Failed to update purchase DB for SKU {sku or 'N/A'}: {e}")

        QMessageBox.information(
            self,
            "アップロード完了",
            f"画像をGCSにアップロードしました。\n\n"
            f"SKU: {sku or '（未設定）'}\n"
            f"画像URL: {public_url}",
        )


    def upload_images_to_gcs(self):
        """選択行（未選択の場合は確認後に全行）の商品画像をGCSにアップロード"""
        return self._upload_images_to_gcs_impl(force_all=False)


    def upload_all_images_to_gcs(self):
        """全行の商品画像をGCSにアップロード"""
        return self._upload_images_to_gcs_impl(force_all=True)


    def _upload_images_to_gcs_impl(self, force_all: bool = False):
        """GCSアップロードの共通実装（force_all=Trueで全行）"""
        if not self.registration_records:
            QMessageBox.warning(self, "警告", "登録されている商品がありません。")
            return
        
        # 保存期間（日）は画像登録タブ右上の「GCS保存期間（日）」で設定。0=無期限。
        retention_days = self.gcs_retention_days_spinbox.value()
        try:
            settings = QSettings("HIRIO", "SedoriDesktopApp")
            settings.setValue("image_manager/gcs_retention_days", retention_days)
        except Exception:
            pass
        
        # 対象行を決定
        if force_all:
            selected_rows = set(range(len(self.registration_records)))
        else:
            # 選択行を取得（選択がない場合は確認して全行）
            selected_rows = set()
            for item in self.registration_table.selectedItems():
                selected_rows.add(item.row())
            
            if not selected_rows:
                reply = QMessageBox.question(
                    self,
                    "確認",
                    "選択された行がありません。全行の画像をアップロードしますか？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return
                selected_rows = set(range(len(self.registration_records)))
        
        # GCSアップロードユーティリティのインポート
        import sys
        import os
        # python/utils/gcs_uploader.py へのパスを追加
        # このファイルは python/desktop/ui/ 配下なので、2つ上の python/ をsys.pathに追加する
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        # ui/image_manager/ → python/ は3階層上（分割前は2階層）
        python_dir = os.path.abspath(os.path.join(current_file_dir, '..', '..', '..'))
        desktop_dir = os.path.abspath(os.path.join(current_file_dir, '..', '..'))

        # パス候補を複数試す（PyInstaller等で__file__が期待通りでない場合に対応）
        candidate_paths = [
            python_dir,  # ui/image_manager/ からの通常パス → python/
            desktop_dir,  # 互換
            os.path.join(python_dir, 'python'),
            os.path.join(desktop_dir, 'python'),
        ]
        
        # 実際にutils/gcs_uploader.pyが存在するパスを探す
        found_path = None
        try:
            for candidate in candidate_paths:
                gcs_uploader_path = os.path.join(candidate, 'utils', 'gcs_uploader.py')
                if os.path.exists(gcs_uploader_path):
                    found_path = candidate
                    break
            
            if found_path:
                # sys.pathの先頭を強制的にfound_pathに設定（他のコードが先頭を書き換えても確実にインポートできるように）
                # 既に存在する場合は削除してから先頭に追加
                if found_path in sys.path:
                    sys.path.remove(found_path)
                sys.path.insert(0, found_path)
                # さらに、sys.path[0]を強制的にfound_pathに設定（念のため）
                sys.path[0] = found_path
            elif python_dir:
                # found_pathが見つからない場合でも、python_dirを試す
                if python_dir in sys.path:
                    sys.path.remove(python_dir)
                sys.path.insert(0, python_dir)
                sys.path[0] = python_dir
            
            # インポート前にsys.pathの先頭を確認（デバッグ用）
            # logger.debug(f"Importing from sys.path[0]: {sys.path[0]}")
            
            # importlibを使って直接ファイルパスからインポート（sys.pathの問題を回避）
            if found_path:
                import importlib.util
                gcs_uploader_file = os.path.join(found_path, 'utils', 'gcs_uploader.py')
                if os.path.exists(gcs_uploader_file):
                    spec = importlib.util.spec_from_file_location("gcs_uploader", gcs_uploader_file)
                    gcs_uploader_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(gcs_uploader_module)
                    upload_image_to_gcs = gcs_uploader_module.upload_image_to_gcs
                    GCS_AVAILABLE = gcs_uploader_module.GCS_AVAILABLE
                    check_gcs_authentication = gcs_uploader_module.check_gcs_authentication
                    find_existing_public_url_for_local_file = getattr(
                        gcs_uploader_module, "find_existing_public_url_for_local_file", None
                    )
                    set_used_items_retention_days = getattr(
                        gcs_uploader_module, "set_used_items_retention_days", None
                    )
                else:
                    raise ImportError(f"gcs_uploader.py not found at {gcs_uploader_file}")
            else:
                # フォールバック: 通常のインポートを試す
                from utils.gcs_uploader import upload_image_to_gcs, GCS_AVAILABLE, check_gcs_authentication
                try:
                    from utils.gcs_uploader import find_existing_public_url_for_local_file
                except Exception:
                    find_existing_public_url_for_local_file = None
                try:
                    from utils.gcs_uploader import set_used_items_retention_days
                except Exception:
                    set_used_items_retention_days = None
            
            if not GCS_AVAILABLE:
                QMessageBox.critical(
                    self, "エラー",
                    "google-cloud-storageがインストールされていません。\n"
                    "pip install google-cloud-storage を実行してください。"
                )
                return
            
            # 認証確認
            auth_success, auth_error = check_gcs_authentication()
            if not auth_success:
                QMessageBox.critical(
                    self, "認証エラー",
                    f"GCSへの認証に失敗しました。\n\n{auth_error}\n\n"
                    f"サービスアカウントキーの設定を確認してください。"
                )
                return
            
            # 保存期間に応じてバケットのライフサイクル（N日後に削除）を設定（0＝無期限の場合は削除ルールを外す）
            if set_used_items_retention_days:
                try:
                    if not set_used_items_retention_days(retention_days):
                        logger.warning("Failed to set GCS lifecycle (used_items retention); continuing upload")
                except Exception as e:
                    logger.warning(f"Failed to set GCS lifecycle: {e}; continuing upload")
        except ImportError as e:
            # デバッグ情報を収集
            debug_info = []
            debug_info.append(f"エラー: {str(e)}")
            debug_info.append(f"現在のファイル: {__file__}")
            debug_info.append(f"計算されたpython_dir: {python_dir}")
            debug_info.append(f"見つかったfound_path: {found_path if found_path else 'None'}")
            debug_info.append(f"試したパス候補:")
            for candidate in candidate_paths:
                gcs_path = os.path.join(candidate, 'utils', 'gcs_uploader.py')
                exists = os.path.exists(gcs_path)
                debug_info.append(f"  - {candidate} (utils/gcs_uploader.py存在: {exists})")
            debug_info.append(f"sys.path[0] (インポート時に使用): {sys.path[0] if sys.path else '空'}")
            if found_path:
                gcs_uploader_file = os.path.join(found_path, 'utils', 'gcs_uploader.py')
                debug_info.append(f"importlibで使用するファイルパス: {gcs_uploader_file}")
                debug_info.append(f"ファイル存在確認: {os.path.exists(gcs_uploader_file)}")
            debug_info.append(f"sys.pathの先頭5件:")
            for i, path in enumerate(sys.path[:5]):
                marker = " ← これがインポート時に使用される" if i == 0 else ""
                debug_info.append(f"  {i+1}. {path}{marker}")
            
            QMessageBox.critical(
                self, "エラー",
                f"GCSアップロード機能の読み込みに失敗しました:\n\n{str(e)}\n\n"
                f"デバッグ情報:\n" + "\n".join(debug_info)
            )
            return
        
        # 進捗ダイアログ
        total_images = 0
        upload_tasks = []  # (row, entry, image_index, image_path)
        
        for row in selected_rows:
            if row >= len(self.registration_records):
                continue
            entry = self.registration_records[row]
            product_images = entry.get("product_images", [])
            
            for idx, image_path in enumerate(product_images):
                if image_path and Path(image_path).exists():
                    # 既にURLが設定されている場合はスキップ
                    existing_urls = entry.get("image_urls", [])
                    if idx < len(existing_urls) and existing_urls[idx]:
                        continue
                    upload_tasks.append((row, entry, idx, image_path))
                    total_images += 1
        
        if not upload_tasks:
            QMessageBox.information(
                self, "情報",
                "アップロード対象の画像がありません。\n"
                "（既にアップロード済み、または画像ファイルが見つかりません）"
            )
            return
        
        # アップロード前の最終確認（保存期間・件数を表示してOKで開始）
        retention_text = f"{retention_days}日後に削除" if retention_days > 0 else "無期限"
        reply = QMessageBox.question(
            self,
            "GCSアップロードの確認",
            f"以下の内容でGCSにアップロードします。よろしいですか？\n\n"
            f"・保存期間: {retention_text}\n"
            f"・アップロード対象: {len(upload_tasks)}件（{total_images}枚の画像）\n\n"
            f"OKでアップロードを開始、キャンセルで中止します。\n\n"
            f"※保存期間はタブ右上の「GCS保存期間（日）」で変更できます。",
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        if reply != QMessageBox.Ok:
            return
        
        # 進捗ダイアログ
        progress = QProgressDialog("GCSに画像をアップロード中...", "キャンセル", 0, total_images, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        
        uploaded_count = 0
        failed_count = 0
        errors = []
        
        try:
            for row, entry, image_idx, image_path in upload_tasks:
                if progress.wasCanceled():
                    break
                
                progress.setValue(uploaded_count + failed_count)
                progress.setLabelText(f"アップロード中: {Path(image_path).name}")
                QApplication.processEvents()
                
                try:
                    # 既にGCSに存在する場合は、アップロードせずURLを設定（重複アップロード防止）
                    if find_existing_public_url_for_local_file:
                        try:
                            existing_url = find_existing_public_url_for_local_file(image_path)
                        except Exception:
                            existing_url = None
                        if existing_url:
                            public_url = existing_url
                        else:
                            # 保存期間をメタデータとして付与（0=無期限）
                            metadata = None
                            if retention_days is not None and retention_days >= 0:
                                metadata = {"retention_days": str(retention_days)}
                            public_url = upload_image_to_gcs(image_path, metadata=metadata)
                    else:
                        # GCSにアップロード（保存期間メタデータ付き）
                        metadata = None
                        if retention_days is not None and retention_days >= 0:
                            metadata = {"retention_days": str(retention_days)}
                        public_url = upload_image_to_gcs(image_path, metadata=metadata)
                    
                    # entryのimage_urlsを更新
                    if "image_urls" not in entry:
                        entry["image_urls"] = [""] * 5
                    while len(entry["image_urls"]) <= image_idx:
                        entry["image_urls"].append("")
                    entry["image_urls"][image_idx] = public_url
                    
                    # テーブルに反映
                    col_offset = 11  # URL1列の開始位置
                    col = col_offset + image_idx
                    if col < self.registration_table.columnCount():
                        item = self.registration_table.item(row, col)
                        if item:
                            item.setText(public_url)
                        else:
                            item = QTableWidgetItem(public_url)
                            item.setFlags(item.flags() | Qt.ItemIsEditable)
                            self.registration_table.setItem(row, col, item)
                    
                    # 仕入DBの画像URLにも保存
                    try:
                        sku = entry.get("sku")
                        if sku:
                            from database.purchase_db import PurchaseDatabase
                            purchase_db = PurchaseDatabase()
                            purchase_record = purchase_db.get_by_sku(sku)
                            
                            if purchase_record:
                                # 既存レコードを更新
                                update_data = dict(purchase_record)
                                # image_idxは0始まりなので、image_url_1～6に保存（1始まりに変換）
                                image_url_key = f"image_url_{image_idx + 1}"
                                update_data[image_url_key] = public_url
                                purchase_db.upsert(update_data)
                                logger.info(f"Updated purchase DB image_url_{image_idx + 1} for SKU {sku}")
                            else:
                                # レコードが存在しない場合は新規作成（最小限の情報で）
                                new_data = {
                                    "sku": sku,
                                    f"image_url_{image_idx + 1}": public_url
                                }
                                purchase_db.upsert(new_data)
                                logger.info(f"Created new purchase DB record with image_url_{image_idx + 1} for SKU {sku}")
                    except Exception as e:
                        # 仕入DBへの保存に失敗してもアップロード処理は続行
                        logger.warning(f"Failed to update purchase DB for SKU {entry.get('sku', 'N/A')}: {e}")
                    
                    uploaded_count += 1
                    logger.info(f"Uploaded {image_path} -> {public_url}")
                
                except (ValueError, FileNotFoundError) as e:
                    # 認証エラーやファイルエラーの場合は処理を停止
                    failed_count += 1
                    error_msg = str(e)
                    errors.append(error_msg)
                    logger.error(f"Critical error during upload: {e}", exc_info=True)
                    
                    # 認証エラーの場合は即座に停止
                    if "認証エラー" in error_msg or "権限エラー" in error_msg or "authentication" in error_msg.lower():
                        progress.close()
                        QMessageBox.critical(
                            self, "認証エラー",
                            f"GCSへの認証に失敗しました。\n\n{error_msg}\n\n"
                            f"処理を中断しました。"
                        )
                        return
                
                except Exception as e:
                    failed_count += 1
                    error_msg = f"SKU {entry.get('sku', 'N/A')}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(f"Failed to upload {image_path}: {e}", exc_info=True)
            
            progress.setValue(total_images)
            
            # 仕入DBに保存
            try:
                from database.purchase_db import PurchaseDatabase
                purchase_db = PurchaseDatabase()
                
                for row in selected_rows:
                    if row >= len(self.registration_records):
                        continue
                    entry = self.registration_records[row]
                    sku = entry.get("sku")
                    if not sku:
                        continue
                    
                    # 仕入DBのレコードを取得
                    purchase_record = purchase_db.get_by_sku(sku)
                    if purchase_record:
                        # 画像URLを更新
                        update_data = {}
                        image_urls = entry.get("image_urls", [])
                        for i in range(5):
                            if i < len(image_urls) and image_urls[i]:
                                update_data[f"image_url_{i + 1}"] = image_urls[i]
                        
                        # バーコード画像URLも保存
                        if entry.get("barcode_image"):
                            # バーコード画像はアップロードしない（識別用のみ）
                            # 必要に応じてここでアップロードも可能
                            pass
                        
                        if update_data:
                            update_data["sku"] = sku
                            purchase_db.upsert(update_data)
                            logger.info(f"Updated purchase DB for SKU {sku} with image URLs")
            
            except Exception as e:
                logger.warning(f"Failed to save image URLs to purchase DB: {e}")
            
            # 結果表示
            result_msg = f"アップロード完了\n\n"
            result_msg += f"成功: {uploaded_count}件\n"
            if failed_count > 0:
                result_msg += f"失敗: {failed_count}件\n"
                if errors:
                    result_msg += "\nエラー詳細:\n" + "\n".join(errors[:5])
                    if len(errors) > 5:
                        result_msg += f"\n... 他 {len(errors) - 5}件"
            
            if failed_count > 0:
                QMessageBox.warning(self, "アップロード完了", result_msg)
            else:
                QMessageBox.information(self, "アップロード完了", result_msg)
        
        finally:
            progress.close()


    def check_existing_images_in_gcs(self):
        """GCSに既に存在する画像を検索して画像URL欄に反映（選択行/未選択なら全行）"""
        if not self.registration_records:
            QMessageBox.warning(self, "警告", "登録されている商品がありません。")
            return

        # 対象行（選択がなければ全行）
        selected_rows = set()
        for item in self.registration_table.selectedItems():
            selected_rows.add(item.row())
        if not selected_rows:
            selected_rows = set(range(len(self.registration_records)))

        # gcs_uploaderを読み込む（uploadと同じパス解決）
        try:
            import sys
            import os
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            python_dir = os.path.abspath(os.path.join(current_file_dir, '..', '..', '..'))
            desktop_dir = os.path.abspath(os.path.join(current_file_dir, '..', '..'))
            candidate_paths = [
                python_dir,
                desktop_dir,
                os.path.join(python_dir, 'python'),
                os.path.join(desktop_dir, 'python'),
            ]

            found_path = None
            for candidate in candidate_paths:
                gcs_uploader_path = os.path.join(candidate, 'utils', 'gcs_uploader.py')
                if os.path.exists(gcs_uploader_path):
                    found_path = candidate
                    break

            if found_path:
                if found_path in sys.path:
                    sys.path.remove(found_path)
                sys.path.insert(0, found_path)
                sys.path[0] = found_path

                import importlib.util
                gcs_uploader_file = os.path.join(found_path, 'utils', 'gcs_uploader.py')
                spec = importlib.util.spec_from_file_location("gcs_uploader", gcs_uploader_file)
                gcs_uploader_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gcs_uploader_module)
                GCS_AVAILABLE = gcs_uploader_module.GCS_AVAILABLE
                check_gcs_authentication = gcs_uploader_module.check_gcs_authentication
                find_existing_public_url_for_local_file = getattr(
                    gcs_uploader_module, "find_existing_public_url_for_local_file", None
                )
            else:
                from utils.gcs_uploader import GCS_AVAILABLE, check_gcs_authentication, find_existing_public_url_for_local_file

            if not GCS_AVAILABLE:
                QMessageBox.critical(
                    self, "エラー",
                    "google-cloud-storageがインストールされていません。\n"
                    "pip install google-cloud-storage を実行してください。"
                )
                return

            auth_success, auth_error = check_gcs_authentication()
            if not auth_success:
                QMessageBox.critical(
                    self, "認証エラー",
                    f"GCSへの認証に失敗しました。\n\n{auth_error}\n\n"
                    f"サービスアカウントキーの設定を確認してください。"
                )
                return
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"GCS存在チェック機能の初期化に失敗しました:\n{e}")
            return

        if not find_existing_public_url_for_local_file:
            QMessageBox.warning(self, "警告", "GCS存在チェック機能が利用できません（関数が見つかりません）。")
            return

        # 進捗
        tasks = []
        for row in sorted(selected_rows):
            if row >= len(self.registration_records):
                continue
            entry = self.registration_records[row]
            product_images = entry.get("product_images", [])
            existing_urls = entry.get("image_urls", []) if isinstance(entry.get("image_urls"), list) else []
            for idx, image_path in enumerate(product_images):
                if not image_path:
                    continue
                # URLが既に埋まっているならスキップ
                if idx < len(existing_urls) and existing_urls[idx]:
                    continue
                tasks.append((row, entry, idx, image_path))

        if not tasks:
            QMessageBox.information(self, "情報", "チェック対象がありません（既にURLが入っている、または画像がありません）。")
            return

        progress = QProgressDialog("GCSの既存画像を確認中...", "キャンセル", 0, len(tasks), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        found_count = 0
        try:
            from database.purchase_db import PurchaseDatabase
            purchase_db = PurchaseDatabase()

            for i, (row, entry, image_idx, image_path) in enumerate(tasks):
                if progress.wasCanceled():
                    break
                progress.setValue(i)
                progress.setLabelText(f"確認中: {Path(image_path).name}")
                QApplication.processEvents()

                url = find_existing_public_url_for_local_file(image_path)
                if not url:
                    continue

                # entry更新
                if "image_urls" not in entry:
                    entry["image_urls"] = [""] * 5
                while len(entry["image_urls"]) <= image_idx:
                    entry["image_urls"].append("")
                entry["image_urls"][image_idx] = url

                # テーブル反映（画像URL1～5は col_offset=11, +0..+4）
                col_offset = 11
                col = col_offset + image_idx
                if col < self.registration_table.columnCount():
                    self.registration_table.blockSignals(True)
                    try:
                        item = self.registration_table.item(row, col)
                        if item:
                            item.setText(url)
                        else:
                            item = QTableWidgetItem(url)
                            item.setFlags(item.flags() | Qt.ItemIsEditable)
                            self.registration_table.setItem(row, col, item)
                    finally:
                        self.registration_table.blockSignals(False)

                # 仕入DBへ保存（SKUがあれば）
                sku = entry.get("sku")
                if sku:
                    try:
                        purchase_db.upsert({"sku": sku, f"image_url_{image_idx + 1}": url})
                    except Exception:
                        pass

                found_count += 1

        finally:
            progress.close()

        QMessageBox.information(self, "完了", f"GCS存在チェック完了：URL反映 {found_count} 件")


