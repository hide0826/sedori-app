#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗編集・カスタムフィールド編集ダイアログ。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QLabel, QGroupBox, QFileDialog, QTextEdit,
    QComboBox, QCheckBox, QDialogButtonBox, QTabWidget,
    QProgressDialog, QApplication, QListWidget, QListWidgetItem,
    QSplitter, QDoubleSpinBox, QAbstractItemView, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QSettings
from PySide6.QtGui import QColor, QDrag
from typing import Tuple, List, Dict, Any, Optional
import sys
import os
import re
import webbrowser

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from utils.excel_importer import ExcelImporter
from utils.ui_utils import reapply_table_column_widths

from .support import (
    get_store_info_from_google,
    recover_store_info_with_japanese,
    normalize_stored_japanese_address,
)


class StoreEditDialog(QDialog):
    """店舗編集ダイアログ"""
    
    def __init__(self, parent=None, store_data=None, custom_fields_def=None, initial_route_name: str = None):
        super().__init__(parent)
        self.store_data = store_data
        self.custom_fields_def = custom_fields_def or []
        self.db = StoreDatabase()
        self.initial_route_name = initial_route_name
        # カスタムフィールド編集ウィジェットのマップは必ず初期化しておく
        self.custom_field_edits = {}
        self._latitude: Optional[float] = None
        self._longitude: Optional[float] = None
        
        self.setWindowTitle("店舗編集" if store_data else "店舗追加")
        self.setModal(True)
        self.setup_ui()
        
        if store_data:
            self.load_data()
        else:
            # 新規追加時に初期ルートが与えられていれば自動入力
            if self.initial_route_name:
                idx = self.affiliated_route_name_combo.findText(self.initial_route_name)
                if idx >= 0:
                    self.affiliated_route_name_combo.setCurrentIndex(idx)
                else:
                    self.affiliated_route_name_combo.setCurrentText(self.initial_route_name)
                # ルートコードを自動設定（店舗コードは店舗名入力時に自動生成）
                self.on_route_name_changed(self.initial_route_name)
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        # 基本情報フォーム
        form_group = QGroupBox("基本情報")
        form_layout = QFormLayout(form_group)
        
        # 所属ルート名: 編集可能なQComboBox
        self.affiliated_route_name_combo = QComboBox()
        self.affiliated_route_name_combo.setEditable(True)  # 編集可能に設定
        self.affiliated_route_name_combo.setInsertPolicy(QComboBox.NoInsert)  # 新規入力時は追加しない
        # 既存ルート名一覧をロード
        self.load_route_names()
        # ルート選択変更時のシグナル接続
        self.affiliated_route_name_combo.currentTextChanged.connect(self.on_route_name_changed)
        # 編集時のシグナル接続（テキスト入力時）
        self.affiliated_route_name_combo.lineEdit().textChanged.connect(self.on_route_name_text_changed)
        form_layout.addRow("所属ルート名:", self.affiliated_route_name_combo)
        
        self.route_code_edit = QLineEdit()
        self.route_code_edit.setReadOnly(True)  # 自動挿入なので読み取り専用
        form_layout.addRow("ルートコード:", self.route_code_edit)
        
        self.store_code_edit = QComboBox()
        self.store_code_edit.setEditable(True)
        self.store_code_edit.setInsertPolicy(QComboBox.NoInsert)
        self.store_code_edit.setToolTip(
            "店舗名入力で候補を表示します。複数チェーンが一致する場合はプルダウンから選択してください。"
        )
        le = self.store_code_edit.lineEdit()
        if le is not None:
            le.setPlaceholderText(
                "例: HA（確定で次番号）／店舗名入力で候補（KO-03 (コーナン) 等）"
            )
            le.editingFinished.connect(self._on_store_code_editing_finished)
        form_layout.addRow("店舗コード:", self.store_code_edit)
        
        self.store_name_edit = QLineEdit()
        self.store_name_edit.setPlaceholderText("必須項目")
        # 店舗名変更時に仕入れ先コードを自動生成
        self.store_name_edit.textChanged.connect(self.on_store_name_changed)
        form_layout.addRow("店舗名:", self.store_name_edit)

        # 住所・電話番号の追加
        self.address_edit = QLineEdit()
        form_layout.addRow("住所:", self.address_edit)
        self.phone_edit = QLineEdit()
        form_layout.addRow("電話番号:", self.phone_edit)
        
        layout.addWidget(form_group)
        
        # カスタムフィールドフォーム
        if self.custom_fields_def:
            custom_group = QGroupBox("カスタムフィールド")
            custom_layout = QFormLayout(custom_group)
            for field_def in self.custom_fields_def:
                if field_def.get('is_active', 1):
                    field_name = field_def['field_name']
                    display_name = field_def['display_name']
                    field_type = field_def['field_type']
                    
                    if field_type in ['TEXT', 'DATE']:
                        edit = QLineEdit()
                    elif field_type == 'INTEGER':
                        edit = QLineEdit()
                        edit.setPlaceholderText("数値")
                    elif field_type == 'REAL':
                        edit = QLineEdit()
                        edit.setPlaceholderText("小数")
                    else:
                        edit = QLineEdit()
                    
                    custom_layout.addRow(f"{display_name}:", edit)
                    self.custom_field_edits[field_name] = edit
            
            layout.addWidget(custom_group)
        
        # 情報取得ボタン（Google Map APIから住所・電話番号を取得）
        info_button_layout = QHBoxLayout()
        info_button_layout.addStretch()
        self.fetch_info_btn = QPushButton("情報取得")
        self.fetch_info_btn.setToolTip(
            "店舗名からGoogle Map APIで住所・電話番号・緯度経度を取得します"
        )
        self.fetch_info_btn.clicked.connect(self.fetch_store_info)
        info_button_layout.addWidget(self.fetch_info_btn)
        layout.addLayout(info_button_layout)
        
        # ボタン
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def fetch_store_info(self):
        """Google Map APIから店舗情報（住所・電話）を取得して入力欄に反映"""
        # Google Mapsサービスが利用できない場合
        if get_store_info_from_google is None:
            QMessageBox.warning(
                self,
                "エラー",
                "Google Mapsサービスモジュールが読み込めませんでした。\n"
                "googlemapsライブラリがインストールされているか確認してください。"
            )
            return
        
        store_name = (self.store_name_edit.text() or "").strip()
        if not store_name:
            QMessageBox.warning(self, "警告", "まず「店舗名」を入力してください。")
            return
        
        # 既に住所や電話番号が入っている場合は上書き確認
        current_address = (self.address_edit.text() or "").strip()
        current_phone = (self.phone_edit.text() or "").strip()
        if current_address or current_phone:
            reply = QMessageBox.question(
                self,
                "確認",
                "既に住所または電話番号が入力されています。\n"
                "Google Map から取得した情報で上書きしてよろしいですか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        
        try:
            info = get_store_info_from_google(store_name, language_code='ja')
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"店舗情報の取得に失敗しました:\n{str(e)}")
            return
        
        if not info:
            QMessageBox.information(
                self,
                "情報",
                "一致する店舗情報が見つかりませんでした。\n"
                "店舗名を少し変えて再度お試しください。"
            )
            return
        
        # 情報を反映（取得できた項目のみ・住所は日本式に統一済み）
        address = info.get("address") or ""
        if normalize_stored_japanese_address and address:
            address = normalize_stored_japanese_address(address)
        phone = info.get("phone") or ""
        if address:
            self.address_edit.setText(address)
        if phone:
            self.phone_edit.setText(phone)
        lat = info.get("latitude")
        lng = info.get("longitude")
        if lat is not None and lng is not None:
            self._latitude = lat
            self._longitude = lng
    
    def load_route_names(self):
        """既存のルート名一覧をロード"""
        route_names = self.db.get_route_names()
        self.affiliated_route_name_combo.clear()
        self.affiliated_route_name_combo.addItems(route_names)
    
    def on_route_name_changed(self, route_name: str):
        """ルート名が変更された時（プルダウン選択時）"""
        if not route_name:
            self.route_code_edit.clear()
            # 店舗コードは店舗名が入力されるまで空のままにする
            if not self.store_name_edit.text().strip():
                self._clear_store_code_suggestions()
            return
        
        # ルートコードを自動挿入（未登録ルートは保存時に採番）
        route_code = self.db.get_route_code_by_name(route_name)
        if route_code and not StoreDatabase.is_invalid_route_code(route_code, route_name):
            self.route_code_edit.setText(route_code)
        elif route_code:
            repaired = self.db.ensure_route_code(route_name)
            self.route_code_edit.setText(repaired)
        else:
            self.route_code_edit.clear()
        
        # 店舗名から店舗コード候補を更新（店舗名が入力されている場合のみ）
        store_name = self.store_name_edit.text().strip()
        if store_name:
            self._refresh_store_code_suggestions(
                store_name,
                auto_pick_first=not bool(self._get_store_code_text()),
            )
        # 店舗名がない場合は店舗コードを空のままにする
        # （店舗名入力時にon_store_name_changedで自動生成される）
    
    def on_route_name_text_changed(self, text: str):
        """ルート名が入力された時（テキスト編集時）"""
        # 既存ルート名と一致するかチェック
        current_index = self.affiliated_route_name_combo.findText(text)
        if current_index >= 0:
            # 既存ルートが見つかった場合は選択状態にする
            self.affiliated_route_name_combo.setCurrentIndex(current_index)
    
    def on_store_name_changed(self, store_name: str):
        """店舗名が変更された時に店舗コード候補を更新（新規追加時のみ）"""
        if self.store_data:
            return
        name = (store_name or "").strip()
        if not name:
            self._clear_store_code_suggestions()
            return
        self._refresh_store_code_suggestions(name, auto_pick_first=True)

    def _get_store_code_text(self) -> str:
        """店舗コード欄の値（プルダウン選択時は実コード、手入力時はそのまま）"""
        le = self.store_code_edit.lineEdit()
        text = (le.text() if le else "").strip() or (
            self.store_code_edit.currentText() or ""
        ).strip()
        idx = self.store_code_edit.currentIndex()
        if idx >= 0:
            data = self.store_code_edit.itemData(idx)
            item_text = (self.store_code_edit.itemText(idx) or "").strip()
            code = str(data).strip() if data else ""
            if code and (text == item_text or text == code):
                return code
        return text

    def _set_store_code_text(self, code: str) -> None:
        text = (code or "").strip()
        if not text:
            self.store_code_edit.setCurrentText("")
            return
        idx = self.store_code_edit.findData(text)
        if idx >= 0:
            self.store_code_edit.setCurrentIndex(idx)
        else:
            self.store_code_edit.setCurrentText(text)

    def _clear_store_code_suggestions(self) -> None:
        self.store_code_edit.blockSignals(True)
        self.store_code_edit.clear()
        self.store_code_edit.setCurrentText("")
        self.store_code_edit.blockSignals(False)

    def _refresh_store_code_suggestions(
        self, store_name: str, *, auto_pick_first: bool = False
    ) -> None:
        """店舗名に一致するチェーンごとの次番号をプルダウン候補に反映する。"""
        suggestions = self.db.get_store_code_suggestions_for_store_name(store_name)
        current_code = self._get_store_code_text()
        valid_codes = {s["store_code"] for s in suggestions}

        self.store_code_edit.blockSignals(True)
        self.store_code_edit.clear()
        for s in suggestions:
            self.store_code_edit.addItem(s["label"], s["store_code"])

        if current_code and current_code in valid_codes:
            self._set_store_code_text(current_code)
        elif auto_pick_first and suggestions and not current_code:
            self._set_store_code_text(suggestions[0]["store_code"])
        elif current_code:
            self._set_store_code_text(current_code)
        elif not suggestions:
            self.store_code_edit.setCurrentText("")
        self.store_code_edit.blockSignals(False)

    def _on_store_code_editing_finished(self):
        """プレフィックスのみ（例: HA, HA-）のとき、確定で次の空き番号を付与する"""
        raw = self._get_store_code_text().upper()
        if not raw:
            return
        # すでに PREFIX-数字 の完全形なら変更しない
        if re.match(r"^[A-Z0-9]+-\d+$", raw):
            return
        m = re.match(r"^([A-Z0-9]{2,10})-?$", raw)
        if not m:
            return
        prefix = m.group(1)
        next_code = self.db.get_next_store_code_for_prefix(prefix)
        if not next_code or next_code == raw:
            return
        self.store_code_edit.blockSignals(True)
        self._set_store_code_text(next_code)
        self.store_code_edit.blockSignals(False)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.store_data:
            return
        
        route_name = self.store_data.get('affiliated_route_name', '')
        if route_name:
            # 既存ルート名がリストにあるかチェック
            index = self.affiliated_route_name_combo.findText(route_name)
            if index >= 0:
                self.affiliated_route_name_combo.setCurrentIndex(index)
            else:
                # リストにない場合は現在のテキストとして設定
                self.affiliated_route_name_combo.setCurrentText(route_name)
        else:
            self.affiliated_route_name_combo.setCurrentText('')
        
        self.route_code_edit.setText(self.store_data.get('route_code', ''))
        # store_codeを優先し、なければsupplier_codeをフォールバック（互換性のため）
        store_code = self.store_data.get('store_code', '') or self.store_data.get('supplier_code', '')
        self._set_store_code_text(store_code)
        self.store_name_edit.setText(self.store_data.get('store_name', ''))
        self.address_edit.setText(self.store_data.get('address', ''))
        self.phone_edit.setText(self.store_data.get('phone', ''))
        self._latitude = self._coerce_coordinate(self.store_data.get('latitude'))
        self._longitude = self._coerce_coordinate(self.store_data.get('longitude'))
        
        # カスタムフィールドの読み込み
        custom_fields = self.store_data.get('custom_fields', {})
        # self.custom_field_edits は空の可能性があるため安全に処理
        if hasattr(self, 'custom_field_edits') and isinstance(self.custom_field_edits, dict):
            for field_name, edit in self.custom_field_edits.items():
                value = custom_fields.get(field_name, '')
                edit.setText(str(value))
    
    @staticmethod
    def _coerce_coordinate(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    
    def get_data(self) -> dict:
        """入力データを取得"""
        # 所属ルート名はQComboBoxから取得（編集可能なので現在のテキスト）
        route_name = self.affiliated_route_name_combo.currentText().strip()
        route_code = self.route_code_edit.text().strip()
        if route_name and (
            not route_code or StoreDatabase.is_invalid_route_code(route_code, route_name)
        ):
            route_code = self.db.ensure_route_code(route_name)
        
        store_code = self._get_store_code_text()
        data = {
            'affiliated_route_name': route_name,
            'route_code': route_code,
            'store_code': store_code if store_code else None,
            'store_name': self.store_name_edit.text().strip(),
            'address': self.address_edit.text().strip(),
            'phone': self.phone_edit.text().strip(),
            'supplier_code': None,  # 互換性のためNULL（store_codeを使用）
            'custom_fields': {}
        }
        
        # カスタムフィールドの取得
        for field_name, edit in self.custom_field_edits.items():
            data['custom_fields'][field_name] = edit.text().strip()

        if self._latitude is not None and self._longitude is not None:
            data['latitude'] = self._latitude
            data['longitude'] = self._longitude
        
        return data
    
    def validate(self) -> Tuple[bool, str]:
        """入力データの検証"""
        data = self.get_data()
        
        # 店舗名は必須
        if not data['store_name']:
            return False, "店舗名を入力してください"
        
        # 店舗コードの重複チェック
        store_code = data['store_code']
        if store_code:
            exclude_id = self.store_data.get('id') if self.store_data else None
            if self.db.check_store_code_exists(store_code, exclude_id):
                return False, f"店舗コード '{store_code}' は既に使用されています"
        
        return True, ""


class CustomFieldEditDialog(QDialog):
    """カスタムフィールド編集ダイアログ"""
    
    def __init__(self, parent=None, field_data=None):
        super().__init__(parent)
        self.field_data = field_data
        
        self.setWindowTitle("カスタムフィールド編集" if field_data else "カスタムフィールド追加")
        self.setModal(True)
        self.setup_ui()
        
        if field_data:
            self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        self.field_name_edit = QLineEdit()
        self.field_name_edit.setPlaceholderText("field_name（英数字、アンダースコア）")
        form_layout.addRow("フィールド名:", self.field_name_edit)
        
        self.display_name_edit = QLineEdit()
        self.display_name_edit.setPlaceholderText("表示名（日本語OK）")
        form_layout.addRow("表示名:", self.display_name_edit)
        
        self.field_type_combo = QComboBox()
        self.field_type_combo.addItems(["TEXT", "INTEGER", "REAL", "DATE"])
        form_layout.addRow("フィールドタイプ:", self.field_type_combo)
        
        self.is_active_check = QCheckBox("有効")
        self.is_active_check.setChecked(True)
        form_layout.addRow("状態:", self.is_active_check)
        
        layout.addLayout(form_layout)
        
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.field_data:
            return
        
        self.field_name_edit.setText(self.field_data.get('field_name', ''))
        self.field_name_edit.setEnabled(False)  # フィールド名は変更不可
        self.display_name_edit.setText(self.field_data.get('display_name', ''))
        self.field_type_combo.setCurrentText(self.field_data.get('field_type', 'TEXT'))
        self.is_active_check.setChecked(bool(self.field_data.get('is_active', 1)))
    
    def get_data(self) -> dict:
        """入力データを取得"""
        return {
            'field_name': self.field_name_edit.text().strip(),
            'display_name': self.display_name_edit.text().strip(),
            'field_type': self.field_type_combo.currentText(),
            'is_active': 1 if self.is_active_check.isChecked() else 0
        }
    
    def validate(self) -> Tuple[bool, str]:
        """入力データの検証"""
        data = self.get_data()
        
        if not data['field_name']:
            return False, "フィールド名を入力してください"
        
        if not data['display_name']:
            return False, "表示名を入力してください"
        
        # フィールド名の形式チェック（英数字とアンダースコアのみ）
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', data['field_name']):
            return False, "フィールド名は英数字とアンダースコアのみ使用できます"
        
        return True, ""
