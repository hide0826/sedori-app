#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシートサービス

- 画像保存（所定ディレクトリ）
- OCR実行（OCRService）
- 金額/税/クーポン/支払額などを抽出
- ReceiptDatabase に保存
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional

from ..database.receipt_db import ReceiptDatabase
from ..services.ocr_service import OCRService


@dataclass
class ReceiptParseResult:
    purchase_date: Optional[str]
    store_name_raw: Optional[str]
    phone_number: Optional[str]
    subtotal: Optional[int]
    tax: Optional[int]
    discount_amount: Optional[int]
    total_amount: Optional[int]
    paid_amount: Optional[int]
    items_count: Optional[int]


class ReceiptService:
    def __init__(self, base_dir: Optional[str | Path] = None, tesseract_cmd: Optional[str] = None, gcv_credentials_path: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2] / "python" / "desktop" / "data" / "receipts"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db = ReceiptDatabase()
        self.ocr = OCRService(tesseract_cmd=tesseract_cmd, gcv_credentials_path=gcv_credentials_path)

    def save_image(self, src_path: str | Path) -> Path:
        src_path = Path(src_path)
        if not src_path.exists():
            raise FileNotFoundError(src_path)
        # ファイル名: receipt_YYYYmmdd_HHMMSS_uuid拡張子は元ファイルのまま
        import uuid, datetime, shutil
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = self.base_dir / f"receipt_{stamp}_{uuid.uuid4().hex}{src_path.suffix.lower()}"
        shutil.copy2(src_path, dst)
        return dst

    def parse_receipt_text(self, text: str) -> ReceiptParseResult:
        """OCRテキストからレシート情報を抽出（簡易版）"""
        # 日付（yyyy-mm-dd or yyyy/mm/dd or yyyy.mm.dd）
        m_date = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text)
        purchase_date = None
        if m_date:
            y, mo, d = m_date.groups()
            purchase_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

        # 店舗名（先頭行近辺の全角/半角混在文字を想定。ここでは1行目を仮採用）
        first_line = text.strip().splitlines()[0] if text.strip().splitlines() else ""
        store_name_raw = first_line[:64] if first_line else None

        # 金額類（日本語表記の代表パターン）
        def _find_int(patterns: list[str]) -> Optional[int]:
            for pat in patterns:
                m = re.search(pat, text, flags=re.IGNORECASE)
                if m:
                    val = _to_int(m.group(1))
                    if val is not None:
                        return val
            return None

        def _to_int(s: str | None) -> Optional[int]:
            if not s:
                return None
            # カンマ・空白を除去、全角→半角
            import unicodedata
            s = unicodedata.normalize('NFKC', s)
            s = s.replace(',', '').replace(' ', '')
            try:
                return int(round(float(s)))
            except Exception:
                return None

        subtotal = _find_int([r"小計\s*[:：]?\s*([0-9,\.]+)", r"税抜\s*[:：]?\s*([0-9,\.]+)"])  # 税抜/小計
        tax = _find_int([r"税\s*[:：]?\s*([0-9,\.]+)", r"消費税\s*[:：]?\s*([0-9,\.]+)"])
        discount_amount = _find_int([r"値引[き|き額]?\s*[:：-]?\s*([0-9,\.]+)", r"クーポン\s*[:：-]?\s*([0-9,\.]+)"])
        total_amount = _find_int([r"合計\s*[:：]?\s*([0-9,\.]+)", r"税込\s*[:：]?\s*([0-9,\.]+)"])
        paid_amount = _find_int([r"お預り\s*[:：]?\s*([0-9,\.]+)", r"お預かり\s*[:：]?\s*([0-9,\.]+)", r"支払\s*[:：]?\s*([0-9,\.]+)"])

        # 電話番号
        def _normalize_phone(raw: str | None) -> Optional[str]:
            if not raw:
                return None
            import unicodedata

            s = unicodedata.normalize('NFKC', raw)
            s = s.replace('ー', '-').replace('−', '-').replace('―', '-').replace('‐', '-')
            s = re.sub(r"[^0-9-]", "", s)
            # 連続した数字のみの場合は標準的なハイフン位置に整形
            if '-' not in s and len(s) in (10, 11):
                if len(s) == 10:
                    s = f"{s[0:2]}-{s[2:6]}-{s[6:]}"
                else:
                    s = f"{s[0:3]}-{s[3:7]}-{s[7:]}"
            parts = [p for p in s.split('-') if p]
            if len(parts) >= 3:
                return "-".join(parts[:3])
            return s or None

        phone_number = None
        phone_patterns = [
            r"(?:TEL|Tel|tel|電話|☎|ＴＥＬ)\s*[:：]?\s*(\d{2,4}[-−‐ー―]?\d{2,4}[-−‐ー―]?\d{3,4})",
            r"(\d{2,4}[-−‐ー―]?\d{2,4}[-−‐ー―]?\d{3,4})"
        ]
        for pat in phone_patterns:
            m = re.search(pat, text)
            if m:
                phone_number = _normalize_phone(m.group(1))
                if phone_number:
                    break

        # 商品点数
        items_count = _find_int([
            r"点数\s*[:：]?\s*([0-9０-９,\.]+)",
            r"品数\s*[:：]?\s*([0-9０-９,\.]+)",
            r"合計\s*品\s*[:：]?\s*([0-9０-９,\.]+)",
            r"([0-9０-９]+)\s*点",
            r"([0-9０-９]+)\s*品"
        ])

        return ReceiptParseResult(
            purchase_date=purchase_date,
            store_name_raw=store_name_raw,
            phone_number=phone_number,
            subtotal=subtotal,
            tax=tax,
            discount_amount=discount_amount,
            total_amount=total_amount,
            paid_amount=paid_amount,
            items_count=items_count,
        )

    def process_receipt(self, image_path: str | Path, currency: str = "JPY") -> Dict[str, Any]:
        """
        レシート画像を保存→OCR→抽出→DB保存まで行い、保存結果を返す
        """
        saved = self.save_image(image_path)
        ocr = self.ocr.extract_text(saved, use_preprocessing=True)
        parsed = self.parse_receipt_text(ocr.get("text") or "")

        receipt_data = {
            "file_path": str(saved),
            "purchase_date": parsed.purchase_date,
            "store_name_raw": parsed.store_name_raw,
            "phone_number": parsed.phone_number,
            "store_code": None,  # マッチング段階で確定
            "subtotal": parsed.subtotal,
            "tax": parsed.tax,
            "discount_amount": parsed.discount_amount,
            "total_amount": parsed.total_amount,
            "paid_amount": parsed.paid_amount,
            "items_count": parsed.items_count,
            "currency": currency,
            "ocr_provider": ocr.get("provider"),
            "ocr_text": ocr.get("text"),
        }
        receipt_id = self.db.insert_receipt(receipt_data)
        receipt_data["id"] = receipt_id
        return receipt_data
