#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
チェーン店コードマッピング編集ダイアログ
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QSpinBox, QCheckBox, QDialogButtonBox,
    QLabel, QGroupBox, QMessageBox
)
from PySide6.QtCore import Qt
from typing import Dict, Any, Tuple, Optional


class ChainMappingDialog(QDialog):
    """チェーン店コードマッピング編集ダイアログ"""
    
    def __init__(self, parent=None, mapping_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.mapping_data = mapping_data
        
        self.setWindowTitle("チェーン店コードマッピング編集" if mapping_data else "チェーン店コードマッピング追加")
        self.setModal(True)
        self.setup_ui()
        
        if mapping_data:
            self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        form_group = QGroupBox("マッピング情報")
        form_layout = QFormLayout(form_group)
        
        # チェーン店コード
        self.chain_code_edit = QLineEdit()
        self.chain_code_edit.setPlaceholderText("例：BO, WO, OF")
        self.chain_code_edit.setMaxLength(10)  # 最大10文字
        form_layout.addRow("チェーン店コード:", self.chain_code_edit)
        
        # 店舗名パターン（複数行テキストエディタ、1行1パターン）
        pattern_label = QLabel("店舗名パターン（1行に1つずつ入力）:")
        form_layout.addRow(pattern_label)
        
        self.patterns_edit = QTextEdit()
        self.patterns_edit.setPlaceholderText("例：\nBOOKOFF\nBOOK OFF\nブックオフ\n\nまたは\n\nhardoff\nハードオフ")
        self.patterns_edit.setMaximumHeight(150)
        form_layout.addRow(self.patterns_edit)
        
        # 優先度
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 100)
        self.priority_spin.setValue(0)
        self.priority_spin.setToolTip("数値が大きいほど優先されます。同じチェーン店に複数のパターンがある場合に使用します。")
        form_layout.addRow("優先度:", self.priority_spin)
        
        # 有効/無効
        self.is_active_check = QCheckBox("有効")
        self.is_active_check.setChecked(True)
        form_layout.addRow("状態:", self.is_active_check)
        
        layout.addWidget(form_group)
        
        # 説明ラベル
        info_label = QLabel(
            "店舗名パターンは、店舗名に含まれる文字列を指定します。\n"
            "複数のパターンを登録する場合は、1行に1つずつ入力してください。\n"
            "例：「BOOKOFF SUPER BAZAAR 14号千葉幕張店」という店舗名には「BOOKOFF」や「BOOK OFF」が含まれるため、それらのパターンを登録します。"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(info_label)
        
        # ボタン
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.mapping_data:
            return
        
        self.chain_code_edit.setText(self.mapping_data.get('chain_code', ''))
        
        patterns = self.mapping_data.get('chain_name_patterns', [])
        patterns_text = '\n'.join(patterns)
        self.patterns_edit.setPlainText(patterns_text)
        
        self.priority_spin.setValue(self.mapping_data.get('priority', 0))
        self.is_active_check.setChecked(bool(self.mapping_data.get('is_active', 1)))
    
    def get_data(self) -> Dict[str, Any]:
        """入力データを取得"""
        # パターンをリストに変換（空行を除去）
        patterns_text = self.patterns_edit.toPlainText()
        patterns = [p.strip() for p in patterns_text.split('\n') if p.strip()]
        
        return {
            'chain_code': self.chain_code_edit.text().strip().upper(),  # 大文字に変換
            'chain_name_patterns': patterns,
            'priority': self.priority_spin.value(),
            'is_active': 1 if self.is_active_check.isChecked() else 0
        }
    
    def validate(self) -> Tuple[bool, str]:
        """入力データの検証"""
        data = self.get_data()
        
        if not data['chain_code']:
            return False, "チェーン店コードを入力してください"
        
        if not data['chain_name_patterns']:
            return False, "店舗名パターンを1つ以上入力してください"
        
        # チェーン店コードの形式チェック（英数字のみ）
        import re
        if not re.match(r'^[A-Z0-9]+$', data['chain_code']):
            return False, "チェーン店コードは英数字のみ使用できます"
        
        return True, ""
    
    def accept(self):
        """OKボタンクリック時の処理"""
        is_valid, error_msg = self.validate()
        if not is_valid:
            QMessageBox.warning(self, "入力エラー", error_msg)
            return
        
        super().accept()

