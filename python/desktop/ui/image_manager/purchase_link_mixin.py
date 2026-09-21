#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入DB紐付け・候補 mixin。"""
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
    first_image_capture_dt,
    resolve_link_image_paths,
    _apply_unlinked_item_style,
    _record_jan_matches_group,
    _candidate_is_known_linked_product,
    _candidate_should_highlight_in_dialog,
    _format_status_prefix_html,
    _format_workflow_pipeline_html,
)

class ImageManagerPurchaseLinkMixin:
    def _is_group_linked_to_purchase_db(
        self,
        group: JanGroup,
        all_records: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """JANグループの画像が仕入DBの画像列に1枚以上登録済みか"""
        if not group or not group.images:
            return False
        if group.jan == "unknown":
            return False
        image_paths = {
            _normalize_image_path(p) for p in self._group_image_paths(group)
        }
        if not image_paths:
            return False
        if all_records is None:
            if not self.product_widget:
                return False
            self._ensure_product_widget_data_loaded()
            try:
                all_records = self.product_widget.get_all_purchase_records()
            except Exception:
                return False
        return any(_record_has_any_image_paths(rec, image_paths) for rec in all_records)


    def _group_has_jan_in_purchase_db(
        self,
        group: JanGroup,
        all_records: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """仕入DBに同一JANの商品レコードが存在するか（商品名表示と同じ基準）"""
        if not group or group.jan == "unknown":
            return False
        jan_norm = _normalize_jan_for_match(group.jan)
        if not jan_norm:
            return False
        if all_records is None:
            if not self.product_widget:
                return False
            self._ensure_product_widget_data_loaded()
            try:
                all_records = self.product_widget.get_all_purchase_records()
            except Exception:
                return False
        for record in all_records:
            record_jan = _normalize_jan_for_match(
                record.get("JAN") or record.get("jan") or record.get("JANコード")
            )
            if record_jan and record_jan == jan_norm:
                return True
        return False


    def _should_highlight_jan_group(
        self,
        group: JanGroup,
        all_records: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """JANグループを黄色表示するか（JAN不明、または仕入DBに商品未紐付け）"""
        if not group or group.jan == "unknown":
            return True
        if self._is_group_linked_to_purchase_db(group, all_records):
            return False
        if self._group_has_jan_in_purchase_db(group, all_records):
            return False
        return True


    def _collect_linked_jan_codes_from_groups(self) -> set[str]:
        """画像一覧でJAN+商品名が紐付いているJANグループのJANコード集合"""
        purchase_records: Optional[List[Dict[str, Any]]] = None
        if self.product_widget:
            try:
                self._ensure_product_widget_data_loaded()
                purchase_records = self.product_widget.get_all_purchase_records()
            except Exception:
                purchase_records = None
        linked: set[str] = set()
        for group in self.jan_groups:
            if self._group_has_jan_in_purchase_db(group, purchase_records):
                norm = _normalize_jan_for_match(group.jan)
                if norm:
                    linked.add(norm)
        return linked


    def _finalize_purchase_db_after_image_link(self) -> None:
        """
        画像パス更新後の永続化（メモリ同期＋スナップショット）。
        仕入DBタブのテーブルは構築済みのときだけ再描画する（未表示時の全行再描画を避けて高速化）。
        """
        if not self.product_widget:
            return
        pw = self.product_widget
        try:
            pw.sync_purchase_master_from_records()
            pw.save_purchase_snapshot()
            pw.refresh_purchase_table_if_built()
        except Exception as e:
            logger.warning(f"仕入DBの保存後更新に失敗しました: {e}")


    def _ensure_product_widget_data_loaded(self, full: bool = False) -> None:
        """
        データベース管理タブを開かなくても仕入DB（purchase_all_records）を参照できるようにする。

        full=False（既定）: スナップショットのみ読み込み（画像管理の紐付け用・高速）
        full=True: テーブル描画まで含む完全読み込み（確定処理など）
        """
        if not self.product_widget:
            return
        try:
            pw = self.product_widget
            if full:
                was_loaded = getattr(pw, "_initial_data_loaded", False)
                pw.ensure_initial_data_loaded()
                if getattr(pw, "_initial_data_loaded", False) and not was_loaded:
                    self._jan_title_cache.clear()
            else:
                was_loaded = (
                    getattr(pw, "_purchase_lookup_loaded", False)
                    or getattr(pw, "_initial_data_loaded", False)
                )
                pw.ensure_purchase_records_for_lookup()
                if getattr(pw, "purchase_all_records", None) and not was_loaded:
                    self._jan_title_cache.clear()
        except Exception as e:
            logger.warning("仕入DBの先行読み込みに失敗しました: %s", e)


    def _search_sku_candidates_by_jan(self, jan: str) -> List[Dict[str, Any]]:
        """仕入DBからJANコードでSKU候補を検索"""
        if not self.product_widget or not jan:
            return []

        self._ensure_product_widget_data_loaded()
        
        try:
            # purchase_all_recordsからJANコードで検索
            candidates = []
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            
            for record in purchase_records:
                record_jan = str(record.get("JAN") or record.get("jan") or "").strip()
                if record_jan.upper() == jan.upper():
                    candidates.append(record)
            
            return candidates
        except Exception as e:
            logger.warning(f"SKU候補検索エラー: {e}")
            return []


    def _get_product_title_by_jan(self, jan: str) -> str:
        """JANコードに紐づく候補商品タイトルを取得"""
        if not jan or jan == "unknown":
            return ""

        self._ensure_product_widget_data_loaded()
        
        if jan in self._jan_title_cache:
            return self._jan_title_cache[jan]
        
        title = ""
        try:
            if self.product_widget:
                purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                for record in purchase_records:
                    record_jan = _normalize_jan_for_match(
                        record.get("JAN") or record.get("jan") or record.get("JANコード")
                    )
                    if record_jan and record_jan == _normalize_jan_for_match(jan):
                        title = (
                            record.get("商品名") or
                            record.get("product_name") or
                            record.get("title") or
                            ""
                        )
                        if title:
                            break
        except Exception as e:
            logger.warning(f"商品タイトル取得エラー: {e}")
            title = ""
        
        self._jan_title_cache[jan] = title
        return title


    def confirm_image_links(self):
        """JANグループエリアに登録されている全てのJANグループの画像パスを仕入DBに登録（既に登録済みはスキップ）"""
        if not self.product_widget:
            QMessageBox.warning(self, "エラー", "データベース管理タブが見つかりません。")
            return

        self._ensure_product_widget_data_loaded()

        # 有効なJANグループを抽出（JAN不明グループは除外）
        valid_groups = [g for g in self.jan_groups if g.jan != "unknown" and g.images]

        if not valid_groups:
            QMessageBox.information(self, "情報", "確定処理対象のJANグループがありません。")
            return

        # 常に最新のレコードリストを取得
        all_records = self.product_widget.get_all_purchase_records()

        # プログレスダイアログを表示
        # 最後の「仕入DB表示更新/スナップ保存」も1ステップとして含め、
        # 進捗バー完了と完了メッセージ表示タイミングを揃える。
        total_steps = len(valid_groups) + 1
        progress = QProgressDialog("確定処理中...", "キャンセル", 0, total_steps, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        success_count = 0
        skipped_count = 0
        failed_groups = []

        try:
            for i, group in enumerate(valid_groups):
                if progress.wasCanceled():
                    break

                progress.setValue(i)
                progress.setLabelText(f"確定処理中... ({i+1}/{len(valid_groups)}) - JAN: {group.jan}")
                QApplication.processEvents()

                jan = group.jan
                image_paths = self._collect_image_paths_for_group(group)

                if not image_paths:
                    continue

                try:
                    # 対象SKUを取得
                    target_sku = self._get_target_sku_for_group(group, all_records)
                    
                    # 更新処理を実行（既存画像をクリアしてから新しい画像で上書き）
                    success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                        jan,
                        image_paths,
                        all_records,
                        skip_existing=False,
                        target_sku=target_sku,
                        clear_existing=True,
                        defer_table_refresh_and_snapshot=True,
                    )

                    if success:
                        if added_count > 0:
                            success_count += 1
                            skipped = len(image_paths) - added_count
                            if skipped > 0:
                                skipped_count += skipped
                        else:
                            skipped_count += len(image_paths)
                        # 既に登録済みでも画像登録タブに反映するため、record_snapshotがあれば追加
                        if record_snapshot:
                            self.add_registration_entry(
                                record_snapshot,
                                skip_barcode_classification=self._is_group_first_image_excluded(group),
                            )
                    else:
                        failed_groups.append(jan)

                except Exception as e:
                    logger.error(f"JAN '{jan}' の確定処理中にエラー: {e}")
                    failed_groups.append(jan)

            # JANグループ処理が完了した段階（最終ステップの直前）
            progress.setValue(len(valid_groups))
            progress.setLabelText("確定処理中... 仕入DB表示を更新しています")
            QApplication.processEvents()

            # 各JANごとにテーブル全再描画・スナップショット保存していたため極端に遅かった。一括で1回だけ行う。
            try:
                pw = self.product_widget
                pw.purchase_records = list(pw.purchase_all_records)
                pw.populate_purchase_table(pw.purchase_records)
                pw.update_purchase_count_label()
                pw.save_purchase_snapshot()
            except Exception as e:
                logger.warning(f"確定処理後の仕入DB表示更新に失敗しました: {e}")
            finally:
                progress.setValue(total_steps)
                QApplication.processEvents()
                progress.close()

            # 結果メッセージを表示
            message_parts = []
            if success_count > 0:
                message_parts.append(f"{success_count}件のJANグループを確定処理しました。")
                if skipped_count > 0:
                    message_parts.append(f"（{skipped_count}件の画像は既に登録済みのためスキップしました）")
            if failed_groups:
                message_parts.append(f"\n以下のJANグループの処理に失敗しました:\n{', '.join(failed_groups)}")

            self.update_tree_widget()
            if message_parts:
                QMessageBox.information(self, "確定処理完了", "\n".join(message_parts))
            else:
                QMessageBox.information(self, "確定処理完了", "処理が完了しました。")

        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "エラー", f"確定処理中にエラーが発生しました:\n{e}")


    def _selected_image_paths_from_list(self) -> List[str]:
        paths: List[str] = []
        image_list = getattr(self, "image_list", None)
        if image_list is None:
            return paths
        for item in image_list.selectedItems():
            path = item.data(Qt.UserRole)
            if path:
                paths.append(str(path))
        return paths

    def _find_jan_group_by_jan(self, jan: Optional[str]) -> Optional[JanGroup]:
        if not jan:
            return None
        jan_norm = _normalize_jan_for_match(jan) if jan != "unknown" else "unknown"
        for group in getattr(self, "jan_groups", None) or []:
            if group.jan == jan or _normalize_jan_for_match(group.jan) == jan_norm:
                return group
        return None

    def _find_jan_group_for_path(self, image_path: str) -> Optional[JanGroup]:
        """画像パスが属するJANグループを、最新の jan_groups から返す。"""
        if not image_path:
            return None
        target = _normalize_image_path(image_path)
        for group in getattr(self, "jan_groups", None) or []:
            for rec in group.images or []:
                if rec.path == image_path or _normalize_image_path(rec.path) == target:
                    return group
        return None

    def _resolve_live_jan_group(
        self,
        group: Optional[JanGroup] = None,
        image_path: Optional[str] = None,
        tree_item: Optional[QTreeWidgetItem] = None,
    ) -> Optional[JanGroup]:
        """
        ツリーに保存した JanGroup は images が空になることがある。
        必ず self.jan_groups の実体を使う。
        """
        if image_path:
            found = self._find_jan_group_for_path(image_path)
            if found and found.images:
                return found

        jan = None
        if group is not None:
            jan = getattr(group, "jan", None)
            if group.images:
                found = self._find_jan_group_by_jan(jan) or group
                if found and found.images:
                    return found

        if tree_item is not None:
            data = tree_item.data(0, Qt.UserRole)
            extra_jan = tree_item.data(0, int(Qt.UserRole) + 1)
            if isinstance(extra_jan, str) and extra_jan:
                jan = extra_jan
            if isinstance(data, JanGroup):
                jan = jan or data.jan
            elif isinstance(data, str):
                found = self._find_jan_group_for_path(data)
                if found and found.images:
                    return found
            found = self._find_jan_group_by_jan(jan)
            if found and found.images:
                return found
            # 子ノードの画像パスから探す
            for i in range(tree_item.childCount()):
                child_path = tree_item.child(i).data(0, Qt.UserRole)
                if isinstance(child_path, str) and child_path:
                    found = self._find_jan_group_for_path(child_path)
                    if found and found.images:
                        return found
            parent = tree_item.parent()
            if parent:
                return self._resolve_live_jan_group(tree_item=parent)

        return None

    def _link_purchase_from_current_image(self):
        """表示中・選択中の画像からJANグループを特定して仕入DB候補紐付けを開く。"""
        paths = self._selected_image_paths_from_list()
        path = (paths[0] if paths else None) or getattr(self, "selected_image_path", None)
        group = self._resolve_live_jan_group(
            group=getattr(self, "selected_group", None),
            image_path=path,
        )
        if not group or not group.images:
            current = self.tree_widget.currentItem() if getattr(self, "tree_widget", None) else None
            if current:
                group = self._resolve_live_jan_group(tree_item=current)
        if not group or not group.images:
            QMessageBox.information(
                self,
                "情報",
                "紐付け対象のJANグループが見つかりませんでした。\n"
                "中央の画像を選ぶか、左のJANグループを選んでから再実行してください。",
            )
            return
        self.show_purchase_candidates_for_group(group, image_paths=paths)

    def show_purchase_candidates_for_group(
        self,
        group: JanGroup,
        image_paths: Optional[List[str]] = None,
        prefer_selected: bool = True,
    ):
        """
        撮影日時に近い仕入DBレコード候補を表示して手動で紐付ける。
        中央リストで画像が選ばれているときは、選んだ画像だけを付け替える。
        """
        if not self.product_widget:
            QMessageBox.warning(self, "エラー", "仕入DBタブ（商品データベース）への参照がありません。")
            return

        live = self._resolve_live_jan_group(group=group)
        if live:
            group = live

        if not group or not group.images:
            QMessageBox.information(self, "情報", "画像が含まれていないJANグループです。")
            return

        group_paths = [img.path for img in group.images if img.path]
        selected_paths = list(image_paths or [])
        if prefer_selected and not selected_paths:
            selected_paths = self._selected_image_paths_from_list()
        link_paths = resolve_link_image_paths(selected_paths, group_paths)
        if not link_paths:
            QMessageBox.information(self, "情報", "紐付けする画像がありません。")
            return
        subset = len(link_paths) < len(group_paths)

        path_map = {_normalize_image_path(img.path): img for img in group.images if img.path}
        link_records = []
        for path in link_paths:
            rec = path_map.get(_normalize_image_path(path))
            if rec:
                link_records.append(rec)
        if not link_records:
            link_records = list(group.images)

        # 選んだ画像（なければグループ1枚目）の撮影日時を基準にする
        first = link_records[0]
        base_dt = first_image_capture_dt(link_records)
        if not base_dt:
            base_dt = self.image_service.get_exif_datetime(first.path)
        if not base_dt:
            for record in link_records[1:]:
                base_dt = record.capture_dt or self.image_service.get_exif_datetime(record.path)
                if base_dt:
                    break

        if not base_dt:
            QMessageBox.warning(self, "エラー", "選択画像から撮影日時を取得できませんでした。")
            return

        progress = QProgressDialog("仕入DB候補を検索中...", None, 0, 0, self)
        progress.setWindowTitle("仕入DB候補")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        # 画像撮影日時 ±7日以内の仕入DB候補を取得（軽量読み込み）
        search_jan = group.jan if group.jan and group.jan != "unknown" else None
        if not search_jan and first.jan_candidate and first.jan_candidate != "unknown":
            search_jan = first.jan_candidate
        try:
            self._ensure_product_widget_data_loaded(full=False)
            candidates = self.product_widget.find_purchase_candidates_by_datetime(
                base_dt,
                days_window=7,
                jan=search_jan,
            )
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"仕入DB候補の取得中にエラーが発生しました:\n{e}")
            return
        finally:
            progress.close()

        if not candidates:
            QMessageBox.information(
                self,
                "候補なし",
                "撮影日時付近の仕入データ候補が見つかりませんでした。\n"
                "（仕入DBの取り込み状況や日付を確認してください）",
            )
            return

        dialog = PurchaseCandidateDialog(
            group,
            base_dt,
            candidates,
            group_image_paths=self._group_image_paths(group),
            linked_session_jans=self._collect_linked_jan_codes_from_groups(),
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted or not dialog.selected_record:
            return

        selected = dialog.selected_record
        target_jan = str(selected.get("JAN") or selected.get("jan") or "").strip()
        target_sku = str(selected.get("SKU") or selected.get("sku") or "").strip()

        if not target_jan:
            reply = QMessageBox.question(
                self,
                "確認",
                "選択した仕入レコードにはJANが設定されていません。\n"
                "それでもこのレコードに画像を紐付けますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        progress = QProgressDialog("仕入DBへ紐付け中...", None, 0, 0, self)
        progress.setWindowTitle("紐付け処理")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        try:
            all_records = self.product_widget.get_all_purchase_records()
            try:
                self.product_widget.remove_image_paths_from_purchase_records(
                    link_paths,
                    all_records,
                    keep_sku=target_sku or None,
                )
            except Exception as e:
                logger.warning("旧レコードからの画像パス解除に失敗: %s", e)
            success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                target_jan,
                link_paths,
                all_records,
                skip_existing=True,
                target_sku=target_sku or None,
                defer_table_refresh_and_snapshot=True,
            )
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "エラー", f"画像パスの紐付け中にエラーが発生しました:\n{e}")
            return
        finally:
            progress.close()

        if not success:
            QMessageBox.warning(
                self,
                "紐付け失敗",
                "選択したJANに対応する仕入レコードが見つかりませんでした。\n"
                "（仕入DB側のJANを確認してください）",
            )
            return

        first_group_path = group.images[0].path if group.images else ""
        moving_first = _normalize_image_path(first_group_path) in {
            _normalize_image_path(p) for p in link_paths
        }
        skip_barcode = moving_first and self._is_group_first_image_excluded(group)
        if record_snapshot:
            self.add_registration_entry(
                record_snapshot,
                skip_barcode_classification=skip_barcode,
            )

        self._finalize_purchase_db_after_image_link()

        # 選択画像だけ別JANへ移す。グループ全体のときは確認してから全画像を更新する。
        if target_jan and group.jan != target_jan:
            if subset:
                for path in link_paths:
                    self.assign_image_to_jan(path, target_jan, refresh_tree=False)
                self.jan_groups = self.image_service.group_by_jan(self.image_records)
                self._jan_title_cache.pop(target_jan, None)
            else:
                reply = QMessageBox.question(
                    self,
                    "JANグループJAN更新の確認",
                    f"このJANグループのJANを仕入DBのJAN {target_jan} に更新しますか？\n"
                    f"（グループ内の全画像が新しいJANで再グルーピングされます）",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    for img_record in list(group.images):
                        self.assign_image_to_jan(
                            img_record.path, target_jan, refresh_tree=False
                        )
                    self.jan_groups = self.image_service.group_by_jan(self.image_records)
                    self._jan_title_cache.pop(target_jan, None)

        try:
            self._jan_title_cache.clear()
        except Exception:
            self._jan_title_cache = {}
        self.update_tree_widget()
        if subset:
            msg = f"選択した {len(link_paths)} 枚だけを仕入DBレコードに紐付けました。"
        else:
            msg = "仕入DBレコードと画像グループを紐付けました。"
        if added_count > 0:
            msg += f"\n新しく登録された画像数: {added_count}枚"
        else:
            msg += "\nすべての画像は既に仕入DB側に登録済みでした。"

        QMessageBox.information(self, "完了", msg)


    def manual_link_by_purchase_date(self):
        """
        仕入DBの「仕入れ日」をユーザーが指定して、
        スキャン済みのJANグループ全体を仕入レコードに一括紐付けする。

        - スキャン時の自動紐付け（撮影日時ベース）で紐付かなかったケースを補うための機能
        - 「このフォルダの画像はこの日の仕入れだはず」という前提で、仕入日を基準に候補を絞り込む
        """
        if not self.product_widget:
            QMessageBox.warning(self, "エラー", "仕入DBタブ（商品データベース）への参照がありません。")
            return

        self._ensure_product_widget_data_loaded(full=False)

        if not getattr(self, "jan_groups", None):
            QMessageBox.information(self, "情報", "JANグループがありません。先にスキャンを実行してください。")
            return

        # 仕入DBから仕入日の候補一覧を作成（過去3ヶ月分に絞る）
        purchase_records = getattr(self.product_widget, "purchase_all_records", [])
        if not purchase_records:
            # 現在メモリに仕入データがない場合は、最新スナップショットから復元を試みる
            try:
                if hasattr(self.product_widget, "restore_latest_purchase_snapshot"):
                    self.product_widget.restore_latest_purchase_snapshot()
                    purchase_records = getattr(self.product_widget, "purchase_all_records", [])
            except Exception:
                purchase_records = getattr(self.product_widget, "purchase_all_records", [])

        if not purchase_records:
            QMessageBox.warning(self, "情報", "照合対象の仕入データがありません。仕入データベースの内容を確認してください。")
            return

        from datetime import date as _Date, datetime as _DateTime, timedelta as _Timedelta

        today = _Date.today()
        cutoff = today - _Timedelta(days=90)  # 過去3ヶ月分のみ

        date_map: Dict[str, _Date] = {}
        for record in purchase_records:
            raw_date = str(
                record.get("仕入れ日")
                or record.get("purchase_date")
                or ""
            ).strip()
            if not raw_date:
                continue

            # ProductWidget側の正規化ロジックを再利用（フォーマットの揺れを吸収）
            try:
                norm = self.product_widget._normalize_date_for_search(raw_date)  # type: ignore[attr-defined]
            except Exception:
                norm = ""
            if not norm:
                continue

            try:
                y, m, d = [int(x) for x in norm.split("-")[:3]]
                dt_obj = _Date(y, m, d)
            except Exception:
                continue

            # 過去3ヶ月より古い日付は候補から除外
            if dt_obj < cutoff:
                continue

            label = dt_obj.strftime("%Y/%m/%d")
            date_map[label] = dt_obj

        if not date_map:
            QMessageBox.warning(self, "情報", "仕入日の情報が存在しません。仕入データの「仕入れ日」を確認してください。")
            return

        # 新しい順に並べた日付リストを用意（最近の仕入日から選べるようにする）
        sorted_labels = sorted(date_map.keys(), reverse=True)

        # 日付選択ダイアログを表示
        dlg = QInputDialog(self)
        dlg.setWindowTitle("指定紐付け - 仕入日選択")
        dlg.setLabelText("このフォルダの画像を紐付ける基準となる仕入日を選択してください。")
        dlg.setComboBoxItems(sorted_labels)
        dlg.setComboBoxEditable(False)

        if dlg.exec_() != QDialog.Accepted:
            return

        selected_label = dlg.textValue().strip()
        if not selected_label or selected_label not in date_map:
            return

        base_date = date_map[selected_label]
        base_dt = _DateTime(base_date.year, base_date.month, base_date.day)

        # 選択した仕入日を基準に、±0日（=その日）の仕入レコードだけを対象にする
        try:
            day_candidates = self.product_widget.find_purchase_candidates_by_datetime(base_dt, days_window=0)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"仕入DB候補の取得中にエラーが発生しました:\n{e}")
            return

        if not day_candidates:
            QMessageBox.information(
                self,
                "候補なし",
                f"選択した仕入日（{selected_label}）に該当する仕入データ候補が見つかりませんでした。\n"
                "（仕入DBの取り込み状況や日付を確認してください）",
            )
            return

        # その日の候補レコードだけを all_records として扱う
        all_records = day_candidates

        # 対象となるJANグループ（JAN不明を除外）
        valid_groups = [g for g in self.jan_groups if g.jan != "unknown" and g.images]
        if not valid_groups:
            QMessageBox.information(self, "情報", "指定紐付け対象のJANグループがありません。")
            return

        # プログレスダイアログを表示
        progress = QProgressDialog("指定紐付け処理中...", "キャンセル", 0, len(valid_groups), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        success_count = 0
        skipped_count = 0
        failed_groups: List[str] = []

        try:
            for i, group in enumerate(valid_groups):
                if progress.wasCanceled():
                    break

                progress.setValue(i)
                progress.setLabelText(
                    f"指定紐付け処理中... ({i+1}/{len(valid_groups)}) - JAN: {group.jan} / 仕入日: {selected_label}"
                )
                QApplication.processEvents()

                jan = group.jan
                image_paths = self._collect_image_paths_for_group(group)

                if not image_paths:
                    continue

                try:
                    # 対象SKUを取得（その日の仕入レコードの範囲内で絞り込む）
                    target_sku = self._get_target_sku_for_group(group, all_records)

                    # 更新処理を実行（既存画像は維持しつつ、新しい画像だけ追加）
                    success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                        jan,
                        image_paths,
                        all_records,
                        skip_existing=True,
                        target_sku=target_sku,
                        clear_existing=False,
                    )

                    if success:
                        if added_count > 0:
                            success_count += 1
                            skipped = len(image_paths) - added_count
                            if skipped > 0:
                                skipped_count += skipped
                        else:
                            skipped_count += len(image_paths)
                        if record_snapshot:
                            self.add_registration_entry(
                                record_snapshot,
                                skip_barcode_classification=self._is_group_first_image_excluded(group),
                            )
                    else:
                        failed_groups.append(jan)

                except Exception as e:
                    logger.error(f"JAN '{jan}' の指定紐付け処理中にエラー: {e}")
                    failed_groups.append(jan)

            progress.close()

            # 結果メッセージ
            message_parts: List[str] = []
            if success_count > 0:
                message_parts.append(
                    f"{success_count}件のJANグループを仕入日 {selected_label} の仕入レコードに紐付けました。"
                )
                if skipped_count > 0:
                    message_parts.append(f"（{skipped_count}件の画像は既に登録済みのためスキップしました）")
            if failed_groups:
                message_parts.append(
                    "\n以下のJANグループの処理に失敗しました（仕入日やJANを確認してください）:\n"
                    + ", ".join(failed_groups)
                )

            if message_parts:
                QMessageBox.information(self, "指定紐付け完了", "\n".join(message_parts))
            else:
                QMessageBox.information(self, "指定紐付け完了", "処理が完了しました。")

            # 仕入DB側に商品名などが入ったので、JAN→タイトルのキャッシュをクリアしてツリーを再描画
            try:
                self._jan_title_cache.clear()
            except Exception:
                self._jan_title_cache = {}
            self.update_tree_widget()

        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "エラー", f"指定紐付け処理中にエラーが発生しました:\n{e}")


