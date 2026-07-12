#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB保存・スナップショット mixin。"""
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
from .snapshot_dialog import CombinedSnapshotDialog


class InventoryPersistenceMixin:
    def save_combined_snapshot(self):
        if self.inventory_data is None or len(self.inventory_data) == 0:
            QMessageBox.information(self, "統合保存", "仕入データがありません。")
            return
        if not self.route_summary_widget:
            QMessageBox.information(self, "統合保存", "ルートテンプレートが未ロードです。")
            return
        try:
            purchase_records = self.inventory_data.fillna("").to_dict(orient="records")
        except Exception:
            purchase_records = []
        route_data = self.route_summary_widget.get_route_data()
        visits = self.route_summary_widget.get_store_visits_data()
        payload = {"route": route_data, "visits": visits}
        route_date = route_data.get('route_date', '')
        route_code = route_data.get('route_code', '')
        
        # ルートコードを日本語名に変換
        route_name = None
        if route_code:
            route_name = self.store_db.get_route_name_by_code(route_code)
        
        # 保存名を生成（日付 + 日本語ルート名）
        snapshot_name = (route_date or "未設定").strip()
        if route_name:
            snapshot_name = f"{snapshot_name} {route_name}".strip()
        elif route_code:
            # 日本語名が取得できない場合はコードをそのまま使用
            snapshot_name = f"{snapshot_name} {route_code}".strip()
        
        if not snapshot_name or snapshot_name == "未設定":
            from datetime import datetime
            snapshot_name = datetime.now().strftime("Snapshot %Y-%m-%d %H:%M:%S")
        
        # 日付とルートが同じ場合は上書き保存、それ以外は新規保存
        self.route_snapshot_db.save_snapshot(
            snapshot_name, 
            purchase_records, 
            payload,
            route_date=route_date,
            route_code=route_code
        )
        QMessageBox.information(self, "統合保存", f"統合スナップショットを保存しました。\n{snapshot_name}")

    def _confirm_condition_edit_then_save_to_databases(self) -> bool:
        """
        DB保存前にコンディション（説明）の編集完了を確認する。
        OK のときだけ save_to_databases を実行する。
        """
        reply = QMessageBox.question(
            self,
            "DB保存",
            "コンディション編集はお済ですか？\n\n"
            "【OK】… 仕入データをデータベースに保存します\n"
            "【キャンセル】… 保存せず、一覧で編集を続けます",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return False
        self.save_to_databases()
        return True

    @contextmanager
    def _db_save_busy_scope(self):
        """DB保存中の待機表示（砂時計カーソル＋くるくるダイアログ）。"""
        progress = QProgressDialog(
            "仕入データとルート情報をデータベースに保存しています...",
            None,
            0,
            0,
            self,
        )
        progress.setWindowTitle("DB保存")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        db_btn = getattr(self, "db_save_btn", None)
        if db_btn is not None:
            db_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()
            if db_btn is not None:
                db_btn.setEnabled(True)
            QApplication.processEvents()

    def save_to_databases(self):
        """仕入データ一覧とルート情報をそれぞれのDBに保存"""
        with self._db_save_busy_scope():
            self._save_to_databases_impl()

    def _save_to_databases_impl(self):
        """save_to_databases の本体（busy 表示は呼び出し側で包む）"""
        import json
        
        messages = []
        purchase_saved = False
        route_saved = False
        
        # 1. 仕入データ一覧を商品DBの仕入DBに保存（仕入DBタブの取り込みと同じ処理）
        try:
            # 本番仕入管理タブと同じ列だけ使う（開発タブの「3-6-9」は仕入DBに保存しない＝表示・保存を本番と同じにすることでSKU途切れを防ぐ）
            BASE_COLUMNS_FOR_PURCHASE_DB = [
                "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
                "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "想定利益率", "想定ROI", "コメント",
                "発送方法", "販売チャネル", COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST,
                "在庫保管手数料",
                "仕入先", "価格改定", "その他詳細", "コンディション説明"
            ]
            if self.filtered_data is not None and len(self.filtered_data) > 0:
                cols = [c for c in BASE_COLUMNS_FOR_PURCHASE_DB if c in self.filtered_data.columns]
                df = self.filtered_data[cols].fillna("").copy()
                purchase_records = df.to_dict(orient="records")
            else:
                df = self.get_table_data()
                if df is None or len(df) == 0:
                    df = self.inventory_data
                if df is None or len(df) == 0:
                    purchase_records = []
                else:
                    df = df.fillna("")
                    cols = [c for c in BASE_COLUMNS_FOR_PURCHASE_DB if c in df.columns]
                    if cols:
                        df = df[cols]
                    purchase_records = df.to_dict(orient="records")
            
            if not purchase_records:
                messages.append("仕入データ: データがありません")
            else:
                # 保証・レシート情報を付与
                purchase_records = self._augment_purchase_records_for_db(purchase_records)
                
                # 最新スナップショットから既存データを取得
                snapshots = self.product_purchase_db.list_snapshots()
                existing_all_records: List[Dict[str, Any]] = []
                if snapshots:
                    latest_snapshot = self.product_purchase_db.get_snapshot(snapshots[0]["id"])
                    if latest_snapshot:
                        existing_all_records = latest_snapshot.get("data", [])
                
                # 既存データとマージ（重複チェック）
                # 同じ仕入時間・同じASINが既に仕入DBにある場合はスキップ（更新しない）
                existing_datetime_asin_keys: set = set()
                for rec in existing_all_records:
                    k = self._get_datetime_asin_key(rec)
                    if k:
                        existing_datetime_asin_keys.add(k)
                
                # キーは SKU があれば SKU、それ以外は「仕入れ日 + ASIN/JAN + 商品名 + 店舗コード」で判定
                existing_index: Dict[str, int] = {}
                for idx, rec in enumerate(existing_all_records):
                    key = self._get_purchase_record_key(rec)
                    if key:
                        existing_index[key] = idx

                updated_count = 0
                new_count = 0
                skipped_count = 0
                
                for rec_idx, record in enumerate(purchase_records):
                    if rec_idx % 25 == 0:
                        QApplication.processEvents()
                    dt_asin_key = self._get_datetime_asin_key(record)
                    if dt_asin_key and dt_asin_key in existing_datetime_asin_keys:
                        # 同じ仕入時間・同じASINが既存にある場合はスキップ（重複登録・上書き防止）
                        skipped_count += 1
                        continue
                    
                    key = self._get_purchase_record_key(record)
                    if key and key in existing_index:
                        # 既存データを更新（同じキーの既存レコードを置き換え）
                        existing_rec = existing_all_records[existing_index[key]]
                        new_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                        existing_sku = str(existing_rec.get("SKU") or existing_rec.get("sku") or "").strip()
                        # 新しいSKUが省略(...)で既存がフルの場合は既存SKUを維持（途切れ防止）
                        if new_sku.endswith("...") and existing_sku and not existing_sku.endswith("..."):
                            record = dict(record)
                            record["SKU"] = existing_sku
                            record["sku"] = existing_sku
                        existing_all_records[existing_index[key]] = record
                        updated_count += 1
                    else:
                        # 新規データを追加
                        existing_all_records.append(record)
                        if key:
                            existing_index[key] = len(existing_all_records) - 1
                        if dt_asin_key:
                            existing_datetime_asin_keys.add(dt_asin_key)
                        new_count += 1
                
                # スナップショットに保存
                self.product_purchase_db.save_snapshot("自動保存(仕入DB)", existing_all_records)
                purchase_saved = True
                
                # 仕入DBタブの表示を即時更新（参照があれば）
                if self.product_widget:
                    try:
                        # 最新スナップショットを読み込んで表示を更新
                        self.product_widget.restore_latest_purchase_snapshot()
                        self.product_widget.load_purchase_data(existing_all_records)
                        # テーブルを即再描画して反映させる
                        if hasattr(self.product_widget, "purchase_table") and self.product_widget.purchase_table is not None:
                            self.product_widget.purchase_table.viewport().update()
                            self.product_widget.purchase_table.updateGeometry()
                    except Exception as e:
                        print(f"仕入DBタブの表示更新エラー: {e}")
                
                message = f"仕入データ: {new_count}件の新規データを追加"
                if updated_count > 0:
                    message += f"、{updated_count}件を更新"
                if skipped_count > 0:
                    message += f"、{skipped_count}件をスキップ（同一仕入時間・ASINの既存あり）"
                message += f"しました。（合計: {len(existing_all_records)}件）"
                messages.append(message)
        except Exception as e:
            messages.append(f"仕入データ保存エラー: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # 2. ルート情報をルート訪問DBに保存
        if self.route_summary_widget:
            try:
                route_data = self.route_summary_widget.get_route_data()
                visits = self.route_summary_widget.get_store_visits_data()
                
                route_date = route_data.get('route_date', '')
                route_code = route_data.get('route_code', '')
                
                if route_date and route_code and len(visits) > 0:
                    # ルートコードを日本語名に変換
                    route_name = self.store_db.get_route_name_by_code(route_code)
                    if not route_name:
                        route_name = route_code
                    
                    # 既存データを取得
                    existing_visits = self.route_visit_db.list_route_visits(
                        route_date=route_date,
                        route_code=route_code
                    )
                    
                    if existing_visits:
                        # 既存データと比較
                        # 訪問データを正規化して比較
                        existing_visits_normalized = [
                            {
                                'visit_order': v.get('visit_order'),
                                'store_code': v.get('store_code'),
                                'store_name': v.get('store_name'),
                                'store_in_time': v.get('store_in_time'),
                                'store_out_time': v.get('store_out_time'),
                                'stay_duration': v.get('stay_duration'),
                                'travel_time_from_prev': v.get('travel_time_from_prev'),
                                'store_gross_profit': v.get('store_gross_profit'),
                                'store_item_count': v.get('store_item_count'),
                                'store_rating': v.get('store_rating'),
                                'store_notes': v.get('store_notes'),
                            }
                            for v in existing_visits
                        ]
                        current_visits_normalized = [
                            {
                                'visit_order': v.get('visit_order'),
                                'store_code': v.get('store_code'),
                                'store_name': v.get('store_name'),
                                'store_in_time': v.get('store_in_time'),
                                'store_out_time': v.get('store_out_time'),
                                'stay_duration': v.get('stay_duration'),
                                'travel_time_from_prev': v.get('travel_time_from_prev'),
                                'store_gross_profit': v.get('store_gross_profit'),
                                'store_item_count': v.get('store_item_count'),
                                'store_rating': v.get('store_rating'),
                                'store_notes': v.get('store_notes'),
                            }
                            for v in visits
                        ]
                        
                        existing_json = json.dumps(existing_visits_normalized, ensure_ascii=False, sort_keys=True, default=str)
                        current_json = json.dumps(current_visits_normalized, ensure_ascii=False, sort_keys=True, default=str)
                        
                        if existing_json == current_json:
                            messages.append(f"ルート情報 ({route_date} {route_name}): 変更なし（スキップ）")
                        else:
                            # 差分がある場合は上書き保存
                            self.route_visit_db.replace_route_visits(route_date, route_code, route_name, visits)
                            route_saved = True
                            messages.append(f"ルート情報 ({route_date} {route_name}): {len(visits)}件を保存しました")
                    else:
                        # 既存データがない場合は新規保存
                        self.route_visit_db.replace_route_visits(route_date, route_code, route_name, visits)
                        route_saved = True
                        messages.append(f"ルート情報 ({route_date} {route_name}): {len(visits)}件を保存しました")
                else:
                    messages.append("ルート情報: ルートデータが不完全です（日付・ルートコード・訪問データが必要）")
            except Exception as e:
                messages.append(f"ルート情報保存エラー: {str(e)}")
                import traceback
                traceback.print_exc()
        else:
            messages.append("ルート情報: ルートテンプレートが未ロードです")
        
        # 結果メッセージを表示
        if purchase_saved or route_saved:
            QMessageBox.information(
                self,
                "DB保存完了",
                "DB保存が完了しました。\n\n" + "\n".join(messages),
                QMessageBox.Ok
            )
        else:
            QMessageBox.information(
                self,
                "DB保存",
                "DB保存を実行しました。\n\n" + "\n".join(messages),
                QMessageBox.Ok
            )

    def _augment_purchase_records_for_db(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """保証・レシート情報を付与（仕入DBタブの_augment_purchase_recordsと同じ処理）"""
        import re
        import unicodedata
        import calendar
        
        augmented: List[Dict[str, Any]] = []
        for record in records:
            row = dict(record)
            if not str(row.get("販売チャネル") or "").strip():
                row["販売チャネル"] = "Amazon"
            sku = row.get("SKU") or row.get("sku")
            
            # コメントから保証期間を算出
            comment_warranty = self._infer_warranty_from_comment_for_db(row)
            if comment_warranty:
                row["保証期間"] = comment_warranty
            
            if sku:
                try:
                    product = self.product_db.get_by_sku(sku)
                except Exception:
                    product = None
                if product:
                    if ("保証期間" not in row or not row.get("保証期間")) and product.get("warranty_until"):
                        row["保証期間"] = product.get("warranty_until")
                    if "レシートID" not in row and product.get("receipt_id") is not None:
                        row["レシートID"] = product.get("receipt_id")
                
                # 保証書情報は warranties テーブルを参照
                try:
                    warranties = self.warranty_db.list_by_sku(sku)
                except Exception:
                    warranties = []
                warranty_id = warranties[0]["id"] if warranties else None
                if "保証書ID" not in row and warranty_id is not None:
                    row["保証書ID"] = warranty_id
            augmented.append(row)
        return augmented

    def _get_purchase_record_key(self, record: Dict[str, Any]) -> Optional[str]:
        """
        仕入レコードを一意に識別するためのキーを生成する。
        - SKU があれば SKU を優先（SKU単位で一意）
        - SKU が無い場合は「仕入れ日 + ASIN or JAN + 商品名 + 店舗コード」で判定
          → これにより、同じ仕入データを何度DB保存しても更新扱いになり、重複登録を防ぐ
        """
        sku = str(record.get("SKU") or record.get("sku") or "").strip()
        if sku:
            return f"SKU:{sku}"

        # SKUが無い場合のフォールバックキー
        purchase_date = str(record.get("仕入れ日") or record.get("purchase_date") or "").strip()
        asin = str(record.get("ASIN") or record.get("asin") or "").strip()
        jan = str(record.get("JAN") or record.get("jan") or "").strip()
        asin_or_jan = asin or jan
        title = str(record.get("商品名") or record.get("title") or record.get("product_name") or "").strip()
        store_code = str(
            record.get("仕入先")
            or record.get("店舗コード")
            or record.get("store_code")
            or ""
        ).strip()

        # ほとんど情報が無い場合はキーを作らない（安全のため）
        if not (purchase_date or asin_or_jan or title or store_code):
            return None

        return f"NO-SKU:{purchase_date}|{asin_or_jan}|{store_code}|{title}"

    def _infer_warranty_from_comment_for_db(self, row: Dict[str, Any]) -> Optional[str]:
        """コメント欄から保証期間（月）を推定し、仕入日からの満了日を返す"""
        comment = row.get("コメント") or row.get("comment")
        if not comment:
            return None
        
        import re
        import unicodedata
        import calendar
        
        normalized = unicodedata.normalize("NFKC", str(comment))
        months = self._extract_warranty_months_for_db(normalized)
        if months is None:
            return None
        
        purchase_date_str = row.get("仕入れ日") or row.get("purchase_date")
        purchase_date = self._parse_purchase_date_for_db(purchase_date_str)
        if not purchase_date:
            return None
        
        end_date = self._add_months_for_db(purchase_date, months)
        return end_date.strftime("%Y-%m-%d")

    @staticmethod
    def _extract_warranty_months_for_db(text: str) -> Optional[int]:
        """コメントから保証期間（月数）を抽出"""
        import re
        patterns = [
            r'(\d+)\s*[ヶヵケかカｶ]?\s*(?:月|ヶ月|か月|カ月)\s*保証',
            r'保証\s*(\d+)\s*[ヶヵケかカｶ]?\s*(?:月|ヶ月|か月|カ月)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    continue
        
        # 特殊表現
        if "半年保証" in text or "半年の保証" in text:
            return 6
        if "1年保証" in text or "一年保証" in text:
            return 12
        
        return None

    @staticmethod
    def _parse_purchase_date_for_db(value: Optional[str]) -> Optional[datetime]:
        """仕入日をdatetimeに変換"""
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        
        # 一部フォーマット（年月日）を変換
        text = (
            text.replace("年", "/")
                .replace("月", "/")
                .replace("日", "")
        )
        text = text.replace("-", "/")
        text = text.replace(".", "/")
        
        # 時刻を分離
        candidates = [text]
        if " " in text:
            date_part, time_part = text.split(" ", 1)
            candidates = [
                f"{date_part} {time_part}",
                date_part
            ]
        else:
            candidates = [text]
        
        fmts = [
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
        ]
        
        for candidate in candidates:
            for fmt in fmts:
                try:
                    return datetime.strptime(candidate, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _add_months_for_db(base_date: datetime, months: int) -> datetime:
        """月数を加算"""
        import calendar
        from datetime import datetime
        month = base_date.month - 1 + months
        year = base_date.year + month // 12
        month = month % 12 + 1
        day = min(base_date.day, calendar.monthrange(year, month)[1])
        return datetime(year, month, day)

    def open_combined_snapshot_history(self):
        snapshots = self.route_snapshot_db.list_snapshots()
        if not snapshots:
            QMessageBox.information(self, "統合読込", "統合スナップショットがありません。")
            return
        
        # カスタムダイアログを使用
        dlg = CombinedSnapshotDialog(self.route_snapshot_db, self)
        res = dlg.exec()
        if res == QDialog.Accepted:
            snapshot_id = dlg.get_selected_snapshot_id()
            if snapshot_id:
                snapshot = self.route_snapshot_db.get_snapshot(snapshot_id)
                if not snapshot:
                    QMessageBox.warning(self, "統合読込", "選択したスナップショットを取得できませんでした。")
                    return
                self._restore_combined_snapshot(snapshot)

    def _restore_combined_snapshot(self, snapshot: Dict[str, Any]):
        try:
            purchase_data = snapshot.get("purchase_data") or []
            if purchase_data:
                try:
                    self.inventory_data = pd.DataFrame(purchase_data)
                except Exception:
                    self.inventory_data = pd.DataFrame()
                self.filtered_data = self.inventory_data.copy()
                
                # SKU自動マッチング処理（商品DBから仕入れ日・ASINで検索）
                self._auto_match_sku_from_product_db()
                
                # コメント→コンディション説明の自動入力は運用方針により無効化
                self.filtered_data = self.inventory_data.copy()
                
                self.update_table()
                self.update_data_count()
                
                # ボタンの有効化（データが読み込まれた場合）
                if len(self.inventory_data) > 0:
                    self.export_btn.setEnabled(True)
                    self.clear_btn.setEnabled(True)
                    if hasattr(self, "clear_sku_btn"):
                        self.clear_sku_btn.setEnabled(True)
                    self.generate_sku_btn.setEnabled(True)
                    self.export_listing_btn.setEnabled(True)
                    self.antique_register_btn.setEnabled(True)
            else:
                self.inventory_data = pd.DataFrame()
                self.filtered_data = self.inventory_data
                self.update_table()
                self.update_data_count()
                
                # ボタンの無効化（データが空の場合）
                self.export_btn.setEnabled(False)
                self.clear_btn.setEnabled(False)
                if hasattr(self, "clear_sku_btn"):
                    self.clear_sku_btn.setEnabled(False)
                self.generate_sku_btn.setEnabled(False)
                self.export_listing_btn.setEnabled(False)
                self.antique_register_btn.setEnabled(False)
            
            route_payload = snapshot.get("route_data") or {}
            route_data = route_payload.get("route", {})
            visits = route_payload.get("visits", [])
            if self.route_summary_widget and route_data:
                if hasattr(self.route_summary_widget, "apply_route_snapshot"):
                    self.route_summary_widget.apply_route_snapshot(route_data, visits)
                self.refresh_route_template_view()
            # route_template_status は削除済み（スナップショット読込メッセージは表示しない）
            QMessageBox.information(self, "統合読込", "統合スナップショットを読み込みました。")
        except Exception as e:
            QMessageBox.critical(self, "統合読込エラー", f"スナップショットの読み込みに失敗しました:\n{e}")

