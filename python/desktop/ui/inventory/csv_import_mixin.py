#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在庫 CSV 取込 mixin。"""
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


class InventoryCsvImportMixin:
    def _get_last_csv_import_folder(self) -> str:
        """直近の CSV 取込で開いたフォルダ（存在する場合のみ）。"""
        from pathlib import Path
        try:
            last_folder = self._get_qsettings().value("inventory/last_csv_folder", "", type=str)
            if last_folder and Path(last_folder).exists():
                return str(last_folder)
        except Exception:
            pass
        return ""

    def _get_default_batch_root_dir(self) -> str:
        """
        仕入処理用のフォルダ選択で使用する基準フォルダを取得
        優先順位:
        1. inventory/default_base_folder（ユーザー指定のデフォルトフォルダ）
        2. inventory/last_csv_folder（最後に読み込んだCSVのフォルダ）
        3. 固定のフォールバックパス / ホームディレクトリ
        """
        from pathlib import Path
        try:
            s = self._get_qsettings()
            base = s.value("inventory/default_base_folder", "", type=str)
            if base and Path(base).exists():
                return base
            last_folder = s.value("inventory/last_csv_folder", "", type=str)
            if last_folder and Path(last_folder).exists():
                return last_folder
        except Exception as e:
            print(f"デフォルトフォルダ取得エラー: {e}")
        # 以前のハードコードされたフォルダをフォールバックとして残す
        fallback = r"D:\せどり総合\店舗せどり仕入リスト入れ"
        if Path(fallback).exists():
            return fallback
        return str(Path.home())

    def import_csv(self):
        """CSVファイルの取込"""
        default_dir = self._get_default_batch_root_dir()
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "CSVファイルを選択",
            default_dir,
            "CSVファイル (*.csv);;すべてのファイル (*)"
        )
        
        if file_path:
            self._import_csv_from_path(file_path)

    def _import_csv_from_path(self, file_path: str):
        """指定パスのCSVファイルを読み込んで仕入データに展開する共通処理"""
        try:
            # CSVファイルの読み込み（複数エンコーディング対応）
            df = self._read_csv_with_encoding_fallback(file_path)
            
            # 選択したフォルダを保存（次回の出品CSV生成時に使用）
            try:
                from pathlib import Path
                selected_folder = str(Path(file_path).parent)
                s = self._get_qsettings()
                s.setValue("inventory/last_csv_folder", selected_folder)
            except Exception:
                pass
            
            # 列マッピングと並び替え
            self.inventory_data = self._map_and_reorder_columns(df)
            # 開発タブの場合のみ、コメント列から 3-6-9 コードを自動判定して「3-6-9」列に反映
            # （ルールは services/sku_template.py の _get_rule369_code と同一）
            if self.dev_mode and self.inventory_data is not None and "3-6-9" in self.inventory_data.columns:
                try:
                    for idx, row in self.inventory_data.iterrows():
                        # 既に値が入っている場合はユーザー編集を優先してスキップ
                        current_val = str(self.inventory_data.at[idx, "3-6-9"]).strip()
                        if current_val not in ("", "nan", "None"):
                            continue
                        comment_val = row.get("コメント") or row.get("comment")
                        code = self._infer_rule369_from_comment(comment_val)
                        self.inventory_data.at[idx, "3-6-9"] = code
                except Exception as e:
                    # 自動判定全体の失敗も、CSV取込自体は継続
                    print(f"3-6-9 自動判定処理でエラー: {e}")

            self.filtered_data = self.inventory_data.copy()
            
            # SKU自動マッチング処理（商品DBから仕入れ日・ASINで検索）
            self._auto_match_sku_from_product_db()

            # 仕入先に未登録店舗があれば店舗マスタへ自動登録（Google Maps 情報付き）
            self._auto_register_stores_from_inventory()
            
            # テーブルの更新
            self.update_table()
            
            # ボタンの有効化
            self.export_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
            if hasattr(self, "clear_sku_btn"):
                self.clear_sku_btn.setEnabled(True)
            self.generate_sku_btn.setEnabled(True)
            self.export_listing_btn.setEnabled(True)
            self.antique_register_btn.setEnabled(True)
            
            # データ件数の更新
            self.update_data_count()
            
            QMessageBox.information(
                self, 
                "取込完了", 
                f"CSVファイルを読み込みました（{len(self.inventory_data)}行）"
            )
            
            # シグナル発火
            self.data_loaded.emit(len(self.inventory_data))
            
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"CSVファイルの読み込みに失敗しました:\n{str(e)}")

    def _read_csv_with_encoding_fallback(self, file_path):
        """複数エンコーディングでCSVファイルを読み込む"""
        encodings = ['utf-8', 'shift_jis', 'cp932', 'utf-8-sig', 'iso-2022-jp']
        
        for encoding in encodings:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                print(f"CSV読み込み成功: エンコーディング={encoding}, 行数={len(df)}")
                return df
            except UnicodeDecodeError:
                print(f"エンコーディング {encoding} で読み込み失敗、次のエンコーディングを試行")
                continue
            except Exception as e:
                print(f"エンコーディング {encoding} で予期しないエラー: {e}")
                continue
        
        # すべてのエンコーディングで失敗した場合
        raise Exception("すべてのエンコーディングでCSVファイルの読み込みに失敗しました")

    def _map_and_reorder_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """CSV列を指定順序にマッピング・並び替え"""
        # CSVファイルの列名と新しい列名のマッピング
        # 参考データ: StockList_20250927_2108_standard.csv
        column_mapping = {
            # 仕入れ日
            "仕入日": "仕入れ日",
            "仕入れ日": "仕入れ日",
            "日付": "仕入れ日",
            # コンディション
            "状態": "コンディション",
            "コンディション": "コンディション",
            "condition": "コンディション",
            # ASIN
            "ASIN": "ASIN",
            "asin": "ASIN",
            # JAN
            "JAN": "JAN",
            "jan": "JAN",
            "JANコード": "JAN",
            # 商品名
            "商品名": "商品名",
            "商品名": "商品名",
            "title": "商品名",
            "name": "商品名",
            # 仕入れ個数
            "仕入個数": "仕入れ個数",
            "仕入れ個数": "仕入れ個数",
            "数量": "仕入れ個数",
            "quantity": "仕入れ個数",
            # 仕入れ価格
            "仕入価格": "仕入れ価格",
            "仕入れ価格": "仕入れ価格",
            "原価": "仕入れ価格",
            "cost": "仕入れ価格",
            "purchasePrice": "仕入れ価格",
            # 販売予定価格
            "販売予定価格": "販売予定価格",
            "価格": "販売予定価格",
            "price": "販売予定価格",
            "plannedPrice": "販売予定価格",
            # 見込み利益
            "見込み利益": "見込み利益",
            "利益": "見込み利益",
            "profit": "見込み利益",
            "expectedProfit": "見込み利益",
            # 損益分岐点
            "損益分岐点": "損益分岐点",
            "akaji": "損益分岐点",
            "breakEven": "損益分岐点",
            # コメント
            "コメント": "コメント",
            "備考": "コメント",
            "comment": "コメント",
            "notes": "コメント",
            # 発送方法
            "発送方法": "発送方法",
            "配送方法": "発送方法",
            "shippingMethod": "発送方法",
            "shipping_method": "発送方法",
            "発送": "発送方法",
            # 販売チャネル
            "販売チャネル": "販売チャネル",
            "販売先": "販売チャネル",
            "チャネル": "販売チャネル",
            "salesChannel": "販売チャネル",
            "sales_channel": "販売チャネル",
            "platform": "販売チャネル",
            # 手数料・費用合計
            COL_PLATFORM_FEE: COL_PLATFORM_FEE,
            COL_LEGACY_AMAZON_FEE: COL_PLATFORM_FEE,
            "amazon_fee": COL_PLATFORM_FEE,
            "platform_fee": COL_PLATFORM_FEE,
            COL_SHIPPING: COL_SHIPPING,
            "shipping_cost": COL_SHIPPING,
            COL_TOTAL_COST: COL_TOTAL_COST,
            "total_cost": COL_TOTAL_COST,
            "在庫保管手数料": "在庫保管手数料",
            "storage_fee": "在庫保管手数料",
            # 仕入先
            "仕入先": "仕入先",
            "仕入元": "仕入先",
            "店舗": "仕入先",
            "supplier": "仕入先",
            # フリマ・電脳取引情報（単品仕入・CSV共通列名）
            "プラットフォーム": "プラットフォーム",
            "platform": "プラットフォーム",
            "取引ID": "取引ID",
            "transaction_id": "取引ID",
            "ユーザー名": "ユーザー名",
            "出品URL": "出品URL",
            "listing_url": "出品URL",
            "伝票番号": "伝票番号",
            "tracking_number": "伝票番号",
            "受取都道府県": "受取都道府県",
            "prefecture": "受取都道府県",
            # その他詳細・コンディション説明
            "その他詳細": "その他詳細",
            "other_details": "その他詳細",
            "コンディション説明": "コンディション説明",
            "conditionNote": "コンディション説明",
            # SKU（取込時は空でもOK）
            "SKU": "SKU",
            "sku": "SKU",
        }
        
        # 新しいDataFrameを作成
        new_df = pd.DataFrame()
        
        # 指定順序で列を作成
        for new_column in self.column_headers:
            # 元のDataFrameから該当する列を探す
            found = False
            for old_column in df.columns:
                # 列名の正規化（空白除去、大文字小文字統一）
                old_col_normalized = str(old_column).strip()
                
                # マッピングから探す
                if old_col_normalized in column_mapping:
                    if column_mapping[old_col_normalized] == new_column:
                        new_df[new_column] = df[old_column]
                        found = True
                        break
                
                # 直接一致する場合
                if old_col_normalized == new_column:
                    new_df[new_column] = df[old_column]
                    found = True
                    break
            
            # 列が見つからない場合は空の列を作成
            if not found:
                new_df[new_column] = ""
        
        # コンディション説明欄を空にする
        if "コンディション説明" in new_df.columns:
            new_df["コンディション説明"] = ""
        # 販売チャネルが空欄なら既定値を補完
        if "販売チャネル" in new_df.columns:
            new_df["販売チャネル"] = new_df["販売チャネル"].fillna("").astype(str).str.strip()
            new_df.loc[new_df["販売チャネル"] == "", "販売チャネル"] = "Amazon"
        # 発送方法が空欄なら既定値を補完
        if "発送方法" in new_df.columns:
            new_df["発送方法"] = new_df["発送方法"].fillna("").astype(str).str.strip()
            new_df.loc[new_df["発送方法"] == "", "発送方法"] = "FBA"
        
        # SKUが空の場合は「未実装」にする
        if "SKU" in new_df.columns:
            new_df["SKU"] = new_df["SKU"].fillna("").astype(str)
            new_df["SKU"] = new_df["SKU"].replace("nan", "")
            # 空の場合は「未実装」に設定
            new_df["SKU"] = new_df["SKU"].apply(lambda x: "未実装" if x == "" or pd.isna(x) else x)
        
        # JANコードの.0を削除（数値として読み込まれた場合の正規化）
        if "JAN" in new_df.columns:
            def normalize_jan(value):
                """JANコードから.0を削除して文字列に変換"""
                if pd.isna(value) or value == "":
                    return ""
                # 文字列に変換
                jan_str = str(value).strip()
                # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
                if jan_str.endswith(".0"):
                    jan_str = jan_str[:-2]
                # 数字以外の文字を除去（念のため）
                jan_str = ''.join(c for c in jan_str if c.isdigit())
                return jan_str
            new_df["JAN"] = new_df["JAN"].apply(normalize_jan)
        
        # 費用合計補完・利益率とROIを計算
        new_df = self._calculate_margin_and_roi(new_df)
        
        return new_df

    @staticmethod
    def _cell_has_numeric_value(value) -> bool:
        """CSVセルなどに数値が入っているか（空欄・NaNは未入力）"""
        return cell_has_numeric_value(value)

    def _calculate_margin_and_roi(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        費用合計を補完し、見込み利益・損益分岐点・利益率・ROIを反映する。
        CSVに見込み利益／損益分岐点がある行は取込値を優先する。
        損益分岐点 = 仕入 + 手数料内訳 or 費用合計（在庫保管手数料は含めない）。
        """
        if df is None or len(df) == 0:
            return df
        migrate_dataframe_fee_columns(df)
        backfill_total_cost_dataframe(df)

        n = len(df)
        purchase_price = df.get("仕入れ価格", pd.Series([0.0] * n)).apply(purchase_cost_to_float)
        planned_price = df.get("販売予定価格", pd.Series([0.0] * n)).apply(purchase_cost_to_float)
        profit_col = df.get("見込み利益", pd.Series([""] * n))
        be_col = df.get("損益分岐点", pd.Series([""] * n))
        has_profit = profit_col.apply(self._cell_has_numeric_value)
        has_be = be_col.apply(self._cell_has_numeric_value)

        break_even_vals = []
        profit_vals = []
        margin_vals = []
        roi_vals = []
        total_vals = []

        for i in range(n):
            row = df.iloc[i]
            platform, shipping, total = read_fee_fields(row.to_dict())
            fields = recalculate_profit_fields(
                purchase_price.iloc[i],
                planned_price.iloc[i],
                platform,
                shipping,
                total,
                stored_profit=profit_col.iloc[i],
                stored_break_even=be_col.iloc[i],
                prefer_stored_profit=bool(has_profit.iloc[i]),
                prefer_stored_break_even=bool(has_be.iloc[i]),
            )
            total_vals.append(fee_storage_value(fields[COL_TOTAL_COST]))
            break_even_vals.append(fields["損益分岐点"])
            profit_vals.append(fields["見込み利益"])
            margin_vals.append(fields["想定利益率"])
            roi_vals.append(fields["想定ROI"])

        df[COL_TOTAL_COST] = total_vals
        for col in (COL_PLATFORM_FEE, COL_SHIPPING):
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: fee_storage_value(x) if cell_has_numeric_value(x) else ""
                )
        df["損益分岐点"] = break_even_vals
        df["見込み利益"] = profit_vals
        df["想定利益率"] = margin_vals
        df["想定ROI"] = roi_vals
        return df

    def export_csv(self):
        """CSV出力"""
        if self.filtered_data is None:
            QMessageBox.warning(self, "エラー", "出力するデータがありません")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "CSVファイルを保存",
            "inventory_preview.csv",
            "CSVファイル (*.csv)"
        )
        
        if file_path:
            try:
                from pathlib import Path
                from utils.file_naming import resolve_unique_path
                target = resolve_unique_path(Path(file_path))
                self.filtered_data.to_csv(str(target), index=False, encoding='utf-8')
                QMessageBox.information(self, "出力完了", f"プレビュー用CSVを保存しました（UTF-8）。出品用は『出品CSV生成』をご利用ください。\n{str(target)}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")

