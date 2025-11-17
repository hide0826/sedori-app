#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR結果の正規化ユーティリティ

OCRで抽出されたテキストを正規化して、読みやすく・解析しやすくする
"""
from __future__ import annotations

import re
import unicodedata
from typing import str as Str


def normalize_ocr_text(text: str) -> str:
    """
    OCR結果のテキストを正規化
    
    処理内容:
    1. NFKC正規化（全角→半角、合字展開）
    2. 連続スペース・改行の整理
    3. よくあるOCR誤認識パターンの修正
    4. 数字の結合（分解された数字を結合）
    
    Args:
        text: OCRで抽出された生テキスト
    
    Returns:
        正規化されたテキスト
    """
    if not text:
        return ""
    
    # 1. NFKC正規化（全角→半角、合字展開）
    normalized = unicodedata.normalize('NFKC', text)
    
    # 2. よくあるOCR誤認識パターンの修正
    # 「キ」が「キキキキ」と連続する問題を修正
    normalized = re.sub(r'キ{3,}', 'キ', normalized)
    normalized = re.sub(r'ま{3,}', 'ま', normalized)
    normalized = re.sub(r'談{2,}', '談', normalized)
    
    # 3. 連続スペース・改行の整理
    normalized = re.sub(r'[ \t]+', ' ', normalized)  # 連続スペースを1つに
    normalized = re.sub(r'\n{3,}', '\n\n', normalized)  # 3つ以上の改行を2つに
    
    # 4. 数字の結合（スペースで区切られた数字を結合）
    # 例: "2 0 2 5" → "2025"
    normalized = re.sub(r'(\d)\s+(\d)', r'\1\2', normalized)
    
    # 5. よくある誤認識パターンの修正
    replacements = {
        # 数字の誤認識
        'O': '0',  # 大文字Oを0に（文脈依存なので注意）
        'l': '1',  # 小文字lを1に（文脈依存なので注意）
        'I': '1',  # 大文字Iを1に（文脈依存なので注意）
        
        # 記号の誤認識
        'ー': '-',
        '−': '-',
        '―': '-',
        '‐': '-',
    }
    
    # 6. 行頭・行末の空白を削除
    lines = normalized.split('\n')
    cleaned_lines = [line.strip() for line in lines]
    normalized = '\n'.join(cleaned_lines)
    
    # 7. 空行を削除（2つ以上の連続空行を1つに）
    normalized = re.sub(r'\n\s*\n\s*\n+', '\n\n', normalized)
    
    return normalized.strip()


def extract_numbers(text: str) -> list[int]:
    """
    テキストから数字を抽出
    
    Args:
        text: テキスト
    
    Returns:
        抽出された数字のリスト
    """
    if not text:
        return []
    
    # 正規化
    normalized = normalize_ocr_text(text)
    
    # 数字パターンを検索（カンマ区切りも対応）
    numbers = []
    patterns = [
        r'\d{1,3}(?:,\d{3})*',  # カンマ区切り数字（例: 1,234）
        r'\d+',  # 通常の数字
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, normalized)
        for match in matches:
            try:
                num = int(match.replace(',', ''))
                numbers.append(num)
            except ValueError:
                continue
    
    return numbers


def extract_date(text: str) -> str | None:
    """
    テキストから日付を抽出（yyyy-mm-dd形式）
    
    Args:
        text: テキスト
    
    Returns:
        日付文字列（yyyy-mm-dd形式）、見つからない場合はNone
    """
    if not text:
        return None
    
    # 正規化
    normalized = normalize_ocr_text(text)
    
    # 日付パターンを検索
    patterns = [
        r'(20\d{2})[./-](\d{1,2})[./-](\d{1,2})',  # yyyy/mm/dd形式
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',  # yyyy年mm月dd日形式
    ]
    
    for pattern in patterns:
        m = re.search(pattern, normalized)
        if m:
            y, mo, d = m.groups()
            try:
                return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            except ValueError:
                continue
    
    return None


def extract_phone_number(text: str) -> str | None:
    """
    テキストから電話番号を抽出
    
    Args:
        text: テキスト
    
    Returns:
        電話番号（ハイフン区切り）、見つからない場合はNone
    """
    if not text:
        return None
    
    # 正規化
    normalized = normalize_ocr_text(text)
    
    # 電話番号パターンを検索
    patterns = [
        r'(?:TEL|Tel|tel|電話|☎|ＴＥＬ)\s*[:：]?\s*(\d{2,4}[-−‐ー―]?\d{2,4}[-−‐ー―]?\d{3,4})',
        r'(\d{2,4}[-−‐ー―]?\d{2,4}[-−‐ー―]?\d{3,4})',
    ]
    
    for pattern in patterns:
        m = re.search(pattern, normalized)
        if m:
            phone = m.group(1)
            # ハイフンを統一
            phone = re.sub(r'[-−‐ー―]', '-', phone)
            # 数字のみの場合はハイフンを追加
            if '-' not in phone:
                if len(phone) == 10:
                    phone = f"{phone[0:2]}-{phone[2:6]}-{phone[6:]}"
                elif len(phone) == 11:
                    phone = f"{phone[0:3]}-{phone[3:7]}-{phone[7:]}"
            return phone
    
    return None

