#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SKUリネーム mixin。"""
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

class ImageManagerRenameMixin:
    def _rename_progress_label(self) -> str:
        """リネーム進捗ダイアログ用のラベル文言"""
        parts: List[str] = []
        if self.auto_correct_rename_checkbox.isChecked():
            parts.append("補正")
        if self.lightweight_rename_checkbox.isChecked():
            parts.append("軽量化")
        if parts:
            return "リネーム・" + "・".join(parts) + "中..."
        return "リネーム処理中..."


    def _rename_image_file(self, source_path: str, dest_path: str) -> None:
        """チェックボックスに応じてリネーム（補正のみ／軽量化のみ／両方／通常）を実行"""
        self.image_service.rename_image_file(
            source_path,
            dest_path,
            lightweight=self.lightweight_rename_checkbox.isChecked(),
            auto_correct=self.auto_correct_rename_checkbox.isChecked(),
            auto_correct_preset=self._auto_correct_preset_id(),
        )


    def _resolve_sku_for_jan_group(self, group: JanGroup) -> Optional[str]:
        """JANグループに対応するSKUを仕入DB候補から選ぶ（撮影日時に最も近い仕入れ日を優先）。"""
        if not group.jan or group.jan == "unknown":
            return None

        image_capture_times = [
            record.capture_dt for record in group.images if record.capture_dt
        ]
        base_capture_dt = min(image_capture_times) if image_capture_times else None

        sku_candidates = self._search_sku_candidates_by_jan(group.jan)
        if not sku_candidates:
            return None

        sku = str(sku_candidates[0].get("SKU") or sku_candidates[0].get("sku") or "").strip()
        if not sku:
            return None

        if base_capture_dt and len(sku_candidates) > 1:
            for candidate in sku_candidates:
                purchase_date_str = str(
                    candidate.get("仕入れ日") or candidate.get("purchase_date") or ""
                )
                if purchase_date_str:
                    try:
                        date_str_clean = purchase_date_str.strip()
                        if " " in date_str_clean:
                            date_part, time_part = date_str_clean.split(" ", 1)
                            date_part = date_part.replace("/", "-")
                            datetime_str = f"{date_part} {time_part}"
                            try:
                                purchase_dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                            except Exception:
                                purchase_dt = datetime.strptime(date_part, "%Y-%m-%d")
                        else:
                            date_part = date_str_clean.replace("/", "-")
                            purchase_dt = datetime.strptime(date_part, "%Y-%m-%d")
                        candidate["_time_diff"] = abs(
                            (purchase_dt - base_capture_dt).total_seconds()
                        )
                    except Exception:
                        candidate["_time_diff"] = float("inf")
                else:
                    candidate["_time_diff"] = float("inf")
            sku_candidates.sort(key=lambda x: x.get("_time_diff", float("inf")))
            sku = str(
                sku_candidates[0].get("SKU") or sku_candidates[0].get("sku") or ""
            ).strip()

        return sku or None


    def _build_rename_plan_for_group(
        self, group: JanGroup, sku: str
    ) -> List[Tuple[ImageRecord, str]]:
        sorted_images = self._sorted_group_images(group)
        exclude_first = self._is_group_first_image_excluded(group)
        return plan_amazon_rename_targets(
            sorted_images,
            sku,
            exclude_first=exclude_first,
            path_getter=lambda r: r.path,
        )


    def _build_rerename_plan_for_group(
        self, group: JanGroup, sku: str
    ) -> List[Tuple[ImageRecord, str]]:
        sorted_images = self._sorted_group_images(group)
        exclude_first = self._is_group_first_image_excluded(group)
        return plan_amazon_rerename_targets(
            sorted_images,
            sku,
            exclude_first=exclude_first,
            path_getter=lambda r: r.path,
        )


    def _resolve_sku_for_group_rerename(self, group: JanGroup) -> Optional[str]:
        """再リネーム用に SKU を推定（仕入DB優先 → ファイル名）。"""
        sku = self._resolve_sku_for_jan_group(group)
        if sku:
            return sku
        sorted_images = self._sorted_group_images(group)
        return infer_sku_from_sorted_images(sorted_images, path_getter=lambda r: r.path)


    def _execute_rename_operations(
        self, rename_operations: List[Tuple[ImageRecord, str]]
    ) -> int:
        if not rename_operations:
            return 0

        progress = QProgressDialog(
            self._rename_progress_label(), "キャンセル", 0, len(rename_operations), self
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        renamed_count = 0
        new_records_map: Dict[str, ImageRecord] = {}

        for i, (record, new_path_str) in enumerate(rename_operations):
            progress.setValue(i)
            if progress.wasCanceled():
                break

            old_path_str = record.path
            try:
                self._rename_image_file(old_path_str, new_path_str)

                db_record = self.image_db.get_by_file_path(old_path_str)
                if db_record:
                    self.image_db.delete_by_file_path(old_path_str)
                    db_record["file_path"] = new_path_str
                    self.image_db.upsert(db_record)

                new_record_data = record._asdict()
                new_record_data["path"] = new_path_str
                new_records_map[old_path_str] = ImageRecord(**new_record_data)
                renamed_count += 1
            except Exception as e:
                logger.error(f"リネームエラー: {old_path_str} -> {new_path_str}: {e}")

        progress.close()

        if new_records_map:
            updated_image_records: List[ImageRecord] = []
            for rec in self.image_records:
                if rec.path in new_records_map:
                    updated_image_records.append(new_records_map[rec.path])
                else:
                    updated_image_records.append(rec)
            self.image_records = updated_image_records

            if self.first_image_flags:
                updated_flags: Dict[str, bool] = {}
                for old_path, new_record in new_records_map.items():
                    if old_path in self.first_image_flags:
                        updated_flags[new_record.path] = self.first_image_flags[old_path]
                for p, flag in self.first_image_flags.items():
                    if p not in new_records_map:
                        updated_flags[p] = flag
                self.first_image_flags = updated_flags

            self.jan_groups = self.image_service.group_by_jan(self.image_records)
            self.update_tree_widget()
            self.update_image_list(self.image_records)

        return renamed_count


    def _execute_rerename_operations(
        self, rename_operations: List[Tuple[ImageRecord, str]]
    ) -> int:
        """
        連番振り直し用リネーム（_2→_1 等の衝突を避けるため一時名を経由）。
        """
        if not rename_operations:
            return 0

        staging: List[Tuple[ImageRecord, str, str]] = []
        for record, final_path in rename_operations:
            parent = Path(final_path).parent
            token = uuid.uuid4().hex[:12]
            temp_path = str(parent / f".hirio_rerename_{token}_{Path(record.path).name}")
            staging.append((record, temp_path, final_path))

        phase1_ops = [(record, temp_path) for record, temp_path, _ in staging]
        renamed_count = self._execute_rename_operations(phase1_ops)
        if renamed_count != len(phase1_ops):
            logger.error(
                "連番振り直しの第1段階が不完全です (%s/%s)",
                renamed_count,
                len(phase1_ops),
            )
            return renamed_count

        path_to_record = {rec.path: rec for rec in self.image_records}
        phase2_ops: List[Tuple[ImageRecord, str]] = []
        for _record, temp_path, final_path in staging:
            current = path_to_record.get(temp_path)
            if current is None:
                logger.error(f"連番振り直し第2段階: 一時ファイルが見つかりません: {temp_path}")
                continue
            phase2_ops.append((current, final_path))

        if len(phase2_ops) != len(staging):
            logger.error(
                "連番振り直しの第2段階をスキップしました（一時ファイル %s 件が残る可能性があります）",
                len(staging) - len(phase2_ops),
            )
            return renamed_count

        return renamed_count + self._execute_rename_operations(phase2_ops)


    def rename_all_images(self):
        """すべてのJANグループの画像をSKUベース（{SKU}_1, _2…）で一括リネームする"""
        if not any(g for g in self.jan_groups if g.jan != "unknown"):
            QMessageBox.information(self, "情報", "リネーム対象のJANグループがありません。")
            return

        reply = QMessageBox.question(
            self,
            "リネーム確認",
            "すべてのJANグループの画像をSKUベース（例: SKU_1.jpg, SKU_2.jpg）で"
            "リネームしますか？\n\n"
            "・1枚目チェックONのグループ → 2枚目を _1 に\n"
            "・1枚目チェックOFFのグループ → 1枚目を _1 に\n"
            "連番がずれているグループ（_1 欠落など）は自動で振り直します。\n"
            "（既に {SKU}_数字 形式のファイルは通常リネームではスキップ）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        failed_skus: set[str] = set()
        rerename_count = 0
        groups_needing_rerename: List[Tuple[JanGroup, str]] = []

        for group in self.jan_groups:
            if group.jan == "unknown":
                continue

            sku = self._resolve_sku_for_group_rerename(group)
            if not sku:
                failed_skus.add(group.jan)
                continue

            sorted_images = self._sorted_group_images(group)
            exclude_first = self._is_group_first_image_excluded(group)
            if needs_amazon_sequence_rerename(
                sorted_images,
                sku,
                exclude_first=exclude_first,
                path_getter=lambda r: r.path,
            ):
                groups_needing_rerename.append((group, sku))

        for group, sku in groups_needing_rerename:
            rerename_ops = self._build_rerename_plan_for_group(group, sku)
            if rerename_ops:
                rerename_count += self._execute_rerename_operations(rerename_ops)

        rename_operations: List[Tuple[ImageRecord, str]] = []
        for group in self.jan_groups:
            if group.jan == "unknown":
                continue

            sku = self._resolve_sku_for_group_rerename(group)
            if not sku:
                continue

            rename_operations.extend(self._build_rename_plan_for_group(group, sku))

        renamed_count = 0
        if rename_operations:
            renamed_count = self._execute_rename_operations(rename_operations)

        total_count = rerename_count + renamed_count
        if total_count == 0:
            QMessageBox.information(self, "情報", "リネーム対象のファイルはありませんでした。")
            return

        message = f"{total_count}件の画像をリネームしました。"
        if rerename_count > 0:
            message += f"\n（うち {rerename_count} 件は _1 欠落などの連番振り直し）"
        if failed_skus:
            message += (
                "\n\n以下のJANコードに対応するSKUが見つからず、関連するグループはスキップされました:\n"
                + ", ".join(failed_skus)
            )
        QMessageBox.information(self, "完了", message)


    def _extract_sku_from_image_path(self, image_path: str) -> Optional[str]:
        """画像ファイル名からSKUを抽出（{SKU}_1 形式。Amazon形式も読み取り互換）。"""
        sku = _amazon_extract_sku_from_path(image_path)
        if sku:
            return sku
        logger.debug(f"SKU抽出できず: {image_path}")
        return None


    def _get_target_sku_for_group(self, group: JanGroup, all_records: List[Dict[str, Any]]) -> Optional[str]:
        """
        JANグループに対応するSKUを取得する
        
        1. 画像ファイル名からSKUを抽出を試みる
        2. 抽出できない場合は、仕入DBからJANで検索して、画像の撮影日時に最も近いSKUを取得
        
        Args:
            group: JANグループ
            all_records: 仕入DBの全レコード
            
        Returns:
            対象SKU、またはNone
        """
        jan_norm = str(group.jan).strip().upper()
        
        # 1. 画像ファイル名からSKUを抽出を試みる
        for img in group.images:
            sku = self._extract_sku_from_image_path(img.path)
            if sku:
                # 抽出したSKUが仕入DBに存在するか確認
                for record in all_records:
                    record_jan = str(record.get("JAN") or record.get("jan") or "").strip().upper()
                    record_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                    if record_sku == sku and record_jan == jan_norm:
                        return sku
        
        # 2. 画像ファイル名から抽出できない場合は、仕入DBからJANで検索
        # まず、JANで直接検索を試みる
        matching_records = []
        for record in all_records:
            record_jan = str(record.get("JAN") or record.get("jan") or "").strip().upper()
            if record_jan == jan_norm:
                record_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                if record_sku:
                    matching_records.append(record)
        
        if matching_records:
            # 画像の撮影日時を基準に最も近いレコードを選択
            if group.images:
                base_capture_dt = None
                for img in group.images:
                    if img.capture_dt:
                        if base_capture_dt is None or img.capture_dt < base_capture_dt:
                            base_capture_dt = img.capture_dt
                
                if base_capture_dt:
                    # 撮影日時に最も近いレコードを選択
                    best_record = None
                    min_time_diff = None
                    
                    for record in matching_records:
                        purchase_date_str = record.get("仕入日") or record.get("purchase_date") or ""
                        if purchase_date_str:
                            try:
                                purchase_dt = datetime.strptime(str(purchase_date_str), "%Y-%m-%d")
                                time_diff = abs((base_capture_dt - purchase_dt).total_seconds())
                                if min_time_diff is None or time_diff < min_time_diff:
                                    min_time_diff = time_diff
                                    best_record = record
                            except Exception:
                                pass
                    
                    if best_record:
                        target_sku = str(best_record.get("SKU") or best_record.get("sku") or "").strip()
                        if target_sku:
                            return target_sku
            
            # 撮影日時が取得できない、または時間差で判定できない場合は最初のレコードを使用
            if matching_records:
                target_sku = str(
                    matching_records[0].get("SKU") or matching_records[0].get("sku") or ""
                ).strip()
                if target_sku:
                    return target_sku
        
        return None


    def rename_images_for_group_with_sku(self, group: JanGroup):
        """
        指定したJANグループ内の画像を、ユーザーが入力したSKUベースでリネームする

        例: SKUが hmk-20251108-used2-029 の場合
            hmk-20251108-used2-029_1.jpg, hmk-20251108-used2-029_2.jpg, ...
        """
        if not group or not group.images:
            QMessageBox.information(self, "情報", "画像が含まれていないJANグループです。")
            return

        self._ensure_product_widget_data_loaded()

        # まずJANコードから仕入DBのSKU候補を検索
        sku = ""
        candidates = []
        if group.jan and group.jan != "unknown":
            candidates = self._search_sku_candidates_by_jan(group.jan)

        if candidates:
            # 「SKU - 商品名」の形で候補リストを作成
            items = []
            sku_map: Dict[str, str] = {}
            for record in candidates:
                cand_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                if not cand_sku:
                    continue
                name = (
                    record.get("商品名")
                    or record.get("product_name")
                    or record.get("title")
                    or ""
                )
                label = cand_sku if not name else f"{cand_sku} - {name}"
                if label not in sku_map:
                    items.append(label)
                    sku_map[label] = cand_sku

            if items:
                # QInputDialogインスタンスを使って、選択時の文字色が見えるように明示的にスタイルを指定
                dlg = QInputDialog(self)
                dlg.setWindowTitle("SKU指定リネーム")
                dlg.setLabelText("JANコードから見つかったSKU候補を選択するか、直接SKUを入力してください：")
                dlg.setComboBoxEditable(True)
                dlg.setComboBoxItems(items)
                # ダークテーマでも選択文字が見えるように白背景＋黒文字を強制
                dlg.setStyleSheet(
                    "QComboBox, QLineEdit, QListView {"
                    "  color: black;"
                    "  background-color: white;"
                    "}"
                    "QListView::item:selected {"
                    "  color: black;"
                    "  background-color: #cce4ff;"
                    "}"
                )

                if dlg.exec_() != QDialog.Accepted:
                    return

                selected_text = dlg.textValue().strip()
                if selected_text in sku_map:
                    sku = sku_map[selected_text]
                else:
                    # 「SKU - 商品名」形式でない場合は、先頭の単語をSKUとみなす
                    sku = selected_text.split()[0]
            else:
                # 候補があってもSKUが空なら手入力にフォールバック
                sku, ok = QInputDialog.getText(
                    self,
                    "SKU指定リネーム",
                    "このJANグループの画像に使用するSKUを入力してください：",
                )
                if not ok or not sku:
                    return
        else:
            # 候補がない場合はSKUを直接入力
            sku, ok = QInputDialog.getText(
                self,
                "SKU指定リネーム",
                "このJANグループの画像に使用するSKUを入力してください：",
            )
            if not ok or not sku:
                return

        sku = sku.strip()
        if not sku:
            QMessageBox.warning(self, "エラー", "SKUが入力されていません。")
            return

        reply = QMessageBox.question(
            self,
            "リネーム確認",
            f"JANグループ「{group.jan}」の画像を\nSKU「{sku}」ベース（SKU_1, SKU_2…）の名前にリネームしますか？\n"
            "（既に {SKU}_数字 形式のファイルはスキップされます）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        rename_operations = self._build_rename_plan_for_group(group, sku)

        if not rename_operations:
            QMessageBox.information(self, "情報", "リネーム対象のファイルはありませんでした。")
            return

        renamed_count = self._execute_rename_operations(rename_operations)

        # 仕入DBへの紐付け処理
        linked_count = 0
        if self.product_widget and group.jan != "unknown":
            try:
                updated_group = next((g for g in self.jan_groups if g.jan == group.jan), None)
                if updated_group:
                    new_image_paths = self._collect_image_paths_for_group(updated_group)
                    
                    # 仕入DBの全レコードを取得
                    all_records = self.product_widget.get_all_purchase_records()
                    
                    # 指定したSKUのレコードに画像パスを紐付け
                    success, added_count, record_snapshot = self.product_widget.update_image_paths_for_jan(
                        group.jan,
                        new_image_paths,
                        all_records,
                        skip_existing=False,  # 既存の画像を上書きする
                        target_sku=sku,
                        defer_table_refresh_and_snapshot=True,
                    )
                    
                    if success and added_count > 0:
                        linked_count = added_count
                        self._finalize_purchase_db_after_image_link()
                        # 画像登録タブに追加（Amazon画像更新ワークフロー用）
                        if record_snapshot:
                            self.add_registration_entry(record_snapshot)
            except Exception as e:
                logger.error(f"SKU指定リネーム後の紐付けエラー: {e}")
                # エラーが出てもリネームは成功しているので続行

        # 完了メッセージ
        message = f"{renamed_count}件の画像をSKU「{sku}」でリネームしました。"
        if linked_count > 0:
            message += f"\n仕入DBのSKU「{sku}」に{linked_count}件の画像を紐付けました。"
        QMessageBox.information(self, "完了", message)


    def rerename_images_for_group(self, group: JanGroup):
        """
        _1 欠落などで連番がずれたグループを振り直す。
        例: 2枚目が _2 のまま → _1、3枚目 _3 → _2 …
        """
        if not group or not group.images:
            QMessageBox.information(self, "情報", "画像が含まれていないJANグループです。")
            return

        self._ensure_product_widget_data_loaded()

        sorted_images = self._sorted_group_images(group)
        exclude_first = self._is_group_first_image_excluded(group)
        sku = self._resolve_sku_for_group_rerename(group)
        if not sku:
            QMessageBox.warning(
                self,
                "SKU不明",
                "このグループから SKU を特定できませんでした。\n"
                "先に「SKUを指定してリネーム」を実行するか、仕入DBに紐付けてください。",
            )
            return

        if not needs_amazon_sequence_rerename(
            sorted_images,
            sku,
            exclude_first=exclude_first,
            path_getter=lambda r: r.path,
        ):
            first_slot_hint = "2枚目" if exclude_first else "1枚目"
            QMessageBox.information(
                self,
                "再リネーム不要",
                f"このグループは再リネームの対象ではありません。\n"
                f"（{first_slot_hint}の画像が既に {sku}_1 になっているか、"
                "SKU付きの商品画像がありません）",
            )
            return

        first_slot_hint = "2枚目（1枚目はバーコード除外）" if exclude_first else "1枚目"
        reply = QMessageBox.question(
            self,
            "再リネーム確認",
            f"JANグループ「{group.jan}」の Amazon 画像名を振り直します。\n\n"
            f"SKU: {sku}\n"
            f"{first_slot_hint}を {sku}_1.jpg にし、以降を _2, _3… に並べ替えます。\n\n"
            "実行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        rename_operations = self._build_rerename_plan_for_group(group, sku)
        if not rename_operations:
            QMessageBox.information(self, "情報", "リネーム対象のファイルはありませんでした。")
            return

        renamed_count = self._execute_rerename_operations(rename_operations)

        linked_count = 0
        if self.product_widget and group.jan != "unknown":
            try:
                updated_group = next((g for g in self.jan_groups if g.jan == group.jan), None)
                if updated_group:
                    new_image_paths = self._collect_image_paths_for_group(updated_group)
                    all_records = self.product_widget.get_all_purchase_records()
                    success, added_count, record_snapshot = (
                        self.product_widget.update_image_paths_for_jan(
                            group.jan,
                            new_image_paths,
                            all_records,
                            skip_existing=False,
                            target_sku=sku,
                            defer_table_refresh_and_snapshot=True,
                        )
                    )
                    if success and added_count > 0:
                        linked_count = added_count
                        self._finalize_purchase_db_after_image_link()
                        if record_snapshot:
                            self.add_registration_entry(record_snapshot)
            except Exception as e:
                logger.error(f"再リネーム後の紐付けエラー: {e}")

        message = f"{renamed_count}件の画像を再リネームしました（{sku}_1 から振り直し）。"
        if linked_count > 0:
            message += f"\n仕入DBの SKU「{sku}」に {linked_count} 件の画像を反映しました。"
        QMessageBox.information(self, "完了", message)


