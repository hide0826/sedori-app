#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GCSアップロード mixin。"""
from __future__ import annotations

import os
import re
import sys
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QTextEdit, QDateEdit, QSpinBox,
    QScrollArea, QSizePolicy, QStyledItemDelegate,
    QSplitter, QListWidget, QListWidgetItem, QMenu,
    QFormLayout, QApplication, QCheckBox, QProgressDialog,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QSettings, QTimer, QUrl, QCoreApplication
from PySide6.QtGui import QPixmap, QTransform, QColor, QDesktopServices, QClipboard

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_evidence_completed

try:
    from services.receipt_service import ReceiptService
    from services.receipt_matching_service import ReceiptMatchingService
    from services.purchase_break_even import compute_break_even_for_record
    from services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
except Exception:
    from desktop.services.receipt_service import ReceiptService
    from desktop.services.receipt_matching_service import ReceiptMatchingService
    from desktop.services.purchase_break_even import compute_break_even_for_record
    from desktop.services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from desktop.services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
from database.receipt_db import ReceiptDatabase
from database.inventory_db import InventoryDatabase
from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from database.product_db import ProductDatabase
from database.route_db import RouteDatabase

from .support import (
    ReceiptOCRThread,
    ReceiptSnapshotDialog,
    _RECEIPT_ACTION_TO_PIPELINE_STEP,
    _RECEIPT_WORKFLOW_PIPELINE_SEGMENTS,
    _format_receipt_status_prefix_html,
    _format_receipt_workflow_pipeline_html,
    AccountTitleDelegate,
    StoreNameDelegate,
    WarrantyProductDelegate,
)


class ReceiptGcsMixin:
    def _load_gcs_uploader(self):
        """GCSアップロードユーティリティを動的に読み込む（画像管理タブと同じ方式）"""
        import sys
        import os
        import importlib.util
        
        # python/utils/gcs_uploader.py へのパスを追加
        # このファイルは python/desktop/ui/receipt/ 配下なので、3つ上の python/ を候補にする
        # （分割前の ui/receipt_widget.py では 2つ上だったため、両方を候補に残す）
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        python_dir = os.path.abspath(os.path.join(current_file_dir, '..', '..', '..'))
        desktop_dir = os.path.abspath(os.path.join(current_file_dir, '..', '..'))

        # パス候補を複数試す（PyInstaller等で__file__が期待通りでない場合に対応）
        candidate_paths = [
            python_dir,  # ui/receipt/ からの通常パス → python/
            desktop_dir,  # 互換・誤配置時
            os.path.join(python_dir, 'python'),  # プロジェクトルートから実行している場合
            os.path.join(desktop_dir, 'python'),
        ]
        
        # 実際にutils/gcs_uploader.pyが存在するパスを探す
        found_path = None
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
            
            # importlibを使って動的にモジュールを読み込む
            gcs_uploader_file = os.path.join(found_path, 'utils', 'gcs_uploader.py')
            if os.path.exists(gcs_uploader_file):
                spec = importlib.util.spec_from_file_location("gcs_uploader", gcs_uploader_file)
                gcs_uploader_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gcs_uploader_module)
                return (
                    gcs_uploader_module.upload_image_to_gcs,
                    gcs_uploader_module.check_gcs_authentication,
                    getattr(gcs_uploader_module, 'set_bucket_lifecycle_policy', None),
                    gcs_uploader_module.GCS_AVAILABLE,
                    getattr(gcs_uploader_module, 'find_existing_public_url_for_local_file', None)
                )
            else:
                raise ImportError(f"gcs_uploader.py not found at {gcs_uploader_file}")
        else:
            # フォールバック: 通常のインポートを試す
            from utils.gcs_uploader import upload_image_to_gcs, check_gcs_authentication, GCS_AVAILABLE
            set_bucket_lifecycle_policy = getattr(__import__('utils.gcs_uploader', fromlist=['set_bucket_lifecycle_policy']), 'set_bucket_lifecycle_policy', None)
            find_existing_public_url_for_local_file = getattr(__import__('utils.gcs_uploader', fromlist=['find_existing_public_url_for_local_file']), 'find_existing_public_url_for_local_file', None)
            return upload_image_to_gcs, check_gcs_authentication, set_bucket_lifecycle_policy, GCS_AVAILABLE, find_existing_public_url_for_local_file

    def show_gcs_upload_dialog(self):
        """GCSアップロードダイアログを表示"""
        if not self._require_bulk_rename_before_post_actions("GCSアップロード"):
            return
        # GCSアップロードユーティリティを動的に読み込む（画像管理タブと同じ方式）
        try:
            upload_func, auth_func, lifecycle_func, gcs_available, find_existing_func = self._load_gcs_uploader()
        except Exception as e:
            import sys
            error_msg = (
                f"GCSアップロード機能の読み込みに失敗しました:\n\n{str(e)}\n\n"
                f"Python実行環境: {sys.executable}\n\n"
                "インストール方法:\n"
                f"  {sys.executable} -m pip install google-cloud-storage\n\n"
                "または、requirements.txtからインストール:\n"
                "  pip install -r requirements.txt"
            )
            QMessageBox.warning(self, "GCSアップロード", error_msg)
            return
        
        if not gcs_available:
            import sys
            error_msg = (
                "google-cloud-storageがインストールされていません。\n\n"
                f"Python実行環境: {sys.executable}\n\n"
                "インストール方法:\n"
                f"  {sys.executable} -m pip install google-cloud-storage\n\n"
                "または、requirements.txtからインストール:\n"
                "  pip install -r requirements.txt"
            )
            QMessageBox.warning(self, "GCSアップロード", error_msg)
            return
        
        # 認証確認
        auth_success, auth_error = auth_func()
        if not auth_success:
            QMessageBox.warning(
                self, "GCS認証エラー",
                f"GCS認証に失敗しました:\n{auth_error}"
            )
            return
        
        # グローバル変数に保存（後で使用するため）
        global upload_image_to_gcs, check_gcs_authentication, set_bucket_lifecycle_policy, GCS_AVAILABLE
        upload_image_to_gcs = upload_func
        check_gcs_authentication = auth_func
        set_bucket_lifecycle_policy = lifecycle_func
        GCS_AVAILABLE = gcs_available
        
        # ライフサイクル管理ポリシー選択ダイアログ
        dialog = QDialog(self)
        dialog.setWindowTitle("GCSアップロード設定")
        dialog.resize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # 説明
        info_label = QLabel(
            "レシート一覧の全件をGCSにアップロードします。\n"
            "電子帳簿保存法に対応するため、10年間保存する前提でライフサイクル管理ポリシーを設定します。"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # ライフサイクル管理ポリシー選択
        policy_group = QGroupBox("ライフサイクル管理ポリシー")
        policy_layout = QFormLayout(policy_group)
        
        # 1年目
        year1_combo = QComboBox()
        year1_combo.addItems(["STANDARD", "COLDLINE", "ARCHIVE"])
        year1_combo.setCurrentText("STANDARD")
        policy_layout.addRow("1年目:", year1_combo)
        
        # 2年目～7年目
        year2_7_combo = QComboBox()
        year2_7_combo.addItems(["STANDARD", "COLDLINE", "ARCHIVE"])
        year2_7_combo.setCurrentText("COLDLINE")
        policy_layout.addRow("2年目～7年目:", year2_7_combo)
        
        # 8年目～10年目
        year8_10_combo = QComboBox()
        year8_10_combo.addItems(["STANDARD", "COLDLINE", "ARCHIVE"])
        year8_10_combo.setCurrentText("ARCHIVE")
        policy_layout.addRow("8年目～10年目:", year8_10_combo)
        
        layout.addWidget(policy_group)
        
        # デフォルトポリシー説明
        default_info = QLabel(
            "デフォルトポリシー:\n"
            "・1年経過後: COLDLINEへ移行\n"
            "・7年経過後: ARCHIVEへ移行\n"
            "・10年経過後: 自動削除（任意）"
        )
        default_info.setWordWrap(True)
        default_info.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(default_info)
        
        # ライフサイクル管理ポリシーをバケットに設定するか
        set_lifecycle_checkbox = QCheckBox("バケットのライフサイクル管理ポリシーを設定する")
        set_lifecycle_checkbox.setChecked(True)
        set_lifecycle_checkbox.setStyleSheet("QCheckBox { color: #000000; font-size: 11px; }")
        layout.addWidget(set_lifecycle_checkbox)
        
        # 10年後の自動削除
        auto_delete_checkbox = QCheckBox("10年経過後に自動削除する（任意）")
        auto_delete_checkbox.setChecked(False)
        auto_delete_checkbox.setStyleSheet("QCheckBox { color: #000000; font-size: 11px; }")
        auto_delete_checkbox.setToolTip("10年経過後にGCS上のファイルを自動削除するかどうかを設定します")
        layout.addWidget(auto_delete_checkbox)
        
        # ボタン
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        if dialog.exec() == QDialog.Accepted:
            # 選択されたポリシーを取得
            year1_storage = year1_combo.currentText()
            year2_7_storage = year2_7_combo.currentText()
            year8_10_storage = year8_10_combo.currentText()
            set_lifecycle = set_lifecycle_checkbox.isChecked()
            enable_auto_delete = auto_delete_checkbox.isChecked()
            
            # バケットのライフサイクル管理ポリシーを設定
            if set_lifecycle:
                # ライフサイクル管理ポリシー設定関数を動的に読み込む
                try:
                    _, _, lifecycle_func, _, _ = self._load_gcs_uploader()
                    if lifecycle_func:
                        success = lifecycle_func(
                            year1_storage=year1_storage,
                            year2_7_storage=year2_7_storage,
                            year8_10_storage=year8_10_storage,
                            enable_auto_delete=enable_auto_delete
                        )
                        if not success:
                            QMessageBox.warning(
                                self, "警告",
                                "バケットのライフサイクル管理ポリシーの設定に失敗しました。\n"
                                "アップロードは続行しますが、手動で設定してください。"
                            )
                    else:
                        QMessageBox.warning(
                            self, "警告",
                            "ライフサイクル管理ポリシー設定機能が利用できません。\n"
                            "アップロードは続行しますが、手動で設定してください。"
                        )
                except Exception as e:
                    QMessageBox.warning(
                        self, "警告",
                        f"バケットのライフサイクル管理ポリシーの設定中にエラーが発生しました:\n{str(e)}\n"
                        "アップロードは続行しますが、手動で設定してください。"
                    )
            
            # アップロード実行
            self.upload_receipts_to_gcs(year1_storage, year2_7_storage, year8_10_storage)
    
    def upload_receipts_to_gcs(self, year1_storage: str, year2_7_storage: str, year8_10_storage: str):
        """レシート一覧の全件をGCSにアップロード"""
        from PySide6.QtWidgets import QProgressDialog
        
        # 現在のレシート一覧・保証書一覧に対応するレシートのみ取得
        receipts = self._get_current_receipts_from_tables()
        if not receipts:
            QMessageBox.information(self, "GCSアップロード", "アップロードするレシートがありません。")
            return
        
        # 確認ダイアログ
        reply = QMessageBox.question(
            self,
            "GCSアップロード",
            f"{len(receipts)} 件のレシートをGCSにアップロードします。\n"
            f"ライフサイクル管理ポリシー:\n"
            f"・1年目: {year1_storage}\n"
            f"・2年目～7年目: {year2_7_storage}\n"
            f"・8年目～10年目: {year8_10_storage}\n\n"
            f"続行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        
        # プログレスダイアログ
        progress = QProgressDialog("GCSアップロード中...", "キャンセル", 0, len(receipts), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        uploaded_count = 0
        skipped_count = 0
        existing_count = 0  # 既存ファイルから取得した件数
        error_count = 0
        error_messages = []
        upload_cancelled = False
        
        for i, receipt in enumerate(receipts):
            if progress.wasCanceled():
                upload_cancelled = True
                break
            
            progress.setValue(i)
            progress.setLabelText(f"アップロード中: {receipt.get('id', '不明')} ({i+1}/{len(receipts)})")
            QApplication.processEvents()
            
            try:
                receipt_id = receipt.get('id')
                
                # ファイルパスを取得
                file_path = receipt.get('original_file_path') or receipt.get('file_path', '')
                if not file_path:
                    skipped_count += 1
                    error_messages.append(f"レシートID {receipt_id}: ファイルパスが設定されていません")
                    continue
                
                file_path_obj = Path(file_path)
                if not file_path_obj.exists():
                    skipped_count += 1
                    error_messages.append(f"レシートID {receipt_id}: ファイルが見つかりません: {file_path}")
                    continue
                
                # ストレージクラスを決定（現在は1年目のストレージクラスを使用）
                # 実際のライフサイクル管理はバケットのライフサイクル管理ポリシーで行う
                storage_class = year1_storage
                
                # GCSにアップロード
                try:
                    # GCSアップロード関数を動的に読み込む
                    upload_func, _, _, _, find_existing_func = self._load_gcs_uploader()
                    
                    # 既にGCSに存在する場合は、アップロードせずURLを取得（重複アップロード防止）
                    public_url = None
                    if find_existing_func:
                        try:
                            # receipts/プレフィックスで既存ファイルを検索
                            existing_url = find_existing_func(str(file_path_obj), prefix="receipts/")
                            if existing_url:
                                public_url = existing_url
                                existing_count += 1
                        except Exception:
                            # 既存ファイル検索でエラーが発生した場合は、通常のアップロード処理に進む
                            pass
                    
                    # 既存ファイルが見つからなかった場合は、アップロードを実行
                    if not public_url:
                        # レシート用のパスを生成（receipts/プレフィックス）
                        destination_blob_name = f"receipts/{file_path_obj.name}"
                        public_url = upload_func(
                            str(file_path_obj),
                            destination_blob_name=destination_blob_name,
                            storage_class=storage_class
                        )
                        uploaded_count += 1
                    
                    # データベースにGCS URLを保存
                    self.receipt_db.update_receipt(receipt_id, {"gcs_url": public_url})
                except Exception as e:
                    error_count += 1
                    error_messages.append(f"レシートID {receipt_id}: アップロードエラー: {str(e)}")
                    continue
                    
            except Exception as e:
                error_count += 1
                error_messages.append(f"レシートID {receipt.get('id', '不明')}: 処理エラー: {str(e)}")
                continue
        
        progress.setValue(len(receipts))
        
        # 結果を表示
        result_message = f"GCSアップロード完了\n\n"
        result_message += f"アップロード成功: {uploaded_count} 件\n"
        if existing_count > 0:
            result_message += f"既存ファイルから取得: {existing_count} 件\n"
        result_message += f"スキップ: {skipped_count} 件\n"
        result_message += f"エラー: {error_count} 件"
        
        if error_messages:
            result_message += f"\n\nエラー詳細:\n" + "\n".join(error_messages[:10])
            if len(error_messages) > 10:
                result_message += f"\n... 他 {len(error_messages) - 10} 件"
        
        QMessageBox.information(self, "GCSアップロード", result_message)
        
        # レシート一覧を更新
        self.refresh_receipt_list()
        if not upload_cancelled:
            self._mark_gcs_upload_completed()
    
