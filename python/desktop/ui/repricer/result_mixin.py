
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QTextEdit, QGroupBox, QSplitter, QApplication,
    QMessageBox, QFrame, QMenu, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices

try:
    from ui.utils.draggable_file_icon import DraggableFileIconWidget
except ImportError:
    from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget  # type: ignore

try:
    from ui.utils.browser_front_scheduler import schedule_bring_browser_to_front
except ImportError:
    from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front  # type: ignore

import pandas as pd
from pathlib import Path
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from utils.error_handler import ErrorHandler, validate_csv_file, safe_execute
from utils.settings_helper import get_pricetar_repricing_url
try:
    from desktop.services.keepa_service import KeepaService
except ImportError:
    from services.keepa_service import KeepaService  # type: ignore

from .support import (
    NumericTableWidgetItem,
    RepricerWorker,
    _PRICETAR_BROWSER_TITLE_KEYWORDS,
    _REPRICER_ACTION_TO_PIPELINE_STEP,
    _REPRICER_WORKFLOW_PIPELINE_SEGMENTS,
    _REPRICER_WORKFLOW_PIPELINE_SEP,
    _format_repricer_status_prefix_html,
    _format_repricer_workflow_pipeline_html,
)


class RepricerResultMixin:
    """価格改定ウィジェットの分割ミックスイン。"""

    def setup_result_area_full_width(self):
        """価格改定結果エリアの設定（全幅）"""
        result_group = QGroupBox()
        result_layout = QVBoxLayout(result_group)
    
        # ヘッダー（「価格改定結果 ＋／－」ボタン）
        header_layout = QHBoxLayout()
        self.result_toggle_btn = QPushButton("価格改定結果 －")
        self.result_toggle_btn.setFlat(True)
        self.result_toggle_btn.clicked.connect(self.toggle_result_area)
        header_layout.addWidget(self.result_toggle_btn)
        header_layout.addStretch()
        result_layout.addLayout(header_layout)

        # 日数フィルタボタン行（価格改定結果用）
        result_filter_layout = QHBoxLayout()
        self.result_filter_90_btn = QPushButton("90")
        self.result_filter_180_btn = QPushButton("180")
        self.result_filter_270_btn = QPushButton("270")
        self.result_filter_340_btn = QPushButton("340")
        self.result_filter_clear_btn = QPushButton("クリア")
        self.result_filter_90_btn.clicked.connect(lambda _=False, d=90: self.apply_result_days_filter(d))
        self.result_filter_180_btn.clicked.connect(lambda _=False, d=180: self.apply_result_days_filter(d))
        self.result_filter_270_btn.clicked.connect(lambda _=False, d=270: self.apply_result_days_filter(d))
        self.result_filter_340_btn.clicked.connect(lambda _=False, d=340: self.apply_result_days_filter(d))
        self.result_filter_clear_btn.clicked.connect(self.clear_result_days_filter)
        for btn in [
            self.result_filter_90_btn,
            self.result_filter_180_btn,
            self.result_filter_270_btn,
            self.result_filter_340_btn,
            self.result_filter_clear_btn,
        ]:
            result_filter_layout.addWidget(btn)
        result_filter_layout.addStretch()
        result_layout.addLayout(result_filter_layout)
        self._update_result_days_filter_styles()
    
        # 結果テーブル
        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.horizontalHeader().setSectionsClickable(True)
        self.result_table.horizontalHeader().setSortIndicatorShown(True)
        self.result_table.setMinimumHeight(200)  # 適度な高さを設定
        # 選択時にQSSのselected色で行背景が上書きされるのを防ぐ
        # （TP下限の黄色ハイライトを常に視認できるようにする）
        self.result_table.setStyleSheet(
            "QTableWidget::item:selected {"
            "background-color: transparent;"
            "}"
        )
    
        # 大量データ対応の最適化
        self.result_table.setSortingEnabled(True)  # ソート機能を有効化
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)  # 行選択
    
        # パフォーマンス向上のための設定
        self.result_table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.result_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
    
        # 選択変更時の自動スクロール機能
        self.result_table.itemSelectionChanged.connect(self.on_result_selection_changed)
        # 行ダブルクリックで仕入行編集（Keepa）ダイアログを開く
        self.result_table.cellDoubleClicked.connect(self.on_result_table_double_clicked)
    
        result_layout.addWidget(self.result_table)
    
        self.layout().addWidget(result_group)

    def toggle_result_area(self):
        """価格改定結果エリアの折りたたみ切り替え"""
        self.result_collapsed = not self.result_collapsed
        self.result_table.setVisible(not self.result_collapsed)
        self.result_toggle_btn.setText("価格改定結果 ＋" if self.result_collapsed else "価格改定結果 －")

    def on_result_selection_changed(self):
        """価格改定結果テーブルの選択変更時の処理"""
        try:
            # NOTE:
            # 過去は選択行の背景色をここで上書きしていたが、
            # 価格改定結果の行色（TP下限の黄色・上昇/下降色）を潰してしまうため
            # 背景変更は行わない。
            pass
        except Exception as e:
            print(f"結果選択変更処理エラー: {e}")

    def get_manual_export_price(self, sku: str) -> Optional[int]:
        """プライスター返却CSV用の手動 price 上書き（未設定なら None）。"""
        key = self.clean_excel_formula(str(sku or "")).strip()
        if not key:
            return None
        val = self._manual_export_prices.get(key)
        return int(val) if val is not None else None

    def set_manual_export_price(self, sku: str, price: int) -> None:
        key = self.clean_excel_formula(str(sku or "")).strip()
        if not key:
            return
        self._manual_export_prices[key] = int(price)

    def clear_manual_export_price(self, sku: str) -> None:
        key = self.clean_excel_formula(str(sku or "")).strip()
        if key:
            self._manual_export_prices.pop(key, None)

    def _akaji_takane_from_rule_percents(
        self, price: int, akaji_drop_percent: Any, takane_rise_percent: Any
    ) -> tuple[int, int]:
        try:
            akaji_pct = int(akaji_drop_percent if akaji_drop_percent is not None else 1)
        except (TypeError, ValueError):
            akaji_pct = 1
        akaji_pct = min(10, max(1, akaji_pct))
        try:
            takane_pct = int(takane_rise_percent if takane_rise_percent is not None else 0)
        except (TypeError, ValueError):
            takane_pct = 0
        takane_pct = min(10, max(0, takane_pct))
        akaji = max(0, round(price * (1.0 - akaji_pct / 100.0)))
        takane = max(price, round(price * (1.0 + takane_pct / 100.0)))
        return akaji, takane

    def _apply_manual_overrides_to_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """手動送付価格をプレビュー/実行結果に反映（改定価格・akaji・takane・理由）。"""
        if not result or not self._manual_export_prices:
            return result
        items = result.get("items")
        if not items:
            return result
        for it in items:
            sku = self.clean_excel_formula(str(it.get("sku", ""))).strip()
            if not sku or sku not in self._manual_export_prices:
                continue
            mp = int(self._manual_export_prices[sku])
            it["new_price"] = mp
            akaji, takane = self._akaji_takane_from_rule_percents(
                mp,
                it.get("akaji_drop_percent"),
                it.get("takane_rise_percent"),
            )
            it["akaji"] = akaji
            it["takane"] = takane
            it["reason"] = self._MANUAL_OVERRIDE_REASON
            it["is_tp_floor_or_below"] = False
            it["tp_reach_status"] = ""
        return result

    def refresh_manual_override_display(self) -> None:
        """プレビュー済みの結果表に手動上書きを即時反映する。"""
        if not self.repricing_result:
            return
        self._apply_manual_overrides_to_result(self.repricing_result)
        self.update_result_table(self.repricing_result)

    def _repricer_csv_snapshot_for_sku(self, sku: str, asin: str) -> Optional[Dict[str, Any]]:
        """3-6-9モードのプレビュー/実行結果から、日数・在庫CSV由来の現在価格・profit を取得。"""
        if str(self.mode) != "369" or not self.repricing_result:
            return None
        items = self.repricing_result.get("items") or []
        for it in items:
            if str(it.get("sku", "")).strip() != sku:
                continue
            it_asin = str(it.get("asin", "")).strip()
            if asin and it_asin and it_asin != asin:
                continue
            try:
                p = float(it.get("price", 0) or 0)
            except (TypeError, ValueError):
                p = 0.0
            raw_profit = it.get("csv_profit", it.get("profit", 0))
            try:
                prof = float(raw_profit or 0)
            except (TypeError, ValueError):
                prof = 0.0
            days_val: Optional[int] = None
            raw_days = it.get("days")
            if raw_days is not None and str(raw_days).strip() != "":
                try:
                    days_val = int(float(raw_days))
                except (TypeError, ValueError):
                    days_val = None
            csv_fallback = self._preview_csv_snapshot_for_sku(sku, asin)
            if csv_fallback:
                if p <= 0:
                    p = float(csv_fallback.get("price") or 0)
                if prof == 0:
                    prof = float(csv_fallback.get("profit") or 0)
                if days_val is None:
                    days_val = csv_fallback.get("days")
            manual_p = self.get_manual_export_price(sku)
            return {
                "price": p,
                "profit": prof,
                "days": days_val,
                "manual_export_price": manual_p,
                "new_price": manual_p if manual_p is not None else it.get("new_price"),
                "action": it.get("action"),
                "reason": (
                    self._MANUAL_OVERRIDE_REASON
                    if manual_p is not None
                    else it.get("reason")
                ),
                "tp_target": it.get("tp_target"),
                "tp_floor": it.get("tp_floor"),
                "rule_action": it.get("rule_action"),
                "priceTraceChangeDisplay": it.get("priceTraceChangeDisplay")
                or it.get("priceTraceChange"),
                "tp_reach_status": it.get("tp_reach_status"),
                "keepa_ref_price": it.get("keepa_ref_price"),
            }
        return None

    def _preview_csv_snapshot_for_sku(self, sku: str, asin: str) -> Optional[Dict[str, Any]]:
        """読み込み済み在庫CSVから、現在価格・現在見込み利益・日数を補完する。"""
        df = getattr(self, "preview_df", None)
        if df is None or getattr(df, "empty", True):
            return None
        for pos, (_, row) in enumerate(df.iterrows()):
            row_sku = self.clean_excel_formula(str(row.get("SKU", "") or "")).strip()
            if row_sku != sku:
                continue
            row_asin = self.clean_excel_formula(str(row.get("ASIN", "") or "")).strip()
            if asin and row_asin and row_asin != asin:
                continue
            price = self._number_from_csv_value(row.get("price")) or 0.0
            profit = self._csv_profit_from_preview_row(row)
            days_val = None
            preview_days = getattr(self, "preview_days", None)
            if preview_days is not None and pos < len(preview_days):
                days_val = preview_days[pos]
            return {"price": price, "profit": profit, "days": days_val}
        return None

    def _csv_profit_from_preview_row(self, row: Any) -> float:
        """profit列が空でも、現在価格と原価から現在見込み利益を計算する。"""
        profit = self._number_from_csv_value(row.get("profit"))
        if profit not in (None, 0):
            return float(profit)
        price = self._number_from_csv_value(row.get("price"))
        cost = self._number_from_csv_value(row.get("cost"))
        if price is None or cost is None:
            return float(profit or 0.0)
        amazon_fee = self._number_from_csv_value(row.get("amazon-fee")) or 0.0
        shipping_price = self._number_from_csv_value(row.get("shipping-price")) or 0.0
        return float(price - cost - amazon_fee - shipping_price)

    def _number_from_csv_value(self, value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            text = self.clean_excel_formula(str(value)).replace(",", "").strip()
            if not text or text.lower() in ("nan", "none"):
                return None
            return float(text)
        except (TypeError, ValueError):
            return None

    def _get_purchase_db(self):
        pw = self.product_widget
        if pw is not None and hasattr(pw, "purchase_history_db"):
            return pw.purchase_history_db
        try:
            from database.purchase_db import PurchaseDatabase
        except ImportError:
            from desktop.database.purchase_db import PurchaseDatabase  # type: ignore
        return PurchaseDatabase()

    def _load_csv_dataframe_for_missing(self) -> Optional[pd.DataFrame]:
        if self.preview_df is not None and not self.preview_df.empty:
            return self.preview_df
        if not self.csv_path:
            return None
        try:
            from utils.csv_io import csv_io
            return csv_io.read_csv(self.csv_path)
        except Exception:
            return None

    def _get_purchase_display_records(self) -> List[Dict[str, Any]]:
        """仕入DBタブの表示用レコード（スナップショット）を取得。"""
        pw = self.product_widget
        if pw is not None:
            try:
                if hasattr(pw, "ensure_initial_data_loaded"):
                    pw.ensure_initial_data_loaded()
            except Exception:
                pass
            master = getattr(pw, "purchase_all_records_master", None) or getattr(
                pw, "purchase_all_records", None
            )
            if master:
                return list(master)
            purchase_snapshot_db = getattr(pw, "purchase_db", None)
            if purchase_snapshot_db is not None:
                try:
                    snapshots = purchase_snapshot_db.list_snapshots()
                    if snapshots:
                        snap = purchase_snapshot_db.get_snapshot(snapshots[0]["id"])
                        if snap and snap.get("data"):
                            return list(snap["data"])
                except Exception:
                    pass
        try:
            from desktop.database.product_purchase_db import ProductPurchaseDatabase
        except ImportError:
            from database.product_purchase_db import ProductPurchaseDatabase  # type: ignore
        try:
            pdb = ProductPurchaseDatabase()
            snapshots = pdb.list_snapshots()
            if snapshots:
                snap = pdb.get_snapshot(snapshots[0]["id"])
                if snap and snap.get("data"):
                    return list(snap["data"])
        except Exception:
            pass
        return []

    def show_missing_inventory_skus_dialog(self) -> None:
        """在庫CSVにあって仕入DBに無い、または ASIN 未入力の SKU を一覧表示。"""
        df = self._load_csv_dataframe_for_missing()
        if df is None or df.empty:
            QMessageBox.information(self, "仕入DB未登録SKU", "先に在庫CSVを読み込んでください。")
            return
        try:
            from desktop.services.purchase_inventory_only import (
                extract_rows_not_in_purchase_db,
                save_pending_missing_list,
            )
        except ImportError:
            from services.purchase_inventory_only import (  # type: ignore
                extract_rows_not_in_purchase_db,
                save_pending_missing_list,
            )
        purchase_db = self._get_purchase_db()
        display_records = self._get_purchase_display_records()
        missing = extract_rows_not_in_purchase_db(
            df, purchase_db, display_records=display_records
        )
        if not missing:
            QMessageBox.information(
                self,
                "仕入DB未登録SKU",
                "登録・上書き対象のSKUはありません。\n"
                "（仕入DBに SKU があり ASIN も入力済みの行は対象外です）",
            )
            return
        save_pending_missing_list(missing, csv_path=self.csv_path or "")
        try:
            from ui.inventory_only_skus_dialog import InventoryOnlySkusDialog
        except ImportError:
            from desktop.ui.inventory_only_skus_dialog import InventoryOnlySkusDialog  # type: ignore
        dlg = InventoryOnlySkusDialog(
            missing,
            purchase_db=purchase_db,
            product_widget=self.product_widget,
            repricer_widget=self,
            csv_path=self.csv_path or "",
            parent=self,
        )
        dlg.exec()

    def open_purchase_row_edit_for_sku(
        self,
        sku: str,
        *,
        asin: str = "",
        title: str = "",
        csv_price: Any = None,
        new_price: str = "",
    ) -> None:
        """SKU指定で仕入行編集（Keepa）を開く。無ければ在庫専用登録を案内。"""
        sku = str(sku or "").strip()
        if not sku:
            return
        current_price = str(csv_price or "").strip()
        pw = self.product_widget
        if pw is not None and hasattr(pw, "ensure_initial_data_loaded"):
            try:
                pw.ensure_initial_data_loaded()
            except Exception:
                pass

        record = None
        if pw is not None:
            records = getattr(pw, "purchase_all_records", None) or getattr(pw, "purchase_records", None) or []
            for rec in records:
                rec_sku = str(rec.get("SKU") or rec.get("sku") or "").strip()
                rec_asin = str(rec.get("ASIN") or rec.get("asin") or "").strip()
                if rec_sku == sku and (not asin or not rec_asin or rec_asin == asin):
                    record = rec
                    break
            if record is None:
                for rec in records:
                    if str(rec.get("SKU") or rec.get("sku") or "").strip() == sku:
                        record = rec
                        break

        if record is None and pw is not None and hasattr(pw, "purchase_history_db"):
            db_rec = pw.purchase_history_db.get_by_sku(sku)
            if db_rec:
                try:
                    from desktop.services.purchase_inventory_only import purchase_record_from_db_row
                except ImportError:
                    from services.purchase_inventory_only import purchase_record_from_db_row  # type: ignore
                record = purchase_record_from_db_row(db_rec)
                if asin:
                    record["ASIN"] = asin
                if title:
                    record["商品名"] = title

        if record is None and pw is not None and hasattr(pw, "db"):
            try:
                product_rec = pw.db.get_by_sku(sku)
            except Exception:
                product_rec = None
            if product_rec:
                record = {"SKU": sku, "sku": sku}
                record["ASIN"] = asin or str(product_rec.get("asin") or "")
                record["商品名"] = title or str(product_rec.get("product_name") or "")

        if record is None:
            reply = QMessageBox.question(
                self,
                "仕入行の編集",
                f"SKU {sku} は仕入DBにありません。\n"
                "「在庫専用」として登録してから月別運用を設定しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return
            try:
                from desktop.services.purchase_inventory_only import register_inventory_only_row
            except ImportError:
                from services.purchase_inventory_only import register_inventory_only_row  # type: ignore
            row = {"SKU": sku, "sku": sku, "ASIN": asin, "商品名": title, "price": current_price}
            purchase_db = self._get_purchase_db()
            display = register_inventory_only_row(row, purchase_db, product_widget=pw)
            record = display
            if pw is not None and hasattr(pw, "save_purchase_snapshot"):
                try:
                    pw.save_purchase_snapshot()
                except Exception:
                    pass

        if record is None:
            QMessageBox.information(self, "仕入行の編集", f"SKU {sku} の登録に失敗しました。")
            return

        record.setdefault("SKU", sku)
        record.setdefault("ASIN", asin or record.get("ASIN") or "")
        if not record.get("商品名"):
            record["商品名"] = title
        if not record.get("コンディション"):
            record["コンディション"] = ""
        if not record.get("販売予定価格"):
            record["販売予定価格"] = current_price or new_price or 0
        if "見込み利益" not in record or record.get("見込み利益") in (None, ""):
            record["見込み利益"] = 0
        record.setdefault("expected_price", record.get("販売予定価格", 0))
        record.setdefault("expected_profit", record.get("見込み利益", 0))

        csv_snap = self._repricer_csv_snapshot_for_sku(sku, asin)
        if csv_snap is None and current_price:
            try:
                csv_snap = {"price": float(str(current_price).replace(",", "")), "profit": 0, "days": None}
            except (TypeError, ValueError):
                csv_snap = None

        try:
            from ui.purchase_row_edit_dialog import PurchaseRowEditDialog
        except ImportError:
            from desktop.ui.purchase_row_edit_dialog import PurchaseRowEditDialog
        dialog = PurchaseRowEditDialog(
            record,
            product_widget=pw,
            csv_inventory_snapshot=csv_snap or {},
            repricer_widget=self,
        )
        dialog.setModal(False)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        self._purchase_edit_dialogs.append(dialog)
        dialog.destroyed.connect(
            lambda _=None, d=dialog: self._purchase_edit_dialogs.remove(d) if d in self._purchase_edit_dialogs else None
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def on_result_table_double_clicked(self, row: int, col: int):
        """価格改定結果行のダブルクリックで仕入行編集ダイアログを開く"""
        try:
            sku_item = self.result_table.item(row, 0)
            asin_item = self.result_table.item(row, 1)
            title_item = self.result_table.item(row, 2)
            current_price_item = self.result_table.item(row, 7)
            new_price_item = self.result_table.item(row, 8)
            sku = sku_item.text().strip() if sku_item else ""
            if not sku:
                return
            self.open_purchase_row_edit_for_sku(
                sku,
                asin=asin_item.text().strip() if asin_item else "",
                title=title_item.text().strip() if title_item else "",
                csv_price=current_price_item.text().strip() if current_price_item else "",
                new_price=new_price_item.text().strip() if new_price_item else "",
            )
        except Exception as e:
            QMessageBox.warning(self, "仕入行の編集", f"ダイアログ表示に失敗しました:\n{e}")

    def apply_result_days_filter(self, threshold: int):
        """価格改定結果の日数フィルタを適用"""
        if not self.repricing_result or "items" not in self.repricing_result:
            return
        self.active_result_days_filter = threshold
        self._update_result_days_filter_styles()
        self.update_result_table(self.repricing_result)

    def clear_result_days_filter(self):
        """価格改定結果の日数フィルタを解除"""
        self.active_result_days_filter = None
        self._update_result_days_filter_styles()
        if self.repricing_result and "items" in self.repricing_result:
            self.update_result_table(self.repricing_result)

    def _update_result_days_filter_styles(self):
        """価格改定結果用の日数フィルタボタンのスタイル更新"""
        base_style = ""
        active_style = (
            "QPushButton {"
            "  background-color: #28a745;"
            "  color: white;"
            "  font-weight: bold;"
            "}"
        )
        button_map = {
            90: getattr(self, "result_filter_90_btn", None),
            180: getattr(self, "result_filter_180_btn", None),
            270: getattr(self, "result_filter_270_btn", None),
            340: getattr(self, "result_filter_340_btn", None),
        }
        for days, btn in button_map.items():
            if btn is None:
                continue
            if self.active_result_days_filter == days:
                btn.setStyleSheet(active_style)
            else:
                btn.setStyleSheet(base_style)
        if hasattr(self, "result_filter_clear_btn"):
            self.result_filter_clear_btn.setStyleSheet(base_style)

    def _format_trace_change(self, price_trace_change):
        """Trace変更の日本語化
    
        マッピング:
        0 = 維持
        1 = FBA状態合わせ
        2 = 状態合わせ
        3 = FBA最安値
        4 = 最安値
        5 = カート価格
        """
        trace_value = int(price_trace_change) if price_trace_change else 0
    
        if trace_value == 0:
            return "維持"
        elif trace_value == 1:
            return "FBA状態合わせ"
        elif trace_value == 2:
            return "状態合わせ"
        elif trace_value == 3:
            return "FBA最安値"
        elif trace_value == 4:
            return "最安値"
        elif trace_value == 5:
            return "カート価格"
        else:
            return f"不明 ({trace_value})"

    def execute_repricing(self):
        """価格改定の実行"""
        if not self.csv_path:
            QMessageBox.warning(self, "エラー", "CSVファイルを選択してください")
            return
        
        # 確認ダイアログ
        reply = QMessageBox.question(
            self, 
            "価格改定実行確認", 
            "価格改定を実行しますか？\n※元のCSVファイルは変更されません。結果は別途保存できます。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
    
        if reply != QMessageBox.Yes:
            return
        
        # 進捗バーの表示
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.execute_btn.setEnabled(False)
    
        # ワーカースレッドの作成と実行（実行モード）
        self.worker = RepricerWorker(self.csv_path, self.api_client, is_preview=False, mode=self.mode)
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.result_ready.connect(self.on_repricing_completed)
        self.worker.error_occurred.connect(self.on_repricing_error)
        self.worker.start()

    def on_repricing_completed(self, result):
        """価格改定完了時の処理"""
        result = self._apply_manual_overrides_to_result(result)
        self.repricing_result = result
        self.progress_bar.setVisible(False)
        self.execute_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.keepa_fetch_btn.setEnabled(True)

        try:
            from services.repricer_execution_store import record_repricer_execution

            record_repricer_execution(self.mode)
            self.repricing_executed.emit(self.mode)
        except Exception:
            pass
    
        # 結果テーブルの更新
        self.update_result_table(result)
    
        # 自動保存は行わず、手動保存のみとする
        auto_save_message = "\n自動保存は行っていません。「結果をCSV保存」から手動保存してください。"
    
        QMessageBox.information(
            self, 
            "価格改定完了", 
            f"価格改定が完了しました\n更新行数: {result['summary']['updated_rows']}{auto_save_message}"
        )

    def on_repricing_error(self, error_message):
        """価格改定エラー時の処理"""
        self.progress_bar.setVisible(False)
        self.execute_btn.setEnabled(True)
    
        QMessageBox.critical(self, "エラー", f"価格改定に失敗しました:\n{error_message}")

    def update_result_table(self, result):
        """結果テーブルの更新"""
        items = result['items']
        if self.active_result_days_filter is not None:
            threshold = int(self.active_result_days_filter)
            filtered_items = []
            for it in items:
                try:
                    d = int(it.get("days", -1))
                except (TypeError, ValueError):
                    d = -1
                if d >= threshold:
                    filtered_items.append(it)
            items = filtered_items
    
        # ソート機能を一時的に無効化（データ投入中はソートしない）
        self.result_table.setSortingEnabled(False)
    
        # テーブルの設定（必要な列のみ）
        self.result_table.setRowCount(len(items))
        columns = ['SKU', 'ASIN', 'Title', '日数', 'TP下限', 'アクション', '理由', '現在価格', '改定価格', 'akaji', 'takane', 'Trace変更', 'Keepa価格(参考)']
        self.result_table.setColumnCount(len(columns))
        self.result_table.setHorizontalHeaderLabels(columns)
        total_columns = len(columns)
    
        # データの設定
        for i, item in enumerate(items):
            # 既存APIレスポンスのキー名に合わせて取得（型変換を追加）
            sku = str(item.get('sku', ''))
            asin = str(item.get('asin', ''))
            title = str(item.get('title', ''))
            days = int(item.get('days', 0)) if item.get('days') is not None else 0
            action = str(item.get('action', ''))
            reason = str(item.get('reason', ''))
            price = float(item.get('price', 0)) if item.get('price') is not None else 0
            new_price = float(item.get('new_price', 0)) if item.get('new_price') is not None else 0
            akaji_value = item.get('akaji', '')
            takane_value = item.get('takane', '')
            tp_floor_raw = item.get('tp_floor', None)
            try:
                tp_floor = float(tp_floor_raw) if tp_floor_raw not in (None, "") else None
            except (TypeError, ValueError):
                tp_floor = None
            is_tp_floor_or_below = bool(item.get('is_tp_floor_or_below', False))
            tp_reach_status = str(item.get('tp_reach_status', '') or '')
            # priceTraceChangeDisplayを優先的に使用（表示用文字列）
            trace_change_text = item.get('priceTraceChangeDisplay', None)
        
            # priceTraceChangeDisplayがない場合は、従来の処理でフォールバック
            if trace_change_text is None:
                # priceTraceChangeの安全な型変換
                price_trace_change = 0
                try:
                    trace_value = item.get('priceTraceChange', item.get('price_trace_change', 0))
                    if trace_value is not None and str(trace_value).strip():
                        # 数値文字列の場合のみfloat変換
                        if str(trace_value).replace('.', '').replace('-', '').isdigit():
                            price_trace_change = float(trace_value)
                        else:
                            # 文字列の場合は0として扱う
                            price_trace_change = 0
                except (ValueError, TypeError):
                    price_trace_change = 0
            
                # Trace変更の日本語化
                trace_change_text = self._format_trace_change(price_trace_change)
        
            # 文字列に変換（Noneの場合は空文字列）
            trace_change_text = str(trace_change_text) if trace_change_text is not None else ""
            keepa_ref = item.get("keepa_ref_price", "")
            keepa_ref_text = "" if keepa_ref in (None, "") else str(keepa_ref)
        
            # Excel数式記法のクリーンアップ
            self.result_table.setItem(i, 0, QTableWidgetItem(self.clean_excel_formula(str(sku))))
            self.result_table.setItem(i, 1, QTableWidgetItem(self.clean_excel_formula(str(asin))))
        
            # Title列の特別処理（50文字制限+ツールチップ）
            title_clean = self.clean_excel_formula(str(title))
            title_display = title_clean[:50] + '...' if len(title_clean) > 50 else title_clean
            title_item = QTableWidgetItem(title_display)
            if len(title_clean) > 50:
                title_item.setToolTip(title_clean)  # ツールチップで全文表示
            self.result_table.setItem(i, 2, title_item)
        
            # 日数列：数値としてソートするためにQt.UserRoleに数値を設定
            days_item = NumericTableWidgetItem(days)
            days_item.setText(self.clean_excel_formula(str(days)))
            self.result_table.setItem(i, 3, days_item)
        
            # TP下限到達マーカー（色に依存しない視認性向上）
            tp_flag_text = ""
            akaji_equal_price = False
            if akaji_value not in (None, ""):
                try:
                    akaji_equal_price = abs(price - float(akaji_value)) <= 1e-9
                except (TypeError, ValueError):
                    akaji_equal_price = False
            if tp_reach_status in ("期間到達", "期間外到達"):
                tp_flag_text = tp_reach_status
            elif is_tp_floor_or_below:
                tp_flag_text = "到達"
            elif akaji_equal_price:
                # 在庫CSVのpriceとakajiが同額の場合は要チェックとして明示
                tp_flag_text = "akaji到達"
            elif "TP下限" in reason:
                tp_flag_text = "近接"
            tp_flag_item = QTableWidgetItem(tp_flag_text)
            if tp_flag_text:
                tp_flag_item.setToolTip("TP下限到達/下限以下の行です")
                if tp_flag_text == "期間到達":
                    tp_flag_item.setForeground(QColor(80, 220, 120))  # 緑
                elif tp_flag_text == "期間外到達":
                    tp_flag_item.setForeground(QColor(255, 80, 80))  # 赤
                elif tp_flag_text == "akaji到達":
                    tp_flag_item.setForeground(QColor(255, 230, 0))  # 黄色
                else:
                    tp_flag_item.setForeground(QColor(255, 80, 80))
            self.result_table.setItem(i, 4, tp_flag_item)

            self.result_table.setItem(i, 5, QTableWidgetItem(self.clean_excel_formula(str(action))))
            self.result_table.setItem(i, 6, QTableWidgetItem(self.clean_excel_formula(str(reason))))
        
            # 価格列：数値としてソートするためにQt.UserRoleに数値を設定
            price_item = NumericTableWidgetItem(price)
            price_item.setText(self.clean_excel_formula(str(price)))
            self.result_table.setItem(i, 7, price_item)
        
            new_price_item = NumericTableWidgetItem(new_price)
            new_price_item.setText(self.clean_excel_formula(str(new_price)))
            self.result_table.setItem(i, 8, new_price_item)

            # akaji / takane は3-6-9実行時の入力値確認用にそのまま表示
            akaji_text = "" if akaji_value in (None, "") else self.clean_excel_formula(str(akaji_value))
            takane_text = "" if takane_value in (None, "") else self.clean_excel_formula(str(takane_value))
            self.result_table.setItem(i, 9, QTableWidgetItem(akaji_text))
            self.result_table.setItem(i, 10, QTableWidgetItem(takane_text))
        
            self.result_table.setItem(i, 11, QTableWidgetItem(trace_change_text))
            self.result_table.setItem(i, 12, QTableWidgetItem(keepa_ref_text))
        
            # 日付不明の行を識別（daysが-1、または理由に「日付不明」が含まれる）
            is_date_unknown = (days == -1) or ("日付不明" in reason)
        
            # 日付不明の場合は灰色で表示
            if is_date_unknown:
                for j in range(total_columns):
                    item = self.result_table.item(i, j)
                    if item:
                        item.setBackground(QColor(150, 150, 150))  # グレー背景
                        item.setForeground(QColor(255, 255, 255))  # 白文字
            else:
                # 価格変更に応じて色分け（型変換を追加）
                try:
                    price_float = float(price) if price else 0
                    new_price_float = float(new_price) if new_price else 0
                
                    if new_price_float > price_float:
                        # 価格上昇：緑色
                        for j in range(total_columns):
                            item = self.result_table.item(i, j)
                            if item:
                                item.setBackground(QColor(200, 255, 200))
                    elif new_price_float < price_float:
                        # 価格下降：赤色
                        for j in range(total_columns):
                            item = self.result_table.item(i, j)
                            if item:
                                item.setBackground(QColor(255, 200, 200))

                    # TP下限ちょうど/以下は最優先で黄色表示
                    # バックエンド判定フラグを最優先で使用し、必要時のみフォールバック判定
                    akaji_float = None
                    try:
                        akaji_float = float(akaji_value) if akaji_value not in (None, "") else None
                    except (TypeError, ValueError):
                        akaji_float = None

                    is_tp_floor_row = bool(
                        is_tp_floor_or_below
                        or (tp_floor is not None and tp_floor > 0 and (new_price_float <= tp_floor or price_float <= tp_floor))
                        or ("TP下限" in reason)
                        or (akaji_float is not None and akaji_float > 0 and (new_price_float <= akaji_float or price_float <= akaji_float))
                    )
                    if is_tp_floor_row:
                        for j in range(total_columns):
                            cell_item = self.result_table.item(i, j)
                            if cell_item:
                                # ダークテーマでも見える強めの黄色
                                cell_item.setBackground(QColor(255, 230, 0))
                        # TP下限マーカー列は常に赤で見せる（行色処理の後に再適用）
                        tp_marker_item = self.result_table.item(i, 4)
                        if tp_marker_item and tp_marker_item.text().strip():
                            marker_text = tp_marker_item.text().strip()
                            if marker_text == "期間到達":
                                tp_marker_item.setForeground(QColor(80, 220, 120))
                            elif marker_text == "akaji到達":
                                tp_marker_item.setForeground(QColor(255, 230, 0))
                            else:
                                tp_marker_item.setForeground(QColor(255, 80, 80))
                except (ValueError, TypeError):
                    # 型変換に失敗した場合は色分けをスキップ
                    pass
    
        # データ投入完了後、ソート機能を再有効化
        self.result_table.setSortingEnabled(True)
    
        # 列幅の自動調整
        self.result_table.resizeColumnsToContents()

    def _is_keepa_target_item(self, item: dict) -> bool:
        """Keepa取得対象行を判定する。"""
        raw_action = str(item.get("rule_action", "")).lower()
        try:
            current_price = float(item.get("new_price", item.get("price", 0)) or 0)
        except (TypeError, ValueError):
            current_price = 0.0
        try:
            akaji = float(item.get("akaji", 0) or 0)
        except (TypeError, ValueError):
            akaji = 0.0
        is_akaji_sticky = akaji > 0 and abs(current_price - akaji) <= 1.0
        return (raw_action == "tp_down") or (raw_action == "pricetrace" and is_akaji_sticky)

    def _pick_keepa_reference_price(self, info) -> str:
        """Keepa情報から参考価格文字列を作る（中古最安ベース）。"""
        candidates = [
            info.used_like_new,
            info.used_very_good,
            info.used_good,
            info.used_acceptable,
        ]
        prices = [float(v) for v in candidates if v is not None and float(v) > 0]
        if prices:
            return str(round(min(prices)))
        if info.new_price is not None and float(info.new_price) > 0:
            return str(round(float(info.new_price)))
        return ""

    def fetch_keepa_for_target_rows(self):
        """対象行だけKeepa価格(参考)を取得して結果テーブルに反映する。"""
        if not self.repricing_result or "items" not in self.repricing_result:
            QMessageBox.information(self, "Keepa取得", "先に価格改定プレビューまたは実行を行ってください。")
            return

        items = self.repricing_result.get("items", [])
        target_items = [it for it in items if self._is_keepa_target_item(it) and str(it.get("asin", "")).strip()]
        if not target_items:
            QMessageBox.information(self, "Keepa取得", "Keepa取得対象のSKUがありません。")
            return

        unique_asins = []
        seen = set()
        for it in target_items:
            asin = str(it.get("asin", "")).strip()
            if asin and asin not in seen:
                seen.add(asin)
                unique_asins.append(asin)

        reply = QMessageBox.question(
            self,
            "Keepa取得確認",
            f"対象SKU: {len(target_items)}件（ASIN重複除外: {len(unique_asins)}件）\nKeepa価格(参考)を取得しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.keepa_fetch_btn.setEnabled(False)

        success = 0
        failed = 0
        service = None
        try:
            service = KeepaService()
            total = len(unique_asins)
            asin_to_price = {}
            for idx, asin in enumerate(unique_asins, 1):
                if asin in self.keepa_cache:
                    asin_to_price[asin] = self.keepa_cache.get(asin, "")
                else:
                    try:
                        info = service.fetch_product_by_asin(asin)
                        keepa_price = self._pick_keepa_reference_price(info)
                        self.keepa_cache[asin] = keepa_price
                        asin_to_price[asin] = keepa_price
                    except Exception:
                        self.keepa_cache[asin] = ""
                        asin_to_price[asin] = ""
                        failed += 1
                self.progress_bar.setValue(round(idx * 100 / max(1, total)))
                QApplication.processEvents()

            for item in target_items:
                asin = str(item.get("asin", "")).strip()
                keepa_price = asin_to_price.get(asin, "")
                if keepa_price:
                    item["keepa_ref_price"] = keepa_price
                    success += 1

            self.update_result_table(self.repricing_result)
            QMessageBox.information(
                self,
                "Keepa取得完了",
                f"Keepa価格(参考)を更新しました。\n成功: {success}件 / 失敗: {failed}件",
            )
        except Exception as e:
            QMessageBox.warning(self, "Keepa取得エラー", f"Keepa取得に失敗しました:\n{e}")
        finally:
            self.progress_bar.setVisible(False)
            self.keepa_fetch_btn.setEnabled(True)

    def _get_unique_file_path(self, directory: str, filename: str) -> str:
        """重複しないファイルパスを生成"""
        import os
    
        # ディレクトリとファイル名を分離
        name, ext = os.path.splitext(filename)
    
        # 最初のファイルパス
        file_path = os.path.join(directory, filename)
    
        # ファイルが存在しない場合はそのまま返す
        if not os.path.exists(file_path):
            return file_path
    
        # 重複する場合は番号を付ける
        counter = 1
        while True:
            new_filename = f"{name}({counter}){ext}"
            new_file_path = os.path.join(directory, new_filename)
        
            if not os.path.exists(new_file_path):
                return new_file_path
        
            counter += 1
        
            # 無限ループ防止（最大999まで）
            if counter > 999:
                return file_path

    def auto_save_results_to_source_dir(self):
        """元CSVと同じフォルダに自動保存"""
        if not self.repricing_result or not self.csv_path:
            return None
    
        source_path = Path(self.csv_path)
        source_dir = str(source_path.parent)
        auto_filename = f"{source_path.stem}_repriced.csv"
        target_path = self._get_unique_file_path(source_dir, auto_filename)
        return self._write_results_to_csv(target_path)

    def save_results(self):
        """結果のCSV保存"""
        if not self.repricing_result:
            QMessageBox.warning(self, "エラー", "保存する結果がありません")
            return
        
        # CSVファイル選択で指定したフォルダをデフォルトディレクトリとして使用
        default_dir = self.settings.value("directories/csv", "")
        if not default_dir and self.csv_path:
            # CSVファイルパスが設定されている場合はそのディレクトリを使用
            default_dir = str(Path(self.csv_path).parent)
    
        default_filename = "repricing_result.csv"
    
        # デフォルトディレクトリがある場合は、自動リネーム機能付きでファイルパスを生成
        if default_dir:
            default_path = self._get_unique_file_path(default_dir, default_filename)
        else:
            default_path = default_filename
    
        # 直接ファイル保存ダイアログを表示（確認ダイアログなし）
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "結果をCSV保存",
            default_path,  # デフォルトパスを指定（CSVファイル選択時のフォルダ）
            "CSVファイル (*.csv)"
        )
    
        if not file_path:
            return  # キャンセルされた場合
    
        if file_path:
            try:
                saved_path = self._write_results_to_csv(file_path)
                print(f"[DEBUG CSV保存] 保存完了: {saved_path}")
                self._set_pricerstar_csv_file(saved_path)
                auto_hint = "「ブラウザで開く」後、CSVアイコンをドラッグしてプライスターへ送ってください。"
                QMessageBox.information(
                    self,
                    "保存完了",
                    f"結果を保存しました:\n{saved_path}\n\n"
                    f"{auto_hint}",
                )
            except Exception as e:
                print(f"[ERROR CSV保存] 保存エラー: {str(e)}")
                print(f"[ERROR CSV保存] エラータイプ: {type(e).__name__}")
                import traceback
                print(f"[ERROR CSV保存] トレースバック: {traceback.format_exc()}")
                QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{str(e)}")

    def _write_results_to_csv(self, file_path: str) -> str:
        """価格改定結果を指定パスに保存して保存先パスを返す"""
        if not self.repricing_result:
            raise ValueError("保存対象の結果がありません。")
    
        items = self.repricing_result['items']
        print(f"[DEBUG CSV保存] 保存開始: {len(items)}件のアイテム")
    
        # 元ファイルのデータを読み込んで、priceとpriceTraceのみを変更
        from utils.csv_io import csv_io
        original_df = csv_io.read_csv(self.csv_path)
    
        if original_df is None:
            raise RuntimeError("元のCSVファイルを読み込めませんでした")
    
        # 価格改定結果を辞書に変換（SKUをキーとして）
        repricing_dict = {}
        for item in items:
            sku = self.clean_excel_formula(str(item.get('sku', '')))
        
            # 安全な型変換
            try:
                new_price = float(item.get('new_price', 0)) if item.get('new_price') is not None else 0
                new_price = int(new_price) if new_price > 0 else 0
            except (ValueError, TypeError):
                new_price = 0
        
            try:
                trace_value = item.get('priceTraceChange', item.get('price_trace_change', 0))
                if trace_value is not None and str(trace_value).strip():
                    # 数値文字列の場合のみint変換
                    if str(trace_value).replace('.', '').replace('-', '').isdigit():
                        price_trace = int(float(trace_value))
                    else:
                        # 文字列の場合は0として扱う
                        price_trace = 0
                else:
                    price_trace = 0
            except (ValueError, TypeError):
                price_trace = 0
        
            # akajiの情報を取得（price_down_ignoreの場合は空白）
            akaji_value = item.get('akaji', None)
        
            repricing_dict[sku] = {
                'new_price': new_price,
                'price_trace': price_trace,
                'akaji': akaji_value,
                'takane': item.get('takane', None),
            }
    
        # 元ファイルのデータをコピーして、該当する行のみpriceとpriceTraceを更新
        # 価格やpriceTraceに変更がない場合は除外する
        data = []
        for _, row in original_df.iterrows():
            sku = self.clean_excel_formula(str(row.get('SKU', '')))
        
            # 元の価格とpriceTraceを取得
            original_price = float(row.get('price', 0)) if pd.notna(row.get('price')) else 0
            original_price_trace = float(row.get('priceTrace', 0)) if pd.notna(row.get('priceTrace')) else 0
        
            manual_price = self._manual_export_prices.get(sku)

            # 価格改定対象の場合はpriceとpriceTraceを更新
            if sku in repricing_dict:
                new_price = repricing_dict[sku]['new_price']
                new_price_trace = repricing_dict[sku]['price_trace']
                akaji_value = repricing_dict[sku].get('akaji', None)
                takane_value = repricing_dict[sku].get('takane', None)
                if manual_price is not None:
                    new_price = manual_price

                orig_akaji = float(row.get('akaji', 0)) if pd.notna(row.get('akaji')) else 0
                orig_takane = float(row.get('takane', 0)) if pd.notna(row.get('takane')) else 0
                new_akaji_f = float(akaji_value) if akaji_value not in (None, "") else orig_akaji
                new_takane_f = float(takane_value) if takane_value not in (None, "") else orig_takane

                # 価格とpriceTraceの両方が変更されていない場合はスキップ（手動上書き時は価格差があれば出力）
                if (
                    manual_price is None
                    and new_price == original_price
                    and new_price_trace == original_price_trace
                ):
                    print(f"[DEBUG CSV保存] スキップ: {sku} (変更なし)")
                    continue
                if (
                    manual_price is not None
                    and int(manual_price) == int(original_price)
                    and new_price_trace == original_price_trace
                    and abs(new_akaji_f - orig_akaji) < 1e-9
                    and abs(new_takane_f - orig_takane) < 1e-9
                ):
                    print(f"[DEBUG CSV保存] スキップ: {sku} (手動・価格/Trace/akaji/takane 変更なし)")
                    continue

                row_data = row.to_dict()
                row_data['price'] = new_price
                row_data['priceTrace'] = new_price_trace
                row_data['conditionNote'] = ""
                if akaji_value is not None:
                    row_data['akaji'] = akaji_value
                if takane_value is not None and takane_value != "":
                    row_data['takane'] = takane_value
                data.append(row_data)
            elif manual_price is not None:
                orig_akaji = float(row.get('akaji', 0)) if pd.notna(row.get('akaji')) else 0
                orig_takane = float(row.get('takane', 0)) if pd.notna(row.get('takane')) else 0
                akaji_out, takane_out = self._akaji_takane_from_rule_percents(int(manual_price), 2, 1)
                for it in items:
                    it_sku = self.clean_excel_formula(str(it.get("sku", ""))).strip()
                    if it_sku == sku:
                        akaji_out, takane_out = self._akaji_takane_from_rule_percents(
                            int(manual_price),
                            it.get("akaji_drop_percent"),
                            it.get("takane_rise_percent"),
                        )
                        break
                if (
                    int(manual_price) == int(original_price)
                    and abs(akaji_out - orig_akaji) < 1e-9
                    and abs(takane_out - orig_takane) < 1e-9
                ):
                    print(f"[DEBUG CSV保存] スキップ: {sku} (手動価格のみ・変更なし)")
                    continue
                row_data = row.to_dict()
                row_data['price'] = manual_price
                row_data['akaji'] = akaji_out
                row_data['takane'] = takane_out
                row_data['conditionNote'] = ""
                data.append(row_data)
            else:
                # 対象外の場合は元のデータをそのまま使用
                row_data = row.to_dict()
                data.append(row_data)
    
        df = pd.DataFrame(data)
    
        # 元ファイルの書式に完全に合わせるための処理
        # 0. 空の値を保持（nanを空文字に変換）
        df = df.fillna('')  # 全てのnan値を空文字に変換
        # 1. 数値列を文字列として出力（クォート付き）
        numeric_columns = ['number', 'price', 'cost', 'akaji', 'takane', 'condition', 'priceTrace', 'amazon-fee', 'shipping-price', 'profit']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = df[col].astype(str)
                # 文字列変換後もnan値を空文字に変換
                df[col] = df[col].replace('nan', '')
    
        # 2. Excel数式記法の修正（プライスター対応）
        text_columns = ['SKU', 'ASIN', 'title', 'conditionNote', 'leadtime', 'add-delete']
        for col in text_columns:
            if col in df.columns:
                try:
                    # 文字列型に変換
                    df[col] = df[col].astype(str)
                    # nan値を空文字に変換
                    df[col] = df[col].replace('nan', '')
                    # Excel数式記法をプライスター形式に変換
                    df[col] = df[col].str.replace(r'^"(.+)"$', r'=\1', regex=True)  # "値" → =値
                except Exception as e:
                    print(f"[WARNING CSV保存] 列 {col} の処理でエラー: {e}")
                    # エラーが発生した場合は文字列型に変換するだけ
                    df[col] = df[col].astype(str)
                    df[col] = df[col].replace('nan', '')
    
        # 3. Shift-JISでエンコードできない文字の置換処理
        def clean_for_shift_jis(text):
            """Shift-JISでエンコードできない文字を置換"""
            if pd.isna(text) or text == '':
                return text
        
            # 文字列に変換
            text = str(text)
        
            # Shift-JISでエンコードできない文字の置換
            replacements = {
                '\uff5e': '~',  # 全角チルダ → 半角チルダ
                '\uff0d': '-',  # 全角ハイフン → 半角ハイフン
                '\uff0c': ',',  # 全角カンマ → 半角カンマ
                '\uff1a': ':',  # 全角コロン → 半角コロン
                '\uff1b': ';',  # 全角セミコロン → 半角セミコロン
                '\uff01': '!',  # 全角エクスクラメーション → 半角
                '\uff1f': '?',  # 全角クエスチョン → 半角
                '\uff08': '(',  # 全角括弧 → 半角括弧
                '\uff09': ')',  # 全角括弧 → 半角括弧
                '\uff3b': '[',  # 全角角括弧 → 半角角括弧
                '\uff3d': ']',  # 全角角括弧 → 半角角括弧
                '\uff5b': '{',  # 全角波括弧 → 半角波括弧
                '\uff5d': '}',  # 全角波括弧 → 半角波括弧
                '\uff0a': '\n',  # 全角改行 → 半角改行
                '\uff20': '@',  # 全角アットマーク → 半角アットマーク
                '\uff23': '#',  # 全角シャープ → 半角シャープ
                '\uff24': '$',  # 全角ドル → 半角ドル
                '\uff25': '%',  # 全角パーセント → 半角パーセント
                '\uff26': '&',  # 全角アンパサンド → 半角アンパサンド
                '\uff2a': '*',  # 全角アスタリスク → 半角アスタリスク
                '\uff2b': '+',  # 全角プラス → 半角プラス
                '\uff2e': '.',  # 全角ピリオド → 半角ピリオド
                '\uff2f': '/',  # 全角スラッシュ → 半角スラッシュ
                '\uff3c': '<',  # 全角小なり → 半角小なり
                '\uff3e': '>',  # 全角大なり → 半角大なり
                '\uff3f': '_',  # 全角アンダースコア → 半角アンダースコア
                '\uff40': '`',  # 全角バッククォート → 半角バッククォート
                '\uff5c': '|',  # 全角パイプ → 半角パイプ
            }
        
            for full_width, half_width in replacements.items():
                text = text.replace(full_width, half_width)
        
            return text
    
        # テキスト列の文字置換処理
        text_columns = ['SKU', 'ASIN', 'title', 'conditionNote', 'leadtime', 'add-delete']
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].apply(clean_for_shift_jis)
    
        # 4. 元ファイルと同じ形式でCSV保存（プライスター対応）
        from desktop.utils.file_naming import resolve_unique_path
        target = resolve_unique_path(Path(file_path))
        try:
            df.to_csv(str(target), index=False, encoding='shift_jis', quoting=0)  # Shift-JIS、クォートなし
        except UnicodeEncodeError as e:
            # Shift-JISでエンコードできない文字が残っている場合の追加処理
            print(f"[WARNING CSV保存] Shift-JISエンコードエラー: {e}")
            print(f"[WARNING CSV保存] エラー文字を除去して再試行...")
        
            # エラーが発生した列を特定して処理
            for col in df.columns:
                try:
                    # 各列をShift-JISでエンコードテスト
                    df[col].astype(str).str.encode('shift_jis')
                except UnicodeEncodeError:
                    # エラーが発生した列の文字を安全な文字に置換
                    df[col] = df[col].astype(str).str.encode('shift_jis', errors='replace').str.decode('shift_jis')
        
            # 再試行（同じtargetパスを使用、resolve_unique_pathは呼ばない）
            df.to_csv(str(target), index=False, encoding='shift_jis', quoting=0)
    
        return str(target)
