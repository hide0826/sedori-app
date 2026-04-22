#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
価格改定ルール設定ウィジェット

既存FastAPIのルール設定機能を活用
- ルール設定の取得・更新
- 出品日数別のアクション設定
- priceTrace設定
- Q4ルール適用オプション
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QSpinBox, QDoubleSpinBox, QGroupBox, QTabWidget,
    QMessageBox, QFrame, QSplitter
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QColor
import json
from typing import Dict, List, Any, Optional


class NoWheelComboBox(QComboBox):
    """誤操作防止: マウスホイールで値変更しないコンボボックス"""

    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """誤操作防止: マウスホイールで値変更しないスピンボックス"""

    def wheelEvent(self, event):
        event.ignore()


class RepricerSettingsWorker(QThread):
    """ルール設定処理のワーカースレッド"""
    config_loaded = Signal(dict)
    config_saved = Signal(bool)
    error_occurred = Signal(str)
    
    def __init__(self, api_client, action="load", config_data=None, mode="standard"):
        super().__init__()
        self.api_client = api_client
        self.action = action
        self.config_data = config_data
        self.mode = mode
        
    def run(self):
        """ルール設定の処理"""
        try:
            if self.action == "load":
                # 設定の取得
                config = self.api_client.get_repricer_config(mode=self.mode)
                self.config_loaded.emit(config)
            elif self.action == "save":
                # 設定の保存
                success = self.api_client.update_repricer_config(self.config_data, mode=self.mode)
                self.config_saved.emit(success)
                
        except Exception as e:
            self.error_occurred.emit(str(e))


class RepricerSettingsWidget(QWidget):
    """価格改定ルール設定ウィジェット"""
    
    def __init__(self, api_client, mode="standard"):
        super().__init__()
        self.api_client = api_client
        self.mode = mode if mode in ("standard", "369") else "standard"
        self.config_data = None
        self.rules_table = None
        
        # UIの初期化
        self.setup_ui()
        
        # 設定の読み込み
        self.load_config()
        
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 上部：基本設定エリア
        self.setup_basic_settings()

        # 3-6-9用か通常用かで設定UIを分岐
        if self.mode == "369":
            self.setup_369_rules_panel()
        else:
            # 中央：ルール設定テーブル（通常タブのみ）
            self.setup_rules_table()
        
        # 下部：アクションボタン
        self.setup_action_buttons()
        
    def setup_basic_settings(self):
        """基本設定エリアの設定"""
        basic_group = QGroupBox("基本設定")
        basic_layout = QGridLayout(basic_group)
        
        # 利益率ガード設定
        basic_layout.addWidget(QLabel("利益率ガード:"), 0, 0)
        self.profit_guard_spin = QDoubleSpinBox()
        self.profit_guard_spin.setRange(1.0, 10.0)
        self.profit_guard_spin.setSingleStep(0.1)
        self.profit_guard_spin.setValue(1.1)
        self.profit_guard_spin.setSuffix("倍")
        basic_layout.addWidget(self.profit_guard_spin, 0, 1)
        
        # Q4ルール適用
        self.q4_rule_check = QCheckBox("Q4ルールを適用 (10月第1週)")
        basic_layout.addWidget(self.q4_rule_check, 1, 0, 1, 2)
        
        # 除外SKU設定
        basic_layout.addWidget(QLabel("除外SKU:"), 2, 0)
        self.excluded_skus_edit = QLineEdit()
        self.excluded_skus_edit.setPlaceholderText("カンマ区切りで入力 (例: SKU1,SKU2,SKU3)")
        basic_layout.addWidget(self.excluded_skus_edit, 2, 1)
        
        self.layout().addWidget(basic_group)

    def setup_369_rules_panel(self):
        """3-6-9価格改定の専用設定UI"""
        profile_group = QGroupBox("3-6-9 改定ルール設定")
        profile_layout = QVBoxLayout(profile_group)

        self.profile_tab = QTabWidget()
        self.profile_rule_tables = {}
        self.profile_tp_spins = {}
        self.profile_akaji_preset_combos = {}
        self.profile_takane_preset_combos = {}
        self.exception_rules_table = None
        for profile_key, label_text in [("3", "3ルール"), ("6", "6ルール"), ("9", "9ルール")]:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tp_group = QGroupBox("TP保持率設定")
            tp_layout = QHBoxLayout(tp_group)
            self.profile_tp_spins[profile_key] = {}
            tp_labels = [
                ("tp0", "TP0の利益保持率(%)"),
                ("tp1", "TP1の利益保持率(%)"),
                ("tp2", "TP2の利益保持率(%)"),
                ("tp3", "TP3の利益保持率(%)"),
            ]
            for tp_key, tp_label in tp_labels:
                tp_layout.addWidget(QLabel(tp_label))
                spin = NoWheelDoubleSpinBox()
                spin.setRange(0.0, 300.0)
                spin.setSingleStep(1.0)
                spin.setSuffix("%")
                spin.setMaximumWidth(92)
                self.profile_tp_spins[profile_key][tp_key] = spin
                tp_layout.addWidget(spin)
            # akaji/takane 一括プリセット
            tp_layout.addSpacing(16)
            tp_layout.addWidget(QLabel("akaji一括(%):"))
            akaji_preset_combo = NoWheelComboBox()
            for v in range(1, 11):
                akaji_preset_combo.addItem(f"{v}%", v)
            akaji_preset_combo.setMaximumWidth(88)
            self.profile_akaji_preset_combos[profile_key] = akaji_preset_combo
            tp_layout.addWidget(akaji_preset_combo)

            tp_layout.addWidget(QLabel("takane一括(%):"))
            takane_preset_combo = NoWheelComboBox()
            for v in range(0, 11):
                takane_preset_combo.addItem(f"{v}%", v)
            takane_preset_combo.setMaximumWidth(88)
            self.profile_takane_preset_combos[profile_key] = takane_preset_combo
            tp_layout.addWidget(takane_preset_combo)

            apply_preset_btn = QPushButton("akaji/takane を全行に適用")
            apply_preset_btn.clicked.connect(lambda _checked=False, key=profile_key: self.apply_percent_preset_to_profile_rules(key))
            tp_layout.addWidget(apply_preset_btn)
            tp_layout.addStretch()
            tab_layout.addWidget(tp_group)
            table = self._create_rules_table_widget(profile_key=profile_key)
            self.profile_rule_tables[profile_key] = table
            self.setup_default_rules(table=table, connect_signals=True)
            tab_layout.addWidget(table)
            self.profile_tab.addTab(tab, label_text)

        # 例外タブ（アプリ運用以前の在庫向け）
        exception_tab = QWidget()
        exception_layout = QVBoxLayout(exception_tab)
        exception_note = QLabel("仕入DBに存在しない旧在庫向けの改定ルールです。")
        exception_note.setStyleSheet("color: #aaaaaa;")
        exception_layout.addWidget(exception_note)
        # 例外タブは通常価格改定と同じ列構成（TP/akaji下限なし）
        self.exception_rules_table = self._create_rules_table_widget(profile_key="exception", force_standard_columns=True)
        self.setup_default_rules(table=self.exception_rules_table, connect_signals=True)
        exception_layout.addWidget(self.exception_rules_table)
        self.profile_tab.addTab(exception_tab, "例外")

        profile_layout.addWidget(self.profile_tab)
        self.layout().addWidget(profile_group)

        common_group = QGroupBox("3-6-9 共通設定")
        common_layout = QGridLayout(common_group)
        common_layout.addWidget(QLabel("改定間隔(日):"), 0, 0)
        self.interval_days_spin = QSpinBox()
        self.interval_days_spin.setRange(1, 90)
        self.interval_days_spin.setValue(7)
        common_layout.addWidget(self.interval_days_spin, 0, 1)

        common_layout.addWidget(QLabel("デフォルトプロファイル:"), 1, 0)
        self.default_profile_combo = QComboBox()
        self.default_profile_combo.addItem("3ルール", "3")
        self.default_profile_combo.addItem("6ルール", "6")
        self.default_profile_combo.addItem("9ルール", "9")
        common_layout.addWidget(self.default_profile_combo, 1, 1)

        self.alert_enabled_check = QCheckBox("アラートを理由欄に表示する")
        self.alert_enabled_check.setChecked(True)
        common_layout.addWidget(self.alert_enabled_check, 2, 0, 1, 2)

        common_layout.addWidget(QLabel("アラート接頭辞:"), 3, 0)
        self.alert_prefix_edit = QLineEdit()
        self.alert_prefix_edit.setText("ALERT")
        common_layout.addWidget(self.alert_prefix_edit, 3, 1)

        common_layout.setColumnStretch(2, 1)
        self.layout().addWidget(common_group)

    def apply_percent_preset_to_profile_rules(self, profile_key: str):
        """選択プロファイルの全行に akaji/takane プリセット(%)を一括適用する。"""
        table = self.profile_rule_tables.get(profile_key)
        if table is None:
            return
        akaji_combo = self.profile_akaji_preset_combos.get(profile_key)
        takane_combo = self.profile_takane_preset_combos.get(profile_key)
        akaji_percent = int(akaji_combo.currentData()) if akaji_combo else 1
        takane_percent = int(takane_combo.currentData()) if takane_combo else 0
        updated_rows = 0
        for i in range(table.rowCount()):
            akaji_cell = table.cellWidget(i, 4)
            if akaji_cell:
                idx = akaji_cell.findData(akaji_percent)
                if idx >= 0:
                    akaji_cell.setCurrentIndex(idx)
            takane_cell = table.cellWidget(i, 5)
            if takane_cell:
                idx = takane_cell.findData(takane_percent)
                if idx >= 0:
                    takane_cell.setCurrentIndex(idx)
            updated_rows += 1
        QMessageBox.information(
            self,
            "一括適用完了",
            f"{profile_key}ルールの {updated_rows} 行に\n"
            f"akaji下限: {akaji_percent}% / takane上限: {takane_percent}% を適用しました。"
        )
        
    def setup_rules_table(self):
        """ルール設定テーブルの設定"""
        rules_group = QGroupBox("価格改定ルール設定")
        rules_layout = QVBoxLayout(rules_group)

        # テーブルの作成
        self.rules_table = self._create_rules_table_widget()
        
        # デフォルトルールの設定
        self.setup_default_rules(table=self.rules_table, connect_signals=True)
        
        rules_layout.addWidget(self.rules_table)
        self.layout().addWidget(rules_group)

    def _create_rules_table_widget(self, profile_key=None, force_standard_columns=False):
        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        is_369_table = (self.mode == "369") and (not force_standard_columns)
        if is_369_table:
            columns = ['出品日数', 'アクション', 'priceTrace設定', 'TP', 'akaji下限(%)', 'takane上限(%)']
        else:
            columns = ['出品日数', 'アクション', 'priceTrace設定']
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setProperty("is_369_table", is_369_table)
        return table

    def setup_default_rules(self, table=None, connect_signals=False):
        """デフォルトルールの設定"""
        table = table or self.rules_table
        is_369_table = bool(table.property("is_369_table"))
        # 出品日数の範囲設定
        day_ranges = [
            (1, 30), (31, 60), (61, 90), (91, 120), (121, 150),
            (151, 180), (181, 210), (211, 240), (241, 270),
            (271, 300), (301, 330), (331, 360), (361, 999)
        ]
        
        table.setRowCount(len(day_ranges))
        
        # アクションの選択肢（日本語）
        actions = [
            ("maintain", "維持"),
            ("priceTrace", "priceTrace"),
            ("price_down_1", "1%値下げ"),
            ("price_down_2", "2%値下げ"),
            ("price_down_3", "3%値下げ"),
            ("price_down_4", "4%値下げ"),
            ("price_down_ignore_1", "1%利益無視値下げ"),
            ("price_down_ignore_2", "2%利益無視値下げ"),
            ("price_down_ignore_3", "3%利益無視値下げ"),
            ("price_down_ignore_4", "4%利益無視値下げ"),
            ("exclude", "対象外")
        ]
        if is_369_table:
            actions.insert(2, ("tp_down", "TP値下げ"))
        
        # priceTrace設定の選択肢（日本語）
        price_trace_options = [
            (0, "追従無し"),
            (1, "FBA状態合わせ"),
            (2, "状態合わせ"),
            (3, "FBA最安値"),
            (4, "最安値"),
            (5, "カート価格")
        ]

        tp_options = [("tp0", "TP0"), ("tp1", "TP1"), ("tp2", "TP2"), ("tp3", "TP3")]
        akaji_percent_options = [(v, f"{v}%") for v in range(1, 11)]
        takane_percent_options = [(v, f"{v}%") for v in range(0, 11)]
        
        for i, (start_day, end_day) in enumerate(day_ranges):
            # 出品日数
            if end_day == 999:
                days_text = f"{start_day}日～"
            else:
                days_text = f"{start_day}-{end_day}日"
            days_item = QTableWidgetItem(days_text)
            days_item.setFlags(days_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(i, 0, days_item)
            
            # アクション選択
            action_combo = NoWheelComboBox()
            for action_key, action_text in actions:
                action_combo.addItem(action_text, action_key)
            # スクロール無効化（誤設定防止）
            action_combo.setEditable(False)
            if connect_signals:
                action_combo.currentTextChanged.connect(lambda text, row=i, tbl=table: self.on_action_changed(row, text, tbl))
            table.setCellWidget(i, 1, action_combo)
            
            # priceTrace設定
            price_trace_combo = NoWheelComboBox()
            for value, text in price_trace_options:
                price_trace_combo.addItem(text, value)
            # スクロール無効化（誤設定防止）
            price_trace_combo.setEditable(False)
            table.setCellWidget(i, 2, price_trace_combo)

            if is_369_table:
                # TP設定
                tp_combo = NoWheelComboBox()
                for tp_key, tp_label in tp_options:
                    tp_combo.addItem(tp_label, tp_key)
                tp_combo.setEditable(False)
                table.setCellWidget(i, 3, tp_combo)

                # akaji下限(%)設定
                akaji_percent_combo = NoWheelComboBox()
                for percent_value, percent_text in akaji_percent_options:
                    akaji_percent_combo.addItem(percent_text, percent_value)
                akaji_percent_combo.setEditable(False)
                table.setCellWidget(i, 4, akaji_percent_combo)

                # takane上限(%)設定
                takane_percent_combo = NoWheelComboBox()
                for percent_value, percent_text in takane_percent_options:
                    takane_percent_combo.addItem(percent_text, percent_value)
                takane_percent_combo.setEditable(False)
                table.setCellWidget(i, 5, takane_percent_combo)
        
        # 列幅の調整
        table.resizeColumnsToContents()
        
        # 列幅の固定設定
        table.setColumnWidth(0, 120)  # 出品日数
        table.setColumnWidth(1, 200)  # アクション
        table.setColumnWidth(2, 150)  # priceTrace設定
        if is_369_table:
            table.setColumnWidth(3, 100)  # TP
            table.setColumnWidth(4, 120)  # akaji下限(%)
            table.setColumnWidth(5, 120)  # takane上限(%)
        
        # 初期状態でpriceTrace設定を非表示
        self.update_price_trace_visibility(table)
        
    def setup_action_buttons(self):
        """アクションボタンエリアの設定"""
        button_layout = QHBoxLayout()
        
        # 設定読み込みボタン
        self.load_btn = QPushButton("設定読み込み")
        self.load_btn.clicked.connect(self.load_config)
        button_layout.addWidget(self.load_btn)
        
        # 設定保存ボタン
        self.save_btn = QPushButton("設定保存")
        self.save_btn.clicked.connect(self.save_config)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        button_layout.addWidget(self.save_btn)
        
        # デフォルト設定ボタン
        self.default_btn = QPushButton("デフォルト設定")
        self.default_btn.clicked.connect(self.reset_to_default)
        button_layout.addWidget(self.default_btn)
        
        button_layout.addStretch()
        
        self.layout().addLayout(button_layout)
        
    def load_config(self):
        """設定の読み込み"""
        try:
            # ワーカースレッドの作成と実行
            self.worker = RepricerSettingsWorker(self.api_client, "load", mode=self.mode)
            self.worker.config_loaded.connect(self.on_config_loaded)
            self.worker.error_occurred.connect(self.on_error)
            self.worker.start()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"設定の読み込みに失敗しました:\n{str(e)}")
    
    def save_config(self):
        """設定の保存"""
        try:
            # 現在の設定を収集
            config_data = self.collect_current_config()
            
            # ワーカースレッドの作成と実行
            self.worker = RepricerSettingsWorker(self.api_client, "save", config_data, mode=self.mode)
            self.worker.config_saved.connect(self.on_config_saved)
            self.worker.error_occurred.connect(self.on_error)
            self.worker.start()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"設定の保存に失敗しました:\n{str(e)}")
    
    def collect_current_config(self):
        """現在の設定を収集"""
        if self.mode == "369":
            return self.collect_current_config_369()
        config = {
            "profit_guard_percentage": self.profit_guard_spin.value(),
            "q4_rule_enabled": self.q4_rule_check.isChecked(),
            "excluded_skus": [sku.strip() for sku in self.excluded_skus_edit.text().split(",") if sku.strip()],
            "reprice_rules": []  # リスト形式に変更
        }
        
        config["reprice_rules"] = self._collect_rules_from_table(self.rules_table)
        
        return config

    def collect_current_config_369(self):
        """3-6-9専用設定を収集"""
        default_tp_rates = {
            "3": {"tp0": 95, "tp1": 75, "tp2": 60, "tp3": 0},
            "6": {"tp0": 90, "tp1": 70, "tp2": 55, "tp3": 0},
            "9": {"tp0": 85, "tp1": 65, "tp2": 50, "tp3": 0},
        }
        existing_profiles = {}
        if isinstance(self.config_data, dict):
            existing_profiles = self.config_data.get("rule_profiles", {}) or {}
        rule_profiles = {}
        for profile_key, table in self.profile_rule_tables.items():
            existing_tp = (existing_profiles.get(profile_key, {}) or {}).get("tp_rates", {})
            spin_map = self.profile_tp_spins.get(profile_key, {})
            rule_profiles[profile_key] = {
                "tp_rates": {
                    "tp0": float(spin_map.get("tp0").value() if spin_map.get("tp0") else existing_tp.get("tp0", default_tp_rates[profile_key]["tp0"])),
                    "tp1": float(spin_map.get("tp1").value() if spin_map.get("tp1") else existing_tp.get("tp1", default_tp_rates[profile_key]["tp1"])),
                    "tp2": float(spin_map.get("tp2").value() if spin_map.get("tp2") else existing_tp.get("tp2", default_tp_rates[profile_key]["tp2"])),
                    "tp3": float(spin_map.get("tp3").value() if spin_map.get("tp3") else existing_tp.get("tp3", default_tp_rates[profile_key]["tp3"])),
                },
                "reprice_rules": self._collect_rules_from_table(table),
            }
        config = {
            "profit_guard_percentage": self.profit_guard_spin.value(),
            "q4_rule_enabled": self.q4_rule_check.isChecked(),
            "excluded_skus": [sku.strip() for sku in self.excluded_skus_edit.text().split(",") if sku.strip()],
            "reprice_rules": self.config_data.get("reprice_rules", []) if isinstance(self.config_data, dict) else [],
            "rule_profiles": rule_profiles,
            "exception_reprice_rules": self._collect_rules_from_table(self.exception_rules_table) if self.exception_rules_table else [],
            "default_profile": self.default_profile_combo.currentData(),
            "interval_days": self.interval_days_spin.value(),
            "alerts": {
                "enabled": self.alert_enabled_check.isChecked(),
                "reason_prefix": self.alert_prefix_edit.text().strip() or "ALERT",
            },
        }
        return config

    def _collect_rules_from_table(self, table):
        rules = []
        is_369_table = bool(table.property("is_369_table"))
        for i in range(table.rowCount()):
            days_item = table.item(i, 0)
            if not days_item:
                continue
            days_text = days_item.text()
            if "～" in days_text:
                end_day = 999
            else:
                end_day = int(days_text.split("-")[1].replace("日", ""))
            action_combo = table.cellWidget(i, 1)
            price_trace_combo = table.cellWidget(i, 2)
            tp_combo = table.cellWidget(i, 3) if is_369_table else None
            akaji_percent_combo = table.cellWidget(i, 4) if is_369_table else None
            takane_percent_combo = table.cellWidget(i, 5) if is_369_table else None
            if action_combo and price_trace_combo:
                action = action_combo.currentData()
                price_trace = price_trace_combo.currentData()
                tp_target = tp_combo.currentData() if tp_combo else "tp0"
                akaji_drop_percent = int(akaji_percent_combo.currentData()) if akaji_percent_combo else 1
                takane_rise_percent = int(takane_percent_combo.currentData()) if takane_percent_combo else 0
                if isinstance(action, str) and action.startswith("price_down_ignore_"):
                    action = "price_down_ignore"
                rules.append({
                    "days_from": end_day,
                    "action": action,
                    "value": price_trace,
                })
                if is_369_table:
                    rules[-1]["tp_target"] = tp_target
                    rules[-1]["akaji_drop_percent"] = akaji_drop_percent
                    rules[-1]["takane_rise_percent"] = takane_rise_percent
        return rules
    
    def on_config_loaded(self, config):
        """設定読み込み完了時の処理"""
        self.config_data = config
        
        # 基本設定の更新
        self.profit_guard_spin.setValue(config.get("profit_guard_percentage", 1.1))
        self.q4_rule_check.setChecked(config.get("q4_rule_enabled", False))
        
        excluded_skus = config.get("excluded_skus", [])
        self.excluded_skus_edit.setText(", ".join(excluded_skus))
        
        if self.mode == "369":
            self.apply_369_config(config)
        else:
            # ルール設定の更新（リスト形式から辞書形式に変換）
            rules_list = config.get("reprice_rules", [])
            rules_dict = {}
            for rule in rules_list:
                days_from = rule.get("days_from")
                if days_from:
                    rules_dict[str(days_from)] = {
                        "action": rule.get("action", "maintain"),
                        "priceTrace": rule.get("value", 0),
                        "tp_target": rule.get("tp_target", "tp0"),
                        "akaji_drop_percent": rule.get("akaji_drop_percent", 1),
                        "takane_rise_percent": rule.get("takane_rise_percent", 0),
                    }
            self.update_rules_table(rules_dict)
            
            # priceTrace設定の表示制御を更新
            self.update_price_trace_visibility()
        
        # 起動時は「起動しています○○%」のプログレスで案内するため、ここではポップアップしない
    
    def on_config_saved(self, success):
        """設定保存完了時の処理"""
        if success:
            QMessageBox.information(self, "設定保存完了", "設定を正常に保存しました")
        else:
            QMessageBox.warning(self, "設定保存失敗", "設定の保存に失敗しました")

    def apply_369_config(self, config):
        """3-6-9設定反映"""
        default_rules = config.get("reprice_rules", [])
        rules_dict_default = {}
        for rule in default_rules:
            days_from = rule.get("days_from")
            if days_from:
                rules_dict_default[str(days_from)] = {
                    "action": rule.get("action", "maintain"),
                    "priceTrace": rule.get("value", 0),
                    "tp_target": rule.get("tp_target", "tp0"),
                    "akaji_drop_percent": rule.get("akaji_drop_percent", 1),
                    "takane_rise_percent": rule.get("takane_rise_percent", 0),
                }
        profiles = config.get("rule_profiles", {}) or {}
        for profile_key, table in self.profile_rule_tables.items():
            tp_rates = (profiles.get(profile_key) or {}).get("tp_rates", {})
            default_tp = {
                "3": {"tp0": 95, "tp1": 75, "tp2": 60, "tp3": 0},
                "6": {"tp0": 90, "tp1": 70, "tp2": 55, "tp3": 0},
                "9": {"tp0": 85, "tp1": 65, "tp2": 50, "tp3": 0},
            }
            spin_map = self.profile_tp_spins.get(profile_key, {})
            for tp_key, spin in spin_map.items():
                spin.setValue(float(tp_rates.get(tp_key, default_tp.get(profile_key, {}).get(tp_key, 0))))

            profile_rules = (profiles.get(profile_key) or {}).get("reprice_rules", [])
            if not profile_rules:
                self.update_rules_table(rules_dict_default, table=table)
                continue
            rules_dict = {}
            for rule in profile_rules:
                days_from = rule.get("days_from")
                if days_from:
                    rules_dict[str(days_from)] = {
                        "action": rule.get("action", "maintain"),
                        "priceTrace": rule.get("value", 0),
                        "tp_target": rule.get("tp_target", "tp0"),
                        "akaji_drop_percent": rule.get("akaji_drop_percent", 1),
                        "takane_rise_percent": rule.get("takane_rise_percent", 0),
                    }
            self.update_rules_table(rules_dict, table=table)

        if self.exception_rules_table is not None:
            exception_rules = config.get("exception_reprice_rules", [])
            if not exception_rules:
                self.update_rules_table(rules_dict_default, table=self.exception_rules_table)
            else:
                exception_rules_dict = {}
                for rule in exception_rules:
                    days_from = rule.get("days_from")
                    if days_from:
                        exception_rules_dict[str(days_from)] = {
                            "action": rule.get("action", "maintain"),
                            "priceTrace": rule.get("value", 0),
                        }
                self.update_rules_table(exception_rules_dict, table=self.exception_rules_table)

        interval_days = int(config.get("interval_days", 7) or 7)
        self.interval_days_spin.setValue(max(1, interval_days))

        default_profile = str(config.get("default_profile", "6"))
        index = self.default_profile_combo.findData(default_profile)
        if index >= 0:
            self.default_profile_combo.setCurrentIndex(index)

        alerts = config.get("alerts", {}) or {}
        self.alert_enabled_check.setChecked(bool(alerts.get("enabled", True)))
        self.alert_prefix_edit.setText(str(alerts.get("reason_prefix", "ALERT")))
    
    def on_error(self, error_message):
        """エラー時の処理"""
        QMessageBox.critical(self, "エラー", f"処理中にエラーが発生しました:\n{error_message}")
    
    def update_rules_table(self, rules_dict, table=None):
        """ルールテーブルの更新"""
        table = table or self.rules_table
        is_369_table = bool(table.property("is_369_table"))
        for i in range(table.rowCount()):
            days_item = table.item(i, 0)
            if days_item:
                days_text = days_item.text()
                # "361日～" の場合は 999 を使用
                if "～" in days_text:
                    end_day = "999"
                else:
                    end_day = days_text.split("-")[1].replace("日", "")
                
                if end_day in rules_dict:
                    rule = rules_dict[end_day]
                    
                    # アクションの設定
                    action_combo = table.cellWidget(i, 1)
                    if action_combo:
                        action = rule.get("action", "maintain")
                        
                        # 既存API形式のprice_down_ignoreを適切な形式に変換
                        if action == "price_down_ignore":
                            # デフォルトで1%利益無視値下げを選択
                            action = "price_down_ignore_1"
                        
                        index = action_combo.findData(action)
                        if index >= 0:
                            action_combo.setCurrentIndex(index)
                    
                    # priceTrace設定
                    price_trace_combo = table.cellWidget(i, 2)
                    if price_trace_combo:
                        price_trace = rule.get("priceTrace", 0)
                        index = price_trace_combo.findData(price_trace)
                        if index >= 0:
                            price_trace_combo.setCurrentIndex(index)

                    if is_369_table:
                        # TP設定
                        tp_combo = table.cellWidget(i, 3)
                        if tp_combo:
                            tp_target = str(rule.get("tp_target", "tp0")).lower()
                            index = tp_combo.findData(tp_target)
                            if index >= 0:
                                tp_combo.setCurrentIndex(index)

                        # akaji下限(%)設定
                        akaji_percent_combo = table.cellWidget(i, 4)
                        if akaji_percent_combo:
                            akaji_drop_percent = int(rule.get("akaji_drop_percent", 1) or 1)
                            index = akaji_percent_combo.findData(akaji_drop_percent)
                            if index >= 0:
                                akaji_percent_combo.setCurrentIndex(index)

                        # takane上限(%)設定
                        takane_percent_combo = table.cellWidget(i, 5)
                        if takane_percent_combo:
                            takane_rise_percent = int(rule.get("takane_rise_percent", 0) or 0)
                            index = takane_percent_combo.findData(takane_rise_percent)
                            if index >= 0:
                                takane_percent_combo.setCurrentIndex(index)
    
    def reset_to_default(self):
        """デフォルト設定にリセット"""
        reply = QMessageBox.question(
            self, 
            "デフォルト設定確認", 
            "デフォルト設定にリセットしますか？\n現在の設定は失われます。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # デフォルト設定の適用
            self.profit_guard_spin.setValue(1.1)
            self.q4_rule_check.setChecked(False)
            self.excluded_skus_edit.clear()
            if self.mode == "369":
                for table in self.profile_rule_tables.values():
                    self.setup_default_rules(table=table, connect_signals=False)
                    self.update_price_trace_visibility(table)
                if self.exception_rules_table is not None:
                    self.setup_default_rules(table=self.exception_rules_table, connect_signals=False)
                    self.update_price_trace_visibility(self.exception_rules_table)
                default_tp = {
                    "3": {"tp0": 95, "tp1": 75, "tp2": 60, "tp3": 0},
                    "6": {"tp0": 90, "tp1": 70, "tp2": 55, "tp3": 0},
                    "9": {"tp0": 85, "tp1": 65, "tp2": 50, "tp3": 0},
                }
                for profile_key, spin_map in self.profile_tp_spins.items():
                    for tp_key, spin in spin_map.items():
                        spin.setValue(float(default_tp.get(profile_key, {}).get(tp_key, 0)))
                self.default_profile_combo.setCurrentIndex(self.default_profile_combo.findData("6"))
                self.interval_days_spin.setValue(7)
                self.alert_enabled_check.setChecked(True)
                self.alert_prefix_edit.setText("ALERT")
            else:
                # デフォルトルールの適用
                self.setup_default_rules(table=self.rules_table, connect_signals=False)
                self.update_price_trace_visibility(self.rules_table)
            
            QMessageBox.information(self, "リセット完了", "デフォルト設定にリセットしました")
    
    def on_action_changed(self, row, action_text, table=None):
        """アクション変更時の処理"""
        # priceTrace設定の表示制御を更新
        self.update_price_trace_visibility(table)
    
    def update_price_trace_visibility(self, table=None):
        """priceTrace設定の表示制御"""
        table = table or self.rules_table
        if table is None:
            return
        for i in range(table.rowCount()):
            action_combo = table.cellWidget(i, 1)
            price_trace_combo = table.cellWidget(i, 2)
            
            if action_combo and price_trace_combo:
                current_action = action_combo.currentData()
                
                # priceTraceアクションの場合のみ有効化
                if current_action == "priceTrace":
                    price_trace_combo.setEnabled(True)
                    price_trace_combo.setStyleSheet("")  # 通常のスタイル
                else:
                    price_trace_combo.setEnabled(False)
                    price_trace_combo.setStyleSheet("background-color: #f0f0f0; color: #999999;")  # 無効化スタイル
