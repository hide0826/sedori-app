#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バーコードチェッカーウィジェット

バーコードリーダーから読み取ったJANコードを検証し、商品DBと照合して商品情報を表示する。
"""
from __future__ import annotations

import sys
import os
from typing import Optional, List, Dict, Any
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QGroupBox,
    QFormLayout, QMessageBox, QTextEdit, QHeaderView
)
from PySide6.QtGui import QFont

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from database.product_db import ProductDatabase


def compute_ean13_check_digit(jan_12: str) -> str:
    """EAN-13の先頭12桁からチェックデジットを計算する"""
    if not jan_12 or not jan_12.isdigit() or len(jan_12) != 12:
        return ""
    
    odd_sum = sum(int(jan_12[i]) for i in range(0, 12, 2))
    even_sum = sum(int(jan_12[i]) for i in range(1, 12, 2))
    
    total_sum = odd_sum + even_sum * 3
    check_digit = (10 - (total_sum % 10)) % 10
    return str(check_digit)


def validate_jan_code(jan: str) -> Dict[str, Any]:
    """
    JANコードを検証する
    
    Args:
        jan: JANコード（13桁）
    
    Returns:
        検証結果の辞書
        - is_valid: 有効かどうか
        - jan: 正規化されたJANコード
        - reason: エラーの理由（無効な場合）
    """
    # 数字のみ抽出
    normalized_jan = ''.join(c for c in jan if c.isdigit())
    
    if not normalized_jan:
        return {
            "is_valid": False,
            "jan": "",
            "reason": "数字が含まれていません"
        }
    
    if len(normalized_jan) != 13:
        return {
            "is_valid": False,
            "jan": normalized_jan,
            "reason": f"桁数が不正です（{len(normalized_jan)}桁）。13桁である必要があります。"
        }
    
    # チェックデジット計算
    check_digit = compute_ean13_check_digit(normalized_jan[:12])
    if normalized_jan[-1] != check_digit:
        return {
            "is_valid": False,
            "jan": normalized_jan,
            "reason": f"チェックデジット不一致（期待値: {check_digit}, 実際: {normalized_jan[-1]}）"
        }
    
    return {
        "is_valid": True,
        "jan": normalized_jan,
        "reason": ""
    }


class BarcodeCheckerWidget(QWidget):
    """バーコードチェッカーウィジェット"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.product_db = ProductDatabase()
        
        # バーコードリーダーからの入力を受け付けるためのタイマー
        self.input_timer = QTimer()
        self.input_timer.setSingleShot(True)
        self.input_timer.timeout.connect(self.process_barcode_input)
        self.barcode_buffer = ""
        
        self.setup_ui()
    
    def setup_ui(self):
        """UIのセットアップ"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 入力エリア
        input_group = QGroupBox("JANコード入力")
        input_layout = QVBoxLayout(input_group)
        
        # JANコード入力欄
        jan_layout = QHBoxLayout()
        jan_label = QLabel("JANコード:")
        jan_label.setMinimumWidth(80)
        self.jan_input = QLineEdit()
        self.jan_input.setPlaceholderText("バーコードリーダーでスキャン、または手入力")
        self.jan_input.returnPressed.connect(self.check_barcode)
        self.jan_input.textChanged.connect(self.on_jan_input_changed)
        # フォントサイズを大きく（バーコードリーダー用）
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self.jan_input.setFont(font)
        
        jan_layout.addWidget(jan_label)
        jan_layout.addWidget(self.jan_input)
        input_layout.addLayout(jan_layout)
        
        # 検証結果表示
        self.validation_label = QLabel("検証結果: -")
        self.validation_label.setStyleSheet("font-weight: bold; color: gray;")
        input_layout.addWidget(self.validation_label)
        
        # ボタン
        button_layout = QHBoxLayout()
        self.check_button = QPushButton("照合実行")
        self.check_button.setMinimumHeight(40)
        self.check_button.clicked.connect(self.check_barcode)
        self.clear_button = QPushButton("クリア")
        self.clear_button.clicked.connect(self.clear_input)
        button_layout.addWidget(self.check_button)
        button_layout.addWidget(self.clear_button)
        input_layout.addLayout(button_layout)
        
        layout.addWidget(input_group)
        
        # 商品情報表示エリア
        info_group = QGroupBox("商品情報")
        info_layout = QVBoxLayout(info_group)
        
        # 検索結果テーブル
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(10)
        self.result_table.setHorizontalHeaderLabels([
            "SKU", "商品名", "JAN", "ASIN", "仕入日", 
            "仕入価格", "数量", "店舗コード", "店舗名", "レシートID"
        ])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        info_layout.addWidget(self.result_table)
        
        # 統計情報
        self.stats_label = QLabel("検索結果: 0件")
        info_layout.addWidget(self.stats_label)
        
        layout.addWidget(info_group)
        
        # 詳細情報エリア
        detail_group = QGroupBox("詳細情報")
        detail_layout = QVBoxLayout(detail_group)
        
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        detail_layout.addWidget(self.detail_text)
        
        layout.addWidget(detail_group)
        
        # 初期フォーカスをJANコード入力欄に設定
        self.jan_input.setFocus()
    
    def on_jan_input_changed(self, text: str):
        """JANコード入力欄の変更時の処理（バーコードリーダー対応）"""
        # バーコードリーダーからの入力は非常に高速なので、
        # 一定時間入力がない場合に入力完了とみなす
        self.barcode_buffer = text
        self.input_timer.stop()
        self.input_timer.start(100)  # 100ms待機
    
    def process_barcode_input(self):
        """バーコードリーダーからの入力処理"""
        # バーコードリーダーから読み取った場合、自動的に照合実行
        if self.barcode_buffer:
            self.check_barcode()
    
    def check_barcode(self):
        """バーコードを検証して商品DBと照合"""
        jan_code = self.jan_input.text().strip()
        
        if not jan_code:
            QMessageBox.warning(self, "入力エラー", "JANコードを入力してください。")
            return
        
        # JANコード検証
        validation_result = validate_jan_code(jan_code)
        
        if validation_result["is_valid"]:
            self.validation_label.setText(f"検証結果: ✓ 有効なJANコード ({validation_result['jan']})")
            self.validation_label.setStyleSheet("font-weight: bold; color: green;")
        else:
            self.validation_label.setText(f"検証結果: ✗ {validation_result['reason']}")
            self.validation_label.setStyleSheet("font-weight: bold; color: red;")
            # 無効な場合でも商品DBを検索（検証が失敗してもDBに登録されている可能性がある）
        
        # 商品DBから検索
        normalized_jan = validation_result.get("jan", ''.join(c for c in jan_code if c.isdigit()))
        products = self.product_db.find_by_jan(normalized_jan)
        
        # 結果を表示
        self.display_results(products, validation_result)
    
    def display_results(self, products: List[Dict[str, Any]], validation_result: Dict[str, Any]):
        """検索結果を表示"""
        self.result_table.setRowCount(len(products))
        
        for row, product in enumerate(products):
            # SKU
            self.result_table.setItem(row, 0, QTableWidgetItem(str(product.get("sku", ""))))
            
            # 商品名
            product_name = str(product.get("product_name", ""))
            if len(product_name) > 50:
                product_name = product_name[:47] + "..."
            self.result_table.setItem(row, 1, QTableWidgetItem(product_name))
            
            # JAN
            self.result_table.setItem(row, 2, QTableWidgetItem(str(product.get("jan", ""))))
            
            # ASIN
            self.result_table.setItem(row, 3, QTableWidgetItem(str(product.get("asin", ""))))
            
            # 仕入日
            purchase_date = product.get("purchase_date", "")
            if purchase_date:
                # 日付形式を整形
                try:
                    dt = datetime.fromisoformat(purchase_date.replace('/', '-'))
                    purchase_date = dt.strftime("%Y/%m/%d")
                except:
                    pass
            self.result_table.setItem(row, 4, QTableWidgetItem(purchase_date))
            
            # 仕入価格
            price = product.get("purchase_price")
            price_str = f"{price:,}円" if price else ""
            self.result_table.setItem(row, 5, QTableWidgetItem(price_str))
            
            # 数量
            quantity = product.get("quantity")
            quantity_str = str(quantity) if quantity else ""
            self.result_table.setItem(row, 6, QTableWidgetItem(quantity_str))
            
            # 店舗コード
            self.result_table.setItem(row, 7, QTableWidgetItem(str(product.get("store_code", ""))))
            
            # 店舗名
            self.result_table.setItem(row, 8, QTableWidgetItem(str(product.get("store_name", ""))))
            
            # レシートID
            receipt_id = product.get("receipt_id")
            receipt_str = str(receipt_id) if receipt_id else ""
            self.result_table.setItem(row, 9, QTableWidgetItem(receipt_str))
        
        # 統計情報
        self.stats_label.setText(f"検索結果: {len(products)}件")
        
        # 詳細情報
        if products:
            detail_text = "=== 検索結果 ===\n"
            for i, product in enumerate(products, 1):
                detail_text += f"\n【商品 {i}】\n"
                detail_text += f"SKU: {product.get('sku', '')}\n"
                detail_text += f"商品名: {product.get('product_name', '')}\n"
                detail_text += f"JAN: {product.get('jan', '')}\n"
                detail_text += f"ASIN: {product.get('asin', '')}\n"
                detail_text += f"仕入日: {product.get('purchase_date', '')}\n"
                detail_text += f"仕入価格: {product.get('purchase_price', '')}円\n"
                detail_text += f"数量: {product.get('quantity', '')}\n"
                detail_text += f"店舗: {product.get('store_code', '')} - {product.get('store_name', '')}\n"
                
                # 保証情報
                warranty_until = product.get("warranty_until")
                if warranty_until:
                    detail_text += f"保証満了日: {warranty_until}\n"
                
                detail_text += "\n"
            self.detail_text.setPlainText(detail_text)
        else:
            self.detail_text.setPlainText("商品DBに登録されていないJANコードです。")
        
        # 検証結果が無効な場合、警告を表示
        if not validation_result["is_valid"] and products:
            QMessageBox.warning(
                self,
                "JANコード検証警告",
                f"JANコードの検証に失敗しましたが、商品DBに登録されている商品が見つかりました。\n\n"
                f"エラー: {validation_result['reason']}\n\n"
                f"見つかった商品: {len(products)}件"
            )
    
    def clear_input(self):
        """入力欄と結果をクリア"""
        self.jan_input.clear()
        self.validation_label.setText("検証結果: -")
        self.validation_label.setStyleSheet("font-weight: bold; color: gray;")
        self.result_table.setRowCount(0)
        self.stats_label.setText("検索結果: 0件")
        self.detail_text.clear()
        self.jan_input.setFocus()

