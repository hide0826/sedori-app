#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ワークフロー mixin。"""
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


class InventoryWorkflowMixin:
    def _sync_workflow_status_label(self) -> None:
        """ワークフロー: 〜 と ①〜⑧ 手順を1行の HTML で表示する。"""
        if not hasattr(self, "workflow_status_label") or self.workflow_status_label is None:
            return
        text = getattr(self, "_workflow_status_text", "ワークフロー: 未実行")
        emph = getattr(self, "_workflow_emphasize", False)
        step = getattr(self, "_workflow_active_step", None)
        prefix = _format_status_prefix_html(text, emph)
        pipe = _format_workflow_pipeline_html(step)
        sep = '<span style="color:#cccccc;">　</span>'
        self.workflow_status_label.setText(prefix + sep + pipe)

    def _set_workflow_pipeline_highlight(self, step: Optional[int]) -> None:
        """手順（①〜⑧）のどれを強調するか。None で強調なし。"""
        self._workflow_active_step = step
        self._sync_workflow_status_label()

    def _update_workflow_status(self, text: str, emphasize: bool = False):
        """ワークフロー状態ラベルを更新（手順リストと1行に結合）"""
        self._workflow_status_text = text
        self._workflow_emphasize = emphasize
        if "コンディション説明編集中" in text:
            self._workflow_active_step = 5
        elif text.strip() == "ワークフロー: 未実行":
            self._workflow_active_step = None
        elif "工程8まで完了" in text and "工程6まで完了" not in text:
            self._workflow_active_step = None
        self._sync_workflow_status_label()

    def _run_action_with_status(self, action_name: str, action_func):
        """押したボタン名をワークフロー表示に反映してから処理を実行"""
        step = _ACTION_TO_PIPELINE_STEP.get(action_name)
        try:
            if step is not None:
                self._workflow_active_step = step
            # 手順①〜⑧に無い操作では、直前までの工程ハイライトを維持する
            self._update_workflow_status("ワークフロー: 実行中", emphasize=True)
            # 重い処理前に表示を即時反映
            QApplication.processEvents()
        except Exception:
            pass
        try:
            return action_func()
        finally:
            # 完了後も「いまどこまで進んだか」が分かるよう、次のボタンが押されるまでハイライトを維持
            if step is not None:
                self._workflow_active_step = step
            self._update_workflow_status("ワークフロー: 待機", emphasize=False)

    def _apply_start_button_style(self, state: str):
        """
        ワークフロー状態に応じてスタートボタンの色を変更
        state: "idle"=通常, "paused"=一時停止（再開可能）, "completed"=工程8まで完了
        """
        # 現在はスタートボタンをUIから削除しているため、スタイル変更は行わない
        return

    def _stop_workflow_paused_state(self):
        """ワークフロー一時停止状態を解除し、スタートボタンを通常表示に戻す"""
        self.workflow_paused_after_step6 = False
        self._update_workflow_status("ワークフロー: 未実行")
        self._apply_start_button_style("idle")

    def _should_run_step(self, title: str, description: str) -> bool:
        """
        スタートワークフローの各工程を実行するかどうかを判定
        
        「1工程ずつ確認」がOFFのときは常にTrueを返し、そのまま進める。
        ONのときは、ユーザーに確認ダイアログを表示し、Yesのときだけ実行を続行する。
        """
        # 「1工程ずつ確認」UIを削除したため、常に確認なしで進む
        return True

    def start_inventory_workflow(self):
        """
        スタートボタンから仕入管理の一連の処理を自動実行する
        
        フロー:
        1. デフォルトフォルダを基準に仕入処理フォルダを選択
        2. 選択フォルダ内の StockList_*.csv を読み込み（CSV取込と同等）
        3. 同じフォルダ内の route_template_*.xlsx を読み込み（ルートテンプレ読込と同等）
        4. 照合処理実行
        5. SKU生成
        6. 統合保存
        7. DB保存
        8. 出品CSV生成（保存先は選択フォルダまたは既定設定）
        9. 古物台帳生成
        """
        from pathlib import Path

        # すでに工程6まで完了してコンディション説明編集待ちの場合は、再開 or ワークフロー終了を選択
        if self.workflow_paused_after_step6:
            # データが残っているか確認
            if self.filtered_data is None or len(self.filtered_data) == 0:
                QMessageBox.warning(
                    self,
                    "再開不可",
                    "仕入データが存在しないため、作業を再開できません。\n最初からワークフローを実行してください。"
                )
                self._stop_workflow_paused_state()
                return

            # 再開 / ワークフロー終了 の2択ダイアログ
            box = QMessageBox(self)
            box.setWindowTitle("スタート")
            box.setText(
                "工程6（DB保存）まで完了し、コンディション説明編集待ちの状態です。\n\n"
                "工程7から再開するか、ワークフローを終了するか選んでください。"
            )
            btn_resume = box.addButton("工程7から再開", QMessageBox.YesRole)
            btn_stop = box.addButton("ワークフロー終了", QMessageBox.NoRole)
            box.exec()
            if box.clickedButton() == btn_stop:
                self._stop_workflow_paused_state()
                QMessageBox.information(
                    self,
                    "ワークフロー終了",
                    "ワークフローを終了しました。\n再度スタートボタンで最初から実行できます。"
                )
                return

            # 出品CSV生成（保存ダイアログは従来どおり表示）
            if not self._should_run_step(
                "工程7: 出品CSV生成",
                "Amazon出品用のCSVファイルを生成します。"
            ):
                return
            self._workflow_active_step = 8
            self._update_workflow_status("ワークフロー: 実行中", emphasize=True)
            QApplication.processEvents()
            self.export_listing_csv()
            
            # 古物台帳生成
            if not self._should_run_step(
                "工程8: 古物台帳生成",
                "現在の仕入データとルート情報を古物台帳タブに転送します。"
            ):
                return
            self._set_workflow_pipeline_highlight(7)
            QApplication.processEvents()
            self.generate_antique_register()

            # 再開完了
            self.workflow_paused_after_step6 = False
            self._update_workflow_status("ワークフロー: 工程8まで完了")
            self._apply_start_button_style("completed")
            QMessageBox.information(self, "作業再開完了", "工程7および工程8の処理が完了しました。")
            return
        
        # 1. 仕入処理フォルダを選択（デフォルトフォルダを基準にする）
        base_dir = self._get_default_batch_root_dir()
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "仕入処理フォルダを選択（StockList_ と route_template_ を含むフォルダ）",
            base_dir
        )
        if not selected_dir:
            # キャンセル
            return
        
        folder_path = Path(selected_dir)
        
        # 選択フォルダを last_csv_folder として保存（出品CSVの初期フォルダにも利用）
        try:
            s = self._get_qsettings()
            s.setValue("inventory/last_csv_folder", str(folder_path))
        except Exception:
            pass
        
        # 2. StockList_ で始まる CSV を探して読み込み
        csv_candidates = sorted(folder_path.glob("StockList_*.csv"))
        if not csv_candidates:
            QMessageBox.warning(
                self,
                "CSVファイル未検出",
                f"選択したフォルダ内に『StockList_』で始まるCSVファイルが見つかりませんでした。\n\nフォルダ: {selected_dir}"
            )
            return
        
        # 最も新しいファイルを優先
        try:
            csv_path = max(csv_candidates, key=lambda p: p.stat().st_mtime)
        except Exception:
            csv_path = csv_candidates[0]
        
        # 工程1: CSV取込
        if not self._should_run_step(
            "工程1: CSV取込",
            f"選択フォルダ内の仕入リストCSVを読み込みます。\n対象ファイル: {csv_path.name}"
        ):
            return
        self._workflow_active_step = 1
        self._update_workflow_status("ワークフロー: 実行中", emphasize=True)
        QApplication.processEvents()
        self._import_csv_from_path(str(csv_path))
        
        # 3. route_template_ で始まる xlsx/xls を探して読み込み
        if not self.route_summary_widget:
            QMessageBox.warning(
                self,
                "ルート機能未初期化",
                "ルート登録タブ（ルートサマリー）が初期化されていないため、ルートテンプレートを読み込めません。"
            )
            return
        
        route_candidates = sorted(
            list(folder_path.glob("route_template_*.xlsx")) +
            list(folder_path.glob("route_template_*.xls"))
        )
        if not route_candidates:
            QMessageBox.warning(
                self,
                "ルートテンプレート未検出",
                f"選択したフォルダ内に『route_template_』で始まるExcelファイルが見つかりませんでした。\n\nフォルダ: {selected_dir}"
            )
            return
        
        try:
            route_path = max(route_candidates, key=lambda p: p.stat().st_mtime)
        except Exception:
            route_path = route_candidates[0]
        
        # 工程2: ルートテンプレート読込
        if not self._should_run_step(
            "工程2: ルートテンプレ読込",
            f"選択フォルダ内のルートテンプレートを読み込みます。\n対象ファイル: {route_path.name}"
        ):
            return
        
        self._set_workflow_pipeline_highlight(2)
        QApplication.processEvents()
        # ルートテンプレ読込と同等の処理（ダイアログを出さずに直接読み込み）
        try:
            loaded_path = self.route_summary_widget.load_template(str(route_path))
            if not loaded_path:
                QMessageBox.warning(
                    self,
                    "ルートテンプレート読込失敗",
                    "ルートテンプレートの読み込みに失敗したため、後続の処理を中止します。"
                )
                return
            # 仕入管理タブ側のルート情報エリアも更新
            self.refresh_route_template_view()
        except Exception as e:
            QMessageBox.critical(
                self,
                "ルートテンプレート読込エラー",
                f"ルートテンプレートの読み込み中にエラーが発生しました:\n{str(e)}"
            )
            return
        
        # 4. 照合処理実行
        if not self._should_run_step(
            "工程3: 照合処理実行",
            "仕入データとルート情報の照合処理を実行します。"
        ):
            return
        self._set_workflow_pipeline_highlight(3)
        QApplication.processEvents()
        self.run_matching()
        
        # 照合処理で inventory_data が更新されている前提で後続処理を実行
        if self.inventory_data is None or len(self.inventory_data) == 0:
            QMessageBox.warning(
                self,
                "データなし",
                "照合処理後の仕入データが存在しないため、後続の処理を中止します。"
            )
            return
        
        # 5. SKU生成
        if not self._should_run_step(
            "工程4: SKU生成",
            "仕入データにSKUを自動生成します。"
        ):
            return
        self._set_workflow_pipeline_highlight(4)
        QApplication.processEvents()
        self.generate_sku()
        
        # 6. 統合保存
        if not self._should_run_step(
            "工程5: 統合保存",
            "現在の仕入データとルート情報を統合スナップショットとして保存します。"
        ):
            return
        self._set_workflow_pipeline_highlight(None)
        QApplication.processEvents()
        self.save_combined_snapshot()
        
        # 7. DB保存
        if not self._should_run_step(
            "工程6: DB保存",
            "コンディション（説明）の編集確認のあと、仕入データをデータベースに保存します。"
        ):
            return
        self._set_workflow_pipeline_highlight(6)
        QApplication.processEvents()
        if not self._confirm_condition_edit_then_save_to_databases():
            self._update_workflow_status("ワークフロー: 工程6で中断（コンディション編集待ち）", emphasize=True)
            return

        # 8. 出品CSV生成（保存ダイアログは従来どおり表示）
        if not self._should_run_step(
            "工程7: 出品CSV生成",
            "Amazon出品用のCSVファイルを生成します。"
        ):
            return
        self._set_workflow_pipeline_highlight(8)
        QApplication.processEvents()
        self.export_listing_csv()
        
        # 9. 古物台帳生成
        if not self._should_run_step(
            "工程8: 古物台帳生成",
            "現在の仕入データとルート情報を古物台帳タブに転送します。"
        ):
            return
        self._set_workflow_pipeline_highlight(7)
        QApplication.processEvents()
        self.generate_antique_register()

        # 全工程完了
        self._update_workflow_status("ワークフロー: 工程8まで完了")
        self._apply_start_button_style("completed")

    def generate_antique_register(self):
        """古物台帳生成：仕入データ＋ルート情報を古物台帳タブへ転送"""
        if self.filtered_data is None or len(self.filtered_data) == 0:
            QMessageBox.warning(self, "エラー", "データがありません。先に仕入データを取り込んでください。")
            return
        
        # 古物台帳ウィジェットの参照確認
        if not self.antique_widget:
            QMessageBox.warning(
                self, 
                "エラー", 
                "古物台帳タブが初期化されていません。\nアプリケーションを再起動してください。"
            )
            return
        
        try:
            # 仕入データを辞書形式に変換
            data_list = self.filtered_data.to_dict('records')
            
            # ルート情報を取得（あれば）
            route_info = None
            if self.route_summary_widget:
                try:
                    route_data = self.route_summary_widget.get_route_data()
                    store_visits = self.route_summary_widget.get_store_visits_data()
                    if route_data and len(store_visits) > 0:
                        route_info = {
                            'route': route_data,
                            'visits': store_visits
                        }
                except Exception:
                    # ルート情報の取得に失敗しても処理は継続
                    pass
            
            # 古物台帳タブにデータを転送
            self.antique_widget.import_inventory_data(data_list, route_info)
            
            # 古物台帳タブに切り替え
            # 親ウィジェット（MainWindow）のタブウィジェットを取得
            parent = self.parent()
            while parent:
                if hasattr(parent, 'tab_widget'):
                    # MainWindowのtab_widgetを取得
                    tab_widget = parent.tab_widget
                    # 古物台帳タブのインデックスを探す
                    for i in range(tab_widget.count()):
                        if tab_widget.widget(i) == self.antique_widget:
                            tab_widget.setCurrentIndex(i)
                            break
                    break
                parent = parent.parent()
            
            # ユーザーに案内メッセージを表示
            QMessageBox.information(
                self,
                "古物台帳タブへ転送完了",
                f"仕入データ {len(data_list)} 件を古物台帳タブへ転送しました。\n"
                "古物台帳タブで内容を確認・編集してから、台帳登録・出力を行ってください。"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"古物台帳タブへのデータ転送中にエラーが発生しました:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def setup_workflow_panel(self):
        """ワークフローパネルの設定（改良版）"""
        # 作業フローグループ
        workflow_group = QGroupBox("作業フロー")
        workflow_layout = QVBoxLayout(workflow_group)
        
        # 作業フローを横展開で表示
        workflow_steps_layout = QHBoxLayout()
        
        # 各ステップのボタンを作成
        steps = [
            ("1. 仕入データ取込", "CSVファイルから仕入データを読み込み", "待機中"),
            ("2. SKU生成", "商品にSKUを自動生成・重複チェック", "待機中"),
            ("3. 出品CSV生成", "プライスター形式の出品CSVを生成", "待機中"),
            ("4. ドッキングリスト生成", "倉庫作業用ピッキングリストを生成", "待機中"),
            ("5. 古物台帳生成", "法定要件に準拠した古物台帳を生成", "待機中")
        ]
        
        self.workflow_buttons = []
        for i, (title, description, status) in enumerate(steps):
            step_widget = QWidget()
            step_layout = QVBoxLayout(step_widget)
            step_layout.setContentsMargins(5, 5, 5, 5)
            
            # ステップボタン
            step_btn = QPushButton(title)
            step_btn.setEnabled(False)
            step_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6c757d;
                    color: white;
                    border: none;
                    padding: 8px 12px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:enabled {
                    background-color: #28a745;
                }
            """)
            step_layout.addWidget(step_btn)
            
            # 説明ラベル
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("font-size: 10px; color: #666;")
            step_layout.addWidget(desc_label)
            
            # ステータスラベル
            status_label = QLabel(status)
            status_label.setStyleSheet("font-size: 10px; color: #666;")
            step_layout.addWidget(status_label)
            
            self.workflow_buttons.append((step_btn, status_label))
            workflow_steps_layout.addWidget(step_widget)
        
        workflow_layout.addLayout(workflow_steps_layout)
        
        # 進捗状況
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("進捗状況:"))
        progress_layout.addWidget(QLabel("0%"))
        progress_layout.addWidget(QLabel("0%"))
        progress_layout.addWidget(QLabel("準備完了"))
        progress_layout.addStretch()
        workflow_layout.addLayout(progress_layout)
        
        # 一括実行コントロール
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("一括実行コントロール:"))
        
        auto_exec_btn = QPushButton("全自動実行")
        auto_exec_btn.setStyleSheet("background-color: #28a745; color: white;")
        control_layout.addWidget(auto_exec_btn)
        
        pause_btn = QPushButton("一時停止")
        pause_btn.setStyleSheet("background-color: #6c757d; color: white;")
        control_layout.addWidget(pause_btn)
        
        reset_btn = QPushButton("リセット")
        reset_btn.setStyleSheet("background-color: #dc3545; color: white;")
        control_layout.addWidget(reset_btn)
        
        control_layout.addStretch()
        workflow_layout.addLayout(control_layout)
        
        # ワークフローグループをレイアウトに追加
        self.layout().addWidget(workflow_group)

