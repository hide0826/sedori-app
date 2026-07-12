#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フォルダ選択・スキャン mixin。"""
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

class ImageManagerScanMixin:
    def _folder_dialog_start_dir(self, prefer_default: bool = False) -> str:
        """フォルダ選択ダイアログの開始位置を決定"""
        candidates: List[str] = []
        if prefer_default and self.default_root_dir:
            candidates.append(self.default_root_dir)
        if self.current_directory:
            candidates.append(self.current_directory)
        if self.default_root_dir:
            candidates.append(self.default_root_dir)
        candidates.append(str(Path.home()))
        for path in candidates:
            if path and os.path.isdir(path):
                return path
        return str(Path.home())


    def select_directory(self):
        """フォルダ選択ダイアログを表示"""
        # フォルダ選択はデフォルト設定の起点フォルダから開く
        start_dir = self._folder_dialog_start_dir(prefer_default=True)
        dialog = QFileDialog(self, "画像フォルダを選択", start_dir)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        if os.path.isdir(start_dir):
            dialog.setDirectory(start_dir)
        directory = ""
        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                directory = selected[0]
        
        if directory:
            self.current_directory = directory
            self.folder_path_label.setText(directory)
            self.scan_btn.setEnabled(True)
            self.scan_unknown_btn.setEnabled(True)
            self.save_last_directory()


    def set_default_root_directory(self):
        """画像管理タブの起点となるデフォルトフォルダを設定"""
        # ダイアログの開始位置（既存のデフォルトフォルダ → 現在のフォルダ → ホーム）
        if self.default_root_dir:
            start_dir = self.default_root_dir
        elif self.current_directory:
            start_dir = self.current_directory
        else:
            start_dir = str(Path.home())

        directory = QFileDialog.getExistingDirectory(self, "デフォルト画像フォルダを選択", start_dir)
        if not directory:
            return

        self.default_root_dir = directory
        # ユーザーに分かるよう簡単なメッセージを表示
        QMessageBox.information(
            self,
            "デフォルトフォルダ設定",
            f"画像管理タブの起点フォルダを次の場所に設定しました:\n{directory}"
        )
        # 設定ファイルに保存
        self.save_last_directory()


    def scan_directory(self):
        """ディレクトリをスキャンして画像を取得"""
        if not self.current_directory:
            QMessageBox.warning(self, "エラー", "フォルダを選択してください。")
            return
        
        self._scan_cancelled = False
        
        try:
            # プログレスダイアログを表示（％表示対応）
            self.progress_dialog = QProgressDialog("画像をスキャン中...", "キャンセル", 0, 1, self)
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.setAutoClose(False)
            self.progress_dialog.setAutoReset(False)
            self.progress_dialog.setValue(0)
            self.progress_dialog.show()
            
            def handle_cancel():
                self._scan_cancelled = True
            
            self.progress_dialog.canceled.connect(handle_cancel)
            
            def progress_callback(current: int, total: int):
                if self._scan_cancelled:
                    raise ScanCancelledError()
                
                if not self.progress_dialog:
                    return
                
                if total <= 0:
                    self.progress_dialog.setMaximum(1)
                    self.progress_dialog.setValue(1)
                    self.progress_dialog.setLabelText("画像をスキャン中... 対象画像が見つかりません")
                else:
                    if self.progress_dialog.maximum() != total:
                        self.progress_dialog.setMaximum(total)
                    self.progress_dialog.setValue(current)
                    percent = (current / total) * 100 if total else 0
                    self.progress_dialog.setLabelText(
                        f"画像をスキャン中... {current}/{total}枚（{percent:.1f}%）"
                    )
                QApplication.processEvents()
            
            # スキャン実行（高速化のためEXIF・画像サイズ・バーコード読み取りをスキップ）
            # DBキャッシュを構築（スマートスキャン）
            db_records = self.image_db.list_all()
            file_cache = {}
            for r in db_records:
                path = r['file_path']
                # mtimeはDBにないので含めない（無条件ヒットさせる）
                # ただしファイルが存在しない場合はキャッシュに含めない方が安全だが、
                # Service側でファイル存在チェックをしているのでここでは単純に構築する
                rec = ImageRecord(
                    path=path,
                    capture_dt=datetime.fromisoformat(r['capture_time']) if r['capture_time'] else None,
                    jan_candidate=r['jan'],
                    width=0,  # DBにないので0（表示時にロードされる）
                    height=0
                )
                file_cache[path] = {"record": rec}

            self.image_records = self.image_service.scan_directory(
                self.current_directory, 
                skip_barcode_reading=False,  # JANを自動判別
                skip_exif=False,             # EXIF撮影日時を取得
                skip_image_size=False,       # 画像サイズも取得
                progress_callback=progress_callback,
                file_cache=file_cache        # キャッシュを渡す
            )
            self._jan_title_cache = {}
            
            # DBに保存済みのJANがある場合は反映（過去の割当てを復元）
            enriched_records: List[ImageRecord] = []
            for record in self.image_records:
                db_record = self.image_db.get_by_file_path(record.path)
                jan_from_db = db_record.get("jan") if db_record else None
                if jan_from_db:
                    enriched_records.append(ImageRecord(
                        path=record.path,
                        capture_dt=record.capture_dt,
                        jan_candidate=jan_from_db,
                        width=record.width,
                        height=record.height
                    ))
                else:
                    enriched_records.append(record)
            self.image_records = enriched_records

            # タイムスタンプに基づく自動紐付け（JAN画像から3分以内の画像を自動追加）
            time_window = 3 * 60  # 3分
            current_jan = None
            current_jan_time = None
            
            auto_linked_records: List[ImageRecord] = []
            
            for record in self.image_records:
                # JANコードを持っている画像（数字のみ）
                if record.jan_candidate and record.jan_candidate.isdigit():
                    current_jan = record.jan_candidate
                    current_jan_time = record.capture_dt
                    auto_linked_records.append(record)
                
                # JANコードがない画像
                elif current_jan and current_jan_time and record.capture_dt:
                    time_diff = (record.capture_dt - current_jan_time).total_seconds()
                    # 0 < diff <= 3分
                    if 0 < time_diff <= time_window:
                        # 自動紐付け
                        new_record = ImageRecord(
                            path=record.path,
                            capture_dt=record.capture_dt,
                            jan_candidate=current_jan,
                            width=record.width,
                            height=record.height
                        )
                        auto_linked_records.append(new_record)
                    else:
                        # 時間外なら紐付けない
                        auto_linked_records.append(record)
                        # 時間外になったらカレントJANの効果を切るべきか？
                        # 要望は「JAN画像の後3分以内」なので、3分経過したら紐付け終了で良いはず。
                        if time_diff > time_window:
                            current_jan = None
                            current_jan_time = None
                else:
                    auto_linked_records.append(record)
            
            self.image_records = auto_linked_records
            
            self._close_progress_dialog()
            
            if not self.image_records:
                QMessageBox.information(self, "結果", "画像ファイルが見つかりませんでした。")
                return
            
            # JANでグルーピング（JANコードなしも含む）
            self.jan_groups = self.image_service.group_by_jan(self.image_records)
            
            # DBに保存
            for group in self.jan_groups:
                for i, record in enumerate(group.images):
                    self.image_db.upsert({
                        "file_path": record.path,
                        "jan": group.jan if group.jan != "unknown" else None,
                        "group_index": i,
                        "capture_time": record.capture_dt.isoformat() if record.capture_dt else None,
                        "rotation": 0
                    })
            
            # UI更新
            self.update_tree_widget()

            # スキャン完了後は手動工程③（画像紐付け調整）へ進む
            self._workflow_post_step = 3
            
            # 全画像を一覧表示（遅延読み込み：スキャン完了後に非同期で実行）
            # 画像読み込みは重いので、まずスキャン完了を通知してから実行
            QMessageBox.information(
                self, "スキャン完了",
                f"{len(self.image_records)}件の画像をスキャンしました。\n"
                f"JANグループ数: {len(self.jan_groups)}"
            )
            
            # スキャン完了後、バックグラウンドで画像一覧を更新（ユーザーが待たない）
            self.update_image_list(self.image_records)
        except ScanCancelledError:
            QMessageBox.information(self, "キャンセル", "画像スキャンを中止しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"スキャン中にエラーが発生しました:\n{str(e)}")
        finally:
            self._close_progress_dialog()


    def scan_unknown_jan_images(self):
        """JAN不明画像に対してOCRを実行し、候補を検索"""
        # JAN不明画像を抽出
        unknown_images = [
            r for r in self.image_records 
            if not r.jan_candidate or r.jan_candidate == "unknown" or not r.jan_candidate.isdigit()
        ]
        
        if not unknown_images:
            QMessageBox.information(self, "情報", "JAN不明な画像はありません。")
            return
        
        # OCRサービスの利用可能性チェック
        if not self.ocr_service.is_tesseract_available() and not self.ocr_service.is_gcv_available():
            QMessageBox.warning(
                self, 
                "OCR利用不可", 
                "OCR機能を使用するには、Tesseract OCRのインストールまたはGoogle Cloud Vision APIの設定が必要です。"
            )
            return

        # 仕入データの準備
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            QMessageBox.warning(self, "情報", "照合対象の仕入データがありません。")
            return

        # 簡易インデックス作成（商品名をトークン化）
        product_index = []
        for p in purchase_records:
            jan = str(p.get("JAN") or p.get("jan") or "").strip()
            title = str(p.get("商品名") or p.get("product_name") or "").strip()
            if not jan or not title:
                continue
            
            # トークン化（簡易的）
            tokens = set(re.split(r'\s+', title.lower()))
            tokens = {t for t in tokens if len(t) > 1} # 1文字は除外
            product_index.append({
                "jan": jan,
                "title": title,
                "tokens": tokens
            })

        # プログレスダイアログ
        progress = QProgressDialog("JAN不明画像をOCR解析中...", "キャンセル", 0, len(unknown_images), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        candidates_map = {} # {image_path: {"ocr_text": str, "candidates": [...]}}
        
        for i, record in enumerate(unknown_images):
            if progress.wasCanceled():
                break
                
            progress.setValue(i)
            progress.setLabelText(f"OCR解析中... ({i+1}/{len(unknown_images)})")
            QApplication.processEvents()
            
            try:
                # OCR実行
                ocr_result = self.ocr_service.extract_text(record.path)
                text = ocr_result.get("text", "")
                
                if not text:
                    continue
                    
                # マッチング処理
                text_lower = text.lower()
                # OCRテキストからトークン抽出
                ocr_tokens = set(re.split(r'\s+|[^\w]+', text_lower))
                ocr_tokens = {t for t in ocr_tokens if len(t) > 2} # 2文字以下は除外（ノイズ対策）
                
                matches = []
                for prod in product_index:
                    # スコア計算: 共通トークン数
                    common = ocr_tokens.intersection(prod["tokens"])
                    if common:
                        # マッチしたトークンの数や割合でスコア化
                        score = len(common) * 10 # 基本点
                        # さらに、OCRテキスト全体に商品名が含まれているか（完全一致ボーナス）
                        # if prod["title"].lower() in text_lower:
                        #    score += 50
                        matches.append({
                            "jan": prod["jan"],
                            "title": prod["title"],
                            "score": score
                        })
                
                # スコア順にソートして上位を抽出
                matches.sort(key=lambda x: x["score"], reverse=True)
                top_matches = matches[:5] # 上位5件
                
                if top_matches and top_matches[0]["score"] >= 10: # 最低スコア閾値
                    candidates_map[record.path] = {
                        "ocr_text": text,
                        "candidates": top_matches
                    }
                    
            except Exception as e:
                logger.warning(f"OCR processing failed for {record.path}: {e}")
                continue
        
        progress.close()
        
        if not candidates_map:
            QMessageBox.information(self, "結果", "OCR解析を行いましたが、商品名と一致する候補は見つかりませんでした。")
            return
            
        # 結果表示ダイアログ
        dialog = CandidateSelectionDialog(candidates_map, self)
        if dialog.exec_() == QDialog.Accepted:
            selected = dialog.selected_results
            if not selected:
                return
                
            count = 0
            for image_path, jan in selected.items():
                if self.assign_image_to_jan(image_path, jan):
                    count += 1
            
            QMessageBox.information(self, "完了", f"{count}件の画像にJANコードを割り当てました。")


    def _close_progress_dialog(self):
        """プログレスダイアログを安全に閉じる"""
        if self.progress_dialog:
            try:
                self.progress_dialog.reset()
            except Exception:
                pass
            self.progress_dialog.close()
            self.progress_dialog = None


