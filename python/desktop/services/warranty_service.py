#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保証書サービス

- 画像保存（所定ディレクトリ）
- OCR実行（商品名抽出）
- productsテーブルからSKU/JAN/ASIN/商品名でマッチング
- 保証情報をproductsに更新（保証期間、保証書画像パスなど）
- 手動修正を学習（ledger_category_dict/ledger_id_mapを使用）
"""
from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import unicodedata

from ..database.product_db import ProductDatabase
from ..database.warranty_db import WarrantyDatabase
from ..database.ledger_db import LedgerDatabase
from ..services.ocr_service import OCRService


class WarrantyService:
    def __init__(
        self,
        base_dir: Optional[str | Path] = None,
        tesseract_cmd: Optional[str] = None,
        gcv_credentials_path: Optional[str] = None,
        default_warranty_days: int = 365,  # デフォルト1年
    ):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2] / "python" / "desktop" / "data" / "warranties"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.default_warranty_days = default_warranty_days
        self.product_db = ProductDatabase()
        self.warranty_db = WarrantyDatabase()
        self.ledger_db = LedgerDatabase()
        self.ocr = OCRService(tesseract_cmd=tesseract_cmd, gcv_credentials_path=gcv_credentials_path)

    def save_image(self, src_path: str | Path) -> Path:
        """保証書画像を保存"""
        src_path = Path(src_path)
        if not src_path.exists():
            raise FileNotFoundError(src_path)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = self.base_dir / f"warranty_{stamp}_{uuid.uuid4().hex}{src_path.suffix.lower()}"
        shutil.copy2(src_path, dst)
        return dst

    def extract_product_name(self, text: str) -> Optional[str]:
        """OCRテキストから商品名を抽出（簡易版）"""
        if not text:
            return None
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # 先頭数行から商品名らしい行を探す
        # 長すぎる行や短すぎる行を除外
        for line in lines[:10]:
            normalized = unicodedata.normalize('NFKC', line)
            if 5 <= len(normalized) <= 100:
                # 数字のみや記号のみは除外
                if re.search(r'[^\d\s\W]', normalized):
                    return normalized
        return None

    def find_matching_products(self, product_name: str) -> List[Dict[str, Any]]:
        """
        productsテーブルから商品名でマッチング候補を返す
        優先順位: SKU（直接指定） > JAN > ASIN > 商品名部分一致
        """
        if not product_name:
            return []
        
        product_name = unicodedata.normalize('NFKC', product_name.strip())
        candidates = []
        
        # 商品名部分一致で検索
        all_products = self.product_db.list_by_date()
        name_lower = product_name.lower()
        
        for prod in all_products:
            prod_name = (prod.get('product_name') or '').lower()
            if prod_name and name_lower in prod_name:
                candidates.append(prod)
            # JAN/ASINが一致する場合も追加（将来的に拡張）
            # if prod.get('jan') == product_name or prod.get('asin') == product_name:
            #     candidates.append(prod)
        
        return candidates

    def process_warranty(
        self,
        image_path: str | Path,
        sku: Optional[str] = None,
        warranty_period_days: Optional[int] = None,
        product_name_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        保証書画像を処理: 保存→OCR→商品名抽出→マッチング→products更新
        
        Args:
            image_path: 保証書画像パス
            sku: SKUが既に分かっている場合（手動指定）
            warranty_period_days: 保証期間（日数）。Noneの場合はデフォルト値を使用
            product_name_override: 商品名を手動で指定する場合
        
        Returns:
            処理結果辞書
        """
        saved = self.save_image(image_path)
        ocr_result = self.ocr.extract_text(saved, use_preprocessing=True)
        ocr_text = ocr_result.get("text") or ""
        
        # 商品名抽出
        if product_name_override:
            product_name = product_name_override
        else:
            product_name = self.extract_product_name(ocr_text)
        
        # SKUが指定されていれば直接更新
        if sku:
            product = self.product_db.get_by_sku(sku)
            if not product:
                raise ValueError(f"Product with SKU {sku} not found")
            matched_sku = sku
            confidence = 1.0
        else:
            # マッチング候補を探す
            candidates = self.find_matching_products(product_name) if product_name else []
            if not candidates:
                # マッチしない場合はwarrantiesテーブルに保存のみ
                warranty_data = {
                    "file_path": str(saved),
                    "ocr_product_name": product_name,
                    "sku": None,
                    "matched_confidence": None,
                    "notes": "No matching product found",
                }
                warranty_id = self.warranty_db.insert_warranty(warranty_data)
                return {
                    "warranty_id": warranty_id,
                    "file_path": str(saved),
                    "product_name": product_name,
                    "matched_sku": None,
                    "confidence": None,
                    "status": "no_match",
                }
            
            # 最初の候補を使用（将来的にUIで選択可能にする）
            matched_product = candidates[0]
            matched_sku = matched_product.get('sku')
            confidence = 0.8 if len(candidates) == 1 else 0.6  # 簡易的な信頼度
        
        # 保証期間計算
        if warranty_period_days is None:
            warranty_period_days = self.default_warranty_days
        warranty_until = (datetime.now() + timedelta(days=warranty_period_days)).strftime("%Y-%m-%d")
        
        # productsテーブルに保証情報を更新
        self.product_db.update_warranty_info(
            matched_sku,
            warranty_period_days=warranty_period_days,
            warranty_until=warranty_until,
            warranty_product_name=product_name,
            warranty_image_path=str(saved),
        )
        
        # warrantiesテーブルに保存
        warranty_data = {
            "file_path": str(saved),
            "ocr_product_name": product_name,
            "sku": matched_sku,
            "matched_confidence": confidence,
            "notes": None,
        }
        warranty_id = self.warranty_db.insert_warranty(warranty_data)
        
        # 学習: 商品名→品目のマッピング（ledger_dbを使用）
        # ここでは商品名のみで学習（将来的に品目も学習可能）
        # self.ledger_db.learn_category_from_edit(product_name, category, identifier)
        
        return {
            "warranty_id": warranty_id,
            "file_path": str(saved),
            "product_name": product_name,
            "matched_sku": matched_sku,
            "confidence": confidence,
            "warranty_period_days": warranty_period_days,
            "warranty_until": warranty_until,
            "status": "matched",
        }

    def learn_correction(self, warranty_id: int, correct_sku: str) -> bool:
        """手動修正を学習（将来的にledger_dbの学習機能と統合）"""
        warranty = self.warranty_db.get_warranty(warranty_id)
        if not warranty:
            return False
        
        product_name = warranty.get('ocr_product_name')
        if product_name:
            # 商品名→SKUの直接マッピングを学習（ledger_id_map的な仕組み）
            # 現時点ではwarranty_dbに保存のみ
            self.warranty_db.update_warranty(warranty_id, {"sku": correct_sku, "matched_confidence": 1.0})
            
            # productsテーブルも更新
            product = self.product_db.get_by_sku(correct_sku)
            if product:
                warranty_data = warranty
                self.product_db.update_warranty_info(
                    correct_sku,
                    warranty_product_name=product_name,
                    warranty_image_path=warranty_data.get('file_path'),
                )
            return True
        return False

