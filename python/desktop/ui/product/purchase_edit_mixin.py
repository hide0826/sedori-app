#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入DB 行編集・スナップショット・画像JAN連携 mixin。"""
from __future__ import annotations

import sys
import os
import re
import unicodedata
import calendar
from datetime import datetime, date
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple, Iterable
import copy
import json
import logging

from PySide6.QtCore import Qt, QMimeData, QUrl, QSettings, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QDialog, QDialogButtonBox,
    QMessageBox, QLabel, QTabWidget, QHeaderView, QFileDialog, QMenu, QApplication,
    QAbstractItemView, QComboBox, QProgressDialog, QCheckBox, QToolButton, QScrollArea, QFrame,
    QSizePolicy, QStyledItemDelegate,
)
from PySide6.QtGui import QDrag, QPixmap, QDesktopServices, QCursor, QColor

from desktop.utils.ui_utils import (
    save_table_header_state, restore_table_header_state,
    save_table_column_widths, restore_table_column_widths
)

logger = logging.getLogger(__name__)

try:
    from utils._desktop_import_compat import (
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        SCROLL_LOAD_THRESHOLD_PX,
        apply_monthly_auto_ladder_to_record,
        augment_purchase_cost_records,
        backfill_condition_label_in_record,
        backfill_purchase_date_from_sku,
        calc_elapsed_days_for_purchase_record as _calc_elapsed_days_for_purchase_record,
        compute_break_even_for_record,
        fee_storage_value,
        fill_purchase_record_tp_from_369,
        get_augment_batch_size,
        get_page_size,
        is_amazon_sales_channel,
        is_eligible_for_monthly_auto,
        is_fee_amount_column,
        is_incremental_render_enabled,
        load_369_repricer_config,
        merge_purchase_history_db_into_display_records,
        normalize_status_code,
        purchase_record_purchase_timestamp,
        resolve_local_image_path,
        resolve_record_product_images,
        should_recompute_break_even,
        sort_purchase_records_for_display,
        summarize_repricing_row,
    )
    from utils._desktop_ui_compat import PurchaseRowEditDialog
except ImportError:
    from desktop.utils._desktop_import_compat import (  # type: ignore
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        SCROLL_LOAD_THRESHOLD_PX,
        apply_monthly_auto_ladder_to_record,
        augment_purchase_cost_records,
        backfill_condition_label_in_record,
        backfill_purchase_date_from_sku,
        calc_elapsed_days_for_purchase_record as _calc_elapsed_days_for_purchase_record,
        compute_break_even_for_record,
        fee_storage_value,
        fill_purchase_record_tp_from_369,
        get_augment_batch_size,
        get_page_size,
        is_amazon_sales_channel,
        is_eligible_for_monthly_auto,
        is_fee_amount_column,
        is_incremental_render_enabled,
        load_369_repricer_config,
        merge_purchase_history_db_into_display_records,
        normalize_status_code,
        purchase_record_purchase_timestamp,
        resolve_local_image_path,
        resolve_record_product_images,
        should_recompute_break_even,
        sort_purchase_records_for_display,
        summarize_repricing_row,
    )
    from desktop.utils._desktop_ui_compat import PurchaseRowEditDialog  # type: ignore

from .support import (
    PRODUCT_NAME_DISPLAY_LIMIT,
    SortableDateItem,
    PurchaseFullTextItemDelegate,
    DraggableTableWidget,
    ProductEditDialog,
    _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV,
    _PURCHASE_RIGHT_ALIGN_NUMERIC_HEADERS,
    _PURCHASE_STATUS_FILTER_OPTIONS,
    _PURCHASE_CHANNEL_FILTER_OPTIONS,
    _PURCHASE_FILE_PATH_COLUMNS,
    _PURCHASE_URL_COLUMNS,
    _PURCHASE_FULLTEXT_MIN_COLUMN_WIDTH,
    _purchase_numeric_cell_text,
    _make_purchase_numeric_table_item,
    _purchase_record_sales_channel,
    _purchase_record_shipping_method,
    purchase_record_matches_amazon_mfn_filter,
    purchase_record_matches_non_amazon_channel_filter,
    _purchase_table_cell_full_text,
)


class PurchaseEditMixin:
    @staticmethod
    def _normalize_jan_for_match(value: Any) -> str:
        jan = str(value or "").strip()
        if jan.endswith(".0"):
            jan = jan[:-2]
        return "".join(c for c in jan if c.isdigit()).upper()

    @staticmethod
    def _extract_purchase_record_date(raw_date: str) -> Optional[date]:
        """候補検索用の高速日付抽出"""
        if not raw_date:
            return None
        s = (
            str(raw_date)
            .strip()
            .replace("/", "-")
            .replace(".", "-")
            .replace("年", "-")
            .replace("月", "-")
            .replace("日", "")
        )
        if " " in s:
            s = s.split(" ", 1)[0]
        if "T" in s:
            s = s.split("T", 1)[0]
        parts = s.split("-")
        if len(parts) < 3:
            return None
        try:
            day_part = str(parts[2]).split(" ")[0]
            return date(int(parts[0]), int(parts[1]), int(day_part))
        except (ValueError, TypeError):
            return None

    def find_purchase_candidates_by_datetime(
        self,
        base_dt: datetime,
        days_window: int = 7,
        jan: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        指定した日時に近い仕入レコード候補を返す

        - 画像の撮影日時から「±N日以内」の仕入データを探すために使用
        - JANが分かっている場合は一致レコードを優先（見つかればJAN一致のみ返す）
        """
        if not hasattr(self, "purchase_all_records") or not self.purchase_all_records:
            return []

        base_date: date = base_dt.date()
        jan_norm = self._normalize_jan_for_match(jan) if jan and str(jan) != "unknown" else ""
        date_matches: List[Tuple[int, Dict[str, Any]]] = []
        jan_matches: List[Tuple[int, Dict[str, Any]]] = []

        for record in self.purchase_all_records:
            raw_date = str(
                record.get("仕入れ日")
                or record.get("purchase_date")
                or ""
            ).strip()
            if not raw_date:
                continue

            rec_date = self._extract_purchase_record_date(raw_date)
            if rec_date is None:
                continue

            diff_days = abs((rec_date - base_date).days)
            if diff_days > days_window:
                continue

            date_matches.append((diff_days, record))
            if jan_norm:
                record_jan = self._normalize_jan_for_match(
                    record.get("JAN") or record.get("jan") or record.get("JANコード")
                )
                if record_jan == jan_norm:
                    jan_matches.append((diff_days, record))

        source = jan_matches if jan_matches else date_matches

        def _sort_key(item: Tuple[int, Dict[str, Any]]):
            diff_days, rec = item
            return (
                diff_days,
                str(rec.get("仕入れ日") or rec.get("purchase_date") or ""),
                str(rec.get("SKU") or rec.get("sku") or ""),
            )

        source.sort(key=_sort_key)

        candidates: List[Dict[str, Any]] = []
        for diff_days, record in source:
            rec_copy = {**record, "_date_diff": diff_days}
            for key in ("JAN", "jan", "JANコード", "jan_code"):
                if key in rec_copy and rec_copy[key]:
                    jan_str = self._normalize_jan_for_match(rec_copy[key])
                    rec_copy[key] = jan_str if jan_str else None
            candidates.append(rec_copy)
        return candidates

    def update_image_paths_for_jan(
        self,
        jan: str,
        image_paths: List[str],
        all_records: List[Dict[str, Any]],
        skip_existing: bool = True,
        target_sku: Optional[str] = None,
        clear_existing: bool = False,
        defer_table_refresh_and_snapshot: bool = False,
    ) -> Tuple[bool, int, Optional[Dict[str, Any]]]:
        """
        指定JANに対応する仕入レコードへ画像パスを割り当てる

        Args:
            jan: 対象とするJANコード
            image_paths: 割り当てたい画像パスのリスト
            all_records: 現在の全仕入レコード（purchase_all_records 相当）
            skip_existing: 既に画像列が埋まっている場合はスキップするかどうか
            clear_existing: 既存の画像をクリアしてから新しい画像を登録するかどうか
            defer_table_refresh_and_snapshot: True のとき、テーブル再描画とスナップショット保存を省略する。
                画像管理の「確定処理」など複数JANを連続更新するとき、各回で全行再描画・DB保存すると極端に遅くなるため。

        Returns:
            (success, added_count, record_snapshot)
        """
        if not jan or not image_paths or not all_records:
            return False, 0, None

        jan_norm = str(jan).strip().upper()

        # 対象レコードを探す
        target_record: Optional[Dict[str, Any]] = None
        target_sku_norm: Optional[str] = None
        if target_sku:
            target_sku_norm = str(target_sku).strip()

        for record in all_records:
            record_jan = str(
                record.get("JAN") or record.get("jan") or ""
            ).strip().upper()
            record_sku = str(record.get("SKU") or record.get("sku") or "").strip()

            # 1. SKU指定がある場合は SKU + JAN の両方が一致するレコードを優先
            if target_sku_norm and record_sku and record_sku == target_sku_norm and record_jan == jan_norm:
                target_record = record
                break

            # 2. SKU指定がない場合は、JAN が一致する最初のレコードを候補にする
            if not target_sku_norm and record_jan == jan_norm:
                target_record = record
                break

        if target_record is None:
            return False, 0, None

        # 画像列名候補（仕入DB側の列名）
        image_columns = [f"画像{i}" for i in range(1, 7)]

        # 既存の画像をクリアする場合
        if clear_existing:
            for col in image_columns:
                target_record[col] = ""

        added_count = 0

        # 既存の画像パスを取得（重複登録を避ける）
        existing_paths = set()
        for col in image_columns:
            val = str(target_record.get(col) or "").strip()
            if val:
                existing_paths.add(val)

        for image_path in image_paths:
            if not image_path:
                continue
            image_path = str(image_path)

            if image_path in existing_paths:
                continue

            # 空いている列を探す
            empty_col_name: Optional[str] = None
            for col in image_columns:
                current_val = str(target_record.get(col) or "").strip()
                if not current_val:
                    empty_col_name = col
                    break

            if empty_col_name is None:
                if skip_existing:
                    # すべて埋まっている場合は追加しない
                    continue
                # skip_existing=False の場合は最後の列を上書き
                empty_col_name = image_columns[-1]

            target_record[empty_col_name] = image_path
            existing_paths.add(image_path)
            added_count += 1

        # added_count == 0 の場合でも、既に登録済みのレコードのスナップショットを返す
        # （画像登録タブに反映するため）
        if added_count == 0:
            # スナップショット用にコピーを返す（既存レコードでも反映するため）
            record_snapshot = dict(target_record)
            return True, 0, record_snapshot

        # purchase_all_records にも変更を反映（同じオブジェクトを指している前提）
        if hasattr(self, "purchase_all_records") and self.purchase_all_records:
            for idx, rec in enumerate(self.purchase_all_records):
                sku1 = rec.get("SKU") or rec.get("sku")
                sku2 = target_record.get("SKU") or target_record.get("sku")
                if sku1 and sku2 and str(sku1) == str(sku2):
                    self.purchase_all_records[idx] = target_record
                    break

        if not defer_table_refresh_and_snapshot:
            # テーブルを再描画
            self.purchase_records = list(self.purchase_all_records)
            self.populate_purchase_table(self.purchase_records)
            self.update_purchase_count_label()

            # スナップショットを保存（リネーム後のパスを永続化）
            try:
                self.save_purchase_snapshot()
            except Exception as e:
                logger.warning(f"スナップショット保存エラー（画像パス更新は反映済み）: {e}")

        # スナップショット用にコピーを返す
        record_snapshot = dict(target_record)
        return True, added_count, record_snapshot

    def patch_purchase_records_by_sku_map(
        self, patches_by_sku: Dict[str, Dict[str, Any]]
    ) -> int:
        """SKU単位で仕入レコード（all/master/filtered）にフィールドを反映する。"""
        if not patches_by_sku:
            return 0
        updated = 0
        list_names = (
            "purchase_all_records",
            "purchase_all_records_master",
            "purchase_records",
        )
        for sku, patch in patches_by_sku.items():
            sku = str(sku or "").strip()
            if not sku or not patch:
                continue
            touched = False
            for lst_name in list_names:
                lst = getattr(self, lst_name, None) or []
                for record in lst:
                    record_sku = str(record.get("SKU") or record.get("sku") or "").strip()
                    if record_sku != sku:
                        continue
                    for key, value in patch.items():
                        if value is not None:
                            record[key] = value
                    touched = True
                    break
            if touched:
                updated += 1
        return updated

    def sync_purchase_master_records_for_skus(self, skus: Iterable[str]) -> int:
        """変更したSKUのみ master / purchase_records に同期（全件 deepcopy を避ける）。"""
        sku_set = {str(s).strip() for s in skus if str(s).strip()}
        if not sku_set:
            return 0
        all_recs = getattr(self, "purchase_all_records", None) or []
        src_by_sku: Dict[str, Dict[str, Any]] = {}
        for record in all_recs:
            sku = str(record.get("SKU") or record.get("sku") or "").strip()
            if sku:
                src_by_sku[sku] = record
        updated = 0
        for lst_name in ("purchase_all_records_master", "purchase_records"):
            lst = getattr(self, lst_name, None)
            if not lst:
                continue
            for i, record in enumerate(lst):
                sku = str(record.get("SKU") or record.get("sku") or "").strip()
                if sku not in sku_set:
                    continue
                src = src_by_sku.get(sku)
                if not src:
                    continue
                lst[i] = dict(src)
                updated += 1
        return updated

    def sync_purchase_master_from_records(self) -> None:
        """purchase_all_records の変更を master に同期（確定・レシート編集後用）。"""
        records = getattr(self, "purchase_all_records", None)
        if not records:
            return
        self.purchase_all_records_master = copy.deepcopy(records)
        if self._purchase_search_filters_active():
            self.filter_purchase_records()
        else:
            self.purchase_records = copy.deepcopy(records)

    def save_purchase_snapshot(self, *, skip_master_sync: bool = False):
        """現在の仕入データをスナップショットとして保存"""
        # 確定処理等で all_records のみ更新されている場合に備え、保存前に master を同期
        if not skip_master_sync:
            self.sync_purchase_master_from_records()
        master = getattr(self, "purchase_all_records_master", None) or getattr(
            self, "purchase_all_records", None
        )
        if not master:
            return
        try:
            latest_non_empty = next(
                (
                    int(s.get("item_count") or 0)
                    for s in self.purchase_db.list_snapshots()
                    if int(s.get("item_count") or 0) > 0
                ),
                0,
            )
            if latest_non_empty >= 100 and len(master) < max(10, latest_non_empty // 2):
                print(
                    "スナップショット保存スキップ: "
                    f"現在件数が少なすぎます ({len(master)} / 直近 {latest_non_empty})"
                )
                return
        except Exception as e:
            print(f"スナップショット保存前チェックエラー: {e}")
        try:
            snapshot_name = f"Snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.purchase_db.save_snapshot(snapshot_name, master)
        except Exception as e:
            print(f"スナップショット保存エラー: {e}")

    def restore_latest_purchase_snapshot(self):
        """最新のスナップショットを復元"""
        try:
            snapshots = self.purchase_db.list_snapshots()
            # 空スナップショットが最新になっても、直近の非空データから復元する。
            # 表示不具合時に「保存件数: 0件」の状態を拾い続けないための保険。
            for row in snapshots:
                if int(row.get("item_count") or 0) <= 0:
                    continue
                snapshot = self.purchase_db.get_snapshot(row["id"])
                if snapshot:
                    data = snapshot.get("data") or []
                    if not data:
                        continue
                    self.purchase_all_records_master = list(data)
                    self.purchase_all_records = list(data)
                    self.purchase_records = list(self.purchase_all_records)
                    return
        except Exception as e:
            print(f"スナップショット復元エラー: {e}")
        
        self.purchase_all_records_master = []
        self.purchase_all_records = []
        self.purchase_records = []

    def reload_purchase_from_latest_snapshot(self):
        """最新スナップショットから仕入DBを再読み込み（表示不具合の復旧用）"""
        reply = QMessageBox.question(
            self,
            "仕入DB再読込",
            "最新のスナップショットから仕入DBを読み直します。\n"
            "テーブル上の未保存の編集は失われます。よろしいですか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._initial_data_loaded = False
        self._purchase_loaded = False
        self.clear_purchase_search()

        try:
            with self._initial_db_load_busy_scope():
                self.restore_latest_purchase_snapshot()
                count = len(self.purchase_records or [])
                if count == 0:
                    QMessageBox.warning(
                        self,
                        "仕入DB再読込",
                        "スナップショットにデータがありません。\n"
                        "仕入管理タブから取り込むか、バックアップを確認してください。",
                    )
                    return
                self.load_purchase_data(self.purchase_records)
                self._purchase_loaded = True
                self._initial_data_loaded = True
        except Exception as e:
            QMessageBox.critical(self, "仕入DB再読込", f"読み込みに失敗しました:\n{e}")
            return

        master_n = len(getattr(self, "purchase_all_records_master", []) or [])
        shown_n = len(getattr(self, "purchase_records", []) or [])
        QMessageBox.information(
            self,
            "仕入DB再読込",
            f"読み込み完了しました。\n全体: {master_n} 件 / 表示: {shown_n} 件",
        )

    def on_delete_purchase_row(self):
        """選択行を削除"""
        rows = sorted({index.row() for index in self.purchase_table.selectedIndexes()})
        if not rows:
            QMessageBox.warning(self, "選択なし", "削除する行を選択してください。")
            return

        # 行ID（_row_id）を取得して削除対象を特定
        row_ids_to_delete = set()
        for row in rows:
            try:
                for c in range(self.purchase_table.columnCount()):
                    it = self.purchase_table.item(row, c)
                    if it is None:
                        continue
                    v = it.data(Qt.UserRole + 1)
                    if v is None:
                        continue
                    try:
                        row_ids_to_delete.add(int(v))
                    except (TypeError, ValueError):
                        continue
                    break
            except Exception:
                continue

        # フォールバック: 行IDがない場合は削除不可
        if not row_ids_to_delete:
            QMessageBox.warning(self, "削除不可", "削除対象の行情報が取得できませんでした。")
            return

        if QMessageBox.question(self, "確認", f"{len(row_ids_to_delete)}件のデータを削除しますか？") != QMessageBox.Yes:
            return

        # _row_id をキーに、内部リストから該当レコードを削除（スナップショット用DBのみ）
        def _filter_by_row_id(lst):
            out = []
            for rec in lst or []:
                try:
                    rid = int(rec.get("_row_id")) if rec.get("_row_id") is not None else None
                except (TypeError, ValueError):
                    rid = None
                if rid is None or rid not in row_ids_to_delete:
                    out.append(rec)
            return out

        if hasattr(self, "purchase_records"):
            self.purchase_records = _filter_by_row_id(getattr(self, "purchase_records", []))

        for attr_name in ["purchase_all_records", "purchase_all_records_master"]:
            if hasattr(self, attr_name):
                setattr(self, attr_name, _filter_by_row_id(getattr(self, attr_name, [])))

        master = self._purchase_master_records()
        self._invalidate_purchase_table_full_master()
        self.populate_purchase_table(master)
        self._purchase_table_full_master_built = bool(master)
        self.filter_purchase_records()
        self.update_purchase_count_label()
        self.save_purchase_snapshot()

    def on_delete_all_purchase(self):
        """全行削除"""
        if not self.purchase_records:
            return
            
        if QMessageBox.question(self, "確認", "表示中の全データを削除しますか？") != QMessageBox.Yes:
            return
            
        self.purchase_records = []
        self.purchase_all_records = []
        self._invalidate_purchase_table_full_master()
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
        self.save_purchase_snapshot()

    _PURCHASE_ROW_EDIT_SYNC_KEYS = (
        "コンディション",
        "condition",
        "condition_code",
        "TP0",
        "tp0",
        "TP1",
        "tp1",
        "TP2",
        "tp2",
        "TP3",
        "tp3",
        "ladder_enabled",
        "ladder_rules",
        "repricing_enabled",
        "価格改定",
        "販売チャネル",
        "sales_channel",
        "発送方法",
        "shippingMethod",
        "shipping_method",
        "プラットフォーム手数料",
        "Amazon手数料",
        "出荷費用",
        "費用合計",
        "見込み利益",
        "expected_profit",
        "損益分岐点",
        "想定利益率",
        "想定ROI",
        "expected_margin",
        "expected_roi",
    )

    def apply_purchase_row_edit_to_memory(
        self, record: Dict[str, Any], *, old_sku: Optional[str] = None
    ) -> None:
        """仕入行編集の反映内容をマスター／表示リストへ同期（SKU 単位）。"""
        new_sku = str(record.get("SKU") or record.get("sku") or "").strip()
        match_sku = str(old_sku or new_sku or "").strip()
        if not match_sku and not new_sku:
            return

        def _row_matches(rec: Dict[str, Any]) -> bool:
            s = str(rec.get("SKU") or rec.get("sku") or "").strip()
            if not s:
                return False
            if match_sku and s == match_sku:
                return True
            return bool(new_sku and s == new_sku)

        def _merge_into(rec: Dict[str, Any]) -> None:
            for key in self._PURCHASE_ROW_EDIT_SYNC_KEYS:
                if key in record:
                    rec[key] = record[key]
            if new_sku:
                rec["SKU"] = new_sku
                rec["sku"] = new_sku

        for lst_name in (
            "purchase_all_records_master",
            "purchase_all_records",
            "purchase_records",
        ):
            lst = getattr(self, lst_name, None)
            if not isinstance(lst, list):
                continue
            for rec in lst:
                if _row_matches(rec):
                    _merge_into(rec)

    def refresh_purchase_display_after_row_edit(
        self, edited_record: Optional[Dict[str, Any]] = None
    ) -> None:
        """仕入行編集反映後: 月別・改定価格列を即時更新し、フィルタ状態を維持する。"""
        if edited_record:
            self._refresh_purchase_repricing_table_cells_for_record(edited_record)
        self.filter_purchase_records()

    def _delete_record_by_row_signature(self, row: int) -> None:
        """
        SKUが空の行などを、テーブル上の内容（全カラム）をキーにして内部レコードから削除する。
        ソートやフィルタで行番号と内部インデックスがずれていても、内容一致で削除できるようにする。
        """
        if not hasattr(self, "purchase_columns"):
            return

        # テーブル行から「列名 -> テキスト」の辞書を作成（空文字はキーとして弱く扱う）
        row_values: Dict[str, str] = {}
        for col_idx, col_name in enumerate(self.purchase_columns):
            if col_name is None:
                continue
            item = self.purchase_table.item(row, col_idx)
            text = (item.text() if item else "").strip()
            # 完全空欄はマッチ条件から外す（ユルめの比較にする）
            if text != "":
                row_values[str(col_name)] = text

        if not row_values:
            return

        def _matches(rec: Dict[str, Any]) -> bool:
            """record が row_values と一致するか判定（指定された列のみ比較）"""
            for col_name, text in row_values.items():
                val = self._get_record_value(rec, [col_name])
                val_str = "" if val is None else str(val).strip()
                if val_str != text:
                    return False
            return True

        # 各リストから最初にマッチしたレコードを1件だけ削除
        for attr_name in ["purchase_records", "purchase_all_records", "purchase_all_records_master"]:
            if not hasattr(self, attr_name):
                continue
            lst = getattr(self, attr_name, [])
            if not lst:
                continue
            for idx, rec in enumerate(lst):
                if _matches(rec):
                    del lst[idx]
                    break

    def _link_receipt_image_to_sku(self, row: int):
        """レシート画像をSKUに紐付けする"""
        from PySide6.QtWidgets import QFileDialog
        
        # SKUを取得
        sku = self._get_value_from_row(row, ["SKU", "sku"])
        if not sku:
            QMessageBox.warning(self, "エラー", "SKUが見つかりません。")
            return
        
        # レシートDBからレシート一覧を取得
        all_receipts = self.receipt_db.find_by_date_and_store(None, None)
        if not all_receipts:
            QMessageBox.information(self, "情報", "レシートが登録されていません。")
            return
        
        # レシート選択ダイアログを表示
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QPushButton, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("レシート画像を選択")
        dialog.resize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        label = QLabel(f"SKU: {sku} に紐付けるレシート画像を選択してください。")
        layout.addWidget(label)
        
        receipt_list = QListWidget()
        receipt_list.setSelectionMode(QListWidget.SingleSelection)
        
        # レシート一覧を表示（日付、店舗名、ファイル名）
        for receipt in all_receipts:
            receipt_id = receipt.get('id')
            purchase_date = receipt.get('purchase_date', '')
            store_name = receipt.get('store_name_raw', '') or receipt.get('store_name', '')
            file_path = receipt.get('original_file_path') or receipt.get('file_path', '')
            file_name = Path(file_path).name if file_path else ''
            
            display_text = f"{purchase_date} - {store_name} - {file_name}"
            receipt_list.addItem(display_text)
            # UserRoleにレシート情報を保存
            receipt_list.item(receipt_list.count() - 1).setData(Qt.UserRole, receipt)
        
        layout.addWidget(receipt_list)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        if dialog.exec_() != QDialog.Accepted:
            return
        
        # 選択されたレシートを取得
        selected_items = receipt_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "エラー", "レシートが選択されていません。")
            return
        
        selected_receipt = selected_items[0].data(Qt.UserRole)
        if not selected_receipt:
            QMessageBox.warning(self, "エラー", "レシート情報の取得に失敗しました。")
            return
        
        # レシート画像を仕入DBに反映
        try:
            # 画像ファイルパスを取得
            file_path = selected_receipt.get('original_file_path') or selected_receipt.get('file_path', '')
            if not file_path:
                QMessageBox.warning(self, "エラー", "レシート画像のファイルパスが見つかりません。")
                return
            
            image_file = Path(file_path)
            if not image_file.exists():
                QMessageBox.warning(self, "エラー", f"レシート画像ファイルが見つかりません:\n{file_path}")
                return
            
            # ファイル名（拡張子なし）を取得（表示用）
            image_file_name = image_file.stem
            
            # purchase_all_recordsを更新
            found = False
            if hasattr(self, 'purchase_all_records') and self.purchase_all_records:
                for record in self.purchase_all_records:
                    record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                    if record_sku == sku:
                        # レシート画像を更新
                        record['レシート画像'] = image_file_name
                        record['レシート画像パス'] = str(image_file.resolve())
                        found = True
                        break
            
            # ProductDatabaseにも反映（永続化）
            product = self.db.get_by_sku(sku)
            if product:
                product['receipt_id'] = image_file_name
                self.db.upsert(product)
            else:
                # ProductDatabaseに商品がない場合は、最小限の情報で作成
                product_data = {
                    'sku': sku,
                    'receipt_id': image_file_name,
                }
                self.db.upsert(product_data)
            
            # レシートDBのlinked_skusにも追加（既存のSKUに追加、重複を避ける）
            receipt_id = selected_receipt.get('id')
            if receipt_id:
                existing_skus_text = selected_receipt.get('linked_skus', '') or ''
                existing_skus = [s.strip() for s in existing_skus_text.split(',') if s.strip()] if existing_skus_text else []
                if sku not in existing_skus:
                    existing_skus.append(sku)
                    self.receipt_db.update_receipt(receipt_id, {'linked_skus': ','.join(existing_skus)})
            
            # テーブルを更新
            if hasattr(self, 'purchase_all_records') and self.purchase_all_records:
                self.populate_purchase_table(self.purchase_all_records)
            
            QMessageBox.information(self, "完了", f"レシート画像をSKU {sku} に紐付けました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"レシート画像の紐付け中にエラーが発生しました:\n{str(e)}")

    def on_purchase_table_cell_clicked(self, row: int, col: int):
        """仕入DBテーブルのセルクリック時の処理（レシート画像をクリックしたときに画像を表示、ステータス理由をクリックしたときに編集モードに入る）"""
        header = self.purchase_table.horizontalHeaderItem(col)
        if not header:
            return
        
        header_text = header.text()
        
        # ステータス理由列をクリックしたときに編集モードに入る
        if header_text == "ステータス理由":
            item = self.purchase_table.item(row, col)
            if item and (item.flags() & Qt.ItemIsEditable):
                # 編集モードに入る（少し遅延を入れて確実に編集モードに入るようにする）
                QApplication.processEvents()
                self.purchase_table.editItem(item)
            return
        if header_text == "レシート画像URL":
            item = self.purchase_table.item(row, col)
            if not item:
                return
            url = _purchase_table_cell_full_text(header_text, item, item.text() or "").strip()
            if not url or self._is_placeholder_url(url):
                QMessageBox.information(
                    self,
                    "情報",
                    "レシート画像URLが設定されていません。\n"
                    "（スナップショットに https://... とだけ保存されている場合は、"
                    "商品DBまたはレシートDBからURLを補完できませんでした）",
                )
                return
            qurl = QUrl(url)
            if not qurl.isValid():
                QMessageBox.warning(self, "警告", f"URLが不正です:\n{url}")
                return
            if not QDesktopServices.openUrl(qurl):
                QMessageBox.warning(self, "警告", f"ブラウザでURLを開けませんでした:\n{url}")
            return
        if header_text.startswith("画像URL"):
            item = self.purchase_table.item(row, col)
            if not item:
                return
            url = _purchase_table_cell_full_text(header_text, item, item.text() or "").strip()
            if not url or self._is_placeholder_url(url):
                QMessageBox.information(self, "情報", "画像URLが設定されていません。")
                return
            qurl = QUrl(url)
            if not qurl.isValid():
                QMessageBox.warning(self, "警告", f"URLが不正です:\n{url}")
                return
            if not QDesktopServices.openUrl(qurl):
                QMessageBox.warning(self, "警告", f"ブラウザでURLを開けませんでした:\n{url}")
            return
        if header_text == "レシート画像":
            item = self.purchase_table.item(row, col)
            if not item:
                return

            receipt_label = (item.text() or "").strip()
            if not receipt_label:
                QMessageBox.information(self, "情報", "レシート画像が設定されていません。")
                return

            record: Dict[str, Any] = {}
            row_id = None
            if row < len(getattr(self, "_purchase_table_row_ids_by_index", [])):
                row_id = self._purchase_table_row_ids_by_index[row]
            if row_id is not None and row_id in getattr(self, "_purchase_row_map", {}):
                record = self._purchase_row_map[row_id]

            file_path = item.data(Qt.UserRole)
            if file_path:
                file_path = str(file_path).strip()
                path_obj = Path(file_path)
                if not (path_obj.exists() and path_obj.is_file()):
                    file_path = self._resolve_receipt_file_path(record, receipt_label) or file_path
            else:
                file_path = self._resolve_receipt_file_path(record, receipt_label)

            receipt_info = self._find_receipt_info_for_key(receipt_label)

            if file_path:
                image_file = Path(file_path)
                if image_file.exists() and image_file.is_file():
                    if record:
                        record["レシート画像パス"] = str(image_file.resolve())
                    item.setData(Qt.UserRole, str(image_file.resolve()))
                    file_url = QUrl.fromLocalFile(str(image_file.absolute()))
                    if not QDesktopServices.openUrl(file_url):
                        QMessageBox.warning(self, "警告", f"画像ファイルを開けませんでした:\n{file_path}")
                    return

            lookup_key = self._receipt_image_lookup_key(receipt_label)
            if receipt_info:
                QMessageBox.warning(
                    self, "警告",
                    f"レシート画像のファイルが見つかりません:\n\n"
                    f"識別子: {lookup_key}\n"
                    f"DB上のパス: {receipt_info.get('original_file_path') or receipt_info.get('file_path')}\n\n"
                    f"レシートDBには登録されていますが、\n"
                    f"ファイルが削除されているか、\n"
                    f"パスが変更されている可能性があります。",
                )
            else:
                QMessageBox.warning(
                    self, "警告",
                    f"レシート画像が見つかりません:\n\n"
                    f"識別子: {lookup_key}\n\n"
                    f"レシートDBに未登録、または識別子が一致しない可能性があります。",
                )
            return
        elif header_text == "保証書画像":
            item = self.purchase_table.item(row, col)
            if not item:
                return
            
            warranty_image_name = item.text().strip()
            if not warranty_image_name:
                QMessageBox.information(self, "情報", "保証書画像が設定されていません。")
                return
            
            # ファイルパスを取得（UserRoleに保存されている）
            file_path = item.data(Qt.UserRole)
            
            # UserRoleにファイルパスがない、またはファイルが存在しない場合は、テキストから再検索
            file_path_found = False
            receipt_info = None
            warranty_info = None
            
            if file_path:
                file_path_obj = Path(file_path)
                # ファイルパスが存在するか確認
                if file_path_obj.exists() and file_path_obj.is_file():
                    file_path_found = True
                else:
                    # UserRoleに保存されている値がファイル名の可能性があるので、再検索
                    file_path = None
            
            # 再検索が必要な場合
            if not file_path_found:
                # まずレシートDBから保証書を検索（ファイル名で検索）
                receipt_info = self.receipt_db.find_by_file_name(warranty_image_name)
                if receipt_info:
                    # original_file_pathを優先、なければfile_path
                    file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path')
                else:
                    # レシートDBで見つからない場合は、保証書DBから検索
                    sku = self._get_value_from_row(row, ["SKU", "sku"])
                    if sku:
                        try:
                            warranties = self.warranty_db.list_by_sku(sku)
                            if warranties:
                                warranty_info = warranties[0]
                                file_path = warranty_info.get('file_path', '')
                        except Exception:
                            pass
            
            if file_path:
                image_file = Path(file_path)
                if image_file.exists() and image_file.is_file():
                    # OSのデフォルトアプリで画像を開く
                    file_url = QUrl.fromLocalFile(str(image_file.absolute()))
                    if not QDesktopServices.openUrl(file_url):
                        QMessageBox.warning(self, "警告", f"画像ファイルを開けませんでした:\n{file_path}")
                else:
                    # ファイルが存在しない場合の詳細メッセージ
                    if receipt_info or warranty_info:
                        QMessageBox.warning(
                            self, "警告",
                            f"保証書画像のファイルが見つかりません:\n\n"
                            f"ファイル名: {warranty_image_name}\n"
                            f"ファイルパス: {file_path}\n\n"
                            f"データベースには登録されていますが、\n"
                            f"ファイルが削除されているか、\n"
                            f"パスが変更されている可能性があります。"
                        )
                    else:
                        QMessageBox.warning(
                            self, "警告",
                            f"保証書画像が見つかりません:\n\n"
                            f"ファイル名: {warranty_image_name}\n\n"
                            f"レシートDBまたは保証書DBに登録されていない可能性があります。"
                        )
            else:
                QMessageBox.information(
                    self, "情報",
                    f"保証書画像の情報を取得できませんでした:\n\n"
                    f"ファイル名: {warranty_image_name}"
                )
        elif header_text and header_text.startswith("画像") and header_text[2:].isdigit():
            # 画像1～6のクリック処理
            item = self.purchase_table.item(row, col)
            if not item:
                return
            
            # ファイルパスを取得（UserRoleに保存されている）
            file_path = item.data(Qt.UserRole)
            record = self._purchase_record_for_table_row(row)
            if file_path and record:
                image_file = Path(file_path)
                if not image_file.is_file():
                    resolved = resolve_local_image_path(str(file_path), record)
                    if resolved:
                        file_path = resolved
                        item.setData(Qt.UserRole, resolved)
                        record[header_text] = resolved
                        idx = None
                        if header_text in self.purchase_columns:
                            idx = self.purchase_columns.index(header_text)
                        if idx is not None:
                            name_item = QTableWidgetItem(Path(resolved).name)
                            name_item.setData(Qt.UserRole, resolved)
                            name_item.setToolTip(f"クリックで画像を開く\n{resolved}")
                            font = name_item.font()
                            font.setUnderline(True)
                            name_item.setFont(font)
                            name_item.setForeground(Qt.white)
                            self.purchase_table.setItem(row, idx, name_item)
            
            if file_path:
                image_file = Path(file_path)
                if image_file.is_file():
                    # 画像を表示
                    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
                    from PySide6.QtGui import QPixmap
                    
                    dialog = QDialog(self)
                    dialog.setWindowTitle(f"{header_text}: {image_file.name}")
                    layout = QVBoxLayout(dialog)
                    
                    label = QLabel()
                    pixmap = QPixmap(str(file_path))
                    if not pixmap.isNull():
                        # 画像を適切なサイズにリサイズ（最大800x600）
                        scaled_pixmap = pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        label.setPixmap(scaled_pixmap)
                    else:
                        label.setText("画像を読み込めませんでした。")
                    
                    layout.addWidget(label)
                    dialog.exec_()
                else:
                    QMessageBox.warning(self, "警告", f"画像ファイルが見つかりません:\n{file_path}")
            else:
                QMessageBox.information(self, "情報", f"{header_text}が設定されていません。")
        else:
            # その他の列をダブルクリックした場合は Keepa 編集ダイアログを開く
            self._open_purchase_row_edit(row)

    def _purchase_record_for_table_row(self, row: int) -> Optional[Dict[str, Any]]:
        """仕入DBテーブルの行に対応するレコード辞書を返す。"""
        row_id: Optional[int] = None
        try:
            for c in range(self.purchase_table.columnCount()):
                it = self.purchase_table.item(row, c)
                if it is None:
                    continue
                v = it.data(Qt.UserRole + 1)
                if v is None:
                    continue
                row_id = int(v)
                break
        except (TypeError, ValueError):
            row_id = None

        row_map = getattr(self, "_purchase_row_map", {}) or {}
        if row_id is not None and row_id in row_map:
            return row_map[row_id]

        sku = (self._get_value_from_row(row, ["SKU", "sku"]) or "").strip()
        if sku:
            for rec in getattr(self, "purchase_records", None) or getattr(self, "purchase_all_records", []) or []:
                if (rec.get("SKU") or rec.get("sku") or "").strip() == sku:
                    return rec
        view_records = getattr(self, "purchase_records", None) or getattr(self, "purchase_all_records", [])
        if (
            view_records
            and not self.purchase_table.isSortingEnabled()
            and 0 <= row < len(view_records)
        ):
            return view_records[row]
        return None

    def _open_purchase_row_edit(self, row: Optional[int] = None) -> None:
        """仕入DB行の編集ダイアログ（Keepa・TP1/TP2 編集）を開く"""
        if row is None:
            row = self.purchase_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "編集", "行を選択してください。")
            return
        # テーブル表示元（フィルタ後）レコード
        view_records = getattr(self, "purchase_records", None) or getattr(self, "purchase_all_records", [])
        if not view_records:
            QMessageBox.warning(self, "編集", "該当するデータがありません。")
            return
        sku_vis = (self._get_value_from_row(row, ["SKU", "sku"]) or "").strip()
        asin_vis = (self._get_value_from_row(row, ["ASIN", "asin"]) or "").strip()

        row_id: Optional[int] = None
        try:
            for c in range(self.purchase_table.columnCount()):
                it = self.purchase_table.item(row, c)
                if it is None:
                    continue
                v = it.data(Qt.UserRole + 1)
                if v is None:
                    continue
                try:
                    row_id = int(v)
                except (TypeError, ValueError):
                    continue
                break
        except Exception:
            row_id = None

        def _rec_sku(rec: Dict[str, Any]) -> str:
            return (rec.get("SKU") or rec.get("sku") or "").strip()

        def _rec_asin(rec: Dict[str, Any]) -> str:
            return (rec.get("ASIN") or rec.get("asin") or "").strip()

        record: Optional[Dict[str, Any]] = None
        row_map = getattr(self, "_purchase_row_map", {}) or {}
        if row_id is not None and row_map:
            candidate = row_map.get(row_id)
            if candidate is not None:
                if (not sku_vis or _rec_sku(candidate) == sku_vis) and (
                    not asin_vis or _rec_asin(candidate) == asin_vis
                ):
                    record = candidate

        if record is None and (sku_vis or asin_vis):
            candidates = []
            for rec in view_records:
                if sku_vis and _rec_sku(rec) != sku_vis:
                    continue
                if asin_vis and _rec_asin(rec) != asin_vis:
                    continue
                candidates.append(rec)
            if len(candidates) == 1:
                record = candidates[0]
            elif len(candidates) > 1 and row_id is not None:
                for rec in candidates:
                    try:
                        if int(rec.get("_row_id")) == row_id:
                            record = rec
                            break
                    except (TypeError, ValueError):
                        continue
                if record is None:
                    record = candidates[0]

        if record is None:
            # 最終フォールバック: 未ソート時のみ一致。ソート済みでは行番号≠リスト添字のため使わない
            if not self.purchase_table.isSortingEnabled() and row < len(view_records):
                rec = view_records[row]
                if (not sku_vis or _rec_sku(rec) == sku_vis) and (
                    not asin_vis or _rec_asin(rec) == asin_vis
                ):
                    record = rec
        if record is None:
            QMessageBox.warning(self, "編集", "該当するデータがありません。")
            return
        dialog = PurchaseRowEditDialog(record, product_widget=self)
        dialog.setModal(False)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        self._purchase_edit_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _=None, d=dialog: self._purchase_edit_dialogs.remove(d) if d in self._purchase_edit_dialogs else None)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _get_value_from_row(self, row: int, keys: List[str]) -> Optional[str]:
        for col in range(self.purchase_table.columnCount()):
            header = self.purchase_table.horizontalHeaderItem(col).text()
            if header in keys:
                item = self.purchase_table.item(row, col)
                if not item:
                    return None
                # SKU・パス・URL列は UserRole のフル値を優先
                if header.upper() == "SKU" or header in _PURCHASE_FILE_PATH_COLUMNS or header in _PURCHASE_URL_COLUMNS:
                    return _purchase_table_cell_full_text(header, item, item.text() if item else "")
                return item.text() if item else None
            for key in keys:
                if header.upper() == key.upper():
                    item = self.purchase_table.item(row, col)
                    if not item:
                        return None
                    if (
                        header.upper() == "SKU"
                        or header in _PURCHASE_FILE_PATH_COLUMNS
                        or header in _PURCHASE_URL_COLUMNS
                    ):
                        return _purchase_table_cell_full_text(header, item, item.text() if item else "")
                    return item.text() if item else None
        return None

    def _infer_warranty_from_comment(self, row: Dict[str, Any]) -> Optional[str]:
        comment = str(row.get("コメント") or row.get("condition_note") or "")
        match = re.search(r"保証.*?(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", comment)
        if match:
            return match.group(1)
        return None

    def _fill_tp_from_comment(self, row: Dict[str, Any]) -> None:
        """
        コメントに「0ta6200」「0tp6200」「1ta6200」「1tp6200」「2ta5800」「2tp5800」「3taXXXX」「3tpXXXX」のような文字列があれば、
        (ta|tp) の次に来る数字を TP0/TP1/TP2/TP3 に設定する（既に値がある場合は上書きしない）。
        """
        comment = str(row.get("コメント") or row.get("comment") or "")
        if not comment:
            return

        # 旧キー(TA*)が残っている場合は TP* へ寄せておく（上書きしない）＋ TA* 側はクリアする
        if (row.get("TA1") or row.get("ta1")) and not (row.get("TP1") or row.get("tp1")):
            v = row.get("TA1") or row.get("ta1")
            row["TP1"] = str(v)
            row["tp1"] = str(v)
        if (row.get("TA2") or row.get("ta2")) and not (row.get("TP2") or row.get("tp2")):
            v = row.get("TA2") or row.get("ta2")
            row["TP2"] = str(v)
            row["tp2"] = str(v)
        # TA* キーは今後使用しないので削除しておく
        for k in ("TA0", "ta0", "TA1", "ta1", "TA2", "ta2", "TA3", "ta3"):
            if k in row:
                row.pop(k, None)

        # 0(ta|tp)数字 → TP0、1(ta|tp)数字 → TP1、2(ta|tp)数字 → TP2（直後の数字を採用）
        m0 = re.search(r"0(?:ta|tp)(\d+)", comment, re.IGNORECASE)
        if m0 and not (row.get("TP0") or row.get("tp0")):
            row["TP0"] = m0.group(1)
            row["tp0"] = m0.group(1)
        m1 = re.search(r"1(?:ta|tp)(\d+)", comment, re.IGNORECASE)
        if m1 and not (row.get("TP1") or row.get("tp1")):
            row["TP1"] = m1.group(1)
            row["tp1"] = m1.group(1)
        m2 = re.search(r"2(?:ta|tp)(\d+)", comment, re.IGNORECASE)
        if m2 and not (row.get("TP2") or row.get("tp2")):
            row["TP2"] = m2.group(1)
            row["tp2"] = m2.group(1)
        m3 = re.search(r"3(?:ta|tp)(\d+)", comment, re.IGNORECASE)
        if m3 and not (row.get("TP3") or row.get("tp3")):
            row["TP3"] = m3.group(1)
            row["tp3"] = m3.group(1)

