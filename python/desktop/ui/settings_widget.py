#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
設定ウィジェット

アプリケーション設定
- API接続設定
- デフォルトディレクトリ設定
- 表示設定
- ログ設定
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QCheckBox,
    QGroupBox, QTabWidget, QTextEdit, QFileDialog,
    QMessageBox, QComboBox, QSlider, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QProgressDialog,
    QApplication,
)
from PySide6.QtCore import Qt, QSettings, Signal, QThread
from PySide6.QtGui import QFont
import json
from datetime import datetime
from pathlib import Path


class _BackupWorker(QThread):
    finished_with_result = Signal(object)

    def __init__(
        self,
        dest_dir: Path,
        *,
        include_config: bool,
        keep_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self._dest_dir = dest_dir
        self._include_config = include_config
        self._keep_count = keep_count

    def run(self) -> None:
        try:
            from services.backup_service import create_backup
        except ImportError:
            from desktop.services.backup_service import create_backup  # type: ignore
        result = create_backup(
            self._dest_dir,
            include_config=self._include_config,
            keep_count=self._keep_count,
        )
        self.finished_with_result.emit(result)


class _RestoreWorker(QThread):
    finished_with_result = Signal(object)

    def __init__(
        self,
        zip_path: Path,
        *,
        include_config: bool,
        parent=None,
    ):
        super().__init__(parent)
        self._zip_path = zip_path
        self._include_config = include_config

    def run(self) -> None:
        try:
            from services.backup_service import restore_from_zip
        except ImportError:
            from desktop.services.backup_service import restore_from_zip  # type: ignore
        result = restore_from_zip(
            self._zip_path,
            include_config_override=self._include_config,
            close_connections=None,
        )
        self.finished_with_result.emit(result)


class SettingsWidget(QWidget):
    """設定ウィジェット"""
    
    settings_changed = Signal(dict)  # 設定変更シグナル
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.settings = QSettings("HIRIO", "DesktopApp")
        self._backup_worker: _BackupWorker | None = None
        self._restore_worker: _RestoreWorker | None = None
        self._backup_progress: QProgressDialog | None = None
        
        # UIの初期化
        self.setup_ui()
        self.load_settings()
        
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # タブウィジェットの作成
        tab_widget = QTabWidget()
        
        # 各設定タブの追加
        self.setup_api_tab(tab_widget)
        self.setup_display_tab(tab_widget)
        self.setup_advanced_tab(tab_widget)
        self.setup_db_settings_tab(tab_widget)
        self.setup_backup_tab(tab_widget)
        self.setup_flea_market_settings_tab(tab_widget)
        self.setup_about_tab(tab_widget)
        
        layout.addWidget(tab_widget)
        
        # 下部：保存・リセットボタン
        self.setup_action_buttons(layout)
        
    def setup_api_tab(self, parent):
        """API設定タブ"""
        api_widget = QWidget()
        layout = QVBoxLayout(api_widget)
        
        # API接続設定
        api_group = QGroupBox("API接続設定")
        api_layout = QGridLayout(api_group)
        
        # ベースURL
        api_layout.addWidget(QLabel("APIベースURL:"), 0, 0)
        self.api_url_edit = QLineEdit("http://localhost:8000")
        self.api_url_edit.setPlaceholderText("http://localhost:8000")
        api_layout.addWidget(self.api_url_edit, 0, 1)
        
        # タイムアウト設定
        api_layout.addWidget(QLabel("タイムアウト(秒):"), 1, 0)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 900)
        self.timeout_spin.setValue(120)
        self.timeout_spin.setToolTip(
            "価格改定プレビューは行数が多いと時間がかかります。\n"
            "タイムアウトが出る場合は 300〜600 秒に増やしてください。"
        )
        api_layout.addWidget(self.timeout_spin, 1, 1)
        
        # 接続テストボタン
        self.test_connection_btn = QPushButton("接続テスト")
        self.test_connection_btn.clicked.connect(self.test_api_connection)
        api_layout.addWidget(self.test_connection_btn, 2, 0, 1, 2)
        
        layout.addWidget(api_group)

        # 外部サービス APIキー（QSettings キーは従来どおり・値は保持）
        ext_keys_group = QGroupBox("外部APIキー")
        ext_layout = QGridLayout(ext_keys_group)

        ext_layout.addWidget(QLabel("Google Maps APIキー:"), 0, 0)
        self.maps_api_key_edit = QLineEdit()
        self.maps_api_key_edit.setPlaceholderText(
            "Maps Embed API / Places API (New) 用（Gemini キーとは別）"
        )
        self.maps_api_key_edit.setEchoMode(QLineEdit.Password)
        self.maps_api_key_edit.setClearButtonEnabled(True)
        self.maps_api_key_edit.setToolTip(
            "ルート地図表示・店舗の住所/緯度経度取得に使用します。\n"
            "Cloud Console で Maps Embed API と Places API (New) を有効化したキーを入力してください。"
        )
        ext_layout.addWidget(self.maps_api_key_edit, 0, 1)
        maps_toggle_btn = QPushButton("表示")
        maps_toggle_btn.setCheckable(True)
        maps_toggle_btn.setMaximumWidth(60)

        def _toggle_maps_visibility(checked: bool) -> None:
            self.maps_api_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            maps_toggle_btn.setText("非表示" if checked else "表示")

        maps_toggle_btn.toggled.connect(_toggle_maps_visibility)
        ext_layout.addWidget(maps_toggle_btn, 0, 2)
        maps_test_btn = QPushButton("テスト")
        maps_test_btn.setMaximumWidth(60)
        maps_test_btn.setToolTip("Places API (New) で接続を確認します")
        maps_test_btn.clicked.connect(self.test_maps_api_key)
        ext_layout.addWidget(maps_test_btn, 0, 3)

        ext_layout.addWidget(QLabel("Gemini APIキー:"), 1, 0)
        self.gemini_api_key_edit = QLineEdit()
        self.gemini_api_key_edit.setPlaceholderText("（オプション）Gemini APIキー")
        self.gemini_api_key_edit.setEchoMode(QLineEdit.Password)
        self.gemini_api_key_edit.setClearButtonEnabled(True)
        ext_layout.addWidget(self.gemini_api_key_edit, 1, 1)
        gemini_toggle_btn = QPushButton("表示")
        gemini_toggle_btn.setCheckable(True)
        gemini_toggle_btn.setMaximumWidth(60)

        def _toggle_gemini_visibility(checked: bool) -> None:
            self.gemini_api_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            gemini_toggle_btn.setText("非表示" if checked else "表示")

        gemini_toggle_btn.toggled.connect(_toggle_gemini_visibility)
        ext_layout.addWidget(gemini_toggle_btn, 1, 2)
        gemini_test_btn = QPushButton("テスト")
        gemini_test_btn.setMaximumWidth(60)
        gemini_test_btn.setToolTip("APIキーと選択中モデルで接続を確認します")
        gemini_test_btn.clicked.connect(self.test_gemini_api_key)
        ext_layout.addWidget(gemini_test_btn, 1, 3)

        ext_layout.addWidget(QLabel("Geminiモデル:"), 2, 0)
        try:
            from utils.gemini_model_helper import resolve_gemini_flash_model
        except ImportError:
            from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
        self.gemini_model_label = QLabel(resolve_gemini_flash_model())
        self.gemini_model_label.setToolTip(
            "HIRIO は gemini-flash-latest（Google 管理の最新 Flash エイリアス）を第一候補に使います。\n"
            "利用不可の場合は flash-lite 等へ自動フォールバックし、API の list_models でも探索します。\n"
            "レシートOCR・Keepa解釈・カスタマー対応AIなど共通です。"
        )
        self.gemini_model_label.setStyleSheet("color: #adb5bd; padding: 4px 0;")
        ext_layout.addWidget(self.gemini_model_label, 2, 1, 1, 2)

        ext_layout.addWidget(QLabel("Keepa APIキー:"), 3, 0)
        self.keepa_api_key_edit = QLineEdit()
        self.keepa_api_key_edit.setPlaceholderText("（任意）Keepa APIキー（ASINから商品情報を取得）")
        self.keepa_api_key_edit.setEchoMode(QLineEdit.Password)
        self.keepa_api_key_edit.setClearButtonEnabled(True)
        ext_layout.addWidget(self.keepa_api_key_edit, 3, 1)
        keepa_toggle_btn = QPushButton("表示")
        keepa_toggle_btn.setCheckable(True)
        keepa_toggle_btn.setMaximumWidth(60)

        def _toggle_keepa_visibility(checked: bool) -> None:
            self.keepa_api_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            keepa_toggle_btn.setText("非表示" if checked else "表示")

        keepa_toggle_btn.toggled.connect(_toggle_keepa_visibility)
        ext_layout.addWidget(keepa_toggle_btn, 3, 2)
        keepa_test_btn = QPushButton("テスト")
        keepa_test_btn.setMaximumWidth(60)
        keepa_test_btn.setToolTip("Keepa APIキーの有効性を確認します（トークン残量表示）")
        keepa_test_btn.clicked.connect(self.test_keepa_api_key)
        ext_layout.addWidget(keepa_test_btn, 3, 3)

        ext_hint = QLabel(
            "Maps / Gemini / Keepa はそれぞれ別キーを使用します。"
            "各キー横の「テスト」で接続確認できます。エラー時は原因と対処法を表示します。"
        )
        ext_hint.setWordWrap(True)
        ext_hint.setStyleSheet("color: #adb5bd; font-size: 11px;")
        ext_layout.addWidget(ext_hint, 4, 0, 1, 4)

        layout.addWidget(ext_keys_group)
        
        # デフォルトディレクトリ設定
        dir_group = QGroupBox("デフォルトディレクトリ設定")
        dir_layout = QGridLayout(dir_group)
        
        # CSVファイル用ディレクトリ
        dir_layout.addWidget(QLabel("CSVファイル用:"), 0, 0)
        self.csv_dir_edit = QLineEdit()
        self.csv_dir_edit.setPlaceholderText("CSVファイルのデフォルトディレクトリ")
        dir_layout.addWidget(self.csv_dir_edit, 0, 1)
        
        csv_browse_btn = QPushButton("参照")
        csv_browse_btn.clicked.connect(lambda: self.browse_directory(self.csv_dir_edit))
        dir_layout.addWidget(csv_browse_btn, 0, 2)
        
        # 結果保存用ディレクトリ
        dir_layout.addWidget(QLabel("結果保存用:"), 1, 0)
        self.result_dir_edit = QLineEdit()
        self.result_dir_edit.setPlaceholderText("結果保存のデフォルトディレクトリ")
        dir_layout.addWidget(self.result_dir_edit, 1, 1)
        
        result_browse_btn = QPushButton("参照")
        result_browse_btn.clicked.connect(lambda: self.browse_directory(self.result_dir_edit))
        dir_layout.addWidget(result_browse_btn, 1, 2)
        
        layout.addWidget(dir_group)
        
        layout.addStretch()
        parent.addTab(api_widget, "API設定")
        
    def setup_display_tab(self, parent):
        """表示設定タブ"""
        display_widget = QWidget()
        layout = QVBoxLayout(display_widget)
        
        # テーブル表示設定
        table_group = QGroupBox("テーブル表示設定")
        table_layout = QGridLayout(table_group)
        
        # 行の高さ
        table_layout.addWidget(QLabel("行の高さ:"), 0, 0)
        self.row_height_spin = QSpinBox()
        self.row_height_spin.setRange(20, 100)
        self.row_height_spin.setValue(25)
        table_layout.addWidget(self.row_height_spin, 0, 1)
        
        # フォントサイズ
        table_layout.addWidget(QLabel("フォントサイズ:"), 1, 0)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 16)
        self.font_size_spin.setValue(9)
        table_layout.addWidget(self.font_size_spin, 1, 1)
        
        # 交互行色
        self.alternating_colors_cb = QCheckBox("交互行色を有効にする")
        self.alternating_colors_cb.setChecked(True)
        table_layout.addWidget(self.alternating_colors_cb, 2, 0, 1, 2)
        
        # ソート機能
        self.sorting_enabled_cb = QCheckBox("ソート機能を有効にする")
        self.sorting_enabled_cb.setChecked(True)
        table_layout.addWidget(self.sorting_enabled_cb, 3, 0, 1, 2)
        
        layout.addWidget(table_group)
        
        # 価格改定結果表示設定
        result_group = QGroupBox("価格改定結果表示設定")
        result_layout = QGridLayout(result_group)
        
        # Title列の文字数制限
        result_layout.addWidget(QLabel("Title列の文字数制限:"), 0, 0)
        self.title_limit_spin = QSpinBox()
        self.title_limit_spin.setRange(20, 100)
        self.title_limit_spin.setValue(50)
        result_layout.addWidget(self.title_limit_spin, 0, 1)
        
        # 価格変更の色分け
        self.price_color_cb = QCheckBox("価格変更の色分けを有効にする")
        self.price_color_cb.setChecked(True)
        result_layout.addWidget(self.price_color_cb, 1, 0, 1, 2)
        
        # ツールチップ表示
        self.tooltip_enabled_cb = QCheckBox("ツールチップを有効にする")
        self.tooltip_enabled_cb.setChecked(True)
        result_layout.addWidget(self.tooltip_enabled_cb, 2, 0, 1, 2)
        
        layout.addWidget(result_group)
        
        layout.addStretch()
        parent.addTab(display_widget, "表示設定")
        
    def setup_advanced_tab(self, parent):
        """詳細設定タブ"""
        advanced_widget = QWidget()
        layout = QVBoxLayout(advanced_widget)
        
        # 3-6-9版
        pro_group = QGroupBox("3-6-9版")
        pro_layout = QGridLayout(pro_group)
        self.pro_enabled_cb = QCheckBox("3-6-9版を有効にする")
        self.pro_enabled_cb.setToolTip("有効にすると、3-6-9版機能が利用できます。今後の機能追加は3-6-9版を前提に進めます。")
        # チェック変更時に即QSettingsへ書き込み（他タブの3-6-9などがすぐ反映される）
        self.pro_enabled_cb.toggled.connect(self._on_pro_toggled)
        pro_layout.addWidget(self.pro_enabled_cb, 0, 0, 1, 2)
        layout.addWidget(pro_group)

        recording_group = QGroupBox("デモモード")
        recording_layout = QVBoxLayout(recording_group)
        self.recording_mode_cb = QCheckBox("デモモードを有効にする")
        self.recording_mode_cb.setToolTip(
            "デモ・説明用です。\n"
            "ON: 仕入・古物台帳などは仮想DBにのみ保存され、本番データには反映されません。\n"
            "過去の仕入リストからSKUが自動入力されることもありません。\n"
            "OFF: 仮想DBのデータは削除されます。"
        )
        recording_layout.addWidget(self.recording_mode_cb)
        self.recording_mode_status_label = QLabel("")
        self.recording_mode_status_label.setWordWrap(True)
        recording_layout.addWidget(self.recording_mode_status_label)
        recording_note = QLabel(
            "チェックを入れるとすぐ反映されます（「設定を保存」ボタンは不要）。"
            "右下ステータスバーに「● デモモード」と表示されます。"
        )
        recording_note.setWordWrap(True)
        recording_note.setStyleSheet("color: #666;")
        recording_layout.addWidget(recording_note)
        layout.addWidget(recording_group)
        self._recording_mode_loading = False
        self.recording_mode_cb.toggled.connect(self._on_recording_toggled)
        
        # パフォーマンス設定
        perf_group = QGroupBox("パフォーマンス設定")
        perf_layout = QGridLayout(perf_group)
        
        # 最大表示行数
        perf_layout.addWidget(QLabel("最大表示行数:"), 0, 0)
        self.max_rows_spin = QSpinBox()
        self.max_rows_spin.setRange(100, 10000)
        self.max_rows_spin.setValue(1000)
        perf_layout.addWidget(self.max_rows_spin, 0, 1)
        
        # バッチサイズ
        perf_layout.addWidget(QLabel("バッチサイズ:"), 1, 0)
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(10, 1000)
        self.batch_size_spin.setValue(50)
        perf_layout.addWidget(self.batch_size_spin, 1, 1)
        
        # 自動保存
        self.auto_save_cb = QCheckBox("処理結果の自動保存を有効にする")
        self.auto_save_cb.setChecked(False)
        perf_layout.addWidget(self.auto_save_cb, 2, 0, 1, 2)

        # 仕入DB段階読み込み（データベース管理タブの高速化。OFFで従来の全件一括描画）
        self.purchase_incremental_cb = QCheckBox("仕入DBを段階読み込みする（推奨・大量データ向け）")
        self.purchase_incremental_cb.setChecked(True)
        self.purchase_incremental_cb.setToolTip(
            "ON: 先頭100件だけ先に表示し、スクロールで追加読み込み\n"
            "OFF: 従来どおり全行を一度に描画"
        )
        perf_layout.addWidget(self.purchase_incremental_cb, 3, 0, 1, 2)

        perf_layout.addWidget(QLabel("仕入DB 1回の表示行数:"), 4, 0)
        self.purchase_page_size_spin = QSpinBox()
        self.purchase_page_size_spin.setRange(20, 500)
        self.purchase_page_size_spin.setValue(100)
        self.purchase_page_size_spin.setToolTip("テーブルに一度に追加する行数")
        perf_layout.addWidget(self.purchase_page_size_spin, 4, 1)

        perf_layout.addWidget(QLabel("仕入DB augmentバッチ:"), 5, 0)
        self.purchase_augment_batch_spin = QSpinBox()
        self.purchase_augment_batch_spin.setRange(20, 500)
        self.purchase_augment_batch_spin.setValue(100)
        self.purchase_augment_batch_spin.setToolTip(
            "バックグラウンドで商品DB等を照会する件数（大きいほど一括だがUI負荷増）"
        )
        perf_layout.addWidget(self.purchase_augment_batch_spin, 5, 1)
        
        layout.addWidget(perf_group)
        
        # ログ設定
        log_group = QGroupBox("ログ設定")
        log_layout = QGridLayout(log_group)
        
        # ログレベル
        log_layout.addWidget(QLabel("ログレベル:"), 0, 0)
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        log_layout.addWidget(self.log_level_combo, 0, 1)
        
        # ログファイル保存
        self.log_file_cb = QCheckBox("ログファイルを保存する")
        self.log_file_cb.setChecked(True)
        log_layout.addWidget(self.log_file_cb, 1, 0, 1, 2)
        
        # ログファイルパス
        log_layout.addWidget(QLabel("ログファイルパス:"), 2, 0)
        self.log_file_edit = QLineEdit("logs/hirio.log")
        log_layout.addWidget(self.log_file_edit, 2, 1)
        
        log_browse_btn = QPushButton("参照")
        log_browse_btn.clicked.connect(lambda: self.browse_file(self.log_file_edit, "ログファイル"))
        log_layout.addWidget(log_browse_btn, 2, 2)
        
        layout.addWidget(log_group)
        
        # OCR設定
        ocr_group = QGroupBox("OCR設定")
        ocr_layout = QGridLayout(ocr_group)
        
        # Tesseract実行ファイルパス
        ocr_layout.addWidget(QLabel("Tesseract実行ファイル:"), 0, 0)
        self.tesseract_cmd_edit = QLineEdit()
        self.tesseract_cmd_edit.setPlaceholderText("C:\\Program Files\\Tesseract-OCR\\tesseract.exe")
        ocr_layout.addWidget(self.tesseract_cmd_edit, 0, 1)
        
        tesseract_browse_btn = QPushButton("参照")
        tesseract_browse_btn.clicked.connect(lambda: self.browse_file(self.tesseract_cmd_edit, "Tesseract実行ファイル", "実行ファイル (*.exe)"))
        ocr_layout.addWidget(tesseract_browse_btn, 0, 2)
        
        # Tessdataディレクトリパス（tessdata_best用）
        ocr_layout.addWidget(QLabel("Tessdataディレクトリ:"), 1, 0)
        self.tessdata_dir_edit = QLineEdit()
        self.tessdata_dir_edit.setPlaceholderText("C:\\Program Files\\Tesseract-OCR\\tessdata")
        ocr_layout.addWidget(self.tessdata_dir_edit, 1, 1)
        
        tessdata_browse_btn = QPushButton("参照")
        tessdata_browse_btn.clicked.connect(lambda: self.browse_directory(self.tessdata_dir_edit))
        ocr_layout.addWidget(tessdata_browse_btn, 1, 2)
        
        # Google Cloud Vision API認証情報パス（オプション）
        ocr_layout.addWidget(QLabel("GCV認証情報(JSON):"), 2, 0)
        self.gcv_credentials_edit = QLineEdit()
        self.gcv_credentials_edit.setPlaceholderText("（オプション）Google Cloud Vision API認証情報")
        ocr_layout.addWidget(self.gcv_credentials_edit, 2, 1)
        
        gcv_browse_btn = QPushButton("参照")
        gcv_browse_btn.clicked.connect(lambda: self.browse_file(self.gcv_credentials_edit, "GCV認証情報", "JSONファイル (*.json)"))
        ocr_layout.addWidget(gcv_browse_btn, 2, 2)

        self.test_ocr_btn = QPushButton("OCR設定テスト")
        self.test_ocr_btn.clicked.connect(self.test_ocr_settings)
        ocr_layout.addWidget(self.test_ocr_btn, 3, 0, 1, 3)
        
        layout.addWidget(ocr_group)

        # Amazon（自店セラーID — Keepa オファー表示などとの突き合わせ用）
        amazon_group = QGroupBox("Amazon")
        amazon_layout = QGridLayout(amazon_group)
        amazon_layout.addWidget(QLabel("自店のセラーID:"), 0, 0)
        self.amazon_seller_id_edit = QLineEdit()
        self.amazon_seller_id_edit.setPlaceholderText(
            "例: A1VC38T7YXB528（Seller Central のマーチャントID。Keepaの sellerId と一致する場合があります）"
        )
        self.amazon_seller_id_edit.setClearButtonEnabled(True)
        amazon_layout.addWidget(self.amazon_seller_id_edit, 0, 1)
        amazon_layout.addWidget(QLabel("FBA料金シミュレーターURL:"), 1, 0)
        self.amazon_fba_simulator_url_edit = QLineEdit()
        self.amazon_fba_simulator_url_edit.setPlaceholderText("https://sellercentral.amazon.co.jp/revcalpublic?lang=ja_JP")
        self.amazon_fba_simulator_url_edit.setClearButtonEnabled(True)
        amazon_layout.addWidget(self.amazon_fba_simulator_url_edit, 1, 1)
        amazon_layout.addWidget(QLabel("出品ファイル(L)アップロードURL:"), 2, 0)
        self.amazon_inventory_loader_upload_url_edit = QLineEdit()
        try:
            from utils.settings_helper import DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL
        except ImportError:
            from desktop.utils.settings_helper import DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL
        self.amazon_inventory_loader_upload_url_edit.setPlaceholderText(
            DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL
        )
        self.amazon_inventory_loader_upload_url_edit.setClearButtonEnabled(True)
        self.amazon_inventory_loader_upload_url_edit.setToolTip(
            "画像登録タブの「Amazonアップロードページを開く」で使用します。"
        )
        amazon_layout.addWidget(self.amazon_inventory_loader_upload_url_edit, 3, 1)
        layout.addWidget(amazon_group)

        # プライスター（CSV出品・価格改定画面URL）
        pricetar_group = QGroupBox("プライスター")
        pricetar_layout = QGridLayout(pricetar_group)
        pricetar_layout.addWidget(QLabel("CSV出品用URL:"), 0, 0)
        self.pricetar_listing_url_edit = QLineEdit()
        self.pricetar_listing_url_edit.setPlaceholderText(
            "https://jp3.pricetar.com/seller/product/csvwarehousing"
        )
        self.pricetar_listing_url_edit.setClearButtonEnabled(True)
        self.pricetar_listing_url_edit.setToolTip(
            "仕入管理の「ブラウザで開く」で使用します。\n"
            "プライスターの「CSVファイルで出品」画面のURLを入力してください。"
        )
        pricetar_layout.addWidget(self.pricetar_listing_url_edit, 0, 1)

        pricetar_layout.addWidget(QLabel("CSV価格改定用URL:"), 1, 0)
        self.pricetar_repricing_url_edit = QLineEdit()
        self.pricetar_repricing_url_edit.setPlaceholderText(
            "https://jp3.pricetar.com/seller/product/csvproductedit"
        )
        self.pricetar_repricing_url_edit.setClearButtonEnabled(True)
        self.pricetar_repricing_url_edit.setToolTip(
            "価格改定タブの「ブラウザで開く」で使用します。\n"
            "プライスターの「CSVかんたん在庫編集」画面のURLを入力してください。"
        )
        pricetar_layout.addWidget(self.pricetar_repricing_url_edit, 1, 1)
        layout.addWidget(pricetar_group)
        
        layout.addStretch()
        parent.addTab(advanced_widget, "詳細設定")
    
    def setup_db_settings_tab(self, parent):
        """DB設定タブ（チェーン店コードマッピング）"""
        from database.store_db import StoreDatabase
        from ui.store_master_widget import (
            OnlinePlatformListWidget,
            FleaMarketListWidget,
        )
        
        db_widget = QWidget()
        layout = QVBoxLayout(db_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        db_tabs = QTabWidget()

        # チェーン店コードマッピングタブ
        chain_mapping_widget = QWidget()
        chain_layout = QVBoxLayout(chain_mapping_widget)
        chain_layout.setContentsMargins(0, 0, 0, 0)
        chain_layout.setSpacing(10)

        info_label = QLabel("チェーン店名とコードのマッピングを設定します。店舗名に含まれる文字列をパターンとして登録できます。")
        info_label.setWordWrap(True)
        chain_layout.addWidget(info_label)

        table_group = QGroupBox("チェーン店コードマッピング")
        table_layout = QVBoxLayout(table_group)

        self.chain_mapping_table = QTableWidget()
        self.chain_mapping_table.setColumnCount(6)
        self.chain_mapping_table.setHorizontalHeaderLabels([
            "ID", "チェーン店コード", "店舗名パターン", "優先度", "有効", "その他"
        ])
        self.chain_mapping_table.setAlternatingRowColors(True)
        self.chain_mapping_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.chain_mapping_table.setEditTriggers(QTableWidget.NoEditTriggers)

        header = self.chain_mapping_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        table_layout.addWidget(self.chain_mapping_table)

        others_info_label = QLabel(
            "「その他」列が「はい」の行は、どのパターンにも当てはまらない店舗に付与するデフォルトのチェーンコードとして使われます。\n"
            "※ 通常は1行のみ「はい」にすることを推奨します。"
        )
        others_info_label.setWordWrap(True)
        others_info_label.setStyleSheet("color: #666; font-size: 9pt;")
        table_layout.addWidget(others_info_label)

        button_layout = QHBoxLayout()

        add_btn = QPushButton("追加")
        add_btn.clicked.connect(lambda: self.add_chain_mapping())
        button_layout.addWidget(add_btn)

        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(lambda: self.edit_chain_mapping())
        button_layout.addWidget(edit_btn)

        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(lambda: self.delete_chain_mapping())
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
            }
        """)
        button_layout.addWidget(delete_btn)

        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(lambda: self.load_chain_mappings())
        button_layout.addWidget(refresh_btn)

        button_layout.addStretch()
        table_layout.addLayout(button_layout)

        chain_layout.addWidget(table_group)
        chain_layout.addStretch()

        self.store_db = StoreDatabase()
        self.load_chain_mappings()

        db_tabs.addTab(chain_mapping_widget, "チェーン店コード")
        self.online_platform_db_widget = OnlinePlatformListWidget()
        db_tabs.addTab(self.online_platform_db_widget, "ECコード")
        self.flea_market_widget = FleaMarketListWidget()
        db_tabs.addTab(self.flea_market_widget, "フリマコード")

        layout.addWidget(db_tabs)
        parent.addTab(db_widget, "店舗コード設定")

    def reinit_databases(self) -> None:
        """デモモード切替後に店舗マスタDB接続を差し替える。"""
        if hasattr(self, "store_db"):
            conn = getattr(self.store_db, "conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                self.store_db.conn = None
        from database.store_db import StoreDatabase
        self.store_db = StoreDatabase()
        if hasattr(self, "chain_mapping_table"):
            self.load_chain_mappings()
        if hasattr(self, "online_platform_db_widget") and hasattr(
            self.online_platform_db_widget, "reload_data"
        ):
            self.online_platform_db_widget.reload_data()
        if hasattr(self, "flea_market_widget") and hasattr(
            self.flea_market_widget, "reload_data"
        ):
            self.flea_market_widget.reload_data()

    def setup_backup_tab(self, parent):
        """データバックアップタブ"""
        backup_widget = QWidget()
        layout = QVBoxLayout(backup_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        info_label = QLabel(
            "業務データ（DB・設定JSON）を ZIP でバックアップします。\n"
            "保存先を Google Drive などの同期フォルダに指定すると、クラウドにも自動コピーできます。\n"
            "※ 使用中の hirio.db を直接同期しないでください。完成した ZIP のみを同期してください。"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        folder_group = QGroupBox("バックアップ保存先")
        folder_layout = QGridLayout(folder_group)

        folder_layout.addWidget(QLabel("フォルダ:"), 0, 0)
        self.backup_folder_edit = QLineEdit()
        self.backup_folder_edit.setPlaceholderText(
            r"例: D:\Google Drive\マイドライブ\HIRIO_Backup"
        )
        folder_layout.addWidget(self.backup_folder_edit, 0, 1)

        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._browse_backup_folder)
        folder_layout.addWidget(browse_btn, 0, 2)

        self.backup_auto_on_exit_cb = QCheckBox("アプリ終了時に自動バックアップ")
        self.backup_auto_on_exit_cb.setToolTip(
            "保存先フォルダが設定されている場合のみ、終了時に ZIP を作成します。"
        )
        folder_layout.addWidget(self.backup_auto_on_exit_cb, 1, 0, 1, 3)

        folder_layout.addWidget(QLabel("保持するバックアップ数:"), 2, 0)
        self.backup_keep_count_spin = QSpinBox()
        self.backup_keep_count_spin.setRange(1, 30)
        self.backup_keep_count_spin.setValue(7)
        self.backup_keep_count_spin.setToolTip("古い ZIP は自動削除されます（最新 N 個を残す）")
        folder_layout.addWidget(self.backup_keep_count_spin, 2, 1, 1, 2)

        self.backup_include_config_cb = QCheckBox("config フォルダも含める（inventory_settings / reprice_rules）")
        self.backup_include_config_cb.setChecked(True)
        folder_layout.addWidget(self.backup_include_config_cb, 3, 0, 1, 3)

        for widget in (
            self.backup_folder_edit,
            self.backup_auto_on_exit_cb,
            self.backup_keep_count_spin,
            self.backup_include_config_cb,
        ):
            if hasattr(widget, "editingFinished"):
                widget.editingFinished.connect(self._save_backup_settings_to_qsettings)
            if hasattr(widget, "toggled"):
                widget.toggled.connect(self._save_backup_settings_to_qsettings)
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._save_backup_settings_to_qsettings)

        layout.addWidget(folder_group)

        action_group = QGroupBox("操作")
        action_layout = QVBoxLayout(action_group)

        btn_row = QHBoxLayout()
        self.backup_now_btn = QPushButton("今すぐバックアップ")
        self.backup_now_btn.clicked.connect(self._run_backup_now)
        btn_row.addWidget(self.backup_now_btn)

        self.backup_restore_btn = QPushButton("バックアップから復元...")
        self.backup_restore_btn.clicked.connect(self._run_restore_from_backup)
        btn_row.addWidget(self.backup_restore_btn)

        refresh_btn = QPushButton("一覧を更新")
        refresh_btn.clicked.connect(self._refresh_backup_status)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        action_layout.addLayout(btn_row)

        self.backup_status_label = QLabel("バックアップ履歴を読み込んでいます...")
        self.backup_status_label.setWordWrap(True)
        self.backup_status_label.setStyleSheet("color: #9eb8d0;")
        action_layout.addWidget(self.backup_status_label)

        layout.addWidget(action_group)
        layout.addStretch()
        parent.addTab(backup_widget, "データバックアップ")

    def _browse_backup_folder(self) -> None:
        current = self.backup_folder_edit.text().strip()
        start_dir = current if current else str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self,
            "バックアップ保存先フォルダを選択",
            start_dir,
        )
        if folder:
            self.backup_folder_edit.setText(folder)
            self._save_backup_settings_to_qsettings()
            self._refresh_backup_status()

    def _save_backup_settings_to_qsettings(self) -> None:
        self.settings.setValue("backup/folder", self.backup_folder_edit.text().strip())
        self.settings.setValue("backup/auto_on_exit", self.backup_auto_on_exit_cb.isChecked())
        self.settings.setValue("backup/keep_count", self.backup_keep_count_spin.value())
        self.settings.setValue("backup/include_config", self.backup_include_config_cb.isChecked())

    def _get_backup_service(self):
        try:
            from services.backup_service import (
                create_backup,
                get_backup_folder,
                list_backup_archives,
                restore_from_zip,
            )
        except ImportError:
            from desktop.services.backup_service import (  # type: ignore
                create_backup,
                get_backup_folder,
                list_backup_archives,
                restore_from_zip,
            )
        return create_backup, get_backup_folder, list_backup_archives, restore_from_zip

    def _refresh_backup_status(self) -> None:
        _, get_backup_folder, list_backup_archives, _ = self._get_backup_service()
        folder_text = self.backup_folder_edit.text().strip() or get_backup_folder()
        last_at = self.settings.value("backup/last_success_at", "")
        last_path = self.settings.value("backup/last_success_path", "")

        lines = []
        if folder_text:
            folder = Path(folder_text)
            archives = list_backup_archives(folder) if folder.is_dir() else []
            lines.append(f"保存先: {folder_text}")
            if archives:
                latest = archives[0]
                lines.append(
                    f"最新バックアップ: {latest.name} "
                    f"({datetime.fromtimestamp(latest.stat().st_mtime).strftime('%Y-%m-%d %H:%M')})"
                )
                lines.append(f"保存件数: {len(archives)} 件")
            else:
                lines.append("保存済みバックアップ: なし")
        else:
            lines.append("保存先: 未設定")

        if last_at:
            lines.append(f"最終成功: {last_at}")
        if last_path:
            lines.append(f"最終ファイル: {last_path}")

        self.backup_status_label.setText("\n".join(lines))

    def _set_backup_busy(self, busy: bool, message: str = "") -> None:
        self.backup_now_btn.setEnabled(not busy)
        self.backup_restore_btn.setEnabled(not busy)
        if busy:
            self.backup_status_label.setText(message or "バックアップを作成しています。しばらくお待ちください...")
            self.backup_status_label.setStyleSheet("color: #f0c674; font-weight: bold;")
        else:
            self.backup_status_label.setStyleSheet("color: #9eb8d0;")

    def _show_backup_progress(self, title: str, label: str) -> QProgressDialog:
        progress = QProgressDialog(label, None, 0, 0, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        QApplication.processEvents()
        return progress

    def _run_backup_now(self) -> None:
        if self._backup_worker is not None and self._backup_worker.isRunning():
            QMessageBox.information(self, "バックアップ", "バックアップ処理が実行中です。")
            return

        self._save_backup_settings_to_qsettings()

        folder_text = self.backup_folder_edit.text().strip()
        if not folder_text:
            QMessageBox.warning(
                self,
                "バックアップ",
                "バックアップ保存先フォルダを指定してください。",
            )
            return

        dest = Path(folder_text)
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(
                self,
                "バックアップ",
                f"保存先フォルダを作成できませんでした:\n{e}",
            )
            return

        self._set_backup_busy(True, "バックアップを作成しています。DBのサイズによっては数分かかることがあります...")
        self._backup_progress = self._show_backup_progress(
            "バックアップ",
            "データをコピーして ZIP を作成しています...\n画面が一時的に固まって見えても処理は続いています。",
        )

        worker = _BackupWorker(
            dest,
            include_config=self.backup_include_config_cb.isChecked(),
            keep_count=self.backup_keep_count_spin.value(),
            parent=self,
        )
        worker.finished_with_result.connect(self._on_backup_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._backup_worker = worker
        worker.start()

    def _on_backup_worker_finished(self, result) -> None:
        if self._backup_progress is not None:
            self._backup_progress.close()
            self._backup_progress = None

        self._set_backup_busy(False)
        self._backup_worker = None

        if result.success:
            try:
                from services.backup_service import record_backup_success
            except ImportError:
                from desktop.services.backup_service import record_backup_success  # type: ignore
            if result.zip_path is not None:
                record_backup_success(result.zip_path)
            QMessageBox.information(self, "バックアップ完了", result.message)
            self._refresh_backup_status()
        else:
            QMessageBox.critical(self, "バックアップ失敗", result.message)
            self._refresh_backup_status()

    def _run_restore_from_backup(self) -> None:
        if self._restore_worker is not None and self._restore_worker.isRunning():
            QMessageBox.information(self, "復元", "復元処理が実行中です。")
            return

        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            "復元するバックアップ ZIP を選択",
            self.backup_folder_edit.text().strip() or str(Path.home()),
            "HIRIO Backup (*.zip)",
        )
        if not zip_path:
            return

        reply = QMessageBox.warning(
            self,
            "復元の確認",
            "選択したバックアップで現在のデータを上書きします。\n"
            "復元前に現在の data は自動で退避されます。\n\n"
            "完了後はアプリの再起動が必要です。\n"
            "続行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        main_window = self.window()
        if main_window is not None and hasattr(
            main_window, "close_all_database_connections_for_restore"
        ):
            main_window.close_all_database_connections_for_restore()

        self._set_backup_busy(True, "バックアップから復元しています。しばらくお待ちください...")
        self._backup_progress = self._show_backup_progress(
            "復元",
            "バックアップを展開してデータを復元しています...",
        )

        worker = _RestoreWorker(
            Path(zip_path),
            include_config=self.backup_include_config_cb.isChecked(),
            parent=self,
        )
        worker.finished_with_result.connect(self._on_restore_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._restore_worker = worker
        worker.start()

    def _on_restore_worker_finished(self, result) -> None:
        if self._backup_progress is not None:
            self._backup_progress.close()
            self._backup_progress = None

        self._set_backup_busy(False)
        self._restore_worker = None

        if not result.success:
            QMessageBox.critical(self, "復元失敗", result.message)
            self._refresh_backup_status()
            return

        extra = ""
        if result.safety_backup_dir:
            extra = f"\n\n退避先:\n{result.safety_backup_dir}"

        restart_reply = QMessageBox.question(
            self,
            "復元完了",
            result.message + extra + "\n\n今すぐアプリを終了して再起動しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        self._refresh_backup_status()
        if restart_reply == QMessageBox.Yes:
            QApplication.quit()

    def setup_flea_market_settings_tab(self, parent):
        """フリマ設定タブ（手数料率・AI出品文案）"""
        try:
            from ui.flea_market_settings_widget import FleaMarketSettingsWidget
        except ImportError:
            from desktop.ui.flea_market_settings_widget import FleaMarketSettingsWidget
        self.flea_market_settings_widget = FleaMarketSettingsWidget()
        parent.addTab(self.flea_market_settings_widget, "フリマ設定")

    def load_chain_mappings(self):
        """チェーン店コードマッピングを読み込む"""
        mappings = self.store_db.list_chain_store_code_mappings()
        
        self.chain_mapping_table.setRowCount(len(mappings))
        
        for i, mapping in enumerate(mappings):
            # ID
            id_item = QTableWidgetItem(str(mapping.get('id', '')))
            id_item.setData(Qt.UserRole, mapping.get('id'))
            self.chain_mapping_table.setItem(i, 0, id_item)
            
            # チェーン店コード
            code_item = QTableWidgetItem(mapping.get('chain_code', ''))
            self.chain_mapping_table.setItem(i, 1, code_item)
            
            # 店舗名パターン（カンマ区切りで表示）
            patterns = mapping.get('chain_name_patterns', [])
            patterns_text = ', '.join(patterns) if patterns else ''
            pattern_item = QTableWidgetItem(patterns_text)
            self.chain_mapping_table.setItem(i, 2, pattern_item)
            
            # 優先度
            priority_item = QTableWidgetItem(str(mapping.get('priority', 0)))
            self.chain_mapping_table.setItem(i, 3, priority_item)
            
            # 有効/無効
            is_active = mapping.get('is_active', 1)
            active_item = QTableWidgetItem('有効' if is_active else '無効')
            self.chain_mapping_table.setItem(i, 4, active_item)

            # その他（マッチしない店舗用デフォルト）
            is_default_for_others = mapping.get('is_default_for_others', 0)
            others_text = 'はい' if is_default_for_others else ''
            others_item = QTableWidgetItem(others_text)
            self.chain_mapping_table.setItem(i, 5, others_item)
    
    def add_chain_mapping(self):
        """チェーン店コードマッピングを追加"""
        from ui.chain_mapping_dialog import ChainMappingDialog
        
        dialog = ChainMappingDialog(self)
        if dialog.exec() == QDialog.Accepted:
            mapping_data = dialog.get_data()
            try:
                self.store_db.add_chain_store_code_mapping(mapping_data)
                QMessageBox.information(self, "完了", "チェーン店コードマッピングを追加しました")
                self.load_chain_mappings()
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{str(e)}")
    
    def edit_chain_mapping(self):
        """チェーン店コードマッピングを編集"""
        selected = self.chain_mapping_table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.warning(self, "警告", "編集するマッピングを選択してください")
            return
        
        row = selected[0].row()
        id_item = self.chain_mapping_table.item(row, 0)
        mapping_id = id_item.data(Qt.UserRole)
        
        mapping_data = self.store_db.get_chain_store_code_mapping(mapping_id)
        if not mapping_data:
            QMessageBox.warning(self, "エラー", "マッピングデータが見つかりません")
            return
        
        from ui.chain_mapping_dialog import ChainMappingDialog
        dialog = ChainMappingDialog(self, mapping_data=mapping_data)
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_data()
            try:
                self.store_db.update_chain_store_code_mapping(mapping_id, new_data)
                QMessageBox.information(self, "完了", "チェーン店コードマッピングを更新しました")
                self.load_chain_mappings()
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{str(e)}")
    
    def delete_chain_mapping(self):
        """チェーン店コードマッピングを削除"""
        selected = self.chain_mapping_table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.warning(self, "警告", "削除するマッピングを選択してください")
            return
        
        row = selected[0].row()
        id_item = self.chain_mapping_table.item(row, 0)
        mapping_id = id_item.data(Qt.UserRole)
        chain_code = self.chain_mapping_table.item(row, 1).text()
        
        reply = QMessageBox.question(
            self,
            "削除確認",
            f"チェーン店コードマッピング '{chain_code}' を削除しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.store_db.delete_chain_store_code_mapping(mapping_id)
                QMessageBox.information(self, "完了", "チェーン店コードマッピングを削除しました")
                self.load_chain_mappings()
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{str(e)}")
        
    def setup_about_tab(self, parent):
        """アプリケーション情報タブ"""
        about_widget = QWidget()
        layout = QVBoxLayout(about_widget)
        
        # アプリケーション情報
        info_group = QGroupBox("アプリケーション情報")
        info_layout = QVBoxLayout(info_group)
        
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMaximumHeight(200)
        info_text.setHtml("""
        <h3>HIRIO - せどり業務統合システム</h3>
        <p><b>バージョン:</b> 1.0.0</p>
        <p><b>技術スタック:</b> PySide6 + FastAPI + SQLite</p>
        <p><b>開発目標:</b> 年内MVP（仕入管理システム完成）</p>
        <p><b>主要機能:</b></p>
        <ul>
        <li>価格改定機能（既存FastAPI活用）</li>
        <li>仕入管理システム</li>
        <li>古物台帳自動生成</li>
        <li>一括実行ワークフロー</li>
        </ul>
        <p><b>© 2025 HIRIO Project</b></p>
        """)
        info_layout.addWidget(info_text)
        
        layout.addWidget(info_group)
        
        # システム情報
        system_group = QGroupBox("システム情報")
        system_layout = QVBoxLayout(system_group)
        
        system_text = QTextEdit()
        system_text.setReadOnly(True)
        system_text.setMaximumHeight(150)
        system_text.setPlainText(f"""
Python バージョン: {__import__('sys').version}
PySide6 バージョン: {__import__('PySide6').__version__}
作業ディレクトリ: {Path.cwd()}
設定ファイル: {self.settings.fileName()}
        """)
        system_layout.addWidget(system_text)
        
        layout.addWidget(system_group)
        
        layout.addStretch()
        parent.addTab(about_widget, "アプリケーション情報")
        
    def setup_action_buttons(self, parent_layout):
        """アクションボタンの設定"""
        button_layout = QHBoxLayout()
        
        # 保存ボタン
        self.save_btn = QPushButton("設定を保存")
        self.save_btn.clicked.connect(self.save_settings)
        self.save_btn.setStyleSheet("""
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
        """)
        button_layout.addWidget(self.save_btn)
        
        # リセットボタン
        self.reset_btn = QPushButton("設定をリセット")
        self.reset_btn.clicked.connect(self.reset_settings)
        button_layout.addWidget(self.reset_btn)
        
        # デフォルトボタン
        self.default_btn = QPushButton("デフォルトに戻す")
        self.default_btn.clicked.connect(self.load_default_settings)
        button_layout.addWidget(self.default_btn)
        
        button_layout.addStretch()
        parent_layout.addLayout(button_layout)

    def _on_pro_toggled(self, checked: bool):
        """3-6-9版チェック変更時に即QSettingsへ保存（保存ボタンなしで他タブに反映）"""
        self.settings.setValue("pro/enabled", checked)

    def _sync_recording_mode_status_label(self) -> None:
        if not hasattr(self, "recording_mode_status_label"):
            return
        try:
            from utils.settings_helper import is_recording_mode
        except ImportError:
            from desktop.utils.settings_helper import is_recording_mode  # type: ignore
        if is_recording_mode():
            self.recording_mode_status_label.setText("現在: デモモード ON（仮想DB使用中）")
            self.recording_mode_status_label.setStyleSheet("color: #e53935; font-weight: bold;")
        else:
            self.recording_mode_status_label.setText("現在: デモモード OFF（本番DB）")
            self.recording_mode_status_label.setStyleSheet("color: #888;")

    def _notify_recording_mode_changed(self) -> None:
        self.settings_changed.emit(self.get_current_settings())

    def _commit_recording_mode_change(self, new_recording: bool) -> bool:
        """デモモードON/OFFを確定。キャンセル時はチェックを戻した値を返す。"""
        try:
            from utils.settings_helper import is_recording_mode, set_recording_mode_enabled_flag
            from services.recording_mode_service import set_recording_mode_enabled
        except ImportError:
            from desktop.utils.settings_helper import (  # type: ignore
                is_recording_mode,
                set_recording_mode_enabled_flag,
            )
            from desktop.services.recording_mode_service import set_recording_mode_enabled  # type: ignore

        previous_recording = is_recording_mode()
        if new_recording == previous_recording:
            return new_recording

        if new_recording and not previous_recording:
            reply = QMessageBox.question(
                self,
                "デモモードを有効にしますか？",
                "仮想DBが新規作成されます。\n"
                "このモード中の仕入・古物台帳の保存は本番DBに反映されません。\n\n"
                "続行しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return previous_recording
        elif not new_recording and previous_recording:
            reply = QMessageBox.question(
                self,
                "デモモードを終了しますか？",
                "仮想DBに保存したデータはすべて削除されます。\n"
                "本番DBのデータは変更されません。\n\n"
                "続行しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return previous_recording

        try:
            set_recording_mode_enabled_flag(new_recording)
            set_recording_mode_enabled(new_recording, previous_recording)
        except Exception as e:
            set_recording_mode_enabled_flag(previous_recording)
            QMessageBox.critical(
                self,
                "デモモードエラー",
                "仮想DBの作成に失敗しました。\n\n"
                f"{e}\n\n"
                "アプリを再起動してから再度お試しください。",
            )
            return previous_recording
        self.settings.setValue("recording/enabled", new_recording)
        self.settings.sync()
        return new_recording

    def _on_recording_toggled(self, checked: bool) -> None:
        """デモモードチェック変更時に即反映（3-6-9版と同様）。"""
        if getattr(self, "_recording_mode_loading", False):
            return
        try:
            from utils.settings_helper import is_recording_mode
        except ImportError:
            from desktop.utils.settings_helper import is_recording_mode  # type: ignore
        before = is_recording_mode()
        final = self._commit_recording_mode_change(checked)
        if final != checked:
            self.recording_mode_cb.blockSignals(True)
            self.recording_mode_cb.setChecked(final)
            self.recording_mode_cb.blockSignals(False)
        self._sync_recording_mode_status_label()
        if final != before:
            self._notify_recording_mode_changed()
            main = self.window()
            if main is not None:
                if hasattr(main, "update_recording_mode_ui"):
                    main.update_recording_mode_ui()
                if hasattr(main, "apply_recording_mode_database_reload"):
                    main.apply_recording_mode_database_reload()
        else:
            main = self.window()
            if main is not None and hasattr(main, "update_recording_mode_ui"):
                main.update_recording_mode_ui()

    def browse_directory(self, line_edit):
        """ディレクトリ選択ダイアログ"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "ディレクトリを選択",
            line_edit.text() or str(Path.home())
        )
        if directory:
            line_edit.setText(directory)
            
    def browse_file(self, line_edit, title, file_filter="すべてのファイル (*)"):
        """ファイル選択ダイアログ"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            line_edit.text() or str(Path.home()),
            file_filter
        )
        if file_path:
            line_edit.setText(file_path)
            
    def _show_api_test_result(self, title: str, result) -> None:
        """APIテスト結果を表示（失敗時は詳細解説付き）"""
        if result.success:
            text = result.summary
            if result.details:
                text += f"\n\n{result.details}"
            QMessageBox.information(self, title, text)
            return
        text = result.summary
        if result.details:
            text += f"\n\n{result.details}"
        QMessageBox.warning(self, title, text)

    def test_api_connection(self):
        """API接続テスト"""
        try:
            from utils.api_test_helper import test_fastapi_connection
        except ImportError:
            from desktop.utils.api_test_helper import test_fastapi_connection

        original_url = self.api_client.base_url
        self.api_client.base_url = self.api_url_edit.text()
        try:
            result = test_fastapi_connection(
                self.api_url_edit.text(),
                test_fn=self.api_client.test_connection,
            )
            self._show_api_test_result("接続テスト", result)
        finally:
            self.api_client.base_url = original_url

    def test_maps_api_key(self):
        """Google Maps APIキーの接続テスト"""
        try:
            from utils.api_test_helper import test_maps_api
        except ImportError:
            from desktop.utils.api_test_helper import test_maps_api
        result = test_maps_api(self.maps_api_key_edit.text())
        self._show_api_test_result("Google Maps APIテスト", result)

    def test_gemini_api_key(self):
        """Gemini APIキー・モデルの接続テスト"""
        try:
            from utils.api_test_helper import test_gemini_api
        except ImportError:
            from desktop.utils.api_test_helper import test_gemini_api
        result = test_gemini_api(self.gemini_api_key_edit.text())
        self._show_api_test_result("Gemini APIテスト", result)

    def test_keepa_api_key(self):
        """Keepa APIキーの接続テスト"""
        try:
            from utils.api_test_helper import test_keepa_api
        except ImportError:
            from desktop.utils.api_test_helper import test_keepa_api
        result = test_keepa_api(self.keepa_api_key_edit.text())
        self._show_api_test_result("Keepa APIテスト", result)
    
    def test_ocr_settings(self):
        """OCR設定のテスト"""
        try:
            try:
                from utils.api_test_helper import explain_api_error
            except ImportError:
                from desktop.utils.api_test_helper import explain_api_error

            tesseract_cmd = self.tesseract_cmd_edit.text().strip() or None
            tessdata_dir = self.tessdata_dir_edit.text().strip() or None
            gcv_credentials = self.gcv_credentials_edit.text().strip() or None
            
            # OCRServiceをインポートしてテスト
            import sys
            import os
            from pathlib import Path
            # python/desktop をパスに追加
            desktop_dir = Path(__file__).parent.parent
            sys.path.insert(0, str(desktop_dir))
            
            # デスクトップ側servicesを優先して読み込む
            try:
                from services.ocr_service import OCRService  # python/desktop/services
            except ImportError:
                # フォールバック
                from desktop.services.ocr_service import OCRService
            
            # 環境変数を一時的に設定
            old_tessdata_prefix = os.environ.get('TESSDATA_PREFIX')
            if tessdata_dir:
                os.environ['TESSDATA_PREFIX'] = tessdata_dir
            
            try:
                ocr_service = OCRService(
                    tesseract_cmd=tesseract_cmd,
                    gcv_credentials_path=gcv_credentials,
                    tessdata_dir=tessdata_dir
                )
                
                # 結果メッセージを構築
                messages = []
                error_details = []
                
                # GCVの確認
                if OCRService.is_gcv_available():
                    if gcv_credentials:
                        if Path(gcv_credentials).exists():
                            if ocr_service.gcv_client:
                                messages.append("✅ Google Cloud Vision API: 設定済み・利用可能")
                            else:
                                messages.append("⚠️  Google Cloud Vision API: 認証情報ファイルは存在しますが、初期化に失敗しました")
                                error_details.append(
                                    explain_api_error(
                                        "ocr_gcv",
                                        "認証情報JSONは存在しますがクライアント初期化に失敗",
                                    )
                                )
                        else:
                            messages.append("❌ Google Cloud Vision API: 認証情報ファイルが見つかりません")
                            error_details.append(
                                explain_api_error(
                                    "ocr_gcv",
                                    f"ファイルが見つかりません: {gcv_credentials}",
                                )
                            )
                    else:
                        messages.append("ℹ️  Google Cloud Vision API: 認証情報が設定されていません（オプション）")
                else:
                    messages.append("ℹ️  Google Cloud Vision API: google-cloud-visionパッケージがインストールされていません")
                    error_details.append(
                        explain_api_error("ocr_gcv", "google-cloud-vision パッケージ未インストール")
                    )
                
                # Tesseractの確認
                if OCRService.is_tesseract_available():
                    if tesseract_cmd:
                        if Path(tesseract_cmd).exists():
                            messages.append(f"✅ Tesseract OCR: 設定済み ({tesseract_cmd})")
                        else:
                            messages.append(f"❌ Tesseract OCR: 実行ファイルが見つかりません ({tesseract_cmd})")
                            error_details.append(
                                explain_api_error(
                                    "ocr_tesseract",
                                    f"実行ファイルが見つかりません: {tesseract_cmd}",
                                )
                            )
                    else:
                        messages.append("✅ Tesseract OCR: 利用可能（デフォルト設定）")
                    
                    if tessdata_dir:
                        if Path(tessdata_dir).exists():
                            messages.append(f"✅ Tessdataディレクトリ: {tessdata_dir}")
                        else:
                            messages.append(f"⚠️  Tessdataディレクトリが見つかりません: {tessdata_dir}")
                            error_details.append(
                                explain_api_error(
                                    "ocr_tesseract",
                                    f"tessdata ディレクトリが見つかりません: {tessdata_dir}",
                                )
                            )
                else:
                    messages.append("❌ Tesseract OCR: pytesseractがインストールされていません")
                    error_details.append(
                        explain_api_error("ocr_tesseract", "pytesseract がインストールされていません")
                    )
                
                # メッセージを表示
                message_text = "OCR設定テスト結果\n\n" + "\n".join(messages)
                if error_details:
                    message_text += "\n\n" + "\n\n".join(error_details)
                
                if any("✅" in msg for msg in messages):
                    QMessageBox.information(self, "OCR設定テスト", message_text)
                else:
                    QMessageBox.warning(self, "OCR設定テスト", message_text)
            finally:
                # 環境変数を元に戻す
                if old_tessdata_prefix:
                    os.environ['TESSDATA_PREFIX'] = old_tessdata_prefix
                elif 'TESSDATA_PREFIX' in os.environ:
                    del os.environ['TESSDATA_PREFIX']
                    
        except Exception as e:
            try:
                from utils.api_test_helper import explain_api_error
            except ImportError:
                from desktop.utils.api_test_helper import explain_api_error
            QMessageBox.critical(
                self,
                "OCR設定テストエラー",
                f"OCR設定テスト中にエラーが発生しました:\n\n{explain_api_error('ocr_tesseract', e)}",
            )
            
    def load_settings(self):
        """設定の読み込み"""
        # API設定
        self.api_url_edit.setText(self.settings.value("api/url", "http://localhost:8000"))
        self.timeout_spin.setValue(int(self.settings.value("api/timeout", 120)))
        
        # ディレクトリ設定
        self.csv_dir_edit.setText(self.settings.value("directories/csv", ""))
        self.result_dir_edit.setText(self.settings.value("directories/result", ""))
        
        # 表示設定
        self.row_height_spin.setValue(int(self.settings.value("display/row_height", 25)))
        self.font_size_spin.setValue(int(self.settings.value("display/font_size", 9)))
        self.alternating_colors_cb.setChecked(self.settings.value("display/alternating_colors", True, type=bool))
        self.sorting_enabled_cb.setChecked(self.settings.value("display/sorting_enabled", True, type=bool))
        self.title_limit_spin.setValue(int(self.settings.value("display/title_limit", 50)))
        self.price_color_cb.setChecked(self.settings.value("display/price_color", True, type=bool))
        self.tooltip_enabled_cb.setChecked(self.settings.value("display/tooltip_enabled", True, type=bool))
        
        # パフォーマンス設定
        self.max_rows_spin.setValue(int(self.settings.value("performance/max_rows", 1000)))
        self.batch_size_spin.setValue(int(self.settings.value("performance/batch_size", 50)))
        self.auto_save_cb.setChecked(self.settings.value("performance/auto_save", False, type=bool))
        self.purchase_incremental_cb.setChecked(
            self.settings.value("performance/purchase_incremental_render", True, type=bool)
        )
        self.purchase_page_size_spin.setValue(
            int(self.settings.value("performance/purchase_page_size", 100))
        )
        self.purchase_augment_batch_spin.setValue(
            int(self.settings.value("performance/purchase_augment_batch_size", 100))
        )
        
        # ログ設定
        self.log_level_combo.setCurrentText(self.settings.value("log/level", "INFO"))
        self.log_file_cb.setChecked(self.settings.value("log/file_enabled", True, type=bool))
        self.log_file_edit.setText(self.settings.value("log/file_path", "logs/hirio.log"))
        
        # OCR設定
        self.tesseract_cmd_edit.setText(self.settings.value("ocr/tesseract_cmd", ""))
        self.tessdata_dir_edit.setText(self.settings.value("ocr/tessdata_dir", ""))
        self.gcv_credentials_edit.setText(self.settings.value("ocr/gcv_credentials", ""))
        self.gemini_api_key_edit.setText(self.settings.value("ocr/gemini_api_key", ""))
        self.maps_api_key_edit.setText(self.settings.value("maps/api_key", ""))
        # Keepa APIキー（新規）
        self.keepa_api_key_edit.setText(self.settings.value("keepa/api_key", ""))
        # Amazon 自店セラーID
        self.amazon_seller_id_edit.setText(self.settings.value("amazon/seller_id", ""))
        self.amazon_fba_simulator_url_edit.setText(
            self.settings.value(
                "amazon/fba_simulator_url",
                "https://sellercentral.amazon.co.jp/revcalpublic?lang=ja_JP"
            )
        )
        try:
            from utils.settings_helper import (
                DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
                DEFAULT_PRICETAR_LISTING_URL,
                DEFAULT_PRICETAR_REPRICING_URL,
            )
        except ImportError:
            from desktop.utils.settings_helper import (
                DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
                DEFAULT_PRICETAR_LISTING_URL,
                DEFAULT_PRICETAR_REPRICING_URL,
            )
        self.amazon_inventory_loader_upload_url_edit.setText(
            self.settings.value(
                "amazon/inventory_loader_upload_url",
                DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
            )
        )
        self.pricetar_listing_url_edit.setText(
            self.settings.value("pricetar/listing_url", DEFAULT_PRICETAR_LISTING_URL)
        )
        self.pricetar_repricing_url_edit.setText(
            self.settings.value("pricetar/repricing_url", DEFAULT_PRICETAR_REPRICING_URL)
        )
        # 3-6-9版（開発段階ではデフォルトON）
        self.pro_enabled_cb.setChecked(self.settings.value("pro/enabled", True, type=bool))
        self._recording_mode_loading = True
        self.recording_mode_cb.setChecked(self.settings.value("recording/enabled", False, type=bool))
        self._recording_mode_loading = False
        self._sync_recording_mode_status_label()
        try:
            from utils.gemini_model_helper import resolve_gemini_flash_model
        except ImportError:
            from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
        gemini_model = resolve_gemini_flash_model(self.settings.value("ocr/gemini_model"))
        if hasattr(self, "gemini_model_label"):
            self.gemini_model_label.setText(gemini_model)
        if self.settings.value("ocr/gemini_model") != gemini_model:
            self.settings.setValue("ocr/gemini_model", gemini_model)

        if hasattr(self, "flea_market_settings_widget"):
            self.flea_market_settings_widget.reload()

        if hasattr(self, "backup_folder_edit"):
            self.backup_folder_edit.setText(self.settings.value("backup/folder", ""))
            self.backup_auto_on_exit_cb.setChecked(
                self.settings.value("backup/auto_on_exit", False, type=bool)
            )
            self.backup_keep_count_spin.setValue(
                int(self.settings.value("backup/keep_count", 7) or 7)
            )
            self.backup_include_config_cb.setChecked(
                self.settings.value("backup/include_config", True, type=bool)
            )
            self._refresh_backup_status()
            
    def save_settings(self):
        """設定の保存"""
        try:
            final_recording = self._commit_recording_mode_change(
                self.recording_mode_cb.isChecked()
            )
            if final_recording != self.recording_mode_cb.isChecked():
                self.recording_mode_cb.blockSignals(True)
                self.recording_mode_cb.setChecked(final_recording)
                self.recording_mode_cb.blockSignals(False)
            self._sync_recording_mode_status_label()

            # API設定
            self.settings.setValue("api/url", self.api_url_edit.text())
            self.settings.setValue("api/timeout", self.timeout_spin.value())
            
            # ディレクトリ設定
            self.settings.setValue("directories/csv", self.csv_dir_edit.text())
            self.settings.setValue("directories/result", self.result_dir_edit.text())
            
            # 表示設定
            self.settings.setValue("display/row_height", self.row_height_spin.value())
            self.settings.setValue("display/font_size", self.font_size_spin.value())
            self.settings.setValue("display/alternating_colors", self.alternating_colors_cb.isChecked())
            self.settings.setValue("display/sorting_enabled", self.sorting_enabled_cb.isChecked())
            self.settings.setValue("display/title_limit", self.title_limit_spin.value())
            self.settings.setValue("display/price_color", self.price_color_cb.isChecked())
            self.settings.setValue("display/tooltip_enabled", self.tooltip_enabled_cb.isChecked())
            
            # パフォーマンス設定
            self.settings.setValue("performance/max_rows", self.max_rows_spin.value())
            self.settings.setValue("performance/batch_size", self.batch_size_spin.value())
            self.settings.setValue("performance/auto_save", self.auto_save_cb.isChecked())
            self.settings.setValue(
                "performance/purchase_incremental_render",
                self.purchase_incremental_cb.isChecked(),
            )
            self.settings.setValue(
                "performance/purchase_page_size",
                self.purchase_page_size_spin.value(),
            )
            self.settings.setValue(
                "performance/purchase_augment_batch_size",
                self.purchase_augment_batch_spin.value(),
            )
            
            # ログ設定
            self.settings.setValue("log/level", self.log_level_combo.currentText())
            self.settings.setValue("log/file_enabled", self.log_file_cb.isChecked())
            self.settings.setValue("log/file_path", self.log_file_edit.text())
            
            # OCR設定
            self.settings.setValue("ocr/tesseract_cmd", self.tesseract_cmd_edit.text())
            self.settings.setValue("ocr/tessdata_dir", self.tessdata_dir_edit.text())
            self.settings.setValue("ocr/gcv_credentials", self.gcv_credentials_edit.text())
            self.settings.setValue("ocr/gemini_api_key", self.gemini_api_key_edit.text())
            self.settings.setValue("maps/api_key", self.maps_api_key_edit.text())
            try:
                from utils.gemini_model_helper import resolve_gemini_flash_model
            except ImportError:
                from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
            self.settings.setValue("ocr/gemini_model", resolve_gemini_flash_model())
            # Keepa API設定
            self.settings.setValue("keepa/api_key", self.keepa_api_key_edit.text())
            # Amazon 自店セラーID
            self.settings.setValue("amazon/seller_id", self.amazon_seller_id_edit.text().strip())
            self.settings.setValue(
                "amazon/fba_simulator_url",
                self.amazon_fba_simulator_url_edit.text().strip()
                or "https://sellercentral.amazon.co.jp/revcalpublic?lang=ja_JP"
            )
            try:
                from utils.settings_helper import (
                    DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL,
                    DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
                    DEFAULT_PRICETAR_LISTING_URL,
                    DEFAULT_PRICETAR_REPRICING_URL,
                )
            except ImportError:
                from desktop.utils.settings_helper import (
                    DEFAULT_AMAZON_BULK_IMAGE_UPLOAD_URL,
                    DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
                    DEFAULT_PRICETAR_LISTING_URL,
                    DEFAULT_PRICETAR_REPRICING_URL,
                )
            self.settings.setValue(
                "amazon/inventory_loader_upload_url",
                self.amazon_inventory_loader_upload_url_edit.text().strip()
                or DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
            )
            self.settings.setValue(
                "pricetar/listing_url",
                self.pricetar_listing_url_edit.text().strip() or DEFAULT_PRICETAR_LISTING_URL,
            )
            self.settings.setValue(
                "pricetar/repricing_url",
                self.pricetar_repricing_url_edit.text().strip() or DEFAULT_PRICETAR_REPRICING_URL,
            )
            # 3-6-9版
            self.settings.setValue("pro/enabled", self.pro_enabled_cb.isChecked())

            if hasattr(self, "flea_market_settings_widget"):
                self.flea_market_settings_widget.save_all()

            if hasattr(self, "backup_folder_edit"):
                self._save_backup_settings_to_qsettings()
            
            # 設定変更シグナルを発火
            settings_dict = self.get_current_settings()
            self.settings_changed.emit(settings_dict)
            
            QMessageBox.information(self, "設定保存", "設定を保存しました")
            
        except Exception as e:
            QMessageBox.critical(self, "設定保存エラー", f"設定の保存に失敗しました:\n{str(e)}")
            
    def reset_settings(self):
        """設定のリセット"""
        reply = QMessageBox.question(
            self,
            "設定リセット確認",
            "現在の設定をリセットしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.settings.clear()
            self.load_settings()
            QMessageBox.information(self, "設定リセット", "設定をリセットしました")
            
    def load_default_settings(self):
        """デフォルト設定の読み込み"""
        # デフォルト値を設定
        self.api_url_edit.setText("http://localhost:8000")
        self.timeout_spin.setValue(120)
        self.csv_dir_edit.setText("")
        self.result_dir_edit.setText("")
        self.row_height_spin.setValue(25)
        self.font_size_spin.setValue(9)
        self.alternating_colors_cb.setChecked(True)
        self.sorting_enabled_cb.setChecked(True)
        self.title_limit_spin.setValue(50)
        self.price_color_cb.setChecked(True)
        self.tooltip_enabled_cb.setChecked(True)
        self.max_rows_spin.setValue(1000)
        self.batch_size_spin.setValue(50)
        self.purchase_incremental_cb.setChecked(True)
        self.purchase_page_size_spin.setValue(100)
        self.purchase_augment_batch_spin.setValue(100)
        self.auto_save_cb.setChecked(False)
        self.log_level_combo.setCurrentText("INFO")
        self.log_file_cb.setChecked(True)
        self.log_file_edit.setText("logs/hirio.log")
        self.tesseract_cmd_edit.setText("")
        self.tessdata_dir_edit.setText("")
        self.gcv_credentials_edit.setText("")
        self.gemini_api_key_edit.setText("")
        self.maps_api_key_edit.setText("")
        self.keepa_api_key_edit.setText("")
        self.amazon_seller_id_edit.setText("")
        self.amazon_fba_simulator_url_edit.setText("https://sellercentral.amazon.co.jp/revcalpublic?lang=ja_JP")
        try:
            from utils.settings_helper import (
                DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
                DEFAULT_PRICETAR_LISTING_URL,
                DEFAULT_PRICETAR_REPRICING_URL,
            )
        except ImportError:
            from desktop.utils.settings_helper import (
                DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL,
                DEFAULT_PRICETAR_LISTING_URL,
                DEFAULT_PRICETAR_REPRICING_URL,
            )
        self.amazon_inventory_loader_upload_url_edit.setText(DEFAULT_AMAZON_INVENTORY_LOADER_UPLOAD_URL)
        self.pricetar_listing_url_edit.setText(DEFAULT_PRICETAR_LISTING_URL)
        self.pricetar_repricing_url_edit.setText(DEFAULT_PRICETAR_REPRICING_URL)
        try:
            from utils.gemini_model_helper import resolve_gemini_flash_model
        except ImportError:
            from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
        if hasattr(self, "gemini_model_label"):
            self.gemini_model_label.setText(resolve_gemini_flash_model())
        self.pro_enabled_cb.setChecked(True)  # 開発段階ではデフォルトON
        self.recording_mode_cb.setChecked(False)
        self._sync_recording_mode_status_label()
        
    def get_current_settings(self):
        """現在の設定を辞書で取得"""
        try:
            from utils.gemini_model_helper import resolve_gemini_flash_model
        except ImportError:
            from desktop.utils.gemini_model_helper import resolve_gemini_flash_model
        return {
            "api": {
                "url": self.api_url_edit.text(),
                "timeout": self.timeout_spin.value()
            },
            "directories": {
                "csv": self.csv_dir_edit.text(),
                "result": self.result_dir_edit.text()
            },
            "display": {
                "row_height": self.row_height_spin.value(),
                "font_size": self.font_size_spin.value(),
                "alternating_colors": self.alternating_colors_cb.isChecked(),
                "sorting_enabled": self.sorting_enabled_cb.isChecked(),
                "title_limit": self.title_limit_spin.value(),
                "price_color": self.price_color_cb.isChecked(),
                "tooltip_enabled": self.tooltip_enabled_cb.isChecked()
            },
            "performance": {
                "max_rows": self.max_rows_spin.value(),
                "batch_size": self.batch_size_spin.value(),
                "auto_save": self.auto_save_cb.isChecked(),
                "purchase_incremental_render": self.purchase_incremental_cb.isChecked(),
                "purchase_page_size": self.purchase_page_size_spin.value(),
                "purchase_augment_batch_size": self.purchase_augment_batch_spin.value(),
            },
            "log": {
                "level": self.log_level_combo.currentText(),
                "file_enabled": self.log_file_cb.isChecked(),
                "file_path": self.log_file_edit.text()
            },
            "ocr": {
                "tesseract_cmd": self.tesseract_cmd_edit.text(),
                "tessdata_dir": self.tessdata_dir_edit.text(),
                "gcv_credentials": self.gcv_credentials_edit.text(),
                "gemini_api_key": self.gemini_api_key_edit.text(),
                "gemini_model": resolve_gemini_flash_model(),
            },
            "maps": {
                "api_key": self.maps_api_key_edit.text(),
            },
            "keepa": {
                "api_key": self.keepa_api_key_edit.text(),
            },
            "amazon": {
                "seller_id": self.amazon_seller_id_edit.text().strip(),
                "fba_simulator_url": self.amazon_fba_simulator_url_edit.text().strip()
                or "https://sellercentral.amazon.co.jp/revcalpublic?lang=ja_JP",
                "inventory_loader_upload_url": self.amazon_inventory_loader_upload_url_edit.text().strip(),
            },
            "pricetar": {
                "listing_url": self.pricetar_listing_url_edit.text().strip(),
                "repricing_url": self.pricetar_repricing_url_edit.text().strip(),
            },
            "pro": {
                "enabled": self.pro_enabled_cb.isChecked(),
            },
            "recording": {
                "enabled": self.recording_mode_cb.isChecked(),
            }
        }
