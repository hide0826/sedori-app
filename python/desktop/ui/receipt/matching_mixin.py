#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マッチング・確定・仕入紐付け mixin。"""
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


class ReceiptMatchingMixin:
    def search_from_purchase_db(self):
        """仕入DBから日付・店舗名・電話番号で検索して店舗コードと点数を自動入力"""
        if not self.product_widget:
            return
        
        # OCR結果から日付・店舗名・電話番号を取得
        # 日付は current_receipt_data を優先し、なければ date_edit から取得
        purchase_date = ""
        if self.current_receipt_data and self.current_receipt_data.get("purchase_date"):
            purchase_date = str(self.current_receipt_data.get("purchase_date")).strip()
        else:
            purchase_date = self.date_edit.date().toString("yyyy-MM-dd") if hasattr(self, 'date_edit') else ""
        store_name_raw = self.store_name_edit.text().strip() if hasattr(self, 'store_name_edit') else ""
        phone_number = self.phone_edit.text().strip() if hasattr(self, 'phone_edit') else ""
        
        if not purchase_date or not store_name_raw:
            return
        
        # 仕入DBの全データを取得
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            return
        
        # 店舗マスタから電話番号で店舗を検索
        stores = self.store_db.list_stores()
        
        # 電話番号で店舗を検索（部分一致）
        matched_store_code = None
        if phone_number:
            for store in stores:
                store_phone = store.get('phone') or ''
                if store_phone and (phone_number in store_phone or store_phone in phone_number):
                    # 店舗コード優先、なければ仕入れ先コード（互換性のため）
                    matched_store_code = store.get('store_code') or store.get('supplier_code')
                    break
        
        # 店舗名でも検索（電話番号で見つからない場合）
        if not matched_store_code:
            for store in stores:
                store_name = store.get('store_name') or ''
                # 店舗名の部分一致チェック
                if store_name and store_name_raw and (store_name_raw in store_name or store_name in store_name_raw):
                    # 店舗コード優先、なければ仕入れ先コード（互換性のため）
                    matched_store_code = store.get('store_code') or store.get('supplier_code')
                    break
        
        # 店舗マスタに無い場合は経費先でマッチング（電話番号→名称の順）
        if not matched_store_code:
            dests = self.store_db.list_expense_destinations()
            normalized_phone = self.matching_service._normalize_phone(phone_number) if phone_number else None
            matched_dest_code = None
            matched_dest_journal = None
            if normalized_phone:
                for d in dests:
                    dp = d.get('phone') or ''
                    if dp and self.matching_service._normalize_phone(dp) == normalized_phone:
                        matched_dest_code = (d.get('code') or '').strip()
                        matched_dest_journal = (d.get('journal') or '').strip()
                        break
            if not matched_dest_code and store_name_raw:
                for d in dests:
                    dn = (d.get('name') or '').strip()
                    if dn and (store_name_raw in dn or dn in store_name_raw):
                        matched_dest_code = (d.get('code') or '').strip()
                        matched_dest_journal = (d.get('journal') or '').strip()
                        break
            if matched_dest_code and self.current_receipt_id:
                if hasattr(self, 'store_code_combo'):
                    idx = self.store_code_combo.findData(matched_dest_code)
                    if idx >= 0:
                        self.store_code_combo.setCurrentIndex(idx)
                self.receipt_db.update_receipt(self.current_receipt_id, {
                    "store_code": matched_dest_code,
                    "account_title": matched_dest_journal or None,
                })
                # 経費先一覧の登録番号が空の場合はレシートの登録番号を入力
                try:
                    dest = self.store_db.get_expense_destination_by_code(matched_dest_code)
                    reg_from_receipt = (self.current_receipt_data.get("registration_number") or "").strip()
                    if dest and reg_from_receipt and not (dest.get("registration_number") or "").strip():
                        self.store_db.update_expense_destination_registration_number(dest["id"], reg_from_receipt)
                except Exception:
                    pass
            return
        
        # 日付を正規化（yyyy-MM-dd形式に揃えて比較）
        normalized_date = purchase_date.replace('/', '-')
        if ' ' in normalized_date:
            normalized_date = normalized_date.split(' ')[0]
        
        # 仕入DBから該当日付・店舗コードで検索
        matched_records = []
        for record in purchase_records:
            record_date = record.get('仕入れ日') or record.get('purchase_date') or ''
            record_store_code = record.get('仕入先') or record.get('store_code') or ''
            
            # 日付の正規化
            normalized_record_date = record_date.replace('/', '-')
            if ' ' in normalized_record_date:
                normalized_record_date = normalized_record_date.split(' ')[0]
            
            # 日付と店舗コードでマッチング
            if normalized_record_date.startswith(normalized_date) and record_store_code == matched_store_code:
                matched_records.append(record)
        
        if matched_records:
            # 店舗コードを入力
            if hasattr(self, 'store_code_combo'):
                idx = self.store_code_combo.findData(matched_store_code)
                if idx >= 0:
                    self.store_code_combo.setCurrentIndex(idx)
            
            # 仕入れ点数を集計
            total_items = 0
            for record in matched_records:
                quantity = record.get('仕入れ個数') or record.get('quantity') or 0
                try:
                    total_items += int(quantity)
                except (ValueError, TypeError):
                    pass
            

    def run_matching(self):
        """マッチングを実行"""
        if not self.current_receipt_data:
            QMessageBox.warning(self, "警告", "レシートデータがありません。")
            return
        
        if not self.product_widget:
            QMessageBox.warning(self, "警告", "仕入DBへの参照がありません。")
            return

        purchase_records = self._get_purchase_records()
        if not purchase_records:
            QMessageBox.warning(self, "警告", "仕入DBにデータがありません。")
            return
        
        # マッチング実行
        candidates = self.matching_service.find_match_candidates(
            self.current_receipt_data,
            purchase_records,
                    preferred_store_code=self.store_code_combo.currentData() if hasattr(self, 'store_code_combo') else None,
        )
        
        if candidates:
            candidate = candidates[0]
            diff = candidate.diff
            
            # マッチング結果の点数を点数欄に入力
            if candidate.items_count > 0:
                # current_receipt_dataにも反映
                if self.current_receipt_data:
                    self.current_receipt_data['items_count'] = candidate.items_count
            
            if is_acceptable_price_difference(diff):
                if hasattr(self, 'match_result_label'):
                    self.match_result_label.setText(
                    f"マッチ成功: 差額 {diff}円（許容範囲内）\n"
                    f"店舗コード: {candidate.store_code}\n"
                    f"アイテム数: {candidate.items_count}"
                )
            else:
                if hasattr(self, 'match_result_label'):
                    self.match_result_label.setText(
                    f"マッチ候補あり（差額: {diff}円）\n"
                    f"確認してください。"
                )
        else:
            if hasattr(self, 'match_result_label'):
                self.match_result_label.setText("マッチする候補が見つかりませんでした。")
    
    def confirm_receipt(self):
        """レシートを確定（学習も実行）"""
        if not self.current_receipt_id:
            return
        
        store_code = self.store_code_combo.currentData() if hasattr(self, 'store_code_combo') else None
        if not store_code:
            QMessageBox.warning(self, "警告", "店舗コードを選択してください。")
            return
        
        # 日付を取得
        purchase_date = self.date_edit.date().toString("yyyy-MM-dd") if hasattr(self, 'date_edit') else ""
        if not purchase_date:
            QMessageBox.warning(self, "警告", "日付が設定されていません。")
            return
        
        # 現在の画像パスを取得
        current_receipt = self.receipt_db.get_receipt(self.current_receipt_id)
        if not current_receipt:
            QMessageBox.warning(self, "警告", "レシートデータが見つかりません。")
            return
        
        old_image_path = current_receipt.get('file_path')
        original_file_path = current_receipt.get('original_file_path')  # 元のファイルパス
        if not old_image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        # 新しい画像ファイル名を生成
        from pathlib import Path
        import os
        import traceback
        from datetime import datetime
        
        # デバッグログ出力先
        log_path = Path(__file__).resolve().parents[2] / "desktop_error.log"
        
        def _write_log(message: str):
            """デバッグログを書き込む"""
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] レシートリネーム処理\n")
                    f.write(f"{message}\n")
                    f.write("-" * 80 + "\n")
            except Exception:
                pass
        
        # DBのIDを取得（ファイル名に使用）
        db_receipt_id = self.current_receipt_id
        
        # 日付をyyyyMMdd形式に変換
        date_str = purchase_date.replace("-", "").replace("/", "").replace(".", "") if purchase_date else "UNKNOWN"
        if len(date_str) == 10:  # yyyy-MM-dd形式
            date_str = date_str[:4] + date_str[5:7] + date_str[8:10]
        elif len(date_str) != 8:
            date_str = "UNKNOWN"
        
        # 連番を決定（同じ日付・店舗コードのファイル名を検索）
        from pathlib import Path as PathLib
        existing_files = []
        if old_image_path:
            parent_dir = PathLib(old_image_path).parent
            pattern = f"{date_str}_{store_code}_*.jpg"
            for ext in ['.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG']:
                pattern_files = list(parent_dir.glob(f"{date_str}_{store_code}_*{ext}"))
                existing_files.extend(pattern_files)
        
        # 既存ファイルから最大の連番を取得
        max_number = 0
        for file_path in existing_files:
            try:
                stem = file_path.stem  # 拡張子なしのファイル名
                parts = stem.split('_')
                if len(parts) >= 3:
                    number_part = parts[-1]  # 最後の部分が連番
                    if number_part.isdigit():
                        max_number = max(max_number, int(number_part))
            except Exception:
                pass
        
        next_number = max_number + 1
        
        # 新しいファイル名を生成: {YYYYMMDD}_{store_code}_{連番}.{拡張子}
        old_image_file = Path(old_image_path)
        if not old_image_file.is_absolute():
            old_image_file = Path(os.path.abspath(old_image_path))
        
        new_image_name = f"{date_str}_{store_code}_{next_number:02d}{old_image_file.suffix}"
        new_image_path = old_image_file.parent / new_image_name
        
        # 同名のファイル名が存在するか確認
        if new_image_path.exists() and new_image_path != old_image_file:
            reply = QMessageBox.question(
                self, "確認",
                f"画像ファイル名「{new_image_name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        _write_log(f"開始: DB ID={db_receipt_id}, コピー先パス={old_image_path}, 元のパス={original_file_path}, 新しいファイル名={new_image_name}")
        
        # コピー先ファイルのパスを絶対パスに正規化
        _write_log(f"コピー先パス解析: is_absolute={old_image_file.is_absolute()}, パス={old_image_file}")
        
        # 元のファイルパスを取得（リネーム対象）
        original_file = None
        if original_file_path:
            original_file = Path(original_file_path)
            if not original_file.is_absolute():
                original_file = Path(os.path.abspath(original_file_path))
            _write_log(f"元のファイルパス: {original_file}, 存在={original_file.exists() if original_file else False}")
        
        # コピー先ファイルの存在確認
        file_exists = old_image_file.exists()
        _write_log(f"コピー先ファイル存在確認: {file_exists}, パス={old_image_file}")
        
        if not file_exists:
            error_msg = (
                f"画像ファイルが見つかりません:\n{old_image_file}\n\n"
                f"元のパス: {old_image_path}"
            )
            _write_log(f"エラー: {error_msg}")
            QMessageBox.warning(self, "警告", error_msg)
            return
        
        # 元のファイルの新しいパスも生成
        new_original_path = None
        if original_file and original_file.exists():
            new_original_path = original_file.parent / f"{date_str}_{store_code}_{next_number:02d}{original_file.suffix}"
            _write_log(f"元のファイルの新しいパス: {new_original_path}")
        
        _write_log(f"新しいファイル名生成: {new_image_name}, コピー先パス={new_image_path}")
        
        # 同名ファイルが存在する場合の確認（自分自身でない場合のみ）
        if new_image_path.exists() and new_image_path != old_image_file:
            _write_log(f"同名ファイル存在: {new_image_path}")
            reply = QMessageBox.question(
                self, "確認",
                f"画像ファイル「{new_image_name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                _write_log("ユーザーが上書きをキャンセル")
                return
        
        # 元のファイルも同名ファイルが存在する場合の確認
        if new_original_path and new_original_path.exists() and new_original_path != original_file:
            _write_log(f"元のファイルの同名ファイル存在: {new_original_path}")
            reply = QMessageBox.question(
                self, "確認",
                f"元の画像ファイル「{new_original_path.name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                _write_log("ユーザーが元のファイルの上書きをキャンセル")
                return
        
        # コピー先ファイルをリネーム（ファイル名が変更される場合のみ）
        if new_image_path != old_image_file:
            _write_log(f"コピー先リネーム実行: {old_image_file} -> {new_image_path}")
            try:
                import shutil
                # ファイルをリネーム（移動）
                _write_log(f"shutil.move実行前: 元ファイル存在={old_image_file.exists()}, 新ファイル存在={new_image_path.exists()}")
                shutil.move(str(old_image_file), str(new_image_path))
                _write_log(f"shutil.move実行後: 元ファイル存在={old_image_file.exists()}, 新ファイル存在={new_image_path.exists()}")
                
                # リネーム後のファイルが存在することを確認
                if not new_image_path.exists():
                    raise Exception(f"リネーム後のファイルが見つかりません: {new_image_path}")
                
                _write_log(f"コピー先リネーム成功: {new_image_path}")
            except Exception as e:
                error_detail = traceback.format_exc()
                _write_log(f"コピー先リネームエラー: {str(e)}\n{error_detail}")
                QMessageBox.critical(
                    self, "エラー",
                    f"画像ファイルのリネームに失敗しました:\n\n"
                    f"エラー: {str(e)}\n\n"
                    f"元のファイル: {old_image_file}\n"
                    f"新しいファイル: {new_image_path}\n\n"
                    f"詳細はログファイルを確認してください:\n{log_path}"
                )
                return
        else:
            _write_log(f"コピー先リネーム不要: ファイル名が同じです（{old_image_file} == {new_image_path}）")
        
        # 元のファイルもリネーム（存在する場合）
        if original_file and original_file.exists() and new_original_path:
            if new_original_path != original_file:
                _write_log(f"元のファイルリネーム実行: {original_file} -> {new_original_path}")
                try:
                    import shutil
                    _write_log(f"元のファイルshutil.move実行前: 元ファイル存在={original_file.exists()}, 新ファイル存在={new_original_path.exists()}")
                    shutil.move(str(original_file), str(new_original_path))
                    _write_log(f"元のファイルshutil.move実行後: 元ファイル存在={original_file.exists()}, 新ファイル存在={new_original_path.exists()}")
                    
                    # リネーム後のファイルが存在することを確認
                    if not new_original_path.exists():
                        raise Exception(f"元のファイルのリネーム後のファイルが見つかりません: {new_original_path}")
                    
                    _write_log(f"元のファイルリネーム成功: {new_original_path}")
                except Exception as e:
                    error_detail = traceback.format_exc()
                    _write_log(f"元のファイルリネームエラー: {str(e)}\n{error_detail}")
                    # 元のファイルのリネーム失敗は警告のみ（コピー先は成功しているため）
                    QMessageBox.warning(
                        self, "警告",
                        f"元の画像ファイルのリネームに失敗しました:\n\n"
                        f"エラー: {str(e)}\n\n"
                        f"元のファイル: {original_file}\n"
                        f"新しいファイル: {new_original_path}\n\n"
                        f"コピー先のリネームは成功しています。"
                    )
            else:
                _write_log(f"元のファイルリネーム不要: ファイル名が同じです（{original_file} == {new_original_path}）")
        
        # レシートDBを更新（店舗コード、画像パス）
        # リネームが実行された場合は新しいパス、実行されなかった場合は元のパスを使用
        final_image_path = str(new_image_path) if new_image_path != old_image_file else str(old_image_file)
        final_original_path = str(new_original_path) if (new_original_path and original_file and new_original_path != original_file) else original_file_path
        _write_log(f"DB更新: 最終的なコピー先パス={final_image_path}, 最終的な元のパス={final_original_path}")
        
        # 画像ファイル名を取得（識別子として使用）
        image_file_name = Path(final_image_path).stem  # 拡張子なしのファイル名
        
        # 時刻を取得（HH:MM形式）
        purchase_time = self.time_edit.text().strip()
        # 時刻の形式を検証（HH:MM形式）
        if purchase_time:
            import re
            if not re.match(r"^\d{1,2}:\d{2}$", purchase_time):
                # 形式が正しくない場合は警告（ただし処理は継続）
                QMessageBox.warning(self, "警告", f"時刻の形式が正しくありません（HH:MM形式で入力してください）: {purchase_time}")
                purchase_time = None
        
        updates = {
            "store_code": store_code,
            "file_path": final_image_path
        }
        if purchase_time:
            updates["purchase_time"] = purchase_time
        if final_original_path:
            updates["original_file_path"] = final_original_path
        
        # レジ袋金額を取得
        plastic_bag_text = self.plastic_bag_edit.text().strip() if hasattr(self, 'plastic_bag_edit') else ""
        plastic_bag_amount = None
        if plastic_bag_text:
            try:
                plastic_bag_amount = int(plastic_bag_text)
            except ValueError:
                pass
        if plastic_bag_amount is not None:
            updates["plastic_bag_amount"] = plastic_bag_amount
        
        _write_log(f"DB更新内容: {updates}")
        update_result = self.receipt_db.update_receipt(self.current_receipt_id, updates)
        _write_log(f"DB更新結果: {update_result}")
        
        # 学習
        self.matching_service.learn_store_correction(self.current_receipt_id, store_code)
        
        # レシートDBからファイルパスを取得
        receipt = self.receipt_db.get_receipt(db_receipt_id)
        receipt_image_path = None
        if receipt:
            receipt_image_path = receipt.get('original_file_path') or receipt.get('file_path')
        
        # 仕入DBの該当SKUに画像ファイル名を自動入力
        self._link_receipt_to_purchase_records(
            purchase_date=purchase_date,
            purchase_time=purchase_time,
            store_code=store_code,
            image_file_name=image_file_name,
            db_receipt_id=db_receipt_id,
            receipt_image_path=receipt_image_path
        )
        
        QMessageBox.information(
            self, "確定",
            f"レシートを確定しました。\n画像ファイル: {new_image_name}"
        )
        
        self.refresh_receipt_list()
        self.reset_form()
    
    def _link_receipt_to_purchase_records(
        self,
        purchase_date: str,
        purchase_time: Optional[str],
        store_code: str,
        image_file_name: str,
        db_receipt_id: int,
        receipt_image_path: Optional[str] = None
    ):
        """
        仕入DBの該当SKUに画像ファイル名を自動入力
        
        Args:
            purchase_date: レシート日付（yyyy-MM-dd形式）
            purchase_time: レシート時刻（HH:MM形式、Noneの場合は時刻比較なし）
            store_code: 店舗コード
            image_file_name: 画像ファイル名（拡張子なし、識別子として使用）
            db_receipt_id: レシートDBのID
        """
        from pathlib import Path
        from datetime import datetime
        log_path = Path(__file__).resolve().parents[2] / "desktop_error.log"
        
        def _write_log(message: str):
            """デバッグログを書き込む"""
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 画像ファイル名自動入力処理\n")
                    f.write(f"{message}\n")
                    f.write("-" * 80 + "\n")
            except Exception:
                pass
        
        _write_log(f"開始: 日付={purchase_date}, 時刻={purchase_time}, 店舗コード={store_code}, 画像ファイル名={image_file_name}, DB ID={db_receipt_id}")
        
        # 仕入管理タブのデータを優先的に使用
        inventory_records = []
        inventory_data_exists = False
        if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
            inventory_data_exists = True
            try:
                import pandas as pd
                inventory_records = self.inventory_widget.inventory_data.fillna("").to_dict(orient="records")
                _write_log(f"仕入管理タブから{len(inventory_records)}件のデータを取得")
            except Exception as e:
                _write_log(f"仕入管理タブのデータ取得エラー: {e}")
        else:
            _write_log(f"仕入管理タブのデータが存在しません: inventory_widget={self.inventory_widget is not None}, hasattr={hasattr(self.inventory_widget, 'inventory_data') if self.inventory_widget else False}, inventory_data={self.inventory_widget.inventory_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') else None}")
        
        # 仕入DBの全データを取得（フォールバック）
        purchase_records = []
        if self.product_widget:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            _write_log(f"仕入DBから{len(purchase_records)}件のデータを取得")
        
        # 仕入管理タブのデータを優先、なければ仕入DBを使用
        if inventory_records:
            target_records = inventory_records
            _write_log("仕入管理タブのデータを使用")
        elif purchase_records:
            target_records = purchase_records
            _write_log("仕入DBのデータを使用")
        else:
            _write_log("データが見つかりません")
            return
        
        # 日付を正規化（yyyy-MM-dd形式）
        normalized_date = purchase_date.replace('/', '-')
        if ' ' in normalized_date:
            normalized_date = normalized_date.split(' ')[0]
        
        # レシート時刻をdatetimeに変換（比較用）
        receipt_datetime = None
        if purchase_time:
            try:
                from datetime import datetime
                time_parts = purchase_time.split(':')
                if len(time_parts) == 2:
                    hour = int(time_parts[0])
                    minute = int(time_parts[1])
                    receipt_datetime = datetime.strptime(f"{normalized_date} {hour:02d}:{minute:02d}:00", "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        
        # ProductDatabaseを取得
        from database.product_db import ProductDatabase
        product_db = ProductDatabase()
        
        matched_count = 0
        updated_count = 0
        
        # 仕入DBから該当するSKUを検索
        matched_skus = []
        for record in target_records:
            # SKUを取得
            sku = record.get('SKU') or record.get('sku') or ''
            if not sku or sku == '未実装':
                continue
            
            # 店舗コードでフィルタリング
            record_store_code = record.get('仕入先') or record.get('store_code') or ''
            if record_store_code != store_code:
                continue
            
            # 日付でフィルタリング
            record_date = record.get('仕入れ日') or record.get('purchase_date') or ''
            if not record_date:
                continue
            
            # 日付の正規化（時刻が含まれている場合も対応）
            normalized_record_date = str(record_date).replace('/', '-')
            record_date_only = normalized_record_date
            if ' ' in normalized_record_date:
                record_date_only = normalized_record_date.split(' ')[0]
            
            # 日付が一致しない場合はスキップ
            if not record_date_only.startswith(normalized_date):
                continue
            
            _write_log(f"マッチ候補: SKU={sku}, 日付={record_date}, 店舗コード={record_store_code}")
            
            # レシート時刻より前のSKUのみを対象
            if receipt_datetime:
                try:
                    # 仕入データの時刻を取得
                    record_datetime_str = str(record.get('仕入れ日') or record.get('purchase_date') or '')
                    record_datetime = None
                    
                    if ' ' in record_datetime_str:
                        # 時刻が含まれている場合
                        # フォーマットを正規化（/を-に変換）
                        normalized_datetime_str = record_datetime_str.replace('/', '-')
                        # 複数のフォーマットに対応
                        datetime_formats = [
                            "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%d %H:%M",
                            "%Y/%m/%d %H:%M:%S",
                            "%Y/%m/%d %H:%M",
                        ]
                        for fmt in datetime_formats:
                            try:
                                record_datetime = datetime.strptime(normalized_datetime_str, fmt)
                                break
                            except ValueError:
                                continue
                    else:
                        # 時刻が含まれていない場合は00:00:00として扱う
                        record_datetime = datetime.strptime(f"{record_date_only} 00:00:00", "%Y-%m-%d %H:%M:%S")
                    
                    if record_datetime is None:
                        # パースに失敗した場合は00:00:00として扱う
                        record_datetime = datetime.strptime(f"{record_date_only} 00:00:00", "%Y-%m-%d %H:%M:%S")
                    
                    # レシート時刻より後の場合はスキップ
                    if record_datetime >= receipt_datetime:
                        _write_log(f"時刻フィルタ: SKU={sku} はレシート時刻より後（{record_datetime} >= {receipt_datetime}）")
                        continue
                except Exception as e:
                    # 時刻の比較に失敗した場合はスキップ
                    _write_log(f"時刻比較エラー: SKU={sku}, エラー={e}, record_datetime_str={record_datetime_str}")
                    continue
            
            # 既にレシートIDが設定されているか確認
            # 仕入管理タブのデータに既にレシートIDがある場合はスキップ
            if inventory_records:
                existing_receipt_id = record.get('レシートID') or record.get('receipt_id') or ''
                if existing_receipt_id:
                    _write_log(f"スキップ: SKU={sku} は既にレシートID={existing_receipt_id}が設定されています")
                    continue
            
            # ProductDatabaseから現在のレシートIDを確認
            product = product_db.get_by_sku(sku)
            product_already_has_receipt_id = False
            if product:
                # productsテーブルに存在する場合
                if product.get('receipt_id'):
                    # 既にレシートIDが設定されている場合でも、UI更新は実行する
                    product_already_has_receipt_id = True
                    matched_count += 1
                    matched_skus.append(sku)
                    _write_log(f"情報: SKU={sku} はproductsテーブルに既にレシートID={product.get('receipt_id')}が設定されています（UI更新のみ実行）")
                else:
                    # レシートIDを設定
                    try:
                        # ProductDatabaseのlink_receiptメソッドを使用
                        # receipt_idは整数（DBのID）を使用
                        if product_db.link_receipt(sku, db_receipt_id):
                            updated_count += 1
                            matched_count += 1
                            matched_skus.append(sku)
                            _write_log(f"更新成功: SKU={sku} にレシートID={db_receipt_id}を設定")
                    except Exception as e:
                        # エラーはログに記録して続行
                        _write_log(f"エラー: SKU={sku}, エラー={e}")
            else:
                # productsテーブルに存在しない場合は、仕入DBのデータからproductsテーブルに登録
                try:
                    # JANコードの.0を削除（数値として読み込まれた場合の正規化）
                    def normalize_jan(jan_value):
                        """JANコードから.0を削除して文字列に変換"""
                        if not jan_value:
                            return None
                        jan_str = str(jan_value).strip()
                        # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
                        if jan_str.endswith(".0"):
                            jan_str = jan_str[:-2]
                        # 数字以外の文字を除去（念のため）
                        jan_str = ''.join(c for c in jan_str if c.isdigit())
                        return jan_str if jan_str else None
                    
                    # 仕入DBのデータから商品情報を構築
                    jan_value = record.get('JAN') or record.get('jan') or None
                    product_data = {
                        "sku": sku,
                        "jan": normalize_jan(jan_value),
                        "asin": record.get('ASIN') or record.get('asin') or None,
                        "product_name": record.get('商品名') or record.get('product_name') or None,
                        "purchase_date": record_date_only,
                        "purchase_price": record.get('仕入れ価格') or record.get('purchase_price') or None,
                        "quantity": record.get('仕入れ個数') or record.get('quantity') or None,
                        "store_code": store_code,
                        "store_name": record.get('店舗名') or record.get('store_name') or None,
                        "receipt_id": db_receipt_id,
                    }
                    # 数値型の変換
                    if product_data.get("purchase_price"):
                        try:
                            product_data["purchase_price"] = int(product_data["purchase_price"])
                        except (ValueError, TypeError):
                            product_data["purchase_price"] = None
                    if product_data.get("quantity"):
                        try:
                            product_data["quantity"] = int(product_data["quantity"])
                        except (ValueError, TypeError):
                            product_data["quantity"] = None
                    
                    # productsテーブルに登録
                    product_db.upsert(product_data)
                    updated_count += 1
                    matched_count += 1
                    matched_skus.append(sku)
                    _write_log(f"新規登録成功: SKU={sku} をproductsテーブルに登録（レシートID={db_receipt_id}）")
                except Exception as e:
                    # エラーはログに記録して続行
                    _write_log(f"新規登録エラー: SKU={sku}, エラー={e}")
            
            # 仕入管理タブのデータにもレシートIDを設定
            # inventory_dataが存在する場合はinventory_dataを更新
            # inventory_dataがNoneでも、filtered_dataが存在する場合はfiltered_dataを更新
            _write_log(f"デバッグ: inventory_data_exists={inventory_data_exists}, inventory_widget={self.inventory_widget is not None}, hasattr={hasattr(self.inventory_widget, 'inventory_data') if self.inventory_widget else False}, inventory_data={self.inventory_widget.inventory_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') else None}, filtered_data={self.inventory_widget.filtered_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') else None}")
            
            # inventory_dataが存在する場合
            if inventory_data_exists and self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
                try:
                    import pandas as pd
                    _write_log(f"仕入管理タブ更新開始: SKU={sku}, inventory_data存在={self.inventory_widget.inventory_data is not None}")
                    
                    # レシートID列が存在しない場合は追加
                    if 'レシートID' not in self.inventory_widget.inventory_data.columns:
                        self.inventory_widget.inventory_data['レシートID'] = ''
                        _write_log("レシートID列を追加しました")
                    
                    # inventory_dataから該当SKUの行を検索
                    matched_in_inventory = False
                    target_sku_normalized = str(sku).strip().lower()
                    _write_log(f"SKU検索開始: target_sku='{sku}', normalized='{target_sku_normalized}'")
                    _write_log(f"inventory_data行数: {len(self.inventory_widget.inventory_data)}")
                    
                    for idx, row in self.inventory_widget.inventory_data.iterrows():
                        row_sku = str(row.get('SKU') or '').strip()
                        row_sku_normalized = row_sku.lower()
                        is_match = (row_sku == sku or 
                                   row_sku == str(sku).strip() or 
                                   row_sku_normalized == target_sku_normalized)
                        
                        if idx < 5:  # 最初の5行だけログ出力（デバッグ用）
                            _write_log(f"SKU比較[{idx}]: row_sku='{row_sku}', target_sku='{sku}', 一致={is_match}")
                        
                        if is_match:
                            # 画像ファイル名を設定（識別子として使用）
                            self.inventory_widget.inventory_data.at[idx, 'レシートID'] = image_file_name
                            # ファイルパス情報も保存（画像リンク用）
                            if receipt_image_path:
                                if 'レシート画像パス' not in self.inventory_widget.inventory_data.columns:
                                    self.inventory_widget.inventory_data['レシート画像パス'] = ''
                                self.inventory_widget.inventory_data.at[idx, 'レシート画像パス'] = receipt_image_path
                            matched_in_inventory = True
                            _write_log(f"仕入管理タブ更新成功: SKU={sku} (idx={idx}) に画像ファイル名={image_file_name}, ファイルパス={receipt_image_path}を設定")
                            # 確認のため、設定後の値をログ出力
                            updated_value = self.inventory_widget.inventory_data.at[idx, 'レシートID']
                            _write_log(f"設定確認: idx={idx}の画像ファイル名={updated_value}")
                            break
                    
                    if not matched_in_inventory:
                        _write_log(f"警告: SKU={sku} がinventory_dataに見つかりませんでした（全{len(self.inventory_widget.inventory_data)}行を検索）")
                    
                    # filtered_dataも更新（表示用）
                    if hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                        if 'レシートID' not in self.inventory_widget.filtered_data.columns:
                            self.inventory_widget.filtered_data['レシートID'] = ''
                        # filtered_dataからも該当SKUの行を検索して更新
                        matched_in_filtered = False
                        _write_log(f"filtered_data検索開始: target_sku='{sku}', filtered_data行数={len(self.inventory_widget.filtered_data)}")
                        for idx, row in self.inventory_widget.filtered_data.iterrows():
                            row_sku = str(row.get('SKU') or '').strip()
                            row_sku_normalized = row_sku.lower()
                            is_match = (row_sku == sku or 
                                       row_sku == str(sku).strip() or 
                                       row_sku_normalized == target_sku_normalized)
                            if is_match:
                                self.inventory_widget.filtered_data.at[idx, 'レシートID'] = image_file_name
                                # ファイルパス情報も保存（画像リンク用）
                                if receipt_image_path:
                                    if 'レシート画像パス' not in self.inventory_widget.filtered_data.columns:
                                        self.inventory_widget.filtered_data['レシート画像パス'] = ''
                                    self.inventory_widget.filtered_data.at[idx, 'レシート画像パス'] = receipt_image_path
                                matched_in_filtered = True
                                _write_log(f"filtered_data更新成功: SKU={sku} (idx={idx}) に画像ファイル名={image_file_name}, ファイルパス={receipt_image_path}を設定")
                                # 確認のため、設定後の値をログ出力
                                updated_value = self.inventory_widget.filtered_data.at[idx, 'レシートID']
                                _write_log(f"filtered_data設定確認: idx={idx}の画像ファイル名={updated_value}")
                                break
                        
                        if not matched_in_filtered:
                            _write_log(f"警告: SKU={sku} がfiltered_dataに見つかりませんでした（全{len(self.inventory_widget.filtered_data)}行を検索）")
                except Exception as e:
                    import traceback
                    _write_log(f"仕入管理タブ更新エラー: SKU={sku}, エラー={e}\n{traceback.format_exc()}")
            
            # inventory_dataがNoneでも、filtered_dataが存在する場合はfiltered_dataを更新
            elif self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                try:
                    import pandas as pd
                    _write_log(f"filtered_dataのみ更新開始: SKU={sku}, filtered_data存在={self.inventory_widget.filtered_data is not None}")
                    
                    # レシートID列が存在しない場合は追加
                    if 'レシートID' not in self.inventory_widget.filtered_data.columns:
                        self.inventory_widget.filtered_data['レシートID'] = ''
                        _write_log("filtered_dataにレシートID列を追加しました")
                    
                    # filtered_dataから該当SKUの行を検索して更新
                    matched_in_filtered = False
                    target_sku_normalized = str(sku).strip().lower()
                    _write_log(f"filtered_data検索開始: target_sku='{sku}', normalized='{target_sku_normalized}'")
                    _write_log(f"filtered_data行数: {len(self.inventory_widget.filtered_data)}")
                    
                    for idx, row in self.inventory_widget.filtered_data.iterrows():
                        row_sku = str(row.get('SKU') or '').strip()
                        row_sku_normalized = row_sku.lower()
                        is_match = (row_sku == sku or 
                                   row_sku == str(sku).strip() or 
                                   row_sku_normalized == target_sku_normalized)
                        
                        if is_match:
                            self.inventory_widget.filtered_data.at[idx, 'レシートID'] = image_file_name
                            # ファイルパス情報も保存（画像リンク用）
                            if receipt_image_path:
                                if 'レシート画像パス' not in self.inventory_widget.filtered_data.columns:
                                    self.inventory_widget.filtered_data['レシート画像パス'] = ''
                                self.inventory_widget.filtered_data.at[idx, 'レシート画像パス'] = receipt_image_path
                            matched_in_filtered = True
                            _write_log(f"filtered_data更新成功: SKU={sku} (idx={idx}) に画像ファイル名={image_file_name}, ファイルパス={receipt_image_path}を設定")
                            # 確認のため、設定後の値をログ出力
                            updated_value = self.inventory_widget.filtered_data.at[idx, 'レシートID']
                            _write_log(f"filtered_data設定確認: idx={idx}の画像ファイル名={updated_value}")
                            break
                    
                    if not matched_in_filtered:
                        _write_log(f"警告: SKU={sku} がfiltered_dataに見つかりませんでした（全{len(self.inventory_widget.filtered_data)}行を検索）")
                except Exception as e:
                    import traceback
                    _write_log(f"filtered_data更新エラー: SKU={sku}, エラー={e}\n{traceback.format_exc()}")
        
        # 結果をログに記録
        _write_log(f"完了: マッチ={matched_count}件, 更新={updated_count}件, 画像ファイル名={image_file_name}, 対象SKU={matched_skus}")
        
        # 仕入管理タブのテーブル表示を更新（ループの外で一度だけ）
        # inventory_dataが存在する場合、またはfiltered_dataが存在する場合は更新する
        has_filtered_data = self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None
        _write_log(f"テーブル更新チェック: matched_count={matched_count}, inventory_data_exists={inventory_data_exists}, has_filtered_data={has_filtered_data}, inventory_widget={self.inventory_widget is not None}, has_update_table={hasattr(self.inventory_widget, 'update_table') if self.inventory_widget else False}")
        if matched_count > 0 and self.inventory_widget and hasattr(self.inventory_widget, 'update_table') and (inventory_data_exists or has_filtered_data):
            try:
                _write_log("仕入管理タブのテーブル表示を更新します")
                # 更新前のレシートID値を確認
                sample_skus = matched_skus[:3] if len(matched_skus) > 0 else []
                for sample_sku in sample_skus:
                    if hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
                        for idx, row in self.inventory_widget.inventory_data.iterrows():
                            if str(row.get('SKU') or '').strip() == sample_sku:
                                receipt_id_value = row.get('レシートID', '')
                                _write_log(f"更新前確認(inventory_data): SKU={sample_sku}, レシートID={receipt_id_value}")
                                break
                    elif hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                        for idx, row in self.inventory_widget.filtered_data.iterrows():
                            if str(row.get('SKU') or '').strip() == sample_sku:
                                receipt_id_value = row.get('レシートID', '')
                                _write_log(f"更新前確認(filtered_data): SKU={sample_sku}, レシートID={receipt_id_value}")
                                break
                self.inventory_widget.update_table()
                _write_log("仕入管理タブのテーブル表示を更新しました")
            except Exception as e:
                import traceback
                _write_log(f"テーブル更新エラー: {e}\n{traceback.format_exc()}")
        else:
            _write_log("テーブル更新をスキップしました（条件を満たしていません）")
            # inventory_dataもfiltered_dataもNoneの場合、テーブルから直接レシートIDを設定
            if matched_count > 0 and self.inventory_widget and hasattr(self.inventory_widget, 'data_table'):
                try:
                    from PySide6.QtWidgets import QTableWidgetItem
                    _write_log("テーブルから直接レシートIDを設定します")
                    data_table = self.inventory_widget.data_table
                    row_count = data_table.rowCount()
                    _write_log(f"テーブル行数: {row_count}")
                    
                    # カラムヘッダーからSKUとレシートIDのインデックスを取得
                    column_headers = []
                    if hasattr(self.inventory_widget, 'column_headers'):
                        column_headers = self.inventory_widget.column_headers
                    else:
                        # カラムヘッダーが取得できない場合は、デフォルトの順序を使用
                        column_headers = [
                            "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
                            "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "コメント",
                            "発送方法", "仕入先", "コンディション説明", "保証期間", "レシートID"
                        ]
                    
                    sku_column_idx = column_headers.index("SKU") if "SKU" in column_headers else 2
                    receipt_id_column_idx = column_headers.index("レシートID") if "レシートID" in column_headers else 16
                    _write_log(f"SKU列インデックス: {sku_column_idx}, レシートID列インデックス: {receipt_id_column_idx}")
                    
                    # テーブルの各行を検索して、該当するSKUの行にレシートIDを設定
                    updated_rows = 0
                    for row_idx in range(row_count):
                        sku_item = data_table.item(row_idx, sku_column_idx)
                        if sku_item:
                            row_sku = str(sku_item.text()).strip()
                            # SKUが「未実装」の場合はスキップ
                            if row_sku == "未実装" or not row_sku:
                                continue
                            
                            # マッチしたSKUか確認
                            if row_sku in matched_skus:
                                # 画像ファイル名を設定
                                receipt_id_item = data_table.item(row_idx, receipt_id_column_idx)
                                if receipt_id_item:
                                    receipt_id_item.setText(image_file_name)
                                else:
                                    receipt_id_item = QTableWidgetItem(image_file_name)
                                    data_table.setItem(row_idx, receipt_id_column_idx, receipt_id_item)
                                updated_rows += 1
                                _write_log(f"テーブル直接更新: 行={row_idx}, SKU={row_sku}, 画像ファイル名={image_file_name}")
                    
                    _write_log(f"テーブル直接更新完了: {updated_rows}行を更新しました")
                except Exception as e:
                    import traceback
                    _write_log(f"テーブル直接更新エラー: {e}\n{traceback.format_exc()}")
        
        if matched_count > 0 or updated_count > 0:
            # 商品DBタブの表示を更新（メソッドが存在する場合）
            if self.product_widget and hasattr(self.product_widget, 'load_products'):
                try:
                    self.product_widget.load_products()
                except Exception:
                    pass
            
            # 仕入DBタブ（ProductWidget内）のレシートIDを更新
            if self.product_widget and hasattr(self.product_widget, 'purchase_all_records'):
                try:
                    _write_log("仕入DBタブ（ProductWidget）のレシートIDを更新します")
                    updated_purchase_records = 0
                    for record in self.product_widget.purchase_all_records:
                        sku = record.get('SKU') or record.get('sku') or ''
                        if sku in matched_skus:
                            record['レシートID'] = image_file_name
                            # レシート画像列にもファイル名を設定（既存の処理と統一）
                            record['レシート画像'] = image_file_name
                            # ファイルパス情報も保存（画像リンク用）
                            if receipt_image_path:
                                record['レシート画像パス'] = receipt_image_path
                            updated_purchase_records += 1
                            _write_log(f"仕入DBタブ更新: SKU={sku}, 画像ファイル名={image_file_name}, ファイルパス={receipt_image_path}")
                    
                    # テーブルを再描画
                    if hasattr(self.product_widget, 'populate_purchase_table'):
                        self.product_widget.populate_purchase_table(self.product_widget.purchase_all_records)
                        _write_log(f"仕入DBタブテーブル再描画完了: {updated_purchase_records}件のレシートIDを更新しました")
                except Exception as e:
                    import traceback
                    _write_log(f"仕入DBタブ更新エラー: {e}\n{traceback.format_exc()}")
    
    def _populate_candidate_sku_list(
        self,
        candidate_skus_list: QListWidget,
        receipt: Dict[str, Any],
        existing_skus: set,
        *,
        purchase_date_str: Optional[str] = None,
        purchase_time_str: Optional[str] = None,
        store_code: Optional[str] = None,
    ) -> None:
        """手動調整: 仕入DB候補SKUを店舗コード一致→同日の順でリストに表示"""
        candidate_skus_list.clear()
        if not self.product_widget:
            return
        purchase_records = getattr(self.product_widget, "purchase_all_records", [])
        if not purchase_records:
            return
        receipt_ctx = dict(receipt)
        if purchase_date_str:
            receipt_ctx["purchase_date"] = purchase_date_str
        if purchase_time_str is not None:
            receipt_ctx["purchase_time"] = purchase_time_str
        if store_code is not None:
            receipt_ctx["store_code"] = store_code
        entries = build_manual_candidate_entries(
            receipt_ctx,
            purchase_records,
            set(existing_skus),
            purchase_date_str=purchase_date_str,
            store_code=store_code,
        )
        for entry in entries:
            candidate_skus_list.addItem(entry["display_text"])
            list_item = candidate_skus_list.item(candidate_skus_list.count() - 1)
            if list_item:
                list_item.setData(Qt.UserRole, entry["sku"])

    def bulk_match_receipts(self):
        """一覧に表示されている全レシートに対してマッチング候補を一括適用"""
        if not self.product_widget:
            QMessageBox.warning(self, "警告", "仕入DBへの参照がありません。")
            return
        self._reset_post_rename_workflow_gate()
        purchase_records = self._get_purchase_records()
        if not purchase_records:
            QMessageBox.warning(self, "警告", "仕入DBにデータがありません。")
            return
        # 現在のレシート一覧・保証書一覧に対応するレシートのみ取得
        receipts = sort_receipts_for_bulk_matching(self._get_current_receipts_from_tables())
        print(f"[一括マッチング] 取得したレシート数（現在の一覧）: {len(receipts)}")
        updated = 0
        skipped_no_candidates = 0
        skipped_no_updates = 0
        used_skus: set[str] = set()
        for receipt in receipts:
            try:
                candidates = self.matching_service.find_match_candidates(
                    receipt,
                    purchase_records,
                    preferred_store_code=receipt.get('store_code'),
                )
                if not candidates:
                    skipped_no_candidates += 1
                    print(f"[一括マッチング] スキップ（候補なし）: receipt_id={receipt.get('id')}, 日付={receipt.get('purchase_date')}, 店舗={receipt.get('store_name_raw')}")
                    continue
                cand = candidates[0]
                updates = {}
                # 店舗コード（候補が存在し、現在のレシートに店舗コードがない、または異なる場合に更新）
                current_store_code = receipt.get('store_code') or ""
                matched_store_code = cand.store_code
                store_name_updated = False
                if getattr(cand, 'account_title', None):
                    updates["account_title"] = cand.account_title
                if matched_store_code and matched_store_code != current_store_code:
                    updates["store_code"] = matched_store_code
                    # 店舗名を店舗マスタまたは経費先の正式名称に更新
                    try:
                        store = self.store_db.get_store_by_code(matched_store_code)
                        if store and store.get("store_name"):
                            updates["store_name_raw"] = store.get("store_name")
                            store_name_updated = True
                        else:
                            dest = self.store_db.get_expense_destination_by_code(matched_store_code)
                            if dest and dest.get("name"):
                                updates["store_name_raw"] = dest.get("name")
                                store_name_updated = True
                    except Exception:
                        pass
                elif not current_store_code and matched_store_code:
                    # 店舗コードが空の場合、候補から店舗コードを設定
                    updates["store_code"] = matched_store_code
                    try:
                        store = self.store_db.get_store_by_code(matched_store_code)
                        if store and store.get("store_name"):
                            updates["store_name_raw"] = store.get("store_name")
                            store_name_updated = True
                        else:
                            dest = self.store_db.get_expense_destination_by_code(matched_store_code)
                            if dest and dest.get("name"):
                                updates["store_name_raw"] = dest.get("name")
                                store_name_updated = True
                    except Exception:
                        pass
                
                # 経費先マッチ時：経費先一覧の登録番号が空ならレシートの登録番号を入力
                if getattr(cand, 'account_title', None) and matched_store_code:
                    try:
                        dest = self.store_db.get_expense_destination_by_code(matched_store_code)
                        reg_from_receipt = (receipt.get("registration_number") or "").strip()
                        if dest and reg_from_receipt and not (dest.get("registration_number") or "").strip():
                            self.store_db.update_expense_destination_registration_number(dest["id"], reg_from_receipt)
                    except Exception:
                        pass
                
                # 紐付き候補SKU（レシート時刻より前・使用済みSKU除外・同一店舗は早いレシートから）
                file_path = receipt.get("file_path") or receipt.get("original_file_path") or ""
                image_file_name = Path(file_path).stem if file_path else ""
                candidate_skus = collect_link_skus_for_receipt(
                    receipt,
                    purchase_records,
                    used_skus,
                    store_code=matched_store_code or receipt.get("store_code"),
                    image_file_name=image_file_name,
                )

                # 紐付き候補SKUを更新
                if candidate_skus:
                    used_skus.update(candidate_skus)
                    updates["linked_skus"] = ",".join(candidate_skus)
                    sku_total = self._compute_linked_sku_total(candidate_skus, purchase_records)
                    receipt_total = receipt.get('total_amount') or 0
                    try:
                        receipt_total = int(receipt_total) if receipt_total else 0
                    except (ValueError, TypeError):
                        receipt_total = 0
                    updates["price_difference"] = int(sku_total - receipt_total)

                # 差額OKの行は店舗名を店舗コード列と同じ表示に揃える
                self._apply_store_name_for_acceptable_difference(
                    receipt, updates, purchase_records
                )

                if updates:
                    # 10円以下の差額の場合は自動修正を提案
                    difference = updates.get("price_difference")
                    if (
                        difference is not None
                        and abs(difference) <= 10
                        and abs(difference) > 0
                        and RECEIPT_MUTATES_PURCHASE_DB_PRICE
                    ):
                        # 自動修正の確認ダイアログ（仕入DBの価格を変えるため、ポリシーが True のときのみ）
                        reply = QMessageBox.question(
                            self,
                            "差額自動修正",
                            f"レシートID: {receipt.get('receipt_id', '不明')}\n"
                            f"差額: ¥{int(difference):,}\n\n"
                            f"10円以下の差額を自動で修正しますか？",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.Yes
                        )
                        
                        if reply == QMessageBox.Yes:
                            # 自動修正を実行
                            # 紐付けSKUの価格を均等に調整
                            merged_skus = [s.strip() for s in updates.get("linked_skus", "").split(',') if s.strip()]
                            if merged_skus and len(merged_skus) > 0:
                                # 差額を均等配分（10円以下の端数は最後のSKUに）
                                adjustment_per_sku = difference // len(merged_skus)
                                remainder = difference % len(merged_skus)
                                
                                # 10円以下の端数は最後のSKUに転嫁
                                small_remainder = 0
                                if abs(remainder) <= 10:
                                    small_remainder = remainder
                                    remainder = 0
                                else:
                                    remainder_per_sku = remainder // len(merged_skus)
                                    small_remainder = remainder % len(merged_skus)
                                    adjustment_per_sku += remainder_per_sku
                                
                                # 各SKUの金額を更新（仕入れ個数 × 仕入れ価格の合計を調整）
                                for idx, sku in enumerate(merged_skus):
                                    # 合計金額に対する調整額
                                    total_adjustment = adjustment_per_sku
                                    if idx == len(merged_skus) - 1:
                                        total_adjustment += small_remainder
                                    
                                    # 仕入DBから該当SKUを検索して価格を更新
                                    for record in purchase_records:
                                        record_sku = record.get('SKU') or record.get('sku', '')
                                        if record_sku and record_sku.strip() == sku:
                                            current_price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                                            try:
                                                current_price = float(current_price) if current_price else 0
                                            except (ValueError, TypeError):
                                                current_price = 0
                                            
                                            # 仕入れ個数を取得
                                            quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                                            try:
                                                quantity = float(quantity) if quantity else 1
                                            except (ValueError, TypeError):
                                                quantity = 1
                                            
                                            # 現在の合計金額 = 仕入れ個数 × 仕入れ価格
                                            current_total = current_price * quantity
                                            
                                            # 新しい合計金額 = 現在の合計金額 - 調整額
                                            new_total = current_total - total_adjustment
                                            if new_total < 0:
                                                new_total = 0
                                            
                                            # 新しい仕入れ価格 = 新しい合計金額 / 仕入れ個数
                                            if quantity > 0:
                                                new_price = new_total / quantity
                                            else:
                                                new_price = new_total
                                            
                                            # 仕入DBの価格を更新
                                            record['仕入れ価格'] = int(new_price)
                                            
                                            # 見込み利益・損益分岐点・利益率・ROIを再計算
                                            planned_price = record.get('販売予定価格') or record.get('planned_price') or 0
                                            try:
                                                planned_price = float(planned_price) if planned_price else 0
                                            except (ValueError, TypeError):
                                                planned_price = 0
                                            
                                            # 見込み利益 = 販売予定価格 - 仕入れ価格
                                            expected_profit = planned_price - new_price if planned_price > 0 else 0
                                            record['見込み利益'] = expected_profit
                                            
                                            other_cost = record.get('その他費用') or record.get('other_cost') or 0
                                            try:
                                                other_cost = float(other_cost) if other_cost else 0
                                            except (ValueError, TypeError):
                                                other_cost = 0
                                            be = compute_break_even_for_record(record)
                                            if be is not None:
                                                record["損益分岐点"] = round(be, 2)
                                            else:
                                                record["損益分岐点"] = new_price + other_cost
                                            
                                            # 利益率 = (見込み利益 / 販売予定価格) * 100
                                            if planned_price > 0:
                                                expected_margin = (expected_profit / planned_price) * 100
                                            else:
                                                expected_margin = 0.0
                                            record['想定利益率'] = round(expected_margin, 2)
                                            
                                            # ROI = (見込み利益 / 仕入れ価格) * 100
                                            if new_price > 0:
                                                expected_roi = (expected_profit / new_price) * 100
                                            else:
                                                expected_roi = 0.0
                                            record['想定ROI'] = round(expected_roi, 2)
                                            break
                                
                                # 差額を0に更新
                                updates["price_difference"] = 0
                    
                    self.receipt_db.update_receipt(receipt.get('id'), updates)
                    updated += 1
                    print(f"[一括マッチング] 更新: receipt_id={receipt.get('id')}, 日付={receipt.get('purchase_date')}, 店舗={receipt.get('store_name_raw')}, updates={updates}")
                else:
                    skipped_no_updates += 1
                    print(f"[一括マッチング] スキップ（更新なし）: receipt_id={receipt.get('id')}, 日付={receipt.get('purchase_date')}, 店舗={receipt.get('store_name_raw')}, 店舗コード={receipt.get('store_code')}, candidate_skus={candidate_skus}")
            except Exception as e:
                import traceback
                print(f"[一括マッチング] エラー: receipt_id={receipt.get('id')}, エラー={e}\n{traceback.format_exc()}")
                continue
        
        # 仕入DBの変更を反映（product_widgetのテーブルを更新）
        if self.product_widget and hasattr(self.product_widget, 'populate_purchase_table'):
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            self.product_widget.populate_purchase_table(purchase_records)
        
        # テーブルを更新（紐付き候補SKUと店舗名を表示）
        self.refresh_receipt_list()
        print(f"[一括マッチング] 完了: 更新={updated}件, 候補なし={skipped_no_candidates}件, 更新なし={skipped_no_updates}件")
        # 一括マッチング完了後は手動工程④（手動調整）へ
        self._workflow_post_step = 4
        QMessageBox.information(self, "一括マッチング", f"{updated} 件のレシートにマッチング候補を適用しました。\n（候補なし: {skipped_no_candidates}件, 更新なし: {skipped_no_updates}件）")

    def verify_receipts_with_purchases(self):
        """レシート一覧と仕入DBの照合チェック"""
        if not self.product_widget:
            QMessageBox.warning(self, "警告", "仕入DBへの参照がありません。")
            return

        purchase_records = self._get_purchase_records()
        if not purchase_records:
            QMessageBox.warning(self, "警告", "仕入DBにデータがありません。")
            return
        
        # 現在のレシート一覧・保証書一覧に対応するレシートのみ取得
        receipts = self._get_current_receipts_from_tables()
        if not receipts:
            self.verification_info_text.setText("レシートが登録されていません（現在の一覧が空です）。")
            return
        
        from datetime import datetime
        from collections import defaultdict
        
        results = []
        total_checked = 0
        total_sku_missing = 0
        total_sku_duplicate = 0
        
        for receipt in receipts:
            receipt_date = receipt.get('purchase_date') or ""
            if not receipt_date:
                continue
            
            # レシートの日付を正規化
            receipt_date_obj = None
            try:
                if "/" in receipt_date:
                    receipt_date_obj = datetime.strptime(receipt_date, "%Y/%m/%d").date()
                elif "-" in receipt_date:
                    receipt_date_obj = datetime.strptime(receipt_date[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            
            if not receipt_date_obj:
                continue
            
            # レシートのSKUを取得
            linked_skus_text = receipt.get('linked_skus', '') or ''
            receipt_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()] if linked_skus_text else []
            
            # 画像ファイル名を取得（識別子として使用）
            file_path = receipt.get('file_path') or ""
            image_file_name = Path(file_path).stem if file_path else ""  # 拡張子なしのファイル名
            
            # レシートに紐付けられている仕入DBレコードを取得
            # 1. 画像ファイル名で紐付けられているSKUを優先
            linked_records = []
            if image_file_name:
                for record in purchase_records:
                    record_receipt_id = record.get('レシートID') or record.get('receipt_id', '')
                    if record_receipt_id == image_file_name:
                        linked_records.append(record)
            
            # 2. レシートに紐付けられているSKUで照合（レシートIDで紐付けられていない場合）
            if not linked_records and receipt_skus:
                for record in purchase_records:
                    sku = record.get('SKU') or record.get('sku', '')
                    if sku and sku.strip() in receipt_skus:
                        # 日付と店舗コードも確認
                        record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                        if not record_date:
                            continue
                        
                        try:
                            record_date_str = str(record_date).strip()
                            if " " in record_date_str:
                                record_date_str = record_date_str.split(" ")[0]
                            if "T" in record_date_str:
                                record_date_str = record_date_str.split("T")[0]
                            
                            record_date_obj = None
                            if "/" in record_date_str:
                                record_date_obj = datetime.strptime(record_date_str[:10].replace("/", "-"), "%Y-%m-%d").date()
                            elif "-" in record_date_str:
                                record_date_obj = datetime.strptime(record_date_str[:10], "%Y-%m-%d").date()
                            
                            # 日付が一致する場合のみ追加
                            if receipt_date_obj == record_date_obj:
                                # 店舗コードも確認（あれば）
                                receipt_store_code = receipt.get('store_code') or ""
                                record_store_code = record.get('仕入先') or record.get('店舗コード') or record.get('store_code', '')
                                if receipt_store_code and record_store_code:
                                    # 店舗コードのみを取得（表示ラベルから抽出）
                                    if " " in str(receipt_store_code):
                                        receipt_store_code = str(receipt_store_code).split(" ")[0]
                                    if " " in str(record_store_code):
                                        record_store_code = str(record_store_code).split(" ")[0]
                                    if receipt_store_code != record_store_code:
                                        continue
                                
                                linked_records.append(record)
                        except Exception:
                            continue
            
            # 紐付けられているレコードがない場合はスキップ
            if not linked_records:
                continue
            
            total_checked += 1
            
            # 紐付けられている仕入DBレコードのSKUを取得
            purchase_skus = []
            for record in linked_records:
                sku = record.get('SKU') or record.get('sku', '')
                if sku and sku.strip():
                    purchase_skus.append(sku.strip())
            
            # SKUの漏れと重複をチェック
            receipt_sku_set = set(receipt_skus)
            purchase_sku_set = set(purchase_skus)
            
            missing_skus = purchase_sku_set - receipt_sku_set  # 仕入DBにあるがレシートにない
            duplicate_skus = []
            sku_count = defaultdict(int)
            for sku in receipt_skus:
                sku_count[sku] += 1
            for sku, count in sku_count.items():
                if count > 1:
                    duplicate_skus.append(sku)
            
            # 結果を記録
            receipt_file_path = receipt.get('file_path', '')
            receipt_file_name = Path(receipt_file_path).stem if receipt_file_path else ''
            receipt_file = receipt_file_name or receipt_file_path.split(os.sep)[-1] if receipt_file_path else ''
            
            issues = []
            if missing_skus:
                issues.append(f"SKU漏れ: {', '.join(sorted(missing_skus))}")
                total_sku_missing += len(missing_skus)
            if duplicate_skus:
                issues.append(f"SKU重複: {', '.join(sorted(duplicate_skus))}")
                total_sku_duplicate += len(duplicate_skus)
            
            if issues:
                results.append({
                    'date': receipt_date,
                    'file_name': receipt_file_name,
                    'file': receipt_file,
                    'issues': issues
                })
        
        # 結果を表示
        info_text = f"照合チェック結果\n"
        info_text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        info_text += f"チェック対象: {total_checked} 件\n"
        info_text += f"SKU漏れ: {total_sku_missing} 件\n"
        info_text += f"SKU重複: {total_sku_duplicate} 件\n"
        info_text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        if results:
            info_text += "【問題のあるレシート】\n\n"
            for result in results:
                info_text += f"日付: {result['date']}\n"
                info_text += f"画像ファイル名: {result.get('file_name', result.get('file', ''))}\n"
                info_text += f"ファイル: {result['file']}\n"
                for issue in result['issues']:
                    info_text += f"  ⚠ {issue}\n"
                info_text += "\n"
        else:
            info_text += "問題は見つかりませんでした。\n"
        
        self.verification_info_text.setText(info_text)

    # ===== ダブルクリック挙動 =====
