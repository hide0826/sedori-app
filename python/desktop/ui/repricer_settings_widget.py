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
    QCheckBox, QSpinBox, QDoubleSpinBox, QGroupBox,
    QMessageBox, QFrame, QSplitter
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QColor
import json
from typing import Dict, List, Any, Optional


class RepricerSettingsWorker(QThread):
    """ルール設定処理のワーカースレッド"""
    config_loaded = Signal(dict)
    config_saved = Signal(bool)
    error_occurred = Signal(str)
    
    def __init__(self, api_client, action="load", config_data=None):
        super().__init__()
        self.api_client = api_client
        self.action = action
        self.config_data = config_data
        
    def run(self):
        """ルール設定の処理"""
        try:
            if self.action == "load":
                # 設定の取得
                config = self.api_client.get_repricer_config()
                self.config_loaded.emit(config)
            elif self.action == "save":
                # 設定の保存
                success = self.api_client.update_repricer_config(self.config_data)
                self.config_saved.emit(success)
                
        except Exception as e:
            self.error_occurred.emit(str(e))


class RepricerSettingsWidget(QWidget):
    """価格改定ルール設定ウィジェット"""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
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
        
        # 中央：ルール設定テーブル
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
        
    def setup_rules_table(self):
        """ルール設定テーブルの設定"""
        rules_group = QGroupBox("価格改定ルール設定")
        rules_layout = QVBoxLayout(rules_group)
        
        # テーブルの作成
        self.rules_table = QTableWidget()
        self.rules_table.setAlternatingRowColors(True)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        
        # スクロール防止設定
        self.rules_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.rules_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # セルの編集を無効化（誤設定防止）
        self.rules_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # 列の設定
        columns = ['出品日数', 'アクション', 'priceTrace設定']
        self.rules_table.setColumnCount(len(columns))
        self.rules_table.setHorizontalHeaderLabels(columns)
        
        # デフォルトルールの設定
        self.setup_default_rules()
        
        rules_layout.addWidget(self.rules_table)
        self.layout().addWidget(rules_group)
        
    def setup_default_rules(self):
        """デフォルトルールの設定"""
        # 出品日数の範囲設定
        day_ranges = [
            (1, 30), (31, 60), (61, 90), (91, 120), (121, 150),
            (151, 180), (181, 210), (211, 240), (241, 270),
            (271, 300), (301, 330), (331, 360), (361, 999)
        ]
        
        self.rules_table.setRowCount(len(day_ranges))
        
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
        
        # priceTrace設定の選択肢（日本語）
        price_trace_options = [
            (0, "追従無し"),
            (1, "FBA状態合わせ"),
            (2, "状態合わせ"),
            (3, "FBA最安値"),
            (4, "最安値"),
            (5, "カート価格")
        ]
        
        for i, (start_day, end_day) in enumerate(day_ranges):
            # 出品日数
            if end_day == 999:
                days_text = f"{start_day}日～"
            else:
                days_text = f"{start_day}-{end_day}日"
            days_item = QTableWidgetItem(days_text)
            days_item.setFlags(days_item.flags() & ~Qt.ItemIsEditable)
            self.rules_table.setItem(i, 0, days_item)
            
            # アクション選択
            action_combo = QComboBox()
            for action_key, action_text in actions:
                action_combo.addItem(action_text, action_key)
            # スクロール無効化（誤設定防止）
            action_combo.setEditable(False)
            # アクション変更時のイベント接続
            action_combo.currentTextChanged.connect(lambda text, row=i: self.on_action_changed(row, text))
            self.rules_table.setCellWidget(i, 1, action_combo)
            
            # priceTrace設定
            price_trace_combo = QComboBox()
            for value, text in price_trace_options:
                price_trace_combo.addItem(text, value)
            # スクロール無効化（誤設定防止）
            price_trace_combo.setEditable(False)
            self.rules_table.setCellWidget(i, 2, price_trace_combo)
        
        # 列幅の調整
        self.rules_table.resizeColumnsToContents()
        
        # 列幅の固定設定
        self.rules_table.setColumnWidth(0, 120)  # 出品日数
        self.rules_table.setColumnWidth(1, 200)  # アクション
        self.rules_table.setColumnWidth(2, 150)  # priceTrace設定
        
        # 初期状態でpriceTrace設定を非表示
        self.update_price_trace_visibility()
        
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
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
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
            self.worker = RepricerSettingsWorker(self.api_client, "load")
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
            self.worker = RepricerSettingsWorker(self.api_client, "save", config_data)
            self.worker.config_saved.connect(self.on_config_saved)
            self.worker.error_occurred.connect(self.on_error)
            self.worker.start()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"設定の保存に失敗しました:\n{str(e)}")
    
    def collect_current_config(self):
        """現在の設定を収集"""
        config = {
            "profit_guard_percentage": self.profit_guard_spin.value(),
            "q4_rule_enabled": self.q4_rule_check.isChecked(),
            "excluded_skus": [sku.strip() for sku in self.excluded_skus_edit.text().split(",") if sku.strip()],
            "reprice_rules": []  # リスト形式に変更
        }
        
        # テーブルからルールを収集
        for i in range(self.rules_table.rowCount()):
            days_item = self.rules_table.item(i, 0)
            if days_item:
                days_text = days_item.text()
                # "1-30日" から "30" を抽出、"361日～" の場合は 999 を使用
                if "～" in days_text:
                    end_day = 999
                else:
                    end_day = int(days_text.split("-")[1].replace("日", ""))
                
                action_combo = self.rules_table.cellWidget(i, 1)
                price_trace_combo = self.rules_table.cellWidget(i, 2)
                
                if action_combo and price_trace_combo:
                    action = action_combo.currentData()  # 内部値（英語）を取得
                    price_trace = price_trace_combo.currentData()
                    
                    # 利益無視値下げのアクション名を既存API形式に変換
                    if action.startswith("price_down_ignore_"):
                        action = "price_down_ignore"
                    
                    # リスト形式で追加
                    config["reprice_rules"].append({
                        "days_from": end_day,
                        "action": action,
                        "value": price_trace
                    })
        
        return config
    
    def on_config_loaded(self, config):
        """設定読み込み完了時の処理"""
        self.config_data = config
        
        # 基本設定の更新
        self.profit_guard_spin.setValue(config.get("profit_guard_percentage", 1.1))
        self.q4_rule_check.setChecked(config.get("q4_rule_enabled", False))
        
        excluded_skus = config.get("excluded_skus", [])
        self.excluded_skus_edit.setText(", ".join(excluded_skus))
        
        # ルール設定の更新（リスト形式から辞書形式に変換）
        rules_list = config.get("reprice_rules", [])
        rules_dict = {}
        for rule in rules_list:
            days_from = rule.get("days_from")
            if days_from:
                rules_dict[str(days_from)] = {
                    "action": rule.get("action", "maintain"),
                    "priceTrace": rule.get("value", 0)
                }
        self.update_rules_table(rules_dict)
        
        # priceTrace設定の表示制御を更新
        self.update_price_trace_visibility()
        
        QMessageBox.information(self, "設定読み込み完了", "設定を正常に読み込みました")
    
    def on_config_saved(self, success):
        """設定保存完了時の処理"""
        if success:
            QMessageBox.information(self, "設定保存完了", "設定を正常に保存しました")
        else:
            QMessageBox.warning(self, "設定保存失敗", "設定の保存に失敗しました")
    
    def on_error(self, error_message):
        """エラー時の処理"""
        QMessageBox.critical(self, "エラー", f"処理中にエラーが発生しました:\n{error_message}")
    
    def update_rules_table(self, rules_dict):
        """ルールテーブルの更新"""
        for i in range(self.rules_table.rowCount()):
            days_item = self.rules_table.item(i, 0)
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
                    action_combo = self.rules_table.cellWidget(i, 1)
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
                    price_trace_combo = self.rules_table.cellWidget(i, 2)
                    if price_trace_combo:
                        price_trace = rule.get("priceTrace", 0)
                        index = price_trace_combo.findData(price_trace)
                        if index >= 0:
                            price_trace_combo.setCurrentIndex(index)
    
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
            
            # デフォルトルールの適用
            self.setup_default_rules()
            
            QMessageBox.information(self, "リセット完了", "デフォルト設定にリセットしました")
    
    def on_action_changed(self, row, action_text):
        """アクション変更時の処理"""
        # priceTrace設定の表示制御を更新
        self.update_price_trace_visibility()
    
    def update_price_trace_visibility(self):
        """priceTrace設定の表示制御"""
        for i in range(self.rules_table.rowCount()):
            action_combo = self.rules_table.cellWidget(i, 1)
            price_trace_combo = self.rules_table.cellWidget(i, 2)
            
            if action_combo and price_trace_combo:
                current_action = action_combo.currentData()
                
                # priceTraceアクションの場合のみ有効化
                if current_action == "priceTrace":
                    price_trace_combo.setEnabled(True)
                    price_trace_combo.setStyleSheet("")  # 通常のスタイル
                else:
                    price_trace_combo.setEnabled(False)
                    price_trace_combo.setStyleSheet("background-color: #f0f0f0; color: #999999;")  # 無効化スタイル
