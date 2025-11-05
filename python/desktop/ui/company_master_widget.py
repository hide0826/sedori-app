#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法人マスタ管理ウィジェット

法人マスタの追加・編集・削除機能
- 検索・フィルタ機能
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QLabel, QGroupBox, QDialogButtonBox
)
from PySide6.QtCore import Qt
from typing import Tuple
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from database.store_db import StoreDatabase


class CompanyEditDialog(QDialog):
    """法人編集ダイアログ"""
    
    def __init__(self, parent=None, company_data=None):
        super().__init__(parent)
        self.company_data = company_data
        
        self.setWindowTitle("法人編集" if company_data else "法人追加")
        self.setModal(True)
        self.setup_ui()
        
        if company_data:
            self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        # 基本情報フォーム
        form_group = QGroupBox("基本情報")
        form_layout = QFormLayout(form_group)
        
        self.chain_name_edit = QLineEdit()
        self.chain_name_edit.setPlaceholderText("必須項目")
        form_layout.addRow("チェーン名:", self.chain_name_edit)
        
        self.company_name_edit = QLineEdit()
        self.company_name_edit.setPlaceholderText("必須項目")
        form_layout.addRow("法人名:", self.company_name_edit)
        
        self.license_number_edit = QLineEdit()
        form_layout.addRow("古物商許可番号:", self.license_number_edit)
        
        self.head_office_address_edit = QLineEdit()
        form_layout.addRow("本社住所:", self.head_office_address_edit)
        
        self.representative_phone_edit = QLineEdit()
        form_layout.addRow("代表電話番号:", self.representative_phone_edit)
        
        layout.addWidget(form_group)
        
        # ボタン
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.company_data:
            return
        
        self.chain_name_edit.setText(self.company_data.get('chain_name', ''))
        self.company_name_edit.setText(self.company_data.get('company_name', ''))
        self.license_number_edit.setText(self.company_data.get('license_number', ''))
        self.head_office_address_edit.setText(self.company_data.get('head_office_address', ''))
        self.representative_phone_edit.setText(self.company_data.get('representative_phone', ''))
    
    def get_data(self) -> dict:
        """入力データを取得"""
        return {
            'chain_name': self.chain_name_edit.text().strip(),
            'company_name': self.company_name_edit.text().strip(),
            'license_number': self.license_number_edit.text().strip(),
            'head_office_address': self.head_office_address_edit.text().strip(),
            'representative_phone': self.representative_phone_edit.text().strip()
        }
    
    def validate(self) -> Tuple[bool, str]:
        """入力データの検証"""
        data = self.get_data()
        
        # チェーン名は必須
        if not data['chain_name']:
            return False, "チェーン名を入力してください"
        
        # 法人名は必須
        if not data['company_name']:
            return False, "法人名を入力してください"
        
        return True, ""


class CompanyMasterWidget(QWidget):
    """法人マスタ管理ウィジェット"""
    
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        
        self.setup_ui()
        self.load_companies()
        self.check_and_initialize_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：操作ボタン
        self.setup_action_buttons(layout)
        
        # 中部：検索・フィルタ
        self.setup_search_filter(layout)
        
        # 下部：法人一覧テーブル
        self.setup_company_table(layout)
        
        # 統計情報
        self.update_statistics()
    
    def setup_action_buttons(self, parent_layout):
        """操作ボタンの設定"""
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        
        # 追加ボタン
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_company)
        button_layout.addWidget(add_btn)
        
        # 編集ボタン
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self.edit_company)
        button_layout.addWidget(edit_btn)
        
        # 削除ボタン
        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_company)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(delete_btn)
        
        button_layout.addStretch()
        
        parent_layout.addWidget(button_group)
    
    def setup_search_filter(self, parent_layout):
        """検索・フィルタの設定"""
        search_group = QGroupBox("検索")
        search_layout = QHBoxLayout(search_group)
        
        search_label = QLabel("検索:")
        search_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("チェーン名、法人名、古物商許可番号で検索...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_edit)
        
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self.search_edit.clear)
        search_layout.addWidget(clear_btn)
        
        parent_layout.addWidget(search_group)
    
    def setup_company_table(self, parent_layout):
        """法人一覧テーブルの設定"""
        table_group = QGroupBox("法人一覧")
        table_layout = QVBoxLayout(table_group)
        
        self.company_table = QTableWidget()
        self.company_table.setAlternatingRowColors(True)
        self.company_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.company_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # ソート機能を有効化
        self.company_table.setSortingEnabled(True)
        
        # ヘッダー設定
        header = self.company_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionsClickable(True)  # ヘッダークリックでソート可能に
        
        table_layout.addWidget(self.company_table)
        
        # 統計情報ラベル
        self.stats_label = QLabel("統計: 読み込み中...")
        table_layout.addWidget(self.stats_label)
        
        parent_layout.addWidget(table_group)
    
    def load_companies(self, search_term: str = ""):
        """法人一覧を読み込む"""
        companies = self.db.list_companies(search_term)
        self.update_table(companies)
        self.update_statistics()
    
    def update_table(self, companies: list):
        """テーブルを更新"""
        # ソート機能を一時的に無効化（データ投入中はソートしない）
        self.company_table.setSortingEnabled(False)
        
        # カラム定義
        columns = ["ID", "チェーン名", "法人名", "古物商許可番号", "本社住所", "代表電話番号"]
        
        self.company_table.setRowCount(len(companies))
        self.company_table.setColumnCount(len(columns))
        self.company_table.setHorizontalHeaderLabels(columns)
        
        # データの設定
        for i, company in enumerate(companies):
            # IDは数値としてソートできるように設定
            id_item = QTableWidgetItem()
            id_item.setData(Qt.EditRole, company.get('id', 0))  # 数値として設定
            id_item.setText(str(company.get('id', '')))
            self.company_table.setItem(i, 0, id_item)
            
            self.company_table.setItem(i, 1, QTableWidgetItem(company.get('chain_name', '')))
            self.company_table.setItem(i, 2, QTableWidgetItem(company.get('company_name', '')))
            self.company_table.setItem(i, 3, QTableWidgetItem(company.get('license_number', '')))
            self.company_table.setItem(i, 4, QTableWidgetItem(company.get('head_office_address', '')))
            self.company_table.setItem(i, 5, QTableWidgetItem(company.get('representative_phone', '')))
        
        # データ投入完了後、ソート機能を再有効化
        self.company_table.setSortingEnabled(True)
        
        # 列幅の自動調整
        self.company_table.resizeColumnsToContents()
    
    def update_statistics(self):
        """統計情報を更新"""
        count = self.db.get_company_count()
        self.stats_label.setText(f"統計: 法人数 {count}件")
    
    def on_search_changed(self, text):
        """検索テキスト変更時の処理"""
        self.load_companies(text)
    
    def add_company(self):
        """法人追加"""
        dialog = CompanyEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            is_valid, error_msg = dialog.validate()
            if not is_valid:
                QMessageBox.warning(self, "エラー", error_msg)
                return
            
            try:
                data = dialog.get_data()
                self.db.add_company(data)
                QMessageBox.information(self, "完了", "法人を追加しました")
                self.load_companies(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{str(e)}")
    
    def edit_company(self):
        """法人編集"""
        selected = self.company_table.selectionModel().selectedRows() if self.company_table.selectionModel() else []
        if not selected:
            QMessageBox.warning(self, "警告", "編集する法人を選択してください")
            return
        
        row = selected[0].row()
        id_item = self.company_table.item(row, 0)
        if not id_item or not id_item.text().strip():
            QMessageBox.warning(self, "エラー", "選択行のIDが取得できません")
            return
        try:
            company_id = int(id_item.text())
        except ValueError:
            QMessageBox.warning(self, "エラー", "不正なID形式です")
            return
        company_data = self.db.get_company(company_id)
        
        if not company_data:
            QMessageBox.warning(self, "エラー", "法人データが見つかりません")
            return
        
        dialog = CompanyEditDialog(self, company_data=company_data)
        if dialog.exec() == QDialog.Accepted:
            is_valid, error_msg = dialog.validate()
            if not is_valid:
                QMessageBox.warning(self, "エラー", error_msg)
                return
            
            try:
                data = dialog.get_data()
                self.db.update_company(company_id, data)
                QMessageBox.information(self, "完了", "法人を更新しました")
                self.load_companies(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{str(e)}")
    
    def delete_company(self):
        """法人削除"""
        selected = self.company_table.selectionModel().selectedRows() if self.company_table.selectionModel() else []
        if not selected:
            QMessageBox.warning(self, "警告", "削除する法人を選択してください")
            return
        
        row = selected[0].row()
        id_item = self.company_table.item(row, 0)
        if not id_item or not id_item.text().strip():
            QMessageBox.warning(self, "エラー", "選択行のIDが取得できません")
            return
        try:
            company_id = int(id_item.text())
        except ValueError:
            QMessageBox.warning(self, "エラー", "不正なID形式です")
            return
        chain_name = self.company_table.item(row, 1).text()
        company_name = self.company_table.item(row, 2).text()
        
        reply = QMessageBox.question(
            self,
            "削除確認",
            f"法人 '{chain_name} ({company_name})' を削除しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            self.db.delete_company(company_id)
            QMessageBox.information(self, "完了", "法人を削除しました")
            self.load_companies(self.search_edit.text())
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{str(e)}")
    
    def check_and_initialize_data(self):
        """初期データの確認と投入"""
        count = self.db.get_company_count()
        if count == 0:
            # 初期データを投入
            self.initialize_default_data()
    
    def initialize_default_data(self):
        """初期データを投入"""
        initial_data = [
            {
                'chain_name': 'ブックオフ',
                'company_name': 'ブックオフコーポレーション株式会社',
                'license_number': '神奈川県公安委員会 第452760001146号',
                'head_office_address': '〒252-0344 神奈川県相模原市南区古淵2-14-20',
                'representative_phone': '03-6701-4614 (※注1)'
            },
            {
                'chain_name': 'ハードオフオフハウスホビーオフ',
                'company_name': '株式会社ハードオフコーポレーション',
                'license_number': '新潟県公安委員会 第461060001043号',
                'head_office_address': '〒957-0063 新潟県新発田市新栄町3丁目1番13号',
                'representative_phone': '0254-24-4344 (代表)'
            },
            {
                'chain_name': 'セカンドストリート',
                'company_name': '株式会社セカンドストリート',
                'license_number': '愛知県公安委員会 第541162001000号',
                'head_office_address': '〒460-0014 愛知県名古屋市中区富士見町8番8号 OMCビル (※注2)',
                'representative_phone': '情報あり (要確認)'
            },
            {
                'chain_name': 'WonderREX (ワンダーレックス)',
                'company_name': 'REXT株式会社',
                'license_number': '古物商許可番号: 詳細情報なし (※注3)',
                'head_office_address': '〒305-0854 茨城県つくば市上横場2364の1',
                'representative_phone': '0800-800-6884 (フリーダイヤル/コールセンター)'
            },
            {
                'chain_name': 'ワットマン',
                'company_name': '株式会社ワットマン',
                'license_number': '神奈川県公安委員会 第451480000321号',
                'head_office_address': '〒241-0021 神奈川県横浜市旭区鶴ケ峰本町1-27-13',
                'representative_phone': '045-959-1100 (代表)'
            }
        ]
        
        try:
            for data in initial_data:
                self.db.add_company(data)
            # 再読み込み
            self.load_companies()
            QMessageBox.information(self, "初期データ投入", f"{len(initial_data)}件の初期データを投入しました")
        except Exception as e:
            QMessageBox.warning(self, "初期データ投入エラー", f"初期データの投入に失敗しました:\n{str(e)}")

