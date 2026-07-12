#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像管理ウィジェット（オーケストレーター）。"""
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


from .workflow_mixin import ImageManagerWorkflowMixin
from .scan_mixin import ImageManagerScanMixin
from .tree_mixin import ImageManagerTreeMixin
from .preview_mixin import ImageManagerPreviewMixin
from .rename_mixin import ImageManagerRenameMixin
from .purchase_link_mixin import ImageManagerPurchaseLinkMixin
from .registration_mixin import ImageManagerRegistrationMixin
from .gcs_mixin import ImageManagerGcsMixin
from .amazon_template_mixin import ImageManagerAmazonTemplateMixin


class ImageManagerWidget(
    ImageManagerWorkflowMixin,
    ImageManagerScanMixin,
    ImageManagerTreeMixin,
    ImageManagerPreviewMixin,
    ImageManagerRenameMixin,
    ImageManagerPurchaseLinkMixin,
    ImageManagerRegistrationMixin,
    ImageManagerGcsMixin,
    ImageManagerAmazonTemplateMixin,
    QWidget,
):
    """画像管理ウィジェット"""

    # URL画像プレビュー用シグナル（バックグラウンド→メインスレッド）
    _preview_image_ready = Signal(str, bytes)  # (token, image_data)
    _preview_image_error = Signal(str, str)    # (token, error_message)

    def __init__(self, api_client=None, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.image_service = ImageService()
        self.ocr_service = OCRService()
        self.image_db = ImageDatabase()
        self.product_widget = None  # ProductWidgetへの参照
        
        # データ
        # 画像管理タブで使用する現在のフォルダ
        self.current_directory = ""
        # 「起点」となるデフォルトフォルダ（ユーザーが任意に登録可能）
        self.default_root_dir: str = ""
        # JANグループ1枚目画像のチェック状態
        #   True  = 1枚目を送信しない（除外）
        #   False = 1枚目も送信する（例外的に含める）
        self.first_image_flags: Dict[str, bool] = {}
        # ツリー更新中フラグ（itemChangedの再入防止）
        self._updating_tree_checks: bool = False
        self.image_records: List[ImageRecord] = []
        self.jan_groups: List[JanGroup] = []
        self.selected_group: Optional[JanGroup] = None
        self.selected_image_path: Optional[str] = None
        self._scan_cancelled = False
        self._workflow_status_text = "ワークフロー: 未実行"
        self._workflow_emphasize = False
        self._workflow_active_step: Optional[int] = None
        self._workflow_post_step: Optional[int] = None
        self._registration_workflow_status_text = "ワークフロー: 未実行"
        self._registration_workflow_emphasize = False
        self._registration_workflow_active_step: Optional[int] = None
        self._jan_title_cache: Dict[str, str] = {}
        self.registration_records: List[Dict[str, Any]] = []
        self._last_amazon_template_output_path: str = ""
        # 画像登録タブ用の簡易スナップショット保存先
        base_dir = Path(__file__).resolve().parents[2]  # desktop/
        self.registration_snapshot_path = base_dir / "data" / "image_registration_snapshot.json"
        
        # 設定ファイルのパス
        self.config_path = Path(__file__).resolve().parents[4] / "config" / "inventory_settings.json"
        
        # スレッド
        self.load_thread: Optional[ImageLoadThread] = None
        self.progress_dialog: Optional[QProgressDialog] = None
        
        self.setup_ui()
        self.load_preferences()
        self._reset_image_manager_folder_state()

        # テーブルの列幅を復元
        # 列構成を変更したのでキーを更新（古い保存状態を無効化）
        restore_table_header_state(self.registration_table, "ImageManagerWidget/RegistrationTableState/v3")


    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.registration_table, "ImageManagerWidget/RegistrationTableState/v3")


    def set_product_widget(self, product_widget):
        """ProductWidgetへの参照を設定"""
        self.product_widget = product_widget


    def setup_ui(self):
        """UIのセットアップ"""
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(10)
        root_layout.setContentsMargins(10, 10, 10, 10)

        self.tab_widget = QTabWidget()
        root_layout.addWidget(self.tab_widget)

        self.main_tab = QWidget()
        layout = QVBoxLayout(self.main_tab)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 上部：ファイル操作・アクション（仕入管理タブと同じ構成）
        file_group = QGroupBox("ファイル操作・アクション")
        file_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        file_outer = QVBoxLayout(file_group)
        file_outer.setSpacing(4)
        file_outer.setContentsMargins(5, 5, 5, 5)

        green_button_style = """
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """

        file_layout = QHBoxLayout()
        file_layout.setSpacing(5)

        folder_label = QLabel("フォルダ:")
        self.folder_path_label = QLabel("（未選択）")
        self.folder_path_label.setMinimumHeight(20)
        self.folder_path_label.setMaximumHeight(20)
        self.folder_path_label.setStyleSheet("border: 1px solid gray; padding: 2px;")
        self.folder_path_label.setWordWrap(False)

        self.select_folder_btn = QPushButton("フォルダ選択")
        self.select_folder_btn.clicked.connect(
            lambda: self._run_action_with_status("フォルダ選択", self.select_directory)
        )
        self.select_folder_btn.setStyleSheet(green_button_style)

        self.scan_btn = QPushButton("スキャン実行")
        self.scan_btn.clicked.connect(
            lambda: self._run_action_with_status("スキャン実行", self.scan_directory)
        )
        self.scan_btn.setEnabled(False)
        self.scan_btn.setStyleSheet(green_button_style)

        self.rename_btn = QPushButton("全画像リネーム")
        self.rename_btn.clicked.connect(
            lambda: self._run_action_with_status("全画像リネーム", self.rename_all_images)
        )
        self.rename_btn.setEnabled(False)
        self.rename_btn.setStyleSheet(green_button_style)

        self.confirm_btn = QPushButton("確定処理")
        self.confirm_btn.clicked.connect(
            lambda: self._run_action_with_status("確定処理", self.confirm_image_links)
        )
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setStyleSheet(green_button_style)

        self.set_default_folder_btn = QPushButton("デフォルト設定")
        self.set_default_folder_btn.setToolTip("画像管理タブでフォルダを開くときの起点フォルダを登録します。")
        self.set_default_folder_btn.clicked.connect(self.set_default_root_directory)

        self.scan_unknown_btn = QPushButton("JAN不明検索")
        self.scan_unknown_btn.clicked.connect(self.scan_unknown_jan_images)
        self.scan_unknown_btn.setEnabled(False)

        self.manual_link_btn = QPushButton("指定紐付け")
        self.manual_link_btn.setToolTip("スキャン済みのJANグループを、データベース管理タブの仕入DBから選んだ仕入日で一括紐付けします。")
        self.manual_link_btn.clicked.connect(self.manual_link_by_purchase_date)

        self.clear_images_btn = QPushButton("画像クリア")
        self.clear_images_btn.clicked.connect(self.clear_jan_groups)
        self.clear_images_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)

        file_layout.addWidget(folder_label)
        file_layout.addWidget(self.folder_path_label, stretch=1)
        file_layout.addWidget(self.select_folder_btn)
        file_layout.addWidget(self.scan_btn)
        file_layout.addWidget(self.rename_btn)
        file_layout.addWidget(self.confirm_btn)
        file_layout.addStretch()
        file_layout.addWidget(self.set_default_folder_btn)
        file_layout.addWidget(self.scan_unknown_btn)
        file_layout.addWidget(self.manual_link_btn)
        file_layout.addWidget(self.clear_images_btn)
        file_outer.addLayout(file_layout)

        self.workflow_status_label = QLabel()
        self.workflow_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.workflow_status_label.setWordWrap(True)
        self.workflow_status_label.setStyleSheet("padding: 2px 0px;")
        self._sync_workflow_status_label()
        file_outer.addWidget(self.workflow_status_label)

        rename_options_row = QHBoxLayout()
        rename_options_row.setSpacing(16)
        self.lightweight_rename_checkbox = QCheckBox("リネーム時に軽量化（長辺1600px・JPEG品質85・EXIF削除）")
        self.lightweight_rename_checkbox.setToolTip(
            "有効にすると、SKUリネーム時に画像を再エンコードします。"
            "一時ファイルへ保存してから置き換えるため、失敗時も元ファイルを保護しやすくなります。"
        )
        self.lightweight_rename_checkbox.stateChanged.connect(self._on_rename_option_preference_changed)
        self.auto_correct_rename_checkbox = QCheckBox("リネーム時に自動補正（明るさ・コントラスト・シャープ）")
        self.auto_correct_rename_checkbox.setToolTip(
            "有効にすると、リネーム時にAIを使わず画像を補正します。"
            "軽量化のON/OFFとは独立して使えます（補正のみ・補正＋軽量化の両方が可能）。"
        )
        self.auto_correct_rename_checkbox.stateChanged.connect(self._on_rename_option_preference_changed)
        rename_options_row.addWidget(self.lightweight_rename_checkbox)
        rename_options_row.addWidget(self.auto_correct_rename_checkbox)
        rename_options_row.addWidget(QLabel("補正:"))
        self.auto_correct_preset_combo = QComboBox()
        for label, preset_id in (("弱", "weak"), ("標準", "standard"), ("強", "strong")):
            self.auto_correct_preset_combo.addItem(label, preset_id)
        self.auto_correct_preset_combo.setToolTip(
            "リネーム時の自動補正の強さ。右のプレビューで補正後の見え方を確認できます。"
        )
        self.auto_correct_preset_combo.currentIndexChanged.connect(self._on_auto_correct_preset_changed)
        rename_options_row.addWidget(self.auto_correct_preset_combo)
        rename_options_row.addStretch()
        file_outer.addLayout(rename_options_row)

        layout.addWidget(file_group)
        
        # メインエリア：三分割レイアウト
        splitter = QSplitter(Qt.Horizontal)
        
        # 左：JANグループツリー
        left_group = QGroupBox("JANグループ")
        left_layout = QVBoxLayout(left_group)
        
        # JANグループ追加ボタン
        add_group_btn = QPushButton("JANグループ追加")
        add_group_btn.clicked.connect(self.add_jan_group_manually)
        left_layout.addWidget(add_group_btn)
        
        self.tree_widget = JanGroupTreeWidget(self)
        self.tree_widget.setHeaderLabel("JANグループ")
        # チェックボックスがダークテーマでもはっきり見えるようにスタイルを調整
        self.tree_widget.setStyleSheet("""
            QTreeWidget::indicator {
                width: 16px;
                height: 16px;
            }
            QTreeWidget::indicator:unchecked {
                image: none;
                border: 2px solid #ffffff;
                background-color: transparent;
            }
            QTreeWidget::indicator:checked {
                image: none;
                border: 2px solid #ffffff;
                background-color: #ffffff;
            }
        """)
        self.tree_widget.itemSelectionChanged.connect(self.on_tree_selection_changed)
        # 各JANグループ1枚目画像のチェックボックス変更を監視
        self.tree_widget.itemChanged.connect(self.on_tree_item_changed)
        self.tree_widget.setAcceptDrops(True)  # ドロップを受け入れる
        self.tree_widget.setDragDropMode(QTreeWidget.DropOnly)  # ドロップのみ許可
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.on_tree_context_menu)
        left_layout.addWidget(self.tree_widget)

        splitter.addWidget(left_group)
        
        # 中央：画像リスト
        center_group = QGroupBox("画像一覧（撮影時間順）")
        center_layout = QVBoxLayout(center_group)
        self.image_list = ImageListWidget(self)
        self.image_list.setViewMode(QListWidget.IconMode)
        self.image_list.setResizeMode(QListWidget.Adjust)
        self.image_list.setIconSize(QSize(192, 192))
        self.image_list.setSpacing(10)
        self.image_list.itemClicked.connect(self.on_image_clicked)
        self.image_list.setSelectionMode(QListWidget.ExtendedSelection)  # 複数選択（ドラッグ範囲・Ctrl/Shift）
        self.image_list.setDragDropMode(QListWidget.DragOnly)  # ドラッグのみ許可
        self.image_list.setDefaultDropAction(Qt.MoveAction)  # ドラッグ時の動作
        self.image_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.image_list.customContextMenuRequested.connect(self.on_image_list_context_menu)
        center_layout.addWidget(self.image_list)
        splitter.addWidget(center_group)
        
        # 右：詳細パネル
        right_group = QGroupBox("詳細情報")
        right_layout = QVBoxLayout(right_group)
        
        # プレビュー（元画像 / 補正後）
        preview_group = QGroupBox("プレビュー")
        preview_group_layout = QVBoxLayout(preview_group)
        preview_split = QHBoxLayout()
        preview_style = "border: 1px solid gray; background-color: #f0f0f0;"
        orig_col = QVBoxLayout()
        orig_col.addWidget(QLabel("元画像"))
        self.preview_original_label = QLabel()
        self.preview_original_label.setMinimumSize(180, 180)
        self.preview_original_label.setStyleSheet(preview_style)
        self.preview_original_label.setAlignment(Qt.AlignCenter)
        self.preview_original_label.setText("画像を選択")
        self.preview_original_label.setScaledContents(True)
        orig_col.addWidget(self.preview_original_label)
        corr_col = QVBoxLayout()
        self.preview_corrected_caption = QLabel("補正後（標準）")
        corr_col.addWidget(self.preview_corrected_caption)
        self.preview_corrected_label = QLabel()
        self.preview_corrected_label.setMinimumSize(180, 180)
        self.preview_corrected_label.setStyleSheet(preview_style)
        self.preview_corrected_label.setAlignment(Qt.AlignCenter)
        self.preview_corrected_label.setText("画像を選択")
        self.preview_corrected_label.setScaledContents(True)
        corr_col.addWidget(self.preview_corrected_label)
        preview_split.addLayout(orig_col)
        preview_split.addLayout(corr_col)
        preview_group_layout.addLayout(preview_split)
        self.preview_label = self.preview_original_label
        
        # 詳細情報フォーム
        detail_form = QFormLayout()
        
        self.jan_edit = QLineEdit()
        self.jan_edit.setPlaceholderText("JANコード（8桁または13桁）")
        detail_form.addRow("JANコード:", self.jan_edit)
        
        self.capture_time_label = QLabel("-")
        detail_form.addRow("撮影日時:", self.capture_time_label)
        
        self.file_name_label = QLabel("-")
        detail_form.addRow("ファイル名:", self.file_name_label)
        
        self.file_size_label = QLabel("-")
        detail_form.addRow("サイズ:", self.file_size_label)
        
        # 操作ボタン
        button_layout = QHBoxLayout()
        self.rotate_left_btn = QPushButton("左回転（-90°）")
        self.rotate_left_btn.clicked.connect(lambda: self.rotate_image(-90))
        self.rotate_right_btn = QPushButton("右回転（+90°）")
        self.rotate_right_btn.clicked.connect(lambda: self.rotate_image(90))
        
        # バーコード読み取りボタン
        self.read_barcode_btn = QPushButton("バーコード読み取り")
        self.read_barcode_btn.clicked.connect(self.read_barcode_from_image)
        
        self.save_jan_btn = QPushButton("JAN保存")
        self.save_jan_btn.clicked.connect(self.save_jan)
        
        button_layout.addWidget(self.rotate_left_btn)
        button_layout.addWidget(self.rotate_right_btn)
        button_layout.addWidget(self.read_barcode_btn)
        button_layout.addWidget(self.save_jan_btn)
        
        right_layout.addWidget(preview_group)
        right_layout.addLayout(detail_form)
        right_layout.addLayout(button_layout)
        right_layout.addStretch()
        
        splitter.addWidget(right_group)
        
        # 分割の比率を設定（左:中央:右 = 1:2:1）
        splitter.setSizes([250, 500, 250])
        
        layout.addWidget(splitter)

        self.tab_widget.addTab(self.main_tab, "画像管理")
        self.setup_registration_tab()
        self.tab_widget.addTab(self.registration_tab, "画像登録")
        self.tab_widget.currentChanged.connect(self._on_inner_tab_changed)
        
        # 初期状態でボタンを無効化
        self.rotate_left_btn.setEnabled(False)
        self.rotate_right_btn.setEnabled(False)
        self.read_barcode_btn.setEnabled(False)
        self.save_jan_btn.setEnabled(False)
        self.rename_btn.setEnabled(False)
        self.confirm_btn.setEnabled(False)

        # バーコードリーダーの利用可能性を確認
        if not self.image_service.is_barcode_reader_available():
            self.read_barcode_btn.setToolTip(
                "バーコードリーダーを使用するには、pyzbarとzbarライブラリが必要です。\n"
                "pip install pyzbar\n"
                "Windows: zbar-w64をダウンロードしてインストール\n"
                "Linux: sudo apt-get install libzbar0\n"
                "macOS: brew install zbar"
            )


    def load_preferences(self):
        """デフォルトフォルダ・リネームオプション等の設定を読み込む（作業フォルダは復元しない）"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # デフォルトフォルダ（起点）の読み込み
                    default_dir = config.get('image_manager_default_root_dir')
                    if default_dir and os.path.exists(default_dir) and os.path.isdir(default_dir):
                        self.default_root_dir = default_dir

                    lw = config.get('image_manager_lightweight_rename')
                    if lw is not None:
                        self.lightweight_rename_checkbox.setChecked(bool(lw))
                    ac = config.get('image_manager_auto_correct_on_rename')
                    if ac is not None:
                        self.auto_correct_rename_checkbox.setChecked(bool(ac))
                    preset_id = config.get(
                        'image_manager_auto_correct_preset',
                        DEFAULT_AUTO_CORRECT_PRESET,
                    )
                    self._set_auto_correct_preset_combo(preset_id)
        except Exception as e:
            print(f"Failed to load image manager preferences: {e}")


    def save_last_directory(self):
        """画像管理の設定（デフォルトフォルダ・リネームオプション）を保存"""
        try:
            # 設定ファイルを読み込む（存在しない場合は新規作成）
            config = {}
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            # 作業フォルダはセッション跨ぎで復元しない
            config.pop('image_manager_last_directory', None)

            # 起点となるデフォルトフォルダも保存
            if self.default_root_dir:
                config['image_manager_default_root_dir'] = self.default_root_dir

            config['image_manager_lightweight_rename'] = self.lightweight_rename_checkbox.isChecked()
            config['image_manager_auto_correct_on_rename'] = self.auto_correct_rename_checkbox.isChecked()
            config['image_manager_auto_correct_preset'] = self._auto_correct_preset_id()
            config.pop('image_manager_upload_mode', None)

            # 設定ファイルを保存
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save last directory: {e}")


    def _on_rename_option_preference_changed(self, _state: int = 0) -> None:
        """リネーム時オプション（軽量化・自動補正）を設定ファイルへ保存する"""
        self.save_last_directory()


    def _auto_correct_preset_id(self) -> str:
        idx = self.auto_correct_preset_combo.currentIndex()
        if idx < 0:
            return DEFAULT_AUTO_CORRECT_PRESET
        data = self.auto_correct_preset_combo.itemData(idx)
        return str(data) if data else DEFAULT_AUTO_CORRECT_PRESET


    def _set_auto_correct_preset_combo(self, preset_id: str) -> None:
        target = (preset_id or DEFAULT_AUTO_CORRECT_PRESET).strip().lower()
        self.auto_correct_preset_combo.blockSignals(True)
        try:
            for i in range(self.auto_correct_preset_combo.count()):
                if str(self.auto_correct_preset_combo.itemData(i)) == target:
                    self.auto_correct_preset_combo.setCurrentIndex(i)
                    break
            else:
                self.auto_correct_preset_combo.setCurrentIndex(1)
            label = self.auto_correct_preset_combo.currentText()
            self.preview_corrected_caption.setText(f"補正後（{label}）")
        finally:
            self.auto_correct_preset_combo.blockSignals(False)


    def _on_auto_correct_preset_changed(self, _index: int = 0) -> None:
        """補正プリセット変更時にプレビューと設定を更新"""
        preset_id = self._auto_correct_preset_id()
        label = self.auto_correct_preset_combo.currentText()
        self.preview_corrected_caption.setText(f"補正後（{label}）")
        self.save_last_directory()
        self._refresh_image_previews()


    def setup_registration_tab(self):
        """画像登録タブのセットアップ"""
        self.registration_tab = QWidget()
        layout = QVBoxLayout(self.registration_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 上段: 説明（左）＋ GCS保存期間（日）（右）
        top_row = QHBoxLayout()
        description = QLabel(
            "確定処理で仕入DBに登録した商品の情報を表示します。\n"
            "アプリ再起動時に自動でクリアされる一時的なリストです。"
        )
        description.setWordWrap(True)
        top_row.addWidget(description)
        top_row.addStretch()
        top_row.addWidget(QLabel("GCS保存期間（日）:"))
        self.gcs_retention_days_spinbox = QSpinBox()
        self.gcs_retention_days_spinbox.setRange(0, 3650)
        self.gcs_retention_days_spinbox.setSuffix(" 日")
        self.gcs_retention_days_spinbox.setToolTip("アップロードした画像を何日後にGCSから削除するか。0=無期限")
        try:
            settings = QSettings("HIRIO", "SedoriDesktopApp")
            saved_days = settings.value("image_manager/gcs_retention_days", 90)
            self.gcs_retention_days_spinbox.setValue(int(saved_days) if saved_days is not None else 90)
        except (TypeError, ValueError):
            self.gcs_retention_days_spinbox.setValue(90)
        top_row.addWidget(self.gcs_retention_days_spinbox)
        top_row.addWidget(QLabel("(0=無期限)"))
        layout.addLayout(top_row)

        registration_action_group = QGroupBox("ファイル操作・アクション")
        registration_action_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        registration_action_outer = QVBoxLayout(registration_action_group)
        registration_action_outer.setSpacing(4)
        registration_action_outer.setContentsMargins(5, 5, 5, 5)

        green_button_style = """
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """

        registration_ops_layout = QHBoxLayout()
        registration_ops_layout.setSpacing(5)

        self.upload_all_to_gcs_btn = QPushButton("GCS一括アップロード")
        self.upload_all_to_gcs_btn.setToolTip("表示中の全行の未アップロード画像をGCSに一括アップロードします")
        self.upload_all_to_gcs_btn.clicked.connect(
            lambda: self._run_registration_action_with_status(
                "GCS一括アップロード", self.upload_all_images_to_gcs
            )
        )
        self.upload_all_to_gcs_btn.setStyleSheet(green_button_style)

        self.save_to_db_btn = QPushButton("DBに保存")
        self.save_to_db_btn.setToolTip("一覧のSKUごとに、画像URL1〜6を仕入DBに保存します")
        self.save_to_db_btn.clicked.connect(
            lambda: self._run_registration_action_with_status(
                "DBに保存", self.save_registration_to_purchase_db
            )
        )
        self.save_to_db_btn.setStyleSheet(green_button_style)

        self.write_amazon_template_btn = QPushButton("amazon（出品ファイルL）テンプレートに書き込み")
        self.write_amazon_template_btn.setToolTip(
            "AmazonテンプレートExcelファイル（出品ファイルL）にSKUと画像URLを書き込みます。"
        )
        self.write_amazon_template_btn.clicked.connect(
            lambda: self._run_registration_action_with_status(
                "amazon（出品ファイルL）テンプレートに書き込み", self.write_to_amazon_template
            )
        )
        self.write_amazon_template_btn.setStyleSheet(green_button_style)

        self.amazon_upload_link_btn = QPushButton("Amazonアップロードページを開く")
        self.amazon_upload_link_btn.setToolTip(
            "Amazon Seller Centralの出品ファイルアップロードページをブラウザで開きます"
        )
        self.amazon_upload_link_btn.clicked.connect(
            lambda: self._run_registration_action_with_status(
                "Amazonアップロードページを開く", self.open_amazon_upload_page
            )
        )
        self.amazon_upload_link_btn.setStyleSheet(green_button_style)

        registration_ops_layout.addWidget(self.upload_all_to_gcs_btn)
        registration_ops_layout.addWidget(self.save_to_db_btn)
        registration_ops_layout.addWidget(self.write_amazon_template_btn)
        registration_ops_layout.addWidget(self.amazon_upload_link_btn)
        registration_ops_layout.addStretch()
        registration_action_outer.addLayout(registration_ops_layout)

        self.registration_workflow_status_label = QLabel()
        self.registration_workflow_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.registration_workflow_status_label.setWordWrap(True)
        self.registration_workflow_status_label.setStyleSheet("padding: 2px 0px;")
        self._sync_registration_workflow_status_label()
        registration_action_outer.addWidget(self.registration_workflow_status_label)

        # テンプレート書き込み後：Amazonへドラッグ＆ドロップ用パネル
        self.amazon_upload_drop_panel = QFrame()
        self.amazon_upload_drop_panel.setObjectName("amazonUploadDropPanel")
        self.amazon_upload_drop_panel.setStyleSheet(
            """
            QFrame#amazonUploadDropPanel {
                background-color: #2a3320;
                border: 1px solid #5a7a3a;
                border-radius: 8px;
                margin-top: 4px;
            }
            """
        )
        amazon_drop_layout = QHBoxLayout(self.amazon_upload_drop_panel)
        amazon_drop_layout.setContentsMargins(12, 10, 12, 10)
        amazon_drop_layout.setSpacing(12)

        self.amazon_template_drag_icon = DraggableFileIconWidget()
        self.amazon_template_drag_icon.setStyleSheet(
            "border: 2px dashed #ffc107; border-radius: 8px; background-color: #3a3520;"
        )
        self.amazon_template_drag_icon.set_browser_title_keywords(
            _AMAZON_UPLOAD_BROWSER_TITLE_KEYWORDS
        )
        self.amazon_template_drag_icon.set_tooltip_prefix(
            "①「Amazonアップロードページを開く」→ ②このアイコンをドラッグしてドロップ欄へ"
        )
        amazon_drop_layout.addWidget(self.amazon_template_drag_icon)

        amazon_drop_text_col = QVBoxLayout()
        amazon_drop_text_col.setSpacing(4)
        self.amazon_upload_drop_title = QLabel("Amazonアップロード用ファイル")
        self.amazon_upload_drop_title.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #d4f0b0;"
        )
        amazon_drop_text_col.addWidget(self.amazon_upload_drop_title)
        self.amazon_upload_drop_hint = QLabel(
            "①「Amazonアップロードページを開く」→ ②左のアイコンをドラッグしてブラウザのドロップ欄へ"
        )
        self.amazon_upload_drop_hint.setWordWrap(True)
        self.amazon_upload_drop_hint.setStyleSheet("color: #b8d8a0;")
        amazon_drop_text_col.addWidget(self.amazon_upload_drop_hint)
        self.amazon_upload_drop_filename = QLabel("（テンプレート書き込み後に表示）")
        self.amazon_upload_drop_filename.setWordWrap(True)
        self.amazon_upload_drop_filename.setStyleSheet("color: #e8e8e8; font-family: monospace;")
        amazon_drop_text_col.addWidget(self.amazon_upload_drop_filename)

        amazon_drop_btn_row = QHBoxLayout()
        self.amazon_upload_open_page_btn = QPushButton("① Amazonアップロードページを開く")
        self.amazon_upload_open_page_btn.setToolTip(
            "Seller Centralの出品ファイルアップロードページをブラウザで開きます"
        )
        self.amazon_upload_open_page_btn.clicked.connect(self.open_amazon_upload_page)
        self.amazon_upload_open_page_btn.setStyleSheet(green_button_style)
        self.amazon_upload_open_folder_btn = QPushButton("保存フォルダを開く")
        self.amazon_upload_open_folder_btn.setToolTip(
            "エクスプローラーでファイルの場所を開きます（ドラッグがうまくいかない場合）"
        )
        self.amazon_upload_open_folder_btn.clicked.connect(self._open_last_amazon_template_folder)
        amazon_drop_btn_row.addWidget(self.amazon_upload_open_page_btn)
        amazon_drop_btn_row.addWidget(self.amazon_upload_open_folder_btn)
        amazon_drop_btn_row.addStretch()
        amazon_drop_text_col.addLayout(amazon_drop_btn_row)
        amazon_drop_layout.addLayout(amazon_drop_text_col, stretch=1)

        self.amazon_upload_drop_panel.setVisible(False)
        registration_action_outer.addWidget(self.amazon_upload_drop_panel)

        layout.addWidget(registration_action_group)

        self.registration_table = RegistrationTableWidget()
        self.registration_columns = [
            "コンディション", "SKU", "ASIN", "JAN", "商品名",
            "画像1", "画像2", "画像3", "画像4", "画像5", "画像6",
            # Amazon Lファイル用追加列（URLのみ残す）
            "画像URL1", "画像URL2", "画像URL3", "画像URL4", "画像URL5"
        ]
        self.registration_table.setColumnCount(len(self.registration_columns))
        self.registration_table.setHorizontalHeaderLabels(self.registration_columns)
        header = self.registration_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # 全列を手動リサイズ可能に
        header.setTextElideMode(Qt.ElideNone)  # ヘッダー文字列を省略しない
        self.registration_table.setTextElideMode(Qt.ElideNone)  # セル文字列も省略しない
        # 初期幅の目安を設定（後から手動リサイズ可能）
        self.registration_table.setColumnWidth(1, 180)  # SKU
        self.registration_table.setColumnWidth(2, 150)  # ASIN
        self.registration_table.setColumnWidth(3, 150)  # JAN
        self.registration_table.setColumnWidth(4, 320)  # 商品名
        for col in range(5, 11):  # 画像1～6
            self.registration_table.setColumnWidth(col, 180)
        for col in range(11, 16):  # 画像URL1～5
            self.registration_table.setColumnWidth(col, 220)
        # 編集トリガー:
        # - シングルクリックは「プレビュー表示」に使いたいので、SelectedClickedは使わない
        # - 編集は「ダブルクリック」または「F2キー」で開始
        self.registration_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.registration_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.registration_table.setSelectionMode(QTableWidget.SingleSelection)
        self.registration_table.verticalHeader().setVisible(False)
        self.registration_table.setDragEnabled(True)
        self.registration_table.cellDoubleClicked.connect(self.on_registration_cell_double_clicked)
        self.registration_table.cellClicked.connect(self.on_registration_cell_clicked)
        # 環境によってはcellClickedが発火しない/分かりにくい場合があるため、
        # カレントセル変更でもプレビュー更新を行う（保険）
        self.registration_table.currentCellChanged.connect(self.on_registration_current_cell_changed)
        # 行選択モードでも確実に拾えるよう、itemClicked/itemPressedでもプレビュー更新（保険）
        self.registration_table.itemClicked.connect(self.on_registration_item_clicked)
        self.registration_table.itemPressed.connect(self.on_registration_item_clicked)
        self.registration_table.cellChanged.connect(self.on_registration_cell_changed)
        # 右クリックメニュー（画像URL削除用）
        self.registration_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.registration_table.customContextMenuRequested.connect(self.on_registration_table_context_menu)
        layout.addWidget(self.registration_table)

        preview_group = QGroupBox("プレビュー / テンプレート書き込み位置")
        preview_group_layout = QHBoxLayout(preview_group)

        preview_left = QWidget()
        preview_left_layout = QVBoxLayout(preview_left)
        preview_left_layout.setContentsMargins(0, 0, 0, 0)
        self.registration_preview_label = QLabel("画像を選択してください")
        self.registration_preview_label.setAlignment(Qt.AlignCenter)
        self.registration_preview_label.setMinimumHeight(200)
        self.registration_preview_label.setStyleSheet(
            "border: 1px solid gray; background-color: #f8f8f8; color: #111;"
        )
        self.registration_preview_label.setScaledContents(False)
        preview_left_layout.addWidget(self.registration_preview_label)

        preview_right = QWidget()
        preview_right_layout = QVBoxLayout(preview_right)
        preview_right_layout.setContentsMargins(8, 0, 0, 0)

        template_notice = QLabel(
            "Amazonの出品ファイル(L)は更新が頻繁に行われています。\n"
            "アップロード時に「最新のファイルに変更してください」と表示された場合は、\n"
            "セラーセントラルから新しいテンプレートをダウンロードし、\n"
            "下の「テンプレート」欄でファイルを差し替えてから「テンプレート再解析」を実行してください。"
        )
        template_notice.setWordWrap(True)
        template_notice.setStyleSheet(
            "color: #ffb74d; background-color: #2a2418; border: 1px solid #665530;"
            "padding: 8px; border-radius: 4px;"
        )
        preview_right_layout.addWidget(template_notice)

        layout_mode_row = QHBoxLayout()
        layout_mode_row.addWidget(QLabel("検出モード:"))
        self.template_layout_mode_combo = QComboBox()
        self.template_layout_mode_combo.addItems(["自動（列名検索）", "手動"])
        self.template_layout_mode_combo.currentIndexChanged.connect(self._on_template_layout_mode_changed)
        layout_mode_row.addWidget(self.template_layout_mode_combo)
        self.template_analyze_btn = QPushButton("テンプレート再解析")
        self.template_analyze_btn.setToolTip("選択中のAmazonテンプレートから書き込み位置を自動検出します")
        self.template_analyze_btn.clicked.connect(self.analyze_amazon_template_layout)
        layout_mode_row.addWidget(self.template_analyze_btn)
        layout_mode_row.addStretch()
        preview_right_layout.addLayout(layout_mode_row)

        layout_form = QFormLayout()
        self.template_sku_col_edit = QLineEdit("A")
        self.template_sku_col_edit.setMaximumWidth(80)
        self.template_image_start_col_edit = QLineEdit("P")
        self.template_image_start_col_edit.setMaximumWidth(80)
        self.template_image_end_col_edit = QLineEdit("U")
        self.template_image_end_col_edit.setMaximumWidth(80)
        self.template_start_row_spin = QSpinBox()
        self.template_start_row_spin.setRange(1, 200)
        self.template_start_row_spin.setValue(7)
        layout_form.addRow("SKU列:", self.template_sku_col_edit)
        layout_form.addRow("画像開始列:", self.template_image_start_col_edit)
        layout_form.addRow("画像終了列:", self.template_image_end_col_edit)
        layout_form.addRow("入力開始行:", self.template_start_row_spin)
        preview_right_layout.addLayout(layout_form)

        self.template_sku_col_edit.editingFinished.connect(self._save_template_layout_settings)
        self.template_image_start_col_edit.editingFinished.connect(self._save_template_layout_settings)
        self.template_image_end_col_edit.editingFinished.connect(self._save_template_layout_settings)
        self.template_start_row_spin.valueChanged.connect(lambda _v: self._save_template_layout_settings())

        self.template_layout_status_label = QLabel("テンプレート未解析")
        self.template_layout_status_label.setWordWrap(True)
        self.template_layout_status_label.setStyleSheet("color: #ccc;")
        preview_right_layout.addWidget(self.template_layout_status_label)
        preview_right_layout.addStretch()

        preview_splitter = QSplitter(Qt.Horizontal)
        preview_splitter.addWidget(preview_left)
        preview_splitter.addWidget(preview_right)
        preview_splitter.setStretchFactor(0, 1)
        preview_splitter.setStretchFactor(1, 1)
        preview_splitter.setSizes([500, 500])
        preview_group_layout.addWidget(preview_splitter)
        layout.addWidget(preview_group)

        # URL画像プレビュー用（非同期・urllibで取得して確実に表示）
        self._registration_preview_pending_url = ""
        self._registration_preview_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._registration_preview_future = None
        # シグナル接続（バックグラウンドスレッドからメインスレッドへ）
        self._preview_image_ready.connect(self._on_preview_image_ready)
        self._preview_image_error.connect(self._on_preview_image_error)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # テンプレートファイル指定
        template_label = QLabel("テンプレート:")
        button_layout.addWidget(template_label)
        
        self.template_file_edit = QLineEdit()
        self.template_file_edit.setPlaceholderText("AmazonテンプレートExcelファイルを選択...")
        self.template_file_edit.setMinimumWidth(300)
        self.template_file_edit.setReadOnly(True)
        button_layout.addWidget(self.template_file_edit)
        
        self.template_file_browse_btn = QPushButton("参照...")
        self.template_file_browse_btn.setToolTip("AmazonテンプレートExcelファイルを選択します")
        self.template_file_browse_btn.clicked.connect(self.browse_template_file)
        button_layout.addWidget(self.template_file_browse_btn)
        
        # Amazonテンプレート保存先のデフォルトフォルダ設定ボタン
        self.template_save_root_btn = QPushButton("保存先デフォルト")
        self.template_save_root_btn.setToolTip("仕入れフォルダ配下など、Amazonテンプレートを書き出す起点フォルダを設定します。")
        self.template_save_root_btn.clicked.connect(self.set_amazon_template_root_dir)
        button_layout.addWidget(self.template_save_root_btn)
        
        # スナップショット保存／読込（実行テスト用）
        self.save_registration_snapshot_btn = QPushButton("スナップ保存")
        self.save_registration_snapshot_btn.setToolTip("現在の一覧を一時保存します（再起動後のテスト用）")
        self.save_registration_snapshot_btn.clicked.connect(self.save_registration_snapshot)
        button_layout.addWidget(self.save_registration_snapshot_btn)

        self.load_registration_snapshot_btn = QPushButton("スナップ読込")
        self.load_registration_snapshot_btn.setToolTip("前回保存したスナップデータを読み込みます")
        self.load_registration_snapshot_btn.clicked.connect(self.load_registration_snapshot)
        button_layout.addWidget(self.load_registration_snapshot_btn)

        self.clear_registration_btn = QPushButton("一覧をクリア")
        self.clear_registration_btn.setToolTip("画像登録リストをすべて削除します")
        self.clear_registration_btn.clicked.connect(self.clear_registration_records)
        button_layout.addWidget(self.clear_registration_btn)

        # 選択行の削除ボタン
        self.delete_registration_row_btn = QPushButton("選択行を削除")
        self.delete_registration_row_btn.setToolTip("選択されている行だけを画像登録リストから削除します")
        self.delete_registration_row_btn.clicked.connect(self.delete_selected_registration_rows)
        button_layout.addWidget(self.delete_registration_row_btn)

        self.upload_to_gcs_btn = QPushButton("GCSアップロード")
        self.upload_to_gcs_btn.setToolTip("選択行（未選択の場合は確認後に全行）の商品画像をGCSにアップロードします")
        self.upload_to_gcs_btn.clicked.connect(self.upload_images_to_gcs)
        button_layout.addWidget(self.upload_to_gcs_btn)

        self.check_existing_gcs_btn = QPushButton("GCS存在チェック")
        self.check_existing_gcs_btn.setToolTip("GCSに既に存在する画像があれば検索し、画像URL欄に自動入力します（ファイル名で検索）")
        self.check_existing_gcs_btn.clicked.connect(self.check_existing_images_in_gcs)
        button_layout.addWidget(self.check_existing_gcs_btn)

        layout.addLayout(button_layout)
        
        # 設定からテンプレートファイルパスを読み込む
        self.load_template_file_setting()


