#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出品CSV・SKU・プライスター mixin。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QSplitter, QMessageBox, QFrame,
    QCheckBox, QSpinBox, QDateEdit, QFileDialog,
    QDialog, QDialogButtonBox, QSizePolicy, QInputDialog, QProgressDialog,
    QPlainTextEdit, QScrollArea, QFormLayout,
    QToolButton, QApplication, QAbstractItemView,
)
from PySide6.QtCore import Qt, QDate, QTime, QDateTime, Signal, QSettings, QThread, QTimer
from PySide6.QtGui import QFont, QColor, QPalette, QStandardItemModel, QStandardItem, QDesktopServices
from PySide6.QtCore import QUrl
import pandas as pd
from pathlib import Path
import re
import sys
import os
import tempfile
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime
from html import escape

# ui/inventory/ から desktop/ を import パス先頭へ
_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)


from database.store_db import StoreDatabase
from database.inventory_db import InventoryDatabase
from database.inventory_route_snapshot_db import InventoryRouteSnapshotDatabase
from database.product_db import ProductDatabase
from database.product_purchase_db import ProductPurchaseDatabase
from database.route_visit_db import RouteVisitDatabase
from database.warranty_db import WarrantyDatabase
from ui.star_rating_widget import StarRatingWidget
try:
    from utils.route_utils import mark_route_flags_from_folder
    from utils.settings_helper import (
        get_pricetar_listing_url,
        is_pro_enabled,
        is_recording_mode,
    )
except ImportError:
    from desktop.utils.route_utils import mark_route_flags_from_folder  # type: ignore
    from desktop.utils.settings_helper import (  # type: ignore
        get_pricetar_listing_url,
        is_pro_enabled,
        is_recording_mode,
    )

try:
    from ui.utils.draggable_file_icon import DraggableFileIconWidget
except ImportError:
    from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget  # type: ignore

try:
    from ui.utils.browser_front_scheduler import schedule_bring_browser_to_front
except ImportError:
    from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front  # type: ignore

from services.keepa_service import KeepaService
from services.ocr_service import OCRService
from services.purchase_cost_calc import (
    COL_PLATFORM_FEE,
    COL_SHIPPING,
    COL_TOTAL_COST,
    COL_LEGACY_AMAZON_FEE,
    augment_purchase_cost_record,
    backfill_total_cost_dataframe,
    cell_has_numeric_value,
    fee_storage_value,
    format_money_display,
    is_fee_amount_column,
    migrate_dataframe_fee_columns,
    read_fee_fields,
    recalculate_profit_fields,
    sync_total_cost_field,
    to_float as purchase_cost_to_float,
)

from .support import (
    _PRICETAR_BROWSER_TITLE_KEYWORDS,
    _WORKFLOW_PIPELINE_SEGMENTS,
    _WORKFLOW_PIPELINE_SEP,
    _ACTION_TO_PIPELINE_STEP,
    _format_status_prefix_html,
    _format_workflow_pipeline_html,
    _normalize_condition_note_newlines,
    _to_stored_newlines,
    _is_repricing_enabled_value,
    SALES_CHANNEL_OPTIONS,
    SHIPPING_METHOD_OPTIONS,
)


class InventoryListingMixin:
    def _set_listing_csv_drag_file(self, file_path: str) -> None:
        """出品CSV保存後、プライスターへドラッグするファイルをパネルに表示する。"""
        path = str(file_path or "").strip()
        self._last_saved_listing_csv_path = path if path and Path(path).is_file() else None
        if not self._last_saved_listing_csv_path:
            if hasattr(self, "listing_drop_panel"):
                self.listing_drop_panel.setVisible(False)
            if hasattr(self, "listing_csv_drag_icon"):
                self.listing_csv_drag_icon.clear_file()
            if hasattr(self, "listing_open_folder_btn"):
                self.listing_open_folder_btn.setEnabled(False)
            if hasattr(self, "listing_open_browser_btn"):
                self.listing_open_browser_btn.setEnabled(False)
            return

        self.listing_csv_drag_icon.set_file_path(self._last_saved_listing_csv_path)
        self.listing_drop_filename.setText(self._last_saved_listing_csv_path)
        self.listing_drop_hint.setText(
            "「ブラウザで開く」後、左のCSVアイコンをドラッグしてプライスターへ送ってください"
        )
        self.listing_open_folder_btn.setEnabled(True)
        self.listing_open_browser_btn.setEnabled(True)
        self.listing_drop_panel.setVisible(True)

    def _get_pricetar_listing_url(self) -> str:
        try:
            return get_pricetar_listing_url()
        except Exception:
            return "https://jp3.pricetar.com/seller/product/csvwarehousing"

    def _open_pricetar_in_browser(self) -> None:
        """プライスター CSV入庫画面を既定ブラウザで開く。"""
        listing_url = self._get_pricetar_listing_url()
        try:
            QDesktopServices.openUrl(QUrl(listing_url))
        except Exception as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"ブラウザでプライスターを開けませんでした:\n{e}\n\n"
                f"手動で以下にアクセスしてください:\n{listing_url}",
            )
            return

        self.listing_drop_hint.setText(
            "ブラウザでプライスターを開きました。"
            "左のCSVアイコンをドラッグしてドロップ欄へ送ってください。"
            "（ドラッグ中はブラウザが最前面に出ます）"
        )
        schedule_bring_browser_to_front(
            _PRICETAR_BROWSER_TITLE_KEYWORDS,
            pin_topmost_until_ms=8000,
        )

    def _open_last_listing_csv_folder(self) -> None:
        """直近に保存した出品CSVのフォルダを開く。"""
        path = self._last_saved_listing_csv_path
        if not path or not Path(path).is_file():
            QMessageBox.information(
                self,
                "情報",
                "保存済みの出品CSVがありません。\n先に「出品CSV生成」を実行してください。",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def create_listing_settings_section(self) -> QWidget:
        """出品リスト生成設定のUI"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        self.chk_include_title = QCheckBox("タイトルを出力する")
        self.chk_include_title.setChecked(True)
        self.chk_include_title.setToolTip("無効にすると、出品CSVのtitle列を空欄で出力します")
        layout.addWidget(self.chk_include_title)

        # 自己発送SKU末尾M挿入設定（タイトルの次に配置）
        self.chk_append_m_for_self_ship = QCheckBox("自己発送末尾にMを挿入")
        self.chk_append_m_for_self_ship.setToolTip("有効にすると、発送方法が『自己発送』の商品は生成されたSKUの末尾にMを付けます")
        layout.addWidget(self.chk_append_m_for_self_ship)
        
        # 高値設定と +% は隣り合わせで配置
        self.chk_enable_takane = QCheckBox("高値を設定する")
        self.chk_enable_takane.setToolTip("有効にすると、takane欄にpriceの〇%上を自動設定")
        layout.addWidget(self.chk_enable_takane)
        
        self.lbl_takane_pct = QLabel("+%:")
        layout.addWidget(self.lbl_takane_pct)
        
        self.spin_takane_pct = QSpinBox()
        self.spin_takane_pct.setRange(0, 200)
        self.spin_takane_pct.setValue(5)
        self.spin_takane_pct.setFixedWidth(60)
        layout.addWidget(self.spin_takane_pct)
        
        layout.addStretch()
        
        # 永続化
        self.chk_include_title.toggled.connect(self.save_listing_settings)
        self.chk_enable_takane.toggled.connect(self.save_listing_settings)
        self.chk_append_m_for_self_ship.toggled.connect(self.save_listing_settings)
        self.spin_takane_pct.valueChanged.connect(self.save_listing_settings)
        self.load_listing_settings()
        
        return container

    def _load_default_base_folder(self):
        """仕入処理用のデフォルトフォルダを設定から読み込んで表示"""
        try:
            s = self._get_qsettings()
            base = s.value("inventory/default_base_folder", "", type=str)
            if hasattr(self, "default_base_folder_edit"):
                self.default_base_folder_edit.setText(base or "")
        except Exception as e:
            print(f"デフォルトフォルダ設定ロード失敗: {e}")

    def browse_default_base_folder(self):
        """デフォルトフォルダをユーザーに選択させて保存"""
        try:
            from pathlib import Path
            s = self._get_qsettings()
            current = s.value("inventory/default_base_folder", "", type=str)
            start_dir = current if current and Path(current).exists() else str(Path.home())
            folder = QFileDialog.getExistingDirectory(
                self,
                "仕入処理用のデフォルトフォルダを選択",
                start_dir
            )
            if folder:
                s.setValue("inventory/default_base_folder", folder)
                if hasattr(self, "default_base_folder_edit"):
                    self.default_base_folder_edit.setText(folder)
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"デフォルトフォルダの設定に失敗しました:\n{str(e)}")

    def load_listing_settings(self):
        try:
            s = self._get_qsettings()
            include_title = s.value("listing/include_title", True, type=bool)
            enable_takane = s.value("listing/enable_takane", False, type=bool)
            takane_pct = s.value("listing/takane_pct", 5, type=int)
            self.chk_include_title.setChecked(bool(include_title))
            self.chk_enable_takane.setChecked(bool(enable_takane))
            # 自己発送末尾M設定（デフォルトはFalse）
            append_m = s.value("listing/append_m_for_self_ship", False, type=bool)
            self.chk_append_m_for_self_ship.setChecked(bool(append_m))
            try:
                self.spin_takane_pct.setValue(int(takane_pct))
            except Exception:
                pass
        except Exception as e:
            print(f"出品設定ロード失敗: {e}")

    def save_listing_settings(self):
        try:
            s = self._get_qsettings()
            s.setValue("listing/include_title", self.chk_include_title.isChecked())
            s.setValue("listing/enable_takane", self.chk_enable_takane.isChecked())
            s.setValue("listing/append_m_for_self_ship", self.chk_append_m_for_self_ship.isChecked())
            s.setValue("listing/takane_pct", int(self.spin_takane_pct.value()))
        except Exception as e:
            print(f"出品設定セーブ失敗: {e}")

    def _auto_match_sku_from_product_db(self):
        """
        商品DBから仕入れ日とASINでマッチングしてSKUを自動設定する
        
        取り込んだデータ一覧のSKUが「未実装」の行について、
        商品DBタブの仕入DBに仕入れ日・ASINを確認してマッチする物はSKUを取得して設定する
        """
        if is_recording_mode():
            return
        if self.inventory_data is None or len(self.inventory_data) == 0:
            return
        
        matched_count = 0
        try:
            # 商品DBタブの仕入DBから最新スナップショットを取得
            purchase_records = []
            try:
                snapshots = self.product_purchase_db.list_snapshots()
                if snapshots:
                    latest_snapshot = self.product_purchase_db.get_snapshot(snapshots[0]["id"])
                    if latest_snapshot and latest_snapshot.get("data"):
                        purchase_records = latest_snapshot["data"]
            except Exception:
                pass
            
            # SKUが「未実装」の行をチェック
            for idx, row in self.inventory_data.iterrows():
                sku = str(row.get('SKU', '')).strip()
                # NaNや空文字列も「未実装」として扱う
                if pd.isna(row.get('SKU')) or sku == '' or sku == 'nan' or sku == 'None':
                    sku = '未実装'
                
                if sku != '未実装':
                    continue
                
                # 仕入れ日とASINを取得
                purchase_date = str(row.get('仕入れ日', '')).strip()
                asin = str(row.get('ASIN', '')).strip()
                
                # 仕入れ日とASINが両方ある場合のみ検索
                if not purchase_date or not asin or purchase_date == 'nan' or asin == 'nan':
                    continue
                
                matched_sku = None
                
                # 1. 商品DBタブの仕入DB（最新スナップショット）から検索
                # 同じ仕入時間・同じASINのレコードからSKUを取得（重複登録防止）
                if purchase_records:
                    normalized_target_datetime = self._normalize_datetime_for_match(purchase_date)
                    for purchase_record in purchase_records:
                        record_datetime = str(purchase_record.get('仕入れ日', '') or purchase_record.get('purchase_date', '')).strip()
                        record_asin = str(purchase_record.get('ASIN', '') or purchase_record.get('asin', '')).strip()
                        record_sku = str(purchase_record.get('SKU', '') or purchase_record.get('sku', '')).strip()
                        
                        normalized_record_datetime = self._normalize_datetime_for_match(record_datetime)
                        
                        # 仕入時間（日付+時刻）+ ASINで比較
                        if normalized_record_datetime == normalized_target_datetime:
                            if record_asin.upper() == asin.upper() and record_sku and record_sku != '未実装':
                                matched_sku = record_sku
                                break
                
                # 2. 商品DB（productsテーブル）から検索（フォールバック）
                if not matched_sku:
                    product = self.product_db.find_by_date_and_asin(purchase_date, asin)
                    if product and product.get('sku'):
                        matched_sku = product['sku']
                
                # SKUを設定
                if matched_sku:
                    self.inventory_data.at[idx, 'SKU'] = matched_sku
                    matched_count += 1
            
            # マッチした場合はfiltered_dataも更新してテーブルを再描画
            if matched_count > 0:
                self.filtered_data = self.inventory_data.copy()
                self.update_table()
        except Exception:
            pass

    def lookup_existing_sku_for_date_asin(self, purchase_date: str, asin: str) -> Optional[str]:
        """
        商品DB（仕入スナップショット・products）から、同一仕入日時・ASINのSKUを1件返す。
        単品仕入ダイアログのSKU生成で、テーブルに載せる前の重複防止に使用。
        """
        if is_recording_mode():
            return None
        purchase_date = (purchase_date or "").strip()
        asin = (asin or "").strip()
        if not purchase_date or not asin:
            return None

        purchase_records: List[Dict[str, Any]] = []
        try:
            snapshots = self.product_purchase_db.list_snapshots()
            if snapshots:
                latest_snapshot = self.product_purchase_db.get_snapshot(snapshots[0]["id"])
                if latest_snapshot and latest_snapshot.get("data"):
                    purchase_records = latest_snapshot["data"]
        except Exception:
            pass

        if purchase_records:
            normalized_target_datetime = self._normalize_datetime_for_match(purchase_date)
            for purchase_record in purchase_records:
                record_datetime = str(
                    purchase_record.get("仕入れ日", "") or purchase_record.get("purchase_date", "")
                ).strip()
                record_asin = str(purchase_record.get("ASIN", "") or purchase_record.get("asin", "")).strip()
                record_sku = str(purchase_record.get("SKU", "") or purchase_record.get("sku", "")).strip()
                normalized_record_datetime = self._normalize_datetime_for_match(record_datetime)
                if normalized_record_datetime == normalized_target_datetime:
                    if record_asin.upper() == asin.upper() and record_sku and record_sku != "未実装":
                        return record_sku

        try:
            product = self.product_db.find_by_date_and_asin(purchase_date, asin)
            if product and product.get("sku"):
                s = str(product["sku"]).strip()
                if s and s != "未実装":
                    return s
        except Exception:
            pass
        return None

    def _normalize_date_for_match(self, date_str: str) -> str:
        """
        日付文字列を正規化して比較用の形式に変換
        
        例:
        - "2025/11/8 10:22" -> "2025-11-08"
        - "2025-11-08" -> "2025-11-08"
        - "2025/11/08" -> "2025-11-08"
        """
        if not date_str or date_str == 'nan':
            return ''
        
        date_str = str(date_str).strip()
        
        # 時刻部分を削除
        if ' ' in date_str:
            date_str = date_str.split(' ')[0]
        
        # スラッシュをハイフンに変換
        date_str = date_str.replace('/', '-')
        
        # 日付部分を抽出（yyyy-MM-dd形式に統一）
        parts = date_str.split('-')
        if len(parts) >= 3:
            year = parts[0].zfill(4)
            month = parts[1].zfill(2)
            day = parts[2].zfill(2)
            return f"{year}-{month}-{day}"
        
        return date_str

    def _normalize_datetime_for_match(self, date_str: str) -> str:
        """
        仕入れ日文字列を正規化（日付+時刻を含む場合も含める）
        同じ仕入時間・同じASINの判定に使用する。
        
        例:
        - "2025/11/8 10:22" -> "2025-11-08 10:22"
        - "2025-11-08 10:22:00" -> "2025-11-08 10:22"
        - "2025/11/8" -> "2025-11-08"
        """
        if not date_str or str(date_str).strip() == '' or str(date_str) == 'nan':
            return ''
        
        s = str(date_str).strip()
        # スラッシュをハイフンに変換
        s = s.replace('/', '-').replace('.', '-')
        
        date_part = s
        time_part = ''
        if ' ' in s:
            parts = s.split(' ', 1)
            date_part = parts[0]
            time_part = (parts[1] or '').strip()
            # 時刻を HH:MM に正規化（秒を削除）
            if time_part and ':' in time_part:
                t_parts = time_part.split(':')
                if len(t_parts) >= 2:
                    try:
                        h, m = int(t_parts[0]), int(t_parts[1])
                        time_part = f"{h:02d}:{m:02d}"
                    except (ValueError, IndexError):
                        time_part = ''
        
        # 日付部分を正規化
        d_parts = date_part.split('-')
        if len(d_parts) >= 3:
            try:
                y, m, d = int(d_parts[0]), int(d_parts[1]), int(d_parts[2])
                date_part = f"{y:04d}-{m:02d}-{d:02d}"
            except (ValueError, IndexError):
                pass
        
        if time_part:
            return f"{date_part} {time_part}"
        return date_part

    def _get_datetime_asin_key(self, record: Dict[str, Any]) -> Optional[str]:
        """
        仕入時間+ASINによる一意キーを生成する。
        同じ仕入時間・同じASIN = 同一レコードとみなす。
        """
        purchase_datetime = self._normalize_datetime_for_match(
            str(record.get("仕入れ日") or record.get("purchase_date") or "").strip()
        )
        asin = str(record.get("ASIN") or record.get("asin") or "").strip()
        if not purchase_datetime or not asin:
            return None
        return f"DT_ASIN:{purchase_datetime}|{asin.upper()}"

    def _is_excluded_for_sku(self, row: dict) -> bool:
        """
        SKU生成時の除外条件
        
        - コメントに『除外』が含まれる行は除外
        - 発送方法が空欄の行は除外
        - FBA 以外（自己発送など）は SKU 生成対象に含める
        """
        try:
            comment = str(row.get('コメント', '') or '')
            if '除外' in comment:
                return True
            ship = str(row.get('発送方法', '') or '').strip()
            # 発送方法が空欄の行は除外
            if ship == '':
                return True
            return False
        except Exception:
            return True

    def clear_sku(self):
        """SKU列だけをクリア（『未実装』に戻す）"""
        # データがない場合は何もしない
        if self.filtered_data is None or "SKU" not in getattr(self.filtered_data, "columns", []):
            QMessageBox.information(self, "SKUクリア", "SKU列を持つ仕入データがありません。")
            return

        reply = QMessageBox.question(
            self,
            "確認",
            "表示中の仕入データのSKUをすべて『未実装』に戻しますか？\n"
            "（仕入データ自体は残ります）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            # DataFrame上のSKU列を『未実装』に統一
            if self.inventory_data is not None and "SKU" in self.inventory_data.columns:
                self.inventory_data["SKU"] = "未実装"
            if self.filtered_data is not None and "SKU" in self.filtered_data.columns:
                self.filtered_data["SKU"] = "未実装"

            # テーブルを再描画（SKUの「未実装」表示ロジックもここで反映される）
            self.update_table()

            QMessageBox.information(self, "SKUクリア", "SKUをすべて『未実装』に戻しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"SKUクリア中にエラーが発生しました:\n{e}")

    def generate_sku(self):
        """SKU生成（店舗マスタ・電脳店舗・フリマコード連携）"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
            
        try:
            # 仕入DBに同じ仕入時間・同じASINがある場合はそこからSKUを入力（重複登録防止）
            self._auto_match_sku_from_product_db()

            # 仕入先の未登録店舗を店舗マスタへ反映（警告防止・Google Maps 情報付き）
            self._auto_register_stores_from_inventory(show_message=False)
            
            # データを辞書形式に変換（除外商品を除く）
            all_list = self.filtered_data.to_dict('records')
            # SKU生成専用の除外条件（自己発送も含める）
            data_list = [r for r in all_list if not self._is_excluded_for_sku(r)]
            excluded_count = len(all_list) - len(data_list)
            
            # 各商品データに店舗情報を追加
            enriched_data = []
            store_not_found_warnings = []
            
            for item in data_list:
                enriched_item = item.copy()
                
                # 「仕入先」列から仕入れ先コードを取得
                supplier_code = item.get('仕入先', '').strip()
                
                if supplier_code:
                    # 実店舗マスタ → 電脳店舗マスタの順で解決
                    resolved = self.store_db.resolve_supplier_for_sku(supplier_code)
                    if resolved:
                        enriched_item['supplier_code'] = resolved['supplier_code']
                        enriched_item['store_name'] = resolved.get('store_name', '')
                        enriched_item['store_id'] = resolved.get('store_id')
                    else:
                        store_not_found_warnings.append(supplier_code)
                        enriched_item['supplier_code'] = supplier_code
                        enriched_item['store_name'] = ''
                        enriched_item['store_id'] = None
                else:
                    # 仕入先コードが空の場合は警告を記録
                    enriched_item['supplier_code'] = ''
                    enriched_item['store_name'] = ''
                    enriched_item['store_id'] = None
                
                enriched_data.append(enriched_item)
            
            # 警告メッセージの表示（店舗が見つからない場合）
            unique_warnings = []
            if store_not_found_warnings:
                unique_warnings = list(set(store_not_found_warnings))
                warning_msg = (
                    "以下の仕入先コードに対応する店舗が見つかりませんでした:\n"
                    f"{', '.join(unique_warnings[:5])}"
                )
                if len(unique_warnings) > 5:
                    warning_msg += f"\n他 {len(unique_warnings) - 5}件..."
                warning_msg += (
                    "\n\n店舗マスタに未登録のコードです。"
                    "設定 → 店舗マスタで登録するか、ルート照合で使った店舗コードか確認してください。"
                )
                QMessageBox.warning(self, "店舗情報警告", warning_msg)
            
            # SKUテンプレート用の日付（任意指定）。未指定ならNoneのまま＝当日扱い。
            sku_date_str = None
            if hasattr(self, "sku_date_edit") and self.sku_date_edit is not None:
                d = self.sku_date_edit.date()
                if d.isValid():
                    sku_date_str = d.toString("yyyyMMdd")

            # APIクライアントでSKU生成（任意のSKU日付を渡す）
            result = self.api_client.inventory_generate_sku(enriched_data, sku_date=sku_date_str)
            
            if result['status'] == 'success':
                # 生成されたSKUをテーブルに反映
                self.update_table_with_sku(result['results'])
                
                # 統計情報の更新
                self.update_stats()
                
                generated_count = result['generated_count']
                success_msg = f"SKU生成が完了しました\n生成数: {generated_count}件"
                if unique_warnings:
                    success_msg += f"\n（店舗未登録: {len(unique_warnings)}件）"
                
                QMessageBox.information(
                    self, 
                    "SKU生成完了", 
                    success_msg
                )
                
                # シグナル発火
                self.sku_generated.emit(result['generated_count'])

                # SKU日付は毎回リセットして当日に戻す
                if hasattr(self, "sku_date_edit") and self.sku_date_edit is not None:
                    self.sku_date_edit.setDate(QDate.currentDate())
            else:
                QMessageBox.warning(self, "SKU生成失敗", "SKU生成に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"SKU生成中にエラーが発生しました:\n{str(e)}")

    def update_table_with_sku(self, sku_results):
        """SKU生成結果をテーブルに反映"""
        try:
            # 元データにSKU情報を追加
            used_rows = set()
            for idx_result, result in enumerate(sku_results):
                if result['status'] == 'success':
                    # 元データの該当行を特定（ASINや商品名でマッチング）
                    original_data = result['original_data']
                    generated_sku = result['generated_sku']
                    q_tag = result['q_tag']
                    
                    # 元データの該当行を更新
                    def _norm(s: str) -> str:
                        return str(s or '').strip().replace('\u3000', ' ')

                    asin = _norm(original_data.get('ASIN') or original_data.get('asin'))
                    jan = _norm(original_data.get('JAN') or original_data.get('jan'))
                    name = _norm(original_data.get('商品名') or original_data.get('product_name'))

                    matched_index = None
                    # 1) ASIN一致
                    if asin:
                        for i, row in self.inventory_data.iterrows():
                            if i in used_rows:
                                continue
                            if _norm(row.get('ASIN')) == asin:
                                matched_index = i; break
                    # 2) JAN一致
                    if matched_index is None and jan:
                        for i, row in self.inventory_data.iterrows():
                            if i in used_rows:
                                continue
                            if _norm(row.get('JAN')) == jan:
                                matched_index = i; break
                    # 3) 商品名（ゆるめ）
                    if matched_index is None and name:
                        for i, row in self.inventory_data.iterrows():
                            if i in used_rows:
                                continue
                            if _norm(row.get('商品名')).lower() == name.lower():
                                matched_index = i; break
                    # 4) 表示順で最初の未実装
                    if matched_index is None:
                        for i, row in self.inventory_data.iterrows():
                            if i in used_rows:
                                continue
                            if str(row.get('SKU', '')) in ('', '未実装'):
                                matched_index = i; break
                    # 5) 最後の保険: インデックス
                    if matched_index is None and idx_result < len(self.inventory_data):
                        matched_index = idx_result

                    if matched_index is not None:
                        # 必要であれば自己発送用に末尾Mを付与
                        if self.chk_append_m_for_self_ship.isChecked():
                            try:
                                ship_method = str(self.inventory_data.at[matched_index, '発送方法'] or '')
                            except Exception:
                                ship_method = ''
                            # 発送方法に「自己発送」が含まれる行だけ対象
                            if '自己発送' in ship_method:
                                if isinstance(generated_sku, str) and not generated_sku.endswith('M'):
                                    generated_sku = f"{generated_sku}M"

                        self.inventory_data.at[matched_index, 'SKU'] = generated_sku
                        used_rows.add(matched_index)
            
            # フィルタデータも更新
            self.filtered_data = self.inventory_data.copy()
            
            # テーブルの再描画
            self.update_table()
            
        except Exception as e:
            print(f"テーブル更新エラー: {e}")

    def _extract_missing_info(self, comment: str) -> Optional[str]:
        """
        コメントから欠品情報を抽出・変換
        
        【付属品】以降の文言を抽出し、欠品キーワード辞書にマッチするものを変換後の文章に置き換え
        【付属品】がない場合はコメント全体をチェック
        複数の欠品情報がある場合はカンマ区切りでキーワード順に並べる
        
        Returns:
            - 辞書にマッチ（複数可）: カンマ区切りの変換後の文章
            - 辞書にないが「欠品」キーワードあり: 空文字列（見出しのみ用）
            - どちらでもない: None
        """
        if not comment or not comment.strip():
            return None
        
        comment = comment.strip()
        
        try:
            # 【付属品】以降の文言を抽出（なければコメント全体を使用）
            if "【付属品】" in comment:
                # 【付属品】以降の部分を取得
                after_attachments = comment.split("【付属品】", 1)[1].strip()
                if not after_attachments:
                    return None
            else:
                # 【付属品】がない場合はコメント全体を使用
                after_attachments = comment
            
            # 欠品キーワード辞書を読み込み
            missing_keywords = self.condition_template_db.load_missing_keywords()
            keywords_dict = missing_keywords.get('keywords', {})
            
            # マッチした変換後の文章をリストに格納（キーワード順）
            converted_list = []
            matched_keywords = []
            
            # 辞書のキーワード順にチェック（辞書の順序を保持）
            # コメント全体に対してチェック（部分一致でマッチ）
            for keyword, converted_text in keywords_dict.items():
                if keyword in after_attachments and keyword not in matched_keywords:
                    converted_list.append(converted_text)
                    matched_keywords.append(keyword)
            
            # マッチした変換後の文章がある場合
            if converted_list:
                # カンマ区切りで結合
                return ",".join(converted_list)
            
            # 辞書にないが「欠品」キーワードが含まれているかチェック
            detection_keywords = missing_keywords.get('detection_keywords', ['欠品', 'なし', '無し', '欠'])
            for keyword in detection_keywords:
                if keyword in after_attachments:
                    # 見出しのみ（内容は空）
                    return ""
            
            # どちらでもない
            return None
        except Exception:
            # エラー時はNoneを返す
            return None

    def _auto_fill_condition_notes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        コンディション説明を自動入力（コメント欄に欠品情報がある場合）
        
        Args:
            df: 仕入データのDataFrame
        
        Returns:
            コンディション説明が自動入力されたDataFrame
        """
        if df is None or len(df) == 0:
            return df
        
        # コンディション説明カラムが存在しない場合は作成
        if "コンディション説明" not in df.columns:
            df["コンディション説明"] = ""
        
        # 各行に対してコンディション説明を自動生成
        for idx in df.index:
            # 既にコンディション説明が入力されている場合はスキップ
            existing_note = df.at[idx, "コンディション説明"]
            if existing_note and str(existing_note).strip():
                continue
            
            # コンディションとコメントを取得
            condition_text = df.at[idx, "コンディション"] if "コンディション" in df.columns else "新品"
            comment = df.at[idx, "コメント"] if "コメント" in df.columns else ""
            
            # コンディションが空の場合はスキップ
            if not condition_text or pd.isna(condition_text) or str(condition_text).strip() == "":
                continue
            
            # コメントが空の場合はスキップ
            if not comment or pd.isna(comment) or str(comment).strip() == "":
                continue
            
            # 欠品情報が含まれているかチェック（【付属品】または欠品キーワード）
            comment_str = str(comment).strip()
            has_missing_info = False
            
            # 【付属品】が含まれているかチェック
            if "【付属品】" in comment_str:
                has_missing_info = True
            else:
                # 【付属品】がなくても、欠品キーワード辞書にマッチするかチェック
                try:
                    missing_keywords = self.condition_template_db.load_missing_keywords()
                    keywords_dict = missing_keywords.get('keywords', {})
                    detection_keywords = missing_keywords.get('detection_keywords', ['欠品', 'なし', '無し', '欠'])
                    
                    # 辞書のキーワードをチェック
                    for keyword in keywords_dict.keys():
                        if keyword in comment_str:
                            has_missing_info = True
                            break
                    
                    # 検出キーワードをチェック
                    if not has_missing_info:
                        for keyword in detection_keywords:
                            if keyword in comment_str:
                                has_missing_info = True
                                break
                except Exception:
                    pass
            
            # 欠品情報がない場合はスキップ
            if not has_missing_info:
                continue
            
            try:
                # コンディションキーを取得
                condition_key = self._get_condition_key(str(condition_text))
                
                # 欠品情報を抽出して確認
                missing_info = self._extract_missing_info(str(comment))
                
                # 欠品情報がある場合のみコンディション説明を生成
                if missing_info is not None:
                    # コンディション説明を生成（アプリ内表示用: 改行あり）
                    condition_note = self._build_condition_note(condition_key, str(comment), for_csv=False)
                    
                    # 生成されたコンディション説明を設定
                    if condition_note:
                        df.at[idx, "コンディション説明"] = condition_note
            except Exception as e:
                # エラー時はスキップ（ログ出力はしない）
                continue
        
        return df

    def _get_condition_key(self, condition_text: str) -> str:
        """
        コンディション文字列からキーを取得
        
        Args:
            condition_text: コンディション文字列（「新品」「ほぼ新品」「中古(ほぼ新品)」など）
        
        Returns:
            コンディションキー（'new', 'like_new', etc.）
        """
        condition_map = {
            '新品': 'new',
            'ほぼ新品': 'like_new',
            '中古(ほぼ新品)': 'like_new',
            '非常に良い': 'very_good',
            '中古(非常に良い)': 'very_good',
            '良い': 'good',
            '中古(良い)': 'good',
            '可': 'acceptable',
            '中古(可)': 'acceptable',
        }
        return condition_map.get(condition_text, 'new')  # デフォルトは新品

    def _build_condition_note(self, condition_key: str, comment: str, for_csv: bool = False) -> str:
        """
        conditionNoteを生成（【付属品】の後ろを欠品情報に置き換え）
        
        Args:
            condition_key: コンディションキー（'new', 'like_new', etc.）
            comment: 仕入データのコメント欄
            for_csv: CSV出力用の場合True（改行を削除）
        
        Returns:
            生成されたconditionNote（改行なし、1行）
        """
        try:
            import re
            
            # テンプレート説明文を取得（DBでは改行を "\\n" で保存しているので実際の改行に変換）
            template_text = self.condition_template_db.get_condition_description_text(condition_key)
            if not template_text:
                template_text = ""
            template_text = _normalize_condition_note_newlines(template_text)
            
            # 欠品情報を抽出
            missing_info = self._extract_missing_info(comment)
            
            # 欠品情報がある場合のみ処理
            if missing_info is not None and missing_info:
                # 【付属品】の行を見つけて、その後の部分を欠品情報に置き換え
                # パターン: 【付属品】で始まる行の【付属品】より後ろを置き換え
                lines = template_text.split('\n')
                replaced = False
                
                for i, line in enumerate(lines):
                    if line.strip().startswith('【付属品】'):
                        # 【付属品】の後ろの部分を欠品情報に置き換え
                        # 「【付属品】」の部分は残して、その後の部分を削除して欠品情報を追加
                        lines[i] = f"【付属品】{missing_info}"
                        replaced = True
                        break
                
                # 【付属品】の行が見つからない場合は、先頭に追加
                if not replaced:
                    # テンプレートの先頭に【付属品】行を追加
                    if template_text.strip():
                        template_text = f"【付属品】{missing_info}\n{template_text}"
                    else:
                        template_text = f"【付属品】{missing_info}"
                else:
                    # 置き換えが成功したので、linesを結合してtemplate_textを更新
                    template_text = '\n'.join(lines)
            else:
                # 欠品情報がない場合はテンプレートをそのまま使用
                pass
            
            # 改行を削除して1行にする
            result = template_text.strip()
            # 改行を空白に置換（連続する改行も1つの空白に）
            result = re.sub(r'\n+', ' ', result)
            # 連続する空白を1つに
            result = re.sub(r' +', ' ', result)
            result = result.strip()
            
            return result
        except Exception as e:
            # エラー時はコメントをそのまま返す（改行削除）
            result = comment if comment else ""
            import re
            result = re.sub(r'\n+', ' ', result)
            result = re.sub(r' +', ' ', result).strip()
            return result

    def _normalize_asin_jan(self, value):
        """
        ASIN/JANコードの科学的記数法を正規化
        
        ASIN: 10桁の数字または10文字の英数字（例: 4048965379, B0085PIHM0）
        JAN: 13桁の数字（例: 4901234567890）
        
        Args:
            value: ASINまたはJANの値（文字列、数値、科学的記数法など）
            
        Returns:
            正規化されたASIN/JANコード（文字列）
        """
        if not value or pd.isna(value):
            return ''
        
        # 文字列に変換
        str_value = str(value).strip()
        if not str_value:
            return ''
        
        # 科学的記数法のパターンをチェック（例: 4.05E+09, 4.8E+09）
        import re
        scientific_pattern = r'^(\d+\.?\d*)[eE][\+\-]?(\d+)$'
        match = re.match(scientific_pattern, str_value)
        
        if match:
            try:
                # 科学的記数法を数値に変換
                num_value = float(str_value)
                # 整数に変換
                int_value = int(num_value)
                # 文字列に変換（先頭0は保持）
                normalized = str(int_value)
                
                # 桁数でASINかJANかを判定
                # ASINは10桁、JANは13桁
                if len(normalized) == 10:
                    # 10桁の場合はASINとして扱う（そのまま返す）
                    return normalized
                elif len(normalized) == 13:
                    # 13桁の場合はJANとして扱う（そのまま返す）
                    return normalized
                elif len(normalized) < 10:
                    # 10桁未満の場合は、10桁のASINとして先頭0埋め
                    return normalized.zfill(10)
                elif len(normalized) < 13:
                    # 10桁以上13桁未満の場合は、13桁のJANとして先頭0埋め
                    return normalized.zfill(13)
                else:
                    # 13桁を超える場合はそのまま返す
                    return normalized
            except (ValueError, OverflowError):
                # 変換に失敗した場合は元の値を返す
                return str_value
        
        # 科学的記数法でない場合は、そのまま返す（ただし文字列として）
        return str_value

    def export_listing_csv(self):
        """出品CSV生成（conditionNote統合版）"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "データがありません")
            return
            
        try:
            # データを辞書形式に変換
            data_list = self.filtered_data.to_dict('records')
            # 除外商品を除く
            included_list = [r for r in data_list if not self._is_excluded_row(r)]
            
            # ステータスで除外（ready以外のステータスを除外）
            status_excluded_count = 0
            status_included_list = []
            for r in included_list:
                status = str(r.get('ステータス') or r.get('status') or 'ready').lower()
                if status == 'ready':
                    status_included_list.append(r)
                else:
                    status_excluded_count += 1
            
            included_list = status_included_list
            excluded_count = len(data_list) - len(included_list)
            
            # 列名をマッピング（日本語→英語）
            mapped_data = []
            for row in included_list:
                # takane 設定が有効なら価格の〇%上で算出
                takane_val = ''
                try:
                    if self.chk_enable_takane.isChecked():
                        pct = int(self.spin_takane_pct.value())
                        base_price = row.get('販売予定価格', 0) or 0
                        # 数値化
                        if isinstance(base_price, str):
                            base_price = float(base_price.replace(',', '')) if base_price else 0
                        takane_val = int(round(float(base_price) * (1.0 + float(pct) / 100.0)))
                except Exception:
                    takane_val = ''

                # タイトル出力の有無
                product_name_val = row.get('商品名', '')
                try:
                    if hasattr(self, 'chk_include_title') and not self.chk_include_title.isChecked():
                        product_name_val = ''
                except Exception:
                    pass

                # コンディション文字列を取得（そのままcondition列に出力）
                condition_text = row.get('コンディション', '新品')

                # 仕入データ一覧の「コンディション説明」カラムの内容をそのまま使用
                # ※ユーザーが画面で確認している文章をそのままCSVに出したい要件
                import re
                existing_condition_note = row.get('コンディション説明', '')
                condition_note = str(existing_condition_note or "").strip()
                # 改行はCSV上では1行にしたいので空白に変換
                if condition_note:
                    condition_note = re.sub(r'\r\n|\r|\n', ' ', condition_note)
                    # 連続する空白を1つに
                    condition_note = re.sub(r' +', ' ', condition_note).strip()
                
                # ASIN/JANコードの科学的記数法を正規化
                asin_value = self._normalize_asin_jan(row.get('ASIN', ''))
                jan_value = self._normalize_asin_jan(row.get('JAN', ''))
                
                mapped_row = {
                    'sku': row.get('SKU', ''),
                    'asin': asin_value,
                    'jan': jan_value,
                    'product_name': product_name_val,
                    'quantity': row.get('仕入れ個数', 1),
                    'plannedPrice': row.get('販売予定価格', 0),
                    'purchasePrice': row.get('仕入れ価格', 0),
                    'breakEven': row.get('損益分岐点', 0),
                    'expectedMargin': row.get('想定利益率', 0.0),
                    'expectedROI': row.get('想定ROI', 0.0),
                    'takane': takane_val,
                    'condition': condition_text,
                    'conditionNote': condition_note if condition_note else '',  # 空文字列を明示的に設定
                    'priceTrace': row.get('priceTrace', 0)
                }
                mapped_data.append(mapped_row)
            
            # APIクライアントで出品CSV生成
            result = self.api_client.inventory_export_listing(mapped_data)
            
            if result['status'] == 'success':
                # 既定の保存ファイル名（仕入れ日から YYYYMMDD_出品用CSV.csv を生成）
                default_name = "listing_export.csv"
                try:
                    if len(self.filtered_data) > 0:
                        first_date = str(self.filtered_data.iloc[0].get('仕入れ日', '')).strip()
                        from datetime import datetime
                        for fmt in ['%Y/%m/%d', '%Y-%m-%d', '%Y.%m.%d', '%Y%m%d']:
                            try:
                                dt = datetime.strptime(first_date, fmt)
                                default_name = f"{dt.strftime('%Y%m%d')}_出品用CSV.csv"
                                break
                            except ValueError:
                                continue
                except Exception:
                    pass

                # 保存先フォルダを取得（CSV取込時に選択したフォルダ、なければデフォルト）
                from pathlib import Path
                from utils.file_naming import resolve_unique_path
                
                default_dir = None
                try:
                    s = self._get_qsettings()
                    saved_folder = s.value("inventory/last_csv_folder", None, type=str)
                    if saved_folder and Path(saved_folder).exists():
                        default_dir = saved_folder
                except Exception:
                    pass
                
                # デフォルトフォルダが設定されていない場合は、仕入処理用の基準フォルダを使用
                if default_dir is None:
                    default_dir = self._get_default_batch_root_dir()
                
                # ファイル保存ダイアログを表示
                default_path = str(Path(default_dir) / default_name)
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "出品CSVファイルを保存",
                    default_path,
                    "CSVファイル (*.csv)"
                )
                
                if file_path:
                    target = resolve_unique_path(Path(file_path))
                    csv_content = result['csv_content']
                    with open(str(target), 'wb') as f:
                        f.write(csv_content)
                    
                    # 選択したフォルダを保存（次回の初期フォルダとして使用）
                    try:
                        selected_folder = str(Path(file_path).parent)
                        s = self._get_qsettings()
                        s.setValue("inventory/last_csv_folder", selected_folder)
                    except Exception:
                        pass
                    
                    self._set_listing_csv_drag_file(str(target))
                    auto_hint = "「ブラウザで開く」後、CSVアイコンをドラッグしてプライスターへ送ってください。"
                    QMessageBox.information(
                        self,
                        "出品CSV生成完了",
                        f"出品CSV生成が完了しました\n出力数: {result['exported_count']}件 (除外 {excluded_count}件)\n"
                        f"保存先: {str(target)}\n\n"
                        f"{auto_hint}",
                    )

                    # ルートタブ側の「出品」チェックをONにする（対応するルートサマリーが判定できた場合）
                    try:
                        base_folder = selected_folder if 'selected_folder' in locals() else str(target.parent)
                        mark_route_flags_from_folder(base_folder, listing_completed=True)
                    except Exception as e:
                        # ルート判定に失敗しても致命的ではないのでログのみ
                        print(f"出品フラグ更新エラー: {e}")
            else:
                QMessageBox.warning(self, "出品CSV生成失敗", "出品CSV生成に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"出品CSV生成中にエラーが発生しました:\n{str(e)}")

    def setup_settings_panel(self):
        self.settings_group = QGroupBox("SKUテンプレート設定")
        self.settings_group.setCheckable(False)
        self.settings_group.setVisible(False)

        lay = QGridLayout(self.settings_group)
        lay.addWidget(QLabel("テンプレート:"), 0, 0)
        self.tpl_edit = QLineEdit()
        self.tpl_edit.setPlaceholderText("{date:YYYYMMDD}-{ASIN|JAN}-{supplier}-{seq:3}-{condNum}")
        self.tpl_edit.setFixedHeight(30)
        lay.addWidget(self.tpl_edit, 0, 1, 1, 3)

        # SKU日付（任意指定。未指定時は当日を使用）
        lay.addWidget(QLabel("SKU日付(任意):"), 1, 0)
        self.sku_date_edit = QDateEdit()
        self.sku_date_edit.setCalendarPopup(True)
        self.sku_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.sku_date_edit.setDate(QDate.currentDate())
        self.sku_date_edit.setFixedHeight(30)
        lay.addWidget(self.sku_date_edit, 1, 1)

        lay.addWidget(QLabel("連番開始:"), 2, 0)
        self.seq_start_spin = QSpinBox()
        self.seq_start_spin.setRange(1, 9999)
        self.seq_start_spin.setValue(1)
        self.seq_start_spin.setFixedHeight(30)
        lay.addWidget(self.seq_start_spin, 2, 1)

        lay.addWidget(QLabel("スコープ:"), 2, 2)
        self.seq_scope_combo = QComboBox()
        self.seq_scope_combo.addItems(["day"])  # まずはdayのみ
        self.seq_scope_combo.setFixedHeight(30)
        lay.addWidget(self.seq_scope_combo, 2, 3)

        self.btn_load_settings = QPushButton("読込")
        self.btn_load_settings.setFixedHeight(30)
        self.btn_load_settings.clicked.connect(self.load_sku_settings)
        lay.addWidget(self.btn_load_settings, 3, 2)

        self.btn_save_settings = QPushButton("保存")
        self.btn_save_settings.setFixedHeight(30)
        self.btn_save_settings.clicked.connect(self.save_sku_settings)
        lay.addWidget(self.btn_save_settings, 3, 3)

        # 8スロットのプルダウン式ビルダー（PRO版: 3-6-9 含む）
        self._sku_token_choices = [
            "(空)",
            "日付",
            "asin",
            "商品コンディション番号",
            "商品コンディション記号",
            "発送方法",
            "仕入先コード",
            "仕入れ価格",
            "連番",
            "3-6-9",  # PRO版: オフ時はグレーアウトで選択不可
            "任意の文字列",
        ]
        self._sku_token_369_index = self._sku_token_choices.index("3-6-9")
        self.slot_types = []
        self.slot_values = []
        self.slot_seq_widths = []
        for i in range(8):
            row = 4 + i
            lay.addWidget(QLabel(f"{i+1}"), row, 0)
            cb = QComboBox()
            self._set_sku_token_choices_to_combo(cb)
            cb.setFixedHeight(30)
            self.slot_types.append(cb)
            lay.addWidget(cb, row, 1)

            val = QLineEdit()
            val.setPlaceholderText("(任意文字列 / 連番桁数) ※選択により使用")
            val.setFixedHeight(30)
            self.slot_values.append(val)
            lay.addWidget(val, row, 2)

            seqw = QSpinBox()
            seqw.setRange(1, 8)
            seqw.setValue(3)
            seqw.setFixedHeight(30)
            self.slot_seq_widths.append(seqw)
            lay.addWidget(seqw, row, 3)

        self.btn_build_tpl = QPushButton("テンプレ生成")
        self.btn_build_tpl.setFixedHeight(30)
        self.btn_build_tpl.clicked.connect(self.build_template_from_slots)
        lay.addWidget(self.btn_build_tpl, 11, 3)

        # 画面に追加（検索フィルタの直下）
        self.layout().addWidget(self.settings_group)

    def _set_sku_token_choices_to_combo(self, combo: QComboBox):
        """token_choices をコンボにセットし、PRO版オフ時は「3-6-9」を無効（グレー・選択不可）にする"""
        from utils.settings_helper import is_pro_enabled
        model = QStandardItemModel()
        for text in self._sku_token_choices:
            item = QStandardItem(text)
            if text == "3-6-9" and not is_pro_enabled():
                item.setEnabled(False)
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)  # コンボで選択不可に
            model.appendRow(item)
        combo.setModel(model)

    def _apply_pro_to_369_in_slot_combos(self):
        """PRO版のON/OFFに応じて、各スロットコンボの「3-6-9」の有効/無効を更新する"""
        from utils.settings_helper import is_pro_enabled
        enabled = is_pro_enabled()
        for cb in self.slot_types:
            model = cb.model()
            if model and model.rowCount() > self._sku_token_369_index:
                item = model.item(self._sku_token_369_index)
                if item:
                    item.setEnabled(enabled)
                    if enabled:
                        item.setFlags(item.flags() | Qt.ItemIsEnabled)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    # 現在「3-6-9」選択中でPROがオフなら強制的に「(空)」へ
                    if not enabled and cb.currentIndex() == self._sku_token_369_index:
                        cb.setCurrentIndex(0)

    def toggle_settings_panel(self):
        self.settings_group.setVisible(not self.settings_group.isVisible())
        if self.settings_group.isVisible():
            self._apply_pro_to_369_in_slot_combos()
            self.load_sku_settings()

    def load_sku_settings(self):
        try:
            self._apply_pro_to_369_in_slot_combos()
            s = self.api_client.inventory_get_sku_template()
            self.tpl_edit.setText(s.get("skuTemplate", ""))
            self.seq_start_spin.setValue(int(s.get("seqStart", 1)))
            scope = s.get("seqScope", "day")
            idx = self.seq_scope_combo.findText(scope)
            if idx >= 0:
                self.seq_scope_combo.setCurrentIndex(idx)
            # SKU日付は毎回クリアして当日に戻す（設定としては保存しない）
            if hasattr(self, "sku_date_edit"):
                self.sku_date_edit.setDate(QDate.currentDate())
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "エラー", f"設定の読込に失敗しました:\n{e}")

    def save_sku_settings(self):
        try:
            # 現在のスロット構成からテンプレを再生成して反映
            self.build_template_from_slots()
            ok = self.api_client.inventory_update_sku_template({
                "skuTemplate": self.tpl_edit.text().strip(),
                "seqScope": self.seq_scope_combo.currentText(),
                "seqStart": int(self.seq_start_spin.value())
            })
            from PySide6.QtWidgets import QMessageBox
            if ok:
                QMessageBox.information(self, "保存", "SKUテンプレート設定を保存しました")
            else:
                QMessageBox.warning(self, "保存", "SKUテンプレート設定の保存に失敗しました")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "エラー", f"設定の保存に失敗しました:\n{e}")

    def build_template_from_slots(self):
        # スロットの選択からテンプレ文字列を生成
        parts = []
        for cb, val, seqw in zip(self.slot_types, self.slot_values, self.slot_seq_widths):
            t = cb.currentText()
            if t == "(空)":
                continue
            if t == "日付":
                parts.append("{date:YYYYMMDD}")
            elif t == "asin":
                parts.append("{asin}")
            elif t == "商品コンディション番号":
                parts.append("{condNum}")
            elif t == "商品コンディション記号":
                parts.append("{condCode}")
            elif t == "発送方法":
                parts.append("{ship}")
            elif t == "仕入先コード":
                parts.append("{supplier}")
            elif t == "仕入れ価格":
                # 仕入れ価格（purchase_price）をそのまま数値文字列として使用
                parts.append("{purchasePrice}")
            elif t == "連番":
                width = int(seqw.value()) if seqw else 3
                parts.append(f"{{seq:{width}}}")
            elif t == "3-6-9":
                # PRO版: 3-6-9ルール用プレースホルダー（PRO版オフ時は追加しない）
                from utils.settings_helper import is_pro_enabled
                if is_pro_enabled():
                    parts.append("{rule369}")
            elif t == "任意の文字列":
                text = val.text().strip()
                if text:
                    parts.append(f"{{custom:{text}}}")
        tpl = "-".join(parts) if parts else self.tpl_edit.text().strip()
        self.tpl_edit.setText(tpl)

