#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ルート照合 mixin。"""
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


class InventoryRouteMatchMixin:
    def setup_route_template_panel(self):
        """ルートテンプレート読み込みエリア（レイアウト先行の仮実装）"""
        self.route_template_group = QGroupBox("ルート情報")
        self.route_template_group.setCheckable(True)
        self.route_template_group.setChecked(True)
        outer_layout = QVBoxLayout(self.route_template_group)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)
        
        self.route_template_content = QWidget()
        content_layout = QVBoxLayout(self.route_template_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        
        self.route_template_summary_label = QLabel("ルート情報: ー")
        self.route_template_summary_label.setStyleSheet("font-weight: bold;")
        # ルート情報ラベルは固定サイズ（stretch factor = 0）
        content_layout.addWidget(self.route_template_summary_label, 0)
        
        self.route_template_table = QTableWidget()
        headers = [
            "訪問順序", "店舗コード", "店舗名", "IN時間", "OUT時間",
            "滞在(分)", "移動(分)", "想定粗利", "仕入点数", "評価", "メモ"
        ]
        self.route_template_table.setColumnCount(len(headers))
        self.route_template_table.setHorizontalHeaderLabels(headers)
        self.route_template_table.setAlternatingRowColors(True)
        self.route_template_table.setSelectionBehavior(QTableWidget.SelectRows)
        # メモ列のみ編集可能（ダブルクリック等）。他列は行単位のため実質コード列は編集しにくいが、必要なら後で調整。
        self.route_template_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked
        )
        # 選択変更時のイベントハンドラ
        self.route_template_table.itemSelectionChanged.connect(self.on_route_selection_changed)
        self.route_template_table.itemChanged.connect(self._on_route_template_memo_changed)
        header = self.route_template_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        # 評価列（列インデックス9）だけは後で手動調整するため、一旦Interactiveに設定
        header.setSectionResizeMode(9, QHeaderView.Interactive)
        header.setStretchLastSection(True)
        # 星評価が綺麗に収まるように行の高さを調整
        self.route_template_table.verticalHeader().setDefaultSectionSize(24)
        # ルートテンプレートテーブルの高さ設定（初期値は制限あり）
        self.route_template_table.setMinimumHeight(150)
        self.route_template_table.setMaximumHeight(200)  # 初期は最大高さを制限
        self.route_template_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # テーブルをレイアウトに追加（stretch factorを0にして高さを制限、折りたたみ時に動的に変更）
        content_layout.addWidget(self.route_template_table, 0)
        
        # 店舗評価の計算ロジック案内
        rating_info_layout = QHBoxLayout()
        rating_info_layout.addStretch()
        self.rating_info_button = QPushButton("※ 店舗評価の計算ロジック")
        self.rating_info_button.setCursor(Qt.PointingHandCursor)
        self.rating_info_button.setFlat(True)
        self.rating_info_button.setStyleSheet(
            "QPushButton { color: #5aa2ff; text-decoration: underline; border: none; font-size: 10pt; }"
            "QPushButton:hover { color: #8fc4ff; }"
        )
        self.rating_info_button.clicked.connect(self.show_rating_logic_popup)
        rating_info_layout.addWidget(self.rating_info_button)
        content_layout.addLayout(rating_info_layout)
        
        # ルート情報の操作ボタン
        route_ops_layout = QHBoxLayout()
        self.route_clear_btn = QPushButton("クリア")
        self.route_clear_btn.clicked.connect(self.clear_route_data)
        self.route_clear_btn.setEnabled(False)
        route_ops_layout.addWidget(self.route_clear_btn)
        
        self.route_delete_row_btn = QPushButton("行削除")
        self.route_delete_row_btn.clicked.connect(self.delete_selected_route_rows)
        self.route_delete_row_btn.setEnabled(False)
        route_ops_layout.addWidget(self.route_delete_row_btn)
        
        route_ops_layout.addStretch()
        content_layout.addLayout(route_ops_layout)
        
        # 前回読込表示を削除（取り込んだデータ一覧エリアの高さを確保）
        # self.route_template_status は削除
        
        outer_layout.addWidget(self.route_template_content)
        
        def _on_toggle(checked: bool):
            self.route_template_content.setVisible(checked)
            # スプリッターを使用している場合は、スプリッターが高さを管理する
            if hasattr(self, 'area_splitter'):
                if checked:
                    # 展開時：スプリッターの設定に従う（制限を解除）
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                    self.route_template_group.setMaximumHeight(16777215)
                else:
                    # 折りたたみ時：最小高さに制限
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    header_height = self.route_template_group.sizeHint().height()
                    self.route_template_group.setMaximumHeight(header_height)
                # スプリッターのサイズを再計算
                self.area_splitter.updateGeometry()
            else:
                # スプリッターがない場合の従来の処理（後方互換性のため）
                if checked:
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    self.route_template_group.setMaximumHeight(16777215)
                else:
                    self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    header_height = self.route_template_group.sizeHint().height()
                    self.route_template_group.setMaximumHeight(header_height)
            # レイアウトを再計算
            self.route_template_group.updateGeometry()
            if self.route_template_group.parent():
                self.route_template_group.parent().updateGeometry()
        self.route_template_group.toggled.connect(_on_toggle)
        self.route_template_content.setVisible(True)
        
        # ルートテンプレートグループのサイズポリシーを制限（高さを縮小）
        self.route_template_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        # スプリッターで管理するため、ここではレイアウトに追加しない
        # setup_splitter()で追加される
        self.refresh_route_template_view()

    def _ensure_missing_stores_registered(
        self,
        entries: List[tuple],
        route_data: Optional[Dict[str, Any]] = None,
        *,
        show_message: bool = True,
    ):
        """店舗マスタに無い店舗コードを、ファイルのコード・店舗名のまま登録する。"""
        if not entries or not self.store_db:
            return None
        try:
            try:
                from services.store_master_auto_register import (
                    ensure_stores_in_master,
                    resolve_route_from_template,
                )
            except ImportError:
                from desktop.services.store_master_auto_register import (  # type: ignore
                    ensure_stores_in_master,
                    resolve_route_from_template,
                )

            route_data = route_data or {}
            combo_name = ""
            if self.route_summary_widget:
                try:
                    combo_name = self.route_summary_widget.route_code_combo.currentText().strip()
                except Exception:
                    pass

            route_code, affiliated = resolve_route_from_template(
                self.store_db,
                route_data,
                combo_route_name=combo_name,
            )

            result = ensure_stores_in_master(
                self.store_db,
                entries,
                route_code=route_code,
                affiliated_route_name=affiliated,
                fetch_google=True,
            )

            if show_message and result.added > 0:
                msg = f"店舗マスタに {result.added} 件を新規登録しました。"
                if affiliated:
                    msg += f"\n所属ルート: {affiliated}"
                if result.google_ok or result.google_failed:
                    msg += (
                        f"\nGoogle Maps 情報: 取得成功 {result.google_ok} 件"
                        f" / 未取得 {result.google_failed} 件"
                    )
                if result.errors:
                    msg += f"\n\n注意:\n" + "\n".join(result.errors[:3])
                    if len(result.errors) > 3:
                        msg += f"\n…他 {len(result.errors) - 3} 件"
                QMessageBox.information(self, "店舗マスタ自動登録", msg)
            return result
        except Exception as exc:
            print(f"店舗マスタ自動登録エラー: {exc}")
            return None

    def _collect_store_entries_from_route_visits(
        self, visits: List[Dict[str, Any]]
    ) -> List[tuple]:
        exclude = {"出発時刻", "帰宅時刻", "往路高速代", "復路高速代"}
        entries: List[tuple] = []
        for visit in visits or []:
            code = str(visit.get("store_code") or "").strip()
            name = str(visit.get("store_name") or "").strip()
            if code and code not in exclude:
                entries.append((code, name or code))
        return entries

    def _collect_store_entries_from_inventory(self) -> List[tuple]:
        """仕入データの仕入先列とルート情報から店舗コード・店舗名を収集。"""
        exclude = {"出発時刻", "帰宅時刻", "往路高速代", "復路高速代"}
        name_by_code: Dict[str, str] = {}

        if self.route_summary_widget:
            try:
                for visit in self.route_summary_widget.get_store_visits_data():
                    code = str(visit.get("store_code") or "").strip()
                    name = str(visit.get("store_name") or "").strip()
                    if code and code not in exclude:
                        if name:
                            name_by_code[code] = name
                        else:
                            name_by_code.setdefault(code, code)
            except Exception:
                pass

        if hasattr(self, "route_template_table"):
            try:
                for row in range(self.route_template_table.rowCount()):
                    code_item = self.route_template_table.item(row, 1)
                    name_item = self.route_template_table.item(row, 2)
                    code = code_item.text().strip() if code_item else ""
                    name = name_item.text().strip() if name_item else ""
                    if code and code not in exclude:
                        if name:
                            name_by_code[code] = name
                        else:
                            name_by_code.setdefault(code, code)
            except Exception:
                pass

        if self.inventory_data is not None and "仕入先" in self.inventory_data.columns:
            for val in self.inventory_data["仕入先"].dropna().unique():
                code = str(val).strip()
                if code and code not in exclude and code.lower() not in ("nan", "none"):
                    name_by_code.setdefault(code, code)

        return [(code, name_by_code.get(code) or code) for code in sorted(name_by_code)]

    def _auto_register_stores_from_route_template(self):
        if not self.route_summary_widget:
            return
        exclude = {"出発時刻", "帰宅時刻", "往路高速代", "復路高速代"}
        visits = self.route_summary_widget.get_store_visits_data()
        filtered = [v for v in visits if v.get("store_code") not in exclude]
        entries = self._collect_store_entries_from_route_visits(filtered)
        route_data = self.route_summary_widget.get_route_data()
        self._ensure_missing_stores_registered(entries, route_data)

    def _auto_register_stores_from_inventory(self, *, show_message: bool = True):
        entries = self._collect_store_entries_from_inventory()
        route_data = {}
        if self.route_summary_widget:
            try:
                route_data = self.route_summary_widget.get_route_data()
            except Exception:
                pass
        self._ensure_missing_stores_registered(entries, route_data, show_message=show_message)

    def apply_route_template(self):
        """ルートテンプレートの読み込みを実行"""
        if not self.route_summary_widget:
            QMessageBox.warning(self, "ルートテンプレート", "ルート機能が未初期化です。ルータブが有効か確認してください。")
            return
        try:
            file_path = self.route_summary_widget.load_template(
                initial_dir=self._get_last_csv_import_folder() or None
            )
            if not file_path:
                # route_template_status は削除済み
                return
            try:
                s = self._get_qsettings()
                s.setValue("route_template/last_selected", file_path)
            except Exception:
                pass
            self.refresh_route_template_view()
            self._auto_register_stores_from_route_template()
            # route_template_status は削除済み（読み込み完了メッセージは表示しない）
        except Exception as e:
            QMessageBox.critical(self, "テンプレート読込エラー", f"テンプレートの読み込みに失敗しました:\n{e}")

    def refresh_route_template_view(self):
        """ルートテンプレートの情報を表示に反映"""
        if not self.route_summary_widget:
            self.route_template_table.setRowCount(0)
            self.route_template_summary_label.setText("ルート情報: ー")
            return
        try:
            route_data = self.route_summary_widget.get_route_data()
            
            # ルートIDがある場合はデータベースから最新データを取得
            route_id = self.route_summary_widget.current_route_id
            if route_id:
                try:
                    # データベースから店舗訪問詳細を取得
                    from database.route_db import RouteDatabase
                    route_db = RouteDatabase()
                    visits_from_db = route_db.get_store_visits_by_route(route_id)
                    
                # 店舗名を補完し、評価が無い場合は計算
                    visits = []
                    for visit in visits_from_db:
                        store_code = visit.get('store_code', '')
                        store_name = visit.get('store_name', '')
                        if not store_name and store_code:
                            # 店舗マスタから店舗名を取得（store_code優先、互換性のため仕入れ先コードも許容）
                            store_info = self.store_db.get_store_by_code(store_code)
                            if store_info:
                                store_name = store_info.get('store_name', '')
                        visit['store_name'] = store_name
                        
                        # 評価が無い、または0の場合、かつ仕入れ点数と想定粗利がある場合は計算する
                        store_rating = visit.get('store_rating')
                        store_item_count = visit.get('store_item_count', 0)
                        store_gross_profit = visit.get('store_gross_profit', 0)
                        
                        # 評価が無い、または0の場合で、仕入れ点数と想定粗利がある場合は評価を計算
                        if (not store_rating or store_rating == 0) and store_item_count and store_gross_profit:
                            rating = self._calculate_store_rating_from_visit(visit)
                            visit['store_rating'] = rating
                        elif not store_rating:
                            visit['store_rating'] = 0.0
                        
                        visits.append(visit)
                except Exception as db_err:
                    # データベース取得に失敗した場合はテーブルから取得
                    print(f"DBから取得失敗、テーブルから取得: {db_err}")
                    visits = self.route_summary_widget.get_store_visits_data()
            else:
                # ルートIDがない場合はテーブルから取得
                visits = self.route_summary_widget.get_store_visits_data()
            
            # 出発時刻・帰宅時間・往路高速代・復路高速代を店舗訪問情報から除外
            # これらの情報はルート全体の情報であり、個別の店舗訪問情報として扱うべきではない
            raw_visits: List[Dict[str, Any]] = []
            exclude_store_codes = ['出発時刻', '帰宅時刻', '往路高速代', '復路高速代']
            for visit in visits:
                store_code = visit.get('store_code', '')
                if store_code not in exclude_store_codes:
                    raw_visits.append(visit)

            # メモ欄があれば店舗マスタの備考欄に保存・追記（未訪問店舗も含む）
            self._save_memos_to_store_master(raw_visits)

            # 実訪問（IN/OUT 両方あり）のみ表示し、IN 時刻順に訪問順を揃える
            route_date = route_data.get('route_date', '')
            try:
                from desktop.services.route_visit_normalize import prepare_actual_visits_for_display
            except ImportError:
                from services.route_visit_normalize import prepare_actual_visits_for_display  # type: ignore
            filtered_visits = prepare_actual_visits_for_display(raw_visits, route_date)

            self.populate_route_template_table(filtered_visits)
            route_code = route_data.get('route_code', '')
            route_date = route_data.get('route_date', '')
            dep = self._format_hm(route_data.get('departure_time'))
            ret = self._format_hm(route_data.get('return_time'))
            toll_outbound = route_data.get('toll_fee_outbound', 0)
            toll_return = route_data.get('toll_fee_return', 0)
            summary_parts = []
            if route_date:
                summary_parts.append(route_date)
            if route_code:
                # ルートコードを日本語名に変換
                route_name = self.store_db.get_route_name_by_code(route_code)
                if route_name:
                    summary_parts.append(route_name)
                else:
                    # 日本語名が取得できない場合はコードをそのまま表示
                    summary_parts.append(route_code)
            times = []
            if dep:
                times.append(f"出発 {dep}")
            if ret:
                times.append(f"帰宅 {ret}")
            costs = []
            if toll_outbound is not None:
                try:
                    toll_outbound_val = float(toll_outbound)
                    costs.append(f"往路高速代 {int(toll_outbound_val):,}円")
                except (ValueError, TypeError):
                    pass
            if toll_return is not None:
                try:
                    toll_return_val = float(toll_return)
                    costs.append(f"復路高速代 {int(toll_return_val):,}円")
                except (ValueError, TypeError):
                    pass
            summary_text = " / ".join(summary_parts) if summary_parts else "ー"
            if times:
                summary_text = f"{summary_text} | {' / '.join(times)}"
            if costs:
                summary_text = f"{summary_text} | {' / '.join(costs)}"
            self.route_template_summary_label.setText(f"ルート情報: {summary_text}")
            
            # ボタンの有効/無効を更新
            has_route_data = self.route_template_table.rowCount() > 0
            if hasattr(self, 'route_clear_btn'):
                self.route_clear_btn.setEnabled(has_route_data)
        except Exception as e:
            self.route_template_table.setRowCount(0)
            self.route_template_summary_label.setText("ルート情報: ー")
            # ボタンの無効化
            if hasattr(self, 'route_clear_btn'):
                self.route_clear_btn.setEnabled(False)
            if hasattr(self, 'route_delete_row_btn'):
                self.route_delete_row_btn.setEnabled(False)
            print(f"ルートテンプレート表示更新エラー: {e}")
            import traceback
            traceback.print_exc()

    def populate_route_template_table(self, visits: List[Dict[str, Any]]):
        if not isinstance(visits, list):
            visits = []
        headers = [
            "訪問順序", "店舗コード", "店舗名", "IN時間", "OUT時間",
            "滞在(分)", "移動(分)", "想定粗利", "仕入点数", "評価", "メモ"
        ]
        self.route_template_table.blockSignals(True)
        try:
            self.route_template_table.setRowCount(len(visits))
            self.route_template_table.setColumnCount(len(headers))
            self.route_template_table.setHorizontalHeaderLabels(headers)
            for row, visit in enumerate(visits):
                def _set(col: int, value: Any):
                    item = QTableWidgetItem("" if value is None else str(value))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.route_template_table.setItem(row, col, item)

                _set(0, visit.get('visit_order', row + 1))
                _set(1, visit.get('store_code', ''))
                _set(2, visit.get('store_name', ''))
                _set(3, self._format_hm(visit.get('store_in_time')))
                _set(4, self._format_hm(visit.get('store_out_time')))
                _set(5, visit.get('stay_duration', ''))
                _set(6, visit.get('travel_time_from_prev', ''))
                _set(7, visit.get('store_gross_profit', ''))
                _set(8, visit.get('store_item_count', ''))

                store_rating = visit.get('store_rating')
                try:
                    rating_value = float(store_rating) if store_rating not in (None, '') else 0.0
                except (TypeError, ValueError):
                    rating_value = 0.0
                star_widget = StarRatingWidget(self.route_template_table, rating=rating_value, star_size=14)
                star_widget.setEnabled(False)
                self.route_template_table.setCellWidget(row, 9, star_widget)

                store_code = visit.get('store_code', '')
                memo_text = visit.get('store_notes', '')
                if store_code and not str(memo_text).strip():
                    store_info = self.store_db.get_store_by_code(store_code)
                    if store_info:
                        sql_n = str(store_info.get("notes", "") or "").strip()
                        cf_n = str((store_info.get("custom_fields") or {}).get("notes", "") or "").strip()
                        memo_text = self._merge_comma_note_tokens(sql_n, cf_n)
                memo_item = QTableWidgetItem("" if memo_text is None else str(memo_text))
                memo_item.setFlags(
                    (memo_item.flags() | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    & ~Qt.ItemIsUserCheckable
                )
                self.route_template_table.setItem(row, 10, memo_item)
        finally:
            self.route_template_table.blockSignals(False)

        # 列幅の調整（評価列の右端が見切れないように）
        self.route_template_table.resizeColumnsToContents()

        # 評価列（列インデックス9）の幅を自動調整（StarRatingWidgetのsizeHint()に基づく）
        if len(visits) > 0:
            first_star_widget = self.route_template_table.cellWidget(0, 9)
            if first_star_widget and isinstance(first_star_widget, StarRatingWidget):
                recommended_size = first_star_widget.sizeHint()
                rating_column_width = recommended_size.width() + 10
                self.route_template_table.setColumnWidth(9, rating_column_width)
            else:
                self.route_template_table.setColumnWidth(9, 130)
        else:
            self.route_template_table.setColumnWidth(9, 130)

        has_route_data = self.route_template_table.rowCount() > 0
        if hasattr(self, 'route_clear_btn'):
            self.route_clear_btn.setEnabled(has_route_data)

    @staticmethod
    def _merge_comma_note_tokens(*parts: str) -> str:
        """カンマ区切りの文字列をまとめ、トークン単位で重複を除く。"""
        seen: List[str] = []
        for part in parts:
            for seg in str(part or "").split(","):
                s = seg.strip()
                if s and s not in seen:
                    seen.append(s)
        return ", ".join(seen)

    def _merge_note_tokens_into_store_master(self, store_code: str, text: str) -> bool:
        """店舗マスタの備考（DBの stores.notes = データベース管理＞店舗一覧の備考列）へ追記する。
        旧データ用に custom_fields.notes も同じ統合結果へ揃える。
        """
        store_code = (store_code or "").strip()
        memo_text = (text or "").strip()
        if not store_code or not memo_text:
            return False
        store_info = self.store_db.get_store_by_code(store_code)
        if not store_info:
            return False
        sql_notes = str(store_info.get("notes", "") or "").strip()
        custom_fields = dict(store_info.get("custom_fields") or {})
        cf_notes = str(custom_fields.get("notes", "") or "").strip()
        before = self._merge_comma_note_tokens(sql_notes, cf_notes)
        after = self._merge_comma_note_tokens(sql_notes, cf_notes, memo_text)
        if before == after:
            return False
        store_id = store_info["id"]
        try:
            self.store_db.update_store_notes(store_id, after)
            if str(custom_fields.get("notes", "") or "").strip() != after:
                custom_fields["notes"] = after
                self.store_db.update_store(
                    store_id,
                    {"custom_fields": custom_fields},
                )
            return True
        except Exception as e:
            print(f"店舗マスタの備考欄更新エラー: {e}")
            return False

    def _on_route_template_memo_changed(self, item: QTableWidgetItem):
        """仕入管理＞ルート情報のメモ列編集で店舗マスタ備考へカンマ区切り追記する。"""
        if not item or item.column() != 10:
            return
        row = item.row()
        code_item = self.route_template_table.item(row, 1)
        store_code = code_item.text().strip() if code_item else ""
        self._merge_note_tokens_into_store_master(store_code, item.text())

    def _save_memos_to_store_master(self, visits: List[Dict[str, Any]]):
        """ルートテンプレート読み込み時にメモ欄があれば店舗マスタの備考欄に保存・追記"""
        for visit in visits:
            self._merge_note_tokens_into_store_master(
                visit.get("store_code", ""),
                visit.get("store_notes", ""),
            )

    def _calculate_store_rating_from_visit(self, visit: Dict[str, Any]) -> float:
        """店舗訪問データから評価を計算（ルート登録タブのロジックに合わせる）"""
        try:
            # 仕入れ点数、想定粗利、滞在時間を取得
            qty = self._safe_float(visit.get('store_item_count', 0))
            profit = self._safe_float(visit.get('store_gross_profit', 0))
            stay = self._safe_float(visit.get('stay_duration', 0))
            
            if qty <= 0 or profit <= 0:
                return 0.0
            
            stay = max(1.0, stay)
            
            # 基礎スコアを決定（仕入れ点数ベース）
            base_score = self._determine_base_score(int(round(qty)))
            
            # 粗利係数を計算
            profit_per_minute = profit / stay
            profit_threshold = 190.0
            profit_scale = 30.0
            profit_factor = max(0.0, min(5.0, (profit_per_minute - profit_threshold) / profit_scale))
            
            # 最終スコアを計算
            base_weight = 0.7
            profit_weight = 0.3
            final_score = (base_weight * base_score) + (profit_weight * profit_factor)
            
            # 0.0〜5.0の範囲に制限し、0.5刻みに丸める
            final_score = max(0.0, min(5.0, final_score))
            return round(final_score * 2) / 2
        except Exception as e:
            print(f"評価計算エラー: {e}")
            return 0.0

    def _determine_base_score(self, item_count: int) -> int:
        """仕入れ点数から基礎スコアを決定"""
        if item_count >= 10:
            return 5
        if item_count >= 7:
            return 4
        if item_count >= 5:
            return 3
        if item_count >= 3:
            return 2
        if item_count >= 1:
            return 1
        return 0

    def _safe_float(self, value: Any) -> float:
        """安全にfloatに変換"""
        if value is None or value == '':
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _format_hm(value: Optional[str]) -> str:
        if not value:
            return ''
        text = str(value)
        if ' ' in text:
            text = text.split(' ')[1]
        return text[:5]

    def clear_route_data(self):
        """ルート情報のみをクリア"""
        reply = QMessageBox.question(
            self,
            "確認",
            "ルート情報をクリアしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.route_template_table.setRowCount(0)
            self.route_template_summary_label.setText("ルート情報: ー")
            
            # ルートサマリーウィジェットのデータもクリア（可能であれば）
            if self.route_summary_widget:
                try:
                    if hasattr(self.route_summary_widget, 'clear_route_data'):
                        self.route_summary_widget.clear_route_data()
                    elif hasattr(self.route_summary_widget, 'current_route_id'):
                        self.route_summary_widget.current_route_id = None
                except Exception as e:
                    print(f"ルート情報のクリア中にエラー: {e}")
            
            # ボタンの無効化
            if hasattr(self, 'route_clear_btn'):
                self.route_clear_btn.setEnabled(False)
            if hasattr(self, 'route_delete_row_btn'):
                self.route_delete_row_btn.setEnabled(False)

    def show_rating_logic_popup(self):
        """店舗評価の計算ロジックを表示"""
        detail_text = (
            "【店舗評価の自動計算】\n\n"
            "1. 基礎星スコア（仕入れ点数）\n"
            "   1〜2点: ★1 / 3〜4点: ★2 / 5〜6点: ★3 / 7〜9点: ★4 / 10点以上: ★5\n\n"
            "2. 粗利係数（想定粗利）\n"
            "   〜5,000円:0.8 / 5,001〜10,000円:1.0 / 10,001〜20,000円:1.2 /\n"
            "   20,001〜40,000円:1.4 / 40,001円以上:1.6\n\n"
            "3. 最終スコア\n"
            "   最終スコア = (基礎星スコア × 粗利係数) × (想定粗利 ÷ 滞在時間)\n"
            "   ※滞在時間が1分未満の場合は1分として計算します。\n\n"
            "4. 星への変換\n"
            "   〜1.5→★1 / 1.6〜2.5→★2 / 2.6〜3.5→★3 /\n"
            "   3.6〜4.5→★4 / 4.6以上→★5\n\n"
            "仕入れ点数または想定粗利が未入力の場合は★0を設定します。"
        )
        QMessageBox.information(self, "店舗評価の計算ロジック", detail_text)

    def delete_selected_route_rows(self):
        """選択されたルート情報の行を削除"""
        selected_rows = set()
        for item in self.route_template_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除する行を選択してください")
            return
        
        reply = QMessageBox.question(
            self,
            "確認",
            f"{len(selected_rows)}行を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 行番号を降順にソート（後ろから削除することでインデックスがずれない）
            sorted_rows = sorted(selected_rows, reverse=True)
            
            # テーブルから行を削除
            for row_idx in sorted_rows:
                self.route_template_table.removeRow(row_idx)
            
            # ルートサマリーウィジェットのデータも更新（可能であれば）
            if self.route_summary_widget:
                try:
                    # テーブルから現在のデータを取得してルートサマリーウィジェットに反映
                    visits = []
                    for i in range(self.route_template_table.rowCount()):
                        visit = {
                            'visit_order': int(self.route_template_table.item(i, 0).text()) if self.route_template_table.item(i, 0) else i + 1,
                            'store_code': self.route_template_table.item(i, 1).text() if self.route_template_table.item(i, 1) else '',
                            'store_name': self.route_template_table.item(i, 2).text() if self.route_template_table.item(i, 2) else '',
                            'in_time': self.route_template_table.item(i, 3).text() if self.route_template_table.item(i, 3) else '',
                            'out_time': self.route_template_table.item(i, 4).text() if self.route_template_table.item(i, 4) else '',
                        }
                        visits.append(visit)
                    
                    # ルートサマリーウィジェットに反映（メソッドがあれば）
                    if hasattr(self.route_summary_widget, 'update_store_visits_from_list'):
                        self.route_summary_widget.update_store_visits_from_list(visits)
                except Exception as e:
                    print(f"ルート情報の更新中にエラー: {e}")
            
            # ボタンの有効/無効を更新
            if self.route_template_table.rowCount() == 0:
                if hasattr(self, 'route_clear_btn'):
                    self.route_clear_btn.setEnabled(False)
                if hasattr(self, 'route_delete_row_btn'):
                    self.route_delete_row_btn.setEnabled(False)

    def on_route_selection_changed(self):
        """ルート情報テーブルの選択変更時の処理"""
        selected_items = self.route_template_table.selectedItems()
        has_selection = len(selected_items) > 0
        if hasattr(self, 'route_delete_row_btn'):
            self.route_delete_row_btn.setEnabled(has_selection)

    def run_matching(self):
        """照合処理実行（仕入管理タブから実行）"""
        try:
            # ルートサマリーウィジェットの確認
            if not self.route_summary_widget:
                QMessageBox.warning(self, "警告", "ルート機能が未初期化です。ルータブが有効か確認してください。")
                return
            
            # 別テンプレ読み込み後も古い route_id が残っていると照合が誤った行に紐づくため、日付・コードで整合チェック
            try:
                _rd = self.route_summary_widget.get_route_data()
                if hasattr(self.route_summary_widget, "invalidate_stale_route_binding"):
                    self.route_summary_widget.invalidate_stale_route_binding(_rd)
            except Exception:
                pass
            
            # 現在のルートIDを取得
            route_id = self.route_summary_widget.current_route_id
            temp_saved = False
            
            # ルートIDがない場合、ルートテンプレートが読み込まれているか確認
            if not route_id:
                # ルートテンプレートのデータを確認
                route_data = self.route_summary_widget.get_route_data()
                store_visits = self.route_summary_widget.get_store_visits_data()
                
                # ルートテンプレートが読み込まれている場合、一時保存を試みる
                if route_data.get('route_code') and len(store_visits) > 0:
                    reply = QMessageBox.question(
                        self,
                        "ルートの一時保存",
                        "照合処理を実行するにはルートの保存が必要です。\nルートテンプレートの情報を一時的に保存してから照合処理を実行しますか？\n（後で削除することもできます）",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes
                    )
                    if reply == QMessageBox.Yes:
                        try:
                            # 一時保存を実行
                            self.route_summary_widget.save_data()
                            route_id = self.route_summary_widget.current_route_id
                            if route_id:
                                temp_saved = True
                                QMessageBox.information(self, "保存完了", "ルートを一時保存しました。照合処理を実行します。")
                            else:
                                QMessageBox.warning(self, "エラー", "ルートの保存に失敗しました。")
                                return
                        except Exception as e:
                            QMessageBox.warning(self, "エラー", f"ルートの保存中にエラーが発生しました:\n{str(e)}")
                            return
                    else:
                        return
                else:
                    # ルートテンプレートが読み込まれていない場合
                    QMessageBox.warning(
                        self,
                        "ルート情報なし",
                        "照合処理を実行するにはルート情報が必要です。\n"
                        "以下のいずれかを実行してください：\n"
                        "1. ルート登録タブでルートを保存する\n"
                        "2. ルートテンプレートを読み込む"
                    )
                    return
            
            # 仕入管理データの確認
            if self.inventory_data is None or len(self.inventory_data) == 0:
                # データがない場合、CSVファイル選択にフォールバック
                reply = QMessageBox.question(
                    self,
                    "データなし",
                    "仕入管理にデータがありません。\nCSVファイルを選択して処理しますか？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    # ルートサマリーウィジェットのCSVファイル選択処理を呼び出し
                    if hasattr(self.route_summary_widget, 'execute_matching_from_csv'):
                        self.route_summary_widget.execute_matching_from_csv()
                return
            
            # 時間許容誤差の設定
            tolerance, ok = QInputDialog.getInt(
                self,
                "時間許容誤差",
                "時間許容誤差（分）:",
                30, 0, 120, 1
            )
            if not ok:
                return
            
            # データをJSON形式に変換（NaN値を事前に処理）
            # テーブルから最新データを取得（手入力の変更を反映）
            self.sync_inventory_data_from_table()
            
            # NaN値を空文字列に置換してからJSON化
            clean_data = self.inventory_data.fillna('')
            purchase_data = clean_data.to_dict(orient="records")
            
            # 照合処理（デスクトップと同一 DB を直接参照）
            QMessageBox.information(self, "処理中", "照合処理を実行しています...")
            from services.inventory_store_matching_runner import (
                InventoryStoreMatchingError,
                match_stores_from_purchase_data_local,
            )
            try:
                result = match_stores_from_purchase_data_local(
                    purchase_data=purchase_data,
                    route_summary_id=route_id,
                    time_tolerance_minutes=tolerance,
                )
            except InventoryStoreMatchingError as e:
                QMessageBox.warning(self, "エラー", str(e))
                return
            
            # 結果を仕入管理ウィジェットに反映
            if result.get('status') == 'success':
                # 照合後のデータで仕入管理データを更新
                result_data = result.get('data', [])
                if result_data:
                    import pandas as pd
                    updated_df = pd.DataFrame(result_data)
                    
                    # 仕入管理ウィジェットのデータを更新
                    self.inventory_data = updated_df
                    self.filtered_data = updated_df.copy()
                    self.update_table()
                    self.update_data_count()
                
                # 店舗コード別の粗利を集計してルートサマリーを更新
                if hasattr(self.route_summary_widget, '_update_route_gross_profit_from_inventory'):
                    self.route_summary_widget._update_route_gross_profit_from_inventory(result_data)
                
                # ルートテンプレート読み込みエリアの表示を更新
                # データベースが更新された後、最新データを表示に反映
                self.refresh_route_template_view()
                
                # 結果表示
                stats = result.get('stats', {})
                matched_rows = stats.get('matched_rows', 0)
                total_rows = stats.get('total_rows', 0)
                
                msg = f"照合処理完了\n\n総行数: {total_rows}\nマッチした行数: {matched_rows}"
                msg += "\n\n仕入管理タブのデータが更新され、\nルートサマリーの想定粗利も自動計算されました。"
                QMessageBox.information(self, "照合処理完了", msg)
                
                # ルートサマリーの計算結果を更新
                if hasattr(self.route_summary_widget, 'update_calculation_results'):
                    self.route_summary_widget.update_calculation_results()
            else:
                QMessageBox.warning(self, "エラー", "照合処理に失敗しました")
                
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"照合処理中にエラーが発生しました:\n{str(e)}")
            import traceback
            traceback.print_exc()

