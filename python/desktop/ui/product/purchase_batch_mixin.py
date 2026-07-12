#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入DB 一括処理 mixin。"""
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


class PurchaseBatchMixin:
    def batch_update_store_codes_from_master(self):
        """
        仕入DBの「仕入先」カラムを店舗マスタの新店舗コードに置き換えるバッチ処理

        - 現在の仕入DBレコード（purchase_all_records）を対象
        - 各レコードの「仕入先」または「店舗コード」から店舗マスタを参照
        - 店舗マスタの store_code が取得できた場合、その値で「仕入先」を上書き
        - テーブル表示と内部キャッシュ（purchase_all_records）を同期
        """
        if not hasattr(self, "purchase_all_records") or not self.purchase_all_records:
            QMessageBox.information(self, "情報", "仕入DBにデータがありません。")
            return

        self.ensure_purchase_records_fully_augmented()

        reply = QMessageBox.question(
            self,
            "確認",
            "仕入DBの「仕入先」カラムを店舗マスタの新店舗コードで置き換えますか？\n"
            "（対応する店舗が見つかった行のみ変更されます）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        updated = 0
        skipped = 0

        row_count = self.purchase_table.rowCount()

        for row_idx in range(row_count):
            # テーブルの並び順と内部リストの順序はソート操作でズレる可能性があるため、
            # 行インデックスではなくSKUをキーに該当レコードを探す
            record = None
            try:
                sku_item = self.purchase_table.item(row_idx, self.purchase_columns.index("SKU")) if "SKU" in self.purchase_columns else None
            except ValueError:
                sku_item = None

            sku_key = sku_item.text().strip() if sku_item else ""

            if sku_key and hasattr(self, "purchase_all_records"):
                for r in self.purchase_all_records:
                    r_sku = (r.get("SKU") or r.get("sku") or "").strip()
                    if r_sku == sku_key:
                        record = r
                        break

            # SKUで見つからなかった場合はフォールバックとしてインデックスを使用
            if record is None:
                try:
                    record = self.purchase_all_records[row_idx]
                except (AttributeError, IndexError):
                    skipped += 1
                    continue

            # 既存のコード（旧仕入先コード or 旧店舗コード）を取得
            raw_code = (
                record.get("仕入先")
                or record.get("店舗コード")
                or record.get("store_code")
                or ""
            )
            raw_code = str(raw_code).strip()
            if not raw_code:
                skipped += 1
                continue

            # 余分な店舗名などが含まれている場合は、空白の前までをコードとみなす
            if " " in raw_code:
                raw_code = raw_code.split(" ")[0]

            # 店舗マスタから店舗情報を取得（store_code優先、互換性のため仕入れ先コードも許容）
            try:
                store = self.store_db.get_store_by_code(raw_code)
            except Exception:
                store = None

            if not store:
                skipped += 1
                continue

            new_store_code = (store.get("store_code") or "").strip()
            if not new_store_code:
                skipped += 1
                continue

            # 既に同じコードならスキップ
            if new_store_code == record.get("仕入先"):
                skipped += 1
                continue

            # 内部レコードを更新
            record["仕入先"] = new_store_code
            record["store_code"] = new_store_code  # 補助的に保持

            # テーブルセル（「仕入先」列）を更新
            if "仕入先" in self.purchase_columns:
                col_idx = self.purchase_columns.index("仕入先")
                item = self.purchase_table.item(row_idx, col_idx)
                if not item:
                    item = QTableWidgetItem()
                    self.purchase_table.setItem(row_idx, col_idx, item)
                item.setText(new_store_code)

            updated += 1

        # マスターキャッシュも更新（フィルタ時の整合性を保つ）
        try:
            self.purchase_all_records_master = copy.deepcopy(self.purchase_all_records)
        except Exception:
            pass

        # スナップショットとして保存（次回起動時も新店舗コードが反映されるようにする）
        try:
            self.save_purchase_snapshot()
        except Exception as e:
            print(f"店舗コードバッチ後のスナップショット保存エラー: {e}")

        # 結果をラベルとメッセージで表示
        if hasattr(self, "purchase_count_label"):
            self.purchase_count_label.setText(f"保存件数: {len(self.purchase_all_records)}件（コード更新 {updated}件）")

        QMessageBox.information(
            self,
            "完了",
            f"店舗コードバッチ更新が完了しました。\n\n"
            f"更新: {updated}件\n"
            f"スキップ: {skipped}件"
        )

    def _tp_batch_progress_open(self, title: str, label: str, maximum: int) -> QProgressDialog:
        prog = QProgressDialog(self)
        prog.setWindowTitle(title)
        prog.setLabelText(label)
        prog.setRange(0, max(0, int(maximum)))
        prog.setCancelButtonText("キャンセル")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        prog.show()
        QApplication.processEvents()
        return prog

    def _tp_batch_progress_set_save_phase(self, prog: QProgressDialog) -> None:
        prog.setRange(0, 0)
        prog.setLabelText("テーブル更新・スナップショット保存中…")
        prog.setCancelButton(None)
        QApplication.processEvents()

    def autofill_purchase_tp_from_369_rules(self) -> None:
        """
        TP0〜TP3 が空の行に、SKU と 3-6-9 改定ルールの TP 利益保持率で価格を入れる。
        仕入行編集ダイアログと同じ逆算式。既存の TP 値は上書きしない。
        """
        if not getattr(self, "purchase_all_records", None):
            QMessageBox.information(self, "情報", "仕入DBにデータがありません。")
            return

        self.ensure_purchase_records_fully_augmented()

        config = load_369_repricer_config(getattr(self, "api_client", None))
        if not isinstance(config, dict) or not config.get("rule_profiles"):
            QMessageBox.warning(
                self,
                "設定",
                "3-6-9 改定ルール（rule_profiles）を読み込めませんでした。\n"
                "FastAPI を起動してから試すか、config/reprice_rules.json を確認してください。",
            )
            return

        total = len(self.purchase_all_records)
        prog = self._tp_batch_progress_open(
            "TP自動(369)",
            f"0 / {total} 行を処理中…",
            total,
        )
        changed_rows = 0
        db_errors: List[str] = []
        canceled = False
        update_every = max(1, min(50, total // 100 or 1))

        for i, record in enumerate(self.purchase_all_records):
            if prog.wasCanceled():
                canceled = True
                break
            if fill_purchase_record_tp_from_369(record, config):
                changed_rows += 1
                sku = str(record.get("SKU") or record.get("sku") or "").strip()
                if sku and hasattr(self, "purchase_history_db"):
                    try:
                        status = record.get("ステータス") or record.get("status") or "ready"
                        reason = record.get("ステータス理由") or record.get("status_reason") or ""
                        self.purchase_history_db.upsert({
                            "sku": sku,
                            "status": status,
                            "status_reason": reason,
                            "tp0": record.get("tp0") or record.get("TP0") or "",
                            "tp1": record.get("tp1") or record.get("TP1") or "",
                            "tp2": record.get("tp2") or record.get("TP2") or "",
                            "tp3": record.get("tp3") or record.get("TP3") or "",
                            "tp0_source": record.get("tp0_source") or "",
                            "tp1_source": record.get("tp1_source") or "",
                            "tp2_source": record.get("tp2_source") or "",
                            "tp3_source": record.get("tp3_source") or "",
                        })
                    except Exception as e:
                        db_errors.append(f"{sku}: {e}")
            if (i + 1) % update_every == 0 or i + 1 == total:
                prog.setValue(i + 1)
                prog.setLabelText(f"{i + 1} / {total} 行を処理中…")
                QApplication.processEvents()

        if not canceled:
            prog.setValue(total)
        self._tp_batch_progress_set_save_phase(prog)

        try:
            self.purchase_all_records_master = copy.deepcopy(self.purchase_all_records)
        except Exception:
            pass

        self.filter_purchase_records()
        QApplication.processEvents()

        try:
            self.save_purchase_snapshot()
        except Exception as e:
            print(f"TP自動(369) 後のスナップショット保存エラー: {e}")

        prog.close()

        msg = (
            f"処理が完了しました。\n\n"
            f"TP を補完した行: {changed_rows} 件\n"
            f"（空欄の TP のみ。販売予定価格が 0 以下の行はスキップされます）"
        )
        if canceled:
            msg = (
                "キャンセルしました。\n"
                f"その時点まで TP を補完した行: {changed_rows} 件\n\n"
                "表示とスナップショットは、処理したところまで反映済みです。"
            )
        if db_errors:
            msg += "\n\nhirio.db 反映でエラー:\n" + "\n".join(db_errors[:5])
            if len(db_errors) > 5:
                msg += f"\n…他 {len(db_errors) - 5} 件"
        QMessageBox.information(self, "TP自動(369)", msg)

    def autofill_purchase_monthly_ladder_batch(self) -> None:
        """TP未入力・月別OFFの行へ月別運用ルールを一括設定する。"""
        if not getattr(self, "purchase_all_records", None):
            QMessageBox.information(self, "情報", "仕入DBにデータがありません。")
            return

        self.ensure_purchase_records_fully_augmented()

        eligible = sum(1 for r in self.purchase_all_records if is_eligible_for_monthly_auto(r))
        if eligible == 0:
            QMessageBox.information(
                self,
                "月別自動",
                "対象行がありません。\n"
                "（TP0〜TP3 がすべて空・月別OFF・価格改定ON・販売予定価格>0 の行のみ対象）",
            )
            return

        reply = QMessageBox.question(
            self,
            "月別自動",
            f"対象行: {eligible} 件\n\n"
            "priceTrace / FBA状態合わせ / 等間隔値下げ（最終0%）を一括設定し、\n"
            "hirio.db にも保存します。実行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        total = len(self.purchase_all_records)
        prog = self._tp_batch_progress_open(
            "月別自動",
            f"0 / {total} 行を処理中…",
            total,
        )
        changed_rows = 0
        skipped_rows = 0
        failed_rows = 0
        db_errors: List[str] = []
        fail_samples: List[str] = []
        changed_records: List[Dict[str, Any]] = []
        canceled = False
        update_every = max(1, min(50, total // 100 or 1))
        ui_refresh_every = max(1, min(20, update_every))

        for i, record in enumerate(self.purchase_all_records):
            if prog.wasCanceled():
                canceled = True
                break
            if not is_eligible_for_monthly_auto(record):
                skipped_rows += 1
                if (i + 1) % update_every == 0 or i + 1 == total:
                    prog.setValue(i + 1)
                    prog.setLabelText(f"{i + 1} / {total} 行を処理中…")
                    QApplication.processEvents()
                continue

            ok, err = apply_monthly_auto_ladder_to_record(record, final_margin_percent=0.0)
            sku = str(record.get("SKU") or record.get("sku") or "").strip()
            if not ok:
                failed_rows += 1
                if err and err != "対象外" and len(fail_samples) < 5:
                    fail_samples.append(f"{sku or '(SKUなし)'}: {err}")
                if (i + 1) % update_every == 0 or i + 1 == total:
                    prog.setValue(i + 1)
                    QApplication.processEvents()
                continue

            changed_rows += 1
            try:
                self.apply_purchase_row_edit_to_memory(record)
            except Exception:
                pass
            if sku and hasattr(self, "purchase_history_db"):
                try:
                    status = record.get("ステータス") or record.get("status") or "ready"
                    reason = record.get("ステータス理由") or record.get("status_reason") or ""
                    self.purchase_history_db.upsert({
                        "sku": sku,
                        "status": status,
                        "status_reason": reason,
                        "repricing_enabled": 1,
                        "ladder_enabled": 1,
                        "ladder_rules": record.get("ladder_rules") or "",
                        "tp0": "",
                        "tp1": "",
                        "tp2": "",
                        "tp3": "",
                        "sales_channel": record.get("sales_channel")
                        or record.get("販売チャネル")
                        or "Amazon",
                    })
                except Exception as e:
                    db_errors.append(f"{sku}: {e}")

            changed_records.append(record)
            if changed_rows % ui_refresh_every == 0:
                self._refresh_purchase_repricing_table_cells_for_record(record)
                QApplication.processEvents()

            if (i + 1) % update_every == 0 or i + 1 == total:
                prog.setValue(i + 1)
                prog.setLabelText(
                    f"{i + 1} / {total} 行を処理中…（月別・改定価格を反映: {changed_rows} 件）"
                )
                QApplication.processEvents()

        if not canceled:
            prog.setValue(total)
        self._tp_batch_progress_set_save_phase(prog)

        try:
            self.purchase_all_records_master = copy.deepcopy(self.purchase_all_records)
        except Exception:
            pass

        for rec in changed_records:
            try:
                self._refresh_purchase_repricing_table_cells_for_record(rec)
            except Exception:
                pass
        if changed_records:
            self.purchase_table.viewport().update()
            QApplication.processEvents()

        self.filter_purchase_records()
        QApplication.processEvents()

        try:
            self.save_purchase_snapshot()
        except Exception as e:
            print(f"月別自動 後のスナップショット保存エラー: {e}")

        prog.close()

        msg = (
            f"処理が完了しました。\n\n"
            f"月別運用を設定した行: {changed_rows} 件\n"
            f"スキップ（対象外）: {skipped_rows} 件\n"
            f"失敗: {failed_rows} 件"
        )
        if canceled:
            msg = (
                "キャンセルしました。\n"
                f"その時点まで設定した行: {changed_rows} 件\n"
                f"スキップ: {skipped_rows} 件 / 失敗: {failed_rows} 件"
            )
        if fail_samples:
            msg += "\n\n失敗例:\n" + "\n".join(fail_samples)
        if db_errors:
            msg += "\n\nhirio.db 反映でエラー:\n" + "\n".join(db_errors[:5])
            if len(db_errors) > 5:
                msg += f"\n…他 {len(db_errors) - 5} 件"
        QMessageBox.information(self, "月別自動", msg)

    def clear_all_purchase_tp_for_dev(self) -> None:
        """【開発用】全仕入レコードの TP0〜TP3 を空にする。"""
        if not getattr(self, "purchase_all_records", None):
            QMessageBox.information(self, "情報", "仕入DBにデータがありません。")
            return

        reply = QMessageBox.question(
            self,
            "確認（開発用）",
            "仕入DBの全行について、TP0〜TP3 をすべて空にしますか？\n"
            "（スナップショット保存まで行います。元に戻せません）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.ensure_purchase_records_fully_augmented()

        tp_keys = (
            "TP0", "tp0",
            "TP1", "tp1", "TA1", "ta1",
            "TP2", "tp2", "TA2", "ta2",
            "TP3", "tp3",
        )
        total = len(self.purchase_all_records)
        prog = self._tp_batch_progress_open(
            "TPクリア(開発)",
            f"0 / {total} 行を処理中…",
            total,
        )
        cleared_rows = 0
        db_errors: List[str] = []
        canceled = False
        update_every = max(1, min(50, total // 100 or 1))

        for i, record in enumerate(self.purchase_all_records):
            if prog.wasCanceled():
                canceled = True
                break
            had_any = any(
                str(record.get(k) or "").strip() and str(record.get(k) or "").strip() != "-"
                for k in tp_keys
            )
            for k in tp_keys:
                record[k] = ""
            if had_any:
                cleared_rows += 1

            sku = str(record.get("SKU") or record.get("sku") or "").strip()
            if sku and hasattr(self, "purchase_history_db"):
                try:
                    status = record.get("ステータス") or record.get("status") or "ready"
                    reason = record.get("ステータス理由") or record.get("status_reason") or ""
                    self.purchase_history_db.upsert({
                        "sku": sku,
                        "status": status,
                        "status_reason": reason,
                        "tp0": "",
                        "tp1": "",
                        "tp2": "",
                        "tp3": "",
                    })
                except Exception as e:
                    db_errors.append(f"{sku}: {e}")
            if (i + 1) % update_every == 0 or i + 1 == total:
                prog.setValue(i + 1)
                prog.setLabelText(f"{i + 1} / {total} 行を処理中…")
                QApplication.processEvents()

        if not canceled:
            prog.setValue(total)
        self._tp_batch_progress_set_save_phase(prog)

        try:
            self.purchase_all_records_master = copy.deepcopy(self.purchase_all_records)
        except Exception:
            pass

        self.filter_purchase_records()
        QApplication.processEvents()

        try:
            self.save_purchase_snapshot()
        except Exception as e:
            print(f"TPクリア(開発) 後のスナップショット保存エラー: {e}")

        prog.close()

        msg = f"TP を空にした行: {cleared_rows} 件（全 {len(self.purchase_all_records)} 行を処理）"
        if canceled:
            msg = (
                "キャンセルしました。\n"
                f"TP を空にした行（その時点まで）: {cleared_rows} 件\n\n"
                "表示とスナップショットは、処理したところまで反映済みです。"
            )
        if db_errors:
            msg += "\n\nhirio.db 反映でエラー:\n" + "\n".join(db_errors[:5])
            if len(db_errors) > 5:
                msg += f"\n…他 {len(db_errors) - 5} 件"
        QMessageBox.information(self, "TPクリア(開発)", msg)

    def save_purchase_from_table(self):
        """
        仕入DBテーブルの現在の状態を内部レコードに反映してスナップショット保存する

        - 手動編集したセルの内容も含めて保存したい場合に使用
        - テーブル上に表示されている行をそのまま「正」とみなし、
          purchase_all_records / master / purchase_records を丸ごと置き換える
        """
        if not hasattr(self, "purchase_columns") or not self.purchase_columns:
            QMessageBox.information(self, "情報", "保存する仕入DBデータがありません。")
            return

        self._purchase_incremental_load_all_rows_sync()
        self.ensure_purchase_records_fully_augmented()

        # テーブルの全行を走査して、現在表示されている内容から新しいレコードリストを構築する
        row_count = self.purchase_table.rowCount()
        col_count = self.purchase_table.columnCount()

        # 既存レコードをキー（SKU or 仕入れ日+ASIN/JAN+商品名+店舗コード）で引けるようにしておく
        def _make_key(rec: Dict[str, Any]) -> str:
            sku = str(rec.get("SKU") or rec.get("sku") or "").strip()
            if sku:
                return f"SKU:{sku}"
            purchase_date = str(rec.get("仕入れ日") or rec.get("purchase_date") or "").strip()
            asin = str(rec.get("ASIN") or rec.get("asin") or "").strip()
            jan = str(rec.get("JAN") or rec.get("jan") or "").strip()
            asin_or_jan = asin or jan
            title = str(rec.get("商品名") or rec.get("title") or rec.get("product_name") or "").strip()
            store_code = str(
                rec.get("仕入先")
                or rec.get("店舗コード")
                or rec.get("store_code")
                or ""
            ).strip()
            return f"{purchase_date}|{asin_or_jan}|{store_code}|{title}"

        existing_index: Dict[str, Dict[str, Any]] = {}
        if hasattr(self, "purchase_all_records") and self.purchase_all_records:
            for rec in self.purchase_all_records:
                key = _make_key(rec)
                if key:
                    existing_index[key] = rec

        new_all_records: List[Dict[str, Any]] = []
        row_ids_by_index = getattr(self, "_purchase_table_row_ids_by_index", None) or []
        row_map = getattr(self, "_purchase_row_map", None) or {}

        for row in range(row_count):
            # 行IDマップがあればフルレコードをベースにする（表示が空のセルでもデータを失わない）
            base_rec: Dict[str, Any] = {}
            row_id = row_ids_by_index[row] if row < len(row_ids_by_index) else None
            if row_id is not None and row_id in row_map:
                base_rec = copy.deepcopy(row_map[row_id])

            # テーブルの1行分の値を辞書にまとめる
            row_data: Dict[str, Any] = {}
            receipt_image_path = None  # レシート画像パスを保持
            
            for col in range(col_count):
                header = self.purchase_columns[col] if col < len(self.purchase_columns) else None
                if not header:
                    continue
                if header == "経過日数":
                    continue
                cell_item = self.purchase_table.item(row, col)
                value = cell_item.text() if cell_item else ""
                # SKU・商品名はUserRoleにフル値を保持している場合はそれを優先（表示が...で切れていても保存はフルで）
                if header == "SKU" and cell_item:
                    full = cell_item.data(Qt.UserRole)
                    if full is not None and str(full).strip():
                        value = str(full).strip()
                elif header == "商品名" and cell_item:
                    full = cell_item.data(Qt.UserRole)
                    if full is not None and str(full).strip():
                        value = str(full).strip()
                elif header == "レシート画像" and cell_item:
                    file_path = cell_item.data(Qt.UserRole)
                    if file_path:
                        from pathlib import Path
                        file_path_obj = Path(str(file_path))
                        receipt_image_path = (
                            str(file_path_obj.resolve())
                            if file_path_obj.exists()
                            else str(file_path)
                        )
                        value = file_path_obj.name or str(file_path)
                elif header in _PURCHASE_FILE_PATH_COLUMNS and cell_item:
                    full = cell_item.data(Qt.UserRole)
                    if full is not None and str(full).strip():
                        value = str(full).strip()
                elif header in _PURCHASE_URL_COLUMNS and cell_item:
                    full = cell_item.data(Qt.UserRole)
                    if full is not None and str(full).strip():
                        value = str(full).strip()
                row_data[header] = value

            if not base_rec:
                key = _make_key(row_data)
                base_rec = existing_index.get(key, {}).copy() if key in existing_index else {}

            # 既存レコードにテーブルの値を上書き
            for k, v in row_data.items():
                base_rec[k] = v

            if receipt_image_path:
                base_rec["レシート画像パス"] = receipt_image_path

            sku_val = str(base_rec.get("SKU") or base_rec.get("sku") or "").strip()
            if not sku_val:
                continue

            new_all_records.append(base_rec)

        # テーブルが空の場合は全削除
        self.purchase_all_records = new_all_records
        self.purchase_all_records_master = copy.deepcopy(new_all_records)
        self.purchase_records = copy.deepcopy(new_all_records)

        # スナップショット保存
        try:
            self.save_purchase_snapshot()
            QMessageBox.information(self, "保存完了", "仕入DBの現在の内容を保存しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"仕入DBの保存に失敗しました:\n{e}")

