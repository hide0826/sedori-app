#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕訳帳ウィジェット

取引日付・借方勘定科目・金額・貸方勘定科目・摘要・インボイス番号・税区分を管理
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, date

from PySide6.QtCore import Qt, QDate, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QLabel, QDateEdit, QComboBox, QLineEdit,
    QMessageBox, QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
    QStyledItemDelegate
)
from PySide6.QtGui import QDesktopServices

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from desktop.database.journal_db import JournalDatabase
from desktop.database.account_title_db import AccountTitleDatabase
from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state


class DebitAccountDelegate(QStyledItemDelegate):
    """借方勘定科目列用デリゲート（プルダウン）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.account_title_db = AccountTitleDatabase()
    
    def _get_titles(self) -> list[str]:
        try:
            titles = [t.get("name", "") for t in self.account_title_db.list_titles()]
        except Exception:
            titles = []
        default = "仕入"
        if default not in titles:
            titles.insert(0, default)
        return [t for t in titles if t]
    
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        for title in self._get_titles():
            combo.addItem(title)
        return combo
    
    def setEditorData(self, editor, index):
        current_text = index.data() or ""
        titles = self._get_titles()
        if not current_text and titles:
            current_text = titles[0]
        idx = editor.findText(current_text)
        if idx >= 0:
            editor.setCurrentIndex(idx)
        else:
            editor.setCurrentText(current_text)
    
    def setModelData(self, editor, model, index):
        title = editor.currentText().strip()
        model.setData(index, title)


class CreditAccountDelegate(QStyledItemDelegate):
    """貸方勘定科目列用デリゲート（プルダウン）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.account_title_db = AccountTitleDatabase()
    
    def _get_accounts(self) -> list[tuple[str, str]]:
        """貸方勘定科目のリストを取得（表示名, 実際の科目名）"""
        try:
            accounts = self.account_title_db.list_credit_accounts()
            result = []
            for account in accounts:
                name = account.get("name", "")
                card_name = account.get("card_name", "")
                last_four = account.get("last_four_digits", "")
                if card_name and last_four:
                    display_name = f"{name} ({card_name} ****{last_four})"
                elif card_name:
                    display_name = f"{name} ({card_name})"
                else:
                    display_name = name
                result.append((display_name, name))
            return result
        except Exception:
            return [("現金", "現金")]
    
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        for display_name, actual_name in self._get_accounts():
            combo.addItem(display_name, actual_name)
        return combo
    
    def setEditorData(self, editor, index):
        current_text = index.data() or ""
        accounts = self._get_accounts()
        
        # 表示名で検索
        found = False
        for i, (display_name, actual_name) in enumerate(accounts):
            if display_name == current_text or actual_name == current_text:
                editor.setCurrentIndex(i)
                found = True
                break
        
        if not found and accounts:
            # 見つからない場合は最初の項目を選択
            editor.setCurrentIndex(0)
    
    def setModelData(self, editor, model, index):
        # 表示名を保存
        display_name = editor.currentText().strip()
        model.setData(index, display_name)


class TaxCategoryDelegate(QStyledItemDelegate):
    """税区分列用デリゲート（プルダウン）"""
    
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems(["10％", "8％"])
        return combo
    
    def setEditorData(self, editor, index):
        current_text = index.data() or "10％"
        idx = editor.findText(current_text)
        if idx >= 0:
            editor.setCurrentIndex(idx)
        else:
            editor.setCurrentIndex(0)
    
    def setModelData(self, editor, model, index):
        category = editor.currentText()
        model.setData(index, category)


class JournalEntryWidget(QWidget):
    """仕訳帳ウィジェット"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.journal_db = JournalDatabase()
        self.setup_ui()
        self.load_entries()
        
        # テーブルの列幅を復元
        restore_table_header_state(self.table, "JournalEntryWidget/TableHeaderState")
    
    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.table, "JournalEntryWidget/TableHeaderState")
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # ヘッダー
        header = QLabel("仕訳帳")
        header.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(header)
        
        # 操作エリア
        controls_group = QGroupBox("操作")
        controls_layout = QHBoxLayout(controls_group)
        
        self.add_btn = QPushButton("追加")
        self.add_btn.clicked.connect(self.add_entry)
        controls_layout.addWidget(self.add_btn)
        
        self.edit_btn = QPushButton("編集")
        self.edit_btn.clicked.connect(self.edit_entry)
        controls_layout.addWidget(self.edit_btn)
        
        self.delete_btn = QPushButton("削除")
        self.delete_btn.clicked.connect(self.delete_entry)
        controls_layout.addWidget(self.delete_btn)
        
        self.refresh_btn = QPushButton("更新")
        self.refresh_btn.clicked.connect(self.load_entries)
        controls_layout.addWidget(self.refresh_btn)
        
        controls_layout.addStretch()
        layout.addWidget(controls_group)
        
        # テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "取引日付",
            "借方勘定科目",
            "金額",
            "貸方勘定科目",
            "摘要",
            "インボイス番号",
            "税区分",
            "画像URL"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        # 編集可能にする（ダブルクリックまたはF2で編集）
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        
        # 各カラムにデリゲートを設定
        self.table.setItemDelegateForColumn(1, DebitAccountDelegate(self))  # 借方勘定科目
        self.table.setItemDelegateForColumn(3, CreditAccountDelegate(self))  # 貸方勘定科目
        # インボイス番号（5列目）はデフォルトでテキスト編集可能
        self.table.setItemDelegateForColumn(6, TaxCategoryDelegate(self))  # 税区分
        
        # 編集完了時にデータベースを更新
        self.table.itemChanged.connect(self.on_item_changed)
        
        # セルダブルクリックイベント（画像URLをブラウザで開く）
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        
        layout.addWidget(self.table)
    
    def load_entries(self):
        """仕訳帳エントリを読み込んでテーブルに表示"""
        entries = self.journal_db.list_all()
        self.table.setRowCount(len(entries))
        
        for row, entry in enumerate(entries):
            # 取引日付
            transaction_date = entry.get("transaction_date", "")
            date_item = QTableWidgetItem(transaction_date)
            date_item.setData(Qt.UserRole, entry.get("id"))  # IDを保存
            self.table.setItem(row, 0, date_item)
            
            # 借方勘定科目（編集可能、プルダウン）
            debit_account = entry.get("debit_account", "")
            debit_item = QTableWidgetItem(debit_account)
            debit_item.setFlags(debit_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 1, debit_item)
            
            # 金額（編集可能）
            amount = entry.get("amount", 0)
            amount_str = f"{amount:,}" if amount else "0"
            amount_item = QTableWidgetItem(amount_str)
            amount_item.setFlags(amount_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 2, amount_item)
            
            # 貸方勘定科目（編集可能、プルダウン）
            credit_account = entry.get("credit_account", "")
            credit_item = QTableWidgetItem(credit_account)
            credit_item.setFlags(credit_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 3, credit_item)
            
            # 摘要（編集可能）
            description = entry.get("description", "")
            desc_item = QTableWidgetItem(description)
            desc_item.setFlags(desc_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 4, desc_item)
            
            # インボイス番号（編集可能）
            invoice_number = entry.get("invoice_number", "")
            invoice_item = QTableWidgetItem(invoice_number)
            invoice_item.setFlags(invoice_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 5, invoice_item)
            
            # 税区分（編集可能、プルダウン）
            tax_category = entry.get("tax_category", "")
            tax_item = QTableWidgetItem(tax_category)
            tax_item.setFlags(tax_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 6, tax_item)
            
            # 画像URL
            image_url = entry.get("image_url", "")
            image_url_item = QTableWidgetItem(image_url)
            if image_url:
                image_url_item.setToolTip(f"画像URL: {image_url}\n（ダブルクリックでブラウザ表示）")
                # URLのスタイル設定
                image_url_item.setForeground(Qt.white)
                font = image_url_item.font()
                font.setUnderline(True)
                image_url_item.setFont(font)
            # 画像URLは編集不可
            image_url_item.setFlags(image_url_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 7, image_url_item)
    
    def on_item_changed(self, item: QTableWidgetItem):
        """テーブルの項目が変更されたときにデータベースを更新"""
        row = item.row()
        col = item.column()
        
        # 取引日付列からエントリIDを取得
        date_item = self.table.item(row, 0)
        if not date_item:
            return
        
        entry_id = date_item.data(Qt.UserRole)
        if not entry_id:
            return
        
        # エントリを取得
        entry = self.journal_db.get_by_id(entry_id)
        if not entry:
            return
        
        # 変更されたカラムに応じて更新
        if col == 1:  # 借方勘定科目
            entry['debit_account'] = item.text().strip()
        elif col == 2:  # 金額
            try:
                amount_text = item.text().replace(",", "").strip()
                entry['amount'] = int(amount_text) if amount_text else 0
            except ValueError:
                QMessageBox.warning(self, "エラー", "金額は数値で入力してください。")
                self.load_entries()  # 元に戻す
                return
        elif col == 3:  # 貸方勘定科目
            # 表示名から実際の科目名を抽出
            credit_account_display = item.text().strip()
            credit_account = credit_account_display.split(' (')[0] if ' (' in credit_account_display else credit_account_display
            entry['credit_account'] = credit_account_display  # 表示名を保存
        elif col == 4:  # 摘要
            entry['description'] = item.text().strip()
        elif col == 5:  # インボイス番号
            entry['invoice_number'] = item.text().strip()
        elif col == 6:  # 税区分
            entry['tax_category'] = item.text().strip()
        
            # データベースを更新
        try:
            self.journal_db.update(entry_id, entry)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{e}")
            self.load_entries()  # 元に戻す
    
    def on_cell_double_clicked(self, row: int, col: int):
        """セルダブルクリック時の処理（画像URL列をダブルクリックしたときにブラウザで開く）"""
        # 画像URL列（7列目、インデックス7）をダブルクリックした場合
        if col == 7:
            item = self.table.item(row, col)
            if not item:
                return
            url = (item.text() or "").strip()
            if not url:
                QMessageBox.information(self, "情報", "URLが設定されていません。")
                return
            qurl = QUrl(url)
            if not qurl.isValid():
                QMessageBox.warning(self, "警告", f"URLが不正です:\n{url}")
                return
            if not QDesktopServices.openUrl(qurl):
                QMessageBox.warning(self, "警告", f"ブラウザでURLを開けませんでした:\n{url}")
    
    def add_entry(self):
        """新しい仕訳エントリを追加"""
        dialog = JournalEntryDialog(self)
        if dialog.exec():
            entry_data = dialog.get_data()
            if entry_data:
                try:
                    self.journal_db.insert(entry_data)
                    self.load_entries()
                    QMessageBox.information(self, "追加", "仕訳エントリを追加しました。")
                except Exception as e:
                    QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{e}")
    
    def edit_entry(self):
        """選択された仕訳エントリを編集"""
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "編集する行を選択してください。")
            return
        
            # エントリIDを取得（テーブルに保存されている場合）
        date_item = self.table.item(current_row, 0)
        if not date_item:
            QMessageBox.warning(self, "警告", "エントリが見つかりません。")
            return
        
        entry_id = date_item.data(Qt.UserRole)
        if not entry_id:
            QMessageBox.warning(self, "警告", "エントリIDが見つかりません。")
            return
        
        # エントリデータを取得
        entry = self.journal_db.get_by_id(entry_id)
        if not entry:
            QMessageBox.warning(self, "警告", "エントリが見つかりません。")
            return
        
        dialog = JournalEntryDialog(self, entry)
        if dialog.exec():
            entry_data = dialog.get_data()
            if entry_data:
                try:
                    self.journal_db.update(entry_id, entry_data)
                    self.load_entries()
                    QMessageBox.information(self, "編集", "仕訳エントリを更新しました。")
                except Exception as e:
                    QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{e}")
    
    def delete_entry(self):
        """選択された仕訳エントリを削除"""
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "削除する行を選択してください。")
            return
        
        reply = QMessageBox.question(
            self, "確認", "選択された仕訳エントリを削除しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # エントリIDを取得
            date_item = self.table.item(current_row, 0)
            if not date_item:
                QMessageBox.warning(self, "警告", "エントリが見つかりません。")
                return
            
            entry_id = date_item.data(Qt.UserRole)
            if entry_id:
                try:
                    self.journal_db.delete(entry_id)
                    self.load_entries()
                    QMessageBox.information(self, "削除", "仕訳エントリを削除しました。")
                except Exception as e:
                    QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{e}")


class JournalEntryDialog(QDialog):
    """仕訳エントリ編集ダイアログ"""
    
    def __init__(self, parent=None, entry: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.entry = entry
        self.setWindowTitle("仕訳エントリ編集" if entry else "仕訳エントリ追加")
        self.setup_ui()
        if entry:
            self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        # 取引日付
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        form_layout.addRow("取引日付:", self.date_edit)
        
        # 借方勘定科目
        self.debit_account_combo = QComboBox()
        self.debit_account_combo.setEditable(True)
        # 勘定科目設定から取得
        try:
            from database.account_title_db import AccountTitleDatabase
            account_title_db = AccountTitleDatabase()
            titles = account_title_db.list_titles()
            account_titles = [title.get('name', '') for title in titles if title.get('name')]
            # デフォルト「仕入」を追加（まだない場合）
            default_title = "仕入"
            if default_title not in account_titles:
                account_titles.insert(0, default_title)
            for title in account_titles:
                self.debit_account_combo.addItem(title)
            # デフォルトを「仕入」に設定
            idx = self.debit_account_combo.findText(default_title)
            if idx >= 0:
                self.debit_account_combo.setCurrentIndex(idx)
        except Exception:
            # エラー時はデフォルト科目のみ追加
            self.debit_account_combo.addItem("仕入")
            self.debit_account_combo.setCurrentText("仕入")
        form_layout.addRow("借方勘定科目:", self.debit_account_combo)
        
        # 金額
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("金額を入力")
        form_layout.addRow("金額:", self.amount_edit)
        
        # 貸方勘定科目
        self.credit_account_combo = QComboBox()
        self.credit_account_combo.setEditable(True)
        # 貸方勘定科目設定から取得
        try:
            from database.account_title_db import AccountTitleDatabase
            account_title_db = AccountTitleDatabase()
            credit_accounts = account_title_db.list_credit_accounts()
            default_account = account_title_db.get_default_credit_account()
            
            for account in credit_accounts:
                name = account.get("name", "")
                card_name = account.get("card_name", "")
                last_four = account.get("last_four_digits", "")
                if card_name and last_four:
                    display_name = f"{name} ({card_name} ****{last_four})"
                elif card_name:
                    display_name = f"{name} ({card_name})"
                else:
                    display_name = name
                self.credit_account_combo.addItem(display_name, account.get("id"))
            
            # デフォルトを設定
            if default_account:
                default_id = default_account.get("id")
                for i in range(self.credit_account_combo.count()):
                    if self.credit_account_combo.itemData(i) == default_id:
                        self.credit_account_combo.setCurrentIndex(i)
                        break
        except Exception:
            # エラー時はデフォルト科目のみ追加
            self.credit_account_combo.addItem("現金")
            self.credit_account_combo.setCurrentText("現金")
        form_layout.addRow("貸方勘定科目:", self.credit_account_combo)
        
        # 摘要
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("摘要を入力")
        form_layout.addRow("摘要:", self.description_edit)
        
        # インボイス番号
        self.invoice_number_edit = QLineEdit()
        self.invoice_number_edit.setPlaceholderText("インボイス番号を入力（T + 13桁）")
        form_layout.addRow("インボイス番号:", self.invoice_number_edit)
        
        # 税区分
        self.tax_category_combo = QComboBox()
        self.tax_category_combo.addItems([
            "10％", "8％", "課税", "非課税", "不課税", "免税"
        ])
        # デフォルトを10％に設定
        idx = self.tax_category_combo.findText("10％")
        if idx >= 0:
            self.tax_category_combo.setCurrentIndex(idx)
        form_layout.addRow("税区分:", self.tax_category_combo)
        
        # 画像URL
        self.image_url_edit = QLineEdit()
        self.image_url_edit.setPlaceholderText("画像URLを入力（GCSアップロード後のURLなど）")
        form_layout.addRow("画像URL:", self.image_url_edit)
        
        layout.addLayout(form_layout)
        
        # ボタン
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.entry:
            return
        
        # 取引日付
        date_str = self.entry.get("transaction_date", "")
        if date_str:
            try:
                date_obj = QDate.fromString(date_str, "yyyy-MM-dd")
                if date_obj.isValid():
                    self.date_edit.setDate(date_obj)
            except Exception:
                pass
        
        # 借方勘定科目
        debit_account = self.entry.get("debit_account", "")
        if debit_account:
            index = self.debit_account_combo.findText(debit_account)
            if index >= 0:
                self.debit_account_combo.setCurrentIndex(index)
            else:
                self.debit_account_combo.setCurrentText(debit_account)
        
        # 金額
        amount = self.entry.get("amount", 0)
        self.amount_edit.setText(str(amount) if amount else "")
        
        # 貸方勘定科目
        credit_account = self.entry.get("credit_account", "")
        if credit_account:
            # 表示名で検索
            found = False
            for i in range(self.credit_account_combo.count()):
                display_text = self.credit_account_combo.itemText(i)
                # 表示名から実際の科目名を抽出（括弧前の部分）
                actual_name = display_text.split(' (')[0] if ' (' in display_text else display_text
                if actual_name == credit_account or display_text == credit_account:
                    self.credit_account_combo.setCurrentIndex(i)
                    found = True
                    break
            if not found:
                self.credit_account_combo.setCurrentText(credit_account)
        
        # 摘要
        description = self.entry.get("description", "")
        self.description_edit.setText(description)
        
        # インボイス番号
        invoice_number = self.entry.get("invoice_number", "")
        self.invoice_number_edit.setText(invoice_number)
        
        # 税区分
        tax_category = self.entry.get("tax_category", "")
        if tax_category:
            index = self.tax_category_combo.findText(tax_category)
            if index >= 0:
                self.tax_category_combo.setCurrentIndex(index)
        
        # 画像URL
        image_url = self.entry.get("image_url", "")
        self.image_url_edit.setText(image_url)
    
    def get_data(self) -> Optional[Dict[str, Any]]:
        """入力データを取得"""
        # 取引日付
        date_obj = self.date_edit.date()
        transaction_date = date_obj.toString("yyyy-MM-dd")
        
        # 借方勘定科目
        debit_account = self.debit_account_combo.currentText().strip()
        if not debit_account:
            QMessageBox.warning(self, "入力エラー", "借方勘定科目を入力してください。")
            return None
        
        # 金額
        amount_text = self.amount_edit.text().strip()
        try:
            amount = int(amount_text.replace(",", "")) if amount_text else 0
        except ValueError:
            QMessageBox.warning(self, "入力エラー", "金額は数値で入力してください。")
            return None
        
        # 貸方勘定科目（表示名から実際の科目名を抽出）
        credit_account_display = self.credit_account_combo.currentText().strip()
        if not credit_account_display:
            QMessageBox.warning(self, "入力エラー", "貸方勘定科目を入力してください。")
            return None
        # 表示名から実際の科目名を抽出（括弧前の部分）
        credit_account = credit_account_display.split(' (')[0] if ' (' in credit_account_display else credit_account_display
        
        # 摘要
        description = self.description_edit.text().strip()
        
        # インボイス番号
        invoice_number = self.invoice_number_edit.text().strip()
        
        # 税区分
        tax_category = self.tax_category_combo.currentText()
        
        # 画像URL
        image_url = self.image_url_edit.text().strip()
        
        return {
            "transaction_date": transaction_date,
            "debit_account": debit_account,
            "amount": amount,
            "credit_account": credit_account,
            "description": description,
            "invoice_number": invoice_number,
            "tax_category": tax_category,
            "image_url": image_url
        }
    
    def accept(self):
        """OKボタンが押されたときの処理"""
        data = self.get_data()
        if data:
            super().accept()
    
    def reject(self):
        """Cancelボタンが押されたときの処理"""
        super().reject()

